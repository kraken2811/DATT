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

import config


def render_frame(
    frame: np.ndarray,
    tracks: Any,
    people_count: int,
    car_tracks: Any = None,
    car_count: int = 0,
    car_count_label: str = "VEHICLES IN VIEW",
    zone_polygon: list[tuple[int, int]] | np.ndarray | None = None,
    target_matches: dict[int, Any] | None = None,
    track_states: dict[int, Any] | None = None,
    plate_results: dict[int, Any] | None = None,
    zone_enabled: bool = False,
    in_zone_ids: set[int] | frozenset[int] | None = None,
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
        plate_results: Optional dict mapping vehicle track_id -> PlateTrackState.
        zone_enabled: If True, renders ROI polygon and highlights in-zone vehicles.
        in_zone_ids: Optional set of tracker_ids located inside the counting zone.

    Returns:
        np.ndarray: Annotated BGR frame copy.
    """
    if frame is None:
        return frame

    # Work on a copy to keep original frame pristine
    canvas = frame.copy()
    h, w = canvas.shape[:2]

    # 1. Draw Zone Polygon ONLY when Zone is explicitly enabled
    if zone_enabled and zone_polygon is not None:
        poly_arr = np.array(zone_polygon, dtype=np.int32)
        # Semi-transparent overlay to clearly delineate the zone
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [poly_arr], color=(0, 200, 255))
        cv2.addWeighted(overlay, 0.12, canvas, 0.88, 0, canvas)
        # Bright yellow boundary with corner indicators
        cv2.polylines(canvas, [poly_arr], isClosed=True, color=(0, 255, 255), thickness=2, lineType=cv2.LINE_AA)
        # Draw label on polygon top-left
        pts = poly_arr.reshape(-1, 2)
        top_idx = np.argmin(pts[:, 1])
        lbl_x, lbl_y = int(pts[top_idx, 0]), max(20, int(pts[top_idx, 1]) - 8)
        cv2.putText(
            canvas,
            "COUNTING ZONE (ACTIVE)",
            (lbl_x, lbl_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

    font = cv2.FONT_HERSHEY_SIMPLEX


    # 2. Draw Vehicle Tracks (Amber / Orange theme with Plate Overlay)
    car_xyxy = getattr(car_tracks, "xyxy", None) if car_tracks is not None else None
    car_tracker_id = getattr(car_tracks, "tracker_id", None) if car_tracks is not None else None
    car_confidence = getattr(car_tracks, "confidence", None) if car_tracks is not None else None
    car_class_id = getattr(car_tracks, "class_id", None) if car_tracks is not None else None

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
            cls_id = int(car_class_id[i]) if car_class_id is not None and i < len(car_class_id) else 2
            v_type_str = getattr(config, "VEHICLE_CLASSES", {}).get(cls_id, "vehicle").upper()

            # Check if this vehicle has an identified license plate
            plate_info = None
            if cid is not None and plate_results is not None:
                plate_info = plate_results.get(int(cid))

            plate_text = getattr(plate_info, "plate_text", "") if plate_info is not None else ""
            plate_conf = getattr(plate_info, "confidence", 0.0) if plate_info is not None else 0.0
            plate_bbox_native = getattr(plate_info, "plate_bbox_native", None) if plate_info is not None else None

            # If Zone is active, distinguish whether vehicle is inside counting zone
            is_in_zone = True
            if zone_enabled and in_zone_ids is not None:
                is_in_zone = cid is not None and int(cid) in in_zone_ids

            # Distinct Amber/Orange color for vehicles; Vibrant Yellow/Gold if plate identified
            if plate_text:
                car_color = (0, 215, 255) if is_in_zone else (140, 160, 175)
                car_thickness = 2
                zone_prefix = "[ZONE] " if (zone_enabled and in_zone_ids is not None and is_in_zone) else ""
                car_label = f"{zone_prefix}{v_type_str} | C-{cid} | [{plate_text}] {plate_conf:.2f}"
            else:
                if is_in_zone:
                    car_color = (11, 158, 245)
                    zone_prefix = "[ZONE] " if (zone_enabled and in_zone_ids is not None) else ""
                else:
                    car_color = (120, 125, 135)  # Muted slate for vehicles outside counting zone
                    zone_prefix = "[OUT] "

                car_thickness = 2
                if cid is not None and conf is not None:
                    car_label = f"{zone_prefix}{v_type_str} | C-{cid} | {conf:.2f}"
                elif cid is not None:
                    car_label = f"{zone_prefix}{v_type_str} | C-{cid}"
                elif conf is not None:
                    car_label = f"{zone_prefix}{v_type_str} | {conf:.2f}"
                else:
                    car_label = f"{zone_prefix}{v_type_str}"

            cv2.rectangle(canvas, (x1, y1), (x2, y2), car_color, car_thickness, cv2.LINE_AA)


            # Draw license plate box on vehicle if localized
            if plate_bbox_native is not None:
                px1, py1, px2, py2 = plate_bbox_native
                px1 = max(0, min(int(px1), w - 1))
                py1 = max(0, min(int(py1), h - 1))
                px2 = max(0, min(int(px2), w - 1))
                py2 = max(0, min(int(py2), h - 1))
                if px2 > px1 and py2 > py1:
                    cv2.rectangle(canvas, (px1, py1), (px2, py2), (0, 255, 0), 2, cv2.LINE_AA)

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

    # 4. Top HUD Status Bar
    hud_bg = canvas.copy()
    cv2.rectangle(hud_bg, (0, 0), (w, 36), (15, 23, 42), -1)
    cv2.addWeighted(hud_bg, 0.75, canvas, 0.25, 0, canvas)
    cv2.line(canvas, (0, 36), (w, 36), (51, 65, 85), 1)

    hud_text = f"PEOPLE: {people_count}  |  {car_count_label}: {car_count}"
    cv2.putText(canvas, hud_text, (16, 24), font, 0.60, (255, 255, 255), 2, cv2.LINE_AA)

    zone_status_text = "[ZONE: ACTIVE]" if zone_enabled else "[ZONE: OFF - FULL VIEW]"
    zone_color = (0, 220, 255) if zone_enabled else (148, 163, 184)
    cv2.putText(canvas, zone_status_text, (max(16, w - 260), 24), font, 0.55, zone_color, 2, cv2.LINE_AA)

    return canvas
