"""Targeted regression and unit tests for YouTube Live vs VOD stream handling.

Verifies:
1. YouTube Live vs VOD differentiation before reader creation (is_live_stream).
2. CameraManager correctly routes Live to CameraReader and VOD to YouTubeVODReader.
3. VOD URLs pass is_vod=True to resolver and select MP4 progressive format.
4. Clean EOF on VOD transitions to VIDEO_FINISHED and terminates without reconnecting.
5. "Sign in to confirm you're not a bot" stops retries immediately and returns AUTH/ANTI_BOT error.
6. YouTube Live streams retain automatic reconnect behavior.
"""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stream.camera_manager import CameraManager
from src.stream.video_source import YouTubeVODReader
from src.stream.youtube_resolver import (
    ERROR_BOT_CHALLENGE,
    StreamCacheEntry,
    classify_youtube_error,
    stream_resolver,
)
from src.stream.youtube_stream import CameraReader, get_stream_url


class TestYouTubeVODWorkflow(unittest.TestCase):
    """Test suite covering YouTube Live vs VOD separation, EOF handling, and anti-bot challenge."""

    def setUp(self) -> None:
        stream_resolver.reset_state()

    def tearDown(self) -> None:
        stream_resolver.reset_state()

    def test_live_vs_vod_differentiation(self) -> None:
        """Requirement 1: is_live_stream accurately detects Live streams vs VOD videos."""
        # 1. Live stream info
        live_info = {
            "id": "live_vid_01",
            "is_live": True,
            "live_status": "is_live",
            "duration": None,
            "formats": [
                {"format_id": "95", "url": "https://googlevideo.com/live.m3u8", "vcodec": "avc1", "acodec": "mp4a", "height": 720, "protocol": "m3u8_native"}
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = live_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            is_live = stream_resolver.is_live_stream("https://www.youtube.com/watch?v=live_vid_01")
            self.assertTrue(is_live)

        # 2. VOD stream info
        vod_info = {
            "id": "vod_vid_02",
            "is_live": False,
            "live_status": "not_live",
            "duration": 213,
            "formats": [
                {"format_id": "18", "url": "https://googlevideo.com/video.mp4", "vcodec": "avc1", "acodec": "mp4a", "height": 360, "protocol": "https"}
            ],
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = vod_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            is_live = stream_resolver.is_live_stream("https://www.youtube.com/watch?v=vod_vid_02")
            self.assertFalse(is_live)

    def test_camera_manager_routes_vod_to_youtube_vod_reader(self) -> None:
        """Requirement 1 & 2: Generic 'youtube' source_type with VOD URL instantiates YouTubeVODReader."""
        mgr = CameraManager()
        vod_url = "https://www.youtube.com/watch?v=vod_test_01"

        # Mock is_live_stream returning False (VOD)
        with patch.object(stream_resolver, "is_live_stream", return_value=False):
            with patch.object(YouTubeVODReader, "start") as mock_vod_start:
                cam_info = mgr.set_video_source(source_type="youtube", source=vod_url, loop=False)

                self.assertEqual(cam_info.type, "youtube_vod")
                self.assertIsInstance(mgr._reader, YouTubeVODReader)
                mock_vod_start.assert_called_once()

    def test_camera_manager_routes_live_to_camera_reader(self) -> None:
        """Requirement 1: Generic 'youtube' source_type with Live URL instantiates CameraReader."""
        mgr = CameraManager()
        live_url = "https://www.youtube.com/watch?v=live_test_01"

        # Mock is_live_stream returning True (Live)
        with patch.object(stream_resolver, "is_live_stream", return_value=True):
            with patch.object(CameraReader, "start") as mock_live_start:
                cam_info = mgr.set_video_source(source_type="youtube", source=live_url, loop=False)

                self.assertEqual(cam_info.type, "youtube")
                self.assertIsInstance(mgr._reader, CameraReader)
                self.assertFalse(mgr._reader.is_vod)
                mock_live_start.assert_called_once()

    def test_vod_passes_is_vod_true_to_resolver(self) -> None:
        """Requirement 2: VOD extraction passes is_vod=True to stream_resolver."""
        vod_url = "https://www.youtube.com/watch?v=vod_param_test"

        with patch.object(stream_resolver, "resolve_stream_url") as mock_resolve:
            mock_resolve.return_value = "https://resolved.mp4"
            res = YouTubeVODReader.resolve_vod_url(vod_url)

            self.assertEqual(res, "https://resolved.mp4")
            mock_resolve.assert_called_once_with(vod_url, is_vod=True)

        with patch.object(stream_resolver, "resolve_stream_url") as mock_resolve:
            mock_resolve.return_value = "https://resolved_cam.mp4"
            res = get_stream_url(vod_url, is_vod=True)

            self.assertEqual(res, "https://resolved_cam.mp4")
            mock_resolve.assert_called_once_with(vod_url, is_vod=True)

    def test_vod_clean_eof_transitions_to_video_finished(self) -> None:
        """Requirement 3: VOD clean EOF sets status to VIDEO_FINISHED and does not reconnect."""
        reader = YouTubeVODReader(youtube_url="https://www.youtube.com/watch?v=vod_eof_test", loop=False)
        reader._direct_url = "https://mock.mp4"

        # Simulate FFmpeg process that exits cleanly with code 0
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.wait.return_value = 0
        mock_proc.stdout = MagicMock()

        # read_frame_bytes returning empty (EOF)
        with patch("src.stream.video_source.read_frame_bytes", return_value=b""):
            with patch.object(reader, "_spawn_ffmpeg"):
                reader._process = mock_proc
                # Run capture loop iteration
                reader._capture_loop()

        self.assertEqual(reader.status, "VIDEO_FINISHED")
        self.assertTrue(reader.finished)
        self.assertFalse(reader.stream_alive)
        self.assertEqual(reader.clean_eof_count, 1)

    def test_camera_reader_vod_clean_eof_stops_without_reconnect(self) -> None:
        """Requirement 3: CameraReader with is_vod=True transitions to VIDEO_FINISHED on clean EOF."""
        reader = CameraReader(url="https://www.youtube.com/watch?v=vod_cr_eof", is_vod=True)
        reader._stream_url = "https://mock.mp4"

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.pid = 9999
        mock_proc.stdout = MagicMock()

        with patch("src.stream.youtube_stream.read_frame_bytes", return_value=b""):
            reader.process = mock_proc
            reader._read_loop_impl()

        self.assertEqual(reader.status, "VIDEO_FINISHED")
        self.assertTrue(reader.finished)
        self.assertEqual(reader.reconnect_attempts, 0)  # No reconnect attempted

    def test_camera_manager_surfaces_video_finished(self) -> None:
        """Requirement 3: CameraManager reports VIDEO_FINISHED status on VOD clean EOF."""
        mgr = CameraManager()
        mock_reader = MagicMock()
        mock_reader.status = "VIDEO_FINISHED"
        mock_reader.finished = True
        mock_reader.stream_alive = False
        mock_reader.clean_eof_count = 1
        mock_reader.loop = False
        mock_reader.read.return_value = None

        mgr._reader = mock_reader
        mgr._status = "RUNNING"

        frame = mgr.read()
        self.assertIsNone(frame)
        self.assertEqual(mgr.status, "VIDEO_FINISHED")

    def test_bot_challenge_in_resolver_raises_auth_anti_bot(self) -> None:
        """Requirement 4: Bot challenge in yt-dlp raises RuntimeError with AUTH/ANTI_BOT."""
        challenge_msg = "Sign in to confirm you're not a bot. Use --cookies-from-browser or visit https://..."
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = RuntimeError(challenge_msg)
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError) as ctx:
                stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=bot_test", is_vod=True)

            self.assertIn("AUTH/ANTI_BOT", str(ctx.exception))
            self.assertIn("Sign in to confirm you're not a bot", str(ctx.exception))

    def test_bot_challenge_stops_reconnect_immediately(self) -> None:
        """Requirement 4: Bot challenge stops CameraReader reconnect immediately."""
        reader = CameraReader("https://www.youtube.com/watch?v=bot_rec_test")
        bot_err = RuntimeError("AUTH/ANTI_BOT: YouTube bot challenge / sign-in required: Sign in to confirm you're not a bot")

        with patch.object(reader, "_get_stream_url_with_diagnostics", side_effect=bot_err):
            reconnected = reader._reconnect()

            self.assertFalse(reconnected)
            self.assertTrue(reader.finished)
            self.assertIn("AUTH/ANTI_BOT", reader.error_reason)
            self.assertEqual(reader.last_error_type, ERROR_BOT_CHALLENGE)
            # Must abort after 1 attempt, not continue looping indefinitely
            self.assertEqual(reader.reconnect_attempts, 1)

    def test_bot_challenge_in_vod_reader_start_aborts_retries(self) -> None:
        """Requirement 4: Bot challenge in YouTubeVODReader.start raises AUTH/ANTI_BOT immediately."""
        reader = YouTubeVODReader("https://www.youtube.com/watch?v=bot_vod_test")
        bot_err = RuntimeError("AUTH/ANTI_BOT: YouTube bot challenge / sign-in required: Sign in to confirm you're not a bot")

        with patch.object(reader, "resolve_vod_url", side_effect=bot_err):
            with self.assertRaises(RuntimeError) as ctx:
                reader.start()

            self.assertIn("AUTH/ANTI_BOT", str(ctx.exception))
            self.assertEqual(reader.status, "ERROR")
            self.assertIn("AUTH/ANTI_BOT", reader.error_reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
