"""Event Engine for DATT - People Counter and Vehicle Passage Tracker.

Monitors runtime occupancy and vehicle passages, generates structured
business events (VEHICLE_ENTER, PLATE_RECOGNIZED, ZONE_ENTER, ZONE_EXIT, VEHICLE_EXIT),
and saves annotated JPEG snapshots / vehicle passages asynchronously via background worker.
Debug telemetry (OCR_ATTEMPT, WAIT_CADENCE, NO_PLATE_DETECTED) is strictly filtered.
"""

from dataclasses import dataclass
from datetime import datetime
import queue
import threading
import time
from typing import Any

import numpy as np

from src.events.event_storage import EventStorage, event_storage
from src.runtime.shared_state import SharedRuntimeState, shared_state
from src.utils.logger import logger

EVENT_REPORT_INTERVAL = 300.0
SIGNIFICANT_CHANGE = 5
STABLE_TIME_SECONDS = 5.0
SNAPSHOT_INTERVAL_SECONDS = 60.0

VALID_BUSINESS_EVENTS = {
    "VEHICLE_ENTER",
    "PLATE_RECOGNIZED",
    "ZONE_ENTER",
    "ZONE_EXIT",
    "VEHICLE_EXIT",
    "PEOPLE_COUNT_CHANGED",
}


@dataclass
class VehiclePassage:
    """One vehicle passage / session record."""
    camera_id: str
    track_id: int
    vehicle_type: str = "vehicle"
    vehicle_color: str | None = None
    zone_id: str | None = None
    plate_text: str = ""
    plate_status: str = "SEARCHING"
    plate_confidence: float = 0.0
    direction: str = "UNKNOWN"
    first_seen: float = 0.0
    last_seen: float = 0.0
    duration: float = 0.0
    best_vehicle_image: np.ndarray | None = None
    best_plate_image: np.ndarray | None = None
    entered: bool = False
    in_zone: bool = False
    exited: bool = False
    best_vehicle_area: float = 0.0


# Backward-compatible alias
VehicleSession = VehiclePassage


