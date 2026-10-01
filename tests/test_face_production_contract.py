"""Production integration contracts independent of legacy ArcFace mocks."""
import ast
import math
from pathlib import Path
from unittest.mock import Mock, patch
import cv2
import numpy as np
import pytest
from src.face import adaptive_pipeline as ap
from src.recognition.target_matcher import TargetManager, TargetMatcher, BestFaceState


def unit(i=0):
    v=np.zeros(512,np.float32);v[i]=1;return v


@pytest.fixture
def scene():
    roi=np.random.default_rng(4).integers(0,255,(80,80,3),dtype=np.uint8)
    bbox=np.float32([12,15,48,60])
    kps=np.float32([[21,25],[39,25],[30,38],[24,49],[36,49]])
    return roi,bbox,kps


def process(scene,overhead=False):
    roi,bbox,kps=scene;kps=kps.copy()
    if overhead:kps[3:,1]=43
    pipeline=ap.AdaptiveFacePipeline(Mock(embed_aligned_face=Mock(return_value=unit())))
    result=pipeline.process(roi,bbox,.9,kps,camera_id='A',track_id=1,frame_id=4,timestamp=1.)
    return pipeline,result


@pytest.mark.parametrize('overhead,representation',[(False,'RAW'),(True,'RECTIFIED')])
def test_representation_before_identity(scene,overhead,representation):
    pipeline,result=process(scene,overhead)
    assert result['representation_type']==representation
    pipeline.embedder.embed_aligned_face.assert_called_once()


@pytest.mark.parametrize('bad',['nan','collapsed','missing','inverted','empty'])
def test_bad_input_safely_retains_raw(scene,bad):
    roi,_,kps=scene;kps=kps.copy()
    if bad=='nan':kps[0,0]=np.nan
    if bad=='collapsed':kps[:]=25
    if bad=='missing':kps=None
    if bad=='inverted':kps[[0,1]]=kps[[1,0]]
    if bad=='empty':roi=roi[:0]
    raw,points,safe,_=ap.apply_homography_with_safety(roi,kps)
    assert not safe and raw is roi and points is kps


@pytest.mark.parametrize('bad',['bounds','singular','nan','alignment','image'])
def test_failed_rectification_preserves_valid_raw_candidate(scene,bad):
    from insightface.utils import face_align
    roi,_,kps=scene
    if bad=='alignment':
        raw=face_align.norm_crop(roi,landmark=kps,image_size=112)
        context=patch.object(face_align,'norm_crop',side_effect=[raw,ValueError('test')])
    elif bad=='singular':
        # H_alpha = .5 I + .5(-I) = 0.
        context=patch.object(ap.cv2,'getPerspectiveTransform',return_value=-np.eye(3))
    elif bad=='nan':context=patch.object(ap.cv2,'getPerspectiveTransform',return_value=np.full((3,3),np.nan))
    elif bad=='image':context=patch.object(ap,'apply_r2_homography',return_value=(None,kps))
    else:context=patch.object(ap,'apply_r2_homography',return_value=(roi,kps+1000))
    with context:
        pipeline,result=process(scene,True)
    assert result['representation_type']=='RAW_FALLBACK'
    assert np.isfinite(result['embedding']).all()


def candidate(frame,cam='A',track=1,q=80,index=0):
    return dict(frame_id=frame,camera_id=cam,track_id=track,face_width=36,
                overhead_distortion_score=20,quality_score=q,composite_quality=q,
                embedding=unit(index),representation_type='RAW')


def test_unique_frame_and_spacing_are_mandatory():
    buffer=ap.CandidateBuffer('A',1)
    raw=candidate(4);rect={**raw,'representation_type':'RECTIFIED'}
    assert buffer.add(raw) and not buffer.add(rect)
    assert len(ap.select_candidates([raw,rect,candidate(5)]))==1
    assert buffer.selected()[0]['representation_type']=='RAW'


def test_top3_f2_exact_weights_and_normalization():
    rows=[candidate(1,index=0),candidate(2,q=100,index=1),candidate(4,q=90,index=2),candidate(6,q=70,index=3)]
    selected=ap.select_candidates(rows)
    assert [c['frame_id'] for c in selected]==[2,4,6]
    expected=100*unit(1)+90*unit(2)+70*unit(3);expected/=np.linalg.norm(expected)
    np.testing.assert_allclose(ap.fuse_candidates(selected),expected,atol=1e-7)


@pytest.mark.parametrize('count',[1,2])
def test_partial_pool_can_match_now(count):
    assert ap.fuse_candidates(ap.select_candidates([candidate(i*2) for i in range(count)])) is not None


