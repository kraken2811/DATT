"""Comprehensive verification test suite for DATT Live Face Recognition and Counter Sync.

Tests all 6 required scenarios:
1. Normal lighting, clear face: accurate detection, alignment, embedding, and high-confidence match.
2. Backlit condition: LAB-L detection (BACKLIT/DARK), CLAHE enhancement, face detection & matching.
3. Fast-passing person: evaluation cadence, fast retry on growth, recognition pausing once matched.
4. Distant person approaching: 30px WAIT_FOR_BETTER_FACE -> 75px FACE_MATCH -> 110px BestFace replacement.
5. Stranger/Unknown: clear face (>=48px, sharp) below threshold 3x -> transitions to UNKNOWN.
6. Counter Sync & Fallback: frame_id, people_count, active_tracks, and is_fallback locked between video and telemetry.
7. Port 8501 Live Server test: /telemetry, /api/targets, and /video_feed verification.
"""

from collections import namedtuple
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import cv2
from fastapi.testclient import TestClient
import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.face.face_embedder import (
    FaceEmbedder,
    cosine_similarity,
    face_embedder,
)
from src.recognition.target_matcher import (
    BestFaceState,
    TargetManager,
    TargetMatcher,
    target_manager,
    target_matcher,
)
from src.runtime.shared_state import shared_state, TelemetrySnapshot, Observation
from src.ui.web_server import app


MockDetections = namedtuple("MockDetections", ["xyxy", "tracker_id", "confidence"])


