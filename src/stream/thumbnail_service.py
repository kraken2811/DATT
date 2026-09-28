"""Camera Thumbnail Service for DATT.

Generates and caches representative camera thumbnails for Public CCTV camera cards.
Priority A: Verified working provider snapshot URL.
Priority B: 1-frame direct HLS capture via lightweight FFmpeg with concurrency limits.
Fallback: Clean SVG placeholder image.

Features:
- Thread-safe TTL in-memory caching (90-120 seconds).
- Strict concurrency limiting (max 3 simultaneous FFmpeg jobs).
- Broken snapshot URL blacklisting to prevent repeated 404/403 spam.
- Never runs YOLO or ByteTrack.
- Never holds persistent FFmpeg processes.
- Never blocks camera selection on thumbnail failure.
"""

from collections import OrderedDict
import logging
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any
import urllib.parse
import urllib.request

import imageio_ffmpeg

logger = logging.getLogger("datt.thumbnail")

# Default TTL in seconds
THUMBNAIL_CACHE_TTL = 90.0

# Max concurrent FFmpeg extraction processes
MAX_CONCURRENT_EXTRACTIONS = 3

CLEAN_PLACEHOLDER_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180" viewBox="0 0 320 180">
  <rect width="320" height="180" fill="#0f172a"/>
  <circle cx="160" cy="80" r="32" fill="#1e293b" stroke="#334155" stroke-width="2"/>
  <path d="M148 70 h24 a4 4 0 0 1 4 4 v16 a4 4 0 0 1 -4 4 h-24 a4 4 0 0 1 -4 -4 v-16 a4 4 0 0 1 4 -4 z" fill="#38bdf8"/>
  <polygon points="176,78 188,72 188,92 176,86" fill="#38bdf8"/>
  <circle cx="160" cy="82" r="5" fill="#0f172a"/>
  <text x="160" y="135" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="13" font-weight="600" fill="#94a3b8" text-anchor="middle">CCTV Live Stream</text>
  <text x="160" y="152" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="11" fill="#64748b" text-anchor="middle">Ready to connect</text>
</svg>"""


class ThumbnailService:
    """Thread-safe camera thumbnail generator and cache."""

    def __init__(
        self,
        cache_ttl: float = THUMBNAIL_CACHE_TTL,
        max_concurrency: int = MAX_CONCURRENT_EXTRACTIONS,
        cache_ttl_seconds: float | None = None,
    ) -> None:
        self.cache_ttl = cache_ttl_seconds if cache_ttl_seconds is not None else cache_ttl
        self._lock = threading.RLock()
        self._semaphore = threading.Semaphore(max_concurrency)

        # Cache: key -> (timestamp, data_bytes, content_type)
        self._cache: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()
        self._max_cache_size = 200

        # Blacklisted broken snapshot URLs (prevent 404/403 spam)
        self._broken_snapshots: set[str] = set()

    def get_thumbnail(
        self,
        camera_id: str,
        stream_url: str | None = None,
        snapshot_url: str | None = None,
        provider: str | None = None,
    ) -> tuple[bytes, str]:
        """Fetch or generate representative thumbnail image.

        Returns:
            tuple[bytes, str]: (image_bytes, content_type)
        """
        cache_key = camera_id or stream_url or snapshot_url or "default"

        # 1. Check in-memory cache
        now = time.time()
        with self._lock:
            if cache_key in self._cache:
                cached_time, cached_bytes, content_type = self._cache[cache_key]
                if (now - cached_time) < self.cache_ttl:
                    return cached_bytes, content_type

        # 2. Priority A: Attempt provider snapshot URL (if verified not broken)
        if snapshot_url and snapshot_url not in self._broken_snapshots:
            snap_bytes = self._fetch_remote_snapshot(snapshot_url)
            if snap_bytes is not None:
                self._store_cache(cache_key, snap_bytes, "image/jpeg")
                return snap_bytes, "image/jpeg"
            else:
                with self._lock:
                    self._broken_snapshots.add(snapshot_url)
                    logger.debug("ThumbnailService: Blacklisted broken snapshot: %s", snapshot_url)

        # 3. Priority B: Extract single frame from live HLS stream via lightweight FFmpeg
        if stream_url:
            frame_bytes = self._extract_hls_frame(stream_url, provider=provider)
            if frame_bytes is not None:
                self._store_cache(cache_key, frame_bytes, "image/jpeg")
                return frame_bytes, "image/jpeg"

        # 4. Fallback: Return clean SVG placeholder
        self._store_cache(cache_key, CLEAN_PLACEHOLDER_SVG, "image/svg+xml")
        return CLEAN_PLACEHOLDER_SVG, "image/svg+xml"

    def _fetch_remote_snapshot(self, url: str, timeout: float = 1.5) -> bytes | None:
        """Fetch remote snapshot with short timeout and validation."""
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DATT/4.5"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", getattr(resp, "code", 200))
                if status == 200 or str(status) == "200" or hasattr(resp, "read"):
                    data = resp.read()
                    # Validate image header (JPEG starts with \xff\xd8, PNG with \x89PNG)
                    if data and (data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")):
                        return data
        except Exception as exc:
            logger.debug("ThumbnailService: Snapshot fetch error on %s: %s", url, exc)
        return None

    def _extract_hls_frame(
        self,
        stream_url: str,
        provider: str | None = None,
        timeout: float = 5.0,
    ) -> bytes | None:
        """Extract a single frame from HLS stream using short-lived lightweight FFmpeg."""
        # Acquire concurrency slot (timeout 3.0s to avoid queue pileup)
        acquired = self._semaphore.acquire(timeout=3.0)
        if not acquired:
            logger.debug("ThumbnailService: Concurrency limit reached, skipping FFmpeg extraction for %s", stream_url)
            return None

        proc = None
        try:
            ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
            headers = "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) DATT/4.5\r\n"
            if provider in ("Seattle SDOT", "seattle", "seattle_sdot") or "seattle" in stream_url.lower():
                headers += "Referer: https://web.seattle.gov/Travelers/\r\n"

            cmd = [
                ffmpeg_path,
                "-nostdin",
                "-y",
                "-loglevel", "error",
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-probesize", "500000",
                "-analyzeduration", "500000",
                "-headers", headers,
                "-i", stream_url,
                "-frames:v", "1",
                "-vf", "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
                "-q:v", "5",
                "-f", "image2",
                "-",
            ]

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            stdout_bytes, _ = proc.communicate(timeout=timeout)
            if proc.returncode == 0 and len(stdout_bytes) > 50:
                return stdout_bytes
        except subprocess.TimeoutExpired:
            logger.debug("ThumbnailService: FFmpeg timed out for %s", stream_url)
            if proc is not None:
                try:
                    proc.kill()
                    proc.communicate(timeout=1.0)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("ThumbnailService: FFmpeg extraction failed for %s: %s", stream_url, exc)
        finally:
            self._semaphore.release()

        return None

    def _store_cache(self, key: str, data: bytes, content_type: str) -> None:
        """Store thumbnail in bounded LRU cache."""
        with self._lock:
            if len(self._cache) >= self._max_cache_size:
                self._cache.popitem(last=False)
            self._cache[key] = (time.time(), data, content_type)

    def clear_cache(self) -> None:
        """Clear all cached thumbnails."""
        with self._lock:
            self._cache.clear()
            self._broken_snapshots.clear()


# Global singleton instance
thumbnail_service = ThumbnailService()
