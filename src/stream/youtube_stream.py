"""YouTube Live and RTSP/HTTP Video Stream Ingestion via yt-dlp and FFmpeg.

Continuously captures raw BGR24 frames in a dedicated thread,
maintaining only the latest frame buffer with zero queue buildup.
"""

from dataclasses import dataclass
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


def get_stream_url(url: str) -> str:
    """Extract direct video stream URL using yt-dlp if it is a YouTube URL."""
    # If the URL is already a direct stream or file, return as is
    if not ("youtube.com" in url or "youtu.be" in url):
        return url

    ydl_opts: dict[str, Any] = {
        "format": "bestvideo[height<=720]/best[height<=720]/bestvideo/best",
        "quiet": True,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=False)
    except DownloadError as exc:
        raise RuntimeError(f"Khong lay duoc stream YouTube: {exc}") from exc

    if not info:
        raise RuntimeError("Khong lay duoc thong tin video tu YouTube")
    stream = info.get("url")
    if not isinstance(stream, str) or not stream:
        raise RuntimeError("Khong lay duoc URL video tu YouTube")
    return cast(str, stream)


class CameraReader:
    """Continuously reads FFmpeg output pipe and keeps only the newest frame.

    Implements zero-queue buffer to ensure inference latency does not cause lag.
    """

    def __init__(self, url: str, width: int = 1280, height: int = 720):
        self.url = url
        self.width = width
        self.height = height
        self.frame_size = width * height * 3

        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.latest: CapturedFrame | None = None
        self.last_read_sequence: int = -1

        self.stream_fps: float = 0.0
        self.last_capture_latency_ms: float = 0.0
        self.last_frame_age_ms: float = 0.0
        self.error: Exception | None = None
        self.finished: bool = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Resolve stream URL, spawn FFmpeg process, and start reader thread."""
        stream_url = get_stream_url(self.url)

        ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_command = [
            ffmpeg_path,
            "-nostdin",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-probesize", "32",
            "-analyzeduration", "0",
            "-loglevel", "error",
            "-i", stream_url,
            "-an",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-vf", f"scale={self.width}:{self.height}",
            "-",
        ]

        self.process = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE)
        self.stop_event.clear()
        self.finished = False
        self._thread = threading.Thread(
            target=self._read_loop, name="ffmpeg-capture", daemon=True
        )
        self._thread.start()

    def _read_loop(self) -> None:
        count = 0
        window_start = time.perf_counter()
        sequence = 0

        try:
            if self.process is None or self.process.stdout is None:
                raise RuntimeError("FFmpeg stdout is unavailable")

            while not self.stop_event.is_set():
                read_start = time.perf_counter()
                raw = read_frame_bytes(self.process.stdout, self.frame_size)
                read_end = time.perf_counter()

                if len(raw) != self.frame_size:
                    break

                frame = np.frombuffer(raw, np.uint8).reshape(
                    self.height, self.width, 3
                ).copy()
                sequence += 1
                count += 1
                now = time.perf_counter()

                with self.lock:
                    self.latest = CapturedFrame(
                        sequence=sequence,
                        captured_at=now,
                        capture_latency_ms=(read_end - read_start) * 1000,
                        frame=frame,
                    )

                elapsed = now - window_start
                if elapsed >= 1.0:
                    with self.lock:
                        self.stream_fps = count / elapsed
                    count = 0
                    window_start = now

        except Exception as exc:
            with self.lock:
                self.error = exc
        finally:
            with self.lock:
                self.finished = True

    def read(self, timeout: float = 1.0) -> np.ndarray | None:
        """Read the newest available frame.

        Blocks up to timeout seconds until a new frame arrives.
        Returns None if stream has terminated or timed out.
        """
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

                if self.finished:
                    return None

            time.sleep(0.001)

        return None

    def stop(self) -> None:
        """Safely terminate FFmpeg subprocess and reader thread."""
        self.stop_event.set()
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
            if self.process.stdout is not None:
                self.process.stdout.close()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
