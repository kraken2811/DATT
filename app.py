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

import cv2
import numpy as np
import supervision as sv

import config
from src.counter.zone_counter import CarCounter, ZoneCounter
from src.detector.yolo_detector import DetectionsData, YOLODetector
from src.events.event_manager import event_manager
from src.ocr.plate_tracker import vehicle_plate_manager
from src.recognition.target_matcher import target_matcher
from src.runtime.shared_state import shared_state
from src.stream.camera_manager import CameraManager
from src.tracker.bytetrack_tracker import CarTracker, PersonTracker
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
    car_in_view: int = 0,
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
        "Cars in view:     %d\n"
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
        car_in_view,
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
    logger.info("Starting DATT - AI Vision Monitor (%s)", mode_desc)
    logger.info("Inference resolution: %dx%d", config.IMG_SIZE, config.IMG_SIZE)
    logger.info("==================================================")

    # 1. Initialize Components
    logger.info("Initializing YOLODetector...")
    detector = YOLODetector(config)
    logger.info("Warming up YOLODetector (persistent GPU/VRAM)...")
    detector.warmup()
    logger.info(
        "Detector active on device: %s (%s, GPU: %s)",
        detector.device,
        detector.device_type,
        detector.device_name,
    )

    logger.info("Initializing PersonTracker & CarTracker (ByteTrack)...")
    tracker = PersonTracker(config)
    car_tracker = CarTracker(config)

    logger.info("Initializing ZoneCounter & CarCounter...")
    counter = ZoneCounter(
        polygon=config.ZONE_POLYGON,
        person_class_id=config.PERSON_CLASS_ID,
    )
    car_counter = CarCounter(
        polygon=config.ZONE_POLYGON,
        car_class_id=getattr(config, "CAR_CLASS_ID", 2),
    )

    logger.info("Initializing CameraManager...")
    camera_mgr = CameraManager()
    active_cam = None
    if camera_id is not None:
        active_cam = camera_mgr.start_camera(camera_id)
        shared_state.set_camera(active_cam.id, active_cam.name)
    else:
        shared_state.set_camera("", "")

    fps_meter = FPSMeter(window_seconds=1.0)

    # Start MJPEG Video Stream Server if in UI mode
    server = None
    if ui_mode:
        logger.info("Starting MJPEG Stream Server at http://%s:%d...", host, port)
        server = start_stream_server(host=host, port=port, state=shared_state, camera_manager=camera_mgr)
        if active_cam is not None:
            shared_state.set_status("RUNNING")
            logger.info("Camera stream started on '%s' (%s).", active_cam.name, active_cam.url)
        else:
            shared_state.set_status("IDLE")
            logger.info("No initial camera specified. Waiting for user camera selection...")
        logger.info("MJPEG video stream:  http://%s:%d/video_feed", host, port)
        logger.info("Realtime telemetry:  http://%s:%d/telemetry", host, port)
        logger.info("Camera API:          http://%s:%d/cameras", host, port)
        logger.info("Events API:          http://%s:%d/events", host, port)

    total_frames = 0
    yolo_latencies = []
    pipeline_latencies = []
    last_yolo_ms = 0.0
    last_pipeline_ms = 0.0
    last_det_count = 0
    last_track_count = 0
    last_people_in_view = 0
    last_car_in_view = 0
    prev_loop_end = 0.0
    last_detections = None

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                logger.info("Stop event signaled. Halting AI pipeline loop.")
                break

            t_loop_t0 = time.perf_counter()
            _t_loop_idle_ms = (t_loop_t0 - prev_loop_end) * 1000.0 if prev_loop_end > 0 else 0.0

            current_cam = camera_mgr.get_active_camera()
            if current_cam is None:
                if active_cam is not None:
                    active_cam = None
                    shared_state.set_camera("", "")
                    shared_state.clear_frames()
                    if shared_state.status != "ERROR":
                        shared_state.set_status("IDLE")
                time.sleep(0.05)
                continue

            # Check if camera was switched externally (via Dashboard / HTTP endpoint)
            if active_cam is None or current_cam.id != active_cam.id:
                logger.info(
                    "Detected runtime camera activation/switch: '%s' -> '%s'. Resetting trackers.",
                    active_cam.id if active_cam else "None",
                    current_cam.id,
                )
                active_cam = current_cam
                tracker.reset()
                car_tracker.reset()
                target_matcher.reset_tracks()
                vehicle_plate_manager.reset_tracks()
                counter.people_count = 0
                car_counter.car_count = 0
                event_manager.reset()
                shared_state.clear_frames()
                shared_state.set_camera(active_cam.id, active_cam.name)
                shared_state.set_status("RUNNING")
                # Pipeline has caught up with the switch; allow ERROR propagation again
                shared_state.clear_switching()

            # 1. Read newest frame from CameraManager with metadata
            t_read0 = time.perf_counter()
            frame_res = camera_mgr.read_with_meta(timeout=2.0)
            _t_source_read_ms = (time.perf_counter() - t_read0) * 1000.0
            _t_source_wait_ms = getattr(camera_mgr, "last_source_wait_ms", 0.0)
            _t_pacing_wait_ms = getattr(camera_mgr, "last_pacing_wait_ms", 0.0)

            if frame_res is None or frame_res[0] is None:
                if camera_mgr.status == "ERROR":
                    shared_state.set_status("ERROR", camera_mgr.error_reason)
                elif camera_mgr.status == "VIDEO_FINISHED":
                    shared_state.set_status("VIDEO_FINISHED")
                if camera_mgr.finished:
                    time.sleep(0.01)
                    continue
                time.sleep(0.001)
                continue

            frame, frame_seq, frame_pts = frame_res
            curr_frame_id = frame_seq

            # Frame prepare
            t_prep0 = time.perf_counter()
            if not isinstance(frame, np.ndarray) or frame.size == 0:
                continue
            _t_frame_prepare_ms = (time.perf_counter() - t_prep0) * 1000.0

            # 2. YOLO Cadence: target ~15 FPS detection cadence while video display is ~30 FPS
            # Even total_frames runs detector; odd total_frames advances Kalman filters via predict()
            is_detection_frame = (total_frames % 2 == 0)

            if is_detection_frame:
                _t_yolo_t0 = time.perf_counter()
                detections = detector.detect(frame)
                last_yolo_ms = detector.last_yolo_ms
                _t_yolo_ms = (time.perf_counter() - _t_yolo_t0) * 1000.0

                person_mask = detections.class_id == config.PERSON_CLASS_ID
                vehicle_class_ids = getattr(config, "VEHICLE_CLASS_IDS", [2, 3, 5, 7])
                vehicle_mask = np.isin(detections.class_id, vehicle_class_ids)

                person_dets = DetectionsData({
                    "xyxy": detections.xyxy[person_mask],
                    "confidence": detections.confidence[person_mask],
                    "class_id": detections.class_id[person_mask],
                })
                vehicle_dets = DetectionsData({
                    "xyxy": detections.xyxy[vehicle_mask],
                    "confidence": detections.confidence[vehicle_mask],
                    "class_id": detections.class_id[vehicle_mask],
                })

                _t_bt_t0 = time.perf_counter()
                tracks = tracker.update(person_dets)
                vehicle_tracks = car_tracker.update(vehicle_dets)
                _t_bytetrack_ms = (time.perf_counter() - _t_bt_t0) * 1000.0
                last_detections = detections
            else:
                _t_yolo_ms = 0.0
                last_yolo_ms = 0.0
                detections = last_detections if last_detections is not None else sv.Detections.empty()

                _t_bt_t0 = time.perf_counter()
                tracks = tracker.predict()
                vehicle_tracks = car_tracker.predict()
                _t_bytetrack_ms = (time.perf_counter() - _t_bt_t0) * 1000.0

            car_tracks = vehicle_tracks

            # 4. Target Matcher (face recognition)
            target_matches = target_matcher.match_tracks(
                frame=frame,
                tracks=tracks,
                frame_id=curr_frame_id,
                native_frame=frame,
            )
            track_states = target_matcher.get_all_track_states()
            _t_face_acq_ms = target_matcher.last_timings.get("acq_ms", 0.0)
            _t_face_det_ms = target_matcher.last_timings.get("det_ms", 0.0)
            _t_face_emb_ms = target_matcher.last_timings.get("emb_ms", 0.0)
            _t_face_match_ms = target_matcher.last_timings.get("match_ms", 0.0)

            # 4.1 Vehicle License Plate Recognition (non-blocking)
            plate_results = vehicle_plate_manager.process_vehicle_tracks(
                frame=frame,
                vehicle_tracks=vehicle_tracks,
                frame_id=curr_frame_id,
            )
            _t_plate_sched_ms = vehicle_plate_manager.last_timings.get("sched_ms", 0.0)
            _t_plate_enq_ms = vehicle_plate_manager.last_timings.get("enq_ms", 0.0)

            # 5. Counting Zone / Vehicles in View Mode Determination
            t_cnt0 = time.perf_counter()
            is_zone_on = shared_state.zone_enabled
            total_tracked_vehicles = (
                len(vehicle_tracks.tracker_id)
                if (vehicle_tracks is not None and getattr(vehicle_tracks, "tracker_id", None) is not None)
                else 0
            )

            # People Occupancy
            people_in_view, visible_person_ids = counter.update_and_get_visible_ids(
                tracks, frame_shape=frame.shape
            )

            if not is_zone_on:
                visible_vehicle_tracks = vehicle_tracks
                vehicles_in_view = total_tracked_vehicles
                vehicles_in_zone = 0
                car_count_label = "VEHICLES IN VIEW"
                zone_mode_str = "Full View"
                active_zone_polygon = None
                in_zone_ids = None
            else:
                visible_vehicle_tracks = vehicle_tracks
                car_in_view, in_zone_ids = car_counter.update_and_get_visible_ids(
                    vehicle_tracks, frame_shape=frame.shape
                )
                vehicles_in_view = len(in_zone_ids)
                vehicles_in_zone = len(in_zone_ids)
                car_count_label = "VEHICLES IN ZONE"
                zone_mode_str = "Selected Zone"
                active_zone_polygon = config.ZONE_POLYGON
            _t_count_ms = (time.perf_counter() - t_cnt0) * 1000.0

            # 5.1 Business Events & Vehicle Passage Tracking
            event_manager.process_vehicle_frame(
                camera_id=active_cam.id if active_cam else "camera_01",
                vehicle_tracks=visible_vehicle_tracks,
                plate_results=plate_results,
                in_zone_ids=in_zone_ids,
                zone_id="zone_1" if is_zone_on else None,
                frame=frame,
            )
            _t_event_build_ms = event_manager.last_event_build_ms
            _t_db_work_ms = event_manager.last_db_work_ms

            # Measure pipeline latency prior to UI rendering
            last_pipeline_ms = (time.perf_counter() - t_loop_t0) * 1000.0

            total_frames += 1
            yolo_latencies.append(last_yolo_ms)
            pipeline_latencies.append(last_pipeline_ms)

            last_det_count = len(detections)
            last_track_count = len(tracks) + total_tracked_vehicles
            last_people_in_view = people_in_view
            last_car_in_view = vehicles_in_view

            # 6. UI Observation & Event Layer (Non-blocking latest-frame update)
            if ui_mode:
                _t_render_t0 = time.perf_counter()
                annotated_frame = render_frame(
                    frame=frame,
                    tracks=tracks,
                    people_count=last_people_in_view,
                    car_tracks=visible_vehicle_tracks,
                    car_count=vehicles_in_view,
                    car_count_label=car_count_label,
                    zone_polygon=active_zone_polygon,
                    zone_enabled=is_zone_on,
                    in_zone_ids=in_zone_ids,
                    target_matches=target_matches,
                    track_states=track_states,
                    plate_results=plate_results,
                )
                _t_render_ms = (time.perf_counter() - _t_render_t0) * 1000.0

                # Single JPEG encode per new frame (re-used by all streaming clients)
                _t_jpeg_t0 = time.perf_counter()
                ret_enc, jpeg_buf = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                jpeg_bytes = jpeg_buf.tobytes() if ret_enc else b""
                _t_jpeg_ms = (time.perf_counter() - _t_jpeg_t0) * 1000.0

                # Process occupancy events asynchronously
                event_manager.process_frame(
                    camera_id=active_cam.id if active_cam else "camera_01",
                    people_count=last_people_in_view,
                    annotated_frame=annotated_frame,
                )
                _t_event_build_ms += event_manager.last_event_build_ms
                _t_db_work_ms += event_manager.last_db_work_ms

                t_pub0 = time.perf_counter()
                shared_state.update(
                    frame_id=curr_frame_id,
                    frame_pts=frame_pts,
                    latest_frame=frame,
                    annotated_frame=annotated_frame,
                    people_count=last_people_in_view,
                    car_count=vehicles_in_view,
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
                    capture_fps=camera_mgr.capture_fps,
                    inference_fps=fps_meter.fps,
                    dropped_frames=camera_mgr.dropped_frames,
                    buffer_age_ms=camera_mgr.buffer_age_ms,
                    decoded_frames_total=camera_mgr.decoded_frames_total,
                    decoded_fps=camera_mgr.decoded_fps,
                    paced_frames_total=camera_mgr.paced_frames_total,
                    paced_fps=camera_mgr.paced_fps,
                    frames_dropped_by_pacer=camera_mgr.frames_dropped_by_pacer,
                    jitter_buffer_frames=camera_mgr.jitter_buffer_frames,
                    jitter_buffer_ms=camera_mgr.jitter_buffer_ms,
                    last_decoded_frame_age=camera_mgr.last_decoded_frame_age,
                    last_paced_frame_age=camera_mgr.last_paced_frame_age,
                    camera_id=active_cam.id if active_cam else "camera_01",
                    camera_name=active_cam.name if active_cam else "",
                    zone_enabled=is_zone_on,
                    zone_mode=zone_mode_str,
                    car_count_label=car_count_label,
                    vehicles_in_view=total_tracked_vehicles,
                    vehicles_in_zone=vehicles_in_zone,
                    jpeg_bytes=jpeg_bytes,
                )
                _t_state_pub_ms = (time.perf_counter() - t_pub0) * 1000.0

                _t_total_loop_ms = (time.perf_counter() - t_loop_t0) * 1000.0
                _t_effective_fps = 1000.0 / max(_t_total_loop_ms, 1.0)

                # Total measured stages
                _t_lock_wait_ms = 0.0
                _t_queue_wait_ms = 0.0
                measured_stages_sum = (
                    _t_source_read_ms
                    + _t_frame_prepare_ms
                    + _t_yolo_ms
                    + _t_bytetrack_ms
                    + _t_face_acq_ms
                    + _t_face_det_ms
                    + _t_face_emb_ms
                    + _t_face_match_ms
                    + _t_plate_sched_ms
                    + _t_plate_enq_ms
                    + _t_count_ms
                    + _t_event_build_ms
                    + _t_db_work_ms
                    + _t_render_ms
                    + _t_jpeg_ms
                    + _t_state_pub_ms
                    + _t_lock_wait_ms
                    + _t_queue_wait_ms
                )
                unaccounted_ms = max(0.0, _t_total_loop_ms - measured_stages_sum)

                logger.info(
                    "[STAGE_TIMING] frame=%d total_loop_ms=%.1f unaccounted_ms=%.2f | read=%.1f (wait=%.1f) prep=%.1f yolo=%.1f bt=%.1f | face[acq=%.1f det=%.1f emb=%.1f mat=%.1f] | plate[sched=%.1f enq=%.1f] | count=%.1f ev=%.1f db=%.2f | render=%.1f jpeg=%.1f state=%.1f idle=%.1f | eff_fps=%.1f cadence=%s",
                    curr_frame_id,
                    _t_total_loop_ms,
                    unaccounted_ms,
                    _t_source_read_ms,
                    _t_source_wait_ms,
                    _t_frame_prepare_ms,
                    _t_yolo_ms,
                    _t_bytetrack_ms,
                    _t_face_acq_ms,
                    _t_face_det_ms,
                    _t_face_emb_ms,
                    _t_face_match_ms,
                    _t_plate_sched_ms,
                    _t_plate_enq_ms,
                    _t_count_ms,
                    _t_event_build_ms,
                    _t_db_work_ms,
                    _t_render_ms,
                    _t_jpeg_ms,
                    _t_state_pub_ms,
                    _t_loop_idle_ms,
                    _t_effective_fps,
                    "DETECT" if is_detection_frame else "PREDICT",
                )

                logger.info(
                    "[FRAME_SYNC] frame_id=%d pts=%.3f det_frame=%d track_frame=%d count_frame=%d render_frame=%d state_frame=%d sync=OK",
                    curr_frame_id, frame_pts, curr_frame_id, curr_frame_id, curr_frame_id, curr_frame_id, curr_frame_id
                )

            prev_loop_end = time.perf_counter()

            # 7. Measure Processing FPS & Output Realtime HUD Log
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
                    car_in_view=vehicles_in_view,
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


