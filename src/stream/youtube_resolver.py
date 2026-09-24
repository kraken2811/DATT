"""Centralized YouTube Stream Resolver with Deduplication, Caching & Rate Limiting.

Provides:
1. Stream URL Cache with TTL & failure tracking to avoid repeated yt-dlp calls.
2. Single-flight deduplication: multiple threads requesting the same video share 1 resolve.
3. Global Rate Limiter & Request Spacing to avoid YouTube rate limits.
4. HTTP 429 exponential backoff with random jitter.
5. Standardized logging ([YT-RESOLVE], [YT-CACHE], [YT-429], [YT-DEDUP]) and metrics.
"""

from dataclasses import dataclass, field
import logging
from pathlib import Path
import random
import re
import sys
import threading
import time
from typing import Any
import urllib.parse

import yt_dlp
from yt_dlp.utils import DownloadError

# Ensure project root is accessible
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config

logger = logging.getLogger("datt.stream.resolver")


@dataclass
class StreamCacheEntry:
    """Cache entry representing a resolved direct stream URL with lifecycle metadata."""
    video_id: str
    stream_url: str
    created_at: float = field(default_factory=time.time)
    last_success: float = field(default_factory=time.time)
    last_failure: float = 0.0
    failure_count: int = 0
    is_live: bool = True
    ttl_seconds: float = 14400.0  # 4 hours default

    @property
    def is_expired(self) -> bool:
        """Check if cache entry has exceeded its TTL."""
        return (time.time() - self.created_at) >= self.ttl_seconds

    @property
    def is_valid(self) -> bool:
        """Valid if not expired and not marked dead by excessive failures."""
        if self.is_expired:
            return False
        max_failures = getattr(config, "STREAM_DIRECT_RECONNECT_RETRIES", 3)
        return self.failure_count < max_failures


@dataclass
class ResolverMetrics:
    """Metrics tracking YouTube extraction events and cache efficiency."""
    total_resolves: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    direct_url_reconnects: int = 0
    http_429_count: int = 0
    resolve_failures: int = 0
    stream_restarts: int = 0
    dedup_waits: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "total_resolves": self.total_resolves,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "direct_url_reconnects": self.direct_url_reconnects,
            "http_429_count": self.http_429_count,
            "resolve_failures": self.resolve_failures,
            "stream_restarts": self.stream_restarts,
            "dedup_waits": self.dedup_waits,
        }


def extract_video_id(url: str) -> str:
    """Extract canonical YouTube video ID or return raw string if not a YouTube URL."""
    if not url:
        return ""
    url_str = str(url).strip()

    # Match youtu.be/<id>
    match_short = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url_str)
    if match_short:
        return match_short.group(1).split("?")[0].split("&")[0]

    # Match youtube.com/watch?v=<id> or live/<id> or embed/<id>
    match_long = re.search(r"(?:[?&]v=|/live/|/embed/|/v/)([a-zA-Z0-9_-]+)", url_str)
    if match_long:
        return match_long.group(1).split("?")[0].split("&")[0]

    # Pure alphanumeric ID (e.g. Cp4RRAEgpeU or test_id)
    if re.match(r"^[a-zA-Z0-9_-]+$", url_str) and not url_str.startswith("http"):
        return url_str

    # Non-YouTube URL: return as-is
    return url_str


def is_youtube_url(url: str) -> bool:
    """Check if the given string is a YouTube URL or video ID."""
    if not url:
        return False
    u = url.lower()
    return "youtube.com" in u or "youtu.be" in u or (
        bool(re.match(r"^[a-zA-Z0-9_-]{11}$", url.strip()))
        and not url.startswith("http://")
        and not url.startswith("https://")
        and not url.startswith("rtsp://")
    )



