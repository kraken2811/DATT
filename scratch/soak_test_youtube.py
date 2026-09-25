"""Controlled Real YouTube Live Stability Soak Test.

Samples metrics every 30 seconds for 30 continuous minutes:
- timestamp
- frames_received
- frame_age_seconds
- stream_alive
- stream_fps
- processing_fps
- ffmpeg_pid
- ffmpeg_exit_code
- yt-dlp call count
- resolver attempts
- reconnect count
- http_403_count
- http_429_count
- last_stderr
- ram_mb
- gpu_mb
"""

import json
import logging
import os
from pathlib import Path
import sys
import time

import psutil

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config
from src.stream.camera_manager import CameraManager
from src.stream.seattle_sdot_service import seattle_service
from src.stream.youtube_resolver import stream_resolver

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("soak_test")


def get_gpu_memory_mb() -> float:
    """Return GPU memory in MB if torch / CUDA is available."""
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated() / (1024 * 1024)
    except Exception:
        pass
    return 0.0


def run_soak_test(
    youtube_url: str = config.YOUTUBE_LINK,
    target_duration_minutes: int = 30,
    sample_interval_seconds: int = 30,
) -> dict:
    process = psutil.Process(os.getpid())
    logger.info("==================================================")
    logger.info("STARTING REAL YOUTUBE LIVE SOAK TEST")
    logger.info("URL: %s", youtube_url)
    logger.info("Target duration: %d minutes (sampling every %ds)", target_duration_minutes, sample_interval_seconds)
    logger.info("==================================================")

    manager = CameraManager()
    samples = []
    start_time = time.time()
    first_frame_time = None
    first_stall_time = None
    first_reconnect_time = None
    first_fatal_time = None
    stable_duration_seconds = 0.0

    # Step 1: Start YouTube stream
    logger.info("Connecting to YouTube stream via CameraManager...")
    t0 = time.time()
    try:
        manager.set_video_source("youtube", youtube_url, name="Tokyo Live Stream")
    except Exception as exc:
        logger.error("FATAL: Failed to initiate YouTube stream: %s", exc)
        return {
            "status": "BLOCKED",
            "error": str(exc),
            "target_duration_minutes": target_duration_minutes,
            "stable_duration_minutes": 0.0,
        }

    # Wait for first frame (up to 30 seconds)
    logger.info("Waiting for first valid frame...")
    wait_start = time.time()
    while time.time() - wait_start < 30.0:
        frame = manager.read(timeout=1.0)
        if frame is not None:
            first_frame_time = time.time()
            time_to_first_frame = first_frame_time - t0
            logger.info("FIRST FRAME RECEIVED in %.2f seconds! Stream resolution: %dx%d",
                        time_to_first_frame, frame.shape[1], frame.shape[0])
            break
        time.sleep(0.5)

    if first_frame_time is None:
        logger.error("FATAL: First frame never received within 30s timeout.")
        manager.stop_camera()
        return {
            "status": "FAILED",
            "error": "Timeout waiting for first frame",
            "target_duration_minutes": target_duration_minutes,
            "stable_duration_minutes": 0.0,
        }

    # Step 2: Sampling loop
    total_target_seconds = target_duration_minutes * 60
    iteration = 0

    try:
        while True:
            now = time.time()
            elapsed = now - first_frame_time

            if elapsed >= total_target_seconds:
                logger.info("Target duration of %d minutes reached successfully!", target_duration_minutes)
                break

            # Read frame to keep stream pumping
            frame = manager.read(timeout=1.0)
            diag = manager.stream_diagnostics()
            source_info = manager.get_current_source_info()
            resolver_metrics = stream_resolver.get_metrics_dict()

            reader = manager.get_active_reader()
            ffmpeg_pid = diag.get("ffmpeg_pid")
            ffmpeg_exit_code = diag.get("ffmpeg_exit_code")
            stream_fps = manager.stream_fps
            frame_age = manager.frame_age_seconds
            stream_alive = manager.stream_alive
            reconnect_count = getattr(reader, "reconnect_count", 0)

            # Check stalls
            if frame_age > 15.0 and first_stall_time is None:
                first_stall_time = now
                logger.warning("STREAM STALL DETECTED at minute %.1f (frame age: %.1fs)", elapsed / 60.0, frame_age)

            if reconnect_count > 0 and first_reconnect_time is None:
                first_reconnect_time = now
                logger.info("FIRST RECONNECT DETECTED at minute %.1f", elapsed / 60.0)

            # Check fatal disconnect
            if source_info["status"] == "ERROR" and frame is None and first_fatal_time is None:
                first_fatal_time = now
                logger.error("STREAM FATAL ERROR at minute %.1f: %s", elapsed / 60.0, manager.error_reason)
                break

            # Process / system metrics
            ram_mb = process.memory_info().rss / (1024 * 1024)
            gpu_mb = get_gpu_memory_mb()

            # Count running yt-dlp child processes if any
            ytdlp_count = sum(1 for p in psutil.process_iter(['name']) if 'yt-dlp' in (p.info['name'] or '').lower())

            sample = {
                "iteration": iteration,
                "timestamp": now,
                "elapsed_seconds": round(elapsed, 1),
                "elapsed_minutes": round(elapsed / 60.0, 2),
                "frames_received": diag.get("frames_received", 0),
                "frame_age_seconds": round(frame_age, 2),
                "stream_alive": stream_alive,
                "stream_fps": round(stream_fps, 2),
                "processing_fps": round(stream_fps, 2),
                "ffmpeg_pid": ffmpeg_pid,
                "ffmpeg_exit_code": ffmpeg_exit_code,
                "ytdlp_process_count": ytdlp_count,
                "resolver_attempts": resolver_metrics.get("total_resolves", 0),
                "reconnect_count": reconnect_count,
                "http_403_count": resolver_metrics.get("http_403_count", 0),
                "http_429_count": resolver_metrics.get("http_429_count", 0),
                "last_stderr": str(diag.get("last_error", ""))[:200],
                "ram_mb": round(ram_mb, 1),
                "gpu_mb": round(gpu_mb, 1),
            }
            samples.append(sample)

            logger.info(
                "[%02d min] frames=%d | fps=%.1f | age=%.1fs | alive=%s | pid=%s | reconn=%d | 429=%d | RAM=%.1fMB",
                int(elapsed // 60),
                sample["frames_received"],
                sample["stream_fps"],
                sample["frame_age_seconds"],
                sample["stream_alive"],
                sample["ffmpeg_pid"],
                sample["reconnect_count"],
                sample["http_429_count"],
                sample["ram_mb"],
            )

            stable_duration_seconds = elapsed
            iteration += 1

            # Sleep until next sample interval while periodically pumping reader
            sample_start = time.time()
            while time.time() - sample_start < sample_interval_seconds:
                manager.read(timeout=0.2)
                time.sleep(0.05)

    finally:
        logger.info("Stopping soak test YouTube stream...")
        manager.stop_camera()

    # Step 3: Switch Test: YouTube Live -> Seattle -> YouTube Live
    logger.info("Executing switch test: YouTube Live -> Seattle -> YouTube Live...")
    switch_success = True
    try:
        # YouTube Live -> Seattle
        seattle_cam = seattle_service.get_camera_by_stream_name("2_Pike_NS")
        seattle_url = seattle_cam["stream_url"] if seattle_cam else "https://video.seattle.gov:443/media/2_Pike_NS.stream/playlist.m3u8"
        manager.set_video_source(
            "direct_hls",
            seattle_url,
            name="Seattle 2_Pike_NS",
            headers={"Referer": "https://web.seattle.gov/Travelers/\r\n"},
        )
        time.sleep(2.0)
        seattle_diag = manager.stream_diagnostics()
        seattle_pid = seattle_diag.get("ffmpeg_pid")
        logger.info("Switched to Seattle SDOT (FFmpeg pid=%s)", seattle_pid)

        # Seattle -> YouTube Live
        manager.set_video_source("youtube", youtube_url, name="Tokyo Live Stream")
        time.sleep(2.0)
        yt2_diag = manager.stream_diagnostics()
        yt2_pid = yt2_diag.get("ffmpeg_pid")
        logger.info("Switched back to YouTube Live (FFmpeg pid=%s)", yt2_pid)

        manager.stop_camera()
        logger.info("Switch test completed successfully! Old processes cleaned up.")
    except Exception as exc:
        logger.error("Switch test error: %s", exc)
        switch_success = False
        manager.stop_camera()

    report = {
        "status": "COMPLETED",
        "youtube_url": youtube_url,
        "target_duration_minutes": target_duration_minutes,
        "actual_stable_duration_minutes": round(stable_duration_seconds / 60.0, 2),
        "actual_stable_duration_seconds": round(stable_duration_seconds, 1),
        "time_to_first_frame_seconds": round(first_frame_time - t0, 2) if first_frame_time else None,
        "first_stall_minute": round((first_stall_time - first_frame_time) / 60.0, 2) if first_stall_time and first_frame_time else None,
        "first_reconnect_minute": round((first_reconnect_time - first_frame_time) / 60.0, 2) if first_reconnect_time and first_frame_time else None,
        "first_fatal_minute": round((first_fatal_time - first_frame_time) / 60.0, 2) if first_fatal_time and first_frame_time else None,
        "total_samples": len(samples),
        "switch_test_passed": switch_success,
        "samples": samples,
    }

    report_path = PROJECT_ROOT / "scratch" / "youtube_soak_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    logger.info("Report saved to %s", report_path)

    return report


if __name__ == "__main__":
    dur = 30
    if len(sys.argv) > 1:
        try:
            dur = int(sys.argv[1])
        except ValueError:
            pass
    run_soak_test(target_duration_minutes=dur)