@pytest.mark.parametrize('cam,track',[('B',1),('A',2)])
def test_track_camera_isolation(cam,track):
    buffer=ap.CandidateBuffer('A',1)
    with pytest.raises(ValueError):buffer.add(candidate(1,cam,track))
    with pytest.raises(ValueError):ap.fuse_candidates([candidate(1),candidate(3,cam,track)])


def test_bounds_and_target_score_independence():
    buffer=ap.CandidateBuffer('A',1,capacity=4)
    for fid in range(10):buffer.add(candidate(fid,q=fid+10))
    assert len(buffer.candidates)==4
    before=[c['frame_id'] for c in buffer.selected()]
    for c in buffer.candidates:c['target_similarity']=-c['composite_quality']
    assert [c['frame_id'] for c in buffer.selected()]==before
    assert not ap.select_candidates([{**candidate(20),'face_width':45}])


def test_camera_switch_and_ttl_even_with_no_targets():
    matcher=TargetMatcher(TargetManager(),ttl_frames=5)
    matcher._camera_id='A';matcher._best_faces[1]=BestFaceState(1,camera_id='A')
    matcher._track_last_seen[1]=1
    frame=np.zeros((20,20,3),np.uint8)
    matcher.match_tracks(frame,None,2,camera_id='B')
    assert not matcher.get_all_track_states()
    matcher._best_faces[1]=BestFaceState(1,camera_id='B');matcher._track_last_seen[1]=2
    matcher.match_tracks(frame,None,10,camera_id='B')
    assert not matcher.get_all_track_states()


def test_legacy_model_fails_closed_without_source_image():
    manager=TargetManager()
    t=manager.add_target_from_db('legacy','legacy',face_embedding=unit(),embedding_model='arcface')
    assert t.face_embedding is None and t.embedding_model=='unavailable'


def test_exact_benchmark_geometry_and_warp(scene):
    source=Path('scratch/run_final_homography_production_validation.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    names={'compute_geometry_and_overhead_score','apply_r2_homography'}
    namespace=dict(np=np,cv2=cv2,math=math,CANONICAL_ASPECT=1.1544)
    for fn in tree.body:
        if isinstance(fn,ast.FunctionDef) and fn.name in names:
            exec(compile(ast.Module(body=[fn],type_ignores=[]),'validated_reference','exec'),namespace)
    roi,box,kps=scene
    assert ap.compute_geometry_and_overhead_score(kps,box,80,80)==namespace['compute_geometry_and_overhead_score'](kps,box,80,80)
    expected=namespace['apply_r2_homography'](roi,kps)
    actual=ap.apply_r2_homography(roi,kps)
    for a,b in zip(actual,expected):np.testing.assert_array_equal(a,b)


def test_single_scrfd_call_retains_threshold(scene):
    from src.face.face_embedder import FaceEmbedder
    fe=FaceEmbedder();fe._initialized=True;fe._det_model=Mock()
    fe._det_model.detect.return_value=(np.array([[12,15,48,60,.9]]),np.array([scene[2]]))
    assert len(fe.detect_faces_in_roi(scene[0],single_pass=True))==1
    fe._det_model.detect.assert_called_once()
    assert fe._det_model.detect.call_args.kwargs['det_thresh']==.35


@pytest.mark.parametrize('similarity,decision',[(.44,'CHECKING'),(.46,'FACE_MATCH')])
def test_real_matcher_uses_unchanged_threshold_with_one_candidate(scene,similarity,decision):
    from types import SimpleNamespace
    from src.face.face_embedder import face_embedder
    manager=TargetManager()
    target=manager.add_target_from_db('reference','reference',face_embedding=unit())
    assert target.face_threshold==.45
    matcher=TargetMatcher(manager);matcher._max_debug_samples=0
    vector=similarity*unit(0)+np.sqrt(1-similarity**2)*unit(1)
    matcher.face_pipeline.embedder=Mock(embed_aligned_face=Mock(return_value=vector))
    roi,box,kps=scene
    tracks=SimpleNamespace(xyxy=np.array([[0,0,80,80]]),tracker_id=np.array([1]))
    with patch.object(face_embedder,'detect_faces_in_roi',return_value=([dict(bbox=box,score=.9,kps=kps)],{})):
        matcher.match_tracks(roi,tracks,1,camera_id='A')
    state=matcher.get_track_state(1)
    assert state.threshold==.45 and state.decision==decision
    assert len(state.selected_candidates)==1
    assert state.similarity==pytest.approx(similarity,abs=.001)
    timings=matcher.face_pipeline.last_observation['timings']
    assert timings['full_face_path'] >= timings['through_embedding'] + timings['fusion']
