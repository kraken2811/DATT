"""Tests for YouTube Live and HLS Stream Ingestion (Phase 4.5+).

Verifies:
1. Mock yt-dlp response: audio-only + video formats -> video format selected (preferring HLS H.264 <=720p)
2. Invalid yt-dlp response -> raises RuntimeError
3. FFmpeg command generation -> contains rawvideo, bgr24, scaling, and timeout flags
4. Retry behavior -> retries 3 times on failed startup before raising RuntimeError
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stream.youtube_stream import (
    CameraReader,
    build_ffmpeg_command,
    get_stream_url,
    select_best_video_format,
)
from yt_dlp.utils import DownloadError


class TestYouTubeStream(unittest.TestCase):
    """Test suite for YouTube stream format selection, FFmpeg command generation, and retries."""

    def test_mock_ytdlp_selects_video_format(self) -> None:
        """Verify video format is selected while audio-only formats are excluded."""
        formats = [
            {
                "format_id": "140",
                "url": "https://stream.audio/only.m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "resolution": "audio only",
            },
            {
                "format_id": "18",
                "url": "https://stream.video/360p.mp4",
                "vcodec": "avc1.42001E",
                "acodec": "mp4a.40.2",
                "height": 360,
                "protocol": "https",
            },
            {
                "format_id": "95",
                "url": "https://manifest.googlevideo.com/live/720p.m3u8",
                "vcodec": "avc1.4D401F",
                "acodec": "mp4a.40.2",
                "height": 720,
                "protocol": "m3u8_native",
            },
            {
                "format_id": "96",
                "url": "https://manifest.googlevideo.com/live/1080p.m3u8",
                "vcodec": "avc1.4D4028",
                "acodec": "mp4a.40.2",
                "height": 1080,
                "protocol": "m3u8_native",
            },
        ]

        selected_url = select_best_video_format(formats)
        self.assertEqual(selected_url, "https://manifest.googlevideo.com/live/720p.m3u8")

        # Test within get_stream_url via mock YoutubeDL
        mock_info = {"formats": formats, "title": "Tokyo Live"}
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            url = get_stream_url("https://www.youtube.com/watch?v=mock_video")
            self.assertEqual(url, "https://manifest.googlevideo.com/live/720p.m3u8")

    def test_invalid_ytdlp_response_raises_runtime_error(self) -> None:
        """Verify invalid or failing yt-dlp responses raise a meaningful RuntimeError."""
        # 1. DownloadError from yt-dlp
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = DownloadError("Network unreachable")
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError) as ctx:
                get_stream_url("https://youtu.be/error_test")
            self.assertIn("Failed extracting YouTube stream", str(ctx.exception))

        # 2. None info returned
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = None
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError) as ctx:
                get_stream_url("https://youtu.be/none_test")
            self.assertIn("Failed to extract video info", str(ctx.exception))

        # 3. Only audio formats available
        audio_only_info = {
            "formats": [
                {"url": "https://audio.m4a", "vcodec": "none", "acodec": "mp4a"}
            ]
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = audio_only_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError) as ctx:
                get_stream_url("https://youtu.be/audio_only_test")
            self.assertIn("No valid video stream URL found", str(ctx.exception))

    def test_ffmpeg_command_generation(self) -> None:
        """Verify FFmpeg command contains rawvideo, bgr24, scale filter, and proper probing options."""
        cmd = build_ffmpeg_command(
            ffmpeg_path="ffmpeg",
            stream_url="https://manifest.googlevideo.com/playlist.m3u8",
            width=1280,
            height=720,
        )

        self.assertIn("-f", cmd)
        self.assertEqual(cmd[cmd.index("-f") + 1], "rawvideo")
        self.assertIn("-pix_fmt", cmd)
        self.assertEqual(cmd[cmd.index("-pix_fmt") + 1], "bgr24")
        self.assertIn("-vf", cmd)
        self.assertEqual(cmd[cmd.index("-vf") + 1], "scale=1280:720")
        self.assertIn("-probesize", cmd)
        self.assertIn("-analyzeduration", cmd)
        self.assertIn("-rw_timeout", cmd)
        self.assertIn("-reconnect", cmd)
        self.assertEqual(cmd[-1], "-")

    def test_retry_behavior_retries_three_times(self) -> None:
        """Verify CameraReader retries failed startups up to 3 times before raising RuntimeError."""
        reader = CameraReader("https://youtu.be/fail_test", width=640, height=480)
        attempts = 0

        def mock_get_stream_url(url: str) -> str:
            nonlocal attempts
            attempts += 1
            raise RuntimeError(f"Connection failure on attempt {attempts}")

        with patch("src.stream.youtube_stream.get_stream_url", side_effect=mock_get_stream_url):
            with patch("time.sleep", return_value=None) as mock_sleep:
                with self.assertRaises(RuntimeError) as ctx:
                    reader.start()

                self.assertEqual(attempts, 3)
                self.assertIn("after 3 attempts", str(ctx.exception))
                self.assertGreaterEqual(mock_sleep.call_count, 2)


def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestYouTubeStream)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    run_tests()