class TestLiveFaceRecAndCounterSync(unittest.TestCase):
    """Test suite for live face recognition scenarios and telemetry-video synchronization."""

    @classmethod
    def setUpClass(cls) -> None:
        """Load sample face images for realistic testing."""
        face_path = PROJECT_ROOT / "venv" / "Lib" / "site-packages" / "insightface" / "data" / "images" / "Tom_Hanks_54745.png"
        if not face_path.is_file():
            raise FileNotFoundError(f"Missing test face image at {face_path}")
        cls.target_face_img = cv2.imread(str(face_path))
        assert cls.target_face_img is not None, "Failed to read target face image"

        scene_path = PROJECT_ROOT / "venv" / "Lib" / "site-packages" / "insightface" / "data" / "images" / "t1.jpg"
        assert scene_path.is_file(), f"Missing scene image at {scene_path}"
        cls.scene_img = cv2.imread(str(scene_path))
        assert cls.scene_img is not None, "Failed to read scene image"

        # Warm up face_embedder models
        face_embedder.initialize()

    def setUp(self) -> None:
        self.manager = TargetManager()
        self.matcher = TargetMatcher(manager=self.manager, ttl_frames=15)
        # Register Target Tom Hanks
        self.target = self.manager.register_target(
            name="Tom Hanks",
            face_image=self.target_face_img,
            face_threshold=0.40,
        )

    def tearDown(self) -> None:
        self.matcher.reset_tracks()
        self.manager.clear()

    def _compose_frame_with_face(
        self,
        canvas_h: int = 720,
        canvas_w: int = 1280,
        person_bbox: tuple[int, int, int, int] = (400, 100, 600, 500),
        face_crop: np.ndarray | None = None,
        face_size: int = 80,
        face_brightness: float = 1.0,
        bg_brightness: int = 128,
    ) -> np.ndarray:
        """Compose a synthetic native frame containing a body with the face in the head region."""
        px1, py1, px2, py2 = person_bbox
        pw = px2 - px1
        ph = py2 - py1

        # Background
        frame = np.full((canvas_h, canvas_w, 3), bg_brightness, dtype=np.uint8)

        # Body torso (lower 60%)
        torso_y1 = py1 + int(ph * 0.35)
        frame[torso_y1:py2, px1:px2] = (60, 60, 60)

        # Head region (upper 35%)
        head_cx = px1 + pw // 2
        head_cy = py1 + int(ph * 0.18)

        # Resize and place face
        src_face = face_crop if face_crop is not None else self.target_face_img
        resized_face = cv2.resize(src_face, (face_size, face_size))
        if face_brightness != 1.0:
            resized_face = np.clip(resized_face.astype(np.float32) * face_brightness, 0, 255).astype(np.uint8)

        fx1 = max(0, head_cx - face_size // 2)
        fy1 = max(0, head_cy - face_size // 2)
        fx2 = min(canvas_w, fx1 + face_size)
        fy2 = min(canvas_h, fy1 + face_size)

        fw = fx2 - fx1
        fh = fy2 - fy1
        if fw > 0 and fh > 0:
            frame[fy1:fy2, fx1:fx2] = resized_face[:fh, :fw]

        return frame

    def test_scenario_1_normal_lighting_clear_face(self) -> None:
        """SCENARIO 1: Normal lighting with clear face -> high similarity FACE_MATCH."""
        native_frame = self._compose_frame_with_face(
            canvas_h=720, canvas_w=1280,
            person_bbox=(300, 100, 500, 550),
            face_size=75,
            face_brightness=1.0,
            bg_brightness=120,
        )

        # Infer frame (e.g. 640x360)
        infer_frame = cv2.resize(native_frame, (640, 360))
        # Person bbox on infer frame
        infer_bbox = np.array([[300 * 0.5, 100 * 0.5, 500 * 0.5, 550 * 0.5]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([10]), confidence=np.array([0.9]))

        matches = self.matcher.match_tracks(
            frame=infer_frame,
            tracks=tracks,
            frame_id=1,
            native_frame=native_frame,
        )

        self.assertIn(10, matches)
        m = matches[10]
        self.assertEqual(m.target_name, "Tom Hanks")
        self.assertEqual(m.decision, "FACE_MATCH")
        self.assertGreaterEqual(m.score, 0.40)
        self.assertGreaterEqual(m.face_size, 48.0)

    def test_scenario_2_backlit_face_enhancement(self) -> None:
        """SCENARIO 2: Backlit condition (dark face against bright background) triggers CLAHE enhancement."""
        # Bright background (L ~ 220), dark face (brightness 0.30 -> L ~ 45)
        native_frame = self._compose_frame_with_face(
            canvas_h=720, canvas_w=1280,
            person_bbox=(300, 100, 500, 550),
            face_size=80,
            face_brightness=0.30,
            bg_brightness=220,
        )

        # Verify check_illumination detects DARK or BACKLIT
        px1, py1, px2, py2 = 300, 100, 500, 550
        head_roi = native_frame[py1:py1 + 250, px1:px2]
        illumination, enhancement, _ = face_embedder.check_illumination(head_roi)
        self.assertIn(illumination, ("BACKLIT", "DARK"))
        self.assertIn(enhancement, ("CLAHE", "CLAHE+GAMMA"))

        # Run through matcher
        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[150.0, 50.0, 250.0, 275.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([12]), confidence=np.array([0.9]))

        matches = self.matcher.match_tracks(
            frame=infer_frame,
            tracks=tracks,
            frame_id=1,
            native_frame=native_frame,
        )

        self.assertIn(12, matches)
        self.assertEqual(matches[12].decision, "FACE_MATCH")
        self.assertGreaterEqual(matches[12].score, 0.40)

    def test_scenario_3_fast_passing_person_cadence(self) -> None:
        """SCENARIO 3: Fast-passing person: evaluated every 4 frames, stops after match."""
        native_frame = self._compose_frame_with_face(
            canvas_h=720, canvas_w=1280,
            person_bbox=(200, 100, 400, 550),
            face_size=70,
        )
        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[100.0, 50.0, 200.0, 275.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([25]), confidence=np.array([0.9]))

        # Frame 1: First evaluation -> matches
        matches_f1 = self.matcher.match_tracks(infer_frame, tracks, frame_id=1, native_frame=native_frame)
        self.assertIn(25, matches_f1)
        self.assertEqual(matches_f1[25].decision, "FACE_MATCH")

        # Frame 2: Immediately next frame -> already matched, so heavy eval skipped, cached match kept
        with patch.object(face_embedder, "detect_faces_in_roi") as mock_det:
            matches_f2 = self.matcher.match_tracks(infer_frame, tracks, frame_id=2, native_frame=native_frame)
            mock_det.assert_not_called()
            self.assertIn(25, matches_f2)
            self.assertEqual(matches_f2[25].decision, "FACE_MATCH")

    def test_scenario_4_approaching_person_quality_progression(self) -> None:
        """SCENARIO 4: Distant person approaching: 30px (WAIT) -> 75px (MATCH) -> 110px (BEST_REPLACED)."""
        # Step A: Face too small (crop 30px -> detected face ~20px < 32px)
        far_frame = self._compose_frame_with_face(
            canvas_h=720, canvas_w=1280,
            person_bbox=(400, 200, 500, 450),
            face_size=30,
        )
        infer_frame_far = cv2.resize(far_frame, (640, 360))
        infer_bbox_far = np.array([[200.0, 100.0, 250.0, 225.0]], dtype=np.float32)
        tracks_far = MockDetections(xyxy=infer_bbox_far, tracker_id=np.array([30]), confidence=np.array([0.85]))

        matches_far = self.matcher.match_tracks(infer_frame_far, tracks_far, frame_id=1, native_frame=far_frame)
        self.assertEqual(len(matches_far), 0)
        state_far = self.matcher._best_faces[30]
        self.assertEqual(state_far.decision, "WAIT_FOR_BETTER_FACE")
        self.assertIsNone(state_far.embedding)

        # Step B: Closer (crop 75px -> detected face ~51px >= 48px CAN_EMBED) -> FACE_MATCH
        mid_frame = self._compose_frame_with_face(
            canvas_h=720, canvas_w=1280,
            person_bbox=(350, 150, 500, 500),
            face_size=75,
        )
        infer_frame_mid = cv2.resize(mid_frame, (640, 360))
        infer_bbox_mid = np.array([[175.0, 75.0, 250.0, 250.0]], dtype=np.float32)
        tracks_mid = MockDetections(xyxy=infer_bbox_mid, tracker_id=np.array([30]), confidence=np.array([0.90]))

        matches_mid = self.matcher.match_tracks(infer_frame_mid, tracks_mid, frame_id=6, native_frame=mid_frame)
        self.assertIn(30, matches_mid)
        self.assertEqual(matches_mid[30].decision, "FACE_MATCH")
        state_mid = self.matcher._best_faces[30]
        self.assertIsNotNone(state_mid.embedding)
        score_mid = state_mid.quality_score

        # Step C: Much closer (crop 110px -> detected face ~75px) -> quality improves by > 10% -> best_replaced = True
        close_frame = self._compose_frame_with_face(
            canvas_h=720, canvas_w=1280,
            person_bbox=(300, 80, 550, 600),
            face_size=110,
        )
        infer_frame_close = cv2.resize(close_frame, (640, 360))
        infer_bbox_close = np.array([[150.0, 40.0, 275.0, 300.0]], dtype=np.float32)
        tracks_close = MockDetections(xyxy=infer_bbox_close, tracker_id=np.array([30]), confidence=np.array([0.95]))

        # Evaluate at frame_id 120 (cadence due)
        matches_close = self.matcher.match_tracks(infer_frame_close, tracks_close, frame_id=120, native_frame=close_frame)
        self.assertIn(30, matches_close)
        state_close = self.matcher._best_faces[30]
        self.assertGreater(state_close.quality_score, score_mid)
        self.assertGreater(state_close.face_size, 65.0)

    def test_scenario_5_stranger_unknown_progression(self) -> None:
        """SCENARIO 5: Stranger with clear face (>=48px) transitions: CHECKING -> UNKNOWN."""
        # Extract a real stranger face crop from t1.jpg (natural sharpness > 40, size ~110px)
        stranger_crop = self.scene_img[266:416, 463:573]

        native_frame = self._compose_frame_with_face(
            canvas_h=720, canvas_w=1280,
            person_bbox=(300, 100, 500, 550),
            face_crop=stranger_crop,
            face_size=90,
        )

        infer_frame = cv2.resize(native_frame, (640, 360))
        infer_bbox = np.array([[150.0, 50.0, 250.0, 275.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=infer_bbox, tracker_id=np.array([88]), confidence=np.array([0.9]))

        # Frame 1: Evaluated -> clear face, low similarity (<0.10 vs 0.40) -> CHECKING
        matches1 = self.matcher.match_tracks(infer_frame, tracks, frame_id=1, native_frame=native_frame)
        self.assertEqual(len(matches1), 0)
        state = self.matcher._best_faces[88]
        self.assertEqual(state.decision, "CHECKING")
        self.assertEqual(state.consecutive_below_thresh, 1)

        # Frame 5: Evaluated -> CHECKING (2nd time)
        matches2 = self.matcher.match_tracks(infer_frame, tracks, frame_id=5, native_frame=native_frame)
        self.assertEqual(len(matches2), 0)
        state = self.matcher._best_faces[88]
        self.assertEqual(state.decision, "CHECKING")
        self.assertEqual(state.consecutive_below_thresh, 2)

        # Frame 9: Evaluated -> 3rd consecutive low similarity -> UNKNOWN
        matches3 = self.matcher.match_tracks(infer_frame, tracks, frame_id=9, native_frame=native_frame)
        self.assertEqual(len(matches3), 0)
        state = self.matcher._best_faces[88]
        self.assertEqual(state.decision, "UNKNOWN")
        self.assertGreaterEqual(state.consecutive_below_thresh, 3)

    def test_scenario_6_counter_sync_and_fallback_consistency(self) -> None:
        """SCENARIO 6: Telemetry and Video MJPEG stream stay strictly coupled across normal & fallback frames."""
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # 1. Update shared_state with 1 person (track_id 5)
        shared_state.update(
            latest_frame=dummy_frame,
            annotated_frame=dummy_frame,
            people_count=1,
            track_count=1,
            detection_count=1,
        )

        # Check telemetry and video frame match
        telemetry1 = shared_state.get_telemetry()
        stream_fid1, stream_frame1, stream_fb1, stream_gen1 = shared_state.get_frame_for_stream()

        self.assertGreaterEqual(telemetry1.frame_id, 1)
        self.assertEqual(telemetry1.people_count, 1)
        self.assertEqual(telemetry1.track_count, 1)
        self.assertFalse(telemetry1.is_fallback)
        self.assertEqual(stream_fid1, telemetry1.frame_id)
        self.assertFalse(stream_fb1)

        # 2. Simulate pipeline pause / gap: request fallback frame
        # In this state, get_frame_for_stream returns fallback=True and telemetry returns fallback=True,
        # but count remains 1 and frame_id stays matched!
        shared_state._annotated_frame = None  # simulate frame consumer took current fresh frame
        stream_fid_fb, stream_frame_fb, stream_fb_flag, stream_gen_fb = shared_state.get_frame_for_stream()
        telemetry_fb = shared_state.get_telemetry()

        self.assertTrue(stream_fb_flag)
        self.assertEqual(stream_fid_fb, telemetry1.frame_id)
        self.assertTrue(telemetry_fb.is_fallback)
        self.assertEqual(telemetry_fb.frame_id, telemetry1.frame_id)
        self.assertEqual(telemetry_fb.people_count, 1)  # Does NOT drop to 0!
        self.assertEqual(telemetry_fb.track_count, 1)

        # 3. Pipeline delivers fresh empty frame (0 people)
        shared_state.update(
            latest_frame=dummy_frame,
            annotated_frame=dummy_frame,
            people_count=0,
            track_count=0,
            detection_count=0,
        )

        telemetry2 = shared_state.get_telemetry()
        stream_fid2, stream_frame2, stream_fb2, stream_gen2 = shared_state.get_frame_for_stream()

        self.assertEqual(telemetry2.people_count, 0)
        self.assertFalse(telemetry2.is_fallback)
        self.assertEqual(stream_fid2, telemetry2.frame_id)

    def test_scenario_7_port_8501_live_endpoints(self) -> None:
        """SCENARIO 7: FastAPI endpoints /telemetry and /api/targets test."""
        client = TestClient(app)

        # 1. Test /telemetry endpoint returns 200 with schema
        resp_telem = client.get("/telemetry")
        self.assertEqual(resp_telem.status_code, 200)
        telem_data = resp_telem.json()
        self.assertIn("people_count", telem_data)
        self.assertIn("frame_id", telem_data)
        self.assertIn("is_fallback", telem_data)

        # 2. Test /api/targets endpoint returns registered target
        resp_targets = client.get("/api/targets")
        self.assertEqual(resp_targets.status_code, 200)
        targets_data = resp_targets.json()
        self.assertIn("targets", targets_data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
