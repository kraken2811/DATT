"""Event Engine for DATT - AI People Counter.

Phase 4 Version 3: Camera Management & Event Logging.
Monitors runtime occupancy changes from ZoneCounter, generates structured
PEOPLE_COUNT_CHANGED events, and saves annotated JPEG snapshots asynchronously.
"""

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


class EventManager:
    """Detects and asynchronously persists people counting events."""

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
        """Evaluate occupancy count on new frame and trigger event if changed.

        Args:
            camera_id: Current camera identifier.
            people_count: Active count of people in view.
            annotated_frame: Rendered frame with bounding boxes.

        Returns:
            dict[str, Any] | None: Event details if an event was generated.
        """
        now_ts = time.time()
        # Initial frame initialization; realtime telemetry remains independent.
        if self._last_people_count is None or self._last_camera_id != camera_id:
            self._last_people_count = people_count
            self._last_camera_id = camera_id
            self._last_saved_count = people_count
            self._last_report_time = now_ts
            self.state.update(last_saved_people_count=people_count)
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
            return None

        if self._candidate_count != people_count:
            self._candidate_count, self._candidate_since = people_count, now_ts
            return None
        if now_ts - self._candidate_since < STABLE_TIME_SECONDS:
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

        # Format human-readable event summary for dashboard / state
        event_summary = f"{camera_id}: {old_count} -> {new_count}"
        # Snapshot and persistence are only reached for filtered, stable events.

        # Snapshot rate-limiting to avoid disk thrashing on rapid count fluctuation
        should_save_snapshot = (
            annotated_frame is not None
            and (now_ts - self._last_event_time) >= self.min_snapshot_interval_sec
        )

        frame_copy = annotated_frame.copy() if (should_save_snapshot and annotated_frame is not None) else None
        if should_save_snapshot:
            self._last_event_time = now_ts

        # Offload file save and DB insert to background worker (<0.1ms overhead)
        try:
            self._task_queue.put_nowait(
                (timestamp_str, camera_id, "PEOPLE_COUNT_CHANGED", old_count, new_count, frame_copy)
            )
        except queue.Full:
            logger.warning("EventManager: Persistence queue full, dropping event disk write.")

        logger.info(
            "[DATT EVENT] Saved occupancy event: [%s] Camera '%s' People Changed: %d -> %d",
            timestamp_str,
            camera_id,
            old_count,
            new_count,
        )
        return event_data

    def _worker_loop(self) -> None:
        """Background thread worker that saves snapshots and records SQLite rows."""
        while not self._stop_event.is_set():
            try:
                task = self._task_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            ts_str, cam_id, ev_type, old_val, new_val, frame = task
            try:
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
            except Exception as exc:
                logger.error("EventManager Worker Error: %s", exc, exc_info=True)
            finally:
                self._task_queue.task_done()

    def reset(self) -> None:
        """Reset internal tracking count."""
        self._last_people_count = None
        self._last_camera_id = None
        self._last_saved_count = None
        self._candidate_count = None

    def stop(self) -> None:
        """Cleanly terminate background worker."""
        self._stop_event.set()
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)


# Global singleton instance
event_manager = EventManager()
