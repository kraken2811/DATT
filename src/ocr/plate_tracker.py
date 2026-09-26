"""Vehicle License Plate Tracking, Lifecycle Management, and Cadence Control.

Features:
- Track-level BestPlateState persistence (keeps best plate crop and text per track).
- Adaptive Cadence: Never OCRs every frame; evaluates every N=10 frames or on >20% bbox growth.
- Once a high-confidence plate is recognized (conf >= 0.70), slows evaluation to every 60 frames.
- Rejection safety: Worse or low-confidence candidates do not overwrite established best plate.
- TTL Expiration and thread-safe camera reset.
"""

from dataclasses import dataclass
import logging
import threading
from typing import Any, Sequence

import cv2
import numpy as np

import config
from src.ocr.plate_reader import LicensePlateReader, plate_reader

logger = logging.getLogger("datt.ocr.plate_tracker")

CADENCE_UNRECOGNIZED_FRAMES = 10
CADENCE_RECOGNIZED_FRAMES = 60
EXPIRATION_TTL_FRAMES = 60


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


class VehiclePlateManager:
    """Manages license plate detection, OCR, and BestPlate retention per active vehicle track."""

    def __init__(
        self,
        reader: LicensePlateReader | None = None,
        eval_interval: int = CADENCE_UNRECOGNIZED_FRAMES,
        ttl_frames: int = EXPIRATION_TTL_FRAMES,
    ) -> None:
        self.reader = reader or plate_reader
        self.eval_interval = eval_interval
        self.ttl_frames = ttl_frames

        self._lock = threading.RLock()
        # track_id -> PlateTrackState
        self._plate_states: dict[int, PlateTrackState] = {}
        # track_id -> last_seen_frame_id
        self._track_last_seen: dict[int, int] = {}

    def get_plate_state(self, track_id: int) -> PlateTrackState | None:
        """Retrieve copy of PlateTrackState for a specific vehicle track."""
        with self._lock:
            state = self._plate_states.get(track_id)
            return state

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

        Args:
            frame: Native unresized BGR frame (H, W, 3).
            car_tracks: Detections/Tracks from ByteTrack with xyxy and tracker_id (legacy alias).
            frame_id: Monotonically increasing sequence frame counter.
            vehicle_tracks: Unified tracked vehicle detections (car, truck, bus, motorcycle).

        Returns:
            dict[int, PlateTrackState]: Active vehicle tracks with their latest recognized plate state.
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
                        tid_int = int(tid)
                        self._track_last_seen[tid_int] = frame_id

            # Purge expired tracks
            expired = [
                tid for tid, last_seen in self._track_last_seen.items()
                if (frame_id - last_seen) > self.ttl_frames
            ]
            for tid in expired:
                self._track_last_seen.pop(tid, None)
                self._plate_states.pop(tid, None)

            if xyxy is None or tracker_id is None or len(xyxy) == 0:
                return {}

            # 2. Process each detected vehicle track
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
                    "[VEHICLE_DET] class=%s conf=%.2f bbox=[%d, %d, %d, %d] track_id=%d size=%dx%d frame_res=%dx%d frame_id=%d",
                    cname, conf_val, vx1, vy1, vx2, vy2, tid_int, vw, vh, w, h, frame_id,
                )

                state = self._plate_states.get(tid_int)
                if state is None:
                    state = PlateTrackState(track_id=tid_int, vehicle_class=cname, last_eval_frame=-999)
                    self._plate_states[tid_int] = state
                else:
                    state.vehicle_class = cname

                # Check license plate eligibility: car, truck, bus (motorcycle excluded from plate OCR)
                eligible_classes = getattr(config, "PLATE_ELIGIBLE_CLASSES", [2, 5, 7])
                if cid not in eligible_classes:
                    logger.info(
                        "[PLATE_ATTEMPT] track_id=%d class=%s frame_id=%d attempt=SKIP reason=not_eligible",
                        tid_int, cname, frame_id,
                    )
                    active_results[tid_int] = state
                    continue

                # Fast retry if vehicle bbox area grew > 20% (moving closer, plate getting larger)
                growth_due = False
                if state.last_bbox_area > 0 and (frame_id - state.last_eval_frame) >= 2:
                    ratio = (bbox_area - state.last_bbox_area) / state.last_bbox_area
                    if ratio > 0.20:
                        growth_due = True

                # Cadence logic (Requirement: Không OCR mọi frame)
                cadence_threshold = CADENCE_RECOGNIZED_FRAMES if (state.status == "RECOGNIZED" and state.confidence >= 0.70) else self.eval_interval
                cadence_gap = frame_id - state.last_eval_frame if state.last_eval_frame >= 0 else -1
                cadence_due = (cadence_gap >= cadence_threshold) if cadence_gap >= 0 else False
                needs_eval = cadence_due or growth_due or (state.last_eval_frame < 0)

                reason = "first_eval" if state.last_eval_frame < 0 else ("growth" if growth_due else ("cadence_interval" if cadence_due else "wait_cadence"))

                logger.info(
                    "[PLATE_ATTEMPT] track_id=%d class=%s frame_id=%d cadence_gap=%d attempt=%s reason=%s v_size=%dx%d status=%s",
                    tid_int, cname, frame_id, cadence_gap, "RUN" if needs_eval else "SKIP", reason, vw, vh, state.status,
                )

                if needs_eval:
                    # Crop vehicle strictly for plate localization (Requirement: Không OCR toàn frame)
                    vehicle_crop = frame[vy1:vy2, vx1:vx2]
                    state.last_eval_frame = frame_id
                    state.last_bbox_area = bbox_area
                    state.eval_count += 1

                    cand = self.reader.extract_license_plate(
                        vehicle_crop=vehicle_crop,
                        native_vehicle_bbox=[vx1, vy1, vx2, vy2],
                        track_id=tid_int,
                        frame_id=frame_id,
                    )

                    # BestPlate retention (Requirement: Giữ best plate crop theo track)
                    if cand is not None:
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
                            better_reason = f"rejected_inferior(q={cand.quality_score:.1f}<={state.plate_quality:.1f},conf={cand.confidence:.2f}<={state.confidence:.2f})"

                        logger.info(
                            "[PLATE_STATE] track_id=%d frame_id=%d status=%s current_plate='%s'(conf=%.2f,q=%.1f) cand='%s'(conf=%.2f,q=%.1f) is_better=%s reason=%s",
                            tid_int, frame_id, state.status, state.plate_text, state.confidence, state.plate_quality,
                            cand.plate_text, cand.confidence, cand.quality_score, is_better, better_reason,
                        )

                        if is_better:
                            state.plate_text = cand.plate_text
                            state.confidence = cand.confidence
                            state.plate_bbox_native = cand.bbox_native
                            state.plate_crop = cand.raw_crop
                            state.plate_quality = cand.quality_score
                            state.frame_id = frame_id
                            state.status = "RECOGNIZED"

                            logger.info(
                                "[PLATE_TRACK] Track %s-%d f=%d NEW BEST PLATE: '%s' conf=%.2f quality=%.1f",
                                cname.upper(), tid_int, frame_id, state.plate_text, state.confidence, state.plate_quality
                            )
                    else:
                        logger.info(
                            "[PLATE_STATE] track_id=%d frame_id=%d status=%s current_plate='%s'(conf=%.2f) cand=None",
                            tid_int, frame_id, state.status, state.plate_text, state.confidence,
                        )

                active_results[tid_int] = state

        return active_results

    def reset_tracks(self) -> None:
        """Clear all vehicle track associations (called on camera/source switch)."""
        with self._lock:
            self._plate_states.clear()
            self._track_last_seen.clear()
            logger.info("[PLATE_TRACKER] Reset all vehicle license plate track associations.")


# Global singleton instance
vehicle_plate_manager = VehiclePlateManager()
