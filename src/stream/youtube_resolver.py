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
import os
from pathlib import Path
import random
import re
import shutil
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



# =========================================================================
# YouTube Error Classification
# =========================================================================

ERROR_HTTP_429 = "HTTP_429"
ERROR_HTTP_403 = "HTTP_403"
ERROR_NO_FORMATS = "NO_FORMATS"
ERROR_BOT_CHALLENGE = "BOT_CHALLENGE"
ERROR_VIDEO_UNAVAILABLE = "VIDEO_UNAVAILABLE"
ERROR_EXTRACTOR_ERROR = "EXTRACTOR_ERROR"
ERROR_FFMPEG_ERROR = "FFMPEG_ERROR"
ERROR_NETWORK_ERROR = "NETWORK_ERROR"
ERROR_CLEAN_STOP = "CLEAN_STOP"

# Explicit 429 markers (never bare "429")
_RE_HTTP_429 = re.compile(
    r"(?:HTTP\s*(?:Error)?\s*429|429\s+Too\s+Many\s+Requests|Too\s+Many\s+Requests|"
    r"(?:status(?:\s*code)?|error(?:\s*code)?|response\s*code)[\s:=]+429\b|"
    r"\bstatus=429\b|\bcode=429\b|\bHTTP/1\.[01]\s+429\b|\bHTTP/2\s+429\b)",
    re.IGNORECASE,
)

# Explicit 403 markers
_RE_HTTP_403 = re.compile(
    r"(?:HTTP\s*(?:Error)?\s*403|403\s+Forbidden|\bForbidden\b|"
    r"(?:status(?:\s*code)?|error(?:\s*code)?|response\s*code)[\s:=]+403\b|"
    r"\bstatus=403\b|\bcode=403\b|\bHTTP/1\.[01]\s+403\b|\bHTTP/2\s+403\b)",
    re.IGNORECASE,
)

# Explicit bot challenge markers
_RE_BOT_CHALLENGE = re.compile(
    r"(?:Sign\s+in\s+to\s+confirm\s+you(?:'re|\s+are)\s+not\s+a\s+bot|confirm\s+you(?:'re|\s+are)\s+not\s+a\s+bot|bot\s+detection)",
    re.IGNORECASE,
)

# Explicit no formats markers
_RE_NO_FORMATS = re.compile(
    r"(?:No\s+video\s+formats?\s+found|Requested\s+format\s+is\s+not\s+available|no\s+suitable\s+format)",
    re.IGNORECASE,
)

# Video unavailable markers
_RE_VIDEO_UNAVAILABLE = re.compile(
    r"(?:Video\s+unavailable|This\s+video\s+is\s+unavailable|Private\s+video|This\s+video\s+is\s+private|"
    r"This\s+live\s+event\s+has\s+ended|Video\s+has\s+been\s+removed|This\s+video\s+has\s+been\s+removed|"
    r"Premieres\s+in\s+\d+)",
    re.IGNORECASE,
)

# Network / transport errors
_RE_NETWORK_ERROR = re.compile(
    r"(?:timed?\s*out|connection\s+reset|connection\s+refused|network\s+is\s+unreachable|"
    r"name\s+resolution|getaddrinfo\s+failed|remotedisconnected|broken\s+pipe|"
    r"connection\s+aborted|server\s+disconnected|tls\s+handshake\s+failed)",
    re.IGNORECASE,
)

# FFmpeg error markers
_RE_FFMPEG_ERROR = re.compile(
    r"(?:ffmpeg\s+(?:failed|crash|error|abnormal|exited)|exit\s*code\s*[1-9]\d*|return_code=[1-9]\d*)",
    re.IGNORECASE,
)

# Clean stop / cancellation
_RE_CLEAN_STOP = re.compile(
    r"(?:clean\s+stop|cancelled|stopped|stop_event\s+set)",
    re.IGNORECASE,
)


