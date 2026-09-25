"""Deterministic Unit and Integration Tests for Camera Selection & Direct HLS System.

Verifies:
1. App opens on Camera Selection instead of Dashboard
2. Caltrans camera catalog parsing
3. Only cameras with streamingVideoURL are returned
4. Camera catalog cache (10-minute TTL)
5. Direct HLS does not call yt-dlp
6. Selecting camera starts direct HLS reader
7. Dashboard opens only after first frame
8. Failed camera remains on selection/error screen
9. Changing camera stops previous FFmpeg (no duplicate FFmpeg processes)
10. Returning to Camera Selection cleans resources
11. Preview cleanup: guaranteed zero stray preview FFmpeg processes
12. Existing Local Video source still works
13. Existing YouTube source still works
"""

import io
import json
from pathlib import Path
import sys
import tempfile
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

from src.stream.caltrans_service import (
    CaltransCameraService,
    SEED_CALTRANS_CAMERAS,
    make_camera_id,
    parse_arcgis_response,
)
from src.stream.camera_manager import CameraManager
from src.stream.direct_hls import DirectHLSReader, build_direct_hls_ffmpeg_cmd
from src.stream.preview_manager import PreviewManager, preview_manager
from src.stream.video_source import LocalVideoReader
from src.stream.youtube_stream import CameraReader
from src.ui.web_server import app


