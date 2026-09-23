"""Decoupled Frame Renderer for DATT - AI People Counter.

Phase 4: Level 2 Realtime Monitoring UI.
Responsible strictly for drawing bounding boxes, track IDs, confidences,
and people count HUD on the video frame.

This module is strictly a visualization layer:
- It NEVER invokes YOLO or ByteTrack.
- It NEVER modifies tracking or counter states.
"""

from typing import Any

import cv2
import numpy as np


def render_frame(
    frame: np.ndarray,
    tracks: Any,
    people_count: int,
    zone_polygon: list[tuple[int, int]] | np.ndarray | None = None,
) -> np.ndarray:
    """Render bounding boxes, tracking labels, and people count HUD onto frame.

    Args:
        frame: Original BGR numpy image.
        tracks: Tracked detections (supervision.Detections or similar).
        people_count: Current count of people in view from ZoneCounter.
        zone_polygon: Optional ROI polygon coordinates.

    Returns:
        np.ndarray: Annotated BGR frame copy.
    """
    if frame is None:
        return frame

    # Work on a copy to keep original frame pristine
    canvas = frame.copy()
    h, w = canvas.shape[:2]

    # 1. Draw Zone Polygon if configured
    if zone_polygon is not None:
        poly_arr = np.array(zone_polygon, dtype=np.int32)
        cv2.polylines(canvas, [poly_arr], isClosed=True, color=(0, 255, 255), thickness=2)

    # 2. Draw Track Bounding Boxes and Labels
    # Extract tracks attributes if available
    xyxy = getattr(tracks, "xyxy", None)
    tracker_id = getattr(tracks, "tracker_id", None)
    confidence = getattr(tracks, "confidence", None)

    if xyxy is not None and len(xyxy) > 0:
        for i, box in enumerate(xyxy):
            x1, y1, x2, y2 = [int(v) for v in box]

            # Clip box coordinates to frame boundaries
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(0, min(x2, w - 1))
            y2 = max(0, min(y2, h - 1))

            if x2 <= x1 or y2 <= y1:
                continue

            # Format label: ID 12 | 0.92
            tid = tracker_id[i] if tracker_id is not None and i < len(tracker_id) else None
            conf = confidence[i] if confidence is not None and i < len(confidence) else None

            if tid is not None and conf is not None:
                label = f"ID {tid} | {conf:.2f}"
            elif tid is not None:
                label = f"ID {tid}"
            elif conf is not None:
                label = f"Person | {conf:.2f}"
            else:
                label = "Person"

            # Vibrant Cyan/Teal box: BGR (255, 200, 0)
            box_color = (255, 200, 0)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), box_color, 2, cv2.LINE_AA)

            # Draw Label Tag with solid dark background
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.55
            font_thickness = 1
            (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, font_thickness)

            tag_y1 = max(0, y1 - text_h - baseline - 6)
            tag_y2 = y1
            tag_x1 = x1
            tag_x2 = min(w, x1 + text_w + 8)

            # Dark tag background
            cv2.rectangle(canvas, (tag_x1, tag_y1), (tag_x2, tag_y2), (20, 20, 20), -1)
            # Outline for tag matching box color
            cv2.rectangle(canvas, (tag_x1, tag_y1), (tag_x2, tag_y2), box_color, 1, cv2.LINE_AA)
            # Label text in bright white
            cv2.putText(
                canvas,
                label,
                (tag_x1 + 4, tag_y2 - baseline - 2),
                font,
                font_scale,
                (255, 255, 255),
                font_thickness,
                cv2.LINE_AA,
            )

    return canvas