def select_best_stream_format(formats: list[dict[str, Any]], is_vod: bool = False) -> str | None:
    """Select the best playable video stream format from yt-dlp format list.

    Preference ranking for Live:
    1. HLS / m3u8 stream
    2. H264 / AVC codec
    3. Target resolution: <= 720p

    Preference ranking for VOD:
    1. MP4 container with H264 video
    2. Target resolution: <= 720p
    """
    valid_video_formats = []
    for f in formats:
        url = f.get("url")
        if not url or not isinstance(url, str):
            continue
        vcodec = f.get("vcodec")
        if not vcodec or vcodec == "none":
            continue
        valid_video_formats.append(f)

    if not valid_video_formats:
        return None

    if is_vod:
        def vod_score(f: dict[str, Any]) -> tuple:
            ext = str(f.get("ext") or "").lower()
            is_mp4 = 1 if ext == "mp4" else 0
            height = f.get("height") or 0
            res_tier = 2 if 0 < height <= 720 else (1 if height > 720 else 0)
            tbr = f.get("tbr") or 0
            return (is_mp4, res_tier, height, tbr)

        best_format = max(valid_video_formats, key=vod_score)
        return best_format.get("url")

    def live_score(f: dict[str, Any]) -> tuple:
        protocol = str(f.get("protocol") or "").lower()
        url = str(f.get("url") or "").lower()
        is_hls = 1 if ("m3u8" in protocol or ".m3u8" in url) else 0

        vcodec = str(f.get("vcodec") or "").lower()
        is_h264 = 1 if ("avc" in vcodec or "h264" in vcodec) else 0

        height = f.get("height") or 0
        if 0 < height <= 720:
            res_tier = 2
            res_score = height
        elif height > 720:
            res_tier = 1
            res_score = -height
        else:
            res_tier = 0
            res_score = 0

        tbr = f.get("tbr") or f.get("vbr") or 0
        fps = f.get("fps") or 0

        return (is_hls, is_h264, res_tier, res_score, tbr, fps)

    best_format = max(valid_video_formats, key=live_score)
    return best_format.get("url")


