"""Dedicated asynchronous database worker for PostgreSQL persistence.

Enforces zero database / disk I/O in the realtime AI frame loop.
Maintains bounded queue, coalescing, retry buffer, and transaction boundaries.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any
from uuid import UUID

import cv2
import numpy as np

from src.db.database import Database
from src.db.repositories import (
    BusinessEventRepository,
    CameraRepository,
    DetectionEventRepository,
    FaceEventRepository,
    PlateEventRepository,
    VehicleEventRepository,
    VehiclePassageRepository,
)
from src.events.event_dto import BusinessEventDTO, FaceEventDTO, VehiclePassageDTO
from src.recognition.color_extractor import extract_vehicle_color

logger = logging.getLogger("datt.events.db_worker")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "events"


class DatabaseWorker:
    """Dedicated background worker that persists DTOs to PostgreSQL."""

    def __init__(
        self,
        db_url: str | None = None,
        max_queue_size: int = 1000,
        batch_size: int = 50,
        snapshot_dir: Path | str | None = None,
    ) -> None:
        self.db = Database(url=db_url)
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else DEFAULT_SNAPSHOT_DIR
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        self._task_queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._retry_buffer: list[tuple[str, Any, Any]] = []
        self._stop_event = threading.Event()

        # Operational metrics
        self.queue_dropped: int = 0
        self.queue_coalesced: int = 0
        self.db_failures: int = 0
        self.retry_count: int = 0
        self.last_write_ms: float = 0.0
        self.write_latencies: list[float] = []
        self.enqueue_latencies: list[float] = []

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="DatabasePersistenceWorker",
            daemon=True,
        )
        self._worker_thread.start()

    @property
    def queue_depth(self) -> int:
        return self._task_queue.qsize() + len(self._retry_buffer)

    def enqueue_passage(
        self,
        dto: VehiclePassageDTO,
        vehicle_crop: np.ndarray | None = None,
        plate_crop: np.ndarray | None = None,
        is_critical: bool = False,
    ) -> bool:
        """Enqueue a VehiclePassageDTO non-blockingly."""
        t0 = time.perf_counter()
        task = ("PASSAGE", dto, (vehicle_crop, plate_crop))
        success = self._put_task(task, is_critical=is_critical or dto.is_final)
        self.enqueue_latencies.append((time.perf_counter() - t0) * 1000.0)
        return success

    def enqueue_business_event(
        self,
        dto: BusinessEventDTO,
        is_critical: bool = True,
    ) -> bool:
        """Enqueue a BusinessEventDTO non-blockingly."""
        t0 = time.perf_counter()
        task = ("BUSINESS_EVENT", dto, None)
        success = self._put_task(task, is_critical=is_critical)
        self.enqueue_latencies.append((time.perf_counter() - t0) * 1000.0)
        return success

    def enqueue_face_event(
        self,
        dto: FaceEventDTO,
        face_crop: np.ndarray | None = None,
        is_critical: bool = True,
    ) -> bool:
        """Enqueue a FaceEventDTO non-blockingly."""
        t0 = time.perf_counter()
        task = ("FACE_EVENT", dto, face_crop)
        success = self._put_task(task, is_critical=is_critical)
        self.enqueue_latencies.append((time.perf_counter() - t0) * 1000.0)
        return success


    def _put_task(self, task: tuple[str, Any, Any], is_critical: bool) -> bool:
        try:
            self._task_queue.put_nowait(task)
            return True
        except queue.Full:
            if is_critical:
                # Evict an existing non-critical task to ensure critical transition is preserved
                try:
                    evicted = self._task_queue.get_nowait()
                    self._task_queue.task_done()
                    self.queue_dropped += 1
                    logger.warning("[DBWorker] Queue full: evicted non-critical task for critical item %s", task[0])
                except queue.Empty:
                    pass
                try:
                    self._task_queue.put_nowait(task)
                    return True
                except queue.Full:
                    self.queue_dropped += 1
                    logger.error("[DBWorker] Queue full: could not enqueue critical item %s", task[0])
                    return False
            else:
                self.queue_dropped += 1
                logger.warning("[DBWorker] Persistence queue full, dropping low-priority task: %s", task[0])
                return False

    def _worker_loop(self) -> None:
        """Dedicated worker loop owning its DB session/transaction lifecycle."""
        backoff_sec = 0.1
        while not (self._stop_event.is_set() and self._task_queue.empty() and not self._retry_buffer):
            batch: list[tuple[str, Any, Any]] = []

            # 1. Take from retry buffer first
            if self._retry_buffer:
                take_n = min(self.batch_size, len(self._retry_buffer))
                batch.extend(self._retry_buffer[:take_n])
                self._retry_buffer = self._retry_buffer[take_n:]

            # 2. Pull from queue up to batch_size
            while len(batch) < self.batch_size:
                timeout = 0.05 if batch else 0.2
                try:
                    task = self._task_queue.get(timeout=timeout)
                    batch.append(task)
                except queue.Empty:
                    break

            if not batch:
                if self._stop_event.is_set():
                    break
                continue

            # 3. Process the batch in a dedicated transaction
            success = self._persist_batch(batch)
            if success:
                backoff_sec = 0.1
                for _ in batch:
                    # mark tasks as done
                    try:
                        self._task_queue.task_done()
                    except ValueError:
                        pass
            else:
                # Retain in retry buffer on failure
                self.retry_count += 1
                self.db_failures += 1
                # Prepend failed batch to retry buffer (bounded to max_queue_size)
                self._retry_buffer = (batch + self._retry_buffer)[: self.max_queue_size]
                time.sleep(backoff_sec)
                backoff_sec = min(2.0, backoff_sec * 1.5)

    def _persist_batch(self, batch: list[tuple[str, Any, Any]]) -> bool:
        t_w0 = time.perf_counter()
        # Coalesce passages by session_key: keep only latest state
        passages_by_key: dict[str, tuple[VehiclePassageDTO, Any]] = {}
        events: list[BusinessEventDTO] = []
        face_events_list: list[tuple[FaceEventDTO, Any]] = []

        for task_type, item, aux in batch:
            if task_type == "PASSAGE":
                dto: VehiclePassageDTO = item
                if dto.session_key in passages_by_key:
                    self.queue_coalesced += 1
                passages_by_key[dto.session_key] = (dto, aux)
            elif task_type == "BUSINESS_EVENT":
                events.append(item)
            elif task_type == "FACE_EVENT":
                face_events_list.append((item, aux))


        try:
            with self.db.transaction() as session:
                passage_repo = VehiclePassageRepository(session)
                event_repo = BusinessEventRepository(session)

                # Persist passages
                for session_key, (dto, crops) in passages_by_key.items():
                    veh_crop, plt_crop = crops if crops else (None, None)
                    best_veh_path = dto.best_vehicle_image_path
                    best_plt_path = dto.best_plate_image_path

                    # Asynchronously save evidence images if provided and not yet written
                    ts_compact = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
                    if veh_crop is not None and getattr(veh_crop, "size", 0) > 0 and not best_veh_path:
                        fn = f"veh_{ts_compact}_{dto.camera_id}_t{dto.track_id}.jpg"
                        dest = self.snapshot_dir / fn
                        try:
                            cv2.imwrite(str(dest), veh_crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
                            try:
                                best_veh_path = str(dest.relative_to(PROJECT_ROOT)).replace("\\", "/")
                            except Exception:
                                best_veh_path = f"data/events/{fn}"
                        except Exception as e:
                            logger.warning("[DBWorker] Failed to save vehicle crop: %s", e)

                    if plt_crop is not None and getattr(plt_crop, "size", 0) > 0 and not best_plt_path:
                        fn = f"plate_{ts_compact}_{dto.camera_id}_t{dto.track_id}.jpg"
                        dest = self.snapshot_dir / fn
                        try:
                            cv2.imwrite(str(dest), plt_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                            try:
                                best_plt_path = str(dest.relative_to(PROJECT_ROOT)).replace("\\", "/")
                            except Exception:
                                best_plt_path = f"data/events/{fn}"
                        except Exception as e:
                            logger.warning("[DBWorker] Failed to save plate crop: %s", e)

                    # Determine vehicle color
                    v_color = dto.vehicle_color
                    if not v_color and veh_crop is not None and getattr(veh_crop, "size", 0) > 0:
                        try:
                            v_color = extract_vehicle_color(veh_crop)
                        except Exception:
                            v_color = "other/unknown"

                    passage_repo.upsert_passage(
                        session_key=dto.session_key,
                        id=dto.id,
                        camera_id=dto.camera_id,
                        video_source_id=dto.video_source_id,
                        zone_id=dto.zone_id,
                        track_id=dto.track_id,
                        vehicle_type=dto.vehicle_type,
                        vehicle_color=v_color,
                        vehicle_type_confidence=dto.vehicle_type_confidence,
                        vehicle_color_confidence=dto.vehicle_color_confidence,
                        plate_text=dto.plate_text,
                        plate_status=dto.plate_status,
                        plate_confidence=dto.plate_confidence,
                        direction=dto.direction,
                        first_seen_at=dto.first_seen_at,
                        last_seen_at=dto.last_seen_at,
                        duration_ms=dto.duration_ms,
                        best_vehicle_image_path=best_veh_path,
                        best_plate_image_path=best_plt_path,
                        finalized_at=dto.finalized_at,
                    )

                    # When a vehicle track completes, persist ONE complete VehicleEvent (+ PlateEvent if plate recognized)
                    if dto.is_final:
                        veh_event_repo = VehicleEventRepository(session)
                        plate_event_repo = PlateEventRepository(session)
                        det_event_repo = DetectionEventRepository(session)
                        cam_repo = CameraRepository(session)

                        existing_ve = veh_event_repo.get(dto.id)
                        if existing_ve is None:
                            det_id = None
                            try:
                                cam_uuid = None
                                try:
                                    cam_uuid = UUID(str(dto.camera_id))
                                except Exception:
                                    pass

                                if cam_uuid is not None:
                                    cam_rec = cam_repo.get(cam_uuid)
                                    if cam_rec is None:
                                        cam_rec = cam_repo.create(
                                            id=cam_uuid,
                                            name=str(dto.camera_id),
                                            source_type="live",
                                            source=str(dto.camera_id),
                                        )
                                    det_ev = det_event_repo.create(
                                        camera_id=cam_rec.id,
                                        video_source_id=dto.video_source_id,
                                        event_type="vehicle",
                                        frame_id=0,
                                        timestamp=dto.last_seen_at,
                                        track_id=dto.track_id,
                                        class_name=dto.vehicle_type,
                                        snapshot_path=best_veh_path,
                                    )
                                    det_id = det_ev.id
                            except Exception as det_err:
                                logger.debug("[DBWorker] Detection event creation optional: %s", det_err)

                            ve = veh_event_repo.create(
                                id=dto.id,
                                detection_event_id=det_id,
                                video_source_id=dto.video_source_id,
                                vehicle_class=dto.vehicle_type,
                                track_id=dto.track_id,
                                zone_id=dto.zone_id,
                                vehicle_color=v_color,
                                vehicle_image_path=best_veh_path,
                                first_seen=dto.first_seen_at,
                                last_seen=dto.last_seen_at,
                            )

                            if dto.plate_text or best_plt_path:
                                plate_event_repo.create(
                                    vehicle_event_id=ve.id,
                                    plate_text=dto.plate_text or "",
                                    confidence=dto.plate_confidence,
                                    plate_crop_path=best_plt_path,
                                    status=dto.plate_status or "confirmed",
                                    created_at=dto.last_seen_at,
                                )

                # Persist business events idempotently
                for ev_dto in events:
                    event_repo.insert_idempotent(
                        id=ev_dto.id,
                        passage_id=ev_dto.passage_id,
                        camera_id=ev_dto.camera_id,
                        video_source_id=ev_dto.video_source_id,
                        zone_id=ev_dto.zone_id,
                        track_id=ev_dto.track_id,
                        event_type=ev_dto.event_type,
                        event_time=ev_dto.event_time,
                        vehicle_type=ev_dto.vehicle_type,
                        plate_text=ev_dto.plate_text,
                        direction=ev_dto.direction,
                        idempotency_key=ev_dto.idempotency_key,
                        metadata=ev_dto.metadata,
                    )

                # Persist face recognition events
                if face_events_list:
                    face_repo = FaceEventRepository(session)
                    for f_dto, f_crop in face_events_list:
                        f_path = f_dto.face_crop_path
                        if f_crop is not None and getattr(f_crop, "size", 0) > 0 and not f_path:
                            ts_compact = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
                            fn = f"face_{ts_compact}_{f_dto.camera_id}_t{f_dto.track_id}.jpg"
                            dest = self.snapshot_dir / fn
                            try:
                                cv2.imwrite(str(dest), f_crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                                try:
                                    f_path = str(dest.relative_to(PROJECT_ROOT)).replace("\\", "/")
                                except Exception:
                                    f_path = f"data/events/{fn}"
                            except Exception as e:
                                logger.warning("[DBWorker] Failed to save face crop: %s", e)

                        face_repo.create(
                            id=f_dto.id,
                            target_id=f_dto.target_id,
                            video_source_id=f_dto.video_source_id,
                            track_id=f_dto.track_id,
                            frame_id=f_dto.frame_id,
                            similarity=f_dto.similarity,
                            decision=f_dto.decision,
                            face_crop_path=f_path,
                            created_at=f_dto.created_at,
                        )


            write_ms = (time.perf_counter() - t_w0) * 1000.0
            self.last_write_ms = write_ms
            self.write_latencies.append(write_ms)
            return True

        except Exception as exc:
            logger.error("[DBWorker] Persistence batch failed: %s", exc)
            return False

    def get_latency_stats(self) -> dict[str, float]:
        """Return p50, p95, p99 latencies for enqueue and worker writes."""
        def calc_percentiles(vals: list[float]) -> dict[str, float]:
            if not vals:
                return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
            sorted_v = sorted(vals)
            n = len(sorted_v)
            return {
                "p50": sorted_v[int(n * 0.50)],
                "p95": sorted_v[min(int(n * 0.95), n - 1)],
                "p99": sorted_v[min(int(n * 0.99), n - 1)],
                "max": sorted_v[-1],
            }

        return {
            "enqueue": calc_percentiles(self.enqueue_latencies),
            "db_write": calc_percentiles(self.write_latencies),
        }

    def stop(self, timeout: float = 5.0) -> None:
        """Clean shutdown: flush queue, commit transactions, close connections."""
        self._stop_event.set()
        t0 = time.time()
        while (not self._task_queue.empty() or self._retry_buffer) and (time.time() - t0 < timeout):
            time.sleep(0.05)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=max(0.5, timeout - (time.time() - t0)))
        self.db.dispose()
