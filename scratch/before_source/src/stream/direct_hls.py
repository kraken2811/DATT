"""Direct HLS Video Stream Reader for DATT - AI People Counter.

Ingests live HLS (.m3u8) video streams directly via FFmpeg without yt-dlp.
Continuously captures raw BGR24 frames in a dedicated background worker,
maintaining strict latest-frame semantics with zero queue buildup.

Pipeline:
    .m3u8 URL -> FFmpeg -> BGR frames -> latest-frame buffer -> DATT AI pipeline
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

import cv2
import imageio_ffmpeg
import numpy as np

logger = logging.getLogger("datt.direct_hls")


@dataclass(frozen=True)
class HLSFrame:
    """Container for a single captured HLS frame."""

    sequence: int
    captured_at: float
    capture_latency_ms: float
    frame: np.ndarray


def read_exact_bytes(stream, size: int) -> bytes:
    """Read exact number of bytes from a pipe stream."""
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def build_direct_hls_ffmpeg_cmd(
    ffmpeg_path: str,
    stream_url: str,
    width: int,
    height: int,
    headers: dict[str, str] | None = None,
) -> list[str]:
    """Construct FFmpeg command optimized for Direct HLS (.m3u8) streams.

    Supports optional generic HTTP headers (e.g. User-Agent, Referer) without
    hardcoding provider-specific logic.
    """
    cmd = [
        ffmpeg_path,
        "-nostdin",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-probesize", "5000000",
        "-analyzeduration", "3000000",
        "-rw_timeout", "15000000",  # 15s network timeout
    ]

    if stream_url.startswith("http://") or stream_url.startswith("https://"):
        if headers:
            header_lines = [f"{k}: {str(v).rstrip()}" + "\r\n" for k, v in headers.items()]
            header_str = "".join(header_lines)
            cmd.extend(["-headers", header_str])
        else:
            cmd.extend([
                "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DATT/4.5",
            ])
        cmd.extend([
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


class DirectHLSReader:
    """High-performance reader for direct HLS (.m3u8) video streams.

    Features:
    - Zero invocation of yt-dlp.
    - Zero-queue buffer to ensure inference latency does not cause lag.
    - Lifecycle monitoring and automatic reconnect on FFmpeg exit / EOF.
    - Zombie process prevention with proper pipe closure, wait(), and kill() fallback.
    - Rolling 30-frame sliding window FPS measurement.
    """

    def __init__(
        self,
        url: str = "",
        width: int = 1280,
        height: int = 720,
        headers: dict[str, str] | None = None,
        stream_url: str | None = None,
    ) -> None:
        self.url = str(stream_url or url).strip()
        self.width = width
        self.height = height
        self.frame_size = width * height * 3
        self.headers = headers

        self.source_type = "direct_hls"
        self.process_generation: int = 0
        self.ffmpeg_start_count: int = 0
        self.reconnect_count: int = 0
        self.clean_eof_count: int = 0
        self.abnormal_exit_count: int = 0
        self.dropped_frames: int = 0

        self._lock = threading.RLock()
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._process: subprocess.Popen | None = None

        self._latest: HLSFrame | None = None
        self._last_read_sequence: int = -1
        self._frames_received: int = 0
        self._last_frame_timestamp: float = 0.0
        self._started_at: float = 0.0
        self._stream_alive: bool = False
        self.finished: bool = False

        self._stream_fps: float = 0.0
        self._timestamps: deque[float] = deque(maxlen=150)
        self.stderr_lines: list[str] = []
        self._last_ffmpeg_pid: int | None = None
        self._last_ffmpeg_exit_code: int | None = None
        self._last_ffmpeg_stderr: str = ""
        self._last_error_message: str = ""

    @property
    def stream_fps(self) -> float:
        with self._lock:
            return self._stream_fps

    @property
    def fps(self) -> float:
        """Alias for stream_fps."""
        return self.stream_fps

    @property
    def capture_fps(self) -> float:
        return self.stream_fps

    @property
    def buffer_age_ms(self) -> float:
        with self._lock:
            if self._last_frame_timestamp <= 0.0:
                return 0.0
            return max(0.0, (time.time() - self._last_frame_timestamp) * 1000.0)

    @property
    def last_frame_time(self) -> float:
        with self._lock:
            return self._last_frame_timestamp

    @property
    def frame_age_seconds(self) -> float:
        with self._lock:
            if self._last_frame_timestamp <= 0.0:
                return 999.0
            return max(0.0, time.time() - self._last_frame_timestamp)

    @property
    def stream_alive(self) -> bool:
        with self._lock:
            age = self.frame_age_seconds
            return self._stream_alive and age <= 15.0

    @property
    def status(self) -> str:
        if self.stop_event.is_set():
            return "STOPPED"
        with self._lock:
            if self.finished and not self._stream_alive:
                return "ERROR"
            if self._frames_received == 0:
                if (time.time() - self._started_at) <= 15.0:
                    return "RUNNING"
                return "ERROR"
            age = self.frame_age_seconds
            if age <= 5.0 and self._stream_alive:
                return "RUNNING"
            elif age <= 15.0:
                return "WARNING"
            else:
                return "ERROR"

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "reader_type": "DirectHLSReader",
                "source_type": self.source_type,
                "reader_alive": self.stream_alive,
                "ffmpeg_alive": self._process.poll() is None if self._process else False,
                "ffmpeg_pid": self._last_ffmpeg_pid,
                "ffmpeg_exit_code": self._last_ffmpeg_exit_code,
                "process_generation": self.process_generation,
                "frames_received": self._frames_received,
                "frame_age_seconds": round(self.frame_age_seconds, 2),
                "stream_fps": round(self.stream_fps, 1),
                "status": self.status,
                "last_error": self._last_error_message,
                "stream_url": self.url,
            }

    def start(self) -> None:
        """Start background FFmpeg reader thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self.stop_event.clear()
            self.finished = False
            self._last_frame_timestamp = 0.0
            self._started_at = time.time()
            self._stream_alive = False
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="DirectHLSReaderThread",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Cleanly terminate FFmpeg process and join worker thread."""
        self.stop_event.set()
        self._cleanup_process()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
        with self._lock:
            self._stream_alive = False
            self.finished = True

    def read(self, timeout: float = 2.0) -> np.ndarray | None:
        """Return the newest decoded BGR24 frame."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.stop_event.is_set():
                return None
            with self._lock:
                if self._latest is not None and self._latest.sequence != self._last_read_sequence:
                    self._last_read_sequence = self._latest.sequence
                    return self._latest.frame
            time.sleep(0.005)
        return None

    def _spawn_ffmpeg(self) -> None:
        """Spawn FFmpeg process targeting direct HLS URL."""
        if self.stop_event.is_set():
            return

        self.process_generation += 1
        self.ffmpeg_start_count += 1
        self.stderr_lines = []

        ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        cmd = build_direct_hls_ffmpeg_cmd(
            ffmpeg_path=ffmpeg_path,
            stream_url=self.url,
            width=self.width,
            height=self.height,
            headers=self.headers,
        )

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        with self._lock:
            self._process = proc
            self._last_ffmpeg_pid = proc.pid
            self._last_ffmpeg_exit_code = None

        logger.info("[DirectHLS] Spawned FFmpeg pid=%s for URL: %s", proc.pid, self.url)

        if proc.stderr is not None:
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr,
                args=(proc.stderr,),
                name="DirectHLS-Stderr",
                daemon=True,
            )
            self._stderr_thread.start()

    def _drain_stderr(self, pipe) -> None:
        """Drain stderr to avoid buffer saturation deadlocks."""
        try:
            for line in iter(pipe.readline, b""):
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self.stderr_lines.append(text)
                    if len(self.stderr_lines) > 50:
                        self.stderr_lines.pop(0)
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _cleanup_process(self) -> None:
        """Safe cancel-safe order: terminate -> wait -> kill -> close pipes."""
        with self._lock:
            proc = self._process
            self._process = None

        if proc is not None:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=1.5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass

            self._last_ffmpeg_exit_code = proc.poll()
            self._last_ffmpeg_stderr = "\n".join(str(s) for s in self.stderr_lines)[-1000:]
            self.stderr_lines.clear()

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

    def _worker_loop(self) -> None:
        """Read stdout pipe frames continuously and auto-reconnect if dropped."""
        sequence = 0
        consecutive_errors = 0

        while not self.stop_event.is_set():
            if self._process is None or self._process.stdout is None:
                try:
                    self._spawn_ffmpeg()
                except Exception as exc:
                    self._last_error_message = f"Spawn error: {exc}"
                    logger.error("[DirectHLS] Failed to spawn FFmpeg: %s", exc)
                    if self.stop_event.wait(3.0):
                        break
                    continue

            proc = self._process
            if proc is None or proc.stdout is None:
                time.sleep(0.1)
                continue

            try:
                raw_bytes = read_exact_bytes(proc.stdout, self.frame_size)
                if len(raw_bytes) != self.frame_size:
                    # EOF or pipe broken
                    logger.warning("[DirectHLS] Reached EOF or incomplete frame from FFmpeg pipe")
                    self._cleanup_process()
                    consecutive_errors += 1
                    self.reconnect_count += 1
                    wait_delay = min(2.0 * consecutive_errors, 10.0)
                    if self.stop_event.wait(wait_delay):
                        break
                    continue

                consecutive_errors = 0
                now = time.time()
                frame_arr = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((self.height, self.width, 3))

                with self._lock:
                    sequence += 1
                    self._frames_received += 1
                    self._last_frame_timestamp = now
                    self._stream_alive = True
                    self._latest = HLSFrame(
                        sequence=sequence,
                        captured_at=now,
                        capture_latency_ms=0.0,
                        frame=frame_arr,
                    )
                    self._timestamps.append(now)
                    cutoff = now - 3.0
                    while len(self._timestamps) > 2 and self._timestamps[0] < cutoff:
                        self._timestamps.popleft()
                    if len(self._timestamps) >= 2:
                        dt = self._timestamps[-1] - self._timestamps[0]
                        if dt >= 1.0:
                            self._stream_fps = (len(self._timestamps) - 1) / dt

            except Exception as exc:
                self._last_error_message = str(exc)
                logger.warning("[DirectHLS] Read error on pipe: %s", exc)
                self._cleanup_process()
                if self.stop_event.wait(2.0):
                    break

        self._cleanup_process()
        with self._lock:
            self._stream_alive = False
            self.finished = True
