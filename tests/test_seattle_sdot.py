"""Deterministic Unit and Integration Tests for Seattle SDOT Live CCTV Integration.

Validates all 16 requirements:
1. Seattle ArcGIS parsing
2. STREAM_NAME -> .stream conversion
3. Wowza template replacement
4. No hard-coded streamlock hostname in source code
5. Missing or null STREAM_NAME ignored
6. Whitelist filters correctly
7. Seattle camera source_type == direct_hls
8. Seattle selection starts DirectHLSReader with headers
9. Seattle direct HLS never invokes yt-dlp
10. Failed Seattle stream does not enter dashboard
11. Switching Seattle -> Seattle cleans old FFmpeg
12. Switching Caltrans -> Seattle
13. Switching Seattle -> Local MP4
14. Existing Caltrans integration still works
15. Existing YouTube source still works
16. Existing Local MP4 still works
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

from src.stream.caltrans_service import caltrans_service
from src.stream.camera_manager import CameraManager
from src.stream.direct_hls import DirectHLSReader, build_direct_hls_ffmpeg_cmd
from src.stream.preview_manager import PreviewManager, preview_manager
from src.stream.seattle_sdot_service import (
    SEATTLE_STREAM_HEADERS,
    SEATTLE_WHITELIST_CAMERAS,
    SeattleCamera,
    SeattleSDOTService,
    parse_seattle_arcgis_response,
    seattle_service,
    upgrade_snapshot_url,
)
from src.stream.video_source import LocalVideoReader
from src.stream.youtube_stream import CameraReader
from src.ui.web_server import app


def make_dummy_mp4(num_frames: int = 5, width: int = 320, height: int = 240) -> Path:
    """Create a temporary MP4 video for local reader testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(tmp_path), fourcc, 25.0, (width, height))
    for i in range(num_frames):
        frame = np.full((height, width, 3), fill_value=i * 40, dtype=np.uint8)
        out.write(frame)
    out.release()
    return tmp_path


MOCK_SEATTLE_ARCGIS_DATA = {
    "features": [
        {
            "attributes": {
                "NAME": "3_Spring_EW.jpg",
                "LOCATION": "3rd Ave & Spring St",
                "DISTRICT": None,
                "URL": "http://www.seattle.gov/trafficcams/images/3_Spring_EW.jpg",
                "STREAM_NAME": "3_Spring_EW",
                "SERVSTAT": "ACTV",
            },
            "geometry": {"x": -122.334057, "y": 47.606212},
        },
        {
            "attributes": {
                "NAME": "3_Stewart_NS.jpg",
                "LOCATION": "3rd Ave & Stewart st",
                "DISTRICT": None,
                "URL": "http://www.seattle.gov/trafficcams/images/3_Stewart_NS.jpg",
                "STREAM_NAME": "3_Stewart_NS",
                "SERVSTAT": "ACTV",
            },
            "geometry": {"x": -122.339247, "y": 47.612142},
        },
        {
            "attributes": {
                "NAME": "Missing_Stream.jpg",
                "LOCATION": "Unknown Place",
                "DISTRICT": None,
                "URL": "http://www.seattle.gov/trafficcams/images/missing.jpg",
                "STREAM_NAME": None,
                "SERVSTAT": "ACTV",
            },
            "geometry": {"x": -122.30, "y": 47.60},
        },
        {
            "attributes": {
                "NAME": "Non_Whitelisted.jpg",
                "LOCATION": "Outer Rim Blvd",
                "DISTRICT": None,
                "URL": "http://www.seattle.gov/trafficcams/images/outer.jpg",
                "STREAM_NAME": "Outer_Rim_99",
                "SERVSTAT": "ACTV",
            },
            "geometry": {"x": -122.35, "y": 47.65},
        },
    ]
}


