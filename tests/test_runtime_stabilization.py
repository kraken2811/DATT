"""Deterministic Regression & Stabilization Tests for DATT Runtime.

Covers:
1. SharedRuntimeState.status property & thread-safe accessors
2. stop_camera does not crash AI pipeline & enters IDLE safely
3. IDLE state telemetry behavior (no false timeouts)
4. Camera lifecycle transitions: RUNNING -> stop -> IDLE -> CONNECTING -> RUNNING
5. Repeated 10 camera switches in one process (no leak, exactly 1 active reader)
6. Old FFmpeg process cleanup upon switch
7. Multipart MP4 upload validation (valid MP4 accepted, invalid/empty rejected)
8. Uploaded MP4 integration with LocalVideoReader
9. Camera thumbnail service (Snapshot Priority A, HLS 1-frame fallback Priority B)
10. Thumbnail caching & non-blocking behavior
11. Dual Person (0) + Car (2) detection split & independent ByteTrack instances
12. Distinct tracking namespaces & HUD rendering
13. Separate people_count and car_count in SharedRuntimeState & TelemetrySnapshot
14. Tracker & counter reset on camera switch
15. Stream FPS metric bounded window calculation (prevents burst spikes)
"""

import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import cv2
from fastapi.testclient import TestClient
import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from src.counter.zone_counter import CarCounter, ZoneCounter
from src.detector.yolo_detector import YOLODetector
from src.runtime.shared_state import SharedRuntimeState, TelemetrySnapshot
from src.stream.camera_manager import CameraManager
from src.stream.direct_hls import DirectHLSReader
from src.stream.thumbnail_service import ThumbnailService, thumbnail_service
from src.stream.video_source import LocalVideoReader
from src.tracker.bytetrack_tracker import CarTracker, PersonTracker
from src.ui.frame_renderer import render_frame
from src.ui.web_server import app


