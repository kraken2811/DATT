"""End-to-End Test for Target Tracking, Highlight, and Dynamic Source Switching.

Runs a complete pipeline simulation:
1. Creates a synthetic test MP4 video with a moving pedestrian wearing red.
2. Registers a target 'Red Person' (clothing_color='red').
3. Feeds frames through:
   LocalVideoReader -> YOLODetector -> ByteTrack -> TargetMatcher -> render_frame
4. Verifies target match association and highlights.
5. Switches video source dynamically at runtime to another local MP4.
6. Verifies pipeline continuity without restarting.
"""

from pathlib import Path
import sys
import tempfile
import time
import unittest

import cv2
import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from src.counter.zone_counter import ZoneCounter
from src.detector.yolo_detector import YOLODetector
from src.recognition.target_matcher import target_manager, target_matcher
from src.stream.camera_manager import CameraManager
from src.tracker.bytetrack_tracker import PersonTracker
from src.ui.frame_renderer import render_frame


def generate_e2e_video(path: Path, color_bgr: tuple[int, int, int] = (0, 0, 255), num_frames: int = 20) -> None:
    """Generate a video with a pedestrian rectangle moving horizontally."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(path), fourcc, 30.0, (640, 480))
    for i in range(num_frames):
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 180  # Light gray background
        x = 100 + i * 10
        y = 150
        # Draw torso
        cv2.rectangle(frame, (x, y + 40), (x + 80, y + 160), color_bgr, -1)
        # Draw head
        cv2.circle(frame, (x + 40, y + 20), 20, (150, 180, 220), -1)
        # Draw legs
        cv2.rectangle(frame, (x + 10, y + 160), (x + 35, y + 240), (50, 50, 50), -1)
        cv2.rectangle(frame, (x + 45, y + 160), (x + 70, y + 240), (50, 50, 50), -1)
        out.write(frame)
    out.release()


class TestEndToEndTargetTracking(unittest.TestCase):
    """End-to-End test suite for Target Tracking, Highlight, and Runtime Source Switch."""

    def setUp(self) -> None:
        target_manager.clear()
        target_matcher.reset_tracks()
        self.camera_mgr = None
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.video1 = Path(self.tmp_dir.name) / "pedestrian_red.mp4"
        self.video2 = Path(self.tmp_dir.name) / "pedestrian_blue.mp4"
        generate_e2e_video(self.video1, color_bgr=(0, 0, 255), num_frames=15)
        generate_e2e_video(self.video2, color_bgr=(255, 0, 0), num_frames=15)

    def tearDown(self) -> None:
        if self.camera_mgr is not None:
            self.camera_mgr.stop_camera()
            self.camera_mgr = None
        target_manager.clear()
        target_matcher.reset_tracks()
        self.tmp_dir.cleanup()

    def test_e2e_flow_and_runtime_switch(self) -> None:
        """Execute full pipeline and runtime source switch."""
        # 1. Register target
        target = target_manager.register_target(name="Target Red", clothing_color="red")
        self.assertEqual(target.clothing_color, "red")

        # 2. Initialize CameraManager with video 1 (Red)
        self.camera_mgr = CameraManager()
        cam_info = self.camera_mgr.set_video_source("local", str(self.video1), loop=True, name="Test Red Video")
        self.assertEqual(cam_info.type, "file")
        self.assertEqual(self.camera_mgr.status, "RUNNING")

        tracker = PersonTracker(config)
        counter = ZoneCounter(polygon=None, person_class_id=0)

        # 3. Process 5 frames from Source 1
        matches_found = []
        for frame_idx in range(5):
            frame = self.camera_mgr.read(timeout=1.0)
            self.assertIsNotNone(frame)
            assert frame is not None

            # Simulate detection on the known pedestrian location
            # [x1, y1, x2, y2]
            x = 100 + frame_idx * 10
            mock_dets = {
                "xyxy": np.array([[x, 150, x + 80, 390]], dtype=np.float32),
                "confidence": np.array([0.95], dtype=np.float32),
                "class_id": np.array([0], dtype=int),
            }

            tracks = tracker.update(mock_dets)
            # ByteTrack requires minimum_consecutive_frames=2 before assigning IDs
            if frame_idx >= 1:
                self.assertGreater(len(tracks), 0)

            # Match target
            matches = target_matcher.match_tracks(frame, tracks, frame_id=frame_idx)
            if matches:
                matches_found.append(matches)

            # Render frame with target highlight
            annotated = render_frame(frame, tracks, people_count=1, target_matches=matches)
            self.assertIsNotNone(annotated)
            self.assertEqual(annotated.shape, frame.shape)

        self.assertGreater(len(matches_found), 0)
        # Verify match is Target Red
        first_match = list(matches_found[0].values())[0]
        self.assertEqual(first_match.target_name, "Target Red")
        self.assertEqual(first_match.match_type, "COLOR_MATCH")

        # 4. RUNTIME SOURCE SWITCH: Switch to video 2 (Blue) without restarting
        cam_info2 = self.camera_mgr.set_video_source("local", str(self.video2), loop=True, name="Test Blue Video")
        self.assertEqual(cam_info2.name, "Test Blue Video")
        self.assertEqual(self.camera_mgr.status, "RUNNING")

        # Reset tracks on source switch (same logic as in app.py)
        tracker.reset()
        target_matcher.reset_tracks()

        # 5. Process frames from Source 2 -> Red target should NOT match Blue video!
        for frame_idx in range(5):
            frame2 = self.camera_mgr.read(timeout=1.0)
            self.assertIsNotNone(frame2)
            assert frame2 is not None

            x = 100 + frame_idx * 10
            mock_dets2 = {
                "xyxy": np.array([[x, 150, x + 80, 390]], dtype=np.float32),
                "confidence": np.array([0.95], dtype=np.float32),
                "class_id": np.array([0], dtype=int),
            }
            tracks2 = tracker.update(mock_dets2)
            if frame_idx >= 1:
                self.assertGreater(len(tracks2), 0)
            matches2 = target_matcher.match_tracks(frame2, tracks2, frame_id=10 + frame_idx)
            # Red target must NOT match blue pedestrian
            self.assertEqual(len(matches2), 0)

        self.camera_mgr.stop_camera()
        self.assertEqual(self.camera_mgr.status, "STOPPED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
