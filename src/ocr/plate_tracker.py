"""Vehicle License Plate Tracking, Lifecycle Management, and Cadence Control.

Features:
- Track-level BestPlateState persistence (keeps best plate crop and text per track).
- Adaptive Cadence: Never OCRs every frame; evaluates every N=10 frames or on >20% bbox growth.
- Once a high-confidence plate is recognized (conf >= 0.70), slows evaluation to every 60 frames.
- Rejection safety: Worse or low-confidence candidates do not overwrite established best plate.
- TTL Expiration and thread-safe camera reset.
- Async OCR Worker: EasyOCR runs in a bounded daemon thread — main pipeline thread is never
  blocked by OCR inference. Results are written back to PlateTrackState asynchronously.
  Each track holds at most one pending OCR job (latest-job semantics).
"""

from dataclasses import dataclass
import logging
import queue
import threading
from typing import Any, NamedTuple, Sequence

import cv2
import numpy as np

import config
from src.ocr.plate_reader import LicensePlateReader, plate_reader

logger = logging.getLogger("datt.ocr.plate_tracker")

CADENCE_UNRECOGNIZED_FRAMES = 10
CADENCE_RECOGNIZED_FRAMES = 60
EXPIRATION_TTL_FRAMES = 60

# Bounded worker queue: max pending OCR jobs across all tracks.
_OCR_QUEUE_MAXSIZE = 8


@dataclass
class PlateTrackState:
    """Stores the best license plate representation and state for a vehicle track."""
    track_id: int
    vehicle_class: str = "vehicle"
    plate_text: str = ""
    confidence: float = 0.0
    plate_bbox_native: tuple[int, int, int, int] | None = None
    plate_crop: np.ndarray | None = None
    plate_quality: float = 0.0
    frame_id: int = -1
    last_eval_frame: int = -999
    last_bbox_area: float = 0.0
    eval_count: int = 0
    status: str = "SEARCHING"  # "SEARCHING", "RECOGNIZED"
    plate_history: list[Any] = None  # type: ignore  # stores past candidates for multi-frame voting
    vote_scores: dict[str, float] = None  # type: ignore

    def __post_init__(self) -> None:
        if self.plate_history is None:
            self.plate_history = []
        if self.vote_scores is None:
            self.vote_scores = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "track_id": self.track_id,
            "vehicle_class": self.vehicle_class,
            "plate_text": self.plate_text,
            "confidence": self.confidence,
            "has_plate": bool(self.plate_text),
            "status": self.status,
            "frame_id": self.frame_id,
        }


class _OcrJob(NamedTuple):
    """Immutable OCR job submitted to the async worker."""
    track_id: int
    frame_id: int
    vehicle_crop: np.ndarray
    native_vehicle_bbox: tuple[int, int, int, int]
    vehicle_class: str
    eval_count: int


