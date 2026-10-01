"""Matcher lifecycle regressions for single-pass AdaFace/F2.

Only SCRFD output and AdaFace inference are mocked. Geometry, quality,
buffering, fusion, decisions and expiration use production implementations.
"""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import numpy as np
from src.face.face_embedder import face_embedder
from src.recognition.target_matcher import TargetManager, TargetMatcher, calculate_face_frontality


def unit(i=0):
    v = np.zeros(512, np.float32)
    v[i] = 1
    return v


class TestCheckingHangAndBestFaceFix(TestCase):
    def setUp(self):
        self.manager = TargetManager()
        self.target = self.manager.add_target_from_db('target', 'Target', face_embedding=unit(), face_threshold=.40)
        self.matcher = TargetMatcher(self.manager, ttl_frames=20)
        self.matcher._max_debug_samples = 0
        self.embed = Mock(return_value=unit(1))
        self.matcher.face_pipeline.embedder = SimpleNamespace(embed_aligned_face=self.embed)
        self.frame = np.random.default_rng(7).integers(0, 255, (100, 100, 3), dtype=np.uint8)

    def evaluate(self, fid, *, width=36, score=.9, track=1, vector=None, detected=True):
        face = dict(bbox=np.float32([12, 15, 12+width, 60]), score=score,
                    kps=np.float32([[21, 25], [39, 25], [30, 38], [24, 49], [36, 49]]))
        # Keep landmarks inside each resized face so width-gate cases do not
        # accidentally test invalid landmark geometry instead.
        face['kps'][:, 0] = 12 + (face['kps'][:, 0] - 12) * width / 36
        if vector is not None:
            self.embed.return_value = vector
        tracks = SimpleNamespace(xyxy=np.float32([[0, 0, 80, 100]]), tracker_id=np.array([track]))
        with patch.object(face_embedder, 'check_illumination', return_value=('NORMAL', False, None)), \
                patch.object(face_embedder, 'detect_faces_in_roi', return_value=([face] if detected else [], {})):
            matches = self.matcher.match_tracks(self.frame, tracks, fid, camera_id='camera-A')
        return matches, self.matcher.get_track_state(track)

    def test_frontality_calculation(self):
        points = np.float32([[30, 40], [70, 40], [50, 60], [35, 80], [65, 80]])
        self.assertAlmostEqual(calculate_face_frontality(points), 1., places=1)
        points[2, 0] = 38
        self.assertLess(calculate_face_frontality(points), .6)

    def test_eligible_face_progresses_to_unknown_after_three_evaluations(self):
        for fid, decision, count in [(1, 'CHECKING', 1), (5, 'CHECKING', 2), (9, 'UNKNOWN', 3)]:
            matches, state = self.evaluate(fid)
            self.assertFalse(matches)
            self.assertEqual(state.decision, decision)
            self.assertEqual(state.consecutive_below_thresh, count)
        self.assertEqual(len(state.selected_candidates), 3)

    def test_invalid_embedding_waits_without_counting_an_attempt(self):
        matches, state = self.evaluate(1, vector=np.full(512, np.nan))
        self.assertFalse(matches)
        self.assertEqual(state.decision, 'WAIT_FOR_BETTER_FACE')
        self.assertIsNone(state.embedding)
        self.assertEqual(state.attempts_count, 0)

    def test_large_face_is_rejected_even_with_high_confidence(self):
        matches, state = self.evaluate(1, width=60, score=.99)
        self.assertFalse(matches)
        self.assertEqual(state.decision, 'WAIT_FOR_BETTER_FACE')
        self.assertIsNone(state.embedding)
        self.embed.assert_not_called()

    def test_rejected_frames_do_not_advance_unknown_counter(self):
        for fid in [1, 5, 9]:
            _, state = self.evaluate(fid, width=60)
        self.assertEqual(state.consecutive_below_thresh, 0)
        self.assertEqual(state.decision, 'WAIT_FOR_BETTER_FACE')

    def test_similarity_above_threshold_matches_with_one_candidate(self):
        matches, state = self.evaluate(1, vector=unit())
        self.assertIn(1, matches)
        self.assertEqual(state.decision, 'FACE_MATCH')
        self.assertEqual(state.consecutive_below_thresh, 0)
        self.assertAlmostEqual(state.similarity, 1.)
        self.assertEqual(len(state.selected_candidates), 1)

    def test_rejected_candidate_preserves_best_metadata(self):
        _, state = self.evaluate(1, score=.95)
        saved = (state.embedding, state.quality_score, state.confidence, state.frame_id)
        _, state = self.evaluate(5, width=20)
        self.assertIs(state.embedding, saved[0])
        self.assertEqual((state.quality_score, state.confidence, state.frame_id), saved[1:])
        self.assertEqual(state.face_size, 36)
        self.assertEqual(state.candidate_face_size, 20)

    def test_small_quality_improvement_updates_best_and_fuses_both(self):
        _, state = self.evaluate(1, score=.85, vector=unit(2))
        first_quality = state.quality_score
        with self.assertLogs('datt.target_matcher', level='DEBUG') as logs:
            _, state = self.evaluate(5, score=.86, vector=unit(3))
        self.assertGreater(state.quality_score, first_quality)
        self.assertLess(state.quality_score, first_quality * 1.1)
        self.assertEqual(state.frame_id, 5)
        np.testing.assert_array_equal(state.embedding, unit(3))
        self.assertEqual([c['frame_id'] for c in state.selected_candidates], [5, 1])
        self.assertGreater(state.fused_embedding[2], 0)
        self.assertGreater(state.fused_embedding[3], 0)
        self.assertTrue(any('[BEST_FACE]' in line for line in logs.output))

    def test_registered_threshold_is_preserved(self):
        # Independent tracks avoid accidentally asserting single-frame similarity
        # for a fused two-frame vector.
        for tid, sim, expected in [(60, .38, 'CHECKING'), (61, .42, 'FACE_MATCH')]:
            vector = sim*unit() + np.sqrt(1-sim**2)*unit(1)
            matches, state = self.evaluate(tid, track=tid, vector=vector)
            self.assertEqual(state.decision, expected)
            self.assertAlmostEqual(state.similarity, sim, places=3)
            self.assertEqual(state.threshold, .40)
            self.assertEqual(tid in matches, expected == 'FACE_MATCH')
        default = self.manager.add_target_from_db('default', 'Default', face_embedding=unit())
        self.assertEqual(default.face_threshold, .45)

    def test_worse_valid_frame_preserves_best_but_participates_in_fusion(self):
        _, state = self.evaluate(1, score=.95, vector=unit(2))
        first = state.embedding
        _, state = self.evaluate(5, score=.8, vector=unit(3))
        self.assertIs(state.embedding, first)
        self.assertEqual(state.frame_id, 1)
        self.assertEqual(self.embed.call_count, 2)
        self.assertEqual(len(state.selected_candidates), 2)
        self.assertGreater(state.fused_embedding[2], state.fused_embedding[3])
        self.assertGreater(state.fused_embedding[3], 0)
        self.assertAlmostEqual(np.linalg.norm(state.fused_embedding), 1., places=6)

    def test_stale_track_does_not_transfer_match_to_reused_id(self):
        matches, _ = self.evaluate(1, track=77, vector=unit())
        self.assertIn(77, matches)
        self.evaluate(50, track=99, detected=False)
        self.assertIsNone(self.matcher.get_track_state(77))
        matches, state = self.evaluate(60, track=77, detected=False)
        self.assertNotIn(77, matches)
        self.assertEqual(state.decision, 'WAIT_FOR_BETTER_FACE')
        self.assertIsNone(state.embedding)
        self.assertIsNone(state.matched_target_id)
        self.assertEqual(state.candidate_buffer.candidates, [])

    def test_per_frame_face_diagnostics_do_not_spam_info(self):
        # Warm the camera switch before checking per-frame logging.
        self.evaluate(1, detected=False)
        with self.assertNoLogs('datt.target_matcher', level='INFO'):
            self.evaluate(5, detected=False)
            self.evaluate(9)
