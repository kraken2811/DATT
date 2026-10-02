"""Per-camera meaningful events; normal detections remain transient in RAM."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any
from uuid import UUID, uuid4

import numpy as np

from src.events.policy import ThresholdEpisodes, MEANINGFUL_EVENTS
from src.events.db_worker import DatabaseWorker
from src.events.event_dto import BusinessEventDTO, FaceEventDTO, VehiclePassageDTO
from src.events.event_storage import EventStorage, event_storage
from src.runtime.shared_state import SharedRuntimeState, shared_state
from src.utils.logger import logger

EVENT_REPORT_INTERVAL = 300.0
SIGNIFICANT_CHANGE = 5
STABLE_TIME_SECONDS = 5.0
SNAPSHOT_INTERVAL_SECONDS = 60.0

VALID_BUSINESS_EVENTS = MEANINGFUL_EVENTS

CLASS_MAP = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


def _parse_uuid(val: Any) -> UUID | None:
    if val is None:
        return None
    if isinstance(val, UUID):
        return val
    try:
        return UUID(str(val))
    except Exception:
        return None


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
    video_source_id: UUID | None = None
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
    best_vehicle_crop_quality: float = -1.0
    best_vehicle_frame_id: int = -1
    last_crop_frame_id: int = -999
    plate_state: Any = None
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
            video_source_id=self.video_source_id,
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

        self._active_passages: dict[tuple[str, int], VehiclePassage] = {}
        self._episodes = ThresholdEpisodes()
        self._emitted_face_tracks: set[str] = set()
        self.last_event_build_ms: float = 0.0
        self.last_db_work_ms: float = 0.0

        # Dedicated PostgreSQL background persistence worker (zero realtime I/O)
        self.db_worker = db_worker or DatabaseWorker()

    def process_frame(self, camera_id, people_count, annotated_frame=None, video_source_id=None, location=None):
        """Persist only a continuously sustained crowd threshold episode."""
        start = time.perf_counter()
        event = self._episodes.people(camera_id, people_count, time.monotonic(), time.time(), location)
        self.last_db_work_ms = 0.0
        if event:
            self._persist_threshold(camera_id, event, annotated_frame, video_source_id)
        self.last_event_build_ms = (time.perf_counter() - start) * 1000.0
        return event

    def _persist_threshold(self, camera_id, event, frame, video_source_id):
        start = time.perf_counter()
        event['camera_id'] = camera_id
        event['type'] = event['event_type']
        dto = BusinessEventDTO(id=uuid4(), passage_id=None, camera_id=camera_id,
            video_source_id=_parse_uuid(video_source_id), event_type=event['event_type'],
            event_time=datetime.fromtimestamp(event['timestamp'], timezone.utc),
            idempotency_key=f"{event['event_type']}:{camera_id}:{event['episode']}", metadata=event)
        self.db_worker.enqueue_business_event(dto, snapshot=frame, is_critical=True)
        self.last_db_work_ms = (time.perf_counter() - start) * 1000.0


    def process_vehicle_frame(self, camera_id, vehicle_tracks, plate_results=None,
                              in_zone_ids=None, zone_id=None, frame=None, video_source_id=None, frame_id=0):
        """Keep normal tracks in RAM; finalize through the existing watchlist gate."""
        start = time.perf_counter()
        now = time.time()
        emitted = []
        ids = getattr(vehicle_tracks, 'tracker_id', None)
        boxes = getattr(vehicle_tracks, 'xyxy', None)
        classes = getattr(vehicle_tracks, 'class_id', None)
        confidences = getattr(vehicle_tracks, 'confidence', None)
        vehicle_count = 0
        if ids is not None and boxes is not None:
            for i, tid in enumerate(ids):
                if tid is None:
                    continue
                tid = int(tid)
                cid = int(classes[i]) if classes is not None else 2
                if cid in (2, 3) and (in_zone_ids is None or tid in in_zone_ids):
                    vehicle_count += 1
                key = (camera_id, tid)
                passage = self._active_passages.get(key)
                current_state = (plate_results or {}).get(tid)
                if (passage is not None and passage.plate_state is not None and current_state is not None
                        and getattr(passage.plate_state, 'generation', None) != getattr(current_state, 'generation', None)):
                    self._finalize_vehicle(passage)
                    del self._active_passages[key]
                    passage = None
                if passage is None:
                    passage = VehiclePassage(camera_id=camera_id, track_id=tid,
                        vehicle_type=CLASS_MAP.get(cid, 'vehicle'), first_seen=now, last_seen=now,
                        video_source_id=_parse_uuid(video_source_id), zone_id=zone_id,
                        vehicle_type_confidence=float(confidences[i]) if confidences is not None else None)
                    self._active_passages[key] = passage
                passage.last_seen = now
                passage.duration = max(0.0, now-passage.first_seen)
                box = boxes[i]
                area = float((box[2]-box[0])*(box[3]-box[1]))
                if frame is not None and (passage.best_vehicle_image is None or frame_id-passage.last_crop_frame_id >= 10):
                    passage.last_crop_frame_id = frame_id
                    x1,y1,x2,y2 = [max(0,int(v)) for v in box[:4]]
                    h,w = frame.shape[:2]; x2=min(w,x2); y2=min(h,y2)
                    if x2-x1 >= 30 and y2-y1 >= 30:
                        from src.ocr.plate_tracker import compute_ocr_job_quality
                        crop = frame[y1:y2,x1:x2]
                        quality = compute_ocr_job_quality(crop, (x1,y1,x2,y2), (w,h))
                        if quality > passage.best_vehicle_crop_quality:
                            passage.best_vehicle_area = area
                            passage.best_vehicle_crop_quality = quality
                            passage.best_vehicle_frame_id = frame_id
                            passage.best_vehicle_image = crop.copy()
                state = (plate_results or {}).get(tid)
                if state is not None:
                    passage.plate_state = state  # Collect a late worker result at finalization.
                self._collect_confirmed_plate(passage)
        threshold = self._episodes.congestion(camera_id, vehicle_count, time.monotonic(), now, zone_id)
        if threshold:
            self._persist_threshold(camera_id, threshold, frame, video_source_id)
            emitted.append(threshold)
        for key, passage in list(self._active_passages.items()):
            if key[0] == camera_id and now-passage.last_seen > 3.0:
                self._finalize_vehicle(passage)
                del self._active_passages[key]
        self.last_event_build_ms = (time.perf_counter()-start)*1000.0
        return emitted

    @staticmethod
    def _collect_confirmed_plate(passage):
        state = passage.plate_state
        if state is None or getattr(state, 'status', '') != 'CONFIRMED':
            return
        plate = getattr(state, 'confirmed_plate', '')
        if not plate:
            return
        passage.plate_text = plate
        passage.plate_status = 'CONFIRMED'
        passage.plate_confidence = state.confidence
        passage.best_plate_image = state.plate_crop
        passage.confirmed_plate = plate
        passage.plate_confirmed_emitted = True

    def _finalize_vehicle(self, passage):
        passage.exited = True
        passage.duration = max(0.0, passage.last_seen-passage.first_seen)
        self._collect_confirmed_plate(passage)
        if not passage.confirmed_plate:
            return
        self.db_worker.enqueue_passage(passage.to_dto(is_final=True),
            vehicle_crop=passage.best_vehicle_image, plate_crop=passage.best_plate_image, is_critical=True)


    def process_face_matches(
        self,
        camera_id: str,
        target_matches: dict[int, Any] | None,
        track_states: dict[int, Any] | None = None,
        tracks: Any = None,
        frame: np.ndarray | None = None,
        video_source_id: UUID | str | None = None,
        frame_id: int = 0,
    ) -> list[dict[str, Any]]:
        """Process target matcher face recognition results and emit FaceEvents asynchronously."""
        if not target_matches:
            return []

        emitted: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        v_src_uuid = _parse_uuid(video_source_id)

        track_boxes = {}
        if tracks is not None:
            t_ids = getattr(tracks, "tracker_id", None)
            xyxy = getattr(tracks, "xyxy", None)
            if t_ids is not None and xyxy is not None:
                for idx, tid_val in enumerate(t_ids):
                    if tid_val is not None:
                        track_boxes[int(tid_val)] = xyxy[idx]

        for tid, match in target_matches.items():
            if match is None:
                continue
            decision = getattr(match, "decision", "FACE_MATCH")
            match_type = getattr(match, "match_type", "")
            if decision != "FACE_MATCH" and match_type not in ("FACE_MATCH", "FULL_MATCH"):
                continue

            target_id_str = getattr(match, "target_id", "")
            dedup_key = f"{camera_id}:{tid}:{target_id_str}"
            if dedup_key in self._emitted_face_tracks:
                continue
            self._emitted_face_tracks.add(dedup_key)

            target_uuid = _parse_uuid(target_id_str)
            target_name = getattr(match, "target_name", "")
            score = float(getattr(match, "score", 0.0))

            face_crop = None
            if frame is not None:
                box = track_boxes.get(int(tid))
                if box is not None:
                    bx1, by1, bx2, by2 = [max(0, int(v)) for v in box[:4]]
                    h, w = frame.shape[:2]
                    bx2, by2 = min(w, bx2), min(h, by2)
                    head_h = max(20, int((by2 - by1) * 0.55))
                    face_y2 = min(h, by1 + head_h)
                    if (bx2 - bx1) >= 20 and (face_y2 - by1) >= 20:
                        face_crop = frame[by1:face_y2, bx1:bx2].copy()

            dto = FaceEventDTO(
                id=uuid4(),
                track_id=int(tid),
                camera_id=camera_id,
                target_id=target_uuid,
                target_name=target_name,
                similarity=score,
                decision=decision,
                video_source_id=v_src_uuid,
                frame_id=frame_id,
                created_at=now,
            )
            self.db_worker.enqueue_face_event(dto, face_crop=face_crop, is_critical=True)
            ev = {
                "type": "FACE_WATCHLIST_MATCH",
                "id": str(dto.id),
                "track_id": int(tid),
                "target_id": str(target_uuid) if target_uuid else target_id_str,
                "target_name": target_name,
                "similarity": score,
                "decision": decision,
                "camera_id": camera_id,
                "video_source_id": str(v_src_uuid) if v_src_uuid else None,
                "timestamp": now.timestamp(),
            }
            emitted.append(ev)

        return emitted

    def reset(self):
        """Finalize pending vehicle sessions and end continuity on a source reset."""
        for passage in self._active_passages.values():
            self._finalize_vehicle(passage)
        self._active_passages.clear()
        self._episodes.reset()
        self._emitted_face_tracks.clear()



    def stop(self) -> None:
        """Cleanly terminate background worker, draining any queued items."""
        self.reset()
        if hasattr(self, "db_worker") and self.db_worker:
            self.db_worker.stop(timeout=3.0)


# Global singleton instance
event_manager = EventManager()