class _OcrWorker:
    """Bounded daemon thread that drains the OCR job queue.

    Design:
    - Single thread — EasyOCR is not thread-safe; one thread prevents contention.
    - Bounded queue (maxsize=_OCR_QUEUE_MAXSIZE): if full, oldest job is discarded.
    - Latest-job semantics per track: stale jobs are skipped on dequeue.
    - Results written directly into VehiclePlateManager._plate_states under its lock.
    """

    def __init__(self, manager: "VehiclePlateManager") -> None:
        self._manager = manager
        self._queue: queue.Queue[_OcrJob | None] = queue.Queue(maxsize=_OCR_QUEUE_MAXSIZE)
        # track_id -> latest enqueued frame_id (for stale-skip)
        self._pending_frame: dict[int, int] = {}
        self._lock = threading.Lock()
        self._last_ocr_worker_ms: float = 0.0
        self._thread = threading.Thread(
            target=self._run,
            name="OcrWorkerThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("[OCR_WORKER] Async OCR worker started (queue_maxsize=%d)", _OCR_QUEUE_MAXSIZE)

    @property
    def last_ocr_worker_ms(self) -> float:
        return self._last_ocr_worker_ms

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def enqueue(self, job: _OcrJob) -> None:
        """Submit an OCR job. If the queue is full, drop the oldest item first."""
        with self._lock:
            self._pending_frame[job.track_id] = job.frame_id

        try:
            self._queue.put_nowait(job)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                pass

    def stop(self) -> None:
        """Signal the worker thread to stop."""
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=2.0)

    def clear(self) -> None:
        """Drain the queue (called on camera reset)."""
        with self._lock:
            self._pending_frame.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _run(self) -> None:
        """Worker loop: dequeue jobs and run EasyOCR synchronously."""
        import time as _t
        while True:
            try:
                job = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if job is None:
                break

            # Stale-job check: skip if a newer job for this track was enqueued
            with self._lock:
                latest_frame = self._pending_frame.get(job.track_id, job.frame_id)

            if latest_frame > job.frame_id:
                logger.debug(
                    "[OCR_WORKER] Skipping stale job track_id=%d job_frame=%d latest_frame=%d",
                    job.track_id, job.frame_id, latest_frame,
                )
                continue

            t0 = _t.perf_counter()
            try:
                cand = self._manager.reader.extract_license_plate(
                    vehicle_crop=job.vehicle_crop,
                    native_vehicle_bbox=job.native_vehicle_bbox,
                    track_id=job.track_id,
                    frame_id=job.frame_id,
                )
            except Exception as exc:
                logger.warning(
                    "[OCR_WORKER] OCR failed track_id=%d frame_id=%d: %s",
                    job.track_id, job.frame_id, exc,
                )
                cand = None
            self._last_ocr_worker_ms = (_t.perf_counter() - t0) * 1000

            self._manager._apply_ocr_result(job, cand)


