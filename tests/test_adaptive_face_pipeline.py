"""Safety and integration regressions; no model downloads or identity-based selection."""
from unittest.mock import Mock, patch
import numpy as np
import pytest

from src.face import adaptive_pipeline as ap
from src.recognition.target_matcher import TargetManager, TargetMatcher, BestFaceState


def unit(index=0):
    x = np.zeros(512, np.float32)
    x[index] = 1
    return x


@pytest.fixture
def inputs():
    roi = np.random.default_rng(4).integers(0, 255, (80, 80, 3), dtype=np.uint8)
    box = np.array([12, 15, 48, 60], np.float32)
    kps = np.array([[21,25],[39,25],[30,38],[24,49],[36,49]], np.float32)
    return roi, box, kps


def run(inputs, **kw):
    roi, box, kps = inputs
    pipeline = ap.AdaptiveFacePipeline(Mock(embed_aligned_face=Mock(return_value=unit())))
    candidate = pipeline.process(roi, box, .9, kps, camera_id='A', track_id=1, frame_id=4, timestamp=1.)
    return pipeline, candidate


def test_normal_uses_raw(inputs):
    pipeline, c = run(inputs)
    assert c['representation_type'] == 'RAW'
    assert pipeline.counters['homography_attempts'] == 0


def overhead(inputs):
    roi, box, kps = inputs
    kps = kps.copy(); kps[3:,1] = 43
    return roi, box, kps


def test_overhead_uses_rectified_once(inputs):
    pipeline, c = run(overhead(inputs))
    assert c['representation_type'] == 'RECTIFIED'
    assert pipeline.embedder.embed_aligned_face.call_count == 1


@pytest.mark.parametrize('failure', ['nan', 'collapsed', 'missing', 'inverted', 'invalid_roi'])
def test_invalid_geometry_returns_raw_fallback(inputs, failure):
    roi, _, kps = inputs
    kps = kps.copy()
    if failure == 'nan': kps[0,0] = np.nan
    elif failure == 'collapsed': kps[:] = 25
    elif failure == 'missing': kps = None
    elif failure == 'inverted': kps[[0,1]] = kps[[1,0]]
    elif failure == 'invalid_roi': roi = roi[:0]
    raw, points, safe, reason = ap.apply_homography_with_safety(roi, kps)
    assert not safe and reason != 'SAFE'
    assert raw is roi and points is kps


def test_out_of_bounds_falls_back_without_losing_raw(inputs):
    roi, box, kps = overhead(inputs)
    with patch.object(ap, 'apply_r2_homography', return_value=(roi, kps+1000)):
        _, c = run((roi, box, kps))
    assert c['representation_type'] == 'RAW_FALLBACK'
    assert c['fallback_reason'] == 'MAPPED_LANDMARKS_OUT_OF_BOUNDS'
    assert np.isfinite(c['embedding']).all()


@pytest.mark.parametrize('matrix', [np.zeros((3,3)), np.full((3,3),np.nan)])
def test_singular_or_nonfinite_transform_falls_back(inputs, matrix):
    with patch.object(ap.cv2, 'getPerspectiveTransform', return_value=matrix):
        # alpha=1 tests the singular matrix directly.
        raw, kps, safe, _ = ap.apply_homography_with_safety(inputs[0], inputs[2], alpha=1)
    assert not safe and raw is inputs[0]


def test_alignment_failure_recovers_raw(inputs):
    from insightface.utils import face_align
    real_align = face_align.norm_crop
    with patch.object(face_align, 'norm_crop', side_effect=[real_align(inputs[0], landmark=inputs[2]), ValueError('test')]):
        _, c = run(overhead(inputs))
    assert c['representation_type'] == 'RAW_FALLBACK'


def candidate(frame, camera='A', track=1, quality=80, index=0):
    return dict(frame_id=frame,camera_id=camera,track_id=track,face_width=36,
                overhead_distortion_score=20,quality_score=quality,composite_quality=quality,
                embedding=unit(index),representation_type='RAW')