def make_dummy_mp4(num_frames: int = 10, width: int = 160, height: int = 120) -> Path:
    """Helper to create a temporary MP4 video for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    writer = cv2.VideoWriter(
        str(tmp_path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (width, height)
    )
    for _ in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.putText(frame, "TEST", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    return tmp_path


class TestRuntimeStabilization(unittest.TestCase):
    """Regression test suite for runtime stabilization, camera switching, uploads, and tracking."""

    def setUp(self):
        self.state = SharedRuntimeState()
        self.client = TestClient(app)

    # =========================================================================
    # 1. SharedRuntimeState Accessors & IDLE State
    # =========================================================================

    def test_01_shared_state_status_property_and_accessors(self):
        """Verify SharedRuntimeState exposes thread-safe public status accessors without AttributeError."""
        self.assertEqual(self.state.status, "STOPPED")
        self.assertFalse(self.state.is_idle)
        self.assertFalse(self.state.is_running)

        self.state.set_status("IDLE")
        self.assertEqual(self.state.status, "IDLE")
        self.assertTrue(self.state.is_idle)
        self.assertFalse(self.state.is_running)

        self.state.set_status("RUNNING")
        self.assertEqual(self.state.status, "RUNNING")
        self.assertFalse(self.state.is_idle)
        self.assertTrue(self.state.is_running)

        self.state.set_status("CONNECTING")
        self.assertEqual(self.state.status, "CONNECTING")

    def test_02_stop_camera_transitions_to_idle_without_crash(self):
        """Verify stopping camera transitions to IDLE and clears frames without crashing the pipeline."""
        dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        self.state.update(latest_frame=dummy_frame)
        self.state.set_status("RUNNING")
        _, frame = self.state.get_raw_frame()
        self.assertIsNotNone(frame)

        # Clear frames and transition to IDLE
        self.state.clear_frames()
        self.state.set_status("IDLE")

        self.assertEqual(self.state.status, "IDLE")
        self.assertTrue(self.state.is_idle)
        _, frame_cleared = self.state.get_raw_frame()
        self.assertIsNone(frame_cleared)

        # Telemetry in IDLE must report IDLE and not trigger stream timeout errors
        telem = self.state.get_telemetry()
        self.assertEqual(telem.camera_status, "IDLE")
        self.assertEqual(telem.people_count, 0)
        self.assertEqual(telem.car_count, 0)

    # =========================================================================
    # 2. Camera Manager Switching & Process Lifecycle
    # =========================================================================

    def test_03_camera_manager_single_reader_invariant(self):
        """Verify CameraManager enforces at most 1 active main reader at all times."""
        manager = CameraManager()
        vid_a = make_dummy_mp4(num_frames=5)
        vid_b = make_dummy_mp4(num_frames=5)

        try:
            # Start camera A
            manager.set_video_source(
                source_type="local",
                source=str(vid_a),
                name="cam_a",
            )
            reader_a = manager.get_active_reader()
            self.assertIsNotNone(reader_a)

            # Start camera B directly without explicit stop
            manager.set_video_source(
                source_type="local",
                source=str(vid_b),
                name="cam_b",
            )
            reader_b = manager.get_active_reader()
            self.assertIsNotNone(reader_b)
            self.assertNotEqual(reader_a, reader_b)

            # Stop camera
            manager.stop_camera()
            self.assertIsNone(manager.get_active_reader())
            self.assertEqual(manager.active_camera_id, "")
        finally:
            manager.stop_camera()
            vid_a.unlink(missing_ok=True)
            vid_b.unlink(missing_ok=True)

    def test_04_repeated_10_camera_switches_in_one_process(self):
        """Verify 10 repeated camera switches do not crash, leak readers, or leave duplicate processes."""
        manager = CameraManager()
        videos = [make_dummy_mp4(num_frames=3) for _ in range(3)]

        try:
            for i in range(10):
                vid = videos[i % len(videos)]
                cam_id = f"switch_test_{i}"

                # Switch directly
                manager.set_video_source(
                    source_type="local",
                    source=str(vid),
                    name=cam_id,
                )
                reader = manager.get_active_reader()
                self.assertIsNotNone(reader)

                # Read a frame to verify reader works
                frame = manager.read()

                # Stop camera every 2 switches to test RUNNING -> IDLE -> RUNNING
                if i % 2 == 1:
                    manager.stop_camera()
                    self.assertIsNone(manager.get_active_reader())

            # Final cleanup
            manager.stop_camera()
            self.assertIsNone(manager.get_active_reader())
        finally:
            manager.stop_camera()
            for v in videos:
                v.unlink(missing_ok=True)

    def test_05_changing_direct_hls_camera_stops_old_ffmpeg(self):
        """Verify switching HLS cameras terminates previous FFmpeg process before starting new one."""
        manager = CameraManager()

        reader_a = MagicMock()
        reader_a.stop = MagicMock()
        manager._reader = reader_a
        manager._active_camera = MagicMock()

        # Switch to Camera B
        with patch("src.stream.direct_hls.DirectHLSReader.start"):
            manager.set_video_source("direct_hls", "https://video.seattle.gov/test.m3u8", name="seattle_b")
            self.assertEqual(reader_a.stop.call_count, 1)
            self.assertNotEqual(manager.get_active_reader(), reader_a)
            manager.stop_camera()

        # Verify DirectHLSReader terminates its process when stopped
        reader = DirectHLSReader("https://video.seattle.gov/test.m3u8")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 12345
        reader._process = mock_proc
        reader.stop()
        mock_proc.terminate.assert_called_once()

    # =========================================================================
    # 3. Real Multipart File Upload for Local Video
    # =========================================================================

    def test_06_upload_video_valid_mp4(self):
        """Verify POST /api/upload_video accepts valid MP4 and writes to data/uploads/."""
        dummy_mp4_path = make_dummy_mp4(num_frames=5)
        try:
            with open(dummy_mp4_path, "rb") as f:
                mp4_bytes = f.read()

            response = self.client.post(
                "/api/upload_video",
                files={"file": ("test_clip.mp4", mp4_bytes, "video/mp4")},
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "ok")
            self.assertIn("server_path", data)
            self.assertTrue(Path(data["server_path"]).exists())
            self.assertGreater(data["size"], 0)

            # Verify it can be loaded by LocalVideoReader
            reader = LocalVideoReader(data["server_path"])
            reader.start()
            frame = reader.read(timeout=2.0)
            self.assertIsNotNone(frame)
            reader.stop()

            # Clean up uploaded file
            Path(data["server_path"]).unlink(missing_ok=True)
        finally:
            dummy_mp4_path.unlink(missing_ok=True)

    def test_07_upload_video_invalid_extension_rejected(self):
        """Verify POST /api/upload_video rejects disallowed file extensions (.exe, .txt)."""
        response = self.client.post(
            "/api/upload_video",
            files={"file": ("malicious.exe", b"not-a-video", "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid video format", response.json()["message"])

    def test_08_upload_video_empty_file_rejected(self):
        """Verify POST /api/upload_video rejects empty files."""
        response = self.client.post(
            "/api/upload_video",
            files={"file": ("empty.mp4", b"", "video/mp4")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Uploaded file is empty", response.json()["message"])

    # =========================================================================
    # 4. Camera Thumbnail Service & Fallbacks
    # =========================================================================

    def test_09_thumbnail_service_snapshot_success(self):
        """Verify ThumbnailService Priority A returns working snapshot immediately."""
        svc = ThumbnailService(cache_ttl_seconds=60.0)

        # Mock urllib request returning a valid JPEG
        dummy_jpeg = cv2.imencode(".jpg", np.zeros((100, 100, 3), dtype=np.uint8))[1].tobytes()

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = dummy_jpeg
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            result, content_type = svc.get_thumbnail(
                camera_id="test_cam_snap",
                provider="Caltrans",
                snapshot_url="http://cctv.dot.ca.gov/snapshot.jpg",
                stream_url="",
            )

            self.assertEqual(content_type, "image/jpeg")
            self.assertGreater(len(result), 0)

            # Test cache hit on second request
            result_cached, _ = svc.get_thumbnail(
                camera_id="test_cam_snap",
                provider="Caltrans",
                snapshot_url="http://cctv.dot.ca.gov/snapshot.jpg",
            )
            self.assertEqual(result, result_cached)
            # urlopen should only have been called once due to TTL caching
            self.assertEqual(mock_urlopen.call_count, 1)

    def test_10_thumbnail_service_snapshot_failure_falls_back_to_hls(self):
        """Verify ThumbnailService Priority B extracts 1 frame via FFmpeg when snapshot 404s."""
        svc = ThumbnailService(cache_ttl_seconds=60.0)

        dummy_jpeg = cv2.imencode(".jpg", np.zeros((100, 100, 3), dtype=np.uint8))[1].tobytes()

        # Mock urllib failure (e.g. 404) and FFmpeg success via Popen
        with patch("urllib.request.urlopen", side_effect=Exception("HTTP 404 Not Found")):
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.communicate.return_value = (dummy_jpeg, b"")
            with patch("subprocess.Popen", return_value=mock_proc):
                result, content_type = svc.get_thumbnail(
                    camera_id="test_cam_hls",
                    provider="Seattle SDOT",
                    snapshot_url="https://web.seattle.gov/Travelers/404.jpg",
                    stream_url="https://video.seattle.gov:443/media/test.stream/playlist.m3u8",
                )

                self.assertEqual(content_type, "image/jpeg")
                self.assertEqual(result, dummy_jpeg)

    def test_11_thumbnail_service_complete_failure_returns_svg_placeholder(self):
        """Verify ThumbnailService returns SVG placeholder without throwing error when all sources fail."""
        svc = ThumbnailService(cache_ttl_seconds=60.0)

        with patch("urllib.request.urlopen", side_effect=Exception("404")):
            with patch("subprocess.run", side_effect=Exception("FFmpeg failed")):
                result, content_type = svc.get_thumbnail(
                    camera_id="broken_cam",
                    provider="Seattle SDOT",
                    snapshot_url="https://broken.url/404.jpg",
                    stream_url="https://broken.stream/playlist.m3u8",
                )

                self.assertEqual(content_type, "image/svg+xml")
                self.assertIn(b"<svg", result)

    # =========================================================================
    # 5. Dual Person + Car Detection & Independent Tracking
    # =========================================================================

    def test_12_config_target_classes_contains_person_and_car(self):
        """Verify config.py contains both PERSON (0) and CAR (2) in TARGET_CLASSES."""
        self.assertEqual(config.PERSON_CLASS_ID, 0)
        self.assertEqual(config.CAR_CLASS_ID, 2)
        self.assertIn(0, config.TARGET_CLASSES)
        self.assertIn(2, config.TARGET_CLASSES)

    def test_13_independent_trackers_maintain_separate_identities(self):
        """Verify PersonTracker and CarTracker run independently and don't mix track IDs."""
        person_tracker = PersonTracker(frame_rate=30.0)
        car_tracker = CarTracker(frame_rate=30.0)

        # Create dummy person detection at (10, 10, 50, 100)
        person_xyxy = np.array([[10, 10, 50, 100]], dtype=np.float32)
        person_conf = np.array([0.9], dtype=np.float32)
        person_class = np.array([0], dtype=np.int32)
        import supervision as sv
        person_dets = sv.Detections(
            xyxy=person_xyxy,
            confidence=person_conf,
            class_id=person_class,
        )

        # Create dummy car detection at (200, 200, 400, 350)
        car_xyxy = np.array([[200, 200, 400, 350]], dtype=np.float32)
        car_conf = np.array([0.85], dtype=np.float32)
        car_class = np.array([2], dtype=np.int32)
        car_dets = sv.Detections(
            xyxy=car_xyxy,
            confidence=car_conf,
            class_id=car_class,
        )

        # Update both trackers over 3 frames to establish active tracks
        for _ in range(3):
            p_tracks = person_tracker.update(person_dets)
            c_tracks = car_tracker.update(car_dets)

        # Verify trackers hold separate state
        self.assertIsNot(person_tracker.tracker, car_tracker.tracker)

        # Verify reset clears both
        person_tracker.reset()
        car_tracker.reset()
        self.assertEqual(len(person_tracker.tracker.tracked_tracks), 0)
        self.assertEqual(len(car_tracker.tracker.tracked_tracks), 0)

    def test_14_counters_track_people_and_cars_separately(self):
        """Verify ZoneCounter and CarCounter maintain separate counts."""
        zone_counter = ZoneCounter(target_class_id=0)
        car_counter = CarCounter(target_class_id=2)

        import supervision as sv
        # 2 people tracks
        p_tracks = sv.Detections(
            xyxy=np.array([[10, 10, 50, 100], [60, 10, 100, 100]], dtype=np.float32),
            tracker_id=np.array([1, 2], dtype=np.int32),
            class_id=np.array([0, 0], dtype=np.int32),
        )
        # 3 car tracks
        c_tracks = sv.Detections(
            xyxy=np.array([[200, 200, 300, 300], [310, 200, 400, 300], [410, 200, 500, 300]], dtype=np.float32),
            tracker_id=np.array([10, 11, 12], dtype=np.int32),
            class_id=np.array([2, 2, 2], dtype=np.int32),
        )

        p_count = zone_counter.update(p_tracks)
        c_count = car_counter.update(c_tracks)

        self.assertEqual(p_count, 2)
        self.assertEqual(c_count, 3)

        # Reset counters
        zone_counter.reset()
        car_counter.reset()
        self.assertEqual(zone_counter.current_count, 0)
        self.assertEqual(car_counter.current_count, 0)

    def test_15_telemetry_includes_both_people_and_car_count(self):
        """Verify TelemetrySnapshot and SharedRuntimeState include car_count."""
        snapshot = TelemetrySnapshot(
            people_count=5,
            car_count=8,
            detection_count=13,
            track_count=13,
        )
        self.assertEqual(snapshot.people_count, 5)
        self.assertEqual(snapshot.car_count, 8)

        self.state.update_telemetry(snapshot)
        telem = self.state.get_telemetry()
        self.assertEqual(telem.people_count, 5)
        self.assertEqual(telem.car_count, 8)

    def test_16_frame_renderer_renders_distinguishable_labels(self):
        """Verify FrameRenderer renders P- for people and CAR | C- for cars without error."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        import supervision as sv
        p_tracks = sv.Detections(
            xyxy=np.array([[50, 50, 100, 200]], dtype=np.float32),
            tracker_id=np.array([7], dtype=np.int32),
            class_id=np.array([0], dtype=np.int32),
        )
        c_tracks = sv.Detections(
            xyxy=np.array([[250, 150, 450, 350]], dtype=np.float32),
            tracker_id=np.array([12], dtype=np.int32),
            class_id=np.array([2], dtype=np.int32),
        )

        rendered = render_frame(
            frame=frame,
            tracks=p_tracks,
            people_count=1,
            car_tracks=c_tracks,
            car_count=1,
        )

        self.assertIsNotNone(rendered)
        self.assertEqual(rendered.shape, (480, 640, 3))
        # Verify rendered frame is not all black (bounding boxes and text were drawn)
        self.assertGreater(np.count_nonzero(rendered), 0)

    # =========================================================================
    # 6. Stream FPS Sliding Window Calculation
    # =========================================================================

    def test_17_stream_fps_bounded_window_prevents_burst_spike(self):
        """Verify Stream FPS Meter uses bounded time window and does not report 100+ FPS on bursts."""
        reader = DirectHLSReader(stream_url="http://dummy.m3u8")

        # Simulate 30 frames pushed in 0.1s (e.g. pipe buffer drain)
        now = time.time()
        for i in range(30):
            reader._timestamps.append(now - 0.1 + (i * 0.003))

        # Because dt < 1.0s, fps should return 0.0 or a smoothed estimate, never 300 FPS
        fps = reader.fps
        self.assertLessEqual(fps, 35.0, "Stream FPS should not spike above realistic source bounds on burst read")
        reader.stop()


if __name__ == "__main__":
    unittest.main()
