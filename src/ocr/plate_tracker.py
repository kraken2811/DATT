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
    max_bbox_area: float = 0.0
    eval_count: int = 0
    status: str = "SEARCHING"  # SEARCHING -> PROVISIONAL -> CONFIRMED
    provisional_plate: str = ""
    provisional_confidence: float = 0.0
    provisional_score: float = 0.0
    provisional_frame_id: int = -1
    confirmed_plate: str = ""
    confirmed_frame_id: int = -1
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
            "provisional_plate": self.provisional_plate,
            "provisional_confidence": self.provisional_confidence,
            "provisional_score": self.provisional_score,
            "provisional_frame_id": self.provisional_frame_id,
            "confirmed_plate": self.confirmed_plate,
            "confirmed_frame_id": self.confirmed_frame_id,
            "candidate_text": self.candidate_text,
            "consensus_count": self.consensus_count,
            "frame_id": self.frame_id,
        }


def compute_ocr_job_quality(
    vehicle_crop: np.ndarray,
    native_vehicle_bbox: tuple[int, int, int, int] | Sequence[int],
    frame_res: tuple[int, int] | None = None,
    prev_bbox_area: float = 0.0,
    max_bbox_area: float = 0.0,
    plate_det_conf: float = 0.0,
    plate_size: tuple[int, int] | None = None,
) -> float:
    """Compute lightweight quality score (0.0 to 100.0) for an OCR candidate job.

    Cheap metrics evaluated without blocking the main loop:
    - Vehicle bounding box size & effective area
    - Sharpness (Laplacian variance)
    - Brightness and contrast (mean & std dev)
    - Plate detector confidence & native dimensions (if already available)
    - Approaching vs leaving dynamics (growth trend, historical peak size, frame boundary truncation)
    """
    if vehicle_crop is None or vehicle_crop.size == 0:
        return 0.0

    vx1, vy1, vx2, vy2 = [int(v) for v in native_vehicle_bbox[:4]]
    vw = max(0, vx2 - vx1)
    vh = max(0, vy2 - vy1)
    if vw < 30 or vh < 30:
        return 0.0

    v_area = float(vw * vh)
    v_eff = math.sqrt(v_area)

    # 1. Vehicle size score (40% weight): larger approaching vehicles provide much higher resolution plates
    size_score = max(0.0, min(100.0, (v_eff - 40.0) / 360.0 * 100.0))

    # 2. Sharpness score (25% weight): Laplacian variance on resized grayscale (takes <0.1ms)
    ch, cw = vehicle_crop.shape[:2]
    if ch > 160 or cw > 160:
        scale = 160.0 / max(ch, cw)
        nw, nh = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
        small = cv2.resize(vehicle_crop, (nw, nh), interpolation=cv2.INTER_NEAREST)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    else:
        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)

    lap_var = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    sharpness_score = max(0.0, min(100.0, (lap_var / 350.0) * 100.0))

    # 3. Brightness and contrast (15% weight)
    mean_val, std_val = cv2.meanStdDev(gray)
    b_val = float(mean_val[0][0])
    c_val = float(std_val[0][0])
    b_score = max(0.0, 100.0 - (abs(b_val - 128.0) / 128.0) * 60.0)
    c_score = max(0.0, min(100.0, (c_val / 45.0) * 100.0))
    illum_score = 0.5 * b_score + 0.5 * c_score

    # Base weighted quality
    score = (0.45 * size_score) + (0.30 * sharpness_score) + (0.15 * illum_score)

    # 4. Plate prior bonus/penalty if already available
    if plate_det_conf > 0:
        score += min(15.0, plate_det_conf * 15.0)
    if plate_size is not None and plate_size[0] > 0 and plate_size[1] > 0:
        pw, ph = plate_size
        if pw >= 60 and ph >= 25:
            score += 10.0
        elif pw < 35 or ph < 18:
            score -= 15.0

    # 5. Approaching vs leaving dynamics
    # When vehicle is significantly smaller than its historical peak, it is leaving/decaying
    if max_bbox_area > 0:
        shrink_ratio = v_area / max_bbox_area
        if shrink_ratio < 0.70:
            leaving_penalty = max(0.0, min(30.0, (1.0 - shrink_ratio) * 35.0))
            score -= leaving_penalty
        elif prev_bbox_area > 0 and v_area > 1.12 * prev_bbox_area:
            # Approaching: vehicle is expanding
            score += 8.0

    # Truncation penalty: vehicle touching frame boundary as it leaves
    if frame_res is not None:
        fw, fh = frame_res
        if vx1 <= 2 or vy1 <= 2 or vx2 >= fw - 3 or vy2 >= fh - 3:
            score -= 15.0

    return max(0.0, min(100.0, score))


