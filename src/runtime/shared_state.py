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
    camera_status: str = "STOPPED"
    stream_alive: bool = False
    last_frame_time: float = 0.0
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
    camera_id: str = "camera_01"
    camera_name: str = ""
    last_event: str = "None"
    event_count_today: int = 0
    filtered_event_count: int = 0
    last_event_time: str = "None"
    last_saved_people_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to standard Python dict."""
        d = asdict(self)
        if not d.get("error_message"):
            d["error_message"] = None
        return d


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

        # Camera & Events
        self._camera_id: str = "camera_01"
        self._camera_name: str = ""
        self._last_event: str = "None"
        self._event_count_today: int = 0
        self._filtered_event_count: int = 0
        self._last_event_time: str = "None"
        self._last_saved_people_count: int = 0

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
        camera_id: str | None = None,
        camera_name: str | None = None,
        last_event: str | None = None,
        event_count_today: int | None = None,
        last_saved_people_count: int | None = None,
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

            if camera_id is not None:
                self._camera_id = camera_id
            if camera_name is not None:
                self._camera_name = camera_name
            if last_event is not None:
                self._last_event = last_event
            if event_count_today is not None:
                self._event_count_today = event_count_today
            if last_saved_people_count is not None:
                self._last_saved_people_count = last_saved_people_count

            self._status = "RUNNING"
            self._error_message = ""

    def set_camera(self, camera_id: str, camera_name: str) -> None:
        """Update the active camera identifiers."""
        with self._lock:
            self._camera_id = camera_id
            self._camera_name = camera_name

    def record_event(self, event_desc: str, count_today: int | None = None) -> None:
        """Record an event description and update today's event count."""
        with self._lock:
            self._last_event = event_desc
            if count_today is not None:
                self._event_count_today = count_today
            else:
                self._event_count_today += 1

    def record_filtered_event(self) -> None:
        with self._lock:
            self._filtered_event_count += 1

    def record_saved_event(self, event_desc: str, timestamp: str, people_count: int, count_today: int) -> None:
        with self._lock:
            self._last_event = event_desc
            self._last_event_time = timestamp
            self._last_saved_people_count = people_count
            self._event_count_today = count_today

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
        """Fetch an immutable point-in-time telemetry snapshot with dynamic camera status."""
        with self._lock:
            now = time.time()
            last_frame_time = self._timestamp

            # Dynamic status evaluation
            if self._status == "STOPPED":
                camera_status = "STOPPED"
                stream_alive = False
                err = self._error_message
            elif self._status == "ERROR":
                camera_status = "ERROR"
                stream_alive = False
                err = self._error_message or "Camera stream stopped or reader crashed"
            elif self._frame_id > 0:
                frame_age = now - last_frame_time
                if frame_age > 15.0:
                    camera_status = "ERROR"
                    stream_alive = False
                    err = self._error_message or "Stream timeout: no frame received for >15s"
                elif frame_age > 5.0:
                    camera_status = "WARNING"
                    stream_alive = True
                    err = self._error_message or "Stream delay: no new frame for >5s"
                else:
                    camera_status = "RUNNING"
                    stream_alive = True
                    err = ""
            else:
                camera_status = self._status
                stream_alive = (camera_status == "RUNNING")
                err = self._error_message

            return TelemetrySnapshot(
                frame_id=self._frame_id,
                timestamp=self._timestamp,
                status=camera_status,
                camera_status=camera_status,
                stream_alive=stream_alive,
                last_frame_time=last_frame_time,
                error_message=err,
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
                camera_id=self._camera_id,
                camera_name=self._camera_name,
                last_event=self._last_event,
                event_count_today=self._event_count_today,
                filtered_event_count=self._filtered_event_count,
                last_event_time=self._last_event_time,
                last_saved_people_count=self._last_saved_people_count,
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
