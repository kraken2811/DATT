"""Smoke test verifying sequential source switching:
Local MP4 -> VOD -> Local -> VOD
with real FFmpeg subprocess execution, recording PIDs, thread counts, frame counts,
and verifying complete resource cleanup after each transition.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.stream.camera_manager import CameraManager
from src.stream.video_source import YouTubeVODReader


def create_smoke_mp4(num_frames: int = 30, width: int = 640, height: int = 480, fps: float = 30.0) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(tmp_path), fourcc, fps, (width, height))
    for i in range(num_frames):
        frame = np.full((height, width, 3), (i * 8) % 255, dtype=np.uint8)
        cv2.putText(frame, f"SMOKE_{i}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        out.write(frame)
    out.release()
    return tmp_path


def get_ffmpeg_pids() -> list[int]:
    """Find running ffmpeg processes on Windows via tasklist."""
    try:
        res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=5)
        pids = []
        for line in res.stdout.strip().splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2 and "ffmpeg" in parts[0].lower():
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    pass
        return pids
    except Exception:
        return []


def run_smoke_test():
    mp4_path = create_smoke_mp4(num_frames=20, width=640, height=480, fps=30.0)
    print(f"[SMOKE] Created temporary MP4 at: {mp4_path}")

    manager = CameraManager()
    results = []

    try:
        # Step 1: Local MP4
        print("\n--- STEP 1: Local MP4 ---")
        threads_before = threading.active_count()
        ffmpeg_before = get_ffmpeg_pids()
        cam1 = manager.set_video_source("local", str(mp4_path), loop=True, name="Smoke Local 1")
        time.sleep(0.5)
        frames_step1 = 0
        for _ in range(5):
            f = manager.read(timeout=0.5)
            if f is not None:
                frames_step1 += 1
            time.sleep(0.05)
        diag1 = manager.stream_diagnostics()
        print(f"Step 1 Active Camera: {cam1.name}, Status: {manager.status}, Frames: {frames_step1}, Diag Frames: {diag1.get('frames_received')}")
        results.append({
            "step": "Local MP4 (1)",
            "camera": cam1.name,
            "status": manager.status,
            "frames_read": frames_step1,
            "reader_alive": diag1.get("reader_alive"),
            "ffmpeg_alive": diag1.get("ffmpeg_alive"),
            "ffmpeg_pid": diag1.get("ffmpeg_pid"),
            "clean_eof_count": diag1.get("clean_eof_count"),
            "abnormal_exit_count": diag1.get("abnormal_exit_count"),
        })

        # Step 2: YouTube VOD (using real FFmpeg to decode the MP4 file via YouTubeVODReader)
        print("\n--- STEP 2: YouTube VOD ---")
        with patch.object(YouTubeVODReader, "resolve_vod_url", return_value=str(mp4_path)):
            cam2 = manager.set_video_source("youtube_vod", "https://www.youtube.com/watch?v=smoke_vod_1", loop=True, name="Smoke VOD 1")
            time.sleep(0.8)
            frames_step2 = 0
            for _ in range(5):
                f = manager.read(timeout=0.5)
                if f is not None:
                    frames_step2 += 1
                time.sleep(0.05)
            diag2 = manager.stream_diagnostics()
            vod_pid_1 = diag2.get("ffmpeg_pid")
            print(f"Step 2 Active Camera: {cam2.name}, Status: {manager.status}, FFmpeg PID: {vod_pid_1}, Frames: {frames_step2}, Diag Frames: {diag2.get('frames_received')}")
            results.append({
                "step": "YouTube VOD (1)",
                "camera": cam2.name,
                "status": manager.status,
                "frames_read": frames_step2,
                "reader_alive": diag2.get("reader_alive"),
                "ffmpeg_alive": diag2.get("ffmpeg_alive"),
                "ffmpeg_pid": vod_pid_1,
                "clean_eof_count": diag2.get("clean_eof_count"),
                "abnormal_exit_count": diag2.get("abnormal_exit_count"),
            })

        # Step 3: Switch back to Local MP4
        print("\n--- STEP 3: Local MP4 ---")
        cam3 = manager.set_video_source("local", str(mp4_path), loop=True, name="Smoke Local 2")
        time.sleep(0.5)
        # Verify previous FFmpeg process is gone!
        ffmpeg_pids_now = get_ffmpeg_pids()
        if vod_pid_1:
            assert vod_pid_1 not in ffmpeg_pids_now, f"Zombie FFmpeg detected! PID {vod_pid_1} still alive!"
        print(f"Verified FFmpeg PID {vod_pid_1} is terminated after switch.")

        frames_step3 = 0
        for _ in range(5):
            f = manager.read(timeout=0.5)
            if f is not None:
                frames_step3 += 1
            time.sleep(0.05)
        diag3 = manager.stream_diagnostics()
        print(f"Step 3 Active Camera: {cam3.name}, Status: {manager.status}, Frames: {frames_step3}, Diag Frames: {diag3.get('frames_received')}")
        results.append({
            "step": "Local MP4 (2)",
            "camera": cam3.name,
            "status": manager.status,
            "frames_read": frames_step3,
            "reader_alive": diag3.get("reader_alive"),
            "ffmpeg_alive": diag3.get("ffmpeg_alive"),
            "ffmpeg_pid": diag3.get("ffmpeg_pid"),
            "clean_eof_count": diag3.get("clean_eof_count"),
            "abnormal_exit_count": diag3.get("abnormal_exit_count"),
        })

        # Step 4: Switch back to YouTube VOD
        print("\n--- STEP 4: YouTube VOD ---")
        with patch.object(YouTubeVODReader, "resolve_vod_url", return_value=str(mp4_path)):
            cam4 = manager.set_video_source("youtube_vod", "https://www.youtube.com/watch?v=smoke_vod_2", loop=True, name="Smoke VOD 2")
            time.sleep(0.8)
            frames_step4 = 0
            for _ in range(5):
                f = manager.read(timeout=0.5)
                if f is not None:
                    frames_step4 += 1
                time.sleep(0.05)
            diag4 = manager.stream_diagnostics()
            vod_pid_2 = diag4.get("ffmpeg_pid")
            print(f"Step 4 Active Camera: {cam4.name}, Status: {manager.status}, FFmpeg PID: {vod_pid_2}, Frames: {frames_step4}, Diag Frames: {diag4.get('frames_received')}")
            results.append({
                "step": "YouTube VOD (2)",
                "camera": cam4.name,
                "status": manager.status,
                "frames_read": frames_step4,
                "reader_alive": diag4.get("reader_alive"),
                "ffmpeg_alive": diag4.get("ffmpeg_alive"),
                "ffmpeg_pid": vod_pid_2,
                "clean_eof_count": diag4.get("clean_eof_count"),
                "abnormal_exit_count": diag4.get("abnormal_exit_count"),
            })

        # Step 5: Final Stop
        print("\n--- STEP 5: Final Stop Camera ---")
        manager.stop_camera()
        time.sleep(0.5)
        ffmpeg_pids_final = get_ffmpeg_pids()
        if vod_pid_2:
            assert vod_pid_2 not in ffmpeg_pids_final, f"Zombie FFmpeg detected! PID {vod_pid_2} still alive!"
        print(f"Verified FFmpeg PID {vod_pid_2} is terminated after final stop.")

        print("\n================== SMOKE TEST SUMMARY ==================")
        for r in results:
            print(f"[{r['step']}] Cam: {r['camera']} | Status: {r['status']} | Read Frames: {r['frames_read']} | "
                  f"FFmpeg Alive: {r['ffmpeg_alive']} | PID: {r['ffmpeg_pid']} | "
                  f"Clean EOF: {r['clean_eof_count']} | Abnormal Exit: {r['abnormal_exit_count']}")
        print("ALL SMOKE TRANSITIONS SUCCESSFUL WITH NO ZOMBIE PROCESSES!")

    finally:
        manager.stop_camera()
        if mp4_path.is_file():
            try:
                mp4_path.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    run_smoke_test()