class _OcrJob(NamedTuple):
    """Immutable OCR job submitted to the async worker."""
    track_id: int
    frame_id: int
    vehicle_crop: np.ndarray
    native_vehicle_bbox: tuple[int, int, int, int]
    vehicle_class: str
    eval_count: int
    generation: int = 0
    quality_score: float = 0.0
    plate_det_conf: float = 0.0
    plate_w: int = 0
    plate_h: int = 0


class _OcrWorker:
    """Best-quality pending crop per track; one running job; bounded global backlog."""
    def __init__(self, manager, start_thread: bool = True):
        self._manager = manager
        self._pending: OrderedDict[int, _OcrJob] = OrderedDict()
        self._condition = threading.Condition()
        self._stopped = False
        self._last_ocr_worker_ms = 0.0
        self._thread: threading.Thread | None = None
        if start_thread:
            self._thread = threading.Thread(target=self._run, name="OcrWorkerThread", daemon=True)
            self._thread.start()

    @property
    def last_ocr_worker_ms(self):
        return self._last_ocr_worker_ms

    @property
    def queue_size(self):
        with self._condition:
            return len(self._pending)

    def get_pending_job(self, track_id: int) -> _OcrJob | None:
        with self._condition:
            return self._pending.get(track_id)

    def enqueue(self, job: _OcrJob) -> None:
        with self._condition:
            if self._stopped:
                return

            old_job = self._pending.get(job.track_id)
            if old_job is not None:
                # Frame age penalty relative to current candidate frame
                age = max(0, job.frame_id - old_job.frame_id)
                age_penalty = min(25.0, max(0.0, (age - 30) * 0.25))
                old_quality = max(0.0, old_job.quality_score - age_penalty)
                new_quality = job.quality_score

                if new_quality > old_quality:
                    action = "REPLACE"
                    self._pending[job.track_id] = job
                else:
                    action = "KEEP_BEST"
                    # Preserve existing old_job in queue

                logger.info(
                    "[OCR_JOB_SELECT] track_id=%d old_frame=%d new_frame=%d old_quality=%.2f new_quality=%.2f action=%s",
                    job.track_id, old_job.frame_id, job.frame_id, old_quality, new_quality, action,
                )
            else:
                if len(self._pending) >= _OCR_QUEUE_MAXSIZE:
                    self._pending.popitem(last=False)
                self._pending[job.track_id] = job

            self._condition.notify()

    def discard(self, track_id: int) -> None:
        with self._condition:
            self._pending.pop(track_id, None)

    def clear(self) -> None:
        with self._condition:
            self._pending.clear()

    def stop(self) -> None:
        with self._condition:
            self._stopped = True
            self._pending.clear()
            self._condition.notify_all()
        if self._thread is not None and self._thread.is_alive():
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
        self.min_observations = min_observations if min_observations is not None else getattr(config, "PLATE_MIN_OBSERVATIONS", 2)
        self.min_confidence = getattr(config, "PLATE_CONSENSUS_CONFIDENCE", 0.35) if min_confidence is None else min_confidence
        self.min_quality = getattr(config, "PLATE_CONSENSUS_QUALITY", 0.0) if min_quality is None else min_quality
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

    def stop(self) -> None:
        """Stop the async OCR worker thread."""
        if self._worker is not None:
            self._worker.stop()

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

            # Confirmed plate is sticky: cannot be downgraded or overwritten
            if state.status in ("CONFIRMED", "RECOGNIZED"):
                normalized_cand = normalize_plate_text(getattr(cand, "plate_text", ""))
                if normalized_cand == state.confirmed_plate and getattr(cand, "quality_score", 0.0) >= state.plate_quality:
                    state.confidence = cand.confidence
                    state.plate_quality = cand.quality_score
                    state.plate_bbox_native = cand.bbox_native
                    state.plate_crop = cand.raw_crop
                    state.frame_id = job.frame_id
                return

            normalized = normalize_plate_text(cand.plate_text)
            raw = getattr(cand, "raw_text", "")
            if not isinstance(raw, str) or not raw:
                raw = cand.plate_text
            valid = is_valid_plate_format(raw) and is_valid_plate_format(normalized)
            eligible = (valid and math.isfinite(cand.confidence) and math.isfinite(cand.quality_score)
                        and cand.confidence >= self.min_confidence and cand.quality_score >= self.min_quality)

            if not eligible:
                return

            cand_score = round(float(cand.confidence * 100.0 + getattr(cand, "quality_score", 0.0)), 2)
            plate_det_conf = getattr(job, "plate_det_conf", 0.0)

            state.plate_history.append({"frame_id": job.frame_id, "raw_text": raw,
                "normalized_text": normalized, "confidence": cand.confidence,
                "quality": cand.quality_score, "score": cand_score, "eligible": True})
            del state.plate_history[:-self.history_size]

            votes = Counter(item["normalized_text"] for item in state.plate_history if item.get("eligible", True))
            state.vote_scores = dict(votes)

            # Stage 1: SEARCHING -> PROVISIONAL
            if state.status == "SEARCHING":
                state.status = "PROVISIONAL"
                state.provisional_plate = normalized
                state.provisional_confidence = cand.confidence
                state.provisional_score = cand_score
                state.provisional_frame_id = job.frame_id
                state.plate_text = normalized  # Display immediately
                state.confidence = cand.confidence
                state.plate_quality = cand.quality_score
                state.plate_bbox_native = cand.bbox_native
                state.plate_crop = cand.raw_crop
                state.frame_id = job.frame_id
                state.candidate_text = normalized
                state.consensus_count = 1

                logger.info(
                    "[PLATE_PROVISIONAL] track_id=%s frame_id=%s raw=%s normalized=%s "
                    "ocr_conf=%.3f plate_det_conf=%.3f score=%.2f",
                    job.track_id, job.frame_id, raw, normalized,
                    cand.confidence, plate_det_conf, cand_score)
                return

            # Stage 2: PROVISIONAL -> CONFIRMED (or Conflict Handling)
            if state.status in ("PROVISIONAL", "CHECKING"):
                if normalized == state.provisional_plate:
                    state.status = "CONFIRMED"
                    state.confirmed_plate = normalized
                    state.confirmed_frame_id = job.frame_id
                    state.plate_text = normalized
                    state.candidate_text = normalized
                    state.consensus_count = votes[normalized]
                    if cand.quality_score >= state.plate_quality:
                        state.confidence = cand.confidence
                        state.plate_quality = cand.quality_score
                        state.plate_bbox_native = cand.bbox_native
                        state.plate_crop = cand.raw_crop
                        state.frame_id = job.frame_id

                    if self._worker is not None:
                        self._worker.discard(job.track_id)

                    first_frame = state.provisional_frame_id
                    logger.info(
                        "[PLATE_CONFIRM] track_id=%s first_frame=%s confirm_frame=%s plate=%s observations=%s",
                        job.track_id, first_frame, job.frame_id, normalized, votes[normalized])
                else:
                    if votes[normalized] >= self.min_observations:
                        state.status = "CONFIRMED"
                        state.confirmed_plate = normalized
                        state.confirmed_frame_id = job.frame_id
                        state.plate_text = normalized
                        state.candidate_text = normalized
                        state.consensus_count = votes[normalized]
                        if cand.quality_score >= state.plate_quality:
                            state.confidence = cand.confidence
                            state.plate_quality = cand.quality_score
                            state.plate_bbox_native = cand.bbox_native
                            state.plate_crop = cand.raw_crop
                            state.frame_id = job.frame_id

                        if self._worker is not None:
                            self._worker.discard(job.track_id)

                        first_matching_frame = [
                            it["frame_id"] for it in state.plate_history if it["normalized_text"] == normalized
                        ][0]
                        logger.info(
                            "[PLATE_CONFIRM] track_id=%s first_frame=%s confirm_frame=%s plate=%s observations=%s",
                            job.track_id, first_matching_frame, job.frame_id, normalized, votes[normalized])
                    else:
                        current_plate = state.provisional_plate
                        current_score = state.provisional_score

                        if cand_score > current_score:
                            action = "REPLACE_PROVISIONAL"
                            state.provisional_plate = normalized
                            state.provisional_confidence = cand.confidence
                            state.provisional_score = cand_score
                            state.provisional_frame_id = job.frame_id
                            state.plate_text = normalized
                            state.confidence = cand.confidence
                            state.plate_quality = cand.quality_score
                            state.plate_bbox_native = cand.bbox_native
                            state.plate_crop = cand.raw_crop
                            state.frame_id = job.frame_id
                            state.candidate_text = normalized
                            state.consensus_count = votes[normalized]
                        elif cand_score < current_score:
                            action = "KEEP_CURRENT"
                        else:
                            action = "WAIT_FOR_TIEBREAK"

                        logger.info(
                            "[PLATE_CONFLICT] track_id=%s current_plate=%s current_score=%.2f new_plate=%s new_score=%.2f action=%s",
                            job.track_id, current_plate, current_score, normalized, cand_score, action)

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
            # Expire before refreshing sightings: a returning ID after a gap
            # must receive a new generation, including when no empty frame ran.
            expired = [
                tid for tid, last_seen in self._track_last_seen.items()
                if (frame_id - last_seen) > self.ttl_frames
            ]
            for tid in expired:
                logger.info("[PLATE_STATE_RESET] track_id=%s reason=ttl_expired", tid)
                self._track_last_seen.pop(tid, None)
                self._plate_states.pop(tid, None)
                if self._worker is not None:
                    self._worker.discard(tid)

            if tracker_id is not None:
                for tid in tracker_id:
                    if tid is not None:
                        self._track_last_seen[int(tid)] = frame_id

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
                    state = PlateTrackState(
                        track_id=tid_int,
                        vehicle_class=cname,
                        last_eval_frame=-999,
                        generation=self._generation,
                        max_bbox_area=bbox_area,
                    )
                    self._plate_states[tid_int] = state
                else:
                    state.vehicle_class = cname
                    if bbox_area > state.max_bbox_area:
                        state.max_bbox_area = bbox_area

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
                    if state.status in ("CONFIRMED", "RECOGNIZED")
                    else self.eval_interval
                )
                cadence_gap = frame_id - state.last_eval_frame if state.last_eval_frame >= 0 else -1
                cadence_due = (cadence_gap >= cadence_threshold) if cadence_gap >= 0 else False
                if state.status in ("CONFIRMED", "RECOGNIZED"):
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
                    prev_area = state.last_bbox_area
                    # Update cadence counters before OCR (prevents re-enqueue next frame)
                    state.last_eval_frame = frame_id
                    state.last_bbox_area = bbox_area
                    state.eval_count += 1

                    # Copy crop so frame buffer can be reused immediately
                    vehicle_crop = frame[vy1:vy2, vx1:vx2].copy()

                    plate_prior_conf = float(state.confidence) if state.confidence > 0 else 0.0
                    plate_prior_size = None
                    if state.plate_bbox_native is not None:
                        px1, py1, px2, py2 = state.plate_bbox_native
                        plate_prior_size = (max(0, px2 - px1), max(0, py2 - py1))

                    quality_score = compute_ocr_job_quality(
                        vehicle_crop=vehicle_crop,
                        native_vehicle_bbox=(vx1, vy1, vx2, vy2),
                        frame_res=(w, h),
                        prev_bbox_area=prev_area,
                        max_bbox_area=state.max_bbox_area,
                        plate_det_conf=plate_prior_conf,
                        plate_size=plate_prior_size,
                    )

                    job = _OcrJob(
                        track_id=tid_int,
                        frame_id=frame_id,
                        vehicle_crop=vehicle_crop,
                        native_vehicle_bbox=(vx1, vy1, vx2, vy2),
                        vehicle_class=cname,
                        eval_count=state.eval_count,
                        generation=state.generation,
                        quality_score=quality_score,
                        plate_det_conf=plate_prior_conf,
                        plate_w=plate_prior_size[0] if plate_prior_size else 0,
                        plate_h=plate_prior_size[1] if plate_prior_size else 0,
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

    def get_pending_ocr_job(self, track_id: int) -> _OcrJob | None:
        """Retrieve the pending _OcrJob for track_id if currently queued."""
        worker = self._worker
        if worker is not None:
            return worker.get_pending_job(track_id)
        return None

    def reset_tracks(self) -> None:
        """Clear all vehicle track associations (called on camera/source switch)."""
        with self._lock:
            worker = self._worker
            if worker is not None:
                worker.clear()
            for tid, state in self._plate_states.items():
                logger.info("[PLATE_STATE_RESET] track_id=%s reason=explicit_reset", tid)
            self._plate_states.clear()
            self._track_last_seen.clear()
            logger.info("[PLATE_TRACKER] Reset all vehicle license plate track associations.")


# Global singleton instance
vehicle_plate_manager = VehiclePlateManager(async_worker=True)

