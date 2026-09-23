"""YouTube Live, HLS, and RTSP/HTTP Video Stream Ingestion via yt-dlp and FFmpeg.

Continuously captures raw BGR24 frames in a dedicated thread,
maintaining only the latest frame buffer with zero queue buildup.
"""

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
        self._stderr_thread: threading.Thread | None = None
        self.stderr_lines: list[str] = []

    def start(self) -> None:
        """Resolve stream URL, spawn FFmpeg process with retries, and start reader thread."""
        ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
        max_retries = 3
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                # 1. Resolve direct stream URL
                stream_url = get_stream_url(self.url)

                # 2. Build FFmpeg command with low latency and proper probing
                ffmpeg_command = build_ffmpeg_command(
                    ffmpeg_path=ffmpeg_path,
                    stream_url=stream_url,
                    width=self.width,
                    height=self.height,
                )

                # 3. Spawn FFmpeg process
                self.stderr_lines = []
                self.process = subprocess.Popen(
                    ffmpeg_command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

                # 4. Drain stderr continuously in a daemon thread to prevent pipe blocking
                if self.process.stderr is not None:
                    self._stderr_thread = threading.Thread(
                        target=self._drain_stderr,
                        args=(self.process.stderr,),
                        name="ffmpeg-stderr",
                        daemon=True,
                    )
                    self._stderr_thread.start()

                # 5. Verify process did not immediately exit with error
                time.sleep(0.5)
                if self.process.poll() is not None:
                    err_msg = " ".join(self.stderr_lines[-5:]) if self.stderr_lines else "Process exited early"
                    raise RuntimeError(f"FFmpeg failed to open YouTube video stream: {err_msg}")

                # Success: launch frame reader thread
                self.stop_event.clear()
                self.finished = False
                self._thread = threading.Thread(
                    target=self._read_loop, name="ffmpeg-capture", daemon=True
                )
                self._thread.start()
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
        except Exception:
            pass
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _cleanup_process(self) -> None:
        """Terminate and clean up FFmpeg process."""
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            if self.process.stdout is not None:
                try:
                    self.process.stdout.close()
                except Exception:
                    pass
            self.process = None

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
                    err_summary = " ".join(self.stderr_lines[-5:]) if self.stderr_lines else ""
                    if err_summary:
                        logger.error("FFmpeg error stream: %s", err_summary)
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
        self._cleanup_process()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
