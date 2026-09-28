"""Camera Manager for DATT - AI People Counter.

Phase 4 Version 3: Camera Management & Event Logging.
Manages the lifecycle of the single active camera source, supporting dynamic
switching between YouTube live streams and RTSP/file streams at runtime.
"""

from pathlib import Path
import threading
import time
from typing import Any

import numpy as np

import config
from src.config.camera_config import CameraInfo, get_camera, get_default_camera
from src.stream.direct_hls import DirectHLSReader
from src.stream.preview_manager import preview_manager
from src.stream.video_source import LocalVideoReader, YouTubeVODReader
from src.stream.youtube_resolver import (
    ERROR_BOT_CHALLENGE,
    classify_youtube_error,
    is_youtube_url,
    stream_resolver,
)
from src.stream.youtube_stream import CameraReader
from src.utils.logger import logger



class CameraManager:
    """Thread-safe manager for the active video camera stream.

    Ensures only one camera runs concurrently, providing safe shutdown,
    reconnection, and runtime camera switching.
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = config_path
        self._lock = threading.RLock()

        self._active_camera: CameraInfo | None = None
        self._reader: CameraReader | None = None

        self._status: str = "STOPPED"  # "STOPPED", "RUNNING", "SWITCHING", "ERROR"
        self._error_reason: str = ""
        self._last_camera_started_at: float = 0.0

    @property
    def status(self) -> str:
        """Current operational status of the camera."""
        with self._lock:
            if self._reader is not None and self._status == "RUNNING":
                reader_status = self._reader.status
                if reader_status != "RUNNING":
                    return reader_status
            return self._status

    @property
    def error_reason(self) -> str:
        """Failure description if camera status is ERROR."""
        with self._lock:
            return self._error_reason

    @property
    def stream_fps(self) -> float:
        """Ingestion FPS from the active camera reader."""
        with self._lock:
            return self._reader.stream_fps if self._reader else 0.0

    @property
    def capture_fps(self) -> float:
        return self.stream_fps

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._reader.dropped_frames if self._reader else 0

    @property
    def buffer_age_ms(self) -> float:
        with self._lock:
            return self._reader.buffer_age_ms if self._reader else 0.0

    @property
    def decoded_frames_total(self) -> int:
        with self._lock:
            return getattr(self._reader, "decoded_frames_total", 0) if self._reader else 0

    @property
    def decoded_fps(self) -> float:
        with self._lock:
            return getattr(self._reader, "decoded_fps", 0.0) if self._reader else 0.0

    @property
    def paced_frames_total(self) -> int:
        with self._lock:
            return getattr(self._reader, "paced_frames_total", 0) if self._reader else 0

    @property
    def paced_fps(self) -> float:
        with self._lock:
            return getattr(self._reader, "paced_fps", 0.0) if self._reader else 0.0

    @property
    def frames_dropped_by_pacer(self) -> int:
        with self._lock:
            return getattr(self._reader, "frames_dropped_by_pacer", 0) if self._reader else 0

    @property
    def jitter_buffer_frames(self) -> int:
        with self._lock:
            return getattr(self._reader, "jitter_buffer_frames", 0) if self._reader else 0

    @property
    def jitter_buffer_ms(self) -> float:
        with self._lock:
            return getattr(self._reader, "jitter_buffer_ms", 0.0) if self._reader else 0.0

    @property
    def last_decoded_frame_age(self) -> float:
        with self._lock:
            return getattr(self._reader, "last_decoded_frame_age", 999.0) if self._reader else 999.0

    @property
    def last_paced_frame_age(self) -> float:
        with self._lock:
            return getattr(self._reader, "last_paced_frame_age", 999.0) if self._reader else 999.0

    @property
    def stream_alive(self) -> bool:
        """Whether the active stream is alive and publishing frames."""
        with self._lock:
            return self._reader.stream_alive if self._reader else False

    @property
    def last_frame_time(self) -> float:
        """Timestamp of newest frame from active camera reader."""
        with self._lock:
            return self._reader.last_frame_time if self._reader else 0.0

    @property
    def frame_age_seconds(self) -> float:
        """Seconds since newest frame was captured."""
        with self._lock:
            return self._reader.frame_age_seconds if self._reader else 999.0

    @property
    def finished(self) -> bool:
        """Whether the active stream has reached EOF or stopped."""
        with self._lock:
            return self._reader.finished if self._reader else True

    def stream_diagnostics(self) -> dict[str, Any]:
        with self._lock:
            base = self._reader.diagnostics() if self._reader else {
                "ffmpeg_alive": False, "reader_alive": False, "last_frame_age": 999.0,
                "frames_received": 0, "ffmpeg_exit_code": None, "last_error": self._error_reason,
            }
            base["resolver_metrics"] = stream_resolver.get_metrics_dict()
            return base

    def get_active_camera(self) -> CameraInfo | None:
        """Return the currently active CameraInfo metadata."""
        with self._lock:
            return self._active_camera

    def start_camera(self, camera_id: str | None = None) -> CameraInfo:
        """Initialize and start the camera stream for the given camera ID.

        Args:
            camera_id: Camera key in cameras.yaml. If None, uses default camera.

        Returns:
            CameraInfo: Metadata of the activated camera.

        Raises:
            RuntimeError: If stream initialization fails.
        """
        with self._lock:
            # Apply startup stagger delay if another camera started recently
            stagger = getattr(config, "CAMERA_STARTUP_STAGGER", 2.0)
            elapsed = time.time() - self._last_camera_started_at
            if self._last_camera_started_at > 0 and elapsed < stagger:
                wait_stagger = stagger - elapsed
                logger.info("CameraManager: Staggering camera start by %.2fs...", wait_stagger)
                time.sleep(wait_stagger)
            self._last_camera_started_at = time.time()

            # Stop existing reader if one is already running
            self._stop_reader_internal()

            if camera_id is None:
                cam_info = get_default_camera(self.config_path)
            else:
                cam_info = get_camera(camera_id, self.config_path)

            # Ensure preview resources are closed before AI pipeline starts
            preview_manager.stop_preview()

            self._status = "SWITCHING"
            self._error_reason = ""
            logger.info("CameraManager: Starting camera '%s' (%s)...", cam_info.name, cam_info.url)

            try:
                if cam_info.type == "direct_hls":
                    reader = DirectHLSReader(
                        url=cam_info.url,
                        width=cam_info.width,
                        height=cam_info.height,
                    )
                elif cam_info.type in ("youtube_vod", "vod"):
                    reader = YouTubeVODReader(
                        youtube_url=cam_info.url,
                        loop=False,
                        width=cam_info.width,
                        height=cam_info.height,
                    )
                elif is_youtube_url(cam_info.url):
                    is_live = stream_resolver.is_live_stream(cam_info.url)
                    if is_live:
                        reader = CameraReader(
                            url=cam_info.url,
                            width=cam_info.width,
                            height=cam_info.height,
                            is_vod=False,
                        )
                    else:
                        reader = YouTubeVODReader(
                            youtube_url=cam_info.url,
                            loop=False,
                            width=cam_info.width,
                            height=cam_info.height,
                        )
                else:
                    reader = CameraReader(
                        url=cam_info.url,
                        width=cam_info.width,
                        height=cam_info.height,
                    )
                reader.start()

                self._reader = reader
                self._active_camera = cam_info
                self._status = "RUNNING"
                logger.info("CameraManager: Camera '%s' is now active and running.", cam_info.name)
                return cam_info

            except Exception as exc:
                self._status = "ERROR"
                self._error_reason = f"Failed to start camera {cam_info.name}: {exc}"
                logger.error("CameraManager Error: %s", self._error_reason, exc_info=True)
                raise RuntimeError(self._error_reason) from exc


    def stop_camera(self) -> None:
        """Stop the currently running camera stream cleanly."""
        with self._lock:
            logger.info("CameraManager: Stopping active camera stream...")
            self._stop_reader_internal()
            self._active_camera = None
            self._status = "STOPPED"
            self._error_reason = ""

    def has_active_camera(self) -> bool:
        """Check if an active camera source is configured and running."""
        with self._lock:
            return self._reader is not None and self._active_camera is not None

    def is_connection_ready(self, max_frame_age: float = 5.0) -> bool:
        """Check if active source satisfies connection criteria:
        - frames_received > 0
        - frame_age_seconds <= max_frame_age
        - stream_alive is True
        """
        with self._lock:
            if self._reader is None or self._status != "RUNNING":
                return False
            frames = getattr(self._reader, "_frames_received", 0)
            age = self.frame_age_seconds
            alive = self.stream_alive
            return frames > 0 and age <= max_frame_age and alive

    def switch_camera(self, camera_id: str) -> CameraInfo:
        """Switch active camera to a new source dynamically.

        Args:
            camera_id: ID of the new camera in cameras.yaml.

        Returns:
            CameraInfo: Metadata of the newly active camera.
        """
        with self._lock:
            current_id = self._active_camera.id if self._active_camera else None
            if current_id == camera_id and self._status == "RUNNING":
                logger.info("CameraManager: Camera '%s' already active, skipping switch.", camera_id)
                assert self._active_camera is not None
                return self._active_camera

            logger.info(
                "CameraManager: Switching camera from '%s' to '%s'...",
                current_id or "None",
                camera_id,
            )
            return self.start_camera(camera_id)

    def set_video_source(
        self,
        source_type: str,
        source: str,
        loop: bool = True,
        name: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> CameraInfo:
        """Switch active stream dynamically to a Local MP4, Direct HLS, or YouTube source.

        Args:
            source_type: 'direct_hls', 'local', 'youtube_vod', or 'youtube'
            source: Local file path or Stream URL
            loop: Whether to loop local video upon EOF
            name: Optional display name for source
            headers: Optional generic HTTP headers for HLS ingestion

        Returns:
            CameraInfo: Metadata representing the active source
        """
        with self._lock:
            stype = str(source_type).lower().strip()
            src_str = str(source).strip()

            if not src_str:
                raise ValueError("Source path or URL cannot be empty")

            # Apply startup stagger delay if another camera/source started recently
            stagger = getattr(config, "CAMERA_STARTUP_STAGGER", 2.0)
            elapsed = time.time() - self._last_camera_started_at
            if self._last_camera_started_at > 0 and elapsed < stagger:
                wait_stagger = stagger - elapsed
                logger.info("CameraManager: Staggering video source start by %.2fs...", wait_stagger)
                time.sleep(wait_stagger)
            self._last_camera_started_at = time.time()

            logger.info(
                "CameraManager: Setting video source [type=%s, source=%s, loop=%s]...",
                stype, src_str, loop,
            )


            # Safely stop and release previous reader and preview
            preview_manager.stop_preview()
            self._stop_reader_internal()
            self._status = "SWITCHING"
            self._error_reason = ""

            try:
                if stype in ("direct_hls", "hls"):
                    reader = DirectHLSReader(url=src_str, width=1280, height=720, headers=headers)
                    reader.start()

                    cam_name = name or "Direct HLS Stream"
                    cam_info = CameraInfo(
                        id=f"hls_{time.time()}",
                        name=cam_name,
                        type="direct_hls",
                        url=src_str,
                        width=1280,
                        height=720,
                        description="Direct HLS (.m3u8) video stream",
                    )

                elif stype in ("local", "file", "mp4"):
                    file_path = Path(src_str)
                    if not file_path.is_file():
                        raise FileNotFoundError(f"Local video file not found: {file_path}")

                    reader = LocalVideoReader(file_path=file_path, loop=loop)
                    reader.start()

                    cam_name = name or f"Local Video: {file_path.name}"
                    cam_info = CameraInfo(
                        id=f"local_{time.time()}",
                        name=cam_name,
                        type="file",
                        url=str(file_path),
                        width=reader.width or 1280,
                        height=reader.height or 720,
                        description=f"Local MP4 file (loop={loop})",
                    )

                elif stype in ("youtube_vod", "vod"):
                    reader = YouTubeVODReader(youtube_url=src_str, loop=loop)
                    reader.start()

                    cam_name = name or "YouTube VOD"
                    cam_info = CameraInfo(
                        id=f"vod_{time.time()}",
                        name=cam_name,
                        type="youtube_vod",
                        url=src_str,
                        width=reader.width or 1280,
                        height=reader.height or 720,
                        description=f"YouTube VOD stream (loop={loop})",
                    )

                elif stype in ("youtube", "live"):
                    # Distinguish YouTube Live vs VOD before creating reader
                    is_live = stream_resolver.is_live_stream(src_str)
                    if is_live:
                        reader = CameraReader(url=src_str, is_vod=False)
                        reader.start()

                        cam_name = name or "YouTube Stream"
                        cam_info = CameraInfo(
                            id=f"youtube_{time.time()}",
                            name=cam_name,
                            type="youtube",
                            url=src_str,
                            width=1280,
                            height=720,
                            description="YouTube Live/HLS stream",
                        )
                    else:
                        reader = YouTubeVODReader(youtube_url=src_str, loop=loop)
                        reader.start()

                        cam_name = name or "YouTube VOD"
                        cam_info = CameraInfo(
                            id=f"vod_{time.time()}",
                            name=cam_name,
                            type="youtube_vod",
                            url=src_str,
                            width=reader.width or 1280,
                            height=reader.height or 720,
                            description=f"YouTube VOD stream (loop={loop})",
                        )
                else:
                    raise ValueError(
                        f"Unsupported source type: '{source_type}'. "
                        "Supported types: 'direct_hls', 'local', 'youtube_vod', 'youtube'"
                    )

                self._reader = reader
                self._active_camera = cam_info
                self._status = "RUNNING"

                # Reset target matcher tracks on source switch
                try:
                    from src.recognition.target_matcher import target_matcher
                    target_matcher.reset_tracks()
                except Exception as exc:
                    logger.debug("CameraManager: Could not reset target matcher: %s", exc)

                logger.info(
                    "CameraManager: Video source '%s' is now active [type=%s].",
                    cam_info.name, stype,
                )
                return cam_info

            except Exception as exc:
                self._status = "ERROR"
                err_str = str(exc)
                if "AUTH/ANTI_BOT" in err_str or classify_youtube_error(err_str) == ERROR_BOT_CHALLENGE:
                    self._error_reason = f"AUTH/ANTI_BOT: {exc}"
                else:
                    self._error_reason = f"Failed to set video source: {exc}"
                logger.error("CameraManager Error: %s", self._error_reason, exc_info=True)
                raise RuntimeError(self._error_reason) from exc

    def get_current_source_info(self) -> dict[str, Any]:
        """Return runtime details of the current video source."""
        with self._lock:
            cam = self._active_camera
            return {
                "id": cam.id if cam else None,
                "name": cam.name if cam else None,
                "type": cam.type if cam else None,
                "url": cam.url if cam else None,
                "status": self.status,
                "stream_fps": self.stream_fps,
                "stream_alive": self.stream_alive,
                "finished": self.finished,
                "diagnostics": self.stream_diagnostics(),
                "resolver_metrics": stream_resolver.get_metrics_dict(),
            }


    def read(self, timeout: float = 2.0) -> np.ndarray | None:
        """Read the latest frame from the active camera reader.

        Args:
            timeout: Max seconds to wait for frame.

        Returns:
            np.ndarray | None: Latest BGR frame, or None if unavailable.
        """
        with self._lock:
            if self._reader is None or self._status == "STOPPED":
                return None
            reader = self._reader

        # Release lock during read() to allow switch_camera to execute concurrently
        try:
            frame = reader.read(timeout=timeout)
            diag = reader.diagnostics() if hasattr(reader, "diagnostics") else {}
            ffmpeg_alive = diag.get("ffmpeg_alive")
            reader_alive = diag.get("reader_alive", reader.stream_alive)

            if frame is not None:
                with self._lock:
                    previous = self._status
                    if self._status != "RUNNING":
                        self._status = "RUNNING"
                        self._error_reason = ""
                        logger.info("[DATT-STREAM STATE CHANGE] old_status=%s new_status=RUNNING reason=frame_received last_frame_age=%.1f ffmpeg_alive=%s reader_alive=%s",
                                    previous, reader.frame_age_seconds, ffmpeg_alive, reader_alive)
                return frame

            with self._lock:
                previous = self._status
                reader_status = reader.status
                if reader_status == "VIDEO_FINISHED" or (reader.finished and getattr(reader, "clean_eof_count", 0) > 0 and not getattr(reader, "loop", False)):
                    self._status = "VIDEO_FINISHED"
                    self._error_reason = ""
                elif reader_status in ("ERROR", "WARNING"):
                    self._status = reader_status
                    if reader_status == "WARNING":
                        self._error_reason = "Stream delay detected: no new frame for >5s"
                    elif reader.finished:
                        self._status = "ERROR"
                        self._error_reason = "Stream ended or camera disconnected unexpectedly."
                    else:
                        self._status = "ERROR"
                        self._error_reason = "Stream timeout: no frame received for >15s"
                if self._status != previous:
                    logger.warning("[DATT-STREAM STATE CHANGE] old_status=%s new_status=%s reason=%s last_frame_age=%.1f ffmpeg_alive=%s reader_alive=%s",
                                   previous, self._status, self._error_reason, reader.frame_age_seconds,
                                   ffmpeg_alive, reader_alive)
            return None
        except Exception as exc:
            with self._lock:
                previous = self._status
                self._status = "ERROR"
                self._error_reason = f"Read error on stream: {exc}"
                logger.error("[DATT-THREAD ERROR] thread_name=camera-manager exception_type=%s exception_message=%s",
                             type(exc).__name__, exc, exc_info=True)
            return None

    def _stop_reader_internal(self) -> None:
        """Internal helper to stop reader without mutating external status."""
        if self._reader is not None:
            try:
                self._reader.stop()
            except Exception as exc:
                logger.warning("Error stopping camera reader: %s", exc)
            finally:
                self._reader = None

    def stop_camera(self) -> None:
        """Public method to stop active camera reader and transition to STOPPED / IDLE."""
        with self._lock:
            self._stop_reader_internal()
            self._active_camera = None
            self._status = "STOPPED"
            self._error_reason = ""
            logger.info("CameraManager: Stopped active camera.")

    def stop(self) -> None:
        """Alias for stop_camera."""
        self.stop_camera()

    def get_active_reader(self) -> Any:
        """Return the current active reader instance or None."""
        with self._lock:
            return self._reader

    @property
    def active_camera_id(self) -> str:
        """Return ID of currently active camera, or empty string."""
        with self._lock:
            return self._active_camera.id if self._active_camera else ""

