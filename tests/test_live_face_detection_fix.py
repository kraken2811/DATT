"""Tests for Live Face Detection Focused Fix.

Verifies:
1. Diagnostics for every meaningful face acquisition ([FACE_ACQ]) with all 12 required fields.
2. Bounded debug sample saving in scratch/face_debug/ (full native, ROI before upscale, ROI after upscale).
3. Adaptive upscale execution (e.g. 109x175 -> 3.0x -> 327x525).
4. Upper-body ROI comparison (58% vs 70% vs full bbox) with automatic broader ROI fallback.
5. NORMAL lighting allows small-face upscaled detection pass (decoupled illumination & upscale).
6. Acceptance criteria: face_count >= 1, face > 0px, conf > 0, emb_recomputed=True, sim > 0.
"""

from pathlib import Path
import shutil
import unittest

import cv2
import numpy as np

from src.face.face_embedder import FaceEmbedder, face_embedder
from src.recognition.target_matcher import TargetManager, TargetMatcher


class MockDetections:
    """Mock detections for Tracker."""
    def __init__(self, xyxy: np.ndarray, tracker_id: np.ndarray, confidence: np.ndarray | None = None) -> None:
        self.xyxy = xyxy
        self.tracker_id = tracker_id
        self.confidence = confidence if confidence is not None else np.ones(len(xyxy), dtype=np.float32)


