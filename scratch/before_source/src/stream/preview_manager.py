"""Preview Manager for DATT - AI People Counter.

Provides lightweight, isolated camera previews without running YOLO, ByteTrack,
or any AI detection models.

Guarantees:
- At most ONE preview FFmpeg process runs at any given time.
- Zero preview FFmpeg running concurrently with AI when a camera is confirmed.
- Clean process termination when preview closes or user switches cameras.
- Provides snapshot retrieval and optional lightweight live MJPEG stream.
"""

import logging
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any
import urllib.error
import urllib.request

import cv2
import imageio_ffmpeg
import numpy as np

logger = logging.getLogger("datt.preview")


class PreviewManager:
    """Manages the single preview stream and snapshot caching."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._active_url: str | None = None
        self._latest_jpeg: bytes | None = None
        self._last_frame_time: float = 0.0
        self._frame_count: int = 0

        # Snapshot cache (url -> (timestamp, jpeg_bytes))
        self._snapshot_cache: dict[str, tuple[float, bytes]] = {}

    def is_active(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def get_active_url(self) -> str | None:
        with self._lock:
            return self._active_url

    def fetch_snapshot_image(self, snapshot_url: str, timeout: float = 4.0) -> bytes | None:
        """Fetch remote snapshot JPEG with in-memory caching."""
        if not snapshot_url:
            return None

        now = time.time()
        with self._lock:
            cached = self._snapshot_cache.get(snapshot_url)
            if cached and (now - cached[0]) < 25.0:  # 25s cache for 30s updates
                return cached[1]

        try:
            req = urllib.request.Request(
                snapshot_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DATT/4.5"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = resp.read()
                    with self._lock:
                        self._snapshot_cache[snapshot_url] = (time.time(), data)
                    return data
        except Exception as exc:
            logger.debug("PreviewManager: Snapshot fetch failed for %s: %s", snapshot_url, exc)

        with self._lock:
            cached = self._snapshot_cache.get(snapshot_url)
            if cached:
                return cached[1]
        return None

    def start_preview(
        self,
        stream_url: str,
        width: int = 640,
        height: int = 360,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Start lightweight preview FFmpeg process (scaled down, zero AI)."""
        with self._lock:
            self._stop_preview_internal()

            self._active_url = stream_url
            self._stop_event.clear()
            self._latest_jpeg = None
            self._last_frame_time = 0.0
            self._frame_count = 0

            ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
            cmd = [
                ffmpeg_path,
                "-nostdin",
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-probesize", "3000000",
                "-analyzeduration", "2000000",
                "-rw_timeout", "10000000",
            ]

            if headers:
                header_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
                cmd.extend(["-headers", header_str])
            else:
                cmd.extend(["-user_agent", "Mozilla/5.0 DATT/4.5"])

            cmd.extend([
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "3",
                "-i", stream_url,
                "-an",
                "-f", "rawvideo",
                "-pix_fmt", "bgr24",
                "-vf", f"scale={width}:{height}",
                "-r", "15",  # Throttle preview to 15 FPS to conserve CPU
                "-",
            ])

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                self._process = proc
                logger.info("PreviewManager: Spawned preview FFmpeg pid=%s for %s", proc.pid, stream_url)

                self._thread = threading.Thread(
                    target=self._preview_worker,
                    args=(proc, width, height),
                    name="PreviewWorkerThread",
                    daemon=True,
                )
                self._thread.start()
            except Exception as exc:
                logger.error("PreviewManager: Failed to start preview: %s", exc)
                self._stop_preview_internal()

    def stop_preview(self) -> None:
        """Safely terminate preview FFmpeg and release all resources."""
        with self._lock:
            self._stop_preview_internal()

    def _stop_preview_internal(self) -> None:
        """Internal worker to kill preview subprocess and drain pipes."""
        self._stop_event.set()
        proc = self._process
        self._process = None
        self._active_url = None

        if proc is not None:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=0.5)
                except Exception:
                    pass

            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
            logger.info("PreviewManager: Cleaned up preview FFmpeg process")

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

    def get_latest_frame_jpeg(self) -> bytes | None:
        """Return the newest preview JPEG frame."""
        with self._lock:
            return self._latest_jpeg

    def _preview_worker(self, proc: subprocess.Popen, width: int, height: int) -> None:
        """Background worker reading raw preview frames and encoding to JPEG."""
        frame_bytes_len = width * height * 3
        while not self._stop_event.is_set():
            if proc.stdout is None:
                break
            try:
                chunk = bytearray()
                while len(chunk) < frame_bytes_len:
                    read_part = proc.stdout.read(frame_bytes_len - len(chunk))
                    if not read_part:
                        break
                    chunk.extend(read_part)

                if len(chunk) != frame_bytes_len:
                    break

                frame_arr = np.frombuffer(chunk, dtype=np.uint8).reshape((height, width, 3))
                success, encoded = cv2.imencode(".jpg", frame_arr, [cv2.IMWRITE_JPEG_QUALITY, 65])
                if success:
                    with self._lock:
                        self._latest_jpeg = encoded.tobytes()
                        self._last_frame_time = time.time()
                        self._frame_count += 1
            except Exception:
                break

        with self._lock:
            if self._process == proc:
                self._stop_preview_internal()


# Global singleton instance
preview_manager = PreviewManager()
