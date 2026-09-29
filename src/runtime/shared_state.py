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
    car_count: int = 0
    detection_count: int = 0
    track_count: int = 0
    is_fallback: bool = False
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
    stream_health: dict[str, Any] | None = None
    capture_fps: float = 0.0
    inference_fps: float = 0.0
    display_fps: float = 0.0
    dropped_frames: int = 0
    buffer_age_ms: float = 0.0

    # Counting Zone & Mode (Full View vs Selected Zone)
    zone_enabled: bool = False
    zone_mode: str = "full_view"
    car_count_label: str = "VEHICLES IN VIEW"
    vehicles_in_view: int = 0
    vehicles_in_zone: int = 0

    # Stream Pacing & Black-Screen Diagnostics (Phase B & C)
    source_generation: int = 1
    mjpeg_clients: int = 0
    mjpeg_connection_generation: int = 0
    last_jpeg_success: bool = True
    last_jpeg_error: str = ""
    decoded_frames_total: int = 0
    decoded_fps: float = 0.0
    paced_frames_total: int = 0
    paced_fps: float = 0.0
    published_frames_total: int = 0
    publish_fps: float = 0.0
    frames_dropped_by_pacer: int = 0
    jitter_buffer_frames: int = 0
    jitter_buffer_ms: float = 0.0
    last_decoded_frame_age: float = 0.0
    last_paced_frame_age: float = 0.0
    last_published_frame_age: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert snapshot to standard Python dict."""
        d = asdict(self)
        if not d.get("error_message"):
            d["error_message"] = None
        return d


@dataclass
class Observation:
    """Unified observation snapshot coupling video frame with detections and counters (Point 10)."""
    frame_id: int = 0
    frame_pts: float = 0.0
    timestamp: float = 0.0
    annotated_frame: np.ndarray | None = None
    raw_frame: np.ndarray | None = None
    people_count: int = 0
    car_count: int = 0
    detection_count: int = 0
    track_count: int = 0
    is_fallback: bool = False
    source_generation: int = 1
    zone_enabled: bool = False
    zone_mode: str = "full_view"
    car_count_label: str = "VEHICLES IN VIEW"
    vehicles_in_view: int = 0
    vehicles_in_zone: int = 0
    jpeg_bytes: bytes | None = None



class SharedRuntimeState:
    """Thread-safe singleton holding the newest frame and telemetry metrics.

    Uses strict latest-frame semantics: old frames are instantly overwritten.
    No unbounded queue exists, guaranteeing zero latency buildup for consumers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Frames & Source Generation
        self._source_generation: int = 1
        self._latest_frame: np.ndarray | None = None
        self._annotated_frame: np.ndarray | None = None
        self._last_good_annotated_frame: np.ndarray | None = None
        self._last_good_source_generation: int = 0
        self._frame_id: int = 0
        self._timestamp: float = time.time()
        self._last_processed_frame_time: float = 0.0
        self._last_annotated_frame_time: float = 0.0

        # Observation and Sync (Point 10)
        self._current_obs: Observation | None = None
        self._last_good_obs: Observation | None = None
        self._is_serving_fallback: bool = False

        # MJPEG Publisher Diagnostics
        self._last_jpeg_encode_time: float = 0.0
        self._last_mjpeg_publish_time: float = 0.0
        self._last_jpeg_success: bool = True
        self._last_jpeg_error: str = ""
        self._mjpeg_clients_count: int = 0
        self._mjpeg_connection_generation: int = 0

        # Pacer Diagnostics
        self._decoded_frames_total: int = 0
        self._decoded_fps: float = 0.0
        self._paced_frames_total: int = 0
        self._paced_fps: float = 0.0
        self._published_frames_total: int = 0
        self._publish_fps: float = 0.0
        self._frames_dropped_by_pacer: int = 0
        self._jitter_buffer_frames: int = 0
        self._jitter_buffer_ms: float = 0.0
        self._last_decoded_frame_age: float = 0.0
        self._last_paced_frame_age: float = 0.0
        self._last_published_frame_age: float = 0.0

        # Status: "STOPPED", "IDLE", "RUNNING", "ERROR"
        self._status: str = "STOPPED"
        self._error_message: str = ""
        # Camera-switch guard: suppresses AI pipeline ERROR writes during switch
        self._switching: bool = False

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
        self._car_count: int = 0
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
        self._stream_health: dict[str, Any] = {}
        self._capture_fps = 0.0
        self._inference_fps = 0.0
        self._display_fps = 0.0
        self._dropped_frames = 0
        self._buffer_age_ms = 0.0

        # Zone Counting & Diagnostics
        self._zone_enabled: bool = False
        self._vehicles_in_view: int = 0
        self._vehicles_in_zone: int = 0
        self._latest_jpeg_bytes: bytes | None = None
        self._latest_jpeg_frame_id: int = -1

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    @property
    def is_idle(self) -> bool:
        with self._lock:
            return self._status == "IDLE"

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._status == "RUNNING"

    @property
    def error_message(self) -> str:
        with self._lock:
            return self._error_message

    @property
    def source_generation(self) -> int:
        with self._lock:
            return self._source_generation

    @property
    def mjpeg_clients_count(self) -> int:
        with self._lock:
            return self._mjpeg_clients_count

    @property
    def zone_enabled(self) -> bool:
        with self._lock:
            return self._zone_enabled

    def set_zone_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._zone_enabled = bool(enabled)

    def get_latest_jpeg_bytes(self, expected_frame_id: int | None = None) -> bytes | None:
        """Return cached JPEG bytes encoded once per new frame."""
        with self._lock:
            if expected_frame_id is not None and self._latest_jpeg_frame_id != expected_frame_id:
                return None
            return self._latest_jpeg_bytes

    def clear_frames(self, increment_generation: bool = True) -> None:
        """Clear cached frames to avoid serving stale video on camera switch or idle.

        Requirement C3: Always clears last-good frame and increments source_generation
        so a new source never renders leftover frames from a previous generation.
        """
        with self._lock:
            if increment_generation:
                self._source_generation += 1
            self._latest_frame = None
            self._annotated_frame = None
            self._last_good_annotated_frame = None
            self._last_good_source_generation = self._source_generation
            self._current_obs = None
            self._last_good_obs = None
            self._is_serving_fallback = False
            self._people_count = 0
            self._car_count = 0
            self._detection_count = 0
            self._track_count = 0
            self._vehicles_in_view = 0
            self._vehicles_in_zone = 0
            self._latest_jpeg_bytes = None
            self._latest_jpeg_frame_id = -1

    def update(
        self,
        latest_frame: np.ndarray | None = None,
        annotated_frame: np.ndarray | None = None,
        people_count: int = 0,
        car_count: int = 0,
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
        capture_fps: float | None = None,
        inference_fps: float | None = None,
        display_fps: float | None = None,
        dropped_frames: int | None = None,
        buffer_age_ms: float | None = None,
        camera_id: str | None = None,
        camera_name: str | None = None,
        last_event: str | None = None,
        event_count_today: int | None = None,
        last_saved_people_count: int | None = None,
        decoded_frames_total: int | None = None,
        decoded_fps: float | None = None,
        paced_frames_total: int | None = None,
        paced_fps: float | None = None,
        published_frames_total: int | None = None,
        publish_fps: float | None = None,
        frames_dropped_by_pacer: int | None = None,
        jitter_buffer_frames: int | None = None,
        jitter_buffer_ms: float | None = None,
        last_decoded_frame_age: float | None = None,
        last_paced_frame_age: float | None = None,
        zone_enabled: bool | None = None,
        zone_mode: str | None = None,
        car_count_label: str | None = None,
        vehicles_in_view: int | None = None,
        vehicles_in_zone: int | None = None,
        jpeg_bytes: bytes | None = None,
        frame_id: int | None = None,
        frame_pts: float | None = None,
    ) -> None:
        """Atomically update state with the newest frame and metrics.

        Overwrites any previous frame to enforce zero-queue latest-frame semantics.
        """
        with self._lock:
            now = time.time()
            if frame_id is not None:
                self._frame_id = frame_id
            else:
                self._frame_id += 1
            self._frame_pts = frame_pts if frame_pts is not None else 0.0
            self._timestamp = now
            self._last_processed_frame_time = now
            self._is_serving_fallback = False

            if zone_enabled is not None:
                self._zone_enabled = bool(zone_enabled)
            if vehicles_in_view is not None:
                self._vehicles_in_view = vehicles_in_view
            else:
                self._vehicles_in_view = car_count
            if vehicles_in_zone is not None:
                self._vehicles_in_zone = vehicles_in_zone
            else:
                self._vehicles_in_zone = car_count
            if jpeg_bytes is not None:
                self._latest_jpeg_bytes = jpeg_bytes
                self._latest_jpeg_frame_id = self._frame_id

            if latest_frame is not None:
                self._latest_frame = latest_frame
            if annotated_frame is not None:
                self._annotated_frame = annotated_frame
                self._last_annotated_frame_time = now
                self._last_good_annotated_frame = annotated_frame
                self._last_good_source_generation = self._source_generation

            self._people_count = people_count
            self._car_count = car_count
            self._detection_count = detection_count
            self._track_count = track_count

            active_label = car_count_label or ("VEHICLES IN ZONE" if self._zone_enabled else "VEHICLES IN VIEW")
            active_mode = zone_mode or ("Selected Zone" if self._zone_enabled else "Full View")

            obs = Observation(
                frame_id=self._frame_id,
                frame_pts=self._frame_pts,
                timestamp=now,
                annotated_frame=annotated_frame,
                raw_frame=latest_frame,
                people_count=people_count,
                car_count=car_count,
                detection_count=detection_count,
                track_count=track_count,
                is_fallback=False,
                source_generation=self._source_generation,
                zone_enabled=self._zone_enabled,
                zone_mode=active_mode,
                car_count_label=active_label,
                vehicles_in_view=self._vehicles_in_view,
                vehicles_in_zone=self._vehicles_in_zone,
                jpeg_bytes=jpeg_bytes,
            )
            self._current_obs = obs

            if annotated_frame is not None:
                self._last_good_obs = obs
            self._stream_fps = stream_fps
            self._processing_fps = processing_fps
            self._yolo_latency_ms = yolo_latency_ms
            self._pipeline_latency_ms = pipeline_latency_ms
            self._device = device
            self._gpu_name = gpu_name
            self._vram_mb = vram_mb
            self._model_name = model_name
            self._input_size = input_size
            if capture_fps is not None: self._capture_fps = capture_fps
            if inference_fps is not None: self._inference_fps = inference_fps
            if display_fps is not None: self._display_fps = display_fps
            if dropped_frames is not None: self._dropped_frames = dropped_frames
            if buffer_age_ms is not None: self._buffer_age_ms = buffer_age_ms

            if decoded_frames_total is not None: self._decoded_frames_total = decoded_frames_total
            if decoded_fps is not None: self._decoded_fps = decoded_fps
            if paced_frames_total is not None: self._paced_frames_total = paced_frames_total
            if paced_fps is not None: self._paced_fps = paced_fps
            if published_frames_total is not None: self._published_frames_total = published_frames_total
            if publish_fps is not None: self._publish_fps = publish_fps
            if frames_dropped_by_pacer is not None: self._frames_dropped_by_pacer = frames_dropped_by_pacer
            if jitter_buffer_frames is not None: self._jitter_buffer_frames = jitter_buffer_frames
            if jitter_buffer_ms is not None: self._jitter_buffer_ms = jitter_buffer_ms
            if last_decoded_frame_age is not None: self._last_decoded_frame_age = last_decoded_frame_age
            if last_paced_frame_age is not None: self._last_paced_frame_age = last_paced_frame_age

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
        """Update the operational status of the pipeline.

        During a camera switch (_switching=True), ERROR writes from the AI pipeline
        loop are suppressed to prevent the race condition where a brief frame gap
        during source switching causes a spurious ERROR status.
        STOPPED, IDLE, RUNNING, and WARNING writes always pass through.
        """
        with self._lock:
            if status == "ERROR" and self._switching:
                return  # Suppress transient error during source switch
            self._status = status
            self._error_message = error_message

    def set_switching(self) -> None:
        """Enter camera-switching mode — suppresses transient ERROR from AI pipeline."""
        with self._lock:
            self._switching = True
            self._status = "RUNNING"
            self._error_message = ""

    def clear_switching(self) -> None:
        """Exit camera-switching mode — allows ERROR status writes again."""
        with self._lock:
            self._switching = False

    def set_stream_health(self, health: dict[str, Any]) -> None:
        """Publish runtime stream diagnostics for the telemetry endpoint."""
        with self._lock:
            self._stream_health = dict(health)

    def set_mjpeg_clients(self, count: int, generation: int) -> None:
        """Track active MJPEG streaming client count and connection generation."""
        with self._lock:
            self._mjpeg_clients_count = count
            self._mjpeg_connection_generation = generation

    def record_mjpeg_publish(self, success: bool, error: str = "") -> None:
        """Record MJPEG frame publish event and latency diagnostics."""
        with self._lock:
            now = time.time()
            self._last_jpeg_encode_time = now
            self._last_mjpeg_publish_time = now
            self._last_jpeg_success = success
            self._last_jpeg_error = error
            if success:
                self._published_frames_total += 1

    def update_telemetry(self, snapshot: TelemetrySnapshot) -> None:
        """Update telemetry fields from a TelemetrySnapshot."""
        with self._lock:
            self._people_count = snapshot.people_count
            self._car_count = snapshot.car_count
            self._detection_count = snapshot.detection_count
            self._track_count = snapshot.track_count
            self._stream_fps = snapshot.stream_fps
            self._processing_fps = snapshot.processing_fps
            self._yolo_latency_ms = snapshot.yolo_latency_ms
            self._pipeline_latency_ms = snapshot.pipeline_latency_ms
            if snapshot.status:
                self._status = snapshot.status
            if snapshot.camera_status:
                self._status = snapshot.camera_status

    def get_annotated_frame(self) -> tuple[int, np.ndarray | None]:
        """Fetch the newest annotated frame and its frame ID.

        Returns:
            tuple[int, np.ndarray | None]: (frame_id, annotated_frame)
        """
        with self._lock:
            return self._frame_id, self._annotated_frame

    def _stream_observation_locked(self):
        current = self._current_obs
        if current is not None and self._annotated_frame is not None and current.annotated_frame is not None and current.source_generation == self._source_generation:
            return current, time.time() - current.timestamp > 0.35
        previous = self._last_good_obs
        if previous is not None and previous.source_generation == self._source_generation:
            return previous, True
        return None, True

    def get_frame_for_stream(self) -> tuple[int, np.ndarray | None, bool, int]:
        """Use the same observation selection as telemetry, including zero-count frames."""
        with self._lock:
            obs, fallback = self._stream_observation_locked()
            self._is_serving_fallback = fallback
            return (obs.frame_id if obs else self._frame_id,
                    obs.annotated_frame if obs else None, fallback, self._source_generation)

    def get_raw_frame(self) -> tuple[int, np.ndarray | None]:
        """Fetch the newest raw frame and its frame ID."""
        with self._lock:
            return self._frame_id, self._latest_frame

    def get_observation(self) -> Observation | None:
        """Fetch current synchronized observation snapshot."""
        with self._lock:
            return self._current_obs

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
            elif self._status == "IDLE":
                camera_status = "IDLE"
                stream_alive = False
                err = ""
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

            last_pub_age = max(0.0, now - self._last_mjpeg_publish_time) if self._last_mjpeg_publish_time > 0 else 0.0

            # Point 10: Counter Sync with Displayed Frame
            obs, is_fallback_active = self._stream_observation_locked()
            active_frame_id = obs.frame_id if obs else self._frame_id
            active_people = obs.people_count if obs else self._people_count
            active_cars = obs.car_count if obs else self._car_count
            active_dets = obs.detection_count if obs else self._detection_count
            active_tracks = obs.track_count if obs else self._track_count

            return TelemetrySnapshot(
                frame_id=active_frame_id,
                timestamp=obs.timestamp if obs else self._timestamp,
                status=camera_status,
                camera_status=camera_status,
                stream_alive=stream_alive,
                last_frame_time=last_frame_time,
                error_message=err,
                people_count=active_people,
                car_count=active_cars,
                detection_count=active_dets,
                track_count=active_tracks,
                is_fallback=is_fallback_active,
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
                stream_health=dict(self._stream_health),
                capture_fps=self._capture_fps,
                inference_fps=self._inference_fps,
                display_fps=self._display_fps,
                dropped_frames=self._dropped_frames,
                buffer_age_ms=self._buffer_age_ms,
                zone_enabled=obs.zone_enabled if obs else self._zone_enabled,
                zone_mode="selected_zone" if self._zone_enabled else "full_view",
                car_count_label="VEHICLES IN ZONE" if self._zone_enabled else "VEHICLES IN VIEW",
                vehicles_in_view=obs.vehicles_in_view if obs else self._vehicles_in_view,
                vehicles_in_zone=obs.vehicles_in_zone if obs else self._vehicles_in_zone,
                source_generation=self._source_generation,
                mjpeg_clients=self._mjpeg_clients_count,
                mjpeg_connection_generation=self._mjpeg_connection_generation,
                last_jpeg_success=self._last_jpeg_success,
                last_jpeg_error=self._last_jpeg_error,
                decoded_frames_total=self._decoded_frames_total,
                decoded_fps=self._decoded_fps,
                paced_frames_total=self._paced_frames_total,
                paced_fps=self._paced_fps,
                published_frames_total=self._published_frames_total,
                publish_fps=self._publish_fps,
                frames_dropped_by_pacer=self._frames_dropped_by_pacer,
                jitter_buffer_frames=self._jitter_buffer_frames,
                jitter_buffer_ms=self._jitter_buffer_ms,
                last_decoded_frame_age=self._last_decoded_frame_age,
                last_paced_frame_age=self._last_paced_frame_age,
                last_published_frame_age=round(last_pub_age, 2),
            )

    def reset(self) -> None:
        """Reset state when pipeline stops."""
        with self._lock:
            self._latest_frame = None
            self._annotated_frame = None
            self._last_good_annotated_frame = None
            self._last_good_source_generation = self._source_generation
            self._frame_id = 0
            self._status = "STOPPED"
            self._error_message = ""
            self._people_count = 0
            self._car_count = 0
            self._detection_count = 0
            self._track_count = 0



# Global shared singleton instance
shared_state = SharedRuntimeState()

