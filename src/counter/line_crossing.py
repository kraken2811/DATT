"""Reliable directional line crossing and ROI passage counter.

Physical passages are evaluated across a configurable normalized counting line.
Deduplication, hysteresis, and direction validation ensure one physical passage = one event.
Operates entirely in-memory with sub-millisecond per-frame execution.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Literal
from uuid import UUID, uuid4

import cv2
import numpy as np
import supervision as sv


DEFAULT_VEHICLE_CLASS_MAP = {
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

DEFAULT_PERSON_CLASS_ID = 0


@dataclass
class CrossingRecord:
    """Record of a verified line crossing."""
    id: UUID
    camera_id: str
    zone_id: str | None
    object_type: str  # "person" or "vehicle"
    object_class: str  # "person", "car", "motorcycle", etc.
    direction: str  # "in" or "out"
    track_id: int
    tracking_session_id: str
    event_time: datetime
    source_type: str
    video_source_id: UUID | None
    idempotency_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _segments_intersect(p1: tuple[float, float], p2: tuple[float, float],
                        q1: tuple[float, float], q2: tuple[float, float],
                        tolerance: float = 0.05) -> bool:
    """Check whether segment p1-p2 intersects segment q1-q2 with extension tolerance."""
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    # Extend line segment q1-q2 by tolerance on both sides for boundary flexibility
    dx = q2[0] - q1[0]
    dy = q2[1] - q1[1]
    eq1 = (q1[0] - dx * tolerance, q1[1] - dy * tolerance)
    eq2 = (q2[0] + dx * tolerance, q2[1] + dy * tolerance)

    return (ccw(p1, eq1, eq2) != ccw(p2, eq1, eq2)) and (ccw(p1, p2, eq1) != ccw(p1, p2, eq2))


class LineCrossingCounter:
    """High-accuracy line crossing counter for people and vehicles."""

    def __init__(
        self,
        camera_id: str,
        line_p1: tuple[float, float] = (0.1, 0.5),
        line_p2: tuple[float, float] = (0.9, 0.5),
        in_direction: str = "normal",  # "normal" (+ to - is IN) or "reverse"
        roi_polygon: list[tuple[float, float]] | None = None,
        supported_classes: list[str] | None = None,
        min_crossing_distance: float = 0.015,
        hysteresis_frames: int = 2,
        cooldown_seconds: float = 3.0,
        zone_id: str | None = None,
        session_id: str | None = None,
        enabled: bool = True,
    ) -> None:
        self.camera_id = camera_id
        self.zone_id = zone_id
        self.enabled = enabled
        self.session_id = session_id or str(uuid4())[:8]

        # Normalized line coordinates [0.0 .. 1.0]
        self.line_p1 = (float(line_p1[0]), float(line_p1[1]))
        self.line_p2 = (float(line_p2[0]), float(line_p2[1]))
        self.in_direction = in_direction
        self.min_crossing_distance = min_crossing_distance
        self.hysteresis_frames = hysteresis_frames
        self.cooldown_seconds = cooldown_seconds

        # Normalized polygon ROI filter [(x, y), ...]
        self.roi_polygon = roi_polygon

        # Supported object classes
        self.supported_classes = set(
            supported_classes or ["person", "car", "motorcycle", "bus", "truck"]
        )

        # Track state tracking: track_id -> dict
        # {
        #   "history": list of (x, y, dist, timestamp),
        #   "last_seen_time": float,
        #   "last_crossed_direction": str | None,
        #   "last_crossed_time": float,
        #   "crossed_count": int,
        # }
        self._tracks: dict[int, dict[str, Any]] = {}

        # Counters
        self.counts = {
            "person": {"in": 0, "out": 0},
            "vehicle": {"in": 0, "out": 0},
            "by_class": {},
        }

    def _signed_distance(self, p: tuple[float, float]) -> float:
        """Calculate signed perpendicular distance from normalized point p to the line.

        Positive on one side, negative on the other side.
        Line vector L = p2 - p1. Normal vector N = (-L.y, L.x).
        """
        x1, y1 = self.line_p1
        x2, y2 = self.line_p2
        dx = x2 - x1
        dy = y2 - y1
        line_len = np.hypot(dx, dy)
        if line_len < 1e-6:
            return 0.0

        # Signed distance via 2D cross product: (x - x1) * dy - (y - y1) * dx
        return ((p[0] - x1) * dy - (p[1] - y1) * dx) / line_len

    def _is_in_roi(self, p: tuple[float, float]) -> bool:
        """Check if normalized point is inside configured ROI polygon."""
        if not self.roi_polygon or len(self.roi_polygon) < 3:
            return True
        poly = np.array(self.roi_polygon, dtype=np.float32)
        dist = cv2.pointPolygonTest(poly, (float(p[0]), float(p[1])), False)
        return dist >= 0

    def update(
        self,
        tracks: sv.Detections,
        frame_shape: tuple[int, ...] | None = None,
        video_source_id: UUID | None = None,
        source_type: str = "live",
        current_time: float | None = None,
    ) -> list[CrossingRecord]:
        """Process one frame of ByteTrack detections and return any newly validated crossings.

        Args:
            tracks: Detections containing tracker_id, xyxy, class_id, confidence.
            frame_shape: (height, width, ...) to normalize coordinates.
            video_source_id: Optional ID of prerecorded video source.
            source_type: "live" or "prerecorded".
            current_time: Monotonic or wall-clock epoch timestamp.

        Returns:
            list[CrossingRecord]: New crossing events emitted in this frame.
        """
        if not self.enabled:
            return []

        now = current_time or time.time()
        emitted_crossings: list[CrossingRecord] = []

        ids = getattr(tracks, "tracker_id", None)
        boxes = getattr(tracks, "xyxy", None)
        classes = getattr(tracks, "class_id", None)

        if ids is None or boxes is None or len(ids) == 0:
            self._prune_inactive(now)
            return []

        h, w = frame_shape[:2] if frame_shape is not None else (1080, 1920)

        for i, tid in enumerate(ids):
            if tid is None:
                continue
            tid = int(tid)
            box = boxes[i]
            cid = int(classes[i]) if classes is not None else DEFAULT_PERSON_CLASS_ID

            # Resolve object class and type
            if cid == DEFAULT_PERSON_CLASS_ID:
                obj_type = "person"
                obj_class = "person"
            elif cid in DEFAULT_VEHICLE_CLASS_MAP:
                obj_type = "vehicle"
                obj_class = DEFAULT_VEHICLE_CLASS_MAP[cid]
            else:
                obj_type = "vehicle"
                obj_class = "vehicle"

            # Filter if class is not supported
            if obj_class not in self.supported_classes and obj_type not in self.supported_classes:
                continue

            # Anchor point: bottom-center of bbox (for foot/wheel line crossing)
            cx = float((box[0] + box[2]) / 2.0) / float(w)
            cy = float(box[3]) / float(h)
            pos = (cx, cy)

            # ROI filter
            if not self._is_in_roi(pos):
                continue

            dist = self._signed_distance(pos)

            track_key = (obj_type, tid)
            track_state = self._tracks.get(track_key)
            if track_state is None:
                self._tracks[track_key] = {
                    "history": [(pos[0], pos[1], dist, now)],
                    "obj_type": obj_type,
                    "obj_class": obj_class,
                    "last_seen_time": now,
                    "last_crossed_direction": None,
                    "last_crossed_time": None,
                    "crossed_count": 0,
                }
                continue

            # Append current position to history
            history = track_state["history"]
            history.append((pos[0], pos[1], dist, now))
            if len(history) > 30:
                history.pop(0)

            track_state["last_seen_time"] = now
            track_state["obj_type"] = obj_type
            track_state["obj_class"] = obj_class

            # Need at least hysteresis_frames + 1 points to validate crossing
            if len(history) < self.hysteresis_frames + 1:
                continue

            # Check crossing against historical anchor before crossing
            # Look back across the hysteresis window
            prev_pos = (history[-self.hysteresis_frames - 1][0], history[-self.hysteresis_frames - 1][1])
            prev_dist = history[-self.hysteresis_frames - 1][2]

            # Cooldown check: prevent oscillating or repeat counting for same track
            if (track_state["last_crossed_time"] is not None
                    and now - track_state["last_crossed_time"] < self.cooldown_seconds):
                continue

            # Crossing condition: sign flip and sufficient displacement
            sign_changed = (prev_dist * dist < 0)
            displacement = abs(dist - prev_dist)

            if sign_changed and displacement >= self.min_crossing_distance:
                # Validate line segment intersection
                if _segments_intersect(prev_pos, pos, self.line_p1, self.line_p2):
                    # Direction determination:
                    # If prev_dist > 0 and dist < 0: moving from positive side to negative side
                    if prev_dist > 0 and dist < 0:
                        direction = "in" if self.in_direction == "normal" else "out"
                    else:
                        direction = "out" if self.in_direction == "normal" else "in"

                    # Register crossing
                    track_state["last_crossed_direction"] = direction
                    track_state["last_crossed_time"] = now
                    track_state["crossed_count"] += 1

                    # Update internal counts
                    self.counts[obj_type][direction] = self.counts[obj_type].get(direction, 0) + 1
                    if obj_class not in self.counts["by_class"]:
                        self.counts["by_class"][obj_class] = {"in": 0, "out": 0}
                    self.counts["by_class"][obj_class][direction] = (
                        self.counts["by_class"][obj_class].get(direction, 0) + 1
                    )

                    # Stable idempotency key
                    # Scoped to camera, session, object_type, track_id, and crossing sequence index
                    seq_idx = track_state["crossed_count"]
                    idempotency_key = f"cross:{self.camera_id}:{self.session_id}:{obj_type}:{tid}:{seq_idx}"

                    record = CrossingRecord(
                        id=uuid4(),
                        camera_id=self.camera_id,
                        zone_id=self.zone_id,
                        object_type=obj_type,
                        object_class=obj_class,
                        direction=direction,
                        track_id=tid,
                        tracking_session_id=self.session_id,
                        event_time=datetime.now(timezone.utc),
                        source_type=source_type,
                        video_source_id=video_source_id,
                        idempotency_key=idempotency_key,
                        metadata={
                            "displacement": float(displacement),
                            "prev_pos": [round(prev_pos[0], 4), round(prev_pos[1], 4)],
                            "curr_pos": [round(pos[0], 4), round(pos[1], 4)],
                            "anchor": "bottom_center",
                        },
                    )
                    emitted_crossings.append(record)

        self._prune_inactive(now)
        return emitted_crossings

    def _prune_inactive(self, now: float, timeout_seconds: float = 5.0) -> None:
        """Remove tracks that haven't been seen for longer than timeout_seconds."""
        stale_keys = [
            k for k, s in self._tracks.items()
            if now - s["last_seen_time"] > timeout_seconds
        ]
        for k in stale_keys:
            del self._tracks[k]

    def reset(self, new_session_id: str | None = None) -> None:
        """Reset internal tracking state and start a new session."""
        self._tracks.clear()
        self.session_id = new_session_id or str(uuid4())[:8]

    def reset_counts(self) -> None:
        """Reset total count registers."""
        self.counts = {
            "person": {"in": 0, "out": 0},
            "vehicle": {"in": 0, "out": 0},
            "by_class": {},
        }
