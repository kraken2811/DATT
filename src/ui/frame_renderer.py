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
    car_tracks: Any = None,
    car_count: int = 0,
    zone_polygon: list[tuple[int, int]] | np.ndarray | None = None,
    target_matches: dict[int, Any] | None = None,
    track_states: dict[int, Any] | None = None,
) -> np.ndarray:
    """Render bounding boxes, tracking labels, occupancy HUD, and target highlights.

    Args:
        frame: Original BGR numpy image.
        tracks: Tracked person detections (supervision.Detections or similar).
        people_count: Current count of people in view from ZoneCounter.
        car_tracks: Optional tracked car detections.
        car_count: Optional current count of cars in view from CarCounter.
        zone_polygon: Optional ROI polygon coordinates.
        target_matches: Optional dict mapping track_id -> TargetMatchInfo.
        track_states: Optional dict mapping track_id -> BestFaceState.

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

    font = cv2.FONT_HERSHEY_SIMPLEX

    # 2. Draw Car Tracks (Amber / Orange theme)
    car_xyxy = getattr(car_tracks, "xyxy", None) if car_tracks is not None else None
    car_tracker_id = getattr(car_tracks, "tracker_id", None) if car_tracks is not None else None
    car_confidence = getattr(car_tracks, "confidence", None) if car_tracks is not None else None

    if car_xyxy is not None and len(car_xyxy) > 0:
        for i, box in enumerate(car_xyxy):
            x1, y1, x2, y2 = [int(v) for v in box]
            x1 = max(0, min(x1, w - 1))
            y1 = max(0, min(y1, h - 1))
            x2 = max(0, min(x2, w - 1))
            y2 = max(0, min(y2, h - 1))
            if x2 <= x1 or y2 <= y1:
                continue

            cid = car_tracker_id[i] if car_tracker_id is not None and i < len(car_tracker_id) else None
            conf = car_confidence[i] if car_confidence is not None and i < len(car_confidence) else None

            # Distinct Amber/Orange color for cars: BGR (11, 158, 245)
            car_color = (11, 158, 245)
            car_thickness = 2
            if cid is not None and conf is not None:
                car_label = f"CAR | C-{cid} | {conf:.2f}"
            elif cid is not None:
                car_label = f"CAR | C-{cid}"
            elif conf is not None:
                car_label = f"CAR | {conf:.2f}"
            else:
                car_label = "CAR"

            cv2.rectangle(canvas, (x1, y1), (x2, y2), car_color, car_thickness, cv2.LINE_AA)

            font_scale = 0.55
            font_thickness = 1
            (text_w, text_h), baseline = cv2.getTextSize(car_label, font, font_scale, font_thickness)
            tag_y1 = max(0, y1 - text_h - baseline - 6)
            tag_y2 = y1
            tag_x1 = x1
            tag_x2 = min(w, x1 + text_w + 8)

            cv2.rectangle(canvas, (tag_x1, tag_y1), (tag_x2, tag_y2), (20, 20, 20), -1)
            cv2.rectangle(canvas, (tag_x1, tag_y1), (tag_x2, tag_y2), car_color, 1, cv2.LINE_AA)
            cv2.putText(
                canvas,
                car_label,
                (tag_x1 + 4, tag_y2 - baseline - 2),
                font,
                font_scale,
                (255, 255, 255),
                font_thickness,
                cv2.LINE_AA,
            )

    # 3. Draw Person Tracks and Labels
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

            tid = tracker_id[i] if tracker_id is not None and i < len(tracker_id) else None
            conf = confidence[i] if confidence is not None and i < len(confidence) else None

            # Check if this track is matched to a registered target
            target_match = None
            if tid is not None and target_matches:
                target_match = target_matches.get(int(tid))

            if target_match is not None:
                # Highlight matched target with vibrant Gold/Amber: BGR (0, 215, 255)
                box_color = (0, 215, 255)
                box_thickness = 3
                t_name = getattr(target_match, "target_name", "Target")
                score = getattr(target_match, "score", 1.0)
                label = f"TARGET: {t_name} | P-{tid} | {score:.2f}"
            else:
                # Check BestFaceState for track state (Point 9)
                st = track_states.get(int(tid)) if (tid is not None and track_states) else None
                decision = getattr(st, "decision", "") if st is not None else ""
                sim = getattr(st, "similarity", 0.0) if st is not None else 0.0

                if decision == "CHECKING":
                    box_color = (0, 230, 255)  # Cyan-Yellow
                    box_thickness = 2
                    label = f"P-{tid} | CHECKING ({sim:.2f})"
                elif decision == "WAIT_FOR_BETTER_FACE":
                    box_color = (255, 200, 0)  # Cyan/Teal
                    box_thickness = 2
                    label = f"ID P-{tid} | WAIT FOR FACE"
                elif decision == "UNKNOWN":
                    box_color = (180, 180, 180)  # Slate Gray
                    box_thickness = 2
                    label = f"ID P-{tid} | UNKNOWN ({sim:.2f})"
                else:
                    # Normal person: Vibrant Cyan/Teal box: BGR (255, 200, 0)
                    box_color = (255, 200, 0)
                    box_thickness = 2
                    if tid is not None and conf is not None:
                        label = f"ID P-{tid} | {conf:.2f}"
                    elif tid is not None:
                        label = f"ID P-{tid}"
                    elif conf is not None:
                        label = f"Person | {conf:.2f}"
                    else:
                        label = "Person"

            cv2.rectangle(canvas, (x1, y1), (x2, y2), box_color, box_thickness, cv2.LINE_AA)

            # Draw Label Tag with solid dark background
            font_scale = 0.55
            font_thickness = 1 if target_match is None else 2
            (text_w, text_h), baseline = cv2.getTextSize(label, font, font_scale, font_thickness)

            tag_y1 = max(0, y1 - text_h - baseline - 6)
            tag_y2 = y1
            tag_x1 = x1
            tag_x2 = min(w, x1 + text_w + 8)

            # Dark tag background
            cv2.rectangle(canvas, (tag_x1, tag_y1), (tag_x2, tag_y2), (20, 20, 20), -1)
            # Outline for tag matching box color
            cv2.rectangle(canvas, (tag_x1, tag_y1), (tag_x2, tag_y2), box_color, 1, cv2.LINE_AA)
            # Label text in bright white (or bright yellow for target)
            text_color = (255, 255, 255) if target_match is None else (0, 255, 255)
            cv2.putText(
                canvas,
                label,
                (tag_x1 + 4, tag_y2 - baseline - 2),
                font,
                font_scale,
                text_color,
                font_thickness,
                cv2.LINE_AA,
            )

    return canvas
