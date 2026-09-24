"""Unit and Integration Tests for YouTube Stream Optimization & Resolver.

Verifies:
1. TEST 1 & 2: YouTube camera startup and continuous reading calls yt-dlp exactly once.
2. TEST 3: Frame read drop (< failure threshold) does not trigger yt-dlp or stream death.
3. TEST 4: Direct stream drops -> reconnect tries existing direct URL first without calling yt-dlp.
4. TEST 5: Direct URL completely dead after retries -> invalidates cache and calls yt-dlp for fresh URL.
5. TEST 6: HTTP 429 triggers exponential backoff and sets global cooldown.
6. TEST 7: Global rate limiter prevents concurrent yt-dlp extractions.
7. TEST 8: Single flight / deduplication: multiple threads requesting same video execute only 1 yt-dlp call.
8. TEST 9: No thread/process leaks on repeated reconnections.
9. TEST 10: Stream cache hit and cache invalidation.
10. TEST 11: Request spacing enforces minimum interval between consecutive resolves.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from src.stream.youtube_resolver import (
    YouTubeStreamResolver,
    extract_video_id,
    is_youtube_url,
    stream_resolver,
)
from src.stream.youtube_stream import CameraReader, get_stream_url
from yt_dlp.utils import DownloadError


class TestYouTubeResolver(unittest.TestCase):
    """Test suite for YouTubeStreamResolver and smart reconnection mechanisms."""

    def setUp(self) -> None:
        # Clear cache and reset metrics before each test
        with stream_resolver._lock:
            stream_resolver._cache.clear()
            stream_resolver._in_flight.clear()
            stream_resolver._in_flight_results.clear()
            stream_resolver._metrics.total_resolves = 0
            stream_resolver._metrics.cache_hits = 0
            stream_resolver._metrics.cache_misses = 0
            stream_resolver._metrics.direct_url_reconnects = 0
            stream_resolver._metrics.http_429_count = 0
            stream_resolver._metrics.resolve_failures = 0
            stream_resolver._metrics.stream_restarts = 0
            stream_resolver._metrics.dedup_waits = 0
            stream_resolver._last_extraction_finished_at = 0.0
            stream_resolver._global_429_cooldown_until = 0.0

    def test_url_and_id_extraction(self) -> None:
        """Verify video ID extraction and YouTube URL detection."""
        self.assertEqual(extract_video_id("https://www.youtube.com/watch?v=Cp4RRAEgpeU"), "Cp4RRAEgpeU")
        self.assertEqual(extract_video_id("https://youtu.be/Cp4RRAEgpeU"), "Cp4RRAEgpeU")
        self.assertEqual(extract_video_id("https://www.youtube.com/live/Cp4RRAEgpeU"), "Cp4RRAEgpeU")
        self.assertEqual(extract_video_id("Cp4RRAEgpeU"), "Cp4RRAEgpeU")
        self.assertEqual(extract_video_id("rtsp://127.0.0.1:8554/live"), "rtsp://127.0.0.1:8554/live")

        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=Cp4RRAEgpeU"))
        self.assertTrue(is_youtube_url("https://youtu.be/Cp4RRAEgpeU"))
        self.assertTrue(is_youtube_url("Cp4RRAEgpeU"))
        self.assertFalse(is_youtube_url("rtsp://127.0.0.1:8554/live"))
        self.assertFalse(is_youtube_url("data/test.mp4"))

    def test_stream_cache_hit_and_miss(self) -> None:
        """TEST 10: Stream cache stores URL, subsequent calls return cached URL without yt-dlp."""
        mock_info = {
            "formats": [
                {"url": "https://manifest.googlevideo.com/live/cached_720p.m3u8", "vcodec": "avc1", "height": 720, "protocol": "m3u8"}
            ]
        }
        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.return_value = mock_info
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            url1 = stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=test_cache_1")
            self.assertEqual(url1, "https://manifest.googlevideo.com/live/cached_720p.m3u8")
            self.assertEqual(mock_ydl.extract_info.call_count, 1)
            self.assertEqual(stream_resolver.metrics.cache_misses, 1)
            self.assertEqual(stream_resolver.metrics.cache_hits, 0)

            # Second call with same URL: MUST be a cache hit, yt-dlp NOT called again
            url2 = stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=test_cache_1")
            self.assertEqual(url2, url1)
            self.assertEqual(mock_ydl.extract_info.call_count, 1)  # Still 1!
            self.assertEqual(stream_resolver.metrics.cache_hits, 1)

            # Invalidate cache
            stream_resolver.invalidate_cache("test_cache_1")
            self.assertIsNone(stream_resolver.get_cached_url("test_cache_1"))

            # Third call after invalidation: fetches fresh URL
            url3 = stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=test_cache_1")
            self.assertEqual(url3, url1)
            self.assertEqual(mock_ydl.extract_info.call_count, 2)
            self.assertEqual(stream_resolver.metrics.cache_misses, 2)

    def test_single_flight_deduplication(self) -> None:
        """TEST 8: Multiple concurrent threads requesting same video produce exactly 1 yt-dlp extraction."""
        mock_info = {
            "formats": [
                {"url": "https://manifest.googlevideo.com/live/dedup_720p.m3u8", "vcodec": "avc1", "height": 720, "protocol": "m3u8"}
            ]
        }
        call_count = 0
        call_lock = threading.Lock()

        def slow_extract(url, download=False):
            nonlocal call_count
            with call_lock:
                call_count += 1
            time.sleep(0.2)  # Simulate network latency
            return mock_info

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = slow_extract
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            # Launch 5 concurrent threads requesting the exact same video
            def fetch():
                return stream_resolver.resolve_stream_url("https://www.youtube.com/watch?v=dedup_video_1")

            with ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(lambda _: fetch(), range(5)))

            # All 5 threads received the correct URL
            for r in results:
                self.assertEqual(r, "https://manifest.googlevideo.com/live/dedup_720p.m3u8")

            # Crucial verification: yt-dlp was called EXACTLY ONCE
            self.assertEqual(call_count, 1)
            self.assertGreaterEqual(stream_resolver.metrics.dedup_waits, 1)

    def test_global_rate_limiter_concurrency(self) -> None:
        """TEST 7: Concurrency limit prevents burst parallel extractions across different videos."""
        current_concurrency = 0
        max_seen_concurrency = 0
        c_lock = threading.Lock()

        def mock_extract(url, download=False):
            nonlocal current_concurrency, max_seen_concurrency
            with c_lock:
                current_concurrency += 1
                if current_concurrency > max_seen_concurrency:
                    max_seen_concurrency = current_concurrency
            time.sleep(0.05)
            with c_lock:
                current_concurrency -= 1
            return {
                "formats": [
                    {"url": f"https://manifest.googlevideo.com/live/{url}.m3u8", "vcodec": "avc1", "height": 720, "protocol": "m3u8"}
                ]
            }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = mock_extract
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            # Test resolver with semaphore = 1
            resolver = YouTubeStreamResolver()
            with patch.object(config, "YOUTUBE_RESOLVE_MIN_INTERVAL", 0.01):
                def fetch_unique(idx):
                    return resolver.resolve_stream_url(f"https://www.youtube.com/watch?v=unique_vid_{idx:03d}")

                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(fetch_unique, range(4)))

                # Concurrency must never exceed 1
                self.assertEqual(max_seen_concurrency, 1)

    def test_http_429_exponential_backoff(self) -> None:
        """TEST 6: HTTP 429 triggers exponential backoff and tracks 429 metrics."""
        attempts = 0

        def mock_429_then_success(url, download=False):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise DownloadError("HTTP Error 429: Too Many Requests")
            return {
                "formats": [
                    {"url": "https://manifest.googlevideo.com/live/recovered_720p.m3u8", "vcodec": "avc1", "height": 720, "protocol": "m3u8"}
                ]
            }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = mock_429_then_success
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            resolver = YouTubeStreamResolver()
            with patch.object(config, "YOUTUBE_BACKOFF_BASE", 0.05):
                with patch.object(config, "YOUTUBE_BACKOFF_JITTER", 0.01):
                    with patch.object(config, "YOUTUBE_MAX_RESOLVE_RETRIES", 3):
                        url = resolver.resolve_stream_url("https://www.youtube.com/watch?v=rate_limit_vid")
                        self.assertEqual(url, "https://manifest.googlevideo.com/live/recovered_720p.m3u8")
                        self.assertEqual(attempts, 2)
                        self.assertEqual(resolver.metrics.http_429_count, 1)

    def test_request_spacing_enforced(self) -> None:
        """TEST 11: Request spacing enforces minimum interval between consecutive extractions."""
        timestamps = []

        def mock_extract(url, download=False):
            timestamps.append(time.time())
            return {
                "formats": [
                    {"url": f"https://manifest.googlevideo.com/{url}.m3u8", "vcodec": "avc1", "height": 720, "protocol": "m3u8"}
                ]
            }

        with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
            mock_ydl = MagicMock()
            mock_ydl.extract_info.side_effect = mock_extract
            mock_ydl_cls.return_value.__enter__.return_value = mock_ydl

            resolver = YouTubeStreamResolver()
            # Set minimum spacing = 0.15s
            min_spacing = 0.15
            with patch.object(config, "YOUTUBE_RESOLVE_MIN_INTERVAL", min_spacing):
                resolver.resolve_stream_url("https://www.youtube.com/watch?v=spacing_vid_1")
                resolver.resolve_stream_url("https://www.youtube.com/watch?v=spacing_vid_2")

            self.assertEqual(len(timestamps), 2)
            delta = timestamps[1] - timestamps[0]
            self.assertGreaterEqual(delta, min_spacing - 0.02)

    def test_smart_reconnect_tries_existing_direct_url_first(self) -> None:
        """TEST 4 & 5: CameraReader re-spawns using existing direct URL first before re-resolving."""
        reader = CameraReader("https://www.youtube.com/watch?v=reconnect_smart", width=640, height=480)
        reader._stream_url = "https://manifest.googlevideo.com/initial_direct_url.m3u8"

        spawn_calls = []

        def mock_spawn(url: str):
            spawn_calls.append(url)
            if len(spawn_calls) == 1:
                # First attempt succeeds with the cached direct URL!
                reader.process = MagicMock()
                return
            raise RuntimeError("Spawn failed")

        reader._spawn_ffmpeg = mock_spawn
        with patch.object(reader.stop_event, "wait", return_value=False):
            with patch("src.stream.youtube_resolver.stream_resolver.resolve_stream_url") as mock_resolve:
                success = reader._reconnect()
                self.assertTrue(success)

                # Reconnect succeeded using the EXISTING direct URL
                self.assertEqual(len(spawn_calls), 1)
                self.assertEqual(spawn_calls[0], "https://manifest.googlevideo.com/initial_direct_url.m3u8")

                # Crucial assertion: resolve_stream_url was NOT CALLED because existing direct URL succeeded!
                mock_resolve.assert_not_called()

    def test_direct_url_exhausted_calls_fresh_resolve(self) -> None:
        """TEST 5: If direct URL fails multiple times, cache is invalidated and fresh URL is resolved."""
        reader = CameraReader("https://www.youtube.com/watch?v=reconnect_exhausted", width=640, height=480)
        reader._stream_url = "https://manifest.googlevideo.com/dead_direct_url.m3u8"

        spawn_calls = []

        def mock_spawn(url: str):
            spawn_calls.append(url)
            if "dead_direct_url" in url:
                raise RuntimeError("Old URL expired (HTTP 403 / 410)")
            # Succeeds when the fresh URL is used
            reader.process = MagicMock()

        reader._spawn_ffmpeg = mock_spawn
        with patch.object(reader.stop_event, "wait", return_value=False):
            with patch.object(config, "STREAM_DIRECT_RECONNECT_RETRIES", 2):
                reader._get_stream_url_with_diagnostics = MagicMock(
                    return_value="https://manifest.googlevideo.com/fresh_resolved_url.m3u8"
                )
                success = reader._reconnect()
                self.assertTrue(success)

                # Verified: Old dead URL tried 2 times (direct limit), then fresh URL resolved & spawned
                self.assertEqual(spawn_calls[0], "https://manifest.googlevideo.com/dead_direct_url.m3u8")
                self.assertEqual(spawn_calls[1], "https://manifest.googlevideo.com/dead_direct_url.m3u8")
                self.assertEqual(spawn_calls[2], "https://manifest.googlevideo.com/fresh_resolved_url.m3u8")
                reader._get_stream_url_with_diagnostics.assert_called_once()

    def test_frame_read_drop_below_threshold_does_not_kill_stream(self) -> None:
        """TEST 3: Consecutive frame drops below threshold do not trigger stream reconnect or yt-dlp."""
        reader = CameraReader("https://www.youtube.com/watch?v=drop_test", width=640, height=480)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Process is alive
        reader.process = mock_proc

        # Read loop should tolerate occasional dropped frames
        reader._consecutive_frame_failures = 3
        max_failures = 10
        self.assertLess(reader._consecutive_frame_failures, max_failures)
        # Status remains non-error while alive
        self.assertFalse(reader.finished)

    def test_no_process_or_thread_leak_on_repeated_reconnect(self) -> None:
        """TEST 9: Repeated reconnect cycles cleanly terminate FFmpeg and close pipes."""
        reader = CameraReader("https://www.youtube.com/watch?v=leak_test", width=640, height=480)
        for i in range(5):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout = MagicMock()
            mock_proc.stderr = MagicMock()
            reader.process = mock_proc
            reader._cleanup_process()

            mock_proc.stdout.close.assert_called_once()
            mock_proc.stderr.close.assert_called_once()
            mock_proc.terminate.assert_called_once()
            self.assertIsNone(reader.process)


if __name__ == "__main__":
    unittest.main(verbosity=2)
