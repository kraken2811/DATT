"""Zone and Frame Occupancy Counter.

Maintains people count based on active ByteTrack tracks currently present
within the defined camera zone or full frame.
"""

from typing import Any

import cv2
import numpy as np
import supervision as sv


class ZoneCounter:
    """Current frame-wide or polygon zone occupancy counter for active person tracks."""

    def __init__(
        self,
        polygon: list[tuple[int, int]] | None = None,
        person_class_id: int = 0,
        *args: Any,
        **kwargs: Any,
    ):
        self.polygon = (
            np.array(polygon, dtype=np.int32) if polygon is not None else None
        )
        self.person_class_id = person_class_id
        self.people_count: int = 0

    def update(
        self,
        tracks: sv.Detections,
        frame_shape: tuple[int, ...] | None = None,
    ) -> int:
        """Calculate current people occupancy in the frame or zone.

        Args:
            tracks: Tracked detections containing tracker_id.
            frame_shape: (height, width, channels) to boundary-check positions.

        Returns:
            int: Number of active people currently in view.
        """
        if tracks.tracker_id is None or len(tracks.tracker_id) == 0:
            self.people_count = 0
            return 0

        # Filter for active person tracks (PERSON_CLASS_ID = 0)
        if tracks.class_id is not None:
            is_person = tracks.class_id == self.person_class_id
            person_tracks = tracks.tracker_id[is_person]
            person_boxes = tracks.xyxy[is_person]
        else:
            person_tracks = tracks.tracker_id
            person_boxes = tracks.xyxy

        if len(person_tracks) == 0:
            self.people_count = 0
            return 0

        # Bottom-center anchor points of the bounding boxes
        cx = (person_boxes[:, 0] + person_boxes[:, 2]) / 2.0
        cy = person_boxes[:, 3]

        # 1. Adapt automatically to any input resolution [0, 0, frame_w, frame_h]
        if frame_shape is not None:
            h, w = frame_shape[:2]
            in_frame = (cx >= 0) & (cx <= w) & (cy >= 0) & (cy <= h)
            person_tracks = person_tracks[in_frame]
            cx = cx[in_frame]
            cy = cy[in_frame]

        # 2. Polygon ROI filter if configured
        if self.polygon is not None and len(person_tracks) > 0:
            in_zone = []
            for px, py in zip(cx, cy):
                dist = cv2.pointPolygonTest(self.polygon, (float(px), float(py)), False)
                in_zone.append(dist >= 0)
            in_zone_arr = np.array(in_zone, dtype=bool)
            person_tracks = person_tracks[in_zone_arr]

        self.people_count = len(person_tracks)
        return self.people_count
