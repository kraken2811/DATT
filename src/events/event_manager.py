"""Event Engine for DATT - People Counter and Vehicle Passage Tracker.

Monitors runtime occupancy and vehicle passages, generates structured
business events (VEHICLE_ENTER, PLATE_RECOGNIZED, ZONE_ENTER, ZONE_EXIT, VEHICLE_EXIT),
and saves vehicle passages asynchronously to PostgreSQL via dedicated DB worker.
Debug telemetry (OCR_ATTEMPT, WAIT_CADENCE, NO_PLATE_DETECTED) is strictly filtered.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from src.events.db_worker import DatabaseWorker
from src.events.event_dto import BusinessEventDTO, VehiclePassageDTO
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

CLASS_MAP = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


@dataclass
class VehiclePassage:
    """One vehicle passage / session record in RAM.

    vehicle_color is nullable and currently unavailable from detector runtime;
    not fabricated.
    """
    camera_id: str
    track_id: int
    id: UUID = field(default_factory=uuid4)
    session_key: str = ""
    vehicle_type: str = "vehicle"
    vehicle_color: str | None = None
    vehicle_type_confidence: float | None = None
    vehicle_color_confidence: float | None = None
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
    best_vehicle_image_path: str | None = None
    best_plate_image_path: str | None = None
    entered: bool = False
    in_zone: bool = False
    exited: bool = False
    best_vehicle_area: float = 0.0
    plate_confirmed_emitted: bool = False
    confirmed_plate: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finalized_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.session_key:
            ts_ms = int(self.first_seen * 1000) if self.first_seen > 0 else int(time.time() * 1000)
            self.session_key = f"{self.camera_id}:{self.track_id}:{ts_ms}"

    def to_dto(self, is_final: bool = False) -> VehiclePassageDTO:
        """Convert internal RAM session state to immutable DTO for DB worker."""
        first_dt = (
            datetime.fromtimestamp(self.first_seen, tz=timezone.utc)
            if self.first_seen > 0
            else self.created_at
        )
        last_dt = (
            datetime.fromtimestamp(self.last_seen, tz=timezone.utc)
            if self.last_seen > 0
            else first_dt
        )
        fin_dt = datetime.now(timezone.utc) if is_final else self.finalized_at
        return VehiclePassageDTO(
            id=self.id,
            session_key=self.session_key,
            camera_id=self.camera_id,
            track_id=self.track_id,
            first_seen_at=first_dt,
            last_seen_at=last_dt,
            vehicle_type=self.vehicle_type,
            vehicle_color=self.vehicle_color,
            vehicle_type_confidence=self.vehicle_type_confidence,
            vehicle_color_confidence=self.vehicle_color_confidence,
            zone_id=self.zone_id,
            plate_text=self.plate_text or None,
            plate_status=self.plate_status or None,
            plate_confidence=self.plate_confidence if self.plate_text else None,
            direction=self.direction if self.direction != "UNKNOWN" else None,
            duration_ms=self.duration * 1000.0,
            best_vehicle_image_path=self.best_vehicle_image_path,
            best_plate_image_path=self.best_plate_image_path,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
            finalized_at=fin_dt,
            is_final=is_final,
        )


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
        db_worker: DatabaseWorker | None = None,
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

        # Dedicated PostgreSQL background persistence worker (zero realtime I/O)
        self.db_worker = db_worker or DatabaseWorker()

    def process_frame(
        self,
        camera_id: str,
        people_count: int,
        annotated_frame: np.ndarray | None = None,
    ) -> dict[str, Any] | None:
        """Evaluate occupancy count on new frame and trigger event if changed."""
        t_eb_0 = time.perf_counter()
        now_ts = time.time()

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

        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        event_data = {
            "time": timestamp_str,
            "camera": camera_id,
            "type": "PEOPLE_COUNT_CHANGED",
            "old_count": old_count,
            "new_count": new_count,
        }

        self.last_event_build_ms = (time.perf_counter() - t_eb_0) * 1000.0

        # Non-blocking enqueue to DB worker
        t_db_0 = time.perf_counter()
        ev_dto = BusinessEventDTO(
            id=uuid4(),
            passage_id=None,
            camera_id=camera_id,
            event_type="PEOPLE_COUNT_CHANGED",
            event_time=now,
            idempotency_key=f"PEOPLE:{camera_id}:{timestamp_str}",
            metadata={"old_count": old_count, "new_count": new_count},
        )
        self.db_worker.enqueue_business_event(ev_dto, is_critical=True)
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
        confidences = getattr(vehicle_tracks, "confidence", None)

        t_db_accum = 0.0

        if tracker_ids is not None and xyxy is not None:
            for idx, tid in enumerate(tracker_ids):
                if tid is None:
                    continue
                tid_int = int(tid)
                active_tracker_ids.add(tid_int)
                box = xyxy[idx]
                box_area = float((box[2] - box[0]) * (box[3] - box[1]))
                cid = int(class_ids[idx]) if class_ids is not None and idx < len(class_ids) else 2
                v_type = CLASS_MAP.get(cid, "vehicle")
                v_conf = float(confidences[idx]) if confidences is not None and idx < len(confidences) else None

                passage = self._active_passages.get(tid_int)
                if passage is None:
                    # NEW TRACK appearance -> start new VehiclePassage
                    passage_id = uuid4()
                    session_key = f"{camera_id}:{tid_int}:{int(now_ts * 1000)}"

                    # Initial vehicle crop
                    initial_veh_crop = None
                    if frame is not None:
                        bx1, by1, bx2, by2 = [max(0, int(v)) for v in box[:4]]
                        vh, vw = frame.shape[:2]
                        bx2, by2 = min(vw, bx2), min(vh, by2)
                        if (bx2 - bx1) >= 30 and (by2 - by1) >= 30:
                            initial_veh_crop = frame[by1:by2, bx1:bx2].copy()

                    passage = VehiclePassage(
                        id=passage_id,
                        session_key=session_key,
                        camera_id=camera_id,
                        track_id=tid_int,
                        vehicle_type=v_type,
                        vehicle_type_confidence=v_conf,
                        first_seen=now_ts,
                        last_seen=now_ts,
                        entered=True,
                        best_vehicle_area=box_area,
                        best_vehicle_image=initial_veh_crop,
                    )
                    self._active_passages[tid_int] = passage


                    ev = {
                        "type": "VEHICLE_ENTER",
                        "track_id": tid_int,
                        "camera_id": camera_id,
                        "timestamp": now_ts,
                        "vehicle_type": v_type,
                    }
                    emitted_events.append(ev)

                    # Enqueue VEHICLE_ENTER business event & initial passage record (non-blocking)
                    t_db_s = time.perf_counter()
                    ev_dto = BusinessEventDTO(
                        id=uuid4(),
                        passage_id=passage.id,
                        camera_id=camera_id,
                        zone_id=passage.zone_id,
                        track_id=tid_int,
                        event_type="VEHICLE_ENTER",
                        event_time=datetime.fromtimestamp(now_ts, tz=timezone.utc),
                        vehicle_type=v_type,
                        idempotency_key=f"{passage.id}:VEHICLE_ENTER",
                        metadata=ev,
                    )
                    self.db_worker.enqueue_business_event(ev_dto, is_critical=True)
                    self.db_worker.enqueue_passage(passage.to_dto(), is_critical=False)
                    t_db_accum += (time.perf_counter() - t_db_s) * 1000.0

                passage.last_seen = now_ts
                passage.duration = max(0.0, now_ts - passage.first_seen)

                # Update best vehicle crop in RAM (zero synchronous disk I/O)
                if frame is not None and box_area > passage.best_vehicle_area:
                    passage.best_vehicle_area = box_area
                    bx1, by1, bx2, by2 = [max(0, int(v)) for v in box[:4]]
                    vh, vw = frame.shape[:2]
                    bx2, by2 = min(vw, bx2), min(vh, by2)
                    if (bx2 - bx1) >= 30 and (by2 - by1) >= 30:
                        passage.best_vehicle_image = frame[by1:by2, bx1:bx2].copy()

                # Check PLATE_RECOGNIZED transition (strict duplicate suppression)
                if plate_results and tid_int in plate_results:
                    p_state = plate_results[tid_int]
                    p_text = getattr(p_state, "plate_text", "")
                    p_status = getattr(p_state, "status", "SEARCHING")
                    p_conf = float(getattr(p_state, "confidence", 0.0))
                    p_crop = getattr(p_state, "plate_crop", None)

                    if p_text and not passage.plate_confirmed_emitted:
                        passage.plate_text = p_text
                        passage.plate_status = p_status
                        passage.plate_confidence = p_conf
                        passage.best_plate_image = p_crop
                        passage.plate_confirmed_emitted = True
                        passage.confirmed_plate = p_text

                        ev = {
                            "type": "PLATE_RECOGNIZED",
                            "track_id": tid_int,
                            "plate_text": passage.plate_text,
                            "confidence": passage.plate_confidence,
                            "camera_id": camera_id,
                            "timestamp": now_ts,
                        }
                        emitted_events.append(ev)

                        t_db_s = time.perf_counter()
                        ev_dto = BusinessEventDTO(
                            id=uuid4(),
                            passage_id=passage.id,
                            camera_id=camera_id,
                            zone_id=passage.zone_id,
                            track_id=tid_int,
                            event_type="PLATE_RECOGNIZED",
                            event_time=datetime.fromtimestamp(now_ts, tz=timezone.utc),
                            vehicle_type=passage.vehicle_type,
                            plate_text=passage.plate_text,
                            direction=passage.direction if passage.direction != "UNKNOWN" else None,
                            idempotency_key=f"{passage.id}:PLATE_RECOGNIZED:{passage.plate_text}",
                            metadata=ev,
                        )
                        self.db_worker.enqueue_business_event(ev_dto, is_critical=True)
                        self.db_worker.enqueue_passage(passage.to_dto(), plate_crop=passage.best_plate_image, is_critical=True)
                        t_db_accum += (time.perf_counter() - t_db_s) * 1000.0

                # Check ZONE_ENTER / ZONE_EXIT transitions
                if in_zone_ids is not None:
                    in_zone = (tid_int in in_zone_ids)
                    if in_zone and not passage.in_zone:
                        passage.in_zone = True
                        passage.zone_id = zone_id or "zone_1"
                        ev = {
                            "type": "ZONE_ENTER",
                            "track_id": tid_int,
                            "zone_id": passage.zone_id,
                            "camera_id": camera_id,
                            "timestamp": now_ts,
                        }
                        emitted_events.append(ev)
                        t_db_s = time.perf_counter()
                        ev_dto = BusinessEventDTO(
                            id=uuid4(),
                            passage_id=passage.id,
                            camera_id=camera_id,
                            zone_id=passage.zone_id,
                            track_id=tid_int,
                            event_type="ZONE_ENTER",
                            event_time=datetime.fromtimestamp(now_ts, tz=timezone.utc),
                            vehicle_type=passage.vehicle_type,
                            plate_text=passage.plate_text or None,
                            idempotency_key=f"{passage.id}:ZONE_ENTER:{passage.zone_id}",
                            metadata=ev,
                        )
                        self.db_worker.enqueue_business_event(ev_dto, is_critical=True)
                        t_db_accum += (time.perf_counter() - t_db_s) * 1000.0
                    elif not in_zone and passage.in_zone:
                        passage.in_zone = False
                        ev = {
                            "type": "ZONE_EXIT",
                            "track_id": tid_int,
                            "zone_id": passage.zone_id,
                            "camera_id": camera_id,
                            "timestamp": now_ts,
                        }
                        emitted_events.append(ev)
                        t_db_s = time.perf_counter()
                        ev_dto = BusinessEventDTO(
                            id=uuid4(),
                            passage_id=passage.id,
                            camera_id=camera_id,
                            zone_id=passage.zone_id,
                            track_id=tid_int,
                            event_type="ZONE_EXIT",
                            event_time=datetime.fromtimestamp(now_ts, tz=timezone.utc),
                            vehicle_type=passage.vehicle_type,
                            plate_text=passage.plate_text or None,
                            idempotency_key=f"{passage.id}:ZONE_EXIT:{passage.zone_id}",
                            metadata=ev,
                        )
                        self.db_worker.enqueue_business_event(ev_dto, is_critical=True)
                        t_db_accum += (time.perf_counter() - t_db_s) * 1000.0

        # Check expired / lost tracks for VEHICLE_EXIT (timeout 3.0s)
        expired_ids = []
        for tid, passage in self._active_passages.items():
            if (now_ts - passage.last_seen) > 3.0:
                expired_ids.append(tid)

        for tid in expired_ids:
            passage = self._active_passages.pop(tid)
            passage.exited = True
            ev = {
                "type": "VEHICLE_EXIT",
                "track_id": tid,
                "camera_id": camera_id,
                "duration": passage.duration,
                "timestamp": now_ts,
            }
            emitted_events.append(ev)

            t_db_s = time.perf_counter()
            ev_dto = BusinessEventDTO(
                id=uuid4(),
                passage_id=passage.id,
                camera_id=camera_id,
                zone_id=passage.zone_id,
                track_id=tid,
                event_type="VEHICLE_EXIT",
                event_time=datetime.fromtimestamp(now_ts, tz=timezone.utc),
                vehicle_type=passage.vehicle_type,
                plate_text=passage.plate_text or None,
                direction=passage.direction if passage.direction != "UNKNOWN" else None,
                idempotency_key=f"{passage.id}:VEHICLE_EXIT",
                metadata=ev,
            )
            self.db_worker.enqueue_business_event(ev_dto, is_critical=True)
            self.db_worker.enqueue_passage(
                passage.to_dto(is_final=True),
                vehicle_crop=passage.best_vehicle_image,
                plate_crop=passage.best_plate_image,
                is_critical=True,
            )
            t_db_accum += (time.perf_counter() - t_db_s) * 1000.0

        self.last_event_build_ms = (time.perf_counter() - t_eb_0) * 1000.0
        self.last_db_work_ms = t_db_accum
        return emitted_events

    def reset(self) -> None:
        """Reset internal tracking count and finalize any active passages."""
        now_ts = time.time()
        for tid, passage in list(self._active_passages.items()):
            passage.exited = True
            passage.last_seen = now_ts
            passage.duration = max(0.0, now_ts - passage.first_seen)
            dto = passage.to_dto(is_final=True)
            self.db_worker.enqueue_passage(
                dto,
                vehicle_crop=passage.best_vehicle_image,
                plate_crop=passage.best_plate_image,
                is_critical=True,
            )
            ev = {
                "type": "VEHICLE_EXIT",
                "track_id": tid,
                "camera_id": passage.camera_id,
                "duration": passage.duration,
                "timestamp": now_ts,
            }
            ev_dto = BusinessEventDTO(
                id=uuid4(),
                passage_id=passage.id,
                camera_id=passage.camera_id,
                zone_id=passage.zone_id,
                track_id=tid,
                event_type="VEHICLE_EXIT",
                event_time=datetime.fromtimestamp(now_ts, tz=timezone.utc),
                vehicle_type=passage.vehicle_type,
                plate_text=passage.plate_text or None,
                direction=passage.direction if passage.direction != "UNKNOWN" else None,
                idempotency_key=f"{passage.id}:VEHICLE_EXIT",
                metadata=ev,
            )
            self.db_worker.enqueue_business_event(ev_dto, is_critical=True)
        self._active_passages.clear()
        self._last_people_count = None
        self._last_camera_id = None
        self._last_saved_count = None
        self._candidate_count = None

    def stop(self) -> None:
        """Cleanly terminate background worker, draining any queued items."""
        self.reset()
        if hasattr(self, "db_worker") and self.db_worker:
            self.db_worker.stop(timeout=3.0)


# Global singleton instance
event_manager = EventManager()
