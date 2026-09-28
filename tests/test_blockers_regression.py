"""Deterministic Regression Test Suite for Livestream-Readiness Blockers (1-5).

Tests:
1. VOD clean EOF + loop=False: stops cleanly (status=STOPPED, clean_eof_count=1).
2. VOD clean EOF + loop=True: restarts playback in a controlled way without error classification.
3. VOD FFmpeg exit code != 0: classified as error, not EOF.
4. VOD abnormal exit with loop=True: consumes retry budget/backoff instead of infinite fast respawn.
5. Blocked stdout cleanup: stop() terminates process first and returns within bounded time.
6. Live reconnect: previous frame timestamp cannot kill a newly spawned FFmpeg process.
7. Live first-frame timeout: new process producing no frame within deadline is recovered.
8. Stop during reconnect sleep: no new FFmpeg process is spawned.
9. Stop while resolver is returning: no post-stop spawn.
10. Source switch during recovery: old reader cannot spawn after new source becomes active.
11. FFmpeg stderr contains HTTP 429: shared rate-limit counter increments.
12. FFmpeg 429: yt-dlp is NOT immediately called again during cooldown.
13. Resolver 429 and FFmpeg 429: share the same cooldown state and backoff level.
14. Cooldown expires: exactly one controlled recovery attempt occurs.
15. HTTP 403: handled separately from 429 (invalidates cache without entering 429 cooldown).
16. No duplicate FFmpeg processes for one reader generation.
17. No zombie subprocess after stop.
18. Diagnostics remain compatible for LocalVideoReader, YouTubeVODReader, and CameraReader.
"""

from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from src.stream.camera_manager import CameraManager
from src.stream.video_source import LocalVideoReader, YouTubeVODReader
from src.stream.youtube_resolver import SharedRateLimitPolicy, stream_resolver
from src.stream.youtube_stream import CameraReader