class EventManager:
    """Detects and asynchronously persists business events and vehicle passages."""

    def __init__(
        self,
        storage: EventStorage = event_storage,
        state: SharedRuntimeState = shared_state,
        min_snapshot_interval_sec: float = SNAPSHOT_INTERVAL_SECONDS,
        event_report_interval: float = EVENT_REPORT_INTERVAL,
    ) -> None:
        self.storage = storage
        self.state = state
        self.min_snapshot_interval_sec = min_snapshot_interval_sec
        self.event_report_interval = event_report_interval

        self._last_people_count: int | None = None
        self._last_camera_id: str | None = None
        self._last_event_time: float = 0.0
        self._last_saved_count: int | None = None
        self._candidate_count: int | None = None
        self._candidate_since: float = 0.0
        self._last_report_time: float = time.time()

        self._active_passages: dict[int, VehiclePassage] = {}
        self.last_event_build_ms: float = 0.0
        self.last_db_work_ms: float = 0.0

        # Background worker for zero-overhead asynchronous disk writes
        self._task_queue: queue.Queue = queue.Queue(maxsize=100)
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="EventPersistenceWorker",
            daemon=True,
        )
        self._worker_thread.start()

    def process_frame(
        self,
        camera_id: str,
        people_count: int,
        annotated_frame: np.ndarray | None = None,
    ) -> dict[str, Any] | None:
        """Evaluate occupancy count on new frame and trigger event if changed."""
        t_eb_0 = time.perf_counter()
        now_ts = time.time()
        # Initial frame initialization; realtime telemetry remains independent.
        if self._last_people_count is None or self._last_camera_id != camera_id:
            self._last_people_count = people_count
            self._last_camera_id = camera_id
            self._last_saved_count = people_count
            self._last_report_time = now_ts
            self.state.update(last_saved_people_count=people_count)
            self.last_event_build_ms = (time.perf_counter() - t_eb_0) * 1000.0
            return None

        self._last_people_count = people_count
        old_count = self._last_saved_count if self._last_saved_count is not None else people_count
        significant = abs(people_count - old_count) >= SIGNIFICANT_CHANGE
        periodic = now_ts - self._last_report_time >= self.event_report_interval
        if not significant and not periodic:
            if people_count != old_count:
                self.state.record_filtered_event()
                logger.info("[DATT EVENT FILTER] Ignored: %d -> %d; Reason: normal fluctuation", old_count, people_count)
            self._candidate_count = None
            self.last_event_build_ms = (time.perf_counter() - t_eb_0) * 1000.0
            return None

        if self._candidate_count != people_count:
            self._candidate_count, self._candidate_since = people_count, now_ts
            self.last_event_build_ms = (time.perf_counter() - t_eb_0) * 1000.0
            return None
        if now_ts - self._candidate_since < STABLE_TIME_SECONDS:
            self.last_event_build_ms = (time.perf_counter() - t_eb_0) * 1000.0
            return None

        new_count = people_count
        self._last_saved_count = new_count
        self._last_report_time = now_ts
        self._candidate_count = None

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        event_data = {
            "time": timestamp_str,
            "camera": camera_id,
            "type": "PEOPLE_COUNT_CHANGED",
            "old_count": old_count,
            "new_count": new_count,
        }

        should_save_snapshot = (
            annotated_frame is not None
            and (now_ts - self._last_event_time) >= self.min_snapshot_interval_sec
        )

        frame_copy = annotated_frame.copy() if (should_save_snapshot and annotated_frame is not None) else None
        if should_save_snapshot:
            self._last_event_time = now_ts

        self.last_event_build_ms = (time.perf_counter() - t_eb_0) * 1000.0
        # Offload file save and DB insert to background worker (<0.01ms overhead)
        t_db_0 = time.perf_counter()
        try:
            self._task_queue.put_nowait(
                ("PEOPLE_EVENT", timestamp_str, camera_id, "PEOPLE_COUNT_CHANGED", old_count, new_count, frame_copy)
            )
        except queue.Full:
            logger.warning("EventManager: Persistence queue full, dropping event disk write.")
        self.last_db_work_ms = (time.perf_counter() - t_db_0) * 1000.0

        logger.info(
            "[DATT EVENT] Saved occupancy event: [%s] Camera '%s' People Changed: %d -> %d",
            timestamp_str,
            camera_id,
            old_count,
            new_count,
        )
        return event_data

    def process_vehicle_frame(
        self,
        camera_id: str,
        vehicle_tracks: Any,
        plate_results: dict[int, Any] | None = None,
        in_zone_ids: Any = None,
        zone_id: str | None = None,
        frame: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate vehicle passage lifecycle and emit business events (non-blocking)."""
        t_eb_0 = time.perf_counter()
        now_ts = time.time()
        emitted_events: list[dict[str, Any]] = []

        active_tracker_ids = set()
        xyxy = getattr(vehicle_tracks, "xyxy", None)
        tracker_ids = getattr(vehicle_tracks, "tracker_id", None)
        class_ids = getattr(vehicle_tracks, "class_id", None)

        if tracker_ids is not None and xyxy is not None:
            for idx, tid in enumerate(tracker_ids):
                if tid is None:
                    continue
                tid_int = int(tid)
                active_tracker_ids.add(tid_int)
                box = xyxy[idx]
                box_area = float((box[2] - box[0]) * (box[3] - box[1]))

                passage = self._active_passages.get(tid_int)
                if passage is None:
                    # VEHICLE_ENTER transition
                    passage = VehiclePassage(
                        camera_id=camera_id,
                        track_id=tid_int,
                        first_seen=now_ts,
                        last_seen=now_ts,
                        entered=True,
                        best_vehicle_area=box_area,
                    )
                    self._active_passages[tid_int] = passage
                    ev = {"type": "VEHICLE_ENTER", "track_id": tid_int, "camera_id": camera_id, "timestamp": now_ts}
                    emitted_events.append(ev)
                    self._queue_business_event("VEHICLE_ENTER", camera_id, tid_int, ev)

                passage.last_seen = now_ts
                passage.duration = max(0.0, now_ts - passage.first_seen)

                # Update best vehicle crop
                if frame is not None and box_area > passage.best_vehicle_area:
                    passage.best_vehicle_area = box_area
                    bx1, by1, bx2, by2 = [max(0, int(v)) for v in box[:4]]
                    vh, vw = frame.shape[:2]
                    bx2, by2 = min(vw, bx2), min(vh, by2)
                    if (bx2 - bx1) >= 30 and (by2 - by1) >= 30:
                        passage.best_vehicle_image = frame[by1:by2, bx1:bx2].copy()

                # Check PLATE_RECOGNIZED transition
                if plate_results and tid_int in plate_results:
                    p_state = plate_results[tid_int]
                    if p_state.plate_text and not passage.plate_text:
                        passage.plate_text = p_state.plate_text
                        passage.plate_status = p_state.status
                        passage.plate_confidence = p_state.confidence
                        passage.best_plate_image = p_state.plate_crop
                        ev = {
                            "type": "PLATE_RECOGNIZED",
                            "track_id": tid_int,
                            "plate_text": passage.plate_text,
                            "confidence": passage.plate_confidence,
                            "camera_id": camera_id,
                            "timestamp": now_ts,
                        }
                        emitted_events.append(ev)
                        self._queue_business_event("PLATE_RECOGNIZED", camera_id, tid_int, ev)

                # Check ZONE_ENTER / ZONE_EXIT transitions
                if in_zone_ids is not None:
                    in_zone = (tid_int in in_zone_ids)
                    if in_zone and not passage.in_zone:
                        passage.in_zone = True
                        passage.zone_id = zone_id or "zone_1"
                        ev = {"type": "ZONE_ENTER", "track_id": tid_int, "zone_id": passage.zone_id, "camera_id": camera_id, "timestamp": now_ts}
                        emitted_events.append(ev)
                        self._queue_business_event("ZONE_ENTER", camera_id, tid_int, ev)
                    elif not in_zone and passage.in_zone:
                        passage.in_zone = False
                        ev = {"type": "ZONE_EXIT", "track_id": tid_int, "zone_id": passage.zone_id, "camera_id": camera_id, "timestamp": now_ts}
                        emitted_events.append(ev)
                        self._queue_business_event("ZONE_EXIT", camera_id, tid_int, ev)

        # Check expired / lost tracks for VEHICLE_EXIT
        expired_ids = []
        for tid, passage in self._active_passages.items():
            if (now_ts - passage.last_seen) > 3.0:
                expired_ids.append(tid)

        for tid in expired_ids:
            passage = self._active_passages.pop(tid)
            passage.exited = True
            ev = {"type": "VEHICLE_EXIT", "track_id": tid, "camera_id": camera_id, "duration": passage.duration, "timestamp": now_ts}
            emitted_events.append(ev)
            self._queue_business_event("VEHICLE_EXIT", camera_id, tid, ev)
            self._queue_passage(passage)

        self.last_event_build_ms = (time.perf_counter() - t_eb_0) * 1000.0
        return emitted_events

    def _queue_business_event(self, event_type: str, camera_id: str, track_id: int, metadata: dict[str, Any]) -> None:
        """Queue a valid business transition event to the background persistence thread."""
        if event_type not in VALID_BUSINESS_EVENTS:
            return  # Reject telemetry
        t_db_0 = time.perf_counter()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._task_queue.put_nowait(("BUSINESS_EVENT", now_str, camera_id, event_type, track_id, metadata, None))
        except queue.Full:
            logger.warning("EventManager: Persistence queue full, dropping business event.")
        self.last_db_work_ms += (time.perf_counter() - t_db_0) * 1000.0

    def _queue_passage(self, passage: VehiclePassage) -> None:
        """Queue finalized VehiclePassage to the background persistence thread."""
        t_db_0 = time.perf_counter()
        try:
            self._task_queue.put_nowait(("VEHICLE_PASSAGE", passage))
        except queue.Full:
            logger.warning("EventManager: Persistence queue full, dropping vehicle passage.")
        self.last_db_work_ms += (time.perf_counter() - t_db_0) * 1000.0

    def _worker_loop(self) -> None:
        """Background thread worker that saves snapshots and records SQLite rows."""
        while not (self._stop_event.is_set() and self._task_queue.empty()):
            try:
                task = self._task_queue.get(timeout=0.1)
            except queue.Empty:
                if self._stop_event.is_set():
                    break
                continue

            try:
                task_type = task[0]
                if task_type == "PEOPLE_EVENT":
                    _, ts_str, cam_id, ev_type, old_val, new_val, frame = task
                    self.storage.save_event(
                        timestamp=ts_str,
                        camera_id=cam_id,
                        event_type=ev_type,
                        old_value=old_val,
                        new_value=new_val,
                        annotated_frame=frame,
                    )
                    today_count = self.storage.get_event_count_today()
                    self.state.record_saved_event(f"{cam_id}: {old_val} -> {new_val}", ts_str, new_val, today_count)
                elif task_type == "BUSINESS_EVENT":
                    _, ts_str, cam_id, ev_type, track_id, metadata, frame = task
                    self.storage.save_event(
                        timestamp=ts_str,
                        camera_id=cam_id,
                        event_type=ev_type,
                        old_value=track_id,
                        new_value=1,
                        annotated_frame=frame,
                    )
                elif task_type == "VEHICLE_PASSAGE":
                    _, passage = task
                    self.storage.save_passage(passage)
            except Exception as exc:
                logger.error("EventManager Worker Error: %s", exc, exc_info=True)
            finally:
                self._task_queue.task_done()

    def reset(self) -> None:
        """Reset internal tracking count and finalize any active passages."""
        for tid, passage in list(self._active_passages.items()):
            passage.exited = True
            try:
                self._task_queue.put_nowait(("VEHICLE_PASSAGE", passage))
            except queue.Full:
                pass
        self._active_passages.clear()
        self._last_people_count = None
        self._last_camera_id = None
        self._last_saved_count = None
        self._candidate_count = None

    def stop(self) -> None:
        """Cleanly terminate background worker, draining any queued items."""
        self.reset()
        self._stop_event.set()
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)


# Global singleton instance
event_manager = EventManager()
