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
import shutil
import subprocess
import threading
import time
from typing import Any
import urllib.parse

import cv2
import imageio_ffmpeg
import numpy as np
import yt_dlp
from yt_dlp.utils import DownloadError

from src.stream.youtube_resolver import (
    ERROR_BOT_CHALLENGE,
    ERROR_CLEAN_STOP,
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
from src.stream.youtube_stream import read_frame_bytes

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
    def error_reason(self) -> str:
        return getattr(self, "_error_reason", "")

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
            "source_type": getattr(self, "source_type", "unknown"),
            "reader_alive": self.stream_alive,
            "ffmpeg_alive": None,
            "ffmpeg_pid": None,
            "ffmpeg_exit_code": None,
            "process_generation": getattr(self, "process_generation", 0),
            "frames_received": getattr(self, "_frames_received", 0),
            "frame_age_seconds": self.frame_age_seconds,
            "first_frame_received": getattr(self, "_first_frame_received", False),
            "first_frame_timeout_count": getattr(self, "first_frame_timeout_count", 0),
            "stale_frame_timeout_count": getattr(self, "stale_frame_timeout_count", 0),
            "reconnect_count": getattr(self, "reconnect_count", 0),
            "ffmpeg_start_count": getattr(self, "ffmpeg_start_count", 0),
            "resolver_attempt_count": stream_resolver.metrics.resolver_attempt_count,
            "resolver_success_count": stream_resolver.metrics.resolver_success_count,
            "http_429_count": stream_resolver.metrics.http_429_count,
            "http_403_count": stream_resolver.metrics.http_403_count,
            "cooldown_remaining_seconds": round(stream_resolver.get_cooldown_remaining(), 2),
            "abnormal_exit_count": getattr(self, "abnormal_exit_count", 0),
            "clean_eof_count": getattr(self, "clean_eof_count", 0),
            "last_error_type": getattr(self, "last_error_type", ""),
            "last_error_message": getattr(self, "last_error_message", ""),
            "stream_fps": self.stream_fps,
            "finished": self.finished,
            "status": self.status,
            "error_reason": getattr(self, "_error_reason", ""),
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

        self.source_type = "local"
        self.process_generation = 0
        self._first_frame_received = False
        self.first_frame_timeout_count = 0
        self.stale_frame_timeout_count = 0
        self.reconnect_count = 0
        self.ffmpeg_start_count = 0
        self.abnormal_exit_count = 0
        self.clean_eof_count = 0
        self.last_error_type = ""
        self.last_error_message = ""

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._latest: VideoFrame | None = None
        self._last_read_sequence = -1
        self._frames_received = 0
        self._dropped_frames = 0
        self._read_errors = 0
        self._last_frame_timestamp = 0.0
        self._stream_alive = False
        self._finished = False
        self._status = "STOPPED"
        self._error_reason = ""

        # FPS calculation window
        self._stream_fps = 0.0
        self._timestamps: deque[float] = deque(maxlen=150)

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
                self.last_error_type = "FILE_NOT_FOUND"
                self.last_error_message = self._error_reason
                self.abnormal_exit_count += 1
                logger.error("[LOCAL-VIDEO] %s", self._error_reason)
                raise FileNotFoundError(self._error_reason)

            # Test opening VideoCapture
            cap = cv2.VideoCapture(str(self.file_path))
            if not cap.isOpened():
                self._status = "ERROR"
                self._error_reason = f"Failed opening video file with OpenCV: {self.file_path}"
                self.last_error_type = "OPENCV_OPEN_FAILED"
                self.last_error_message = self._error_reason
                self.abnormal_exit_count += 1
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
            self._first_frame_received = False
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
                self.last_error_type = "WORKER_OPEN_FAILED"
                self.last_error_message = self._error_reason
                self.abnormal_exit_count += 1
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
                        self.clean_eof_count += 1
                        logger.debug("[LOCAL-VIDEO] EOF reached, looping to start")
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        continue
                    else:
                        self.clean_eof_count += 1
                        logger.info("[LOCAL-VIDEO] EOF reached, finishing stream")
                        with self._lock:
                            self._finished = True
                            self._stream_alive = False
                            self._status = "STOPPED"
                        break

                sequence += 1
                now_perf = time.perf_counter()
                now_wall = time.time()
                self._first_frame_received = True

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
                cutoff = now_perf - 3.0
                while len(self._timestamps) > 2 and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) >= 2:
                    dt = self._timestamps[-1] - self._timestamps[0]
                    if dt >= 1.0:
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
                self.last_error_type = "CAPTURE_EXCEPTION"
                self.last_error_message = str(exc)
                self.abnormal_exit_count += 1
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
    def error_reason(self) -> str:
        with self._lock:
            return self._error_reason

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
                "source_type": "local",
                "reader_alive": self._thread.is_alive() if self._thread else False,
                "ffmpeg_alive": None,
                "ffmpeg_pid": None,
                "ffmpeg_exit_code": None,
                "process_generation": self.process_generation,
                "frames_received": self._frames_received,
                "frame_age_seconds": self.frame_age_seconds,
                "first_frame_received": self._first_frame_received,
                "first_frame_timeout_count": self.first_frame_timeout_count,
                "stale_frame_timeout_count": self.stale_frame_timeout_count,
                "reconnect_count": self.reconnect_count,
                "ffmpeg_start_count": self.ffmpeg_start_count,
                "resolver_attempt_count": stream_resolver.metrics.resolver_attempt_count,
                "resolver_success_count": stream_resolver.metrics.resolver_success_count,
                "http_429_count": stream_resolver.metrics.http_429_count,
                "http_403_count": stream_resolver.metrics.http_403_count,
                "cooldown_remaining_seconds": round(stream_resolver.get_cooldown_remaining(), 2),
                "abnormal_exit_count": self.abnormal_exit_count,
                "clean_eof_count": self.clean_eof_count,
                "last_error_type": self.last_error_type,
                "last_error_message": self.last_error_message,
                "last_resolver_error_type": "",
                "last_ffmpeg_error_type": "",
                "no_formats_count": 0,
                "bot_challenge_count": 0,
                "file_path": str(self.file_path),
                "fps": self.video_fps,
                "stream_fps": self._stream_fps,
                "read_errors": getattr(self, "_read_errors", 0),
                "last_frame_time": self._last_frame_timestamp,
                "finished": self._finished,
                "status": self._status,
                "error_reason": self._error_reason,
            }


