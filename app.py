"""Application Pipeline Orchestrator for DATT - AI People Counter.

Phase 3.2: Headless CUDA Runtime with Realtime Telemetry Logging.
Replaces cv2.imshow with realtime logging suitable for Google Colab GPU / Server.

Pipeline:
    CameraReader (Stream) -> YOLODetector (CUDA) -> PersonTracker (ByteTrack) -> ZoneCounter (Occupancy) -> Realtime Log
"""

import argparse
from pathlib import Path
import sys
import threading
import time

import config
from src.counter.zone_counter import ZoneCounter
from src.detector.yolo_detector import YOLODetector
from src.events.event_manager import event_manager
from src.runtime.shared_state import shared_state
from src.stream.camera_manager import CameraManager
from src.tracker.bytetrack_tracker import PersonTracker
from src.ui.frame_renderer import render_frame
from src.ui.video_stream import start_stream_server
from src.utils.fps import FPSMeter
from src.utils.logger import logger


def log_realtime_hud(
    device: str,
    gpu: str,
    vram_mb: float,
    stream_fps: float,
    processing_fps: float,
    yolo_latency_ms: float,
    pipeline_latency_ms: float,
    detection_count: int,
    track_count: int,
    people_in_view: int,
    camera_name: str = "",
    input_res: str = "1280x720",
    inference_res: str = "960x960",
) -> None:
    """Log realtime HUD telemetry replacing OpenCV GUI display."""
    cam_str = f" [{camera_name}]" if camera_name else ""
    logger.info(
        "\n"
        "==================== [REALTIME HUD%s] ====================\n"
        "Input:            %s\n"
        "Inference:        %s\n"
        "Device:           %s\n"
        "GPU:              %s\n"
        "VRAM:             %.1f MB\n"
        "Stream FPS:       %.1f\n"
        "Processing FPS:   %.1f\n"
        "YOLO latency:     %.1f ms\n"
        "Pipeline latency: %.1f ms\n"
        "Detection count:  %d\n"
        "Track count:      %d\n"
        "People in view:   %d\n"
        "========================================================",
        cam_str,
        input_res,
        inference_res,
        device,
        gpu,
        vram_mb,
        stream_fps,
        processing_fps,
        yolo_latency_ms,
        pipeline_latency_ms,
        detection_count,
        track_count,
        people_in_view,
    )


