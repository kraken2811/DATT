"""Regression Tests for YouTube VOD FFmpeg Pipeline, Diagnostics & Source Switching.

Validates all 10 requirements:
1. YouTubeVODReader does NOT call cv2.VideoCapture(direct_https_url).
2. Mock yt-dlp resolver returns direct URL -> FFmpeg reader created -> frames read correctly.
3. diagnostics() of LocalVideoReader, YouTubeVODReader, and CameraReader do not raise KeyError.
4. Runtime switch: Local MP4 -> YouTube VOD.
5. Runtime switch: YouTube VOD -> Local MP4.
6. stop() cleanly terminates FFmpeg subprocess (no zombies).
7. VOD EOF with loop=False finishes cleanly without infinite restarts.
8. yt-dlp resolver is NOT called on every frame.
9. Reader does not spawn multiple FFmpeg processes while active.
10. YouTube Live (CameraReader) functionality remains functional.
"""

import io
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
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
from src.stream.youtube_stream import CameraReader, build_ffmpeg_command
    
def create_dummy_mp4(num_frames: int = 10, width: int = 320, height: int = 240, fps: float = 30.0) -> Path:
    """Helper to create a temporary MP4 file for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(tmp_path), fourcc, fps, (width, height))
    for i in range(num_frames):
        frame = np.full((height, width, 3), fill_value=i * 20, dtype=np.uint8)
        out.write(frame)
    out.release()
    return tmp_path


class FakeStdoutPipe:
    """Simulates FFmpeg stdout pipe generating raw BGR24 frames."""

    def __init__(self, frame_size: int, max_frames: int = 5):
        self.frame_size = frame_size
        self.max_frames = max_frames
        self.frames_yielded = 0
        self.closed = False

    def read(self, n: int = -1) -> bytes:
        if self.closed or self.frames_yielded >= self.max_frames:
            return b""
        chunk_size = min(n if n > 0 else self.frame_size, self.frame_size)
        self.frames_yielded += 1
        return b"\x55" * chunk_size

    def readline(self) -> bytes:
        return b""

    def close(self) -> None:
        self.closed = True


class FakePopen:
    """Simulates FFmpeg subprocess.Popen."""

    def __init__(self, stdout_pipe: FakeStdoutPipe, pid: int = 12345):
        self.stdout = stdout_pipe
        self.stderr = io.BytesIO(b"")
        self.pid = pid
        self._returncode = None
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self._returncode

    def terminate(self) -> None:
        self.terminated = True
        self._returncode = 0
        self.stdout.close()

    def kill(self) -> None:
        self.killed = True
        self._returncode = -9
        self.stdout.close()

    def wait(self, timeout: float = 2.0) -> int:
        if self._returncode is None:
            self._returncode = 0
        return self._returncode


class TestYouTubeVODRegression(unittest.TestCase):
    """Regression test suite for YouTube VOD FFmpeg ingestion & diagnostics."""

    def setUp(self) -> None:
        self.dummy_mp4 = create_dummy_mp4(num_frames=10, width=320, height=240)

    def tearDown(self) -> None:
        if self.dummy_mp4.is_file():
            try:
                self.dummy_mp4.unlink()
            except Exception:
                pass

    def test_1_youtube_vod_never_calls_cv2_videocapture(self) -> None:
        """Requirement 1: YouTubeVODReader must NOT call cv2.VideoCapture for googlevideo URLs."""
        fake_pipe = FakeStdoutPipe(frame_size=320 * 240 * 3, max_frames=3)
        fake_proc = FakePopen(fake_pipe, pid=1111)

        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", return_value="https://googlevideo.com/videoplayback?id=123"):
            with patch("subprocess.Popen", return_value=fake_proc):
                with patch("cv2.VideoCapture") as mock_cv2_cap:
                    reader = YouTubeVODReader(
                        youtube_url="https://youtu.be/h0C7pdiwCrs",
                        width=320,
                        height=240,
                    )
                    reader.start()
                    try:
                        frame = reader.read(timeout=1.0)
                        self.assertIsNotNone(frame)
                        # Assert OpenCV VideoCapture was NEVER called
                        mock_cv2_cap.assert_not_called()
                    finally:
                        reader.stop()

    def test_2_mock_ytdlp_spawns_ffmpeg_and_reads_frame(self) -> None:
        """Requirement 2: Mock yt-dlp resolver returns direct URL -> FFmpeg reader reads frame."""
        frame_size = 640 * 360 * 3
        fake_pipe = FakeStdoutPipe(frame_size=frame_size, max_frames=5)
        fake_proc = FakePopen(fake_pipe, pid=2222)

        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", return_value="https://googlevideo.com/mock_stream.mp4"):
            with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
                reader = YouTubeVODReader(
                    youtube_url="https://www.youtube.com/watch?v=mock_vod_test",
                    width=640,
                    height=360,
                )
                reader.start()
                try:
                    frame = reader.read(timeout=2.0)
                    self.assertIsNotNone(frame)
                    assert frame is not None
                    self.assertEqual(frame.shape, (360, 640, 3))

                    self.assertTrue(mock_popen.called)
                    # Verify FFmpeg command arguments
                    cmd_args = mock_popen.call_args[0][0]
                    self.assertIn("-f", cmd_args)
                    self.assertIn("rawvideo", cmd_args)
                    self.assertIn("-pix_fmt", cmd_args)
                    self.assertIn("bgr24", cmd_args)
                    self.assertIn("scale=640:360", cmd_args[cmd_args.index("-vf") + 1])
                finally:
                    reader.stop()

    def test_3_diagnostics_no_keyerror_in_camera_manager(self) -> None:
        """Requirement 3: diagnostics() of LocalVideoReader, YouTubeVODReader, CameraReader never cause KeyError."""
        local_reader = LocalVideoReader(self.dummy_mp4, loop=True)
        vod_reader = YouTubeVODReader("https://youtu.be/dummy_test")
        camera_reader = CameraReader("https://youtu.be/dummy_live")

        manager = CameraManager()

        # Check diagnostics dictionary keys directly
        diag_local = local_reader.diagnostics()
        self.assertIsNone(diag_local.get("ffmpeg_alive"))
        self.assertIn("reader_alive", diag_local)

        diag_vod = vod_reader.diagnostics()
        self.assertIn("ffmpeg_alive", diag_vod)
        self.assertIn("reader_alive", diag_vod)

        diag_cam = camera_reader.diagnostics()
        self.assertIn("ffmpeg_alive", diag_cam)
        self.assertIn("reader_alive", diag_cam)

        # Execute manager.read() with each reader and verify no KeyError is raised
        for r in [local_reader, vod_reader, camera_reader]:
            manager._reader = r
            try:
                manager.read(timeout=0.01)
            except KeyError as exc:
                self.fail(f"CameraManager.read() raised KeyError: {exc}")

    def test_4_and_5_source_switching_local_vod_local(self) -> None:
        """Requirements 4 & 5: Runtime source switching Local -> VOD -> Local -> VOD without restarting."""
        manager = CameraManager()
        fake_pipe1 = FakeStdoutPipe(frame_size=320 * 240 * 3, max_frames=20)
        fake_proc1 = FakePopen(fake_pipe1, pid=4441)
        fake_pipe2 = FakeStdoutPipe(frame_size=320 * 240 * 3, max_frames=20)
        fake_proc2 = FakePopen(fake_pipe2, pid=4442)

        # 1. Start Local MP4
        cam1 = manager.set_video_source("local", str(self.dummy_mp4), loop=True, name="Local 1")
        self.assertEqual(cam1.type, "file")
        self.assertEqual(manager.status, "RUNNING")
        f1 = manager.read(timeout=1.0)
        self.assertIsNotNone(f1)

        # 2. Switch to YouTube VOD
        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", return_value="https://googlevideo.com/vod1"):
            with patch("subprocess.Popen", return_value=fake_proc1):
                cam2 = manager.set_video_source("youtube_vod", "https://youtu.be/switch1", name="VOD 1")
                self.assertEqual(cam2.type, "youtube_vod")
                self.assertEqual(manager.status, "RUNNING")
                f2 = manager.read(timeout=1.0)
                self.assertIsNotNone(f2)

        # 3. Switch back to Local MP4
        cam3 = manager.set_video_source("local", str(self.dummy_mp4), loop=True, name="Local 2")
        self.assertEqual(cam3.type, "file")
        self.assertEqual(manager.status, "RUNNING")
        f3 = manager.read(timeout=1.0)
        self.assertIsNotNone(f3)

        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", return_value="https://googlevideo.com/vod2"):
            with patch("subprocess.Popen", return_value=fake_proc2):
                cam4 = manager.set_video_source("youtube_vod", "https://youtu.be/switch2", name="VOD 2")
                self.assertEqual(cam4.type, "youtube_vod")
                self.assertEqual(manager.status, "RUNNING")
                f4 = manager.read(timeout=1.0)
                self.assertIsNotNone(f4)

        # Clean stop
        manager.stop_camera()
        self.assertEqual(manager.status, "STOPPED")

    def test_6_stop_cleanly_terminates_ffmpeg_process(self) -> None:
        """Requirement 6: stop() does not leave FFmpeg process alive."""
        fake_pipe = FakeStdoutPipe(frame_size=320 * 240 * 3, max_frames=50)
        fake_proc = FakePopen(fake_pipe, pid=6666)

        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", return_value="https://googlevideo.com/stream.mp4"):
            with patch("subprocess.Popen", return_value=fake_proc):
                reader = YouTubeVODReader("https://youtu.be/test_cleanup", width=320, height=240)
                reader.start()
                frame = reader.read(timeout=1.0)
                self.assertIsNotNone(frame)
                self.assertIsNotNone(reader._process)

                reader.stop()
                self.assertTrue(fake_proc.terminated)
                self.assertIsNone(reader._process)
                self.assertEqual(reader.status, "STOPPED")

    def test_7_vod_eof_terminates_cleanly_when_loop_false(self) -> None:
        """Requirement 7: VOD EOF with loop=False stops cleanly without restarting."""
        # Yield only 2 frames then EOF
        fake_pipe = FakeStdoutPipe(frame_size=320 * 240 * 3, max_frames=2)
        fake_proc = FakePopen(fake_pipe, pid=7777)

        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", return_value="https://googlevideo.com/stream.mp4"):
            with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
                reader = YouTubeVODReader("https://youtu.be/test_eof", loop=False, width=320, height=240, target_fps=120.0)
                reader.start()
                try:
                    t0 = time.time()
                    while not reader.finished and (time.time() - t0) < 3.0:
                        reader.read(timeout=0.05)

                    self.assertTrue(reader.finished)
                    self.assertFalse(reader.stream_alive)
                    self.assertEqual(reader.status, "VIDEO_FINISHED")
                    # FFmpeg should only have been spawned once, not restarted
                    self.assertEqual(mock_popen.call_count, 1)
                finally:
                    reader.stop()

    def test_8_ytdlp_not_called_per_frame(self) -> None:
        """Requirement 8: yt-dlp is NOT resolved every frame."""
        fake_pipe = FakeStdoutPipe(frame_size=320 * 240 * 3, max_frames=10)
        fake_proc = FakePopen(fake_pipe, pid=8888)

        mock_resolve = MagicMock(return_value="https://googlevideo.com/stream.mp4")
        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", mock_resolve):
            with patch("subprocess.Popen", return_value=fake_proc):
                reader = YouTubeVODReader("https://youtu.be/test_resolve_count", width=320, height=240, target_fps=120.0)
                reader.start()
                try:
                    frames_read = 0
                    for _ in range(5):
                        f = reader.read(timeout=0.2)
                        if f is not None:
                            frames_read += 1
                    self.assertGreaterEqual(frames_read, 2)
                    # Resolve was called ONLY ONCE at startup
                    self.assertEqual(mock_resolve.call_count, 1)
                finally:
                    reader.stop()

    def test_9_no_multiple_ffmpeg_processes_spawned(self) -> None:
        """Requirement 9: Reader does not spawn multiple FFmpeg processes for the same reader session."""
        fake_pipe = FakeStdoutPipe(frame_size=320 * 240 * 3, max_frames=10)
        fake_proc = FakePopen(fake_pipe, pid=9999)

        with patch("src.stream.video_source.YouTubeVODReader.resolve_vod_url", return_value="https://googlevideo.com/stream.mp4"):
            with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
                reader = YouTubeVODReader("https://youtu.be/test_no_duplicate", width=320, height=240)
                reader.start()
                frame = reader.read(timeout=1.0)
                self.assertIsNotNone(frame)
                # Attempt to call start() again
                reader.start()
                try:
                    self.assertEqual(mock_popen.call_count, 1)
                finally:
                    reader.stop()

    def test_10_existing_youtube_live_stream_remains_functional(self) -> None:
        """Requirement 10: Existing YouTube Live CameraReader remains fully functional."""
        cmd = build_ffmpeg_command("ffmpeg", "https://manifest.googlevideo.com/live.m3u8", 1280, 720)
        self.assertIn("scale=1280:720", " ".join(cmd))
        self.assertIn("-reconnect", cmd)

        reader = CameraReader("https://youtu.be/live_test")
        diag = reader.diagnostics()
        self.assertIn("ffmpeg_alive", diag)
        self.assertIn("reader_alive", diag)
        self.assertIn("resolver_metrics", diag)
        self.assertFalse(diag["ffmpeg_alive"])
        self.assertFalse(diag["reader_alive"])


if __name__ == "__main__":
    unittest.main()