class VehiclePlateManager:
    """Manages license plate detection, OCR, and BestPlate retention per active vehicle track.

    The main pipeline thread calls process_vehicle_tracks() which:
    1. Updates cadence / TTL state (fast, in-memory).
    2. Enqueues OCR jobs for eligible tracks (non-blocking).
    3. Returns current (possibly cached) PlateTrackState dict immediately.

    EasyOCR inference runs in a single daemon OcrWorker thread.
    """

    def __init__(
        self,
        reader: LicensePlateReader | None = None,
        eval_interval: int = CADENCE_UNRECOGNIZED_FRAMES,
        ttl_frames: int = EXPIRATION_TTL_FRAMES,
        async_worker: bool = False,
    ) -> None:
        self.reader = reader or plate_reader
        self.eval_interval = eval_interval
        self.ttl_frames = ttl_frames
        self.async_worker = async_worker

        self._lock = threading.RLock()
        self._plate_states: dict[int, PlateTrackState] = {}
        self._track_last_seen: dict[int, int] = {}

        self._worker: _OcrWorker | None = None
        self._worker_lock = threading.Lock()

    @property
    def last_ocr_worker_ms(self) -> float:
        if self._worker is not None:
            return self._worker.last_ocr_worker_ms
        return 0.0

    @property
    def ocr_queue_size(self) -> int:
        if self._worker is not None:
            return self._worker.queue_size
        return 0

    def _get_worker(self) -> _OcrWorker:
        if self._worker is None:
            with self._worker_lock:
                if self._worker is None:
                    self._worker = _OcrWorker(self)
        return self._worker

    def _apply_ocr_result(self, job: _OcrJob, cand: Any) -> None:
        """Write OCR result from worker thread into plate state with multi-frame voting (thread-safe)."""
        with self._lock:
            state = self._plate_states.get(job.track_id)
            if state is None:
                return

            if cand is not None and cand.plate_text:
                # 1. Multi-frame candidate voting
                state.plate_history.append(cand)
                if len(state.plate_history) > 10:
                    state.plate_history.pop(0)

                weight = float(cand.confidence) * (float(cand.quality_score) / 100.0)
                state.vote_scores[cand.plate_text] = state.vote_scores.get(cand.plate_text, 0.0) + weight
                winner_text = max(state.vote_scores, key=state.vote_scores.get)

                logger.info(
                    "[PLATE_VOTING] track_id=%d candidate='%s'(conf=%.2f,q=%.1f) vote_scores=%s WINNER='%s'",
                    job.track_id, cand.plate_text, cand.confidence, cand.quality_score,
                    {k: round(v, 2) for k, v in state.vote_scores.items()}, winner_text,
                )

                is_better = False
                better_reason = ""
                if not state.plate_text:
                    is_better = True
                    better_reason = "first_plate"
                elif cand.quality_score > state.plate_quality:
                    is_better = True
                    better_reason = f"higher_quality({cand.quality_score:.1f}>{state.plate_quality:.1f})"
                elif cand.confidence > state.confidence + 0.08:
                    is_better = True
                    better_reason = f"higher_conf({cand.confidence:.2f}>{state.confidence:.2f})"
                else:
                    better_reason = (
                        f"voting_update(winner='{winner_text}', q={cand.quality_score:.1f}<={state.plate_quality:.1f})"
                    )

                state.plate_text = winner_text
                state.status = "RECOGNIZED"
                state.confidence = max(state.confidence, cand.confidence)

                if is_better:
                    state.plate_bbox_native = cand.bbox_native
                    state.plate_crop = cand.raw_crop
                    state.plate_quality = cand.quality_score
                    state.frame_id = job.frame_id
                    logger.info(
                        "[PLATE_TRACK] Track %s-%d f=%d NEW BEST PLATE: '%s' conf=%.2f quality=%.1f reason=%s",
                        job.vehicle_class.upper(), job.track_id, job.frame_id,
                        state.plate_text, state.confidence, state.plate_quality, better_reason,
                    )
            else:
                logger.info(
                    "[PLATE_STATE] track_id=%d frame_id=%d status=%s current_plate='%s'"
                    "(conf=%.2f) cand=None",
                    job.track_id, job.frame_id, state.status,
                    state.plate_text, state.confidence,
                )


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_plate_state(self, track_id: int) -> PlateTrackState | None:
        """Retrieve PlateTrackState for a specific vehicle track."""
        with self._lock:
            return self._plate_states.get(track_id)

    def get_all_plate_states(self) -> dict[int, PlateTrackState]:
        """Retrieve copy of all active plate states."""
        with self._lock:
            return dict(self._plate_states)

    def process_vehicle_tracks(
        self,
        frame: np.ndarray,
        car_tracks: Any = None,
        frame_id: int = 0,
        vehicle_tracks: Any = None,
    ) -> dict[int, PlateTrackState]:
        """Evaluate active vehicle tracks for license plate detection & OCR.

        Non-blocking: enqueues OCR jobs to the async worker and returns
        the current (possibly cached) PlateTrackState dict immediately.

        Args:
            frame: Native unresized BGR frame (H, W, 3).
            car_tracks: Detections/Tracks from ByteTrack (legacy alias).
            frame_id: Monotonically increasing sequence frame counter.
            vehicle_tracks: Unified tracked vehicle detections (car, truck, bus, motorcycle).

        Returns:
            dict[int, PlateTrackState]: Active vehicle tracks with cached plate state.
        """
        v_tracks = vehicle_tracks if vehicle_tracks is not None else car_tracks
        if frame is None or v_tracks is None:
            return {}

        xyxy = getattr(v_tracks, "xyxy", None)
        tracker_id = getattr(v_tracks, "tracker_id", None)
        class_id = getattr(v_tracks, "class_id", None)
        confidence = getattr(v_tracks, "confidence", None)

        h, w = frame.shape[:2]
        active_results: dict[int, PlateTrackState] = {}

        with self._lock:
            # 1. Update last seen frame & purge expired tracks
            if tracker_id is not None:
                for tid in tracker_id:
                    if tid is not None:
                        self._track_last_seen[int(tid)] = frame_id

            expired = [
                tid for tid, last_seen in self._track_last_seen.items()
                if (frame_id - last_seen) > self.ttl_frames
            ]
            for tid in expired:
                self._track_last_seen.pop(tid, None)
                self._plate_states.pop(tid, None)

            if xyxy is None or tracker_id is None or len(xyxy) == 0:
                return {}

            # 2. Process each detected vehicle track (cadence check — no blocking OCR here)
            for i, box in enumerate(xyxy):
                tid = tracker_id[i] if i < len(tracker_id) else None
                if tid is None:
                    continue
                tid_int = int(tid)

                vx1, vy1, vx2, vy2 = [int(v) for v in box]
                vx1 = max(0, min(vx1, w - 1))
                vy1 = max(0, min(vy1, h - 1))
                vx2 = max(0, min(vx2, w - 1))
                vy2 = max(0, min(vy2, h - 1))

                vw = vx2 - vx1
                vh = vy2 - vy1
                if vw < 30 or vh < 30:
                    continue
                bbox_area = float(vw * vh)

                cid = int(class_id[i]) if class_id is not None and i < len(class_id) else 2
                cname = getattr(config, "VEHICLE_CLASSES", {}).get(cid, "vehicle")
                conf_val = float(confidence[i]) if confidence is not None and i < len(confidence) else 0.0

                logger.info(
                    "[VEHICLE_DET] class=%s conf=%.2f bbox=[%d, %d, %d, %d] track_id=%d"
                    " size=%dx%d frame_res=%dx%d frame_id=%d",
                    cname, conf_val, vx1, vy1, vx2, vy2, tid_int, vw, vh, w, h, frame_id,
                )

                state = self._plate_states.get(tid_int)
                if state is None:
                    state = PlateTrackState(track_id=tid_int, vehicle_class=cname, last_eval_frame=-999)
                    self._plate_states[tid_int] = state
                else:
                    state.vehicle_class = cname

                eligible_classes = getattr(config, "PLATE_ELIGIBLE_CLASSES", [2, 5, 7])
                if cid not in eligible_classes:
                    logger.info(
                        "[PLATE_ATTEMPT] track_id=%d class=%s frame_id=%d attempt=SKIP reason=not_eligible",
                        tid_int, cname, frame_id,
                    )
                    active_results[tid_int] = state
                    continue

                growth_due = False
                if state.last_bbox_area > 0 and (frame_id - state.last_eval_frame) >= 2:
                    ratio = (bbox_area - state.last_bbox_area) / state.last_bbox_area
                    if ratio > 0.20:
                        growth_due = True

                cadence_threshold = (
                    CADENCE_RECOGNIZED_FRAMES
                    if (state.status == "RECOGNIZED" and state.confidence >= 0.70)
                    else self.eval_interval
                )
                cadence_gap = frame_id - state.last_eval_frame if state.last_eval_frame >= 0 else -1
                cadence_due = (cadence_gap >= cadence_threshold) if cadence_gap >= 0 else False
                needs_eval = cadence_due or growth_due or (state.last_eval_frame < 0)

                reason = (
                    "first_eval" if state.last_eval_frame < 0
                    else ("growth" if growth_due
                          else ("cadence_interval" if cadence_due else "wait_cadence"))
                )

                logger.info(
                    "[PLATE_ATTEMPT] track_id=%d class=%s frame_id=%d cadence_gap=%d attempt=%s"
                    " reason=%s v_size=%dx%d status=%s",
                    tid_int, cname, frame_id, cadence_gap,
                    "ENQUEUE" if needs_eval else "SKIP",
                    reason, vw, vh, state.status,
                )

                if needs_eval:
                    # Update cadence counters before OCR (prevents re-enqueue next frame)
                    state.last_eval_frame = frame_id
                    state.last_bbox_area = bbox_area
                    state.eval_count += 1

                    # Copy crop so frame buffer can be reused immediately
                    vehicle_crop = frame[vy1:vy2, vx1:vx2].copy()

                    job = _OcrJob(
                        track_id=tid_int,
                        frame_id=frame_id,
                        vehicle_crop=vehicle_crop,
                        native_vehicle_bbox=(vx1, vy1, vx2, vy2),
                        vehicle_class=cname,
                        eval_count=state.eval_count,
                    )
                    if self.async_worker:
                        self._get_worker().enqueue(job)
                    else:
                        cand = self.reader.extract_license_plate(
                            vehicle_crop=vehicle_crop,
                            native_vehicle_bbox=(vx1, vy1, vx2, vy2),
                            track_id=tid_int,
                            frame_id=frame_id,
                        )
                        self._apply_ocr_result(job, cand)

                active_results[tid_int] = state

        return active_results

    def reset_tracks(self) -> None:
        """Clear all vehicle track associations (called on camera/source switch)."""
        worker = self._worker
        if worker is not None:
            worker.clear()
        with self._lock:
            self._plate_states.clear()
            self._track_last_seen.clear()
            logger.info("[PLATE_TRACKER] Reset all vehicle license plate track associations.")


# Global singleton instance
vehicle_plate_manager = VehiclePlateManager(async_worker=True)

