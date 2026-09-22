"""Application Pipeline Orchestrator for DATT - AI People Counter.

Coordinates:
    CameraReader (Stream) -> YOLODetector (ONNX) -> PersonTracker (ByteTrack) -> ZoneCounter (Occupancy) -> HUD
"""

from pathlib import Path
import time

import cv2
import supervision as sv

import config
from src.counter.zone_counter import ZoneCounter
from src.detector.yolo_detector import YOLODetector
from src.stream.youtube_stream import CameraReader
from src.tracker.bytetrack_tracker import PersonTracker
from src.utils.fps import FPSMeter
from src.utils.logger import logger


def draw_hud(
    frame,
    model_name: str,
    img_size: int,
    tile_count: int,
    num_detections: int,
    num_tracks: int,
    yolo_ms: float,
    detection_ms: float,
    stream_fps: float,
    processing_fps: float,
    frame_age_ms: float,
    capture_latency_ms: float,
    people_in_view: int,
) -> None:
    """Render performance and tracking telemetry HUD overlay on frame."""
    debug_lines = [
        f"Model: {model_name}",
        f"Input: {img_size}",
        f"Tiles: {tile_count}",
        "",
        f"Detections: {num_detections}",
        f"Tracks: {num_tracks}",
        "",
        f"YOLO latency: {yolo_ms:.0f} ms",
        f"Detection latency: {detection_ms:.0f} ms",
        "",
        f"Stream FPS: {stream_fps:.1f}",
        f"Processing FPS: {processing_fps:.1f}",
        f"Frame age: {frame_age_ms:.0f} ms",
        f"Capture latency: {capture_latency_ms:.0f} ms",
        "",
        f"People in view: {people_in_view}",
    ]

    y = 26
    for line in debug_lines:
        if line == "":
            y += 6
            continue
        cv2.putText(
            frame,
            line,
            (16, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
        )
        y += 22


def main() -> None:
    logger.info("==================================================")
    logger.info("Starting DATT - AI People Counter (Phase 2 Refactored)")
    logger.info("==================================================")

    # 1. Initialize Components
    logger.info("Initializing YOLODetector...")
    detector = YOLODetector(config)

    logger.info("Initializing PersonTracker (ByteTrack)...")
    tracker = PersonTracker(config)

    logger.info("Initializing ZoneCounter...")
    counter = ZoneCounter(
        polygon=config.ZONE_POLYGON,
        person_class_id=config.PERSON_CLASS_ID,
    )

    logger.info("Initializing CameraReader (%s)...", config.YOUTUBE_LINK)
    camera = CameraReader(
        url=config.YOUTUBE_LINK,
        width=config.WIDTH,
        height=config.HEIGHT,
    )

    # Annotators for visualization
    box_annotator = sv.BoxAnnotator(thickness=2)
    label_annotator = sv.LabelAnnotator(text_scale=0.5, text_thickness=1)
    class_names = {config.PERSON_CLASS_ID: "Person"}

    show_raw = config.SHOW_RAW_DETECTIONS
    fps_meter = FPSMeter(window_seconds=1.0)
    model_filename = Path(config.MODEL_PATH).name

    logger.info("Starting camera stream...")
    camera.start()
    logger.info("Controls: Press 'q' to quit, 'd' to toggle raw detections / tracking.")

    gui_available = True
    try:
        while True:
            # 1. Read newest frame
            frame = camera.read(timeout=2.0)
            if frame is None:
                if camera.finished:
                    logger.warning("Stream ended or camera stopped.")
                    break
                # Yield slightly while waiting
                time.sleep(0.001)
                continue

            # 2. Detect with YOLO ONNX
            t0 = time.perf_counter()
            detections = detector.detect(frame)
            detection_ms = (time.perf_counter() - t0) * 1000

            # 3. Update ByteTrack
            tracks = tracker.update(detections)

            # 4. Count people in zone / full frame
            people_in_view = counter.update(tracks, frame_shape=frame.shape)

            # 5. Measure Processing FPS & log telemetry
            fps_updated = fps_meter.tick()
            if fps_updated:
                logger.info(
                    "Stream FPS: %.1f | Proc FPS: %.1f | YOLO: %.0fms | Det: %.0fms | Dets: %d | Tracks: %d | People: %d",
                    camera.stream_fps,
                    fps_meter.fps,
                    detector.last_yolo_ms,
                    detection_ms,
                    len(detections),
                    len(tracks),
                    people_in_view,
                )

            # 6. Build labels & annotate frame
            display_detections = (
                sv.Detections(
                    xyxy=detections.xyxy,
                    confidence=detections.confidence,
                    class_id=detections.class_id,
                )
                if show_raw
                else tracks
            )

            labels = []
            if (
                display_detections.class_id is not None
                and display_detections.confidence is not None
            ):
                for i, cls in enumerate(display_detections.class_id):
                    score = float(display_detections.confidence[i])
                    if show_raw:
                        identity = "YOLO"
                    elif display_detections.tracker_id is not None:
                        identity = f"#{display_detections.tracker_id[i]}"
                    else:
                        identity = "pending"
                    labels.append(f"{class_names.get(int(cls), 'Obj')} {identity} {score:.2f}")

            frame = box_annotator.annotate(scene=frame, detections=display_detections)  # type: ignore
            frame = label_annotator.annotate(  # type: ignore
                scene=frame, detections=display_detections, labels=labels
            )

            # Draw HUD
            draw_hud(
                frame=frame,
                model_name=model_filename,
                img_size=config.IMG_SIZE,
                tile_count=detector.last_tile_count,
                num_detections=len(detections),
                num_tracks=len(tracks),
                yolo_ms=detector.last_yolo_ms,
                detection_ms=detection_ms,
                stream_fps=camera.stream_fps,
                processing_fps=fps_meter.fps,
                frame_age_ms=camera.last_frame_age_ms,
                capture_latency_ms=camera.last_capture_latency_ms,
                people_in_view=people_in_view,
            )

            # 7. GUI Display with Headless Fallback
            if gui_available:
                try:
                    cv2.imshow("DATT - AI People Counter (Phase 2)", frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        logger.info("User requested quit ('q').")
                        break
                    if key == ord("d"):
                        show_raw = not show_raw
                        logger.info("Toggled raw detections: %s", show_raw)
                except cv2.error:
                    gui_available = False
                    logger.warning("No GUI display available (headless mode). Continuing headless.")

    finally:
        logger.info("Stopping camera reader and releasing resources...")
        camera.stop()
        if gui_available:
            try:
                cv2.destroyAllWindows()
            except cv2.error:
                pass
        logger.info("Pipeline stopped cleanly.")


if __name__ == "__main__":
    main()