def classify_youtube_error(message: str | Exception | None, default: str = ERROR_EXTRACTOR_ERROR) -> str:
    """Classify YouTube/yt-dlp/FFmpeg failure based on explicit error evidence.

    Explicitly distinguishes:
    1. HTTP_429 (only on explicit 429 / Too Many Requests markers)
    2. HTTP_403 (only on explicit 403 / Forbidden markers)
    3. BOT_CHALLENGE (sign in / bot verification)
    4. NO_FORMATS (No video formats found)
    5. VIDEO_UNAVAILABLE (private/removed/ended)
    6. NETWORK_ERROR (connection timeout/reset/DNS)
    7. CLEAN_STOP (stopped cleanly)
    8. FFMPEG_ERROR (FFmpeg non-zero exit / failure)
    9. EXTRACTOR_ERROR (generic extraction failure)
    """
    if message is None:
        return default
    text = str(message).strip()
    if not text:
        return default

    # 1. Explicit 429 evidence (Rate limit)
    if _RE_HTTP_429.search(text):
        return ERROR_HTTP_429

    # 2. Explicit 403 evidence (Forbidden / token expired)
    if _RE_HTTP_403.search(text):
        return ERROR_HTTP_403

    # 3. Bot challenge / CAPTCHA (distinct from 429 unless 429 is also present)
    if _RE_BOT_CHALLENGE.search(text):
        return ERROR_BOT_CHALLENGE

    # 4. No formats available (NOT 429!)
    if _RE_NO_FORMATS.search(text):
        return ERROR_NO_FORMATS

    # 5. Video permanently or temporarily unavailable
    if _RE_VIDEO_UNAVAILABLE.search(text):
        return ERROR_VIDEO_UNAVAILABLE

    # 6. Network / transport errors
    if _RE_NETWORK_ERROR.search(text):
        return ERROR_NETWORK_ERROR

    # 7. Clean stop / cancellation
    if _RE_CLEAN_STOP.search(text):
        return ERROR_CLEAN_STOP

    # 8. FFmpeg error markers
    if _RE_FFMPEG_ERROR.search(text):
        return ERROR_FFMPEG_ERROR

    return default


@dataclass
class ResolverMetrics:
    """Metrics tracking YouTube extraction events and cache efficiency."""
    total_resolves: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    direct_url_reconnects: int = 0
    http_429_count: int = 0
    http_403_count: int = 0
    no_formats_count: int = 0
    bot_challenge_count: int = 0
    resolve_failures: int = 0
    stream_restarts: int = 0
    dedup_waits: int = 0
    resolver_attempt_count: int = 0
    resolver_success_count: int = 0
    last_resolver_error_type: str = ""
    last_resolver_error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_resolves": self.total_resolves,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "direct_url_reconnects": self.direct_url_reconnects,
            "http_429_count": self.http_429_count,
            "http_403_count": self.http_403_count,
            "no_formats_count": self.no_formats_count,
            "bot_challenge_count": self.bot_challenge_count,
            "resolve_failures": self.resolve_failures,
            "stream_restarts": self.stream_restarts,
            "dedup_waits": self.dedup_waits,
            "resolver_attempt_count": self.resolver_attempt_count,
            "resolver_success_count": self.resolver_success_count,
            "last_resolver_error_type": self.last_resolver_error_type,
            "last_resolver_error_message": self.last_resolver_error_message,
        }


@dataclass
class SharedRateLimitPolicy:
    """Unified rate limit and circuit breaker policy for YouTube access."""
    http_429_count: int = 0
    http_403_count: int = 0
    last_429_timestamp: float = 0.0
    cooldown_until: float = 0.0
    current_backoff_level: int = 0
    base_cooldown: float = 10.0
    max_cooldown: float = 120.0
    jitter: float = 5.0

    @property
    def is_in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self.cooldown_until - time.time())


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