class TestLiveFaceDetectionFix(unittest.TestCase):
    """Test suite covering the 7 focused requirements for live face detection."""

    @classmethod
    def setUpClass(cls) -> None:
        face_embedder.initialize()
        face_img_path = Path("results/onnx_detection.jpg")
        if face_img_path.is_file():
            raw = cv2.imread(str(face_img_path))
            cls.sample_face_img = raw
            # Face is at [280, 196, 470, 429] (size 190x233)
            cls.face_only = raw[196:429, 280:470]
        else:
            cls.sample_face_img = np.ones((200, 200, 3), dtype=np.uint8) * 150
            cls.face_only = cls.sample_face_img

    def setUp(self) -> None:
        self.debug_dir = Path("scratch/face_debug")
        if self.debug_dir.is_dir():
            shutil.rmtree(self.debug_dir, ignore_errors=True)

        self.manager = TargetManager()
        self.matcher = TargetMatcher(manager=self.manager, ttl_frames=30)
        # Register a target
        self.target = self.manager.register_target(
            name="long",
            face_image=self.sample_face_img,
            face_threshold=0.35,
        )

    def tearDown(self) -> None:
        self.matcher.reset_tracks()
        self.manager.clear()

    def test_point_3_and_6_adaptive_upscale_and_normal_illum_independence(self) -> None:
        """Requirement 3 & 6: Verify adaptive 3x upscale executes on 109x175 and NORMAL lighting allows it."""
        # Create a 109x175 ROI with normal illumination containing a face
        small_roi = np.full((175, 109, 3), 110, dtype=np.uint8)
        head = cv2.resize(self.face_only, (42, 52))
        small_roi[20:72, 33:75] = head

        faces, diag = face_embedder.detect_faces_in_roi(
            small_roi, illumination="NORMAL", enhanced_roi=None, return_diag=True
        )

        # Upscale factor for 109x175 (min_dim=109 <= 125) must be 3.0
        self.assertEqual(diag["upscale_factor"], 3.0)
        # Detector input size must be 327x525
        self.assertEqual(diag["detector_input_size"], (327, 525))
        self.assertEqual(diag["illumination_state"], "NORMAL")
        self.assertGreaterEqual(len(faces), 1)

    def test_point_3_adaptive_upscale_159x193(self) -> None:
        """Requirement 3: Verify adaptive 2x upscale on 159x193 ROI."""
        med_roi = np.full((193, 159, 3), 110, dtype=np.uint8)
        head = cv2.resize(self.face_only, (48, 58))
        med_roi[25:83, 55:103] = head

        faces, diag = face_embedder.detect_faces_in_roi(
            med_roi, illumination="NORMAL", enhanced_roi=None, return_diag=True
        )

        # Upscale factor for 159x193 (min_dim=159 <= 220) must be 2.0
        self.assertEqual(diag["upscale_factor"], 2.0)
        self.assertEqual(diag["detector_input_size"], (318, 386))
        self.assertGreaterEqual(len(faces), 1)

    def test_point_1_and_2_diagnostics_and_bounded_debug_samples(self) -> None:
        """Requirement 1 & 2: Full acquisition diagnostics [FACE_ACQ] and debug sample saving."""
        # Synthesize a 1280x720 native frame with person at [653, 133, 742, 400]
        native_frame = np.full((720, 1280, 3), 110, dtype=np.uint8)
        # Person torso:
        native_frame[133+50:400, 653:742] = (70, 70, 70)
        # Person head:
        head = cv2.resize(self.face_only, (40, 50))
        native_frame[133+5:133+55, 653+24:653+64] = head

        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[653 * 0.5, 133 * 0.5, 742 * 0.5, 400 * 0.5]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([1]))

        with self.assertLogs("datt.target_matcher", level="INFO") as log_capture:
            self.matcher.match_tracks(
                frame=infer_frame,
                tracks=tracks,
                frame_id=10,
                native_frame=native_frame,
            )

        # Check Requirement 1 diagnostics logged
        acq_logs = [line for line in log_capture.output if "[FACE_ACQ]" in line]
        self.assertTrue(len(acq_logs) > 0, "Expected [FACE_ACQ] log line")
        log_line = acq_logs[0]
        self.assertIn("track_id=1", log_line)
        self.assertIn("frame_id=10", log_line)
        self.assertIn("person_bbox_native=[653,133,742,400]", log_line)
        self.assertIn("upscale_factor=3.0", log_line)
        self.assertIn("detector_input_size=327x525", log_line)
        self.assertIn("original_face_count=", log_line)
        self.assertIn("enhanced_face_count=", log_line)
        self.assertIn("best_face_confidence=", log_line)

        # Check Requirement 2 debug samples saved in scratch/face_debug/
        self.assertTrue(self.debug_dir.is_dir())
        saved_files = list(self.debug_dir.glob("f10_t1_*.jpg"))
        self.assertGreaterEqual(len(saved_files), 3)
        sample_names = [f.name for f in saved_files]
        self.assertIn("f10_t1_full_native.jpg", sample_names)
        self.assertIn("f10_t1_roi_before_upscale.jpg", sample_names)
        self.assertIn("f10_t1_roi_after_upscale.jpg", sample_names)

    def test_point_4_roi_comparison_fallback(self) -> None:
        """Requirement 4: Verify broader 70% ROI fallback when upper 58% has face cut off."""
        native_frame = np.full((720, 1280, 3), 110, dtype=np.uint8)
        head = cv2.resize(self.face_only, (50, 60))
        # Place head at y=290 to 350 so 58% ROI cuts it off but 70% ROI captures it
        native_frame[290:350, 240:290] = head

        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[200 * 0.5, 100 * 0.5, 350 * 0.5, 450 * 0.5]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([7]))

        with self.assertLogs("datt.target_matcher", level="INFO") as log_capture:
            self.matcher.match_tracks(
                frame=infer_frame,
                tracks=tracks,
                frame_id=20,
                native_frame=native_frame,
            )

        # Broader 70% ROI fallback should be logged and adopted
        roi_logs = [line for line in log_capture.output if "[ROI_COMPARE]" in line]
        self.assertTrue(len(roi_logs) > 0, "Expected [ROI_COMPARE] fallback log")
        self.assertIn("broader 70% ROI found", roi_logs[0])
        state = self.matcher.get_track_state(7)
        self.assertIsNotNone(state)
        self.assertGreater(state.confidence, 0.0)

    def test_acceptance_criteria_real_person_acquisition(self) -> None:
        """Requirement Acceptance: face_count >= 1, face > 0px, conf > 0, emb_recomputed=True, sim > 0."""
        # Frame with person bbox [531, 204, 660, 498] (pw=129, ph=294, roi=159x193)
        native_frame = np.full((720, 1280, 3), 110, dtype=np.uint8)
        native_frame[204+60:498, 531:660] = (80, 80, 80)
        head_crop = cv2.resize(self.face_only, (48, 58))
        native_frame[204+5:204+63, 531+40:531+88] = head_crop

        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[531 * 0.5, 204 * 0.5, 660 * 0.5, 498 * 0.5]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([42]))

        matches = self.matcher.match_tracks(
            frame=infer_frame,
            tracks=tracks,
            frame_id=5,
            native_frame=native_frame,
        )

        state = self.matcher.get_track_state(42)
        self.assertIsNotNone(state)
        # Acceptance criteria checks:
        self.assertGreater(state.face_size, 0.0, "face_size must be > 0")
        self.assertGreater(state.confidence, 0.0, "confidence must be > 0")
        self.assertIsNotNone(state.embedding, "embedding must be computed")
        self.assertGreater(state.similarity, 0.0, "similarity must be a real nonzero value")
        self.assertIn(42, matches, "Target 'long' must match")


if __name__ == "__main__":
    unittest.main()