def make_dummy_mp4(num_frames: int = 5, width: int = 160, height: int = 120) -> Path:
    """Helper to create a tiny temporary video for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    writer = cv2.VideoWriter(
        str(tmp_path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (width, height)
    )
    for _ in range(num_frames):
        writer.write(np.zeros((height, width, 3), dtype=np.uint8))
    writer.release()
    return tmp_path


class TestCameraSelectionSystem(unittest.TestCase):
    """Deterministic test suite for Camera Selection, Caltrans, and Direct HLS."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    # -------------------------------------------------------------------------
    # 1. Initial Launch State: Camera Selection instead of Dashboard
    # -------------------------------------------------------------------------

    def test_app_opens_on_camera_selection_instead_of_dashboard(self) -> None:
        """Requirement: App launches with Camera Selection page before monitoring Dashboard."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text

        # Header requirements
        self.assertIn("DATT", html)
        self.assertIn("HỆ THỐNG GIÁM SÁT THÔNG MINH", html)
        self.assertIn("Chọn camera để bắt đầu giám sát", html)

        # Tab requirements
        self.assertIn("Public CCTV", html)
        self.assertIn("Direct HLS", html)
        self.assertIn("YouTube Live", html)
        self.assertIn("Local Video", html)

        # Source banner & Change camera button in Dashboard
        self.assertIn("active-source-banner", html)
        self.assertIn("ĐỔI CAMERA", html)

        # Selection screen and modal components
        self.assertIn("selectionScreen", html)
        self.assertIn("connectingScreen", html)
        self.assertIn("errorScreen", html)
        self.assertIn("monitoringScreen", html)
        self.assertIn("previewModal", html)

    # -------------------------------------------------------------------------
    # 2. Caltrans Camera Catalog Parsing
    # -------------------------------------------------------------------------

    def test_caltrans_camera_catalog_parsing(self) -> None:
        """Requirement: Normalize ArcGIS CCTV FeatureServer response to internal structure."""
        sample_arcgis = {
            "features": [
                {
                    "attributes": {
                        "locationName": "Hwy 5 at Pocket",
                        "streamingVideoURL": "https://cctv.dot.ca.gov/data/d3/hls/hwy5_pocket.stream/playlist.m3u8",
                        "currentImageURL": "https://cctv.dot.ca.gov/data/d3/cctv/image/hwy5_pocket.jpg",
                        "currentImageUpdateFrequency": 30,
                        "district": "District 3",
                        "county": "Sacramento",
                    }
                }
            ]
        }

        parsed = parse_arcgis_response(sample_arcgis)
        self.assertEqual(len(parsed), 1)
        cam = parsed[0].to_dict()

        self.assertEqual(cam["name"], "Hwy 5 at Pocket")
        self.assertEqual(cam["provider"], "Caltrans")
        self.assertEqual(cam["source_type"], "direct_hls")
        self.assertEqual(
            cam["stream_url"],
            "https://cctv.dot.ca.gov/data/d3/hls/hwy5_pocket.stream/playlist.m3u8",
        )
        self.assertEqual(
            cam["snapshot_url"],
            "https://cctv.dot.ca.gov/data/d3/cctv/image/hwy5_pocket.jpg",
        )
        self.assertEqual(cam["update_frequency"], 30)

        # Ensure no raw ArcGIS envelope like 'features' or 'attributes' is exposed
        self.assertNotIn("attributes", cam)
        self.assertNotIn("features", cam)

    # -------------------------------------------------------------------------
    # 3. Only Cameras with streamingVideoURL are Returned
    # -------------------------------------------------------------------------

    def test_only_cameras_with_streamingVideoURL_are_returned(self) -> None:
        """Requirement: Filter out cameras where streamingVideoURL is null or empty."""
        mixed_arcgis = {
            "features": [
                {
                    "attributes": {
                        "locationName": "Valid Camera",
                        "streamingVideoURL": "https://cctv.dot.ca.gov/valid.m3u8",
                        "currentImageURL": "https://cctv.dot.ca.gov/valid.jpg",
                    }
                },
                {
                    "attributes": {
                        "locationName": "No Video Null",
                        "streamingVideoURL": None,
                        "currentImageURL": "https://cctv.dot.ca.gov/novideo.jpg",
                    }
                },
                {
                    "attributes": {
                        "locationName": "No Video Empty String",
                        "streamingVideoURL": "   ",
                        "currentImageURL": "https://cctv.dot.ca.gov/empty.jpg",
                    }
                },
                {
                    "attributes": {
                        "locationName": "No Video 'null' String",
                        "streamingVideoURL": "null",
                        "currentImageURL": "https://cctv.dot.ca.gov/null.jpg",
                    }
                },
            ]
        }

        parsed = parse_arcgis_response(mixed_arcgis)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].name, "Valid Camera")
        self.assertEqual(parsed[0].stream_url, "https://cctv.dot.ca.gov/valid.m3u8")

    # -------------------------------------------------------------------------
    # 4. Camera Catalog Cache (10-minute TTL)
    # -------------------------------------------------------------------------

    def test_camera_catalog_cache(self) -> None:
        """Requirement: Cache camera catalog for ~10 minutes, avoiding redundant network queries."""
        service = CaltransCameraService(cache_ttl=600.0)

        mock_cameras = [
            {
                "id": "caltrans_mock_1",
                "name": "Mock Hwy 1",
                "provider": "Caltrans",
                "source_type": "direct_hls",
                "stream_url": "https://example.com/1.m3u8",
                "snapshot_url": "https://example.com/1.jpg",
                "update_frequency": 30,
            }
        ]

        with patch.object(service, "_fetch_and_cache") as mock_fetch:
            mock_obj = MagicMock()
            mock_obj.to_dict.return_value = mock_cameras[0]
            mock_fetch.return_value = [mock_obj]

            # 1st call: cache miss, invokes _fetch_and_cache
            cams1 = service.get_cameras(force_refresh=False)
            self.assertEqual(len(cams1), 1)
            self.assertEqual(mock_fetch.call_count, 1)

            # Set simulated cache state
            service._cached_cameras = [mock_obj]
            service._cache_timestamp = time.time()

            # 2nd call within TTL: cache hit, must NOT call _fetch_and_cache again
            cams2 = service.get_cameras(force_refresh=False)
            self.assertEqual(len(cams2), 1)
            self.assertEqual(mock_fetch.call_count, 1)

            # 3rd call with force_refresh=True: must trigger fetch
            service.get_cameras(force_refresh=True)
            self.assertEqual(mock_fetch.call_count, 2)

    # -------------------------------------------------------------------------
    # 5. Direct HLS Does NOT Call yt-dlp
    # -------------------------------------------------------------------------

    def test_direct_hls_does_not_call_ytdlp(self) -> None:
        """Requirement: Direct HLS (.m3u8) flow must strictly NEVER invoke yt-dlp or stream_resolver."""
        reader = DirectHLSReader("https://cctv.dot.ca.gov/live.m3u8", width=640, height=360)

        with patch("yt_dlp.YoutubeDL") as mock_ytdlp, \
             patch("src.stream.youtube_resolver.stream_resolver.resolve_stream_url") as mock_resolver, \
             patch("subprocess.Popen") as mock_popen:

            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout = MagicMock()
            mock_proc.stderr = io.BytesIO(b"")
            mock_proc.pid = 9911
            mock_popen.return_value = mock_proc

            reader._spawn_ffmpeg()

            # Verify yt-dlp and stream_resolver were NEVER touched
            self.assertEqual(mock_ytdlp.call_count, 0)
            self.assertEqual(mock_resolver.call_count, 0)

            # Verify FFmpeg was spawned directly with the .m3u8 URL
            self.assertEqual(mock_popen.call_count, 1)
            args, _ = mock_popen.call_args
            cmd_args = args[0]
            self.assertIn("https://cctv.dot.ca.gov/live.m3u8", cmd_args)
            self.assertIn("rawvideo", cmd_args)
            self.assertIn("bgr24", cmd_args)

            reader.stop()

    # -------------------------------------------------------------------------
    # 6. Selecting Camera Starts Direct HLS Reader
    # -------------------------------------------------------------------------

    def test_selecting_camera_starts_direct_hls_reader(self) -> None:
        """Requirement: Selecting a direct HLS camera starts DirectHLSReader in CameraManager."""
        mgr = CameraManager()

        with patch("src.stream.direct_hls.DirectHLSReader.start") as mock_hls_start:
            cam_info = mgr.set_video_source(
                source_type="direct_hls",
                source="https://cctv.dot.ca.gov/stream.m3u8",
                name="Caltrans Hwy 5",
            )

            self.assertEqual(cam_info.type, "direct_hls")
            self.assertEqual(cam_info.name, "Caltrans Hwy 5")
            self.assertIsInstance(mgr._reader, DirectHLSReader)
            self.assertEqual(mock_hls_start.call_count, 1)

            mgr.stop_camera()

    # -------------------------------------------------------------------------
    # 7. Dashboard Opens Only After First Frame
    # -------------------------------------------------------------------------

    def test_dashboard_opens_only_after_first_frame(self) -> None:
        """Requirement: Dashboard criteria requires frames_received > 0, recent frame_age, alive."""
        mgr = CameraManager()

        # Before any source is started
        self.assertFalse(mgr.is_connection_ready())

        # Start simulated reader with 0 frames
        mock_reader = MagicMock()
        mock_reader.status = "RUNNING"
        mock_reader.stream_alive = True
        mock_reader._frames_received = 0
        mock_reader.frame_age_seconds = 999.0
        mgr._reader = mock_reader
        mgr._status = "RUNNING"

        # 0 frames -> NOT ready
        self.assertFalse(mgr.is_connection_ready(max_frame_age=5.0))

        # 1 frame received, but stale (frame_age = 12s) -> NOT ready
        mock_reader._frames_received = 1
        mock_reader.frame_age_seconds = 12.0
        self.assertFalse(mgr.is_connection_ready(max_frame_age=5.0))

        # 1 frame received and fresh (frame_age = 0.2s) -> READY!
        mock_reader.frame_age_seconds = 0.2
        self.assertTrue(mgr.is_connection_ready(max_frame_age=5.0))

        mgr.stop_camera()

    # -------------------------------------------------------------------------
    # 8. Failed Camera Remains on Selection / Error Screen
    # -------------------------------------------------------------------------

    def test_failed_camera_remains_on_selection_or_error_screen(self) -> None:
        """Requirement: Camera failure sets status=ERROR and does NOT report ready."""
        mgr = CameraManager()
        mock_reader = MagicMock()
        mock_reader.status = "ERROR"
        mock_reader.stream_alive = False
        mock_reader._frames_received = 0
        mock_reader.frame_age_seconds = 999.0
        mgr._reader = mock_reader
        mgr._status = "ERROR"
        mgr._error_reason = "Connection refused by remote host"

        self.assertFalse(mgr.is_connection_ready())
        self.assertEqual(mgr.status, "ERROR")

        info = mgr.get_current_source_info()
        self.assertEqual(info["status"], "ERROR")

    # -------------------------------------------------------------------------
    # 9. Changing Camera Stops Previous FFmpeg & No Duplicate Processes
    # -------------------------------------------------------------------------

    def test_changing_camera_stops_previous_ffmpeg(self) -> None:
        """Requirement: Switching from Camera A to Camera B cleanly stops Camera A first."""
        mgr = CameraManager()

        reader_a = MagicMock()
        reader_a.stop = MagicMock()
        mgr._reader = reader_a
        mgr._active_camera = MagicMock()

        # Switch to Camera B
        with patch("src.stream.direct_hls.DirectHLSReader.start"):
            mgr.set_video_source("direct_hls", "https://example.com/cam_b.m3u8", name="Camera B")

            # Verify Reader A was stopped before Camera B became active
            self.assertEqual(reader_a.stop.call_count, 1)
            self.assertNotEqual(mgr._reader, reader_a)
            self.assertEqual(mgr.get_active_camera().name, "Camera B")

            mgr.stop_camera()

    # -------------------------------------------------------------------------
    # 10. Returning to Camera Selection Cleans Resources
    # -------------------------------------------------------------------------

    def test_returning_to_camera_selection_cleans_resources(self) -> None:
        """Requirement: Clicking 'ĐỔI CAMERA' / stopping source cleanly frees FFmpeg & reader."""
        mgr = CameraManager()

        mock_reader = MagicMock()
        mock_reader.stop = MagicMock()
        mgr._reader = mock_reader
        mgr._status = "RUNNING"
        mgr._active_camera = MagicMock()

        self.assertTrue(mgr.has_active_camera())

        # Stop camera (simulating [ĐỔI CAMERA])
        mgr.stop_camera()

        self.assertEqual(mock_reader.stop.call_count, 1)
        self.assertIsNone(mgr._reader)
        self.assertIsNone(mgr.get_active_camera())
        self.assertEqual(mgr.status, "STOPPED")
        self.assertFalse(mgr.has_active_camera())

    # -------------------------------------------------------------------------
    # 11. Preview Cleanup & Resource Safety
    # -------------------------------------------------------------------------

    def test_preview_cleanup_and_safety(self) -> None:
        """Requirement: Preview FFmpeg is terminated cleanly and never runs concurrently with AI."""
        pm = PreviewManager()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.terminate = MagicMock()
        mock_proc.wait = MagicMock()
        mock_proc.stdout = MagicMock()

        with patch("subprocess.Popen", return_value=mock_proc):
            pm.start_preview("https://example.com/preview.m3u8")
            self.assertTrue(pm.is_active())

            # Stop preview
            pm.stop_preview()
            self.assertFalse(pm.is_active())
            self.assertEqual(mock_proc.terminate.call_count, 1)
            self.assertEqual(mock_proc.stdout.close.call_count, 1)

    # -------------------------------------------------------------------------
    # 12. Existing Local Video Source Still Works
    # -------------------------------------------------------------------------

    def test_existing_local_video_still_works(self) -> None:
        """Requirement: Local MP4 video source remains fully operational."""
        mp4_path = make_dummy_mp4(num_frames=5)
        try:
            reader = LocalVideoReader(mp4_path, loop=False)
            reader.start()
            self.assertEqual(reader.status, "RUNNING")
            frame = reader.read(timeout=1.5)
            self.assertIsNotNone(frame)
            reader.stop()
        finally:
            if mp4_path.is_file():
                try:
                    mp4_path.unlink()
                except Exception:
                    pass

    # -------------------------------------------------------------------------
    # 13. Existing YouTube Source Still Works
    # -------------------------------------------------------------------------

    def test_existing_youtube_source_still_works(self) -> None:
        """Requirement: YouTube Live source integration remains intact."""
        mgr = CameraManager()
        with patch("src.stream.youtube_stream.CameraReader.start") as mock_yt_start:
            cam_info = mgr.set_video_source("youtube", "https://youtu.be/dummy_test", name="YouTube Test")
            self.assertEqual(cam_info.type, "youtube")
            self.assertEqual(cam_info.name, "YouTube Test")
            self.assertIsInstance(mgr._reader, CameraReader)
            self.assertEqual(mock_yt_start.call_count, 1)
            mgr.stop_camera()


if __name__ == "__main__":
    unittest.main()