class YouTubeStreamResolver:
    """Centralized, thread-safe resolver for YouTube live and VOD stream URLs.

    Guarantees:
    - yt-dlp is ONLY called to resolve URLs, NEVER per frame.
    - Caches direct URLs with configurable TTL and lifecycle tracking.
    - Single-flight deduplication: concurrent requests for the same video execute 1 extraction.
    - Global rate limiting (`MAX_CONCURRENT_YOUTUBE_RESOLVE = 1`) and request spacing.
    - Exponential backoff + random jitter for HTTP 429 / Too Many Requests.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, StreamCacheEntry] = {}
        self._metrics = ResolverMetrics()

        # Single Flight deduplication data
        self._in_flight: dict[str, threading.Event] = {}
        self._in_flight_results: dict[str, tuple[str | None, Exception | None]] = {}

        # Concurrency & Spacing controls
        concurrency = getattr(config, "YOUTUBE_MAX_CONCURRENT_RESOLVE", 1)
        self._resolve_semaphore = threading.Semaphore(max(1, concurrency))
        self._last_extraction_finished_at: float = 0.0
        self._global_429_cooldown_until: float = 0.0

    @property
    def metrics(self) -> ResolverMetrics:
        """Return snapshot of resolver metrics."""
        with self._lock:
            return self._metrics

    def get_metrics_dict(self) -> dict[str, int]:
        """Return metrics as a dictionary for telemetry APIs."""
        with self._lock:
            return self._metrics.to_dict()

    def get_cached_url(self, url_or_id: str) -> str | None:
        """Return active cached stream URL if valid, or None if expired/missing."""
        video_id = extract_video_id(url_or_id)
        with self._lock:
            entry = self._cache.get(video_id)
            if entry and entry.is_valid:
                return entry.stream_url
            return None

    def invalidate_cache(self, url_or_id: str, reason: str = "manual") -> None:
        """Explicitly invalidate cached URL for the given video."""
        video_id = extract_video_id(url_or_id)
        with self._lock:
            if video_id in self._cache:
                del self._cache[video_id]
                logger.info("[YT-CACHE] video_id=%s invalidated (reason=%s)", video_id, reason)

    def record_success(self, url_or_id: str) -> None:
        """Mark video stream working successfully, resetting failure counter."""
        video_id = extract_video_id(url_or_id)
        with self._lock:
            entry = self._cache.get(video_id)
            if entry:
                entry.last_success = time.time()
                entry.failure_count = 0

    def record_failure(self, url_or_id: str) -> int:
        """Record a stream failure for the given video; return updated failure count."""
        video_id = extract_video_id(url_or_id)
        with self._lock:
            entry = self._cache.get(video_id)
            if entry:
                entry.last_failure = time.time()
                entry.failure_count += 1
                return entry.failure_count
            return 1

    def resolve_stream_url(
        self,
        url_or_id: str,
        is_vod: bool = False,
        force_refresh: bool = False,
    ) -> str:
        """Resolve a playable direct stream URL for a YouTube video or stream.

        Args:
            url_or_id: YouTube URL or 11-char video ID (or non-YouTube direct URL).
            is_vod: True for VOD MP4 video, False for Live HLS stream.
            force_refresh: Force ignoring cache and extracting fresh URL.

        Returns:
            str: Direct playable video stream URL.

        Raises:
            RuntimeError: If URL extraction fails after all retries.
        """
        # If not a YouTube URL or ID, return directly (e.g. RTSP, HTTP MP4, local path)
        if not is_youtube_url(url_or_id):
            return url_or_id

        video_id = extract_video_id(url_or_id)

        # 1. Check Stream Cache (Fast path)
        if not force_refresh:
            with self._lock:
                entry = self._cache.get(video_id)
                if entry is not None and entry.is_valid:
                    self._metrics.cache_hits += 1
                    logger.info(
                        "[YT-CACHE] video_id=%s cache hit (age=%.1fs, ttl=%.1fs)",
                        video_id, time.time() - entry.created_at, entry.ttl_seconds,
                    )
                    return entry.stream_url

        # 2. Single-Flight Deduplication Check
        wait_event: threading.Event | None = None
        with self._lock:
            if video_id in self._in_flight:
                wait_event = self._in_flight[video_id]
                self._metrics.dedup_waits += 1
                logger.info("[YT-DEDUP] video_id=%s resolve already in-flight, waiting...", video_id)

        if wait_event is not None:
            # Wait for the first thread to complete the extraction
            wait_timeout = 60.0
            finished = wait_event.wait(timeout=wait_timeout)
            if not finished:
                logger.warning("[YT-DEDUP] Timeout waiting for in-flight resolve on %s", video_id)
            with self._lock:
                result, error = self._in_flight_results.get(video_id, (None, None))
                if result:
                    self._metrics.cache_hits += 1
                    return result
                if error:
                    raise error

        # 3. Register as the in-flight worker for this video_id
        current_event = threading.Event()
        with self._lock:
            self._in_flight[video_id] = current_event
            self._in_flight_results.pop(video_id, None)

        try:
            resolved_url = self._execute_yt_dlp_extraction(url_or_id, video_id, is_vod)
            with self._lock:
                # Cache the freshly resolved direct URL
                ttl = getattr(config, "YOUTUBE_URL_TTL_SECONDS", 14400.0)
                self._cache[video_id] = StreamCacheEntry(
                    video_id=video_id,
                    stream_url=resolved_url,
                    created_at=time.time(),
                    last_success=time.time(),
                    is_live=not is_vod,
                    ttl_seconds=ttl,
                )
                self._metrics.total_resolves += 1
                self._metrics.cache_misses += 1
                self._in_flight_results[video_id] = (resolved_url, None)
            return resolved_url

        except Exception as exc:
            with self._lock:
                self._metrics.resolve_failures += 1
                self._in_flight_results[video_id] = (None, exc)
            raise

        finally:
            with self._lock:
                # Notify any waiting threads and clean up in-flight registry
                current_event.set()
                self._in_flight.pop(video_id, None)

    def _execute_yt_dlp_extraction(
        self,
        original_url: str,
        video_id: str,
        is_vod: bool,
    ) -> str:
        """Execute yt-dlp under global rate limiter with request spacing and backoff."""
        max_retries = getattr(config, "YOUTUBE_MAX_RESOLVE_RETRIES", 3)
        min_interval = getattr(config, "YOUTUBE_RESOLVE_MIN_INTERVAL", 3.0)
        base_delay = getattr(config, "YOUTUBE_BACKOFF_BASE", 10.0)
        max_delay = getattr(config, "YOUTUBE_BACKOFF_MAX", 120.0)
        jitter = getattr(config, "YOUTUBE_BACKOFF_JITTER", 5.0)

        # Acquire global resolve slot (concurrency <= MAX_CONCURRENT_YOUTUBE_RESOLVE)
        acquired = self._resolve_semaphore.acquire(timeout=60.0)
        if not acquired:
            raise RuntimeError("Timeout acquiring global YouTube resolve lock")

        try:
            # 1. Enforce Global 429 Cooldown if active
            with self._lock:
                cooldown_remaining = self._global_429_cooldown_until - time.time()
            if cooldown_remaining > 0:
                logger.warning(
                    "[YT-429] Global cooldown active, sleeping %.1fs before resolve...",
                    cooldown_remaining,
                )
                time.sleep(cooldown_remaining)

            # 2. Enforce Minimum Request Spacing
            with self._lock:
                elapsed_since_last = time.time() - self._last_extraction_finished_at
                spacing_wait = max(0.0, min_interval - elapsed_since_last)
            if spacing_wait > 0:
                logger.debug("[YT-SPACING] Waiting %.2fs before calling yt-dlp...", spacing_wait)
                time.sleep(spacing_wait)

            # 3. Build canonical URL
            target_url = original_url
            if not target_url.startswith("http://") and not target_url.startswith("https://"):
                target_url = f"https://www.youtube.com/watch?v=video_id" if video_id == original_url else f"https://www.youtube.com/watch?v={video_id}"

            ydl_opts: dict[str, Any] = {
                "format": (
                    "best[ext=mp4]/bestvideo[height<=720][ext=mp4]+bestaudio/best"
                    if is_vod
                    else "bestvideo[height<=720]/best[height<=720]/bestvideo/best"
                ),
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "nocheckcertificate": True,
                "skip_download": True,
                "extractor_args": {
                    "youtube": {
                        "player_client": ["android", "web"]
                    }
                },
            }

            last_exception: Exception | None = None

            for attempt in range(1, max_retries + 1):
                t_start = time.perf_counter()
                logger.info(
                    "[YT-RESOLVE] video_id=%s resolving... (attempt %d/%d, is_vod=%s)",
                    video_id, attempt, max_retries, is_vod,
                )

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
                        info = ydl.extract_info(target_url, download=False)

                    duration = time.perf_counter() - t_start
                    if not info or not isinstance(info, dict):
                        raise RuntimeError(f"Failed to extract video info from YouTube for {video_id}")

                    # Prefer format selection
                    formats = info.get("formats", [])
                    selected_url = None
                    if isinstance(formats, list) and formats:
                        selected_url = select_best_stream_format(formats, is_vod=is_vod)

                    if not selected_url:
                        selected_url = info.get("url")

                    if not selected_url or not isinstance(selected_url, str):
                        err_label = "YouTube VOD extraction error: " if is_vod else ""
                        raise RuntimeError(f"{err_label}No valid video stream URL found from YouTube for {video_id}")

                    logger.info(
                        "[YT-RESOLVE] video_id=%s resolved in %.2fs (URL prefix=%s...)",
                        video_id, duration, selected_url[:60],
                    )
                    return selected_url

                except DownloadError as exc:
                    err_str = str(exc)
                    is_429 = "429" in err_str or "Too Many Requests" in err_str
                    if is_429:
                        self._metrics.http_429_count += 1
                        backoff = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, jitter), max_delay)
                        logger.error(
                            "[YT-429] HTTP 429 Too Many Requests detected for video_id=%s. Backing off for %.1fs (attempt %d/%d)",
                            video_id, backoff, attempt, max_retries,
                        )
                        with self._lock:
                            self._global_429_cooldown_until = time.time() + backoff
                        if attempt < max_retries:
                            time.sleep(backoff)
                            continue
                        raise RuntimeError(f"HTTP 429 Too Many Requests from YouTube: {exc}") from exc

                    err_prefix = "YouTube VOD extraction error: " if is_vod else "Failed extracting YouTube stream: "
                    raise RuntimeError(f"{err_prefix}{exc}") from exc

                except Exception as exc:
                    duration = time.perf_counter() - t_start
                    last_exception = exc
                    err_str = str(exc)
                    is_429 = "429" in err_str or "Too Many Requests" in err_str

                    if is_429:
                        self._metrics.http_429_count += 1
                        backoff = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, jitter), max_delay)
                        logger.error(
                            "[YT-429] HTTP 429 Too Many Requests detected for video_id=%s. Backing off for %.1fs (attempt %d/%d)",
                            video_id, backoff, attempt, max_retries,
                        )
                        with self._lock:
                            self._global_429_cooldown_until = time.time() + backoff
                        if attempt < max_retries:
                            time.sleep(backoff)
                            continue
                    else:
                        # Non-retryable validation errors re-raise directly
                        if "Failed to extract video info" in err_str or "No valid video stream URL" in err_str:
                            raise
                        logger.warning(
                            "[YT-RESOLVE] Attempt %d/%d failed in %.2fs: %s",
                            attempt, max_retries, duration, exc,
                        )
                        if attempt < max_retries:
                            time.sleep(min_interval)

            raise RuntimeError(
                f"Failed extracting YouTube stream for video_id={video_id} after {max_retries} attempts: {last_exception}"
            ) from last_exception

        finally:
            with self._lock:
                self._last_extraction_finished_at = time.time()
            self._resolve_semaphore.release()


# Global Singleton Instance for application-wide use
stream_resolver = YouTubeStreamResolver()
