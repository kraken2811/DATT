"""Unit and regression tests for CHECKING hang fix and BestFace lifecycle improvements.

Verifies:
1. Face 32-48px with low similarity returns to WAIT_FOR_BETTER_FACE (does not hang in CHECKING).
2. Face >= 48px with low similarity transitions to UNKNOWN after 3 valid evaluations.
3. Face with sim >= threshold transitions to FACE_MATCH immediately.
4. Candidate metadata does not overwrite best face metadata on worse candidate.
5. Best face replaces easily when candidate is clearer/more frontal/higher quality without requiring 10% improvement.
6. Structured short log format:
   [BEST_FACE] best_face_size=... candidate_size=... quality=... best_replaced=... replacement_reason=... sim=... failed_match_count=... decision=...
"""

from collections import namedtuple
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.face.face_embedder import face_embedder
from src.recognition.target_matcher import (
    BestFaceState,
    TargetManager,
    TargetMatcher,
    calculate_face_frontality,
)

MockDetections = namedtuple("MockDetections", ["xyxy", "tracker_id", "confidence"])


class TestCheckingHangAndBestFaceFix(unittest.TestCase):
    """Test suite ensuring CHECKING hang is eliminated and BestFace replacement behaves flexibly."""

    @classmethod
    def setUpClass(cls) -> None:
        face_embedder.initialize()

    def setUp(self) -> None:
        self.manager = TargetManager()
        self.matcher = TargetMatcher(manager=self.manager, ttl_frames=20)
        # Register a target with a known embedding vector
        self.target_emb = np.zeros(512, dtype=np.float32)
        self.target_emb[0] = 1.0  # Unit vector along axis 0
        self.target = self.manager.register_target(name="Target Person", clothing_color="black", face_threshold=0.40)
        self.target.face_embedding = self.target_emb
        self.target.clothing_color = None  # Face only

    def tearDown(self) -> None:
        self.matcher.reset_tracks()
        self.manager.clear()

    def test_frontality_calculation(self) -> None:
        """Verify calculate_face_frontality scores frontal vs turned faces."""
        # Perfectly frontal: left eye (30, 40), right eye (70, 40), nose (50, 60)
        kps_frontal = np.array([
            [30.0, 40.0],
            [70.0, 40.0],
            [50.0, 60.0],
            [35.0, 80.0],
            [65.0, 80.0],
        ], dtype=np.float32)
        front_score = calculate_face_frontality(kps_frontal)
        self.assertAlmostEqual(front_score, 1.0, places=1)

        # Turned face: nose closer to left eye
        kps_turned = np.array([
            [30.0, 40.0],
            [70.0, 40.0],
            [38.0, 60.0],
            [32.0, 80.0],
            [60.0, 80.0],
        ], dtype=np.float32)
        turned_score = calculate_face_frontality(kps_turned)
        self.assertLess(turned_score, 0.6)

    def test_point_1_small_face_low_sim_returns_to_wait_for_better_face(self) -> None:
        """Requirement 1: Face 32-48px + low similarity -> WAIT_FOR_BETTER_FACE, not stuck in CHECKING."""
        # Orthogonal embedding (sim = 0.0)
        stranger_emb = np.zeros(512, dtype=np.float32)
        stranger_emb[1] = 1.0

        native_frame = np.full((720, 1280, 3), 120, dtype=np.uint8)
        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[100.0, 50.0, 200.0, 250.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([10]), confidence=np.array([0.9]))

        mock_face = {
            "bbox": np.array([20.0, 20.0, 56.0, 60.0]),  # 36x40 px -> min dim 36px
            "score": 0.85,
            "kps": np.array([[30, 30], [50, 30], [40, 40], [35, 50], [45, 50]]),
        }

        with patch.object(face_embedder, "detect_faces_in_roi", return_value=([mock_face], {})):
            with patch.object(face_embedder, "calculate_face_quality", return_value=(36.0, 50.0, 65.0, "CAN_EMBED")):
                with patch.object(face_embedder, "align_and_embed", return_value=stranger_emb):
                    with self.assertLogs("datt.target_matcher", level="INFO") as log_capture:
                        matches = self.matcher.match_tracks(infer_frame, tracks, frame_id=1, native_frame=native_frame)

        self.assertEqual(len(matches), 0)
        state = self.matcher.get_track_state(10)
        self.assertIsNotNone(state)
        self.assertLess(state.face_size, 48.0)
        self.assertGreaterEqual(state.face_size, 32.0)
        # MUST BE WAIT_FOR_BETTER_FACE, NOT CHECKING!
        self.assertEqual(state.decision, "WAIT_FOR_BETTER_FACE")
        self.assertEqual(state.consecutive_below_thresh, 0, "Counter must NOT increment for face < 48px")

        # Verify short log format contains all required keys
        best_logs = [l for l in log_capture.output if "[BEST_FACE]" in l]
        self.assertTrue(len(best_logs) > 0)
        self.assertIn("decision=WAIT_FOR_BETTER_FACE", best_logs[0])
        self.assertIn("failed_match_count=0", best_logs[0])

    def test_point_2_large_face_low_sim_transitions_to_unknown_after_3_attempts(self) -> None:
        """Requirement 2: Face >= 48px + low similarity transitions to UNKNOWN on 3rd attempt."""
        stranger_emb = np.zeros(512, dtype=np.float32)
        stranger_emb[1] = 1.0

        native_frame = np.full((720, 1280, 3), 120, dtype=np.uint8)
        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[100.0, 50.0, 200.0, 250.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([20]), confidence=np.array([0.9]))

        mock_face = {
            "bbox": np.array([20.0, 20.0, 75.0, 80.0]),  # 55x60 px -> min dim 55px (>= 48px)
            "score": 0.90,
            "kps": np.array([[35, 35], [65, 35], [50, 50], [40, 65], [60, 65]]),
        }

        with patch.object(face_embedder, "detect_faces_in_roi", return_value=([mock_face], {})):
            with patch.object(face_embedder, "calculate_face_quality", return_value=(55.0, 60.0, 85.0, "CAN_EMBED")):
                with patch.object(face_embedder, "align_and_embed", return_value=stranger_emb):
                    # Attempt 1 -> CHECKING (count=1)
                    self.matcher.match_tracks(infer_frame, tracks, frame_id=1, native_frame=native_frame)
                    st1 = self.matcher.get_track_state(20)
                    self.assertEqual(st1.decision, "CHECKING")
                    self.assertEqual(st1.consecutive_below_thresh, 1)

                    # Attempt 2 -> CHECKING (count=2)
                    self.matcher.match_tracks(infer_frame, tracks, frame_id=5, native_frame=native_frame)
                    st2 = self.matcher.get_track_state(20)
                    self.assertEqual(st2.decision, "CHECKING")
                    self.assertEqual(st2.consecutive_below_thresh, 2)

                    # Attempt 3 -> UNKNOWN (count=3)
                    self.matcher.match_tracks(infer_frame, tracks, frame_id=9, native_frame=native_frame)
                    st3 = self.matcher.get_track_state(20)
                    self.assertEqual(st3.decision, "UNKNOWN")
                    self.assertEqual(st3.consecutive_below_thresh, 3)

    def test_point_3_similarity_above_threshold_matches_immediately(self) -> None:
        """Requirement 3: Sim >= threshold -> FACE_MATCH ngay."""
        # Target matching embedding (sim = 1.0)
        match_emb = self.target_emb.copy()

        native_frame = np.full((720, 1280, 3), 120, dtype=np.uint8)
        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[100.0, 50.0, 200.0, 250.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([30]), confidence=np.array([0.9]))

        mock_face = {
            "bbox": np.array([20.0, 20.0, 55.0, 60.0]),  # 35px face
            "score": 0.85,
            "kps": np.array([[30, 30], [50, 30], [40, 40], [35, 50], [45, 50]]),
        }

        with patch.object(face_embedder, "detect_faces_in_roi", return_value=([mock_face], {})):
            with patch.object(face_embedder, "calculate_face_quality", return_value=(35.0, 40.0, 60.0, "CAN_EMBED")):
                with patch.object(face_embedder, "align_and_embed", return_value=match_emb):
                    matches = self.matcher.match_tracks(infer_frame, tracks, frame_id=1, native_frame=native_frame)

        self.assertIn(30, matches)
        self.assertEqual(matches[30].decision, "FACE_MATCH")
        st = self.matcher.get_track_state(30)
        self.assertEqual(st.decision, "FACE_MATCH")
        self.assertEqual(st.consecutive_below_thresh, 0)
        self.assertAlmostEqual(st.similarity, 1.0, places=2)

    def test_point_4_worse_candidate_does_not_overwrite_best_face_metadata(self) -> None:
        """Requirement 4: Candidate xấu không ghi đè face_size/sharpness/confidence của embedding cũ."""
        emb_first = np.zeros(512, dtype=np.float32)
        emb_first[2] = 1.0

        native_frame = np.full((720, 1280, 3), 120, dtype=np.uint8)
        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[100.0, 50.0, 200.0, 250.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([40]), confidence=np.array([0.9]))

        # Frame 1: High quality candidate (60px, sharp)
        mock_face_good = {
            "bbox": np.array([10.0, 10.0, 70.0, 70.0]),  # 60px
            "score": 0.95,
            "kps": np.array([[25, 25], [55, 25], [40, 40], [30, 55], [50, 55]]),
        }
        with patch.object(face_embedder, "detect_faces_in_roi", return_value=([mock_face_good], {})):
            with patch.object(face_embedder, "calculate_face_quality", return_value=(60.0, 80.0, 95.0, "CAN_EMBED")):
                with patch.object(face_embedder, "align_and_embed", return_value=emb_first):
                    self.matcher.match_tracks(infer_frame, tracks, frame_id=1, native_frame=native_frame)

        st = self.matcher.get_track_state(40)
        self.assertEqual(st.face_size, 60.0)
        self.assertEqual(st.confidence, 0.95)
        saved_quality = st.quality_score
        saved_emb = st.embedding

        # Frame 5: Bad candidate (quality gate rejection: face too small, e.g. 20px)
        mock_face_bad = {
            "bbox": np.array([10.0, 10.0, 30.0, 30.0]),  # 20px < 32px (FACE_TOO_SMALL)
            "score": 0.35,
            "kps": np.array([[15, 15], [25, 15], [20, 20], [17, 25], [23, 25]]),
        }
        with patch.object(face_embedder, "detect_faces_in_roi", return_value=([mock_face_bad], {})):
            with patch.object(face_embedder, "calculate_face_quality", return_value=(20.0, 5.0, 15.0, "FACE_TOO_SMALL")):
                self.matcher.match_tracks(infer_frame, tracks, frame_id=5, native_frame=native_frame)

        # BestFace metadata MUST NOT be overwritten by the 20px candidate!
        st_after = self.matcher.get_track_state(40)
        self.assertEqual(st_after.face_size, 60.0, "Best face size must remain 60px")
        self.assertEqual(st_after.confidence, 0.95, "Best face confidence must remain 0.95")
        self.assertEqual(st_after.quality_score, saved_quality, "Quality score must be preserved")
        self.assertIs(st_after.embedding, saved_emb, "Embedding must not be replaced by bad candidate")
        self.assertEqual(st_after.candidate_face_size, 20.0, "Candidate face size recorded separately")

    def test_point_5_easier_best_face_replacement(self) -> None:
        """Requirement 5: Replace best face when candidate is slightly better or more frontal without needing 10%."""
        emb1 = np.zeros(512, dtype=np.float32)
        emb1[3] = 1.0
        emb2 = np.zeros(512, dtype=np.float32)
        emb2[4] = 1.0

        native_frame = np.full((720, 1280, 3), 120, dtype=np.uint8)
        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[100.0, 50.0, 200.0, 250.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([50]), confidence=np.array([0.9]))

        # Frame 1: Face 50px, turned (nose x=25 vs eyes 20 and 50 -> asymmetric)
        mock_face_1 = {
            "bbox": np.array([10.0, 10.0, 60.0, 60.0]),  # 50px
            "score": 0.85,
            "kps": np.array([[20.0, 25.0], [50.0, 25.0], [25.0, 35.0], [22.0, 45.0], [45.0, 45.0]]),
        }
        with patch.object(face_embedder, "detect_faces_in_roi", return_value=([mock_face_1], {})):
            with patch.object(face_embedder, "calculate_face_quality", return_value=(50.0, 50.0, 70.0, "CAN_EMBED")):
                with patch.object(face_embedder, "align_and_embed", return_value=emb1):
                    self.matcher.match_tracks(infer_frame, tracks, frame_id=1, native_frame=native_frame)

        st1 = self.matcher.get_track_state(50)
        self.assertEqual(st1.face_size, 50.0)

        # Frame 5: Face 52px (only 4% larger, < 10%), but perfectly frontal!
        mock_face_2 = {
            "bbox": np.array([10.0, 10.0, 62.0, 62.0]),  # 52px
            "score": 0.88,
            "kps": np.array([[20.0, 25.0], [52.0, 25.0], [36.0, 35.0], [25.0, 47.0], [47.0, 47.0]]),
        }
        with patch.object(face_embedder, "detect_faces_in_roi", return_value=([mock_face_2], {})):
            with patch.object(face_embedder, "calculate_face_quality", return_value=(52.0, 52.0, 73.0, "CAN_EMBED")):
                with patch.object(face_embedder, "align_and_embed", return_value=emb2):
                    with self.assertLogs("datt.target_matcher", level="INFO") as log_capture:
                        self.matcher.match_tracks(infer_frame, tracks, frame_id=5, native_frame=native_frame)

        st2 = self.matcher.get_track_state(50)
        # Should be replaced because it is more frontal and slightly larger/higher quality
        self.assertEqual(st2.face_size, 52.0, "Best face must be replaced by better/frontal candidate")
        self.assertIs(st2.embedding, emb2)

        best_logs = [l for l in log_capture.output if "[BEST_FACE]" in l]
        self.assertTrue(len(best_logs) > 0)
        self.assertIn("best_replaced=YES", best_logs[0])
        self.assertIn("replacement_reason=", best_logs[0])


if __name__ == "__main__":
    unittest.main()
