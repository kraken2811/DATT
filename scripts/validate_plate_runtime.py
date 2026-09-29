"""Real-video vehicle/OCR audit, without face or persistence side effects.

Run from project root with a real local recording (no looping or generated frames):
python scripts/validate_plate_runtime.py --video PATH --frames 500 --output scratch/plate_runtime.json
FPS covers detection, ByteTrack, async scheduling, rendering, JPEG and telemetry;
it is NOT a measurement of app.py with Face/Event Persistence enabled.
"""
import argparse
import json
import logging
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
import config
from src.detector.yolo_detector import YOLODetector
from src.tracker.bytetrack_tracker import CarTracker
from src.ocr.plate_reader import LicensePlateReader
from src.ocr.plate_tracker import VehiclePlateManager
from src.runtime.shared_state import SharedRuntimeState
from src.ui.frame_renderer import render_frame


class AuditManager(VehiclePlateManager):
    def __init__(self, reader):
        super().__init__(reader, async_worker=True)
        self.observations = []

    def _apply_ocr_result(self, job, candidate):
        super()._apply_ocr_result(job, candidate)
        with self._lock:
            state = self._plate_states.get(job.track_id)
            native_size = None
            if candidate and getattr(candidate, "raw_crop", None) is not None and candidate.raw_crop.size > 0:
                native_size = [int(candidate.raw_crop.shape[1]), int(candidate.raw_crop.shape[0])]
            self.observations.append({
                "track_id": job.track_id,
                "frame_id": job.frame_id,
                "vehicle_class": job.vehicle_class,
                "plate_detector_conf": round(float(candidate.confidence), 3) if candidate else 0.0,
                "native_plate_size": native_size,
                "raw_ocr_result": candidate.raw_text if candidate else None,
                "normalized_result": candidate.normalized_text if candidate else None,
                "consensus_count": state.consensus_count if state else 0,
                "consensus": dict(state.vote_scores) if state else {},
                "final_confirmed_plate": state.plate_text if state else "",
                "status": state.status if state else "EXPIRED",
                "queue_size": self.ocr_queue_size,
                "worker_ms": self.last_ocr_worker_ms,
            })


