"""Video Source Readers for DATT - AI People Counter.

Provides unified readers for:
1. Local MP4 / Video files (with optional looping and EOF handling)
2. YouTube VOD (extracts direct MP4 / stream URL via yt-dlp with retries)

Both readers adhere to the CameraReader interface expected by CameraManager:
- start() / stop()
- read(timeout) -> np.ndarray | None
- status, stream_fps, stream_alive, finished, diagnostics
"""

from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path
import threading
import time
from typing import Any

import cv2
import numpy as np
import yt_dlp
from yt_dlp.utils import DownloadError

import config
from src.stream.youtube_resolver import stream_resolver

logger = logging.getLogger("datt.video_source")



@dataclass(frozen=True)
class VideoFrame:
    """Container for a single captured video frame."""
    sequence: int
    captured_at: float
    frame: np.ndarray


class BaseVideoReader:
    """Abstract base class for video readers used by CameraManager."""

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        raise NotImplementedError

    @property
    def status(self) -> str:
        return "STOPPED"

    @property
    def stream_fps(self) -> float:
        return 0.0

    @property
    def dropped_frames(self) -> int:
        return 0

    @property
    def buffer_age_ms(self) -> float:
        return 0.0

    @property
    def stream_alive(self) -> bool:
        return False

    @property
    def last_frame_time(self) -> float:
        return 0.0

    @property
    def frame_age_seconds(self) -> float:
        return 999.0

    @property
    def finished(self) -> bool:
        return True

    def diagnostics(self) -> dict[str, Any]:
        return {
            "reader_type": self.__class__.__name__,
            "status": self.status,
            "finished": self.finished,
        }