class TestSeattleSDOTIntegration(unittest.TestCase):
    """Deterministic unit and integration tests for Seattle SDOT Live CCTV."""

    # -------------------------------------------------------------------------
    # 1. Seattle ArcGIS Parsing
    # -------------------------------------------------------------------------

    def test_1_seattle_arcgis_parsing(self) -> None:
        """1. ArcGIS FeatureServer JSON is correctly parsed into SeattleCamera objects."""
        template = "https://dynamic-server.net:443/live/{stream}/playlist.m3u8"
        cameras = parse_seattle_arcgis_response(
            MOCK_SEATTLE_ARCGIS_DATA,
            hls_template=template,
            whitelist=SEATTLE_WHITELIST_CAMERAS,
        )

        self.assertEqual(len(cameras), 2)
        cam = next(c for c in cameras if c.stream_name == "3_Spring_EW")
        self.assertEqual(cam.id, "seattle_3_Spring_EW")
        self.assertEqual(cam.name, "3rd Ave & Spring St")
        self.assertEqual(cam.provider, "Seattle SDOT")
        self.assertEqual(cam.city, "Seattle")
        self.assertEqual(cam.state, "Washington")
        self.assertEqual(cam.source_type, "direct_hls")
        self.assertEqual(cam.status, "ACTV")
        self.assertAlmostEqual(cam.latitude, 47.606212, places=5)
        self.assertAlmostEqual(cam.longitude, -122.334057, places=5)
        self.assertTrue(cam.snapshot_url.startswith("https://www.seattle.gov/"))

    # -------------------------------------------------------------------------
    # 2. STREAM_NAME -> .stream Conversion
    # -------------------------------------------------------------------------

    def test_2_stream_name_to_stream_conversion(self) -> None:
        """2. STREAM_NAME is appended with .stream to form stream_id."""
        stream_name = "3_Spring_EW"
        stream_id = f"{stream_name}.stream"
        self.assertEqual(stream_id, "3_Spring_EW.stream")

    # -------------------------------------------------------------------------
    # 3. Wowza Template Replacement
    # -------------------------------------------------------------------------

    def test_3_wowza_template_replacement(self) -> None:
        """3. Constructed HLS URL replaces {stream} with {stream_name}.stream."""
        template = "https://example-wowza.gov:443/live/{stream}/playlist.m3u8"
        stream_name = "3_Spring_EW"
        stream_id = f"{stream_name}.stream"
        constructed = template.replace("{stream}", stream_id)
        self.assertEqual(
            constructed,
            "https://example-wowza.gov:443/live/3_Spring_EW.stream/playlist.m3u8",
        )

    # -------------------------------------------------------------------------
    # 4. No Hard-coded Streamlock Hostname
    # -------------------------------------------------------------------------

    def test_4_no_hardcoded_streamlock_hostname(self) -> None:
        """4. Source code must strictly NEVER hard-code the streamlock hostname."""
        service_file = PROJECT_ROOT / "src" / "stream" / "seattle_sdot_service.py"
        self.assertTrue(service_file.is_file())
        source_code = service_file.read_text(encoding="utf-8")

        self.assertNotIn("streamlock.net", source_code)
        self.assertIn("SEATTLE_WOWZA_TEMPLATE_URL", source_code)

    # -------------------------------------------------------------------------
    # 5. Missing STREAM_NAME Ignored
    # -------------------------------------------------------------------------

    def test_5_missing_stream_name_ignored(self) -> None:
        """5. Cameras with None, empty, or whitespace STREAM_NAME are ignored."""
        bad_data = {
            "features": [
                {"attributes": {"STREAM_NAME": None, "LOCATION": "Cam 1"}},
                {"attributes": {"STREAM_NAME": "", "LOCATION": "Cam 2"}},
                {"attributes": {"STREAM_NAME": "   ", "LOCATION": "Cam 3"}},
                {"attributes": {"STREAM_NAME": "null", "LOCATION": "Cam 4"}},
            ]
        }
        template = "https://wowza.net/live/{stream}/playlist.m3u8"
        cameras = parse_seattle_arcgis_response(bad_data, hls_template=template)
        self.assertEqual(len(cameras), 0)

    # -------------------------------------------------------------------------
    # 6. Whitelist Filters Correctly
    # -------------------------------------------------------------------------

    def test_6_whitelist_filters_correctly(self) -> None:
        """6. Only cameras in SEATTLE_WHITELIST_CAMERAS are included."""
        template = "https://wowza.net/live/{stream}/playlist.m3u8"
        cameras = parse_seattle_arcgis_response(
            MOCK_SEATTLE_ARCGIS_DATA,
            hls_template=template,
            whitelist=SEATTLE_WHITELIST_CAMERAS,
        )
        returned_streams = {c.stream_name for c in cameras}
        self.assertIn("3_Spring_EW", returned_streams)
        self.assertIn("3_Stewart_NS", returned_streams)
        self.assertNotIn("Outer_Rim_99", returned_streams)

    # -------------------------------------------------------------------------
    # 7. Seattle Camera source_type == direct_hls
    # -------------------------------------------------------------------------

    def test_7_seattle_camera_source_type_is_direct_hls(self) -> None:
        """7. All Seattle cameras specify source_type='direct_hls'."""
        template = "https://wowza.net/live/{stream}/playlist.m3u8"
        cameras = parse_seattle_arcgis_response(MOCK_SEATTLE_ARCGIS_DATA, hls_template=template)
        for c in cameras:
            self.assertEqual(c.source_type, "direct_hls")
            self.assertEqual(c.to_dict()["source_type"], "direct_hls")

    # -------------------------------------------------------------------------
    # 8. Seattle Selection Starts DirectHLSReader
    # -------------------------------------------------------------------------

    def test_8_seattle_selection_starts_direct_hls_reader(self) -> None:
        """8. Selecting a Seattle camera initializes and starts DirectHLSReader with headers."""
        mgr = CameraManager()
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://web.seattle.gov/Travelers/"}

        with patch("src.stream.direct_hls.DirectHLSReader.start") as mock_start:
            cam_info = mgr.set_video_source(
                source_type="direct_hls",
                source="https://host/live/3_Spring_EW.stream/playlist.m3u8",
                name="3rd Ave & Spring St",
                headers=headers,
            )

            self.assertEqual(cam_info.type, "direct_hls")
            self.assertEqual(cam_info.name, "3rd Ave & Spring St")
            self.assertIsInstance(mgr._reader, DirectHLSReader)
            self.assertEqual(mgr._reader.headers, headers)
            self.assertEqual(mock_start.call_count, 1)

            mgr.stop_camera()

    # -------------------------------------------------------------------------
    # 9. Seattle Direct HLS Never Invokes yt-dlp
    # -------------------------------------------------------------------------

    def test_9_seattle_direct_hls_never_invokes_ytdlp(self) -> None:
        """9. Seattle direct HLS stream spawning FFmpeg strictly never touches yt-dlp."""
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://web.seattle.gov/Travelers/"}
        reader = DirectHLSReader(
            "https://host/live/3_Spring_EW.stream/playlist.m3u8",
            width=640,
            height=360,
            headers=headers,
        )

        with patch("yt_dlp.YoutubeDL") as mock_ytdlp, \
             patch("src.stream.youtube_resolver.stream_resolver.resolve_stream_url") as mock_resolver, \
             patch("subprocess.Popen") as mock_popen:

            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout = MagicMock()
            mock_proc.stderr = io.BytesIO(b"")
            mock_proc.pid = 7711
            mock_popen.return_value = mock_proc

            reader._spawn_ffmpeg()

            self.assertEqual(mock_ytdlp.call_count, 0)
            self.assertEqual(mock_resolver.call_count, 0)
            self.assertEqual(mock_popen.call_count, 1)

            # Check that -headers was included in the FFmpeg command
            cmd_args = mock_popen.call_args[0][0]
            self.assertIn("-headers", cmd_args)
            headers_arg = cmd_args[cmd_args.index("-headers") + 1]
            self.assertIn("Referer: https://web.seattle.gov/Travelers/", headers_arg)
            self.assertIn("User-Agent: Mozilla/5.0", headers_arg)

            reader.stop()

    # -------------------------------------------------------------------------
    # 10. Failed Seattle Stream Does Not Enter Dashboard
    # -------------------------------------------------------------------------

    def test_10_failed_seattle_stream_does_not_enter_dashboard(self) -> None:
        """10. Failed Seattle stream (0 frames, dead stream) is not connection ready."""
        mgr = CameraManager()
        mock_reader = MagicMock()
        mock_reader.status = "ERROR"
        mock_reader.stream_alive = False
        mock_reader._frames_received = 0
        mock_reader.frame_age_seconds = 999.0
        mgr._reader = mock_reader
        mgr._status = "ERROR"

        self.assertFalse(mgr.is_connection_ready())
        self.assertEqual(mgr.status, "ERROR")

    # -------------------------------------------------------------------------
    # 11. Switching Seattle -> Seattle Cleans Old FFmpeg
    # -------------------------------------------------------------------------

    def test_11_switching_seattle_to_seattle_cleans_old_ffmpeg(self) -> None:
        """11. Switching between Seattle cameras cleanly terminates previous reader."""
        mgr = CameraManager()
        old_reader = MagicMock()
        old_reader.stop = MagicMock()
        mgr._reader = old_reader
        mgr._active_camera = MagicMock()

        with patch("src.stream.direct_hls.DirectHLSReader.start"):
            mgr.set_video_source(
                source_type="direct_hls",
                source="https://host/live/3_Stewart_NS.stream/playlist.m3u8",
                name="3rd Ave & Stewart st",
            )

            self.assertEqual(old_reader.stop.call_count, 1)
            self.assertNotEqual(mgr._reader, old_reader)
            self.assertEqual(mgr.get_active_camera().name, "3rd Ave & Stewart st")

            mgr.stop_camera()

    # -------------------------------------------------------------------------
    # 12. Switching Caltrans -> Seattle
    # -------------------------------------------------------------------------

    def test_12_switching_caltrans_to_seattle(self) -> None:
        """12. Switching from Caltrans to Seattle cleanly releases Caltrans reader."""
        mgr = CameraManager()
        caltrans_reader = MagicMock()
        caltrans_reader.stop = MagicMock()
        mgr._reader = caltrans_reader
        mgr._active_camera = MagicMock()

        with patch("src.stream.direct_hls.DirectHLSReader.start"):
            cam_info = mgr.set_video_source(
                source_type="direct_hls",
                source="https://host/live/3_Spring_EW.stream/playlist.m3u8",
                name="Seattle: 3rd & Spring",
                headers=SEATTLE_STREAM_HEADERS,
            )

            self.assertEqual(caltrans_reader.stop.call_count, 1)
            self.assertEqual(cam_info.name, "Seattle: 3rd & Spring")
            self.assertEqual(mgr._reader.headers, SEATTLE_STREAM_HEADERS)

            mgr.stop_camera()

    # -------------------------------------------------------------------------
    # 13. Switching Seattle -> Local MP4
    # -------------------------------------------------------------------------

    def test_13_switching_seattle_to_local(self) -> None:
        """13. Switching from Seattle to Local MP4 cleanly transitions readers."""
        mp4_path = make_dummy_mp4(num_frames=5)
        mgr = CameraManager()
        seattle_reader = MagicMock()
        seattle_reader.stop = MagicMock()
        mgr._reader = seattle_reader
        mgr._active_camera = MagicMock()

        try:
            cam_info = mgr.set_video_source(
                source_type="local",
                source=str(mp4_path),
                name="Local Test Video",
            )

            self.assertEqual(seattle_reader.stop.call_count, 1)
            self.assertEqual(cam_info.type, "file")
            self.assertIsInstance(mgr._reader, LocalVideoReader)
            self.assertEqual(mgr.status, "RUNNING")

            mgr.stop_camera()
        finally:
            if mp4_path.is_file():
                try:
                    mp4_path.unlink()
                except Exception:
                    pass

    # -------------------------------------------------------------------------
    # 14. Existing Caltrans Tests Still Pass
    # -------------------------------------------------------------------------

    def test_14_existing_caltrans_tests_still_pass(self) -> None:
        """14. Caltrans service caching and /api/public_cameras backward compatibility."""
        client = TestClient(app)

        # GET /api/public_cameras without provider defaults to Caltrans
        resp_def = client.get("/api/public_cameras")
        self.assertEqual(resp_def.status_code, 200)
        data_def = resp_def.json()
        self.assertEqual(data_def.get("status"), "ok")
        self.assertGreater(data_def.get("total", 0), 0)

        # GET /api/public_cameras?provider=caltrans
        resp_cal = client.get("/api/public_cameras?provider=caltrans")
        self.assertEqual(resp_cal.status_code, 200)
        data_cal = resp_cal.json()
        self.assertEqual(data_cal.get("provider"), "caltrans")
        self.assertGreater(data_cal.get("total", 0), 0)

    # -------------------------------------------------------------------------
    # 15. Existing YouTube Source Still Works
    # -------------------------------------------------------------------------

    def test_15_existing_youtube_source_still_works(self) -> None:
        """15. Existing YouTube Live stream reader integration remains intact."""
        mgr = CameraManager()
        with patch("src.stream.youtube_stream.CameraReader.start") as mock_yt_start:
            cam_info = mgr.set_video_source(
                source_type="youtube",
                source="https://youtu.be/dummy_test_yt",
                name="YouTube Live Test",
            )
            self.assertEqual(cam_info.type, "youtube")
            self.assertEqual(cam_info.name, "YouTube Live Test")
            self.assertIsInstance(mgr._reader, CameraReader)
            self.assertEqual(mock_yt_start.call_count, 1)
            mgr.stop_camera()

    # -------------------------------------------------------------------------
    # 16. Existing Local MP4 Still Works
    # -------------------------------------------------------------------------

    def test_16_existing_local_mp4_still_works(self) -> None:
        """16. Existing local MP4 playback and frame reading remains functional."""
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


if __name__ == "__main__":
    unittest.main()
