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

from src.ocr.plate_reader import LicensePlateReader, plate_reader

logger = logging.getLogger("datt.ocr.plate_tracker")

CADENCE_UNRECOGNIZED_FRAMES = 10
CADENCE_RECOGNIZED_FRAMES = 60
EXPIRATION_TTL_FRAMES = 60


@dataclass
class PlateTrackState:
    """Stores the best license plate representation and state for a vehicle track."""
    track_id: int
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
        car_tracks: Any,
        frame_id: int,
    ) -> dict[int, PlateTrackState]:
        """Evaluate active vehicle tracks for license plate detection & OCR.

        Args:
            frame: Native unresized BGR frame (H, W, 3).
            car_tracks: Detections/Tracks from ByteTrack with xyxy and tracker_id.
            frame_id: Monotonically increasing sequence frame counter.

        Returns:
            dict[int, PlateTrackState]: Active vehicle tracks with their latest recognized plate state.
        """
        if frame is None or car_tracks is None:
            return {}

        xyxy = getattr(car_tracks, "xyxy", None)
        tracker_id = getattr(car_tracks, "tracker_id", None)

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

                state = self._plate_states.get(tid_int)
                if state is None:
                    state = PlateTrackState(track_id=tid_int, last_eval_frame=-999)
                    self._plate_states[tid_int] = state

                # Fast retry if vehicle bbox area grew > 20% (moving closer, plate getting larger)
                growth_due = False
                if state.last_bbox_area > 0 and (frame_id - state.last_eval_frame) >= 2:
                    ratio = (bbox_area - state.last_bbox_area) / state.last_bbox_area
                    if ratio > 0.20:
                        growth_due = True

                # Cadence logic (Requirement: Không OCR mọi frame)
                if state.status == "RECOGNIZED" and state.confidence >= 0.70:
                    needs_eval = (frame_id - state.last_eval_frame) >= CADENCE_RECOGNIZED_FRAMES or growth_due
                else:
                    cadence_due = (frame_id - state.last_eval_frame) >= self.eval_interval
                    needs_eval = cadence_due or growth_due or (state.last_eval_frame < 0)

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
                        if not state.plate_text:
                            is_better = True
                        elif cand.quality_score > state.plate_quality:
                            is_better = True
                        elif cand.confidence > state.confidence + 0.08:
                            is_better = True

                        if is_better:
                            state.plate_text = cand.plate_text
                            state.confidence = cand.confidence
                            state.plate_bbox_native = cand.bbox_native
                            state.plate_crop = cand.raw_crop
                            state.plate_quality = cand.quality_score
                            state.frame_id = frame_id
                            state.status = "RECOGNIZED"

                            logger.info(
                                "[PLATE_TRACK] Track C-%d f=%d NEW BEST PLATE: '%s' conf=%.2f quality=%.1f",
                                tid_int, frame_id, state.plate_text, state.confidence, state.plate_quality
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
