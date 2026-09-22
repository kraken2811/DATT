"""Thread-safe Shared Runtime State for DATT - AI People Counter.

Phase 4: Level 2 Realtime Monitoring UI.
Provides decoupled, non-blocking latest-frame semantics between the AI pipeline
and observation layers (MJPEG stream & Streamlit dashboard).
"""

from dataclasses import asdict, dataclass
import threading
import time
from typing import Any

import numpy as np


@dataclass
class TelemetrySnapshot:
    """Immutable point-in-time snapshot of telemetry metrics."""

    frame_id: int = 0
    timestamp: float = 0.0
    status: str = "STOPPED"
    error_message: str = ""
    people_count: int = 0
    detection_count: int = 0
    track_count: int = 0
    stream_fps: float = 0.0
    processing_fps: float = 0.0
    yolo_latency_ms: float = 0.0
    pipeline_latency_ms: float = 0.0
    device: str = "CPU"
    gpu_name: str = "CPU"
    vram_mb: float = 0.0
    model_name: str = "YOLO11s"
    input_size: str = "640x640"

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to standard Python dict."""
        return asdict(self)


class SharedRuntimeState:
    """Thread-safe singleton holding the newest frame and telemetry metrics.

    Uses strict latest-frame semantics: old frames are instantly overwritten.
    No unbounded queue exists, guaranteeing zero latency buildup for consumers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Frames
        self._latest_frame: np.ndarray | None = None
        self._annotated_frame: np.ndarray | None = None
        self._frame_id: int = 0
        self._timestamp: float = time.time()

        # Status
        self._status: str = "STOPPED"  # "STOPPED", "RUNNING", "ERROR"
        self._error_message: str = ""

        # Telemetry
        self._people_count: int = 0
        self._detection_count: int = 0
        self._track_count: int = 0
        self._stream_fps: float = 0.0
        self._processing_fps: float = 0.0
        self._yolo_latency_ms: float = 0.0
        self._pipeline_latency_ms: float = 0.0

        # Hardware & Model
        self._device: str = "CPU"
        self._gpu_name: str = "CPU"
        self._vram_mb: float = 0.0
        self._model_name: str = "YOLO11s"
        self._input_size: str = "640x640"

    def update(
        self,
        latest_frame: np.ndarray | None = None,
        annotated_frame: np.ndarray | None = None,
        people_count: int = 0,
        detection_count: int = 0,
        track_count: int = 0,
        stream_fps: float = 0.0,
        processing_fps: float = 0.0,
        yolo_latency_ms: float = 0.0,
        pipeline_latency_ms: float = 0.0,
        device: str = "CPU",
        gpu_name: str = "CPU",
        vram_mb: float = 0.0,
        model_name: str = "YOLO11s",
        input_size: str = "640x640",
    ) -> None:
        """Atomically update state with the newest frame and metrics.

        Overwrites any previous frame to enforce zero-queue latest-frame semantics.
        """
        with self._lock:
            self._frame_id += 1
            self._timestamp = time.time()
            if latest_frame is not None:
                self._latest_frame = latest_frame
            if annotated_frame is not None:
                self._annotated_frame = annotated_frame

            self._people_count = people_count
            self._detection_count = detection_count
            self._track_count = track_count
            self._stream_fps = stream_fps
            self._processing_fps = processing_fps
            self._yolo_latency_ms = yolo_latency_ms
            self._pipeline_latency_ms = pipeline_latency_ms
            self._device = device
            self._gpu_name = gpu_name
            self._vram_mb = vram_mb
            self._model_name = model_name
            self._input_size = input_size

            if self._status != "ERROR":
                self._status = "RUNNING"

    def set_status(self, status: str, error_message: str = "") -> None:
        """Update the operational status of the pipeline."""
        with self._lock:
            self._status = status
            self._error_message = error_message

    def get_annotated_frame(self) -> tuple[int, np.ndarray | None]:
        """Fetch the newest annotated frame and its frame ID.

        Returns:
            tuple[int, np.ndarray | None]: (frame_id, annotated_frame)
        """
        with self._lock:
            return self._frame_id, self._annotated_frame

    def get_raw_frame(self) -> tuple[int, np.ndarray | None]:
        """Fetch the newest raw frame and its frame ID."""
        with self._lock:
            return self._frame_id, self._latest_frame

    def get_telemetry(self) -> TelemetrySnapshot:
        """Fetch an immutable point-in-time telemetry snapshot."""
        with self._lock:
            return TelemetrySnapshot(
                frame_id=self._frame_id,
                timestamp=self._timestamp,
                status=self._status,
                error_message=self._error_message,
                people_count=self._people_count,
                detection_count=self._detection_count,
                track_count=self._track_count,
                stream_fps=self._stream_fps,
                processing_fps=self._processing_fps,
                yolo_latency_ms=self._yolo_latency_ms,
                pipeline_latency_ms=self._pipeline_latency_ms,
                device=self._device,
                gpu_name=self._gpu_name,
                vram_mb=self._vram_mb,
                model_name=self._model_name,
                input_size=self._input_size,
            )

    def reset(self) -> None:
        """Reset state when pipeline stops."""
        with self._lock:
            self._latest_frame = None
            self._annotated_frame = None
            self._frame_id = 0
            self._status = "STOPPED"
            self._error_message = ""
            self._people_count = 0
            self._detection_count = 0
            self._track_count = 0


# Global shared singleton instance
shared_state = SharedRuntimeState()