class LocalVideoReader(BaseVideoReader):
    """Reads local video files (MP4, MKV, AVI) using OpenCV VideoCapture.

    Features:
    - Validates file existence before opening
    - Configurable looping on EOF (loop=True) or clean termination (loop=False)
    - Paces frame capture according to native video FPS
    - Clean resource release on stop or source switch
    """

    def __init__(
        self,
        file_path: str | Path,
        loop: bool = True,
        target_fps: float | None = None,
    ) -> None:
        self.file_path = Path(file_path).resolve()
        self.loop = loop
        self.target_fps = target_fps

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._latest: VideoFrame | None = None
        self._last_read_sequence = -1
        self._frames_received = 0
        self._dropped_frames = 0
        self._last_frame_timestamp = 0.0
        self._stream_alive = False
        self._finished = False
        self._status = "STOPPED"
        self._error_reason = ""

        # FPS calculation window
        self._stream_fps = 0.0
        self._timestamps: deque[float] = deque(maxlen=30)

        # Video properties
        self.video_fps = 30.0
        self.total_frames = 0
        self.width = 0
        self.height = 0

    def start(self) -> None:
        """Start reading thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            if not self.file_path.is_file():
                self._status = "ERROR"
                self._error_reason = f"File not found: {self.file_path}"
                logger.error("[LOCAL-VIDEO] %s", self._error_reason)
                raise FileNotFoundError(self._error_reason)

            # Test opening VideoCapture
            cap = cv2.VideoCapture(str(self.file_path))
            if not cap.isOpened():
                self._status = "ERROR"
                self._error_reason = f"Failed opening video file with OpenCV: {self.file_path}"
                logger.error("[LOCAL-VIDEO] %s", self._error_reason)
                cap.release()
                raise RuntimeError(self._error_reason)

            fps = cap.get(cv2.CAP_PROP_FPS)
            self.video_fps = (self.target_fps or fps) if (fps and fps > 0 and not np.isnan(fps)) else 30.0
            self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            cap.release()

            self._stop_event.clear()
            self._finished = False
            self._status = "RUNNING"
            self._error_reason = ""
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="LocalVideoReaderThread",
                daemon=True,
            )
            self._thread.start()
            logger.info(
                "[LOCAL-VIDEO] Started reading '%s' (%dx%d @ %.1f FPS, loop=%s)",
                self.file_path.name, self.width, self.height, self.video_fps, self.loop,
            )

    def _capture_loop(self) -> None:
        """Background worker reading frames at target FPS pace."""
        cap = cv2.VideoCapture(str(self.file_path))
        if not cap.isOpened():
            with self._lock:
                self._status = "ERROR"
                self._error_reason = "VideoCapture failed to open in worker thread"
                self._finished = True
                self._stream_alive = False
            return

        frame_interval = 1.0 / max(self.video_fps, 1.0)
        sequence = 0

        try:
            while not self._stop_event.is_set():
                t_start = time.perf_counter()
                ret, frame = cap.read()

                if not ret or frame is None:
                    # EOF reached
                    if self.loop and not self._stop_event.is_set():
                        logger.debug("[LOCAL-VIDEO] EOF reached, looping to start")
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        logger.info("[LOCAL-VIDEO] EOF reached, finishing stream")
                        with self._lock:
                            self._finished = True
                            self._stream_alive = False
                            self._status = "STOPPED"
                        break

                sequence += 1
                now_perf = time.perf_counter()
                now_wall = time.time()

                with self._lock:
                    self._latest = VideoFrame(
                        sequence=sequence,
                        captured_at=now_perf,
                        frame=frame.copy(),
                    )
                    self._last_frame_timestamp = now_wall
                    self._stream_alive = True
                    self._frames_received = sequence

                # Calculate sliding window FPS
                self._timestamps.append(now_perf)
                if len(self._timestamps) >= 2:
                    dt = self._timestamps[-1] - self._timestamps[0]
                    if dt > 0:
                        with self._lock:
                            self._stream_fps = (len(self._timestamps) - 1) / dt

                # Pacing: maintain native FPS playback speed
                elapsed = time.perf_counter() - t_start
                sleep_time = max(0.0, frame_interval - elapsed)
                if sleep_time > 0 and self._stop_event.wait(sleep_time):
                    break

        except Exception as exc:
            logger.error("[LOCAL-VIDEO] Capture loop exception: %s", exc, exc_info=True)
            with self._lock:
                self._status = "ERROR"
                self._error_reason = str(exc)
                self._stream_alive = False
                self._finished = True
        finally:
            cap.release()
            logger.info("[LOCAL-VIDEO] Released VideoCapture for '%s'", self.file_path.name)

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        """Read newest available frame."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self._lock:
                if self._latest is not None and self._latest.sequence != self._last_read_sequence:
                    self._last_read_sequence = self._latest.sequence
                    return self._latest.frame.copy()

                if self._finished and not self._stream_alive:
                    return None

            time.sleep(0.002)
        return None

    def stop(self) -> None:
        """Stop reader cleanly and wait for worker thread."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        with self._lock:
            self._stream_alive = False
            self._status = "STOPPED"
            self._latest = None

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def stream_fps(self) -> float:
        with self._lock:
            return self._stream_fps

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    @property
    def buffer_age_ms(self) -> float:
        return self.frame_age_seconds * 1000.0

    @property
    def stream_alive(self) -> bool:
        with self._lock:
            return self._stream_alive and not self._finished

    @property
    def last_frame_time(self) -> float:
        with self._lock:
            return self._last_frame_timestamp

    @property
    def frame_age_seconds(self) -> float:
        with self._lock:
            if self._last_frame_timestamp <= 0:
                return 999.0
            return max(0.0, time.time() - self._last_frame_timestamp)

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "reader_type": "LocalVideoReader",
                "file_path": str(self.file_path),
                "fps": self.video_fps,
                "stream_fps": self._stream_fps,
                "frames_received": self._frames_received,
                "finished": self._finished,
                "status": self._status,
                "error_reason": self._error_reason,
            }


class YouTubeVODReader(BaseVideoReader):
    """Reads YouTube VOD streams by resolving direct video URLs with yt-dlp.

    Features:
    - Resolves playable direct MP4/stream URL (format 'best[ext=mp4]/best')
    - Handles invalid, unavailable, or private YouTube URLs
    - Reconnects with bounded retries if URL expires or connection drops
    - Clean VideoCapture release on stop or source change
    """

    def __init__(
        self,
        youtube_url: str,
        target_fps: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.youtube_url = youtube_url.strip()
        self.target_fps = target_fps
        self.max_retries = max_retries

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._latest: VideoFrame | None = None
        self._last_read_sequence = -1
        self._frames_received = 0
        self._dropped_frames = 0
        self._last_frame_timestamp = 0.0
        self._stream_alive = False
        self._finished = False
        self._status = "STOPPED"
        self._error_reason = ""

        self._stream_fps = 0.0
        self._timestamps: deque[float] = deque(maxlen=30)
        self._direct_url: str | None = None
        self._retries_used = 0

    @staticmethod
    def resolve_vod_url(url: str) -> str:
        """Extract direct video stream URL using stream_resolver for YouTube VOD."""
        return stream_resolver.resolve_stream_url(url, is_vod=True)

    def start(self) -> None:
        """Resolve URL and start reader thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._status = "SWITCHING"
            self._error_reason = ""
            logger.info("[YOUTUBE-VOD] Resolving URL: %s", self.youtube_url)

            try:
                self._direct_url = self.resolve_vod_url(self.youtube_url)
                logger.info("[YOUTUBE-VOD] URL resolved successfully")
            except Exception as exc:
                self._status = "ERROR"
                self._error_reason = f"Failed to resolve YouTube VOD: {exc}"
                logger.error("[YOUTUBE-VOD] %s", self._error_reason)
                raise RuntimeError(self._error_reason) from exc

            self._stop_event.clear()
            self._finished = False
            self._status = "RUNNING"
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="YouTubeVODReaderThread",
                daemon=True,
            )
            self._thread.start()

    def _capture_loop(self) -> None:
        """Capture loop with auto-recovery for expired URLs or dropped connections."""
        sequence = 0
        frame_interval = 1.0 / max(self.target_fps, 1.0)
        direct_reconnect_attempts = 0
        direct_limit = getattr(config, "STREAM_DIRECT_RECONNECT_RETRIES", 3)
        max_frame_failures = getattr(config, "STREAM_READ_FAILURE_THRESHOLD", 10)

        while not self._stop_event.is_set():
            if not self._direct_url:
                try:
                    self._direct_url = self.resolve_vod_url(self.youtube_url)
                    direct_reconnect_attempts = 0
                except Exception as exc:
                    self._retries_used += 1
                    logger.warning("[YOUTUBE-VOD] Retry %d/%d failed: %s", self._retries_used, self.max_retries, exc)
                    if self._retries_used >= self.max_retries:
                        with self._lock:
                            self._status = "ERROR"
                            self._error_reason = f"Exceeded max retries: {exc}"
                            self._finished = True
                            self._stream_alive = False
                        break
                    if self._stop_event.wait(3.0):
                        break
                    continue

            cap = cv2.VideoCapture(self._direct_url)
            if not cap.isOpened():
                cap.release()
                direct_reconnect_attempts += 1
                logger.warning(
                    "[YOUTUBE-VOD] VideoCapture open failed (direct attempt %d/%d)",
                    direct_reconnect_attempts, direct_limit,
                )
                if direct_reconnect_attempts >= direct_limit:
                    logger.info("[YOUTUBE-VOD] Direct URL reconnect exhausted, invalidating cache...")
                    stream_resolver.invalidate_cache(self.youtube_url, reason="vod_open_failed")
                    self._direct_url = None
                    direct_reconnect_attempts = 0

                self._retries_used += 1
                if self._retries_used >= self.max_retries:
                    with self._lock:
                        self._status = "ERROR"
                        self._error_reason = "Failed opening YouTube VOD stream with OpenCV"
                        self._finished = True
                        self._stream_alive = False
                    break
                if self._stop_event.wait(2.0):
                    break
                continue

            # Stream opened successfully
            self._retries_used = 0
            direct_reconnect_attempts = 0
            stream_resolver.record_success(self.youtube_url)
            with self._lock:
                self._status = "RUNNING"
                self._stream_alive = True

            consecutive_failures = 0
            try:
                while not self._stop_event.is_set():
                    t_start = time.perf_counter()
                    ret, frame = cap.read()

                    if not ret or frame is None:
                        consecutive_failures += 1
                        if consecutive_failures < max_frame_failures:
                            time.sleep(0.05)
                            continue
                        logger.info("[YOUTUBE-VOD] Stream reached end or dropped (%d consecutive failures)", consecutive_failures)
                        break

                    consecutive_failures = 0
                    sequence += 1
                    now_perf = time.perf_counter()
                    now_wall = time.time()

                    with self._lock:
                        self._latest = VideoFrame(
                            sequence=sequence,
                            captured_at=now_perf,
                            frame=frame.copy(),
                        )
                        self._last_frame_timestamp = now_wall
                        self._stream_alive = True
                        self._frames_received = sequence

                    # Calculate sliding window FPS
                    self._timestamps.append(now_perf)
                    if len(self._timestamps) >= 2:
                        dt = self._timestamps[-1] - self._timestamps[0]
                        if dt > 0:
                            with self._lock:
                                self._stream_fps = (len(self._timestamps) - 1) / dt

                    elapsed = time.perf_counter() - t_start
                    sleep_time = max(0.0, frame_interval - elapsed)
                    if sleep_time > 0 and self._stop_event.wait(sleep_time):
                        break

            finally:
                cap.release()

            if self._stop_event.is_set():
                break

            # Disconnect or EOF: try reopening existing direct URL first before re-resolving
            direct_reconnect_attempts += 1
            if direct_reconnect_attempts >= direct_limit:
                logger.info("[YOUTUBE-VOD] Invalidating cache and re-resolving direct URL...")
                stream_resolver.invalidate_cache(self.youtube_url, reason="vod_dropped")
                self._direct_url = None
                direct_reconnect_attempts = 0

            self._retries_used += 1
            if self._retries_used >= self.max_retries:
                with self._lock:
                    self._finished = True
                    self._stream_alive = False
                    self._status = "STOPPED"
                break
            self._stop_event.wait(1.5)

        with self._lock:
            self._stream_alive = False
            self._finished = True


    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        """Read newest available frame."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self._lock:
                if self._latest is not None and self._latest.sequence != self._last_read_sequence:
                    self._last_read_sequence = self._latest.sequence
                    return self._latest.frame.copy()

                if self._finished and not self._stream_alive:
                    return None

            time.sleep(0.002)
        return None

    def stop(self) -> None:
        """Stop reader cleanly."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        with self._lock:
            self._stream_alive = False
            self._status = "STOPPED"
            self._latest = None

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def stream_fps(self) -> float:
        with self._lock:
            return self._stream_fps

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    @property
    def buffer_age_ms(self) -> float:
        return self.frame_age_seconds * 1000.0

    @property
    def stream_alive(self) -> bool:
        with self._lock:
            return self._stream_alive and not self._finished

    @property
    def last_frame_time(self) -> float:
        with self._lock:
            return self._last_frame_timestamp

    @property
    def frame_age_seconds(self) -> float:
        with self._lock:
            if self._last_frame_timestamp <= 0:
                return 999.0
            return max(0.0, time.time() - self._last_frame_timestamp)

    @property
    def finished(self) -> bool:
        with self._lock:
            return self._finished

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "reader_type": "YouTubeVODReader",
                "youtube_url": self.youtube_url,
                "stream_fps": self._stream_fps,
                "frames_received": self._frames_received,
                "finished": self._finished,
                "status": self._status,
                "error_reason": self._error_reason,
                "resolver_metrics": stream_resolver.get_metrics_dict(),
            }

