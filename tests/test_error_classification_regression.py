"""Deterministic Regression Tests for YouTube Error Classification and Reconnect Behavior.

Covers:
1. Error text: 'No video formats found!' -> NO_FORMATS, no 429 increment, no cooldown.
2. Error text: 'HTTP Error 429: Too Many Requests' -> HTTP_429, record_429 called, cooldown active.
3. Error text: 'HTTP Error 403: Forbidden' -> HTTP_403, record_403 called, 429 count unchanged.
4. Error text: 'Sign in to confirm you're not a bot' -> BOT_CHALLENGE, not 429.
5. Generic DownloadError -> EXTRACTOR_ERROR, no 429 cooldown.
6. FFmpeg non-zero exit without HTTP status -> FFMPEG_ERROR, no 429 cooldown.
7. FFmpeg stderr explicitly contains 429 -> HTTP_429, shared cooldown activates.
8. NO_FORMATS during camera reconnect -> bounded normal backoff, no shared 429 cooldown.
9. After one NO_FORMATS failure, a later successful resolver response recovers stream.
10. Stale/dead FFmpeg PID is cleared from diagnostics after cleanup (ffmpeg_pid is None, ffmpeg_alive is False).
"""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stream.youtube_resolver import (
    ERROR_BOT_CHALLENGE,
    ERROR_EXTRACTOR_ERROR,
    ERROR_FFMPEG_ERROR,
    ERROR_HTTP_403,
    ERROR_HTTP_429,
    ERROR_NETWORK_ERROR,
    ERROR_NO_FORMATS,
    ERROR_VIDEO_UNAVAILABLE,
    classify_youtube_error,
    stream_resolver,
)
from src.stream.youtube_stream import CameraReader
from src.stream.video_source import YouTubeVODReader
from yt_dlp.utils import DownloadError


