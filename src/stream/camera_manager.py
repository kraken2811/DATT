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

from src.config.camera_config import CameraInfo, get_camera, get_default_camera
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
            return self._reader.diagnostics() if self._reader else {
                "ffmpeg_alive": False, "reader_alive": False, "last_frame_age": 999.0,
                "frames_received": 0, "ffmpeg_exit_code": None, "last_error": self._error_reason,
            }

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
            # Stop existing reader if one is already running
            self._stop_reader_internal()

            if camera_id is None:
                cam_info = get_default_camera(self.config_path)
            else:
                cam_info = get_camera(camera_id, self.config_path)

            self._status = "SWITCHING"
            self._error_reason = ""
            logger.info("CameraManager: Starting camera '%s' (%s)...", cam_info.name, cam_info.url)

            try:
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
            self._status = "STOPPED"
            self._error_reason = ""

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
            if frame is not None:
                with self._lock:
                    previous = self._status
                    if self._status != "RUNNING":
                        self._status = "RUNNING"
                        self._error_reason = ""
                        logger.info("[DATT-STREAM STATE CHANGE] old_status=%s new_status=RUNNING reason=frame_received last_frame_age=%.1f ffmpeg_alive=%s reader_alive=%s",
                                    previous, reader.frame_age_seconds, reader.diagnostics()["ffmpeg_alive"], reader.diagnostics()["reader_alive"])
                return frame

            with self._lock:
                previous = self._status
                reader_status = reader.status
                if reader_status in ("ERROR", "WARNING"):
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
                                   reader.diagnostics()["ffmpeg_alive"], reader.diagnostics()["reader_alive"])
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
