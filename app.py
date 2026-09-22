"""Application Pipeline Orchestrator for DATT - AI People Counter.

Phase 3.2: Headless CUDA Runtime with Realtime Telemetry Logging.
Replaces cv2.imshow with realtime logging suitable for Google Colab GPU / Server.

Pipeline:
    CameraReader (Stream) -> YOLODetector (CUDA) -> PersonTracker (ByteTrack) -> ZoneCounter (Occupancy) -> Realtime Log
"""

import argparse
from pathlib import Path
import sys
import time

import config
from src.counter.zone_counter import ZoneCounter
from src.detector.yolo_detector import YOLODetector
from src.stream.youtube_stream import CameraReader
from src.tracker.bytetrack_tracker import PersonTracker
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
) -> None:
    """Log realtime HUD telemetry replacing OpenCV GUI display."""
    logger.info(
        "\n"
        "==================== [REALTIME HUD] ====================\n"
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


def run_pipeline(max_frames: int | None = None) -> dict:
    """Execute the end-to-end people counter pipeline without cv2.imshow."""
    logger.info("==================================================")
    logger.info("Starting DATT - AI People Counter (Phase 3.2 Colab CUDA)")
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

    logger.info("Initializing CameraReader (%s)...", config.YOUTUBE_LINK)
    camera = CameraReader(
        url=config.YOUTUBE_LINK,
        width=config.WIDTH,
        height=config.HEIGHT,
    )

    fps_meter = FPSMeter(window_seconds=1.0)

    logger.info("Starting camera stream...")
    camera.start()
    logger.info("Stream started. Telemetry will be logged in realtime.")

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
            # 1. Read newest frame from CameraReader
            frame = camera.read(timeout=2.0)
            if frame is None:
                if camera.finished:
                    logger.warning("Stream finished or camera stopped.")
                    break
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

            # 5. Measure Processing FPS & Output Realtime HUD Log
            fps_updated = fps_meter.tick()
            if fps_updated or total_frames == 1:
                log_realtime_hud(
                    device=detector.device_type,
                    gpu=detector.device_name,
                    vram_mb=detector.vram_allocated_mb,
                    stream_fps=camera.stream_fps,
                    processing_fps=fps_meter.fps,
                    yolo_latency_ms=last_yolo_ms,
                    pipeline_latency_ms=last_pipeline_ms,
                    detection_count=last_det_count,
                    track_count=last_track_count,
                    people_in_view=last_people_in_view,
                )

            if max_frames is not None and total_frames >= max_frames:
                logger.info("Reached maximum requested frames (%d). Stopping.", max_frames)
                break

    except KeyboardInterrupt:
        logger.info("Interrupted by user (Ctrl+C).")
    finally:
        logger.info("Stopping camera reader and releasing resources...")
        camera.stop()
        logger.info("Pipeline stopped cleanly.")

    # Calculate final benchmark summary
    avg_yolo = sum(yolo_latencies) / max(len(yolo_latencies), 1)
    avg_pipeline = sum(pipeline_latencies) / max(len(pipeline_latencies), 1)
    return {
        "total_frames": total_frames,
        "avg_yolo_ms": avg_yolo,
        "avg_pipeline_ms": avg_pipeline,
        "stream_fps": camera.stream_fps,
        "processing_fps": fps_meter.fps,
        "device": detector.device_type,
        "gpu": detector.device_name,
        "vram_mb": detector.vram_allocated_mb,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="DATT - AI People Counter (Phase 3.2)")
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Maximum frames to process (default: run indefinitely)",
    )
    args = parser.parse_args()
    run_pipeline(max_frames=args.max_frames)


if __name__ == "__main__":
    main()