def test_duplicate_representation_first_wins():
    buffer = ap.CandidateBuffer('A',1)
    raw = candidate(4); rect = {**raw, 'representation_type':'RECTIFIED'}
    assert buffer.add(raw) and not buffer.add(rect)
    assert buffer.selected() == [raw]
    assert len(ap.select_candidates([raw,rect])) == 1


def test_top3_quality_weights_spacing_and_norm():
    rows = [candidate(1,index=0),candidate(2,quality=100,index=1),
            candidate(4,quality=90,index=2),candidate(6,quality=70,index=3)]
    selected = ap.select_candidates(rows)
    assert [c['frame_id'] for c in selected] == [2,4,6]
    fused = ap.fuse_candidates(selected)
    expected = 100*unit(1)+90*unit(2)+70*unit(3)
    expected /= np.linalg.norm(expected)
    np.testing.assert_allclose(fused,expected,atol=1e-7)
    assert np.linalg.norm(fused) == pytest.approx(1.)


@pytest.mark.parametrize('count',[1,2])
def test_partial_pool_does_not_wait_for_three(count):
    rows = [candidate(2*i) for i in range(count)]
    assert ap.fuse_candidates(ap.select_candidates(rows)) is not None


@pytest.mark.parametrize('camera,track',[('B',1),('A',2)])
def test_tracks_and_cameras_cannot_mix(camera,track):
    buffer = ap.CandidateBuffer('A',1)
    buffer.add(candidate(1))
    with pytest.raises(ValueError,match='MIXED_SOURCE_TRACK'):
        buffer.add(candidate(3,camera,track))
    with pytest.raises(ValueError,match='MIXED_SOURCE_TRACK'):
        ap.fuse_candidates([candidate(1),candidate(3,camera,track)])


def test_bounds_gates_and_no_spacing_relaxation():
    buffer = ap.CandidateBuffer('A',1,capacity=4)
    for frame in range(10): buffer.add(candidate(frame))
    assert len(buffer.candidates) == 4
    assert len(ap.select_candidates([candidate(1),candidate(2)])) == 1
    assert not ap.select_candidates([{**candidate(1),'face_width':45}])


def test_no_target_score_leakage():
    rows = [candidate(i*2,quality=80+i) for i in range(5)]
    first = [c['frame_id'] for c in ap.select_candidates(rows)]
    for i,c in enumerate(rows): c['enrollment_similarity'] = 100-i
    assert [c['frame_id'] for c in ap.select_candidates(rows)] == first


def test_camera_switch_and_expiration_clear_state():
    matcher = TargetMatcher(TargetManager(),ttl_frames=5)
    matcher._camera_id = 'A'
    matcher._best_faces[1] = BestFaceState(1,camera_id='A')
    matcher._track_last_seen[1] = 1
    frame = np.zeros((20,20,3),np.uint8)
    matcher.match_tracks(frame,None,2,camera_id='B')
    assert not matcher.get_all_track_states()
    matcher._best_faces[1] = BestFaceState(1,camera_id='B')
    matcher._track_last_seen[1] = 2
    matcher.match_tracks(frame,None,10,camera_id='B')
    assert not matcher.get_all_track_states()


def test_legacy_embedding_without_original_is_never_cross_compared():
    manager = TargetManager()
    t = manager.add_target_from_db('legacy','legacy',face_embedding=unit(),embedding_model='arcface')
    assert t.face_embedding is None and t.embedding_model == 'unavailable'


def test_one_scrfd_call_in_production_detection(inputs):
    from src.face.face_embedder import FaceEmbedder
    fe = FaceEmbedder(); fe._initialized = True
    fe._det_model = Mock()
    fe._det_model.detect.return_value = (np.array([[12,15,48,60,.9]]), np.array([inputs[2]]))
    result = fe.detect_faces_in_roi(inputs[0],single_pass=True)
    assert len(result) == 1
    fe._det_model.detect.assert_called_once()
    assert fe._det_model.detect.call_args.kwargs['det_thresh'] == .35
