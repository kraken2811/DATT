"""YouTube Live, HLS, and RTSP/HTTP Video Stream Ingestion via yt-dlp and FFmpeg.

Continuously captures raw BGR24 frames in a dedicated thread,
maintaining only the latest frame buffer with zero queue buildup.
"""

from collections import deque
from dataclasses import dataclass
import logging
import random
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

import config

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


def get_stream_url(url: str, is_vod: bool = False) -> str:
    """Extract direct video stream URL using yt-dlp if it is a YouTube URL.

    Robustly selects HLS / H264 <=720p video format for YouTube Live, or MP4 for VOD.
    Delegates to centralized stream_resolver for caching, single-flight deduplication,
    global rate limiting, and HTTP 429 backoff.
    """
    if not ("youtube.com" in url or "youtu.be" in url or (len(url) == 11 and "/" not in url)):
        return url

    return stream_resolver.resolve_stream_url(url, is_vod=is_vod)



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

    # Add User-Agent and network reconnection options for HTTP/HTTPS/HLS inputs.
    if stream_url.startswith("http://") or stream_url.startswith("https://"):
        cmd.extend([
            "-user_agent", "Mozilla/5.0",
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

    def __init__(self, url: str, width: int = 1280, height: int = 720, is_vod: bool = False):
        self.url = url
        self.width = width
        self.height = height
        self.frame_size = width * height * 3
        self.is_vod = is_vod

        self.source_type = "youtube_vod" if is_vod else "youtube"
        self._status: str = "STOPPED"
        self.error_reason: str = ""
        self.process_generation: int = 0
        self._process_started_at: float = 0.0
        self._first_frame_received: bool = False
        self._generation_frame_timestamp: float = 0.0
        self._first_frame_timeout_count: int = 0
        self._stale_frame_timeout_count: int = 0
        self.reconnect_count: int = 0
        self.ffmpeg_start_count: int = 0
        self.abnormal_exit_count: int = 0
        self.clean_eof_count: int = 0
        self.last_error_type: str = ""
        self.last_error_message: str = ""
        self.last_resolver_error_type: str = ""
        self.last_ffmpeg_error_type: str = ""
        self.first_frame_timeout_seconds: float = 15.0
        self.stale_frame_timeout_seconds: float = 15.0

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
        self._stream_timestamps: deque[float] = deque(maxlen=150)

        # Auto-Recovery Configuration
        self.reconnect_attempts: int = 0
        self.reconnect_delays: list[int] = [3, 5, 10, 20, 40, 60, 120, 300]
        self._force_url_refresh = False
        self._stale_termination_requested = False
        self._consecutive_frame_failures: int = 0
        self._direct_reconnect_attempts: int = 0

    @property
    def first_frame_timeout_count(self) -> int:
        return self._first_frame_timeout_count

    @property
    def stale_frame_timeout_count(self) -> int:
        return self._stale_frame_timeout_count

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
            if getattr(self, "_status", None) == "VIDEO_FINISHED":
                return "VIDEO_FINISHED"
            if self.finished and not self._stream_alive:
                if self.is_vod and self.clean_eof_count > 0:
                    return "VIDEO_FINISHED"
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
        if self.stop_event.is_set():
            raise RuntimeError("Cannot spawn FFmpeg: reader is stopped")

        self.process_generation += 1
        self.ffmpeg_start_count += 1
        self._first_frame_received = False
        self._generation_frame_timestamp = 0.0
        self._stale_termination_requested = False
        self.stderr_lines = []

        ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_command = build_ffmpeg_command(
            ffmpeg_path=ffmpeg_path,
            stream_url=stream_url,
            width=self.width,
            height=self.height,
        )
        proc = subprocess.Popen(
            ffmpeg_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if self.stop_event.is_set():
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            raise RuntimeError("Stopped immediately after spawn")

        with self.lock:
            self.process = proc
            self._last_ffmpeg_pid = proc.pid
            self._last_ffmpeg_exit_code = None
            self._last_ffmpeg_stderr = ""
            self._process_started_at = time.time()

        logger.info("[DATT-FFMPEG] started pid=%s gen=%s", proc.pid, self.process_generation)
        logger.info("[DATT-STREAM START] pid=%s frame_size=%s", proc.pid, self.frame_size)

        if proc.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(proc.stderr,),
                name="ffmpeg-stderr",
                daemon=True,
            )
            self._stderr_thread.start()

        if self.stop_event.wait(0.3):
            return

        if proc.poll() is not None:
            err_msg = " ".join(self.stderr_lines[-5:]) if self.stderr_lines else "Process exited early"
            raise RuntimeError(f"FFmpeg failed to open video stream: {err_msg}")

    def start(self) -> None:
        """Start capture asynchronously; startup failures use the same retry loop."""
        if self._thread is not None and self._thread.is_alive():
            return
        self.stop_event.clear()
        self.finished = False
        self._last_frame_timestamp = 0.0
        self._stream_alive = False
        self._thread = threading.Thread(target=self._read_loop, name="ffmpeg-capture", daemon=True)
        self._thread.start()
        self._health_thread = threading.Thread(target=self._health_loop, name="ffmpeg-health", daemon=True)
        self._health_thread.start()

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
        """Safely terminate FFmpeg process according to cancel-safe cleanup order:
        1. mark stopping / prevent race
        2. terminate FFmpeg first
        3. allow blocked pipe reads to unblock
        4. wait with deadline
        5. kill if still alive
        6. close stdout / stderr
        7. verify process is gone
        """
        with self.lock:
            proc = self.process
            self.process = None

        if proc is not None:
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
            self._last_ffmpeg_stderr = "\n".join(self.stderr_lines)[-2000:]
            self.stderr_lines.clear()

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

            logger.info(
                "[DATT-STREAM FFmpeg EXIT] pid=%s exit_code=%s stderr=%s",
                self._last_ffmpeg_pid, self._last_ffmpeg_exit_code,
                self._last_ffmpeg_stderr or "<empty>",
            )

    def _reconnect(self) -> bool:
        """Retry indefinitely with bounded delays until stopped or recovered.

        Follows Smart Reconnection rules:
        Step 1: Try reconnecting using the current direct stream URL (up to STREAM_DIRECT_RECONNECT_RETRIES times).
        Step 2: Only after direct URL reconnect fails repeatedly (or forced refresh), invalidate cache and call stream_resolver.
        Step 3: Handled by stream_resolver with exponential backoff + jitter on HTTP 429.
        """
        direct_reconnect_limit = getattr(config, "STREAM_DIRECT_RECONNECT_RETRIES", 3)

        while not self.stop_event.is_set():
            # Check shared rate-limit cooldown
            cooldown_rem = stream_resolver.get_cooldown_remaining()
            if cooldown_rem > 0:
                logger.warning("[DATT-STREAM] In shared 429 cooldown (%.1fs remaining). Pausing reconnect...", cooldown_rem)
                if self.stop_event.wait(cooldown_rem):
                    return False

            self.reconnect_attempts += 1
            self.reconnect_count = self.reconnect_attempts
            delay_idx = min(self.reconnect_attempts - 1, len(self.reconnect_delays) - 1)
            delay = 0 if self.reconnect_attempts == 1 and self._stream_url is None else self.reconnect_delays[delay_idx]

            # Decide whether to retry direct URL or refresh from resolver
            use_cached = (
                not self._force_url_refresh
                and self._stream_url is not None
                and self._direct_reconnect_attempts < direct_reconnect_limit
            )

            if use_cached:
                logger.info(
                    "[STREAM] camera=%s reconnect existing URL (attempt %d/%d)",
                    self.url, self._direct_reconnect_attempts + 1, direct_reconnect_limit,
                )
            else:
                logger.info("[STREAM] camera=%s requesting new URL from resolver", self.url)

            delay = max(0, delay)
            if delay > 0:
                delay += random.uniform(0, min(5, delay * 0.1))
                logger.warning(
                    "[DATT-STREAM] Reconnect attempt %d (waiting %.1fs)...",
                    self.reconnect_attempts,
                    delay,
                )
            # Sleep with stop_event check
            if self.stop_event.wait(delay):
                return False

            if self.stop_event.is_set():
                return False

            try:
                if use_cached:
                    self._direct_reconnect_attempts += 1
                    target_url = self._stream_url
                    strategy = "use_cached_url"
                else:
                    strategy = "refresh_url"
                    stream_resolver.invalidate_cache(self.url, reason="direct_reconnect_exhausted")
                    target_url = self._get_stream_url_with_diagnostics("recovery")
                    self._direct_reconnect_attempts = 0

                assert target_url is not None
                if self.stop_event.is_set():
                    return False

                self.recovery_state = "URL_REFRESH_REQUIRED" if not use_cached else "FFmpeg_RESTART"
                logger.info("[DATT-RECOVERY] attempt=%s strategy=%s", self.reconnect_attempts, strategy)
                self._spawn_ffmpeg(target_url)
                self._stream_url = target_url
                self._force_url_refresh = False
                self._consecutive_frame_failures = 0
                stream_resolver.record_success(self.url)
                if use_cached:
                    stream_resolver.metrics.direct_url_reconnects += 1
                logger.info(
                    "[DATT STREAM RECOVERY] attempt=%s new_pid=%s recovered_time=%s",
                    self.reconnect_attempts, self.process.pid if self.process else None,
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
                return True

            except Exception as exc:
                stream_resolver.record_failure(self.url)
                err_str = str(exc)
                cat = classify_youtube_error(err_str, default=ERROR_EXTRACTOR_ERROR)
                self.last_resolver_error_type = cat
                self.last_error_type = cat
                self.last_error_message = err_str

                if cat == ERROR_HTTP_429:
                    self.last_error_message = f"429 in reconnect: {err_str}"
                    stream_resolver.record_429(source="camera_reconnect")
                    # Suppress immediate yt-dlp refresh during cooldown
                    self._force_url_refresh = False
                    self._stream_url = None
                    logger.error("[YT-429] 429 detected during camera reconnect on %s", self.url)
                elif cat == ERROR_HTTP_403:
                    self.last_error_message = f"403 in reconnect: {err_str}"
                    stream_resolver.record_403(self.url, source="camera_reconnect")
                    if self._direct_reconnect_attempts >= direct_reconnect_limit:
                        self._force_url_refresh = True
                        self._stream_url = None
                    logger.warning("[YT-403] 403 detected during camera reconnect on %s", self.url)
                elif cat == ERROR_NO_FORMATS:
                    # NO_FORMATS is NOT 429! Do NOT call record_429()
                    self._force_url_refresh = True
                    self._stream_url = None
                    self.abnormal_exit_count += 1
                    logger.warning("[YT-RECONNECT] No video formats found for %s, will retry with bounded backoff", self.url)
                elif cat == ERROR_BOT_CHALLENGE or "AUTH/ANTI_BOT" in err_str or "confirm you're not a bot" in err_str.lower():
                    self.last_error_type = ERROR_BOT_CHALLENGE
                    self.last_error_message = f"AUTH/ANTI_BOT: YouTube bot challenge / sign-in required: {err_str}"
                    self.error = exc
                    self.finished = True
                    with self.lock:
                        self._status = "ERROR"
                        self.error_reason = self.last_error_message
                    logger.error("[YT-BOT] Bot challenge detected on %s, stopping reconnect immediately", self.url)
                    self._cleanup_process()
                    return False
                elif cat == ERROR_VIDEO_UNAVAILABLE:
                    self._force_url_refresh = True
                    self._stream_url = None
                    self.abnormal_exit_count += 1
                    logger.error("[YT-RECONNECT] Video unavailable: %s", self.url)
                    if self.reconnect_attempts >= 3:
                        logger.error("[YT-RECONNECT] Video %s permanently unavailable, aborting reconnect", self.url)
                        self.error = exc
                        self.finished = True
                        return False
                else:
                    self.abnormal_exit_count += 1
                    logger.warning(
                        "[DATT-STREAM] Reconnect attempt %d failed: %s (%s)",
                        self.reconnect_attempts,
                        cat,
                        type(exc).__name__,
                    )
                self._cleanup_process()

        self.recovery_state = "STOPPED"
        return False

    def _get_stream_url_with_diagnostics(self, reason: str) -> str:
        now = time.time()
        self._ytdlp_attempt += 1
        self._last_ytdlp_call_at = now
        logger.info(
            "[DATT-YTDLP CALL] timestamp=%s reason=%s attempt=%s",
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), reason, self._ytdlp_attempt,
        )
        try:
            result = get_stream_url(self.url, is_vod=self.is_vod)
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
        self._consecutive_frame_failures = 0
        max_frame_failures = getattr(config, "STREAM_READ_FAILURE_THRESHOLD", 10)

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

            if len(raw) == self.frame_size:
                self._consecutive_frame_failures = 0
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
                    self._generation_frame_timestamp = now_wall
                    self._first_frame_received = True
                    self._stream_alive = True
                    self._frames_received = sequence

                # Sliding window FPS (bounded 3.0s window to avoid burst decoding spikes)
                self._stream_timestamps.append(now_perf)
                cutoff = now_perf - 3.0
                while len(self._stream_timestamps) > 2 and self._stream_timestamps[0] < cutoff:
                    self._stream_timestamps.popleft()
                if len(self._stream_timestamps) >= 2:
                    dt = self._stream_timestamps[-1] - self._stream_timestamps[0]
                    if dt >= 1.0:
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

            # Incomplete or empty frame bytes received
            if self.stop_event.is_set():
                break

            self._consecutive_frame_failures += 1
            proc = self.process
            proc_alive = proc is not None and proc.poll() is None

            # Distinguish temporary frame drop from true stream death:
            if proc_alive and self._consecutive_frame_failures < max_frame_failures:
                logger.debug(
                    "[DATT-PIPE WARNING] read_duration_ms=%.1f expected_bytes=%d received_bytes=%d (drop %d/%d)",
                    (read_end - read_start) * 1000, self.frame_size, len(raw),
                    self._consecutive_frame_failures, max_frame_failures,
                )
                time.sleep(0.05)
                continue

            # Failure threshold exceeded or FFmpeg process exited
            exit_code = proc.poll() if proc is not None else None
            old_pid = proc.pid if proc is not None else self._last_ffmpeg_pid
            old_runtime = time.time() - self._process_started_at if self._process_started_at else 0.0
            reason = "stdout_eof" if len(raw) == 0 else "incomplete_frame"
            logger.warning(
                "[DATT-STREAM RECOVERY] reason=%s old_pid=%s old_runtime=%ss consecutive_failures=%d",
                reason, old_pid, int(old_runtime), self._consecutive_frame_failures,
            )
            logger.warning(
                "[DATT-STREAM FFmpeg EXIT] exit_code=%s stderr=%s",
                exit_code, "\n".join(self.stderr_lines)[-2000:],
            )

            with self.lock:
                self._stream_alive = False
                self.latest = None
                self.last_read_sequence = -1

            self._recovery_started_at = time.time()
            stderr_tail = "\n".join(self.stderr_lines)

            if exit_code == 0:
                self.clean_eof_count += 1
                self.last_error_type = "CLEAN_EOF"
                self.last_ffmpeg_error_type = "CLEAN_EOF"
                if self.is_vod:
                    logger.info("[DATT-STREAM] Clean EOF on YouTube VOD reached, stopping with VIDEO_FINISHED")
                    with self.lock:
                        self.finished = True
                        self._stream_alive = False
                        self._status = "VIDEO_FINISHED"
                    self._cleanup_process()
                    break
            else:
                self.abnormal_exit_count += 1
                cat = classify_youtube_error(stderr_tail, default=ERROR_FFMPEG_ERROR)
                self.last_ffmpeg_error_type = cat
                if cat == ERROR_HTTP_429:
                    self.last_error_type = ERROR_HTTP_429
                    self.last_error_message = f"429 in FFmpeg: {stderr_tail[-200:]}"
                    stream_resolver.record_429(source="ffmpeg_live")
                    self._force_url_refresh = False
                    self._stream_url = None
                elif cat == ERROR_HTTP_403:
                    self.last_error_type = ERROR_HTTP_403
                    self.last_error_message = f"403 in FFmpeg: {stderr_tail[-200:]}"
                    stream_resolver.record_403(self.url, source="ffmpeg_live")
                    self._force_url_refresh = True
                    self._stream_url = None
                else:
                    self.last_error_type = cat if cat != ERROR_FFMPEG_ERROR else "FFMPEG_ABNORMAL_EXIT"
                    self.last_error_message = f"FFmpeg abnormal exit {exit_code}: {stderr_tail[-200:]}"

            self._cleanup_process()
            self._stale_termination_requested = False

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
        with self.lock:
            proc = self.process
            proc_alive = proc is not None and proc.poll() is None
            return {
                "reader_type": "CameraReader",
                "source_type": "youtube",
                "reader_alive": self._thread.is_alive() if self._thread else False,
                "ffmpeg_alive": proc_alive,
                "ffmpeg_pid": proc.pid if proc_alive else None,
                "ffmpeg_exit_code": proc.poll() if proc else self._last_ffmpeg_exit_code,
                "process_generation": self.process_generation,
                "frames_received": self._frames_received,
                "frame_age_seconds": self.frame_age_seconds,
                "first_frame_received": self._first_frame_received,
                "first_frame_timeout_count": self._first_frame_timeout_count,
                "stale_frame_timeout_count": self._stale_frame_timeout_count,
                "reconnect_count": self.reconnect_attempts,
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
                "stream_fps": self.stream_fps,
                "last_frame_time": self._last_frame_timestamp,
                "last_frame_age": self.frame_age_seconds,
                "last_error": str(self.error or "") or self._last_ffmpeg_stderr or ("\n".join(self.stderr_lines)[-2000:] if self.stderr_lines else ""),
                "resolver_metrics": stream_resolver.get_metrics_dict(),
            }

    @property
    def buffer_age_ms(self) -> float:
        return self.frame_age_seconds * 1000.0

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        """Read the newest available frame.

        Blocks up to timeout seconds until a new frame arrives.
        Returns None if stream has terminated or timed out.
        """
        # Generation-aware watchdogs
        proc = self.process
        if proc is not None and proc.poll() is None and not self._stale_termination_requested:
            now = time.time()
            # Condition A: FIRST FRAME TIMEOUT
            # Process started but has not delivered its first frame within deadline
            if not self._first_frame_received:
                if self._process_started_at > 0 and (now - self._process_started_at) > self.first_frame_timeout_seconds:
                    self._first_frame_timeout_count += 1
                    self.last_error_type = "FIRST_FRAME_TIMEOUT"
                    self.last_error_message = f"Process gen={self.process_generation} delivered no frame within {self.first_frame_timeout_seconds}s"
                    logger.warning(
                        "[DATT-STREAM] First-frame timeout (>%ss). Terminating unresponsive FFmpeg process.",
                        self.first_frame_timeout_seconds,
                    )
                    self._recovery_started_at = now
                    with self.lock:
                        self.latest = None
                        self._stream_alive = False
                    self._stale_termination_requested = True
                    if proc.poll() is None:
                        proc.terminate()
            # Condition B: STALE FRAME TIMEOUT
            # Process previously delivered frames but no fresh frame arrived within interval
            else:
                if self._generation_frame_timestamp > 0 and (now - self._generation_frame_timestamp) > self.stale_frame_timeout_seconds:
                    self._stale_frame_timeout_count += 1
                    self.last_error_type = "STALE_FRAME_TIMEOUT"
                    self.last_error_message = f"Process gen={self.process_generation} stalled: no frame for >{self.stale_frame_timeout_seconds}s"
                    logger.warning(
                        "[DATT-STREAM] Stale frame detected (>%ss). Terminating unresponsive FFmpeg process.",
                        self.stale_frame_timeout_seconds,
                    )
                    self._recovery_started_at = now
                    with self.lock:
                        self.latest = None
                        self._stream_alive = False
                    self._stale_termination_requested = True
                    if proc.poll() is None:
                        proc.terminate()

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
            self._thread.join(timeout=3.0)
        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)
        if self._health_thread is not None and self._health_thread.is_alive():
            self._health_thread.join(timeout=1.0)
        with self.lock:
            self._stream_alive = False
            self.finished = True
            self.latest = None
