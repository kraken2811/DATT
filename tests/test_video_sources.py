"""Unit and Integration Tests for Local MP4 and YouTube VOD Video Sources.

Tests:
- TEST 1: Local MP4 opens successfully and returns valid frames.
- TEST 2: Local MP4 loops cleanly on EOF when loop=True, terminates when loop=False.
- TEST 3: Invalid local path raises FileNotFoundError.
- TEST 4: YouTube VOD resolves and reads stream.
- TEST 5: Invalid YouTube URL raises RuntimeError.
- TEST 13: Runtime video source switching on CameraManager.
- TEST 14: Proper release of old video source when switching.
"""

from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stream.camera_manager import CameraManager
from src.stream.video_source import LocalVideoReader, YouTubeVODReader


def create_dummy_mp4(num_frames: int = 15, width: int = 320, height: int = 240, fps: float = 30.0) -> Path:
    """Helper to generate a small temporary MP4 file for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(tmp_path), fourcc, fps, (width, height))
    for i in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Draw frame number
        cv2.putText(frame, f"F{i}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        out.write(frame)
    out.release()
    return tmp_path


class TestVideoSources(unittest.TestCase):
    """Test suite for Local MP4 and YouTube VOD video sources."""

    def setUp(self) -> None:
        self.test_mp4 = create_dummy_mp4(num_frames=10, width=320, height=240, fps=30.0)

    def tearDown(self) -> None:
        if self.test_mp4.is_file():
            try:
                self.test_mp4.unlink()
            except Exception:
                pass

    def test_local_mp4_opens_and_reads(self) -> None:
        """TEST 1: Local MP4 opens successfully and yields frames."""
        reader = LocalVideoReader(self.test_mp4, loop=False, target_fps=60.0)
        reader.start()
        try:
            self.assertEqual(reader.status, "RUNNING")
            self.assertEqual(reader.width, 320)
            self.assertEqual(reader.height, 240)

            frame = reader.read(timeout=2.0)
            self.assertIsNotNone(frame)
            assert frame is not None
            self.assertEqual(frame.shape, (240, 320, 3))
            self.assertTrue(reader.stream_alive)
        finally:
            reader.stop()

    def test_local_mp4_loop_behavior(self) -> None:
        """TEST 2: Local MP4 loops cleanly on EOF when loop=True, terminates when loop=False."""
        # 1. loop=True: stream keeps running past EOF
        reader_loop = LocalVideoReader(self.test_mp4, loop=True, target_fps=120.0)
        reader_loop.start()
        try:
            frames_read = 0
            t0 = time.time()
            # Read 25 frames from a 10-frame video -> must loop at least twice
            while frames_read < 25 and (time.time() - t0) < 3.0:
                f = reader_loop.read(timeout=0.2)
                if f is not None:
                    frames_read += 1
            self.assertGreaterEqual(frames_read, 15)
            self.assertFalse(reader_loop.finished)
        finally:
            reader_loop.stop()

        # 2. loop=False: stream finishes cleanly
        reader_no_loop = LocalVideoReader(self.test_mp4, loop=False, target_fps=120.0)
        reader_no_loop.start()
        try:
            t0 = time.time()
            while not reader_no_loop.finished and (time.time() - t0) < 3.0:
                reader_no_loop.read(timeout=0.1)
            self.assertTrue(reader_no_loop.finished)
        finally:
            reader_no_loop.stop()

    def test_invalid_local_path(self) -> None:
        """TEST 3: Non-existent local file path raises FileNotFoundError."""
        invalid_path = Path("data/non_existent_video_12345.mp4")
        reader = LocalVideoReader(invalid_path)
        with self.assertRaises(FileNotFoundError):
            reader.start()
        self.assertEqual(reader.status, "ERROR")

    def test_youtube_vod_resolve_and_read(self) -> None:
        """TEST 4: YouTube VOD resolves URL and reads frames."""
        mock_info = {
            "url": "https://googlevideo.com/mock_mp4_vod.mp4",
            "formats": [
                {"url": "https://googlevideo.com/mock_mp4_vod.mp4", "ext": "mp4", "height": 720, "vcodec": "avc1"}
            ]
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            resolved_url = YouTubeVODReader.resolve_vod_url("https://www.youtube.com/watch?v=sample_vod")
            self.assertEqual(resolved_url, "https://googlevideo.com/mock_mp4_vod.mp4")

    def test_invalid_youtube_vod_url(self) -> None:
        """TEST 5: Invalid YouTube VOD URL raises RuntimeError."""
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            from yt_dlp.utils import DownloadError
            mock_ydl.extract_info.side_effect = DownloadError("Video unavailable")
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError) as ctx:
                YouTubeVODReader.resolve_vod_url("https://www.youtube.com/watch?v=invalid_id")
            self.assertIn("YouTube VOD extraction error", str(ctx.exception))

    def test_runtime_video_source_switch_and_release(self) -> None:
        """TEST 13 & 14: Switch video source at runtime and verify old source is released."""
        manager = CameraManager()
        # 1. Start with local video 1
        cam1 = manager.set_video_source(
            source_type="local",
            source=str(self.test_mp4),
            loop=True,
            name="Source 1",
        )
        self.assertEqual(cam1.type, "file")
        self.assertEqual(manager.status, "RUNNING")
        old_reader = manager._reader
        self.assertIsNotNone(old_reader)

        # Read at least one frame
        frame = manager.read(timeout=1.0)
        self.assertIsNotNone(frame)

        # 2. Switch to another source (or YouTube VOD with mock)
        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", return_value=str(self.test_mp4)):
            cam2 = manager.set_video_source(
                source_type="youtube_vod",
                source="https://www.youtube.com/watch?v=mock_switch",
                name="Source 2 VOD",
            )
            self.assertEqual(cam2.type, "youtube_vod")
            self.assertEqual(manager.status, "RUNNING")

            # Verify old reader was cleanly stopped
            self.assertNotEqual(manager._reader, old_reader)
            self.assertEqual(old_reader.status, "STOPPED")

            # Read frame from new source
            frame2 = manager.read(timeout=1.0)
            self.assertIsNotNone(frame2)

        manager.stop_camera()
        self.assertEqual(manager.status, "STOPPED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