class YouTubeVODReader(BaseVideoReader):
    """Reads YouTube VOD streams using FFmpeg subprocess piping rawvideo BGR24 to stdout.

    Features:
    - Resolves playable direct video URL via stream_resolver (yt-dlp).
    - Uses FFmpeg subprocess with rawvideo BGR24 stdout pipe (never cv2.VideoCapture on HTTPS).
    - Preserves zero-queue latest-frame semantics.
    - Handles EOF cleanly: stops on EOF if loop=False; restarts FFmpeg using cached direct URL if loop=True.
    - Safe subprocess lifecycle management without zombie processes.
    """

    def __init__(
        self,
        youtube_url: str,
        loop: bool = False,
        width: int = 1280,
        height: int = 720,
        target_fps: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.youtube_url = youtube_url.strip()
        self.loop = loop
        self.width = width
        self.height = height
        self.frame_size = width * height * 3
        self.target_fps = target_fps
        self.max_retries = max_retries

        self.source_type = "youtube_vod"
        self.process_generation: int = 0
        self.clean_eof_count: int = 0
        self.abnormal_exit_count: int = 0
        self.reconnect_count: int = 0
        self.ffmpeg_start_count: int = 0
        self.first_frame_timeout_count: int = 0
        self.stale_frame_timeout_count: int = 0
        self._first_frame_received: bool = False
        self.last_error_type: str = ""
        self.last_error_message: str = ""
        self.last_resolver_error_type: str = ""
        self.last_ffmpeg_error_type: str = ""

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None

        self._latest: VideoFrame | None = None
        self._last_read_sequence = -1
        self._frames_received = 0
        self._dropped_frames = 0
        self._read_errors = 0
        self._last_frame_timestamp = 0.0
        self._stream_alive = False
        self._finished = False
        self._status = "STOPPED"
        self._error_reason = ""

        self._stream_fps = 0.0
        self._timestamps: deque[float] = deque(maxlen=150)
        self._stderr_lines: list[str] = []
        self._direct_url: str | None = None
        self._last_ffmpeg_pid: int | None = None
        self._last_ffmpeg_exit_code: int | None = None
        self._last_ffmpeg_stderr: str = ""
        self._process_started_at: float = 0.0
        self._retries_used = 0

    @staticmethod
    def resolve_vod_url(url: str) -> str:
        """Extract direct video stream URL using stream_resolver for YouTube VOD."""
        return stream_resolver.resolve_stream_url(url, is_vod=True)

    @staticmethod
    def _build_ffmpeg_cmd(
        ffmpeg_path: str,
        stream_url: str,
        width: int,
        height: int,
    ) -> list[str]:
        """Build FFmpeg command for raw BGR24 decoding to stdout."""
        cmd = [
            ffmpeg_path,
            "-nostdin",
            "-loglevel", "error",
        ]
        if stream_url.startswith("http://") or stream_url.startswith("https://"):
            cmd.extend([
                "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "5",
            ])
        cmd.extend([
            "-i", stream_url,
            "-an",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-vf", f"scale={width}:{height}",
            "-",
        ])
        return cmd

    def _drain_stderr(self, pipe) -> None:
        """Continuously drain FFmpeg stderr to prevent pipe buffer deadlocks."""
        try:
            for line in iter(pipe.readline, b""):
                decoded = line.decode(errors="replace").strip()
                if decoded:
                    self._stderr_lines.append(decoded)
                    if len(self._stderr_lines) > 50:
                        self._stderr_lines.pop(0)
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _cleanup_process(self) -> None:
        """Safely terminate FFmpeg process according to cancel-safe cleanup order:
        1. mark stopping / prevent race
        2. terminate FFmpeg first
        3. allow blocked pipe reads to unblock
        4. wait with deadline
        5. kill if still alive
        6. close stdout / stderr
        7. verify process is gone
        """
        with self._lock:
            proc = self._process
            self._process = None

        if proc is not None:
            self._last_ffmpeg_exit_code = proc.poll()
            self._last_ffmpeg_stderr = "\n".join(self._stderr_lines)[-2000:]
            self._stderr_lines.clear()

            # 1. Terminate FFmpeg first
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

            # 2. Wait with deadline, kill fallback
            try:
                proc.wait(timeout=2.0)
            except (subprocess.TimeoutExpired, Exception):
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except Exception:
                    pass

            self._last_ffmpeg_exit_code = proc.poll()

            # 3. Close stdout and stderr pipes
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
            if proc.stderr is not None:
                try:
                    proc.stderr.close()
                except Exception:
                    pass

    def _spawn_ffmpeg(self, stream_url: str) -> None:
        """Construct FFmpeg command, spawn subprocess, and start stderr drain thread."""
        if self._stop_event.is_set():
            raise RuntimeError("Cannot spawn FFmpeg: reader is stopped")

        self.process_generation += 1
        self.ffmpeg_start_count += 1
        self._first_frame_received = False
        self._stderr_lines = []

        ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        cmd = self._build_ffmpeg_cmd(ffmpeg_path, stream_url, self.width, self.height)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=self.frame_size * 2,
        )

        if self._stop_event.is_set():
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            raise RuntimeError("Stopped immediately after spawn")

        with self._lock:
            self._process = proc
            self._last_ffmpeg_pid = proc.pid
            self._last_ffmpeg_exit_code = None
            self._last_ffmpeg_stderr = ""
            self._process_started_at = time.time()
        logger.info("[YOUTUBE-VOD] FFmpeg started pid=%s gen=%s", self._last_ffmpeg_pid, self.process_generation)

        if proc.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(proc.stderr,),
                name="YouTubeVODStderrThread",
                daemon=True,
            )
            self._stderr_thread.start()

        if self._stop_event.wait(0.2):
            return

        if proc.poll() is not None:
            err_msg = " ".join(self._stderr_lines[-5:]) if self._stderr_lines else "Process exited early"
            raise RuntimeError(f"FFmpeg failed to open video stream: {err_msg}")

    def start(self) -> None:
        """Resolve URL and start reader thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            if self._stop_event.is_set():
                return

            self._status = "SWITCHING"
            self._error_reason = ""
            logger.info("[YOUTUBE-VOD] Resolving URL...")

            # Check shared rate-limit cooldown
            if stream_resolver.is_in_cooldown():
                cooldown_rem = stream_resolver.get_cooldown_remaining()
                logger.warning("[YOUTUBE-VOD] YouTube resolver in 429 cooldown (%.1fs remaining)", cooldown_rem)

            try:
                self._direct_url = self.resolve_vod_url(self.youtube_url)
                logger.info("[YOUTUBE-VOD] URL resolved successfully")
            except Exception as exc:
                self._status = "ERROR"
                err_str = str(exc)
                cat = classify_youtube_error(err_str, default=ERROR_EXTRACTOR_ERROR)
                self.last_resolver_error_type = cat
                self.last_error_type = cat
                self.last_error_message = err_str
                if cat == ERROR_BOT_CHALLENGE or "AUTH/ANTI_BOT" in err_str:
                    self._error_reason = f"AUTH/ANTI_BOT: YouTube bot challenge / sign-in required: {exc}"
                elif cat == ERROR_HTTP_429:
                    self._error_reason = f"Failed to resolve YouTube VOD: {exc}"
                    stream_resolver.record_429(source="vod_resolve_start")
                elif cat == ERROR_HTTP_403:
                    self._error_reason = f"Failed to resolve YouTube VOD: {exc}"
                    stream_resolver.record_403(self.youtube_url, source="vod_resolve_start")
                else:
                    self._error_reason = f"Failed to resolve YouTube VOD: {exc}"
                self._finished = True
                self._stream_alive = False
                self.abnormal_exit_count += 1
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
        """Capture frames from FFmpeg stdout pipe with pacing, clean EOF and abnormal exit handling."""
        sequence = 0
        frame_interval = 1.0 / max(self.target_fps, 1.0)

        while not self._stop_event.is_set():
            # Check 429 cooldown before resolving URL
            cooldown_rem = stream_resolver.get_cooldown_remaining()
            if cooldown_rem > 0:
                logger.warning("[YOUTUBE-VOD] In 429 cooldown. Waiting %.1fs...", cooldown_rem)
                if self._stop_event.wait(cooldown_rem):
                    break

            if not self._direct_url:
                if self._stop_event.is_set():
                    break
                logger.info("[YOUTUBE-VOD] Resolving URL...")
                try:
                    self._direct_url = self.resolve_vod_url(self.youtube_url)
                    logger.info("[YOUTUBE-VOD] URL resolved successfully")
                except Exception as exc:
                    self._read_errors += 1
                    self.abnormal_exit_count += 1
                    err_str = str(exc)
                    cat = classify_youtube_error(err_str, default=ERROR_EXTRACTOR_ERROR)
                    self.last_resolver_error_type = cat
                    self.last_error_type = cat
                    self.last_error_message = err_str
                    if cat == ERROR_BOT_CHALLENGE or "AUTH/ANTI_BOT" in err_str:
                        self._error_reason = f"AUTH/ANTI_BOT: YouTube bot challenge / sign-in required: {exc}"
                    elif cat == ERROR_HTTP_429:
                        self._error_reason = f"Failed to resolve YouTube VOD: {exc}"
                        stream_resolver.record_429(source="vod_resolver")
                    elif cat == ERROR_HTTP_403:
                        self._error_reason = f"Failed to resolve YouTube VOD: {exc}"
                        stream_resolver.record_403(self.youtube_url, source="vod_resolver")
                    else:
                        self._error_reason = f"Failed to resolve YouTube VOD: {exc}"

                    with self._lock:
                        self._status = "ERROR"
                        self._finished = True
                        self._stream_alive = False
                    logger.error("[YOUTUBE-VOD] %s", self._error_reason)
                    break

            if self._stop_event.is_set():
                break

            # Start FFmpeg subprocess
            logger.info("[YOUTUBE-VOD] Starting FFmpeg reader")
            try:
                self._spawn_ffmpeg(self._direct_url)
                with self._lock:
                    self._status = "RUNNING"
                    self._stream_alive = True
            except Exception as exc:
                self._read_errors += 1
                self.abnormal_exit_count += 1
                self._retries_used += 1
                err_str = str(exc)
                stderr_tail = "\n".join(self._stderr_lines)
                cat = classify_youtube_error(stderr_tail or err_str, default=ERROR_FFMPEG_ERROR)
                self.last_ffmpeg_error_type = cat
                self.last_error_type = cat
                if cat == ERROR_HTTP_429:
                    self.last_error_message = f"FFmpeg 429 on spawn: {stderr_tail[-200:] or err_str}"
                    stream_resolver.record_429(source="ffmpeg_vod_spawn")
                elif cat == ERROR_HTTP_403:
                    self.last_error_message = f"FFmpeg 403 on spawn: {stderr_tail[-200:] or err_str}"
                    stream_resolver.record_403(self.youtube_url, source="ffmpeg_vod_spawn")
                else:
                    self.last_error_type = "SPAWN_FAILURE"
                    self.last_error_message = err_str
                    stream_resolver.invalidate_cache(self.youtube_url, reason="ffmpeg_spawn_failed")

                self._direct_url = None
                self._cleanup_process()

                if self._retries_used >= self.max_retries:
                    with self._lock:
                        self._status = "ERROR"
                        self._error_reason = f"Exceeded max retries spawning FFmpeg: {exc}"
                        self._finished = True
                        self._stream_alive = False
                    break
                backoff_delay = stream_resolver.get_cooldown_remaining() if self.last_error_type == "HTTP_429" else min(30.0, 1.0 * (2 ** (self._retries_used - 1)))
                if self._stop_event.wait(backoff_delay):
                    break
                continue

            proc = self._process
            stdout = proc.stdout if proc is not None else None
            if stdout is None:
                self._cleanup_process()
                continue

            consecutive_read_failures = 0
            is_clean_eof = False
            read_exception = False

            while not self._stop_event.is_set():
                t_start = time.perf_counter()
                try:
                    raw = read_frame_bytes(stdout, self.frame_size)
                except Exception as exc:
                    raw = b""
                    self._read_errors += 1
                    read_exception = True
                    self.last_error_type = "READ_EXCEPTION"
                    self.last_error_message = str(exc)

                if len(raw) == self.frame_size:
                    consecutive_read_failures = 0
                    now_wall = time.time()
                    now_perf = time.perf_counter()

                    frame = np.frombuffer(raw, np.uint8).reshape(
                        self.height, self.width, 3
                    ).copy()
                    sequence += 1

                    if not self._first_frame_received:
                        self._first_frame_received = True
                        logger.info("[YOUTUBE-VOD] First frame received (gen=%d)", self.process_generation)

                    with self._lock:
                        self._latest = VideoFrame(
                            sequence=sequence,
                            captured_at=now_perf,
                            frame=frame,
                        )
                        self._last_frame_timestamp = now_wall
                        self._stream_alive = True
                        self._frames_received = sequence

                    # Calculate sliding window FPS
                    self._timestamps.append(now_perf)
                    cutoff = now_perf - 3.0
                    while len(self._timestamps) > 2 and self._timestamps[0] < cutoff:
                        self._timestamps.popleft()
                    if len(self._timestamps) >= 2:
                        dt = self._timestamps[-1] - self._timestamps[0]
                        if dt >= 1.0:
                            with self._lock:
                                self._stream_fps = (len(self._timestamps) - 1) / dt

                    # Pacing: maintain target playback pace and avoid filling CPU/memory
                    elapsed = time.perf_counter() - t_start
                    sleep_time = max(0.0, frame_interval - elapsed)
                    if sleep_time > 0 and self._stop_event.wait(sleep_time):
                        break
                    continue

                if self._stop_event.is_set():
                    break

                # Stream ended or pipe closed. Determine whether this is a Clean EOF or Abnormal Exit.
                try:
                    proc.wait(timeout=0.5)
                except Exception:
                    pass
                exit_code = proc.poll()

                if exit_code == 0 and not read_exception:
                    is_clean_eof = True
                    break

                # Non-zero exit code or read exception or unexpected closure
                consecutive_read_failures += 1
                if exit_code is not None or consecutive_read_failures > 5 or read_exception:
                    break
                time.sleep(0.05)

            # Cleanup FFmpeg cleanly (cancellation-safe order)
            self._cleanup_process()

            if self._stop_event.is_set():
                break

            if is_clean_eof:
                self.clean_eof_count += 1
                self._retries_used = 0
                logger.info("[YOUTUBE-VOD] Clean EOF reached (exit_code=0, loop=%s)", self.loop)
                if not self.loop:
                    with self._lock:
                        self._finished = True
                        self._stream_alive = False
                        self._status = "VIDEO_FINISHED"
                    break
                else:
                    logger.info("[YOUTUBE-VOD] Looping enabled, restarting stream cleanly...")
                    if self._stop_event.wait(0.1):
                        break
                    continue
            else:
                # Abnormal exit: non-zero exit code, broken pipe, read exception, or HTTP error
                self.abnormal_exit_count += 1
                self._retries_used += 1
                stderr_tail = self._last_ffmpeg_stderr or "\n".join(self._stderr_lines)
                exit_code = self._last_ffmpeg_exit_code

                cat = classify_youtube_error(stderr_tail, default=ERROR_FFMPEG_ERROR)
                self.last_ffmpeg_error_type = cat

                if cat == ERROR_BOT_CHALLENGE or "AUTH/ANTI_BOT" in stderr_tail:
                    self.last_error_type = ERROR_BOT_CHALLENGE
                    self.last_error_message = "AUTH/ANTI_BOT: YouTube bot challenge / sign-in required"
                    with self._lock:
                        self._finished = True
                        self._stream_alive = False
                        self._status = "ERROR"
                        self._error_reason = self.last_error_message
                    logger.error("[YOUTUBE-VOD] Bot challenge detected in stderr, stopping retries immediately")
                    break

                elif cat == ERROR_HTTP_429:
                    self.last_error_type = ERROR_HTTP_429
                    self.last_error_message = f"HTTP 429 detected in FFmpeg stderr: {stderr_tail[-200:]}"
                    stream_resolver.record_429(source="ffmpeg_vod")
                    self._direct_url = None
                elif cat == ERROR_HTTP_403:
                    self.last_error_type = ERROR_HTTP_403
                    self.last_error_message = f"HTTP 403 detected in FFmpeg stderr: {stderr_tail[-200:]}"
                    stream_resolver.record_403(self.youtube_url, source="ffmpeg_vod")
                    self._direct_url = None
                else:
                    self.last_error_type = cat if cat != ERROR_FFMPEG_ERROR else ("FFMPEG_ABNORMAL_EXIT" if not read_exception else "READ_EXCEPTION")
                    self.last_error_message = f"FFmpeg abnormal exit {exit_code}: {stderr_tail[-200:]}" if not read_exception else self.last_error_message
                    stream_resolver.invalidate_cache(self.youtube_url, reason="ffmpeg_abnormal_exit")
                    self._direct_url = None

                logger.warning(
                    "[YOUTUBE-VOD] Abnormal exit: type=%s retries_used=%d/%d msg=%s",
                    self.last_error_type, self._retries_used, self.max_retries, self.last_error_message,
                )

                if self._retries_used >= self.max_retries:
                    with self._lock:
                        self._finished = True
                        self._stream_alive = False
                        self._status = "ERROR"
                        self._error_reason = f"Max retries ({self.max_retries}) reached after abnormal exit: {self.last_error_message}"
                    break

                backoff_delay = stream_resolver.get_cooldown_remaining() if self.last_error_type == "HTTP_429" else min(30.0, 1.0 * (2 ** (self._retries_used - 1)))
                if self._stop_event.wait(backoff_delay):
                    break

        with self._lock:
            self._stream_alive = False
            self._finished = True
            if self._status not in ("ERROR", "VIDEO_FINISHED"):
                self._status = "STOPPED"

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
        self._cleanup_process()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)
        with self._lock:
            self._stream_alive = False
            self._status = "STOPPED"
            self._latest = None
        logger.info("[YOUTUBE-VOD] Stopped cleanly")

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def error_reason(self) -> str:
        with self._lock:
            return self._error_reason

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
            proc = self._process
            proc_alive = proc is not None and proc.poll() is None
            return {
                "reader_type": "YouTubeVODReader",
                "source_type": "youtube_vod",
                "reader_alive": self._thread.is_alive() if self._thread else False,
                "ffmpeg_alive": proc_alive,
                "ffmpeg_pid": proc.pid if proc_alive else None,
                "ffmpeg_exit_code": proc.poll() if proc else self._last_ffmpeg_exit_code,
                "process_generation": self.process_generation,
                "frames_received": self._frames_received,
                "frame_age_seconds": self.frame_age_seconds,
                "first_frame_received": self._first_frame_received,
                "first_frame_timeout_count": self.first_frame_timeout_count,
                "stale_frame_timeout_count": self.stale_frame_timeout_count,
                "reconnect_count": self.reconnect_count,
                "ffmpeg_start_count": self.ffmpeg_start_count,
                "resolver_attempt_count": stream_resolver.metrics.resolver_attempt_count,
                "resolver_success_count": stream_resolver.metrics.resolver_success_count,
                "http_429_count": stream_resolver.metrics.http_429_count,
                "http_403_count": stream_resolver.metrics.http_403_count,
                "no_formats_count": stream_resolver.metrics.no_formats_count,
                "bot_challenge_count": stream_resolver.metrics.bot_challenge_count,
                "cooldown_remaining_seconds": round(stream_resolver.get_cooldown_remaining(), 2),
                "abnormal_exit_count": self.abnormal_exit_count,
                "clean_eof_count": self.clean_eof_count,
                "last_error_type": self.last_error_type,
                "last_error_message": self.last_error_message,
                "last_resolver_error_type": self.last_resolver_error_type,
                "last_ffmpeg_error_type": self.last_ffmpeg_error_type,
                "stream_fps": self._stream_fps,
                "read_errors": self._read_errors,
                "last_frame_time": self._last_frame_timestamp,
                "finished": self._finished,
                "status": self._status,
                "error_reason": self._error_reason,
                "youtube_url": self.youtube_url,
                "resolver_metrics": stream_resolver.get_metrics_dict(),
            }