def get_cookie_config() -> tuple[bool, str | None]:
    """Retrieve and validate yt-dlp cookie configuration from env or auto-discovery.

    Returns:
        tuple[bool, str | None]: (cookie_enabled, resolved_cookie_path)

    Raises:
        FileNotFoundError: If an explicit cookie path is configured but does not exist.
    """
    raw_path = os.getenv("YTDLP_COOKIE_FILE")
    if raw_path is None:
        raw_path = getattr(config, "YTDLP_COOKIE_FILE", None)

    if raw_path is not None:
        raw_path = str(raw_path).strip()

    if raw_path:
        p = Path(raw_path).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(
                f"[YT-CONFIG] YTDLP_COOKIE_FILE specified at '{raw_path}' does not exist or is not a file."
            )
        return True, str(p)

    # Auto-discovery fallback for standard locations (e.g. Colab / project root)
    auto_candidates = [
        Path("/content/DATT/www.youtube.com_cookies.txt"),
        PROJECT_ROOT / "www.youtube.com_cookies.txt",
        PROJECT_ROOT / "cookies.txt",
        Path("www.youtube.com_cookies.txt"),
        Path("cookies.txt"),
    ]
    for cand in auto_candidates:
        if cand.is_file():
            return True, str(cand.resolve())

    return False, None


def get_js_runtime_config() -> tuple[dict[str, Any], list[str], str]:
    """Discover available JavaScript runtime (Deno/Node) and remote components (EJS) for yt-dlp.

    Returns:
        tuple[dict[str, Any], list[str], str]: (js_runtimes_dict, remote_components_list, runtime_label)
    """
    deno_env = os.getenv("DENO_PATH")
    if deno_env and Path(deno_env).is_file():
        deno_bin = str(Path(deno_env).resolve())
    else:
        deno_bin = shutil.which("deno")
        if not deno_bin:
            for cand in [
                Path("/root/.deno/bin/deno"),
                Path.home() / ".deno" / "bin" / "deno",
                Path("/usr/local/bin/deno"),
                Path("/usr/bin/deno"),
            ]:
                if cand.is_file():
                    deno_bin = str(cand.resolve())
                    break

    remote_components = ["ejs:github", "ejs:npm"]

    if deno_bin:
        js_runtimes = {"deno": {"path": deno_bin}}
        js_runtime_label = f"deno ({deno_bin})"
        return js_runtimes, remote_components, js_runtime_label

    node_bin = shutil.which("node")
    if node_bin:
        js_runtimes = {"node": {"path": node_bin}}
        js_runtime_label = f"node ({node_bin})"
        return js_runtimes, remote_components, js_runtime_label

    return {"deno": {"path": None}}, remote_components, "deno (default)"