def find_video_path(requested: str | None = None) -> str:
    if requested and Path(requested).is_file():
        return str(Path(requested).resolve())
    # Search locations
    search_dirs = [Path("data/uploads"), Path(r"C:\Users\User\Downloads"), Path(".")]
    for s_dir in search_dirs:
        if s_dir.exists():
            matches = list(s_dir.glob("*9_nwSrwpKYA*.mp4"))
            if matches:
                return str(matches[0].resolve())
    raise FileNotFoundError("Could not find video file '*9_nwSrwpKYA*.mp4'")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default=None, help="Video path or auto-detect")
    parser.add_argument("--frames", type=int, default=500)
    parser.add_argument("--start-frame", type=int, default=0,
                        help="Skip to a source frame; track IDs may differ after seeking")
    parser.add_argument("--output", default="scratch/plate_runtime.json")
    args = parser.parse_args()
    if args.frames < 500:
        parser.error("Runtime validation requires at least 500 real frames")
    if args.start_frame < 0:
        parser.error("--start-frame must be nonnegative")
    video_path = find_video_path(args.video)
    print(f"Using runtime video: {video_path}", flush=True)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(output.with_suffix(".log")), level=logging.INFO, force=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open supplied video: {video_path}")
    if args.start_frame:
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.start_frame)
    detector, tracker = YOLODetector(config), CarTracker(config)
    reader = LicensePlateReader()
    if not reader.initialize():
        raise RuntimeError("EasyOCR failed to initialize")
    manager, state = AuditManager(reader), SharedRuntimeState()
    count, queue_max, mismatches = 0, 0, 0
    yolo_times = []
    start = time.perf_counter()
    try:
        while count < args.frames:
            ok, frame = cap.read()
            if not ok:
                break
            count += 1
            t_yolo_0 = time.perf_counter()
            detections = detector.detect(frame)
            yolo_times.append((time.perf_counter() - t_yolo_0) * 1000)

            mask = np.isin(detections.class_id, config.VEHICLE_CLASS_IDS)
            tracks = tracker.update({"xyxy": detections.xyxy[mask],
                "confidence": detections.confidence[mask], "class_id": detections.class_id[mask]})
            plates = manager.process_vehicle_tracks(frame, vehicle_tracks=tracks,
                                                    frame_id=args.start_frame + count)
            canvas = render_frame(frame=frame, tracks=None, people_count=0, car_tracks=tracks,
                                  car_count=len(tracks), plate_results=plates)
            ok, jpeg = cv2.imencode(".jpg", canvas)
            state.update(latest_frame=frame, annotated_frame=canvas, car_count=len(tracks),
                         vehicles_in_view=len(tracks), track_count=len(tracks),
                         jpeg_bytes=jpeg.tobytes() if ok else None)
            fid, _, _, _ = state.get_frame_for_stream()
            telemetry = state.get_telemetry()
            mismatches += int(fid != telemetry.frame_id or telemetry.vehicles_in_view != len(tracks))
            queue_max = max(queue_max, manager.ocr_queue_size)
            if count % 50 == 0:
                print(f"frames={count} fps={count/(time.perf_counter()-start):.2f} yolo_ms={np.mean(yolo_times[-50:]):.1f} queue={manager.ocr_queue_size}", flush=True)
    finally:
        elapsed = time.perf_counter() - start
        cap.release()
        # Allow async worker a moment to finish any in-flight job
        time.sleep(0.5)
        if manager._worker:
            manager._worker.stop()
        with manager._lock:
            observations = list(manager.observations)
            all_plate_states = manager.get_all_plate_states()

        worker_times = [entry["worker_ms"] for entry in observations if entry.get("worker_ms")]
        
        # Build track summaries
        track_summaries = {}
        for obs in observations:
            tid = obs["track_id"]
            if tid not in track_summaries:
                track_summaries[tid] = {
                    "track_id": tid,
                    "vehicle_class": obs["vehicle_class"],
                    "obs_count": 0,
                    "raw_results": [],
                    "normalized_results": [],
                    "statuses": [],
                    "consensus_counts": [],
                    "final_plate": "",
                    "native_sizes": [],
                }
            ts = track_summaries[tid]
            ts["obs_count"] += 1
            if obs["raw_ocr_result"]:
                ts["raw_results"].append(obs["raw_ocr_result"])
            if obs["normalized_result"]:
                ts["normalized_results"].append(obs["normalized_result"])
            ts["statuses"].append(obs["status"])
            ts["consensus_counts"].append(obs["consensus_count"])
            if obs["native_plate_size"]:
                ts["native_sizes"].append(obs["native_plate_size"])
            if obs["final_confirmed_plate"]:
                ts["final_plate"] = obs["final_confirmed_plate"]

        report = {
            "source": video_path,
            "frames": count,
            "start_frame": args.start_frame,
            "completed_500_real_frames": count >= 500,
            "device": detector.device,
            "scope": "vehicle pipeline; excludes Face/Event Persistence",
            "main_loop_fps": count / max(elapsed, 1e-9),
            "yolo_ms_mean": float(np.mean(yolo_times)) if yolo_times else None,
            "yolo_ms_p95": float(np.percentile(yolo_times, 95)) if yolo_times else None,
            "queue_max": queue_max,
            "telemetry_mismatches": mismatches,
            "ocr_jobs_completed": len(observations),
            "ocr_worker_ms_mean": float(np.mean(worker_times)) if worker_times else None,
            "ocr_worker_ms_p95": float(np.percentile(worker_times, 95)) if worker_times else None,
            "track_summaries": track_summaries,
            "observations": observations,
        }
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if count < 500:
        raise RuntimeError(f"Only {count} real frames available; validation incomplete")
    print(f"Saved real-video audit: {output}")


if __name__ == "__main__":
    main()
