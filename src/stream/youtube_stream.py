"""YouTube Live, HLS, and RTSP/HTTP Video Stream Ingestion via yt-dlp and FFmpeg.

Continuously captures raw BGR24 frames in a dedicated thread,
maintaining only the latest frame buffer with zero queue buildup.
"""

from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any, cast

import cv2
import imageio_ffmpeg
import numpy as np
import yt_dlp
from yt_dlp.utils import DownloadError

logger = logging.getLogger("datt.stream")
YTDLP_REFRESH_COOLDOWN_SECONDS = 30.0
URL_REFRESH_AFTER_FAILURES = 3

try:
    import psutil
except ImportError:  # diagnostics remain available without optional psutil
    psutil = None


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    captured_at: float
    capture_latency_ms: float
    frame: np.ndarray


def read_frame_bytes(stream, size: int) -> bytes:
    """Read exact number of bytes from a pipe stream."""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def select_best_video_format(formats: list[dict[str, Any]]) -> str | None:
    """Select the best playable video stream format from yt-dlp format list.

    Filtering rules:
    - Exclude audio-only formats (vcodec == 'none' or missing)
    - Require valid non-empty 'url'

    Preference ranking:
    1. HLS / m3u8 stream (protocol starts with 'm3u8' or url contains '.m3u8')
    2. H264 / AVC codec (vcodec starts with 'avc' or 'h264')
    3. Target resolution: height <= 720 (prefer 720p, then 480p, 360p, etc.)
    4. Higher fps / bitrate
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

    def format_score(f: dict[str, Any]) -> tuple:
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
            res_score = -height  # prefer 1080 over 4K if forced >720
        else:
            res_tier = 0
            res_score = 0

        tbr = f.get("tbr") or f.get("vbr") or 0
        fps = f.get("fps") or 0

        return (is_hls, is_h264, res_tier, res_score, tbr, fps)

    best_format = max(valid_video_formats, key=format_score)
    return best_format.get("url")


def get_stream_url(url: str) -> str:
    """Extract direct video stream URL using yt-dlp if it is a YouTube URL.

    Robustly selects HLS / H264 <=720p video format for YouTube Live.
    """
    # If the URL is already a direct stream or file, return as is
    if not ("youtube.com" in url or "youtu.be" in url):
        return url

    ydl_opts: dict[str, Any] = {
        "format": "bestvideo[height<=720]/best[height<=720]/bestvideo/best",
        "quiet": True,
        "noplaylist": True,
        "js_runtimes": {
            "node": {}
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android"]
            }
        },
        "nocheckcertificate": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise RuntimeError(f"Failed extracting YouTube stream: {exc}") from exc

    if not info or not isinstance(info, dict):
        raise RuntimeError("Failed to extract video info from YouTube")

    # 1. First attempt robust format selection from available formats
    formats = info.get("formats", [])
    if isinstance(formats, list) and formats:
        selected_url = select_best_video_format(formats)
        if selected_url:
            return selected_url

    # 2. Fallback to info['url'] if present
    direct_url = info.get("url")
    if isinstance(direct_url, str) and direct_url:
        return direct_url

    raise RuntimeError("No valid video stream URL found from YouTube")


def build_ffmpeg_command(
    ffmpeg_path: str,
    stream_url: str,
    width: int,
    height: int,
) -> list[str]:
    """Construct FFmpeg command optimized for HLS, RTSP, and HTTP live streams."""
    cmd = [
        ffmpeg_path,
        "-nostdin",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-probesize", "10000000",
        "-analyzeduration", "5000000",
        "-rw_timeout", "15000000",
    ]

    # Add network protocol reconnection options for HTTP/HTTPS/HLS
    if stream_url.startswith("http://") or stream_url.startswith("https://"):
        cmd.extend([
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
        ])
    elif stream_url.startswith("rtsp://"):
        cmd.extend([
            "-rtsp_transport", "tcp",
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


class CameraReader:
    """Continuously reads FFmpeg output pipe with auto-recovery and health monitoring.

    Implements:
    - Zero-queue buffer to ensure inference latency does not cause lag.
    - Lifecycle monitoring and automatic reconnect on FFmpeg exit / EOF (up to 5 retries).
    - Zombie process prevention with proper pipe closure, wait(), and kill() fallback.
    - Stale frame detection (RUNNING <= 5s, WARNING <= 15s, ERROR > 15s).
    - Rolling 30-frame sliding window FPS measurement.
    """

    def __init__(self, url: str, width: int = 1280, height: int = 720):
        self.url = url
        self.width = width
        self.height = height
        self.frame_size = width * height * 3

        self.process: subprocess.Popen | None = None
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.latest: CapturedFrame | None = None
        self.last_read_sequence: int = -1

        self.stream_fps: float = 0.0
        self.last_capture_latency_ms: float = 0.0
        self.last_frame_age_ms: float = 0.0
        self.error: Exception | None = None
        self.finished: bool = False
        self._thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self.stderr_lines: list[str] = []
        self._process_started_at: float = 0.0
        self._frames_received: int = 0
        self.dropped_frames: int = 0
        self._read_errors: int = 0
        self._last_pipe_warning: str = ""
        self._health_thread: threading.Thread | None = None
        self._last_status: str = "STOPPED"
        self._last_ffmpeg_pid: int | None = None
        self._last_ffmpeg_exit_code: int | None = None
        self._last_ffmpeg_stderr: str = ""
        self._recovery_started_at: float = 0.0
        self._stream_url: str | None = None
        self._last_ytdlp_call_at: float = 0.0
        self._ytdlp_attempt: int = 0
        self.recovery_state: str = "STREAM_OK"

        # Health & Stale Frame Tracking
        self._last_frame_timestamp: float = 0.0
        self._stream_alive: bool = False
        self._stream_timestamps: deque[float] = deque(maxlen=30)

        # Auto-Recovery Configuration
        self.reconnect_attempts: int = 0
        self.max_reconnect_retries: int = 5
        self.reconnect_delays: list[int] = [3, 5, 10, 15, 30]

    @property
    def last_frame_time(self) -> float:
        """Timestamp of newest captured frame."""
        with self.lock:
            return self._last_frame_timestamp

    @property
    def frame_age_seconds(self) -> float:
        """Elapsed seconds since newest frame was captured."""
        with self.lock:
            if self._last_frame_timestamp <= 0.0:
                return 999.0
            return max(0.0, time.time() - self._last_frame_timestamp)

    @property
    def stream_alive(self) -> bool:
        """Health flag indicating stream process is active and publishing recent frames."""
        with self.lock:
            age = 999.0 if self._last_frame_timestamp <= 0.0 else max(0.0, time.time() - self._last_frame_timestamp)
            return self._stream_alive and age <= 15.0

    @property
    def status(self) -> str:
        """Operational status based on frame age:
        - RUNNING: frame_age <= 5s
        - WARNING: 5s < frame_age <= 15s
        - ERROR: frame_age > 15s or process stopped
        """
        if self.stop_event.is_set():
            return "STOPPED"
        with self.lock:
            if self.finished and not self._stream_alive:
                return "ERROR"
            age = 999.0 if self._last_frame_timestamp <= 0.0 else max(0.0, time.time() - self._last_frame_timestamp)
            if age <= 5.0 and self._stream_alive:
                return "RUNNING"
            elif age <= 15.0:
                return "WARNING"
            else:
                return "ERROR"

    def _spawn_ffmpeg(self, stream_url: str) -> None:
        """Construct FFmpeg command, spawn subprocess, and start stderr drain thread."""
        ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_command = build_ffmpeg_command(
            ffmpeg_path=ffmpeg_path,
            stream_url=stream_url,
            width=self.width,
            height=self.height,
        )
        self.stderr_lines = []
        self.process = subprocess.Popen(
            ffmpeg_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._last_ffmpeg_pid = self.process.pid
        self._last_ffmpeg_exit_code = None
        self._last_ffmpeg_stderr = ""
        self._process_started_at = time.time()
        logger.info("[DATT-FFMPEG] started pid=%s", self.process.pid)
        logger.info("[DATT-STREAM START] pid=%s frame_size=%s url=%s", self.process.pid, self.frame_size, stream_url)
        if self.process.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(self.process.stderr,),
                name="ffmpeg-stderr",
                daemon=True,
            )
            self._stderr_thread.start()

        time.sleep(0.5)
        if self.process.poll() is not None:
            err_msg = " ".join(self.stderr_lines[-5:]) if self.stderr_lines else "Process exited early"
            raise RuntimeError(f"FFmpeg failed to open video stream: {err_msg}")

    def start(self) -> None:
        """Resolve stream URL, spawn FFmpeg process with retries, and start reader thread."""
        max_retries = 3
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                stream_url = self._get_stream_url_with_diagnostics("startup")
                self._stream_url = stream_url
                self._spawn_ffmpeg(stream_url)

                self.stop_event.clear()
                self.finished = False
                self._last_frame_timestamp = time.time()
                self._stream_alive = True
                self._thread = threading.Thread(
                    target=self._read_loop, name="ffmpeg-capture", daemon=True
                )
                self._thread.start()
                self._health_thread = threading.Thread(target=self._health_loop, name="ffmpeg-health", daemon=True)
                self._health_thread.start()
                return

            except Exception as exc:
                last_error = exc
                logger.warning(
                    "CameraReader: Attempt %d/%d to start stream failed: %s",
                    attempt,
                    max_retries,
                    exc,
                )
                self._cleanup_process()
                if attempt < max_retries:
                    time.sleep(3.0)

        raise RuntimeError(
            f"FFmpeg failed to open YouTube video stream after {max_retries} attempts: {last_error}"
        ) from last_error

    def _drain_stderr(self, pipe) -> None:
        """Continuously drain FFmpeg stderr to prevent pipe buffer deadlocks."""
        try:
            for line in iter(pipe.readline, b""):
                decoded = line.decode(errors="replace").strip()
                if decoded:
                    self.stderr_lines.append(decoded)
                    if len(self.stderr_lines) > 50:
                        self.stderr_lines.pop(0)
        except Exception as exc:
            self._log_thread_error("ffmpeg-stderr", exc)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _cleanup_process(self) -> None:
        """Safely terminate FFmpeg process, closing pipes and avoiding zombie processes."""
        proc = self.process
        self.process = None

        if proc is not None:
            # Snapshot lifecycle data before releasing the process object.
            self._last_ffmpeg_exit_code = proc.poll()
            self._last_ffmpeg_stderr = "\n".join(self.stderr_lines)[-2000:]
            # 1. Close stdout to unblock reading threads
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

            # 2. Terminate or kill
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

            try:
                proc.wait(timeout=2.0)
            except (subprocess.TimeoutExpired, Exception):
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except Exception:
                    pass

            # 3. Close stderr
            if proc.stderr is not None:
                try:
                    proc.stderr.close()
                except Exception:
                    pass
            logger.info("[DATT-STREAM FFmpeg EXIT] pid=%s exit_code=%s stderr=%s",
                        self._last_ffmpeg_pid, self._last_ffmpeg_exit_code,
                        self._last_ffmpeg_stderr or "<empty>")

    def _reconnect(self) -> bool:
        """Execute auto-reconnect backoff sequence when FFmpeg exits unexpectedly."""
        while not self.stop_event.is_set() and self.reconnect_attempts < self.max_reconnect_retries:
            self.reconnect_attempts += 1
            delay_idx = min(self.reconnect_attempts - 1, len(self.reconnect_delays) - 1)
            delay = self.reconnect_delays[delay_idx]
            logger.warning(
                "[DATT-STREAM] Reconnect attempt %d/%d (waiting %ds)...",
                self.reconnect_attempts,
                self.max_reconnect_retries,
                delay,
            )
            # Sleep with stop_event check
            if self.stop_event.wait(delay):
                return False

            try:
                use_refresh = self._stream_url is None or self.reconnect_attempts >= URL_REFRESH_AFTER_FAILURES
                strategy = "refresh_url" if use_refresh else ("use_cached_url" if self._stream_url else "restart_ffmpeg")
                self.recovery_state = "URL_REFRESH_REQUIRED" if use_refresh else "FFmpeg_RESTART"
                logger.info("[DATT-RECOVERY] attempt=%s strategy=%s", self.reconnect_attempts, strategy)
                new_url = self._get_stream_url_with_diagnostics("recovery") if use_refresh else self._stream_url
                assert new_url is not None
                self._spawn_ffmpeg(new_url)
                self._stream_url = new_url
                logger.info("[DATT STREAM RECOVERY] attempt=%s new_url=%s new_pid=%s recovered_time=%s",
                            self.reconnect_attempts, new_url, self.process.pid if self.process else None,
                            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
                return True
            except Exception as exc:
                logger.warning(
                    "[DATT-STREAM] Reconnect attempt %d/%d failed: %s",
                    self.reconnect_attempts,
                    self.max_reconnect_retries,
                    exc,
                )
                self._cleanup_process()

        self.recovery_state = "FAILED"
        logger.error("[DATT-RECOVERY] attempt=%s strategy=FAILED", self.reconnect_attempts)
        return False

    def _get_stream_url_with_diagnostics(self, reason: str) -> str:
        now = time.time()
        elapsed = now - self._last_ytdlp_call_at
        remaining = max(0.0, YTDLP_REFRESH_COOLDOWN_SECONDS - elapsed)
        allowed = remaining <= 0.0
        logger.info("[DATT-YTDLP] refresh_allowed=%s last_refresh=%s cooldown_remaining=%.1f",
                    allowed, self._last_ytdlp_call_at or None, remaining)
        if not allowed:
            raise RuntimeError("yt-dlp refresh cooldown active")
        self._ytdlp_attempt += 1
        self._last_ytdlp_call_at = now
        logger.info("[DATT-YTDLP CALL] timestamp=%s reason=%s attempt=%s",
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), reason, self._ytdlp_attempt)
        try:
            result = get_stream_url(self.url)
            logger.info("[DATT-YTDLP RESULT] success=True error=")
            return result
        except Exception as exc:
            logger.error("[DATT-YTDLP RESULT] success=False error=%s", exc, exc_info=True)
            raise

    def _read_loop(self) -> None:
        """Reader thread boundary that preserves an unexpected traceback."""
        try:
            self._read_loop_impl()
        except Exception as exc:
            self._log_thread_error("ffmpeg-capture", exc)
            logger.error("[DATT-READER EXIT] unexpected_exception=%s", exc)
            with self.lock:
                self._stream_alive = False
                self.finished = True

    def _read_loop_impl(self) -> None:
        """Read frame bytes from FFmpeg pipe continuously with auto-reconnection."""
        sequence = 0
        self.reconnect_attempts = 0

        while not self.stop_event.is_set():
            if self.process is None or self.process.stdout is None:
                if not self._reconnect():
                    break
                continue

            read_start = time.perf_counter()
            try:
                raw = read_frame_bytes(self.process.stdout, self.frame_size)
            except Exception as exc:
                self._read_errors += 1
                self._log_thread_error("ffmpeg-capture", exc)
                raw = b""
            read_end = time.perf_counter()

            if (read_end - read_start) > 2.0 or len(raw) != self.frame_size:
                logger.warning("[DATT-PIPE WARNING] read_duration_ms=%.1f expected_bytes=%d received_bytes=%d",
                               (read_end - read_start) * 1000, self.frame_size, len(raw))
                logger.warning("[DATT-STREAM FRAME EOF] expected_bytes=%d received_bytes=%d ffmpeg_poll=%s",
                               self.frame_size, len(raw), self.process.poll() if self.process else None)

            if len(raw) == self.frame_size:
                now_wall = time.time()
                now_perf = time.perf_counter()
                frame = np.frombuffer(raw, np.uint8).reshape(
                    self.height, self.width, 3
                ).copy()
                sequence += 1

                with self.lock:
                    self.latest = CapturedFrame(
                        sequence=sequence,
                        captured_at=now_perf,
                        capture_latency_ms=(read_end - read_start) * 1000,
                        frame=frame,
                    )
                    self._last_frame_timestamp = now_wall
                    self._stream_alive = True
                    self._frames_received = sequence

                # Sliding window FPS (last 30 timestamps)
                self._stream_timestamps.append(now_perf)
                if len(self._stream_timestamps) >= 2:
                    dt = self._stream_timestamps[-1] - self._stream_timestamps[0]
                    if dt > 0:
                        with self.lock:
                            self.stream_fps = (len(self._stream_timestamps) - 1) / dt

                if self.reconnect_attempts > 0:
                    delay_ms = (time.time() - self._recovery_started_at) * 1000 if self._recovery_started_at else 0.0
                    logger.info("[DATT-STREAM RECOVERED] new_pid=%s first_frame_delay_ms=%.1f",
                                self.process.pid if self.process else self._last_ffmpeg_pid, delay_ms)
                    self.reconnect_attempts = 0
                    self._recovery_started_at = 0.0
                    self.recovery_state = "STREAM_OK"

                continue

            # EOF or broken pipe encountered
            if self.stop_event.is_set():
                break

            proc = self.process
            exit_code = proc.poll() if proc is not None else None
            old_pid = proc.pid if proc is not None else self._last_ffmpeg_pid
            old_runtime = time.time() - self._process_started_at if self._process_started_at else 0.0
            reason = "stdout_eof" if len(raw) == 0 else "incomplete_frame"
            logger.error("[DATT-REGRESSION] before reconnect ffmpeg_pid=%s exit_code=%s stderr_tail=%s last_frame_timestamp=%s reader_thread_alive=%s",
                         old_pid, exit_code, "\n".join(self.stderr_lines)[-2000:] or "<empty>",
                         self.last_frame_time,
                         self._thread.is_alive() if self._thread else False)
            logger.warning("[DATT-STREAM RECOVERY] reason=%s old_pid=%s old_runtime=%ss",
                           reason, old_pid, int(old_runtime))
            logger.warning("[DATT-STREAM FFmpeg EXIT] exit_code=%s stderr=%s",
                           exit_code, "\n".join(self.stderr_lines)[-2000:])
            logger.error("[DATT STREAM FAILURE] pid=%s runtime=%ss exit_code=%s stderr=%s",
                         old_pid, int(old_runtime), exit_code,
                         "\n".join(self.stderr_lines)[-2000:] or "<empty>")
            logger.warning("[DATT-STREAM STDERR] %s", "\n".join(self.stderr_lines)[-2000:] or "<empty>")
            with self.lock:
                self._stream_alive = False
                self.latest = None
                self.last_read_sequence = -1

            self._recovery_started_at = time.time()

            self._cleanup_process()

            if not self._reconnect():
                break

        with self.lock:
            self._stream_alive = False
            self.finished = True
        logger.info("[DATT-READER EXIT] frames_received=%s ffmpeg_poll=%s stderr=%s",
                    self._frames_received, self.process.poll() if self.process else None,
                    "\n".join(self.stderr_lines)[-2000:] or "<empty>")
        self._cleanup_process()

    def _log_thread_error(self, name: str, exc: Exception) -> None:
        import traceback
        logger.error("[DATT-THREAD ERROR] thread_name=%s exception_type=%s exception_message=%s traceback=%s",
                     name, type(exc).__name__, exc, traceback.format_exc())

    def _health_loop(self) -> None:
        """Periodic lifecycle/resource diagnostics; intentionally no recovery actions."""
        last_resource = 0.0
        while not self.stop_event.wait(10.0):
            proc = self.process
            alive = proc is not None and proc.poll() is None
            code = None if proc is None else proc.poll()
            runtime = max(0.0, time.time() - self._process_started_at) if self._process_started_at else 0.0
            logger.info("[DATT-FFMPEG HEALTH]\npid=%s\nalive=%s\nreturn_code=%s\nruntime=%ss",
                        proc.pid if proc else self._last_ffmpeg_pid, alive,
                        code if proc is not None else self._last_ffmpeg_exit_code, int(runtime))
            age = self.frame_age_seconds
            logger.info("[DATT-CAMERA READER HEALTH]\nthread_alive=%s\nframes_received=%s\nlast_frame_time=%s\nframe_age_seconds=%.1f\nstream_fps=%.2f\nread_errors=%s",
                        self._thread.is_alive() if self._thread else False, self._frames_received,
                        self.last_frame_time, age, self.stream_fps, self._read_errors)
            if (proc is not None and code is not None) or self._last_ffmpeg_exit_code is not None:
                logger.error("[DATT-FFMPEG EXIT]\nexit_code=%s\nruntime=%ss\nlast_stderr=%s",
                             code if proc is not None else self._last_ffmpeg_exit_code,
                             int(runtime), self._last_ffmpeg_stderr or "\n".join(self.stderr_lines)[-2000:])
            status = self.status
            if status != self._last_status:
                logger.warning("[DATT-STREAM STATE CHANGE]\nold_status=%s\nnew_status=%s\nreason=%s\nlast_frame_age=%.1f\nffmpeg_alive=%s\nreader_alive=%s",
                               self._last_status, status, self.error or "", age, alive,
                               self._thread.is_alive() if self._thread else False)
                self._last_status = status
            if psutil is not None and time.time() - last_resource >= 60:
                try:
                    p = psutil.Process()
                    logger.info("[DATT-RESOURCE] RAM usage=%sMB GPU memory usage=unavailable number of threads=%s number of processes=%s",
                                round(p.memory_info().rss / 1048576, 1), threading.active_count(), len(psutil.pids()))
                except Exception as exc:
                    self._log_thread_error("ffmpeg-health", exc)
                last_resource = time.time()

    def diagnostics(self) -> dict[str, Any]:
        proc = self.process
        return {"ffmpeg_alive": proc is not None and proc.poll() is None,
                "reader_alive": self._thread.is_alive() if self._thread else False,
                "last_frame_age": self.frame_age_seconds, "frames_received": self._frames_received,
                "ffmpeg_pid": proc.pid if proc else self._last_ffmpeg_pid,
                "ffmpeg_exit_code": proc.poll() if proc else self._last_ffmpeg_exit_code,
                "last_error": str(self.error or "") or self._last_ffmpeg_stderr or ("\n".join(self.stderr_lines)[-2000:] if self.stderr_lines else "")}

    @property
    def buffer_age_ms(self) -> float:
        return self.frame_age_seconds * 1000.0

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        """Read the newest available frame.

        Blocks up to timeout seconds until a new frame arrives.
        Returns None if stream has terminated or timed out.
        """
        # If stream has stalled > 15s while process is alive, terminate stalled FFmpeg to unblock auto-recovery
        if self.process is not None and self.frame_age_seconds > 15.0:
            logger.warning("[DATT-STREAM] Stale frame detected (>15s). Terminating unresponsive FFmpeg process.")
            logger.error("[DATT-REGRESSION] stale watchdog terminating ffmpeg_pid=%s exit_code=%s stderr_tail=%s last_frame_timestamp=%s reader_thread_alive=%s",
                         self.process.pid, self.process.poll(), "\n".join(self.stderr_lines)[-2000:] or "<empty>",
                         self.last_frame_time, self._thread.is_alive() if self._thread else False)
            self._recovery_started_at = time.time()
            with self.lock:
                self.latest = None
                self._stream_alive = False
            self._cleanup_process()

        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self.lock:
                if self.error is not None:
                    raise RuntimeError("Camera capture error") from self.error

                if self.latest is not None and self.latest.sequence != self.last_read_sequence:
                    self.last_read_sequence = self.latest.sequence
                    self.last_capture_latency_ms = self.latest.capture_latency_ms
                    self.last_frame_age_ms = (time.perf_counter() - self.latest.captured_at) * 1000
                    return self.latest.frame.copy()

                if self.finished and not self._stream_alive and self.process is None:
                    return None

            time.sleep(0.001)

        return None

    def stop(self) -> None:
        """Safely terminate FFmpeg subprocess and reader thread."""
        self.stop_event.set()
        self._cleanup_process()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