def run_pipeline(
    max_frames: int | None = None,
    ui_mode: bool = False,
    host: str = "0.0.0.0",
    port: int = 8000,
    camera_id: str | None = None,
    stop_event: threading.Event | None = None,
    img_size: int | None = None,
) -> dict:
    """Execute the end-to-end people counter pipeline.

    Supports Normal CLI mode (Phase 3.2) and UI mode (Phase 4 Version 3) with
    CameraManager, EventManager, MJPEG streaming & shared runtime state.
    """
    if img_size is not None:
        config.IMG_SIZE = img_size

    logger.info("==================================================")
    mode_desc = "Phase 4 Version 3 Camera & Event System" if ui_mode else "Phase 3.2 Colab CUDA"
    logger.info("Starting DATT - AI People Counter (%s)", mode_desc)
    logger.info("Inference resolution: %dx%d", config.IMG_SIZE, config.IMG_SIZE)
    logger.info("==================================================")

    # 1. Initialize Components
    logger.info("Initializing YOLODetector...")
    detector = YOLODetector(config)
    logger.info(
        "Detector active on device: %s (%s, GPU: %s)",
        detector.device,
        detector.device_type,
        detector.device_name,
    )

    logger.info("Initializing PersonTracker (ByteTrack)...")
    tracker = PersonTracker(config)

    logger.info("Initializing ZoneCounter...")
    counter = ZoneCounter(
        polygon=config.ZONE_POLYGON,
        person_class_id=config.PERSON_CLASS_ID,
    )

    logger.info("Initializing CameraManager...")
    camera_mgr = CameraManager()
    active_cam = camera_mgr.start_camera(camera_id)
    shared_state.set_camera(active_cam.id, active_cam.name)

    fps_meter = FPSMeter(window_seconds=1.0)

    # Start MJPEG Video Stream Server if in UI mode
    server = None
    if ui_mode:
        logger.info("Starting MJPEG Stream Server at http://%s:%d...", host, port)
        server = start_stream_server(host=host, port=port, state=shared_state, camera_manager=camera_mgr)
        shared_state.set_status("RUNNING")
        logger.info("MJPEG video stream:  http://%s:%d/video_feed", host, port)
        logger.info("Realtime telemetry:  http://%s:%d/telemetry", host, port)
        logger.info("Camera API:          http://%s:%d/cameras", host, port)
        logger.info("Events API:          http://%s:%d/events", host, port)
        logger.info("To launch dashboard: streamlit run src/ui/dashboard.py")

    logger.info("Camera stream started on '%s' (%s).", active_cam.name, active_cam.url)

    total_frames = 0
    yolo_latencies = []
    pipeline_latencies = []
    last_yolo_ms = 0.0
    last_pipeline_ms = 0.0
    last_det_count = 0
    last_track_count = 0
    last_people_in_view = 0

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("Stop event signaled. Halting AI pipeline loop.")
                break

            # Check if camera was switched externally (via Dashboard / HTTP endpoint)
            current_cam = camera_mgr.get_active_camera()
            if current_cam is not None and current_cam.id != active_cam.id:
                logger.info(
                    "Detected runtime camera switch: '%s' -> '%s'. Resetting tracker.",
                    active_cam.id,
                    current_cam.id,
                )
                active_cam = current_cam
                tracker.reset()
                counter.people_count = 0
                event_manager.reset()
                shared_state.set_camera(active_cam.id, active_cam.name)

            # 1. Read newest frame from CameraManager
            frame = camera_mgr.read(timeout=2.0)
            if frame is None:
                if camera_mgr.status == "ERROR":
                    shared_state.set_status("ERROR", camera_mgr.error_reason)
                if camera_mgr.finished:
                    time.sleep(0.01)
                    continue
                time.sleep(0.001)
                continue

            # Start total pipeline timer
            pipeline_t0 = time.perf_counter()

            # 2. Detect with YOLO (PyTorch CUDA)
            detections = detector.detect(frame)
            last_yolo_ms = detector.last_yolo_ms

            # 3. Update ByteTrack
            tracks = tracker.update(detections)

            # 4. Update Zone Occupancy Counter
            people_in_view = counter.update(tracks, frame_shape=frame.shape)

            # Measure total pipeline latency (detection + tracking + counting)
            last_pipeline_ms = (time.perf_counter() - pipeline_t0) * 1000

            total_frames += 1
            yolo_latencies.append(last_yolo_ms)
            pipeline_latencies.append(last_pipeline_ms)

            last_det_count = len(detections)
            last_track_count = len(tracks)
            last_people_in_view = people_in_view

            # 5. UI Observation & Event Layer (Non-blocking latest-frame update)
            if ui_mode:
                annotated_frame = render_frame(
                    frame=frame,
                    tracks=tracks,
                    people_count=last_people_in_view,
                    zone_polygon=config.ZONE_POLYGON,
                )
                # Process occupancy events asynchronously
                event_manager.process_frame(
                    camera_id=active_cam.id,
                    people_count=last_people_in_view,
                    annotated_frame=annotated_frame,
                )
                shared_state.update(
                    latest_frame=frame,
                    annotated_frame=annotated_frame,
                    people_count=last_people_in_view,
                    detection_count=last_det_count,
                    track_count=last_track_count,
                    stream_fps=camera_mgr.stream_fps,
                    processing_fps=fps_meter.fps,
                    yolo_latency_ms=last_yolo_ms,
                    pipeline_latency_ms=last_pipeline_ms,
                    device=detector.device_type,
                    gpu_name=detector.device_name,
                    vram_mb=detector.vram_allocated_mb,
                    model_name="YOLO11s",
                    input_size=f"{config.IMG_SIZE}x{config.IMG_SIZE}",
                    camera_id=active_cam.id,
                    camera_name=active_cam.name,
                )

            # 6. Measure Processing FPS & Output Realtime HUD Log
            fps_updated = fps_meter.tick()
            if fps_updated or total_frames == 1:
                log_realtime_hud(
                    device=detector.device_type,
                    gpu=detector.device_name,
                    vram_mb=detector.vram_allocated_mb,
                    stream_fps=camera_mgr.stream_fps,
                    processing_fps=fps_meter.fps,
                    yolo_latency_ms=last_yolo_ms,
                    pipeline_latency_ms=last_pipeline_ms,
                    detection_count=last_det_count,
                    track_count=last_track_count,
                    people_in_view=last_people_in_view,
                    camera_name=active_cam.name,
                    input_res=f"{active_cam.width}x{active_cam.height}",
                    inference_res=f"{config.IMG_SIZE}x{config.IMG_SIZE}",
                )

            if max_frames is not None and total_frames >= max_frames:
                logger.info("Reached maximum requested frames (%d). Stopping.", max_frames)
                break

    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C).")
    except Exception as exc:
        logger.error("Error in AI pipeline: %s", exc, exc_info=True)
        if ui_mode:
            shared_state.set_status("ERROR", str(exc))
        raise
    finally:
        logger.info("Stopping camera manager and releasing resources...")
        camera_mgr.stop_camera()
        event_manager.stop()
        if server is not None:
            logger.info("Stopping MJPEG stream server...")
            server.stop()
        if ui_mode:
            shared_state.set_status("STOPPED")
        logger.info("Pipeline stopped cleanly.")

    # Calculate final benchmark summary
    avg_yolo = sum(yolo_latencies) / max(len(yolo_latencies), 1)
    avg_pipeline = sum(pipeline_latencies) / max(len(pipeline_latencies), 1)
    return {
        "total_frames": total_frames,
        "avg_yolo_ms": avg_yolo,
        "avg_pipeline_ms": avg_pipeline,
        "stream_fps": camera_mgr.stream_fps,
        "processing_fps": fps_meter.fps,
        "device": detector.device_type,
        "gpu": detector.device_name,
        "vram_mb": detector.vram_allocated_mb,
    }


def main() -> None:
    """Main CLI entry point (retained for backward compatibility).

    Delegates execution to the unified runtime in src/main.py.
    """
    from src.main import main as run_unified_main
    run_unified_main()


if __name__ == "__main__":
    main()



