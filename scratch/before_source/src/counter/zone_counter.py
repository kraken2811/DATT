"""Zone and Frame Occupancy Counter.

Maintains people count based on active ByteTrack tracks currently present
within the defined camera zone or full frame.
"""

from typing import Any

import cv2
import numpy as np
import supervision as sv


class ZoneCounter:
    """Current frame-wide or polygon zone occupancy counter for active tracks."""

    def __init__(
        self,
        polygon: list[tuple[int, int]] | None = None,
        person_class_id: int = 0,
        target_class_id: int | None = None,
        *args: Any,
        **kwargs: Any,
    ):
        self.polygon = (
            np.array(polygon, dtype=np.int32) if polygon is not None else None
        )
        self.target_class_id = target_class_id if target_class_id is not None else person_class_id
        self.person_class_id = self.target_class_id
        self.count: int = 0
        self.people_count: int = 0

    def update(
        self,
        tracks: sv.Detections,
        frame_shape: tuple[int, ...] | None = None,
    ) -> int:
        """Calculate current occupancy in the frame or zone.

        Args:
            tracks: Tracked detections containing tracker_id.
            frame_shape: (height, width, channels) to boundary-check positions.

        Returns:
            int: Number of active tracks currently in view.
        """
        if tracks.tracker_id is None or len(tracks.tracker_id) == 0:
            self.count = 0
            self.people_count = 0
            return 0

        # Filter for active tracks matching target class ID if class_id is present
        if tracks.class_id is not None and len(tracks.class_id) > 0:
            is_target = tracks.class_id == self.target_class_id
            active_tracks = tracks.tracker_id[is_target]
            active_boxes = tracks.xyxy[is_target]
        else:
            active_tracks = tracks.tracker_id
            active_boxes = tracks.xyxy

        if len(active_tracks) == 0:
            self.count = 0
            self.people_count = 0
            return 0

        # Bottom-center anchor points of the bounding boxes
        cx = (active_boxes[:, 0] + active_boxes[:, 2]) / 2.0
        cy = active_boxes[:, 3]

        # 1. Adapt automatically to any input resolution [0, 0, frame_w, frame_h]
        if frame_shape is not None:
            h, w = frame_shape[:2]
            in_frame = (cx >= 0) & (cx <= w) & (cy >= 0) & (cy <= h)
            active_tracks = active_tracks[in_frame]
            cx = cx[in_frame]
            cy = cy[in_frame]

        # 2. Polygon ROI filter if configured
        if self.polygon is not None and len(active_tracks) > 0:
            in_zone = []
            for px, py in zip(cx, cy):
                dist = cv2.pointPolygonTest(self.polygon, (float(px), float(py)), False)
                in_zone.append(dist >= 0)
            in_zone_arr = np.array(in_zone, dtype=bool)
            active_tracks = active_tracks[in_zone_arr]

        self.count = len(active_tracks)
        self.people_count = self.count
        return self.count

    @property
    def current_count(self) -> int:
        """Current number of active tracks in view."""
        return self.count

    def reset(self) -> None:
        """Reset counter to 0."""
        self.count = 0
        self.people_count = 0


class CarCounter(ZoneCounter):
    """Dedicated occupancy counter for cars in view."""

    def __init__(
        self,
        polygon: list[tuple[int, int]] | None = None,
        car_class_id: int = 2,
        target_class_id: int | None = None,
        *args: Any,
        **kwargs: Any,
    ):
        cid = target_class_id if target_class_id is not None else car_class_id
        super().__init__(polygon=polygon, target_class_id=cid, *args, **kwargs)
        self.car_count: int = 0

    def update(
        self,
        tracks: sv.Detections,
        frame_shape: tuple[int, ...] | None = None,
    ) -> int:
        val = super().update(tracks, frame_shape=frame_shape)
        self.car_count = val
        return val

    def reset(self) -> None:
        """Reset car counter to 0."""
        super().reset()
        self.car_count = 0
