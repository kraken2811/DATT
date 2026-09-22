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


class EventManager:
    """Detects and asynchronously persists people counting events."""

    def __init__(
        self,
        storage: EventStorage = event_storage,
        state: SharedRuntimeState = shared_state,
        min_snapshot_interval_sec: float = 0.5,
    ) -> None:
        self.storage = storage
        self.state = state
        self.min_snapshot_interval_sec = min_snapshot_interval_sec

        self._last_people_count: int | None = None
        self._last_camera_id: str | None = None
        self._last_event_time: float = 0.0

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
        # Initial frame initialization
        if self._last_people_count is None or self._last_camera_id != camera_id:
            self._last_people_count = people_count
            self._last_camera_id = camera_id
            return None

        # Check for count change
        if people_count == self._last_people_count:
            return None

        old_count = self._last_people_count
        new_count = people_count
        self._last_people_count = new_count
        self._last_camera_id = camera_id

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        now_ts = time.time()

        event_data = {
            "time": timestamp_str,
            "camera": camera_id,
            "type": "PEOPLE_COUNT_CHANGED",
            "old_count": old_count,
            "new_count": new_count,
        }

        # Format human-readable event summary for dashboard / state
        event_summary = f"{camera_id}: {old_count} -> {new_count}"
        self.state.record_event(event_summary)

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
            "Event Triggered: [%s] Camera '%s' People Changed: %d -> %d",
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
                self.state.record_event(f"{cam_id}: {old_val} -> {new_val}", count_today=today_count)
            except Exception as exc:
                logger.error("EventManager Worker Error: %s", exc, exc_info=True)
            finally:
                self._task_queue.task_done()

    def reset(self) -> None:
        """Reset internal tracking count."""
        self._last_people_count = None
        self._last_camera_id = None

    def stop(self) -> None:
        """Cleanly terminate background worker."""
        self._stop_event.set()
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)


# Global singleton instance
event_manager = EventManager()
