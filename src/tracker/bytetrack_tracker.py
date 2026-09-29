"""ByteTrack Tracker Wrapper.

Decoupled multi-object tracking using Supervision ByteTrack.
Accepts generic detection dictionaries or objects without knowledge of the detector backend.
"""

from typing import Any, Mapping

import numpy as np
import supervision as sv


class PersonTracker:
    """ByteTrack wrapper configured for person tracking."""

    def __init__(self, config: Any = None, frame_rate: float | None = None):
        fps = frame_rate if frame_rate is not None else getattr(config, "TRACKER_FRAME_RATE", 30.0)
        self.tracker = sv.ByteTrack(
            track_activation_threshold=getattr(
                config, "TRACK_ACTIVATION_THRESHOLD", 0.40
            ),
            lost_track_buffer=getattr(config, "LOST_TRACK_BUFFER", 30),
            minimum_matching_threshold=getattr(
                config, "MINIMUM_MATCHING_THRESHOLD", 0.80
            ),
            frame_rate=fps,
            minimum_consecutive_frames=getattr(
                config, "MINIMUM_CONSECUTIVE_FRAMES", 2
            ),
        )

    def update(self, detections: Any) -> sv.Detections:
        """Update tracker state with new detections.

        Args:
            detections: Generic mapping or object containing 'xyxy', 'confidence', 'class_id'.

        Returns:
            sv.Detections: Tracked detections containing tracker_id.
        """
        if isinstance(detections, sv.Detections):
            sv_dets = detections
        elif isinstance(detections, Mapping):
            xyxy = detections.get("xyxy", np.empty((0, 4), dtype=np.float32))
            confidence = detections.get("confidence", np.empty((0,), dtype=np.float32))
            class_id = detections.get("class_id", np.empty((0,), dtype=int))
            sv_dets = sv.Detections(
                xyxy=xyxy,
                confidence=confidence,
                class_id=class_id,
            )
        else:
            xyxy = getattr(detections, "xyxy", np.empty((0, 4), dtype=np.float32))
            confidence = getattr(
                detections, "confidence", np.empty((0,), dtype=np.float32)
            )
            class_id = getattr(detections, "class_id", np.empty((0,), dtype=int))
            sv_dets = sv.Detections(
                xyxy=xyxy,
                confidence=confidence,
                class_id=class_id,
            )

        tracked_detections = self.tracker.update_with_detections(sv_dets)
        return tracked_detections

    def predict(self) -> sv.Detections:
        """Smoothly advance active tracks with Kalman prediction between detector updates."""
        try:
            from supervision.tracker.byte_tracker import core
            if hasattr(self.tracker, "tracked_tracks") and self.tracker.tracked_tracks:
                core.STrack.multi_predict(self.tracker.tracked_tracks, self.tracker.shared_kalman)
                active = [t for t in self.tracker.tracked_tracks if t.is_activated]
                if active:
                    xyxy = np.array([t.tlbr for t in active], dtype=np.float32)
                    tracker_id = np.array([int(t.external_track_id) for t in active], dtype=int)
                    confidence = np.array([float(t.score) for t in active], dtype=np.float32)
                    class_id = np.zeros(len(active), dtype=int)
                    return sv.Detections(
                        xyxy=xyxy,
                        confidence=confidence,
                        class_id=class_id,
                        tracker_id=tracker_id,
                    )
        except Exception:
            pass
        return sv.Detections.empty()

    def reset(self) -> None:
        """Reset internal tracker state."""
        self.tracker.reset()


class CarTracker:
    """ByteTrack wrapper configured for car tracking.

    Operates an independent ByteTrack instance to avoid cross-class track ID collisions.
    """

    def __init__(self, config: Any = None, frame_rate: float | None = None):
        fps = frame_rate if frame_rate is not None else getattr(config, "TRACKER_FRAME_RATE", 30.0)
        self.tracker = sv.ByteTrack(
            track_activation_threshold=getattr(
                config, "CAR_TRACK_ACTIVATION_THRESHOLD", 0.40
            ),
            lost_track_buffer=getattr(config, "CAR_LOST_TRACK_BUFFER", 30),
            minimum_matching_threshold=getattr(
                config, "CAR_MINIMUM_MATCHING_THRESHOLD", 0.80
            ),
            frame_rate=fps,
            minimum_consecutive_frames=getattr(
                config, "MINIMUM_CONSECUTIVE_FRAMES", 2
            ),
        )
        self._track_class_ids: dict[int, int] = {}

    def update(self, detections: Any) -> sv.Detections:
        """Update tracker state with new car detections."""
        if isinstance(detections, sv.Detections):
            sv_dets = detections
        elif isinstance(detections, Mapping):
            xyxy = detections.get("xyxy", np.empty((0, 4), dtype=np.float32))
            confidence = detections.get("confidence", np.empty((0,), dtype=np.float32))
            class_id = detections.get("class_id", np.empty((0,), dtype=int))
            sv_dets = sv.Detections(
                xyxy=xyxy,
                confidence=confidence,
                class_id=class_id,
            )
        else:
            xyxy = getattr(detections, "xyxy", np.empty((0, 4), dtype=np.float32))
            confidence = getattr(
                detections, "confidence", np.empty((0,), dtype=np.float32)
            )
            class_id = getattr(detections, "class_id", np.empty((0,), dtype=int))
            sv_dets = sv.Detections(
                xyxy=xyxy,
                confidence=confidence,
                class_id=class_id,
            )

        tracked_detections = self.tracker.update_with_detections(sv_dets)
        if len(tracked_detections) > 0 and getattr(tracked_detections, "tracker_id", None) is not None:
            cids = getattr(tracked_detections, "class_id", None)
            for i, tid in enumerate(tracked_detections.tracker_id):
                if tid is not None:
                    cid = int(cids[i]) if cids is not None and i < len(cids) else 2
                    self._track_class_ids[int(tid)] = cid
        return tracked_detections

    def predict(self) -> sv.Detections:
        """Smoothly advance active vehicle tracks with Kalman prediction between detector updates."""
        try:
            from supervision.tracker.byte_tracker import core
            if hasattr(self.tracker, "tracked_tracks") and self.tracker.tracked_tracks:
                core.STrack.multi_predict(self.tracker.tracked_tracks, self.tracker.shared_kalman)
                active = [t for t in self.tracker.tracked_tracks if t.is_activated]
                if active:
                    xyxy = np.array([t.tlbr for t in active], dtype=np.float32)
                    tracker_id = np.array([int(t.external_track_id) for t in active], dtype=int)
                    confidence = np.array([float(t.score) for t in active], dtype=np.float32)
                    class_id = np.array([self._track_class_ids.get(int(t.external_track_id), 2) for t in active], dtype=int)
                    return sv.Detections(
                        xyxy=xyxy,
                        confidence=confidence,
                        class_id=class_id,
                        tracker_id=tracker_id,
                    )
        except Exception:
            pass
        return sv.Detections.empty()

    def reset(self) -> None:
        """Reset internal car tracker state."""
        self.tracker.reset()
        self._track_class_ids.clear()