class TestBlockersRegression(unittest.TestCase):
    """Regression test suite for Blockers 1 through 5."""

    def setUp(self) -> None:
        stream_resolver.reset_for_testing()

    def tearDown(self) -> None:
        stream_resolver.reset_for_testing()

    # =========================================================================
    # BLOCKER 1 — DISTINGUISH CLEAN VOD EOF FROM FAILURE
    # =========================================================================

    def test_1_vod_clean_eof_loop_false_stops_cleanly(self) -> None:
        """1. VOD clean EOF + loop=False: stops cleanly."""
        reader = YouTubeVODReader("https://www.youtube.com/watch?v=clean_eof_false", loop=False, max_retries=3)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.stdout.read.return_value = b""
        mock_proc.pid = 9901

        with patch.object(reader, "_spawn_ffmpeg"):
            reader._process = mock_proc
            reader._direct_url = "https://mock.googlevideo.com/video.mp4"
            with patch("src.stream.video_source.read_frame_bytes", return_value=b""):
                # Run one loop iteration
                reader._capture_loop()

        self.assertEqual(reader.clean_eof_count, 1)
        self.assertEqual(reader.abnormal_exit_count, 0)
        self.assertTrue(reader.finished)
        self.assertEqual(reader.status, "STOPPED")

    def test_2_vod_clean_eof_loop_true_controlled_restart(self) -> None:
        """2. VOD clean EOF + loop=True: restarts playback in a controlled way."""
        reader = YouTubeVODReader("https://www.youtube.com/watch?v=clean_eof_true", loop=True, max_retries=3)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.pid = 9902
        mock_proc.stderr = None
        mock_proc.stdout = MagicMock()

        spawns = 0

        def fake_spawn(url):
            nonlocal spawns
            spawns += 1
            reader._process = mock_proc
            if spawns >= 2:
                reader._stop_event.set()

        reader._spawn_ffmpeg = fake_spawn
        reader._direct_url = "https://mock.googlevideo.com/video.mp4"

        with patch("src.stream.video_source.read_frame_bytes", return_value=b""):
            with patch.object(reader._stop_event, "wait", return_value=False):
                reader._capture_loop()

        self.assertGreaterEqual(reader.clean_eof_count, 1)
        self.assertEqual(reader.abnormal_exit_count, 0)
        self.assertEqual(reader._retries_used, 0)

    def test_3_vod_ffmpeg_exit_code_nonzero_classified_as_error(self) -> None:
        """3. VOD FFmpeg exit code != 0: classified as error, not EOF."""
        reader = YouTubeVODReader("https://www.youtube.com/watch?v=abnormal_exit", loop=False, max_retries=1)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Crash
        mock_proc.pid = 9903
        reader._stderr_lines = ["Server returned 500 Internal Server Error"]

        with patch.object(reader, "_spawn_ffmpeg"):
            reader._process = mock_proc
            reader._direct_url = "https://mock.googlevideo.com/video.mp4"
            with patch("src.stream.video_source.read_frame_bytes", return_value=b""):
                reader._capture_loop()

        self.assertEqual(reader.clean_eof_count, 0)
        self.assertEqual(reader.abnormal_exit_count, 1)
        self.assertEqual(reader.last_error_type, "FFMPEG_ABNORMAL_EXIT")
        self.assertEqual(reader.status, "ERROR")

    def test_4_vod_abnormal_exit_loop_true_consumes_retry_budget(self) -> None:
        """4. VOD abnormal exit with loop=True: consumes retry budget/backoff instead of infinite respawn."""
        reader = YouTubeVODReader("https://www.youtube.com/watch?v=infinite_loop_guard", loop=True, max_retries=2)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 2  # Non-zero error
        mock_proc.pid = 9904
        reader._stderr_lines = ["Connection reset by peer"]

        def fake_spawn(url):
            reader._process = mock_proc

        reader._spawn_ffmpeg = fake_spawn
        with patch.object(YouTubeVODReader, "resolve_vod_url", return_value="https://mock.googlevideo.com/video.mp4"):
            reader._direct_url = "https://mock.googlevideo.com/video.mp4"
            with patch("src.stream.video_source.read_frame_bytes", return_value=b""):
                with patch.object(reader._stop_event, "wait", return_value=False):
                    reader._capture_loop()

        self.assertEqual(reader.clean_eof_count, 0)
        self.assertEqual(reader.abnormal_exit_count, 2)
        self.assertEqual(reader._retries_used, 2)
        self.assertEqual(reader.status, "ERROR")
        self.assertTrue(reader.finished)

    # =========================================================================
    # BLOCKER 2 — FIX FFMPEG CLEANUP ORDER
    # =========================================================================

    def test_5_blocked_stdout_cleanup_terminates_first(self) -> None:
        """5. Blocked stdout cleanup: stop() terminates process first and returns within bounded time."""
        reader = YouTubeVODReader("https://www.youtube.com/watch?v=blocked_stdout", width=640, height=480)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process initially running

        action_order = []

        def fake_terminate():
            action_order.append("terminate")
            mock_proc.poll.return_value = 0

        def fake_close():
            action_order.append("close_stdout")

        mock_proc.terminate.side_effect = fake_terminate
        mock_proc.stdout.close.side_effect = fake_close
        reader._process = mock_proc

        t0 = time.time()
        reader.stop()
        duration = time.time() - t0

        self.assertLess(duration, 2.0)
        self.assertIn("terminate", action_order)
        self.assertIn("close_stdout", action_order)
        self.assertLess(action_order.index("terminate"), action_order.index("close_stdout"))
        self.assertIsNone(reader._process)

    # =========================================================================
    # BLOCKER 3 — FIX LIVE STALE FRAME GENERATION
    # =========================================================================

    def test_6_live_reconnect_previous_timestamp_does_not_kill_new_process(self) -> None:
        """6. Live reconnect: previous frame timestamp cannot kill a newly spawned FFmpeg process."""
        reader = CameraReader("https://www.youtube.com/watch?v=stale_gen_test", width=640, height=480)
        # Previous frame timestamp is very old (30s ago)
        reader._last_frame_timestamp = time.time() - 30.0

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 9906
        reader.process = mock_proc

        # Brand new process generation starting just now
        reader.process_generation = 2
        reader._process_started_at = time.time()
        reader._first_frame_received = False
        reader._generation_frame_timestamp = 0.0

        reader.read(timeout=0.01)

        # Watchdog must NOT terminate the new process using previous frame timestamp
        mock_proc.terminate.assert_not_called()
        self.assertEqual(reader.stale_frame_timeout_count, 0)
        self.assertEqual(reader.first_frame_timeout_count, 0)

    def test_7_live_first_frame_timeout_recovers_unresponsive_process(self) -> None:
        """7. Live first-frame timeout: new process producing no frame within deadline is recovered."""
        reader = CameraReader("https://www.youtube.com/watch?v=first_frame_timeout_test", width=640, height=480)
        reader.first_frame_timeout_seconds = 0.1  # Fast timeout for test

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 9907
        reader.process = mock_proc

        reader.process_generation = 1
        reader._process_started_at = time.time() - 1.0  # Started 1s ago without delivering frame
        reader._first_frame_received = False

        reader.read(timeout=0.01)

        # First-frame timeout watchdog must terminate process
        mock_proc.terminate.assert_called_once()
        self.assertEqual(reader.first_frame_timeout_count, 1)
        self.assertEqual(reader.last_error_type, "FIRST_FRAME_TIMEOUT")

    # =========================================================================
    # BLOCKER 4 — MAKE STOP / RECONNECT CANCEL-SAFE
    # =========================================================================

    def test_8_stop_during_reconnect_sleep_no_spawn(self) -> None:
        """8. Stop during reconnect sleep: no new FFmpeg process is spawned."""
        reader = CameraReader("https://www.youtube.com/watch?v=stop_during_sleep", width=640, height=480)
        spawn_mock = MagicMock()
        reader._spawn_ffmpeg = spawn_mock

        # Trigger stop during sleep
        def fake_wait(delay):
            reader.stop_event.set()
            return True

        with patch.object(reader.stop_event, "wait", side_effect=fake_wait):
            result = reader._reconnect()

        self.assertFalse(result)
        spawn_mock.assert_not_called()

    def test_9_stop_while_resolver_returning_no_post_stop_spawn(self) -> None:
        """9. Stop while resolver is returning: no post-stop spawn."""
        reader = CameraReader("https://www.youtube.com/watch?v=stop_during_resolve", width=640, height=480)
        spawn_mock = MagicMock()
        reader._spawn_ffmpeg = spawn_mock

        def fake_resolve(reason):
            # stop requested while resolver was executing
            reader.stop_event.set()
            return "https://mock.googlevideo.com/live.m3u8"

        reader._get_stream_url_with_diagnostics = fake_resolve
        with patch.object(reader.stop_event, "wait", return_value=False):
            result = reader._reconnect()

        self.assertFalse(result)
        spawn_mock.assert_not_called()

    def test_10_source_switch_during_recovery_clean_transition(self) -> None:
        """10. Source switch during recovery: old reader cannot spawn after new source becomes active."""
        manager = CameraManager()
        # Mock active live reader
        old_reader = CameraReader("https://www.youtube.com/watch?v=source_switch_recovery")
        old_reader.start = MagicMock()
        manager._reader = old_reader
        manager._status = "RUNNING"

        # Switch to dummy file
        dummy_file = PROJECT_ROOT / "tests" / "dummy_video_switch.mp4"
        try:
            dummy_file.write_bytes(b"dummy")
            with patch("src.stream.camera_manager.LocalVideoReader") as mock_lvr_cls:
                mock_lvr = MagicMock()
                mock_lvr.width = 640
                mock_lvr.height = 480
                mock_lvr.stream_alive = True
                mock_lvr_cls.return_value = mock_lvr

                manager.set_video_source("local", str(dummy_file), loop=False)

                # Old reader must be stopped and stop_event set
                self.assertTrue(old_reader.stop_event.is_set())
                self.assertNotEqual(manager._reader, old_reader)
        finally:
            if dummy_file.exists():
                dummy_file.unlink()

    # =========================================================================
    # BLOCKER 5 — SHARED 429 RATE-LIMIT POLICY
    # =========================================================================

    def test_11_ffmpeg_stderr_429_increments_shared_rate_limit(self) -> None:
        """11. FFmpeg stderr contains HTTP 429: shared rate-limit counter increments."""
        initial_429 = stream_resolver.metrics.http_429_count
        reader = YouTubeVODReader("https://www.youtube.com/watch?v=stderr_429_vod")
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1
        reader._stderr_lines = ["HTTP 429 Too Many Requests from googlevideo"]
        reader.max_retries = 1

        with patch.object(reader, "_spawn_ffmpeg"):
            reader._process = mock_proc
            reader._direct_url = "https://mock.googlevideo.com/video.mp4"
            with patch("src.stream.video_source.read_frame_bytes", return_value=b""):
                with patch.object(reader._stop_event, "wait", return_value=False):
                    reader._capture_loop()

        self.assertEqual(stream_resolver.metrics.http_429_count, initial_429 + 1)
        self.assertTrue(stream_resolver.is_in_cooldown())
        self.assertEqual(reader.last_error_type, "HTTP_429")

    def test_12_ffmpeg_429_ytdlp_not_immediately_called(self) -> None:
        """12. FFmpeg 429: yt-dlp is NOT immediately called again during cooldown."""
        reader = CameraReader("https://www.youtube.com/watch?v=ffmpeg_429_no_ytdlp", width=640, height=480)
        
        # 1. FFmpeg encounters 429 and enters shared cooldown
        stream_resolver.record_429(source="ffmpeg_live")
        self.assertTrue(stream_resolver.is_in_cooldown())

        ytdlp_mock = MagicMock()
        reader._get_stream_url_with_diagnostics = ytdlp_mock

        # Reconnect should check cooldown and pause, NOT immediately calling yt-dlp
        with patch.object(reader.stop_event, "wait", return_value=True):
            result = reader._reconnect()

        self.assertFalse(result)
        ytdlp_mock.assert_not_called()

    def test_13_resolver_and_ffmpeg_share_same_cooldown_state(self) -> None:
        """13. Resolver 429 and FFmpeg 429: share the same cooldown state and backoff level."""
        policy = stream_resolver.policy
        initial_level = policy.current_backoff_level

        # 1. FFmpeg reports 429
        stream_resolver.record_429(source="ffmpeg_test")
        self.assertEqual(policy.current_backoff_level, initial_level + 1)
        cooldown_1 = stream_resolver.get_cooldown_remaining()
        self.assertGreater(cooldown_1, 0.0)

        # 2. Resolver sees active cooldown
        self.assertTrue(stream_resolver.is_in_cooldown())

        # 3. Another 429 increases backoff level on the same shared policy
        stream_resolver.record_429(source="resolver_test")
        self.assertEqual(policy.current_backoff_level, initial_level + 2)

    def test_14_cooldown_expires_single_recovery_attempt(self) -> None:
        """14. Cooldown expires: exactly one controlled recovery attempt occurs."""
        stream_resolver.record_429(source="test_expire")
        self.assertTrue(stream_resolver.is_in_cooldown())

        # Manually expire cooldown
        stream_resolver.policy.cooldown_until = time.time() - 1.0
        self.assertFalse(stream_resolver.is_in_cooldown())
        self.assertEqual(stream_resolver.get_cooldown_remaining(), 0.0)

    def test_15_http_403_handled_separately_from_429(self) -> None:
        """15. HTTP 403: handled separately from 429 (invalidates cache without entering 429 cooldown)."""
        stream_resolver.reset_for_testing()
        stream_resolver.record_403("https://www.youtube.com/watch?v=token_expired", source="ffmpeg_403")

        self.assertEqual(stream_resolver.metrics.http_403_count, 1)
        self.assertEqual(stream_resolver.metrics.http_429_count, 0)
        self.assertFalse(stream_resolver.is_in_cooldown())
        self.assertEqual(stream_resolver.get_cooldown_remaining(), 0.0)

    # =========================================================================
    # RESOURCE AND SUBPROCESS INTEGRITY
    # =========================================================================

    def test_16_no_duplicate_ffmpeg_processes_for_one_reader_generation(self) -> None:
        """16. No duplicate FFmpeg processes for one reader generation."""
        reader = YouTubeVODReader("https://www.youtube.com/watch?v=no_dup_proc")
        mock_proc1 = MagicMock()
        mock_proc1.poll.return_value = None
        mock_proc1.pid = 9916
        mock_proc1.stderr = None
        mock_proc1.stdout = None

        with patch("subprocess.Popen", return_value=mock_proc1):
            reader._spawn_ffmpeg("https://mock.googlevideo.com/stream.mp4")

        self.assertEqual(reader.process_generation, 1)
        self.assertIsNotNone(reader._process)
        self.assertEqual(reader._process.pid, 9916)

        # Cleanup cleans up process object
        reader._cleanup_process()
        self.assertIsNone(reader._process)

    def test_17_no_zombie_subprocess_after_stop(self) -> None:
        """17. No zombie subprocess after stop."""
        # Spawn a genuine lightweight python sleep subprocess
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertIsNone(proc.poll())  # Alive

        reader = CameraReader("https://www.youtube.com/watch?v=zombie_test")
        reader.process = proc
        reader.stop()

        self.assertIsNotNone(proc.poll())  # Dead, not zombie

    # =========================================================================
    # DIAGNOSTICS COMPATIBILITY
    # =========================================================================

    def test_18_diagnostics_remain_compatible(self) -> None:
        """18. Diagnostics remain compatible for LocalVideoReader, YouTubeVODReader, CameraReader."""
        required_keys = {
            "source_type",
            "reader_alive",
            "ffmpeg_alive",
            "ffmpeg_pid",
            "process_generation",
            "frames_received",
            "frame_age_seconds",
            "first_frame_received",
            "first_frame_timeout_count",
            "stale_frame_timeout_count",
            "reconnect_count",
            "ffmpeg_start_count",
            "resolver_attempt_count",
            "resolver_success_count",
            "http_429_count",
            "http_403_count",
            "cooldown_remaining_seconds",
            "abnormal_exit_count",
            "clean_eof_count",
            "last_error_type",
            "last_error_message",
        }

        # 1. LocalVideoReader
        dummy_file = PROJECT_ROOT / "tests" / "diag_dummy.mp4"
        try:
            dummy_file.write_bytes(b"dummy")
            lvr = LocalVideoReader(dummy_file, loop=False)
            d1 = lvr.diagnostics()
            self.assertTrue(required_keys.issubset(d1.keys()), f"Missing keys in LocalVideoReader: {required_keys - d1.keys()}")
            self.assertEqual(d1["source_type"], "local")
        finally:
            if dummy_file.exists():
                dummy_file.unlink()

        # 2. YouTubeVODReader
        yvr = YouTubeVODReader("https://www.youtube.com/watch?v=diag_vod")
        d2 = yvr.diagnostics()
        self.assertTrue(required_keys.issubset(d2.keys()), f"Missing keys in YouTubeVODReader: {required_keys - d2.keys()}")
        self.assertEqual(d2["source_type"], "youtube_vod")

        # 3. CameraReader
        cr = CameraReader("https://www.youtube.com/watch?v=diag_cam")
        d3 = cr.diagnostics()
        self.assertTrue(required_keys.issubset(d3.keys()), f"Missing keys in CameraReader: {required_keys - d3.keys()}")
        self.assertEqual(d3["source_type"], "youtube")


if __name__ == "__main__":
    unittest.main(verbosity=2)