def build_ydl_opts(
    is_vod: bool = False,
    is_probe: bool = False,
    extra_opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build unified, standardized yt-dlp options for both probe and resolve operations.

    Ensures identical cookie, JS runtime (Deno/EJS), network, and extractor settings
    across is_live_stream() and resolve_stream_url().

    Logs:
        cookie_enabled=True/False, cookie_path=<path>, js_runtime=<label>
        (Never logs cookie contents).
    """
    cookie_enabled, cookie_path = get_cookie_config()
    js_runtimes, remote_components, js_runtime_label = get_js_runtime_config()

    logger.info(
        "[YT-CONFIG] cookie_enabled=%s cookie_path=%s js_runtime=%s",
        cookie_enabled,
        cookie_path,
        js_runtime_label,
    )

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
        "skip_download": True,
        "js_runtimes": js_runtimes,
        "remote_components": remote_components,
    }

    if cookie_enabled and cookie_path:
        opts["cookiefile"] = cookie_path

    if not is_probe:
        opts["format"] = (
            "best[ext=mp4]/bestvideo[height<=720][ext=mp4]+bestaudio/best"
            if is_vod
            else "bestvideo[height<=720]/best[height<=720]/bestvideo/best"
        )

    if extra_opts:
        opts.update(extra_opts)

    return opts


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
        self._policy = SharedRateLimitPolicy()
        self.last_resolver_error_type: str = ""
        self.last_resolver_error_message: str = ""

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

    @property
    def policy(self) -> SharedRateLimitPolicy:
        """Return shared 429 rate-limit policy."""
        with self._lock:
            return self._policy

    def record_429(self, source: str = "general", retry_after: float | None = None, count: bool = True) -> float:
        """Record an HTTP 429 event from yt-dlp or FFmpeg and calculate shared cooldown."""
        with self._lock:
            if count:
                self._metrics.http_429_count += 1
                self._policy.http_429_count += 1
            self._policy.last_429_timestamp = time.time()
            self._policy.current_backoff_level += 1
            level = self._policy.current_backoff_level

            base = getattr(config, "YOUTUBE_BACKOFF_BASE", 10.0)
            max_delay = getattr(config, "YOUTUBE_BACKOFF_MAX", 120.0)
            jitter = getattr(config, "YOUTUBE_BACKOFF_JITTER", 5.0)

            if retry_after is not None and retry_after > 0:
                cooldown = max(retry_after, base)
            else:
                backoff = min(base * (2 ** min(level - 1, 5)) + random.uniform(0, jitter), max_delay)
                cooldown = backoff

            self._policy.cooldown_until = time.time() + cooldown
            self._global_429_cooldown_until = self._policy.cooldown_until
            logger.error(
                "[YT-429] 429 recorded from source=%s. Entering global cooldown for %.1fs (level=%d, until=%.1f)",
                source, cooldown, level, self._policy.cooldown_until,
            )
            return cooldown

    def record_403(self, url_or_id: str = "", source: str = "general") -> None:
        """Record an HTTP 403 Forbidden event (e.g. expired googlevideo token) and invalidate cache."""
        with self._lock:
            self._metrics.http_403_count += 1
            self._policy.http_403_count += 1
            logger.warning("[YT-403] 403 Forbidden detected from source=%s for %s. Invalidating cache.", source, url_or_id)
            if url_or_id:
                self.invalidate_cache(url_or_id, reason="http_403_forbidden")

    def is_in_cooldown(self) -> bool:
        """Check if global 429 cooldown is currently active."""
        with self._lock:
            return time.time() < self._policy.cooldown_until

    def get_cooldown_remaining(self) -> float:
        """Return remaining seconds of 429 cooldown, or 0.0 if not in cooldown."""
        with self._lock:
            return max(0.0, self._policy.cooldown_until - time.time())

    def reset_backoff_level(self) -> None:
        """Reset or decay backoff level after stable operation."""
        with self._lock:
            self._policy.current_backoff_level = 0

    def reset_state(self) -> None:
        """Reset internal cache, metrics, in-flight state, and shared rate-limit policy."""
        with self._lock:
            self._cache.clear()
            self._in_flight.clear()
            self._in_flight_results.clear()
            self._metrics = ResolverMetrics()
            self._policy = SharedRateLimitPolicy()
            self._last_extraction_finished_at = 0.0
            self._global_429_cooldown_until = 0.0
            self.last_resolver_error_type = ""
            self.last_resolver_error_message = ""

    def reset_for_testing(self) -> None:
        """Alias for reset_state() in test environments."""
        self.reset_state()

    def get_metrics_dict(self) -> dict[str, Any]:
        """Return metrics as a dictionary for telemetry APIs."""
        with self._lock:
            m = self._metrics.to_dict()
            m["cooldown_remaining_seconds"] = round(self.get_cooldown_remaining(), 2)
            m["current_backoff_level"] = self._policy.current_backoff_level
            m["no_formats_count"] = self._metrics.no_formats_count
            m["bot_challenge_count"] = self._metrics.bot_challenge_count
            m["last_resolver_error_type"] = self.last_resolver_error_type
            return m

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

    def probe_stream_metadata(self, url_or_id: str) -> dict[str, Any]:
        """Probe YouTube video/stream metadata without downloading.

        Returns:
            dict[str, Any]: {
                "video_id": str,
                "is_live": bool,
                "status": str ("not_live", "is_live", "was_live"),
                "duration": int | float,
                "title": str,
            }
        """
        if not is_youtube_url(url_or_id):
            return {
                "video_id": url_or_id,
                "is_live": False,
                "status": "not_live",
                "duration": 0,
                "title": "",
            }

        video_id = extract_video_id(url_or_id)
        acquired = self._resolve_semaphore.acquire(timeout=60.0)
        if not acquired:
            raise RuntimeError("Timeout acquiring global YouTube resolve lock")

        try:
            # Enforce 429 cooldown & spacing
            cooldown_rem = self.get_cooldown_remaining()
            if cooldown_rem > 0:
                time.sleep(cooldown_rem)

            with self._lock:
                elapsed = time.time() - self._last_extraction_finished_at
                min_interval = getattr(config, "YOUTUBE_RESOLVE_MIN_INTERVAL", 3.0)
                wait_s = max(0.0, min_interval - elapsed)
            if wait_s > 0:
                time.sleep(wait_s)

            target_url = url_or_id
            if not target_url.startswith("http://") and not target_url.startswith("https://"):
                target_url = f"https://www.youtube.com/watch?v={video_id}"

            ydl_opts = build_ydl_opts(is_vod=False, is_probe=True)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(target_url, download=False)
            except Exception as exc:
                cat = classify_youtube_error(exc)
                if cat == ERROR_BOT_CHALLENGE:
                    with self._lock:
                        self._metrics.bot_challenge_count += 1
                        self.last_resolver_error_type = ERROR_BOT_CHALLENGE
                        self.last_resolver_error_message = str(exc)
                    raise RuntimeError(
                        f"AUTH/ANTI_BOT: YouTube bot challenge / sign-in required (Sign in to confirm you're not a bot): {exc}"
                    ) from exc
                elif cat == ERROR_HTTP_429:
                    self.record_429(source="is_live_probe")
                    raise RuntimeError(f"HTTP 429 Too Many Requests from YouTube: {exc}") from exc
                raise RuntimeError(f"Failed to probe YouTube stream type for {video_id}: {exc}") from exc

            if not info or not isinstance(info, dict):
                raise RuntimeError(f"Failed to extract video info from YouTube for {video_id}")

            is_live = bool(info.get("is_live") or info.get("live_status") == "is_live")
            duration = info.get("duration") or 0
            live_status = str(info.get("live_status") or "").lower()
            if duration > 0 or live_status in ("was_live", "not_live"):
                is_live = False

            logger.info(
                "[YT-PROBE] video_id=%s is_live=%s status=%s duration=%s",
                video_id,
                is_live,
                live_status,
                duration,
            )

            # Pre-cache direct URL with matching format to make subsequent resolve instant
            formats = info.get("formats", [])
            is_vod = not is_live
            selected_url = None
            if isinstance(formats, list) and formats:
                selected_url = select_best_stream_format(formats, is_vod=is_vod)
            if not selected_url:
                selected_url = info.get("url")

            if selected_url and isinstance(selected_url, str):
                with self._lock:
                    ttl = getattr(config, "YOUTUBE_URL_TTL_SECONDS", 14400.0)
                    self._cache[video_id] = StreamCacheEntry(
                        video_id=video_id,
                        stream_url=selected_url,
                        created_at=time.time(),
                        last_success=time.time(),
                        is_live=is_live,
                        ttl_seconds=ttl,
                    )

            return {
                "video_id": video_id,
                "is_live": is_live,
                "status": live_status or ("is_live" if is_live else "not_live"),
                "duration": duration,
                "title": str(info.get("title") or ""),
            }
        finally:
            with self._lock:
                self._last_extraction_finished_at = time.time()
            self._resolve_semaphore.release()

    def is_live_stream(self, url_or_id: str) -> bool:
        """Determine whether a YouTube URL is a Live stream (True) or VOD (False).

        Checks internal cache first. If not cached, executes yt-dlp metadata probe via probe_stream_metadata(),
        pre-caches the resolved direct URL to optimize subsequent resolve_stream_url calls,
        and accurately classifies live vs VOD based on yt-dlp extraction metadata.
        """
        if not is_youtube_url(url_or_id):
            return False

        video_id = extract_video_id(url_or_id)
        with self._lock:
            entry = self._cache.get(video_id)
            if entry is not None and entry.is_valid:
                return entry.is_live

        metadata = self.probe_stream_metadata(url_or_id)
        return metadata["is_live"]

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
                if entry is not None and entry.is_valid and (entry.is_live == (not is_vod)):
                    self._metrics.cache_hits += 1
                    logger.info(
                        "[YT-CACHE] video_id=%s cache hit (is_vod=%s, age=%.1fs, ttl=%.1fs)",
                        video_id, is_vod, time.time() - entry.created_at, entry.ttl_seconds,
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
            cooldown_remaining = self.get_cooldown_remaining()
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

            ydl_opts = build_ydl_opts(is_vod=is_vod, is_probe=False)

            last_exception: Exception | None = None

            for attempt in range(1, max_retries + 1):
                t_start = time.perf_counter()
                with self._lock:
                    self._metrics.resolver_attempt_count += 1
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

                    with self._lock:
                        self._metrics.resolver_success_count += 1
                        self.last_resolver_error_type = ""
                        self.last_resolver_error_message = ""
                        self._metrics.last_resolver_error_type = ""
                        self._metrics.last_resolver_error_message = ""

                    logger.info(
                        "[YT-RESOLVE] video_id=%s resolved in %.2fs (URL prefix=%s...)",
                        video_id, duration, selected_url[:60],
                    )
                    return selected_url

                except Exception as exc:
                    duration = time.perf_counter() - t_start
                    last_exception = exc
                    err_str = str(exc)
                    cat = classify_youtube_error(err_str, default=ERROR_EXTRACTOR_ERROR)
                    with self._lock:
                        self.last_resolver_error_type = cat
                        self.last_resolver_error_message = err_str
                        self._metrics.last_resolver_error_type = cat
                        self._metrics.last_resolver_error_message = err_str

                    err_prefix = "YouTube VOD extraction error: " if is_vod else "Failed extracting YouTube stream: "

                    if cat == ERROR_HTTP_429:
                        backoff = self.record_429(source="yt-dlp", count=(attempt == 1))
                        logger.error(
                            "[YT-429] HTTP 429 Too Many Requests detected for video_id=%s. Backing off for %.1fs (attempt %d/%d)",
                            video_id, backoff, attempt, max_retries,
                        )
                        if attempt < max_retries:
                            time.sleep(backoff)
                            continue
                        raise RuntimeError(f"{err_prefix}HTTP 429 Too Many Requests from YouTube: {exc}") from exc

                    elif cat == ERROR_HTTP_403:
                        self.record_403(url_or_id=video_id, source="yt-dlp")
                        logger.warning(
                            "[YT-403] HTTP 403 Forbidden detected for video_id=%s (attempt %d/%d)",
                            video_id, attempt, max_retries,
                        )
                        if attempt < max_retries:
                            time.sleep(min_interval)
                            continue
                        raise RuntimeError(f"{err_prefix}HTTP 403 Forbidden from YouTube: {exc}") from exc

                    elif cat == ERROR_NO_FORMATS:
                        with self._lock:
                            self._metrics.no_formats_count += 1
                        logger.warning(
                            "[YT-NO-FORMATS] No video formats found for video_id=%s (attempt %d/%d)",
                            video_id, attempt, max_retries,
                        )
                        if attempt < max_retries:
                            time.sleep(min_interval)
                            continue
                        raise RuntimeError(f"{err_prefix}{exc}") from exc

                    elif cat == ERROR_BOT_CHALLENGE:
                        with self._lock:
                            self._metrics.bot_challenge_count += 1
                        logger.error(
                            "[YT-BOT] YouTube bot challenge / sign-in required for video_id=%s: %s",
                            video_id, exc,
                        )
                        raise RuntimeError(
                            f"{err_prefix}AUTH/ANTI_BOT: YouTube bot challenge / sign-in required (Sign in to confirm you're not a bot): {exc}"
                        ) from exc

                    elif cat == ERROR_VIDEO_UNAVAILABLE:
                        logger.error("[YT-UNAVAILABLE] Video %s is unavailable: %s", video_id, exc)
                        raise RuntimeError(f"{err_prefix}YouTube video unavailable: {exc}") from exc

                    else:
                        # Non-retryable validation errors re-raise directly
                        if "Failed to extract video info" in err_str or "No valid video stream URL" in err_str:
                            raise
                        logger.warning(
                            "[YT-RESOLVE] Attempt %d/%d failed in %.2fs [%s]: %s",
                            attempt, max_retries, duration, cat, exc,
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
