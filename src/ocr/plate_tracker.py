"""Bounded asynchronous plate OCR with strict multi-frame track consensus.

Only exact normalized votes confirm an observed VN plate. Frame candidates remain
CHECKING until confidence, quality, agreement and distinct-frame thresholds pass.
"""

from dataclasses import dataclass
import logging
from collections import OrderedDict, Counter
from dataclasses import replace
import math
import time
import threading
from typing import Any, NamedTuple, Sequence

import cv2
import numpy as np

import config
from src.ocr.plate_reader import LicensePlateReader, plate_reader, normalize_plate_text, is_valid_plate_format

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
    status: str = "SEARCHING"  # SEARCHING -> CHECKING -> RECOGNIZED
    candidate_text: str = ""
    consensus_count: int = 0
    last_result_frame: int = -1
    generation: int = 0
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
            "candidate_text": self.candidate_text,
            "consensus_count": self.consensus_count,
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
    generation: int = 0


class _OcrWorker:
    """One latest pending crop per track; one running job; bounded global backlog."""
    def __init__(self, manager):
        self._manager = manager
        self._pending = OrderedDict()
        self._condition = threading.Condition()
        self._stopped = False
        self._last_ocr_worker_ms = 0.0
        self._thread = threading.Thread(target=self._run, name="OcrWorkerThread", daemon=True)
        self._thread.start()

    @property
    def last_ocr_worker_ms(self):
        return self._last_ocr_worker_ms

    @property
    def queue_size(self):
        with self._condition:
            return len(self._pending)

    def enqueue(self, job):
        with self._condition:
            if self._stopped:
                return
            if job.track_id not in self._pending and len(self._pending) >= _OCR_QUEUE_MAXSIZE:
                self._pending.popitem(last=False)
            self._pending[job.track_id] = job
            self._condition.notify()

    def discard(self, track_id):
        with self._condition:
            self._pending.pop(track_id, None)

    def clear(self):
        with self._condition:
            self._pending.clear()

    def stop(self):
        with self._condition:
            self._stopped = True
            self._pending.clear()
            self._condition.notify_all()
        self._thread.join(timeout=2.0)

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._stopped or self._pending)
                if self._stopped:
                    return
                _, job = self._pending.popitem(last=False)
            start = time.perf_counter()
            try:
                candidate = self._manager.reader.extract_license_plate(
                    vehicle_crop=job.vehicle_crop, native_vehicle_bbox=job.native_vehicle_bbox,
                    track_id=job.track_id, frame_id=job.frame_id)
            except Exception:
                logger.exception("OCR failed track=%s frame=%s", job.track_id, job.frame_id)
                candidate = None
            self._last_ocr_worker_ms = (time.perf_counter() - start) * 1000
            self._manager._apply_ocr_result(job, candidate)


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
        min_observations: int | None = None,
        min_confidence: float | None = None,
        min_quality: float | None = None,
        history_size: int | None = None,
        consensus_ratio: float | None = None,
        recheck_interval: int | None = None,
    ) -> None:
        self.reader = reader or plate_reader
        self.eval_interval = eval_interval
        self.ttl_frames = ttl_frames
        self.async_worker = async_worker
        self.min_observations = max(3, min_observations or getattr(config, "PLATE_MIN_OBSERVATIONS", 3))
        self.min_confidence = getattr(config, "PLATE_CONSENSUS_CONFIDENCE", 0.65) if min_confidence is None else min_confidence
        self.min_quality = getattr(config, "PLATE_CONSENSUS_QUALITY", 55.0) if min_quality is None else min_quality
        self.history_size = history_size or getattr(config, "PLATE_HISTORY_SIZE", 10)
        self.consensus_ratio = getattr(config, "PLATE_CONSENSUS_RATIO", 0.75) if consensus_ratio is None else consensus_ratio
        self.recheck_interval = recheck_interval or getattr(config, "PLATE_RECHECK_FRAMES", 180)
        if self.history_size < self.min_observations or not 0.5 < self.consensus_ratio <= 1:
            raise ValueError("history_size must cover minimum observations; ratio must exceed 0.5")
        self._generation = 0

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
        with self._lock:
            state = self._plate_states.get(job.track_id)
            if state is None or state.generation != job.generation or job.frame_id <= state.last_result_frame:
                return
            state.last_result_frame = job.frame_id
            if cand is None:
                return
            normalized = normalize_plate_text(cand.plate_text)
            raw = getattr(cand, "raw_text", "")
            if not isinstance(raw, str) or not raw:
                raw = cand.plate_text
            valid = is_valid_plate_format(raw) and is_valid_plate_format(normalized)
            eligible = (valid and math.isfinite(cand.confidence) and math.isfinite(cand.quality_score)
                        and cand.confidence >= self.min_confidence and cand.quality_score >= self.min_quality)
            state.plate_history.append({"frame_id": job.frame_id, "raw_text": raw,
                "normalized_text": normalized, "confidence": cand.confidence,
                "quality": cand.quality_score, "eligible": eligible})
            del state.plate_history[:-self.history_size]
            votes = Counter(item["normalized_text"] for item in state.plate_history if item["eligible"])
            state.vote_scores = dict(votes)
            if not votes:
                return
            winner, count = votes.most_common(1)[0]
            state.candidate_text = winner
            state.consensus_count = count
            if state.status != "RECOGNIZED":
                state.status = "CHECKING"
            # Exact normalized agreement is mandatory. Near strings are diagnostics only:
            # even a single differing registration digit could identify a different vehicle.
            near = [text for text in votes if text != winner and len(text) == len(winner)
                    and text[:3] == winner[:3] and sum(a != b for a, b in zip(text, winner)) == 1]
            confirmed = count >= self.min_observations and count / len(state.plate_history) >= self.consensus_ratio
            if confirmed and normalized == winner and eligible:
                changed = state.plate_text != winner
                state.plate_text = winner
                state.status = "RECOGNIZED"
                if changed or cand.quality_score >= state.plate_quality:
                    state.confidence = cand.confidence
                    state.plate_quality = cand.quality_score
                    state.plate_bbox_native = cand.bbox_native
                    state.plate_crop = cand.raw_crop
                    state.frame_id = job.frame_id
                if self._worker is not None:
                    self._worker.discard(job.track_id)
            logger.info("[PLATE_CONSENSUS] track=%s frame=%s raw=%r normalized=%s votes=%s near=%s status=%s confirmed=%s",
                job.track_id, job.frame_id, raw, normalized, dict(votes), near, state.status, state.plate_text)

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
            return {tid: replace(state, plate_history=list(state.plate_history), vote_scores=dict(state.vote_scores)) for tid, state in self._plate_states.items()}

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
                if self._worker is not None:
                    self._worker.discard(tid)

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
                    self._generation += 1
                    state = PlateTrackState(track_id=tid_int, vehicle_class=cname, last_eval_frame=-999, generation=self._generation)
                    self._plate_states[tid_int] = state
                else:
                    state.vehicle_class = cname

                eligible_classes = getattr(config, "PLATE_ELIGIBLE_CLASSES", [2, 3, 5, 7])
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
                    self.recheck_interval
                    if state.status == "RECOGNIZED"
                    else self.eval_interval
                )
                cadence_gap = frame_id - state.last_eval_frame if state.last_eval_frame >= 0 else -1
                cadence_due = (cadence_gap >= cadence_threshold) if cadence_gap >= 0 else False
                if state.status == "RECOGNIZED":
                    growth_due = False
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
                        generation=state.generation,
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