class TestErrorClassificationRegression(unittest.TestCase):
    """Deterministic regression tests for YouTube error classification and reconnect behavior."""

    def setUp(self) -> None:
        stream_resolver.reset_for_testing()

    def tearDown(self) -> None:
        stream_resolver.reset_for_testing()

    # =========================================================================
    # 1. NO_FORMATS Classification and Rate-Limit Isolation
    # =========================================================================

    def test_1_no_video_formats_found_classification(self) -> None:
        """1. 'No video formats found!' classified as NO_FORMATS; does NOT increment 429 or activate cooldown."""
        err_msg = "ERROR: [youtube] Cp4RRAEgpeU: No video formats found!"
        cat = classify_youtube_error(err_msg)
        self.assertEqual(cat, ERROR_NO_FORMATS)

        # Simulate resolver encountering this error
        initial_429 = stream_resolver.metrics.http_429_count
        initial_no_formats = stream_resolver.metrics.no_formats_count

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = DownloadError(err_msg)
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError):
                stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=Cp4RRAEgpeU", force_refresh=True)

        self.assertEqual(stream_resolver.metrics.http_429_count, initial_429)
        self.assertFalse(stream_resolver.is_in_cooldown())
        self.assertEqual(stream_resolver.get_cooldown_remaining(), 0.0)
        self.assertGreater(stream_resolver.metrics.no_formats_count, initial_no_formats)
        self.assertEqual(stream_resolver.last_resolver_error_type, ERROR_NO_FORMATS)

    # =========================================================================
    # 2. HTTP 429 Explicit Evidence
    # =========================================================================

    def test_2_http_429_too_many_requests(self) -> None:
        """2. 'HTTP Error 429: Too Many Requests' classified as HTTP_429; record_429 called; cooldown activates."""
        err_msg = "HTTP Error 429: Too Many Requests"
        cat = classify_youtube_error(err_msg)
        self.assertEqual(cat, ERROR_HTTP_429)

        initial_429 = stream_resolver.metrics.http_429_count

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = DownloadError(err_msg)
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError):
                stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=Cp4RRAEgpeU", force_refresh=True)

        self.assertEqual(stream_resolver.metrics.http_429_count, initial_429 + 1)
        self.assertTrue(stream_resolver.is_in_cooldown())
        self.assertGreater(stream_resolver.get_cooldown_remaining(), 0.0)
        self.assertEqual(stream_resolver.last_resolver_error_type, ERROR_HTTP_429)

    # =========================================================================
    # 3. HTTP 403 Forbidden
    # =========================================================================

    def test_3_http_403_forbidden(self) -> None:
        """3. 'HTTP Error 403: Forbidden' classified as HTTP_403; record_403 called; 429 count unchanged."""
        err_msg = "HTTP Error 403: Forbidden"
        cat = classify_youtube_error(err_msg)
        self.assertEqual(cat, ERROR_HTTP_403)

        initial_429 = stream_resolver.metrics.http_429_count
        initial_403 = stream_resolver.metrics.http_403_count

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = DownloadError(err_msg)
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError):
                stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=Cp4RRAEgpeU", force_refresh=True)

        self.assertEqual(stream_resolver.metrics.http_429_count, initial_429)
        self.assertGreater(stream_resolver.metrics.http_403_count, initial_403)
        self.assertFalse(stream_resolver.is_in_cooldown())
        self.assertEqual(stream_resolver.last_resolver_error_type, ERROR_HTTP_403)

    # =========================================================================
    # 4. BOT_CHALLENGE Classification
    # =========================================================================

    def test_4_bot_challenge_distinct_from_429(self) -> None:
        """4. 'Sign in to confirm you're not a bot' classified as BOT_CHALLENGE; not 429."""
        err_msg = "Sign in to confirm you're not a bot"
        cat = classify_youtube_error(err_msg)
        self.assertEqual(cat, ERROR_BOT_CHALLENGE)

        # If explicit 429 is also present, it classifies as 429
        both_msg = "Sign in to confirm you're not a bot (HTTP Error 429: Too Many Requests)"
        self.assertEqual(classify_youtube_error(both_msg), ERROR_HTTP_429)

        # Test resolver handling of bot challenge
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = DownloadError(err_msg)
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError):
                stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=bot_test", force_refresh=True)

        self.assertEqual(stream_resolver.metrics.http_429_count, 0)
        self.assertEqual(stream_resolver.metrics.bot_challenge_count, 1)
        self.assertFalse(stream_resolver.is_in_cooldown())
        self.assertEqual(stream_resolver.last_resolver_error_type, ERROR_BOT_CHALLENGE)

    # =========================================================================
    # 5. Generic DownloadError -> EXTRACTOR_ERROR
    # =========================================================================

    def test_5_generic_download_error(self) -> None:
        """5. Generic DownloadError classified as EXTRACTOR_ERROR; no 429 cooldown."""
        err_msg = "DownloadError: Unable to download webpage"
        cat = classify_youtube_error(err_msg)
        self.assertEqual(cat, ERROR_EXTRACTOR_ERROR)

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = DownloadError(err_msg)
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            with self.assertRaises(RuntimeError):
                stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=generic_fail", force_refresh=True)

        self.assertEqual(stream_resolver.metrics.http_429_count, 0)
        self.assertFalse(stream_resolver.is_in_cooldown())
        self.assertEqual(stream_resolver.last_resolver_error_type, ERROR_EXTRACTOR_ERROR)

    # =========================================================================
    # 6. FFmpeg Non-Zero Exit Without HTTP Status
    # =========================================================================

    def test_6_ffmpeg_nonzero_exit_without_http_status(self) -> None:
        """6. FFmpeg non-zero exit without HTTP status -> FFMPEG_ERROR; no 429 cooldown."""
        stderr_msg = "frame= 1429 fps=30.0 q=-1.0 size= 24000kB time=00:04:29.12 bitrate= 429.0kbits/s speed=1.00x\nConversion failed!"
        cat = classify_youtube_error(stderr_msg, default=ERROR_FFMPEG_ERROR)
        self.assertEqual(cat, ERROR_FFMPEG_ERROR)

        reader = CameraReader("https://www.youtube.com/watch?v=ffmpeg_err", width=640, height=480)
        reader.stderr_lines = [stderr_msg]

        # Trigger exit handling with code 8
        proc = MagicMock()
        proc.poll.return_value = 8
        proc.pid = 7712
        reader.process = proc

        # Simulating abnormal exit in _read_loop_impl
        reader._process_started_at = time.time() - 30.0
        reader._read_errors = 1

        # Error handling block
        stderr_tail = "\n".join(reader.stderr_lines)
        exit_code = 8
        cat = classify_youtube_error(stderr_tail, default=ERROR_FFMPEG_ERROR)
        self.assertEqual(cat, ERROR_FFMPEG_ERROR)
        self.assertEqual(stream_resolver.metrics.http_429_count, 0)
        self.assertFalse(stream_resolver.is_in_cooldown())

    # =========================================================================
    # 7. FFmpeg Stderr Explicitly Contains HTTP 429
    # =========================================================================

    def test_7_ffmpeg_stderr_explicit_429(self) -> None:
        """7. FFmpeg stderr explicitly contains 429 -> HTTP_429; shared cooldown activates."""
        stderr_msg = "Opening 'https://manifest.googlevideo.com/...' [https @ 0x123] HTTP error 429 Too Many Requests"
        cat = classify_youtube_error(stderr_msg, default=ERROR_FFMPEG_ERROR)
        self.assertEqual(cat, ERROR_HTTP_429)

        # Feed to CameraReader stderr
        reader = CameraReader("https://www.youtube.com/watch?v=ffmpeg_429", width=640, height=480)
        reader.stderr_lines = [stderr_msg]

        # In _read_loop_impl:
        stderr_tail = "\n".join(reader.stderr_lines)
        cat = classify_youtube_error(stderr_tail, default=ERROR_FFMPEG_ERROR)
        if cat == ERROR_HTTP_429:
            stream_resolver.record_429(source="ffmpeg_live")

        self.assertEqual(stream_resolver.metrics.http_429_count, 1)
        self.assertTrue(stream_resolver.is_in_cooldown())
        self.assertGreater(stream_resolver.get_cooldown_remaining(), 0.0)

    # =========================================================================
    # 8. NO_FORMATS During Camera Reconnect
    # =========================================================================

    def test_8_no_formats_during_camera_reconnect(self) -> None:
        """8. NO_FORMATS during camera reconnect uses bounded normal backoff; no shared 429 cooldown."""
        reader = CameraReader("https://www.youtube.com/watch?v=reconnect_no_formats", width=640, height=480)
        reader._stream_url = None
        reader._force_url_refresh = True

        # Mock resolver raising No video formats found
        ytdlp_mock = MagicMock(side_effect=RuntimeError("ERROR: [youtube] Cp4RRAEgpeU: No video formats found!"))
        reader._get_stream_url_with_diagnostics = ytdlp_mock

        with patch.object(reader.stop_event, "wait", return_value=True):
            result = reader._reconnect()

        self.assertFalse(result)
        self.assertEqual(reader.last_error_type, ERROR_NO_FORMATS)
        self.assertEqual(reader.last_resolver_error_type, ERROR_NO_FORMATS)
        self.assertEqual(stream_resolver.metrics.http_429_count, 0)
        self.assertFalse(stream_resolver.is_in_cooldown())
        self.assertEqual(stream_resolver.get_cooldown_remaining(), 0.0)

    # =========================================================================
    # 9. Recovery After Temporary NO_FORMATS Failure
    # =========================================================================

    def test_9_recovery_after_temporary_no_formats(self) -> None:
        """9. After one NO_FORMATS failure, a later successful resolver response is allowed and Live recovers."""
        reader = CameraReader("https://www.youtube.com/watch?v=recover_after_no_formats", width=640, height=480)
        reader._stream_url = None
        reader._force_url_refresh = True

        call_count = 0

        def mock_resolve(reason):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("ERROR: [youtube] Cp4RRAEgpeU: No video formats found!")
            return "https://manifest.googlevideo.com/recovered.m3u8"

        reader._get_stream_url_with_diagnostics = mock_resolve

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 8844
        mock_proc.stderr = None
        mock_proc.stdout = None

        with patch.object(reader, "_spawn_ffmpeg", return_value=None):
            reader.process = mock_proc
            # Reconnect will fail on attempt 1, sleep, and succeed on attempt 2
            with patch.object(reader.stop_event, "wait", return_value=False):
                with patch.object(reader.stop_event, "is_set", side_effect=[False, False, False, False, False, False]):
                    success = reader._reconnect()

        self.assertTrue(success)
        self.assertEqual(call_count, 2)
        self.assertEqual(reader._stream_url, "https://manifest.googlevideo.com/recovered.m3u8")
        self.assertEqual(stream_resolver.metrics.http_429_count, 0)
        self.assertFalse(stream_resolver.is_in_cooldown())

    # =========================================================================
    # 10. Stale / Dead FFmpeg PID Cleared from Diagnostics
    # =========================================================================

    def test_10_dead_ffmpeg_pid_cleared_from_diagnostics(self) -> None:
        """10. Stale/dead FFmpeg PID is cleared from diagnostics after cleanup (ffmpeg_pid is None, ffmpeg_alive is False)."""
        reader = CameraReader("https://www.youtube.com/watch?v=pid_cleanup_test", width=640, height=480)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 9182
        mock_proc.stdout = None
        mock_proc.stderr = None
        reader.process = mock_proc
        reader._last_ffmpeg_pid = 9182

        # 1. While running: diagnostics exposes PID and alive=True
        d_running = reader.diagnostics()
        self.assertTrue(d_running["ffmpeg_alive"])
        self.assertEqual(d_running["ffmpeg_pid"], 9182)

        # 2. Process exits and is cleaned up
        mock_proc.poll.return_value = 0
        reader._cleanup_process()

        # 3. After cleanup: ffmpeg_pid MUST be None and ffmpeg_alive MUST be False
        d_stopped = reader.diagnostics()
        self.assertFalse(d_stopped["ffmpeg_alive"])
        self.assertIsNone(d_stopped["ffmpeg_pid"])

        # Also verify for YouTubeVODReader
        vod_reader = YouTubeVODReader("https://www.youtube.com/watch?v=vod_pid_cleanup")
        vod_reader._process = mock_proc
        vod_reader._last_ffmpeg_pid = 9182

        d_vod_running = vod_reader.diagnostics()
        self.assertFalse(d_vod_running["ffmpeg_alive"])  # mock_proc.poll is 0
        self.assertIsNone(d_vod_running["ffmpeg_pid"])

        vod_reader._cleanup_process()
        d_vod_stopped = vod_reader.diagnostics()
        self.assertFalse(d_vod_stopped["ffmpeg_alive"])
        self.assertIsNone(d_vod_stopped["ffmpeg_pid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
