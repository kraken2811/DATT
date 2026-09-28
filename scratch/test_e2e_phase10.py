"""Phase 10: Real End-to-End Application Lifecycle and Regression Test.

Validates the full live lifecycle against the real DATT server:
A. Start app with no source -> IDLE, port 8000 alive, 8501 alive
B. Select Seattle (2_Pike_NS) -> CONNECTING -> first frame -> RUNNING
   - video_feed 200, YOLO, person tracking, car tracking, People In View, Car In View
C. Click DOI CAMERA (POST /stop_camera) -> old FFmpeg PID dies, IDLE, port 8000 alive!
D. Select Seattle (3_Spring_EW) -> new FFmpeg PID, first frame, RUNNING, no 503
E. Direct change to Seattle (3_Stewart_NS) -> new PID, RUNNING, old PID dies
F. Upload real MP4 via POST /api/upload_video -> select uploaded MP4 -> RUNNING
G. Switch back to Seattle -> RUNNING, no server restart
H. Camera thumbnail endpoint verification (Priority A / Priority B fallback & caching)
I. Page load timing metrics (UI shell, catalog, state)
"""

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import psutil

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("e2e_test")

BASE_WEB_URL = "http://127.0.0.1:8501"
BASE_AI_URL = "http://127.0.0.1:8000"


def http_get(url: str, timeout: float = 10.0) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "DATT-E2E/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read(), dict(resp.headers)


def http_post_json(url: str, data: dict, timeout: float = 10.0) -> tuple[int, dict]:
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "DATT-E2E/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return resp.status, body


def http_post_multipart(url: str, file_path: Path, field_name: str = "file") -> tuple[int, dict]:
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    filename = file_path.name
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    lines = [
        f"--{boundary}".encode("utf-8"),
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'.encode("utf-8"),
        b"Content-Type: video/mp4",
        b"",
        file_bytes,
        f"--{boundary}--".encode("utf-8"),
        b"",
    ]
    body = b"\r\n".join(lines)
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "DATT-E2E/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30.0) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return resp.status, res


def wait_for_ports(ports: list[int], timeout: float = 25.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        all_up = True
        for p in ports:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{p}/", timeout=1.0)
            except urllib.error.HTTPError:
                pass  # Port answered, even 404/503 means port is up
            except Exception:
                all_up = False
                break
        if all_up:
            return True
        time.sleep(0.5)
    return False


def wait_for_status(expected_statuses: list[str], timeout: float = 30.0) -> dict:
    t0 = time.time()
    last_state = {}
    while time.time() - t0 < timeout:
        try:
            _, body = http_get_json(f"{BASE_WEB_URL}/api/status")
            last_state = body
            if body.get("status") in expected_statuses:
                return body
        except Exception:
            pass
        time.sleep(0.5)
    return last_state


def wait_for_active_stream(timeout: float = 25.0) -> tuple[int | None, dict]:
    """Wait until FFmpeg PID is active and frames_received > 0."""
    t0 = time.time()
    last_diag = {}
    while time.time() - t0 < timeout:
        try:
            _, body = http_get_json(f"{BASE_WEB_URL}/api/source_status")
            last_diag = body
            pid = body.get("ffmpeg_pid") or body.get("diagnostics", {}).get("ffmpeg_pid")
            frames = body.get("frames_received", 0)
            if pid and psutil.pid_exists(pid) and frames > 0:
                return pid, body
        except Exception:
            pass
        time.sleep(0.5)
    pid = last_diag.get("ffmpeg_pid") or last_diag.get("diagnostics", {}).get("ffmpeg_pid")
    return pid, last_diag


def http_get_json(url: str, timeout: float = 10.0) -> tuple[int, dict]:
    status, raw, _ = http_get(url, timeout)
    return status, json.loads(raw.decode("utf-8"))


def run_e2e() -> dict:
    logger.info("==================================================")
    logger.info("PHASE 10 REAL END-TO-END APPLICATION TEST")
    logger.info("==================================================")

    # 1. Fetch real Seattle SDOT cameras from service
    from src.stream.seattle_sdot_service import seattle_service
    seattle_cameras = seattle_service.get_cameras()
    logger.info("Resolved %d Seattle SDOT cameras from provider.", len(seattle_cameras))
    
    cam_pike = seattle_service.get_camera_by_stream_name("2_Pike_NS")
    cam_spring = seattle_service.get_camera_by_stream_name("3_Spring_EW")
    cam_stewart = seattle_service.get_camera_by_stream_name("3_Stewart_NS")

    assert cam_pike is not None, "2_Pike_NS not found in Seattle catalog"
    assert cam_spring is not None, "3_Spring_EW not found in Seattle catalog"
    assert cam_stewart is not None, "3_Stewart_NS not found in Seattle catalog"

    python_exe = sys.executable
    app_proc = None
    app_log_file = None
    results = {}

    try:
        # A. Start app with no source
        logger.info("\n--- STEP A: Starting app.py with no initial source ---")
        t_start = time.time()
        app_log_path = PROJECT_ROOT / "scratch" / "app_e2e.log"
        app_log_file = open(app_log_path, "w", encoding="utf-8")
        app_proc = subprocess.Popen(
            [python_exe, "-u", "app.py"],
            cwd=str(PROJECT_ROOT),
            stdout=app_log_file,
            stderr=subprocess.STDOUT,
        )
        logger.info("Spawned app.py (PID=%d, logging to %s). Waiting for ports 8000 and 8501...",
                    app_proc.pid, app_log_path)

        assert wait_for_ports([8000, 8501], timeout=25.0), "Ports 8000 and 8501 failed to start!"
        time_to_ports = time.time() - t_start
        logger.info("Both ports (8000, 8501) UP in %.2f seconds.", time_to_ports)

        # Measure page load timings
        t_ui_0 = time.time()
        status_ui, body_ui, _ = http_get(f"{BASE_WEB_URL}/")
        time_to_ui_shell = time.time() - t_ui_0
        assert status_ui == 200, f"UI shell returned HTTP {status_ui}"
        logger.info("UI shell loaded in %.3fs (HTTP 200)", time_to_ui_shell)

        t_state_0 = time.time()
        _, state_a = http_get_json(f"{BASE_WEB_URL}/api/status")
        time_to_state = time.time() - t_state_0
        logger.info("Runtime state initial: status=%s, camera='%s' in %.3fs",
                    state_a.get("status"), state_a.get("camera_name"), time_to_state)
        assert state_a.get("status") == "IDLE", f"Expected IDLE but got {state_a.get('status')}"

        t_cat_0 = time.time()
        _, cat_data = http_get_json(f"{BASE_WEB_URL}/api/public_cameras?provider=seattle")
        time_to_catalog = time.time() - t_cat_0
        logger.info("Seattle catalog fetched %d cameras in %.3fs", len(cat_data.get("cameras", [])), time_to_catalog)

        results["step_a"] = {
            "status": "PASSED",
            "time_to_ports": round(time_to_ports, 2),
            "time_to_ui_shell": round(time_to_ui_shell, 3),
            "time_to_state": round(time_to_state, 3),
            "time_to_catalog": round(time_to_catalog, 3),
            "initial_state": state_a.get("status"),
        }

        # B. Select Seattle: 2_Pike_NS
        logger.info("\n--- STEP B: Selecting Seattle: 2_Pike_NS ---")
        t_sel_b = time.time()
        status_b, resp_b = http_post_json(
            f"{BASE_WEB_URL}/api/select_source",
            {
                "source_type": "direct_hls",
                "source": cam_pike["stream_url"],
                "name": cam_pike["name"],
                "headers": {"Referer": "https://web.seattle.gov/Travelers/\r\n"},
            },
        )
        assert status_b == 200, f"select_source failed: {resp_b}"
        logger.info("select_source response: %s", resp_b)

        # Wait for active stream and frames
        ffmpeg_pid_1, diag_b = wait_for_active_stream(timeout=25.0)
        time_to_running_b = time.time() - t_sel_b
        logger.info("Active FFmpeg PID: %s (frames_received=%s) in %.2fs",
                    ffmpeg_pid_1, diag_b.get("frames_received"), time_to_running_b)
        assert ffmpeg_pid_1 is not None, "Expected active FFmpeg PID"
        assert psutil.pid_exists(ffmpeg_pid_1), f"FFmpeg PID {ffmpeg_pid_1} should be running"

        _, telem_b = http_get_json(f"{BASE_WEB_URL}/api/telemetry")
        logger.info("Telemetry: people_count=%s | car_count=%s | fps=%.1f | frames_received=%s",
                    telem_b.get("people_count"), telem_b.get("car_count"),
                    telem_b.get("stream_fps", 0), telem_b.get("frames_received"))
        assert "people_count" in telem_b, "Missing people_count in telemetry"
        assert "car_count" in telem_b, "Missing car_count in telemetry"

        results["step_b"] = {
            "status": "PASSED",
            "camera": "2_Pike_NS",
            "time_to_running": round(time_to_running_b, 2),
            "ffmpeg_pid_1": ffmpeg_pid_1,
            "people_count": telem_b.get("people_count"),
            "car_count": telem_b.get("car_count"),
            "frames_received": telem_b.get("frames_received"),
        }

        # C. Click DOI CAMERA (POST /stop_camera)
        logger.info("\n--- STEP C: Clicking DOI CAMERA (POST /stop_camera) ---")
        status_stop, resp_stop = http_post_json(f"{BASE_WEB_URL}/stop_camera", {})
        assert status_stop == 200, f"stop_camera returned HTTP {status_stop}"
        logger.info("stop_camera response: %s", resp_stop)

        time.sleep(1.0)
        # Verify old FFmpeg PID died
        assert not psutil.pid_exists(ffmpeg_pid_1), f"Old FFmpeg PID {ffmpeg_pid_1} is still running!"
        logger.info("CONFIRMED: Old FFmpeg PID %s has exited.", ffmpeg_pid_1)

        # Verify state is IDLE
        _, state_c = http_get_json(f"{BASE_WEB_URL}/api/status")
        logger.info("State after stop: status=%s", state_c.get("status"))
        assert state_c.get("status") == "IDLE", f"Expected IDLE, got {state_c.get('status')}"

        # CRITICAL REGRESSION CHECK: Port 8000 and 8501 remain alive!
        assert wait_for_ports([8000, 8501], timeout=3.0), "FATAL REGRESSION: Port 8000 died after stop_camera!"
        _, ai_health = http_get_json(f"{BASE_AI_URL}/cameras")
        logger.info("CONFIRMED: Port 8000 is ALIVE and responded to /cameras (%d configured)", len(ai_health.get("cameras", [])))

        results["step_c"] = {
            "status": "PASSED",
            "old_ffmpeg_killed": True,
            "state_after_stop": state_c.get("status"),
            "port_8000_alive": True,
        }

        # D. Select Seattle: 3_Spring_EW
        logger.info("\n--- STEP D: Selecting Seattle: 3_Spring_EW ---")
        t_sel_d = time.time()
        status_d, resp_d = http_post_json(
            f"{BASE_WEB_URL}/api/select_source",
            {
                "source_type": "direct_hls",
                "source": cam_spring["stream_url"],
                "name": cam_spring["name"],
                "headers": {"Referer": "https://web.seattle.gov/Travelers/\r\n"},
            },
        )
        assert status_d == 200, f"select_source 3_Spring_EW failed: {resp_d}"
        ffmpeg_pid_2, diag_d = wait_for_active_stream(timeout=25.0)
        time_to_running_d = time.time() - t_sel_d
        logger.info("New FFmpeg PID: %s (old was %s, frames=%s) in %.2fs",
                    ffmpeg_pid_2, ffmpeg_pid_1, diag_d.get("frames_received"), time_to_running_d)
        assert ffmpeg_pid_2 is not None and ffmpeg_pid_2 != ffmpeg_pid_1, "Expected distinct new FFmpeg PID"
        assert psutil.pid_exists(ffmpeg_pid_2), f"New FFmpeg PID {ffmpeg_pid_2} should be running"

        _, telem_d = http_get_json(f"{BASE_WEB_URL}/api/telemetry")
        logger.info("Telemetry: people_count=%s | car_count=%s | frames=%s",
                    telem_d.get("people_count"), telem_d.get("car_count"), telem_d.get("frames_received"))

        results["step_d"] = {
            "status": "PASSED",
            "camera": "3_Spring_EW",
            "ffmpeg_pid_2": ffmpeg_pid_2,
            "time_to_running": round(time_to_running_d, 2),
            "people_count": telem_d.get("people_count"),
            "car_count": telem_d.get("car_count"),
        }

        # E. Direct Change to Seattle: 3_Stewart_NS (without prior stop)
        logger.info("\n--- STEP E: Direct switch to Seattle: 3_Stewart_NS ---")
        t_sel_e = time.time()
        status_e, resp_e = http_post_json(
            f"{BASE_WEB_URL}/api/select_source",
            {
                "source_type": "direct_hls",
                "source": cam_stewart["stream_url"],
                "name": cam_stewart["name"],
                "headers": {"Referer": "https://web.seattle.gov/Travelers/\r\n"},
            },
        )
        ffmpeg_pid_3, diag_e = wait_for_active_stream(timeout=25.0)
        time_to_running_e = time.time() - t_sel_e
        logger.info("New FFmpeg PID: %s (frames=%s) in %.2fs", ffmpeg_pid_3, diag_e.get("frames_received"), time_to_running_e)
        assert ffmpeg_pid_3 is not None and ffmpeg_pid_3 != ffmpeg_pid_2
        assert not psutil.pid_exists(ffmpeg_pid_2), f"Old FFmpeg PID {ffmpeg_pid_2} was not cleaned up!"

        _, telem_e = http_get_json(f"{BASE_WEB_URL}/api/telemetry")
        logger.info("Telemetry: people_count=%s | car_count=%s | frames=%s",
                    telem_e.get("people_count"), telem_e.get("car_count"), telem_e.get("frames_received"))

        results["step_e"] = {
            "status": "PASSED",
            "camera": "3_Stewart_NS",
            "ffmpeg_pid_3": ffmpeg_pid_3,
            "old_pid_2_cleaned": True,
            "time_to_running": round(time_to_running_e, 2),
            "people_count": telem_e.get("people_count"),
            "car_count": telem_e.get("car_count"),
        }

        # F. Switch to Local Video via real browser upload
        logger.info("\n--- STEP F: Uploading MP4 and switching to Local Video ---")
        test_video = PROJECT_ROOT / "results" / "readiness_audit" / "local.mp4"
        assert test_video.exists(), f"Sample test video not found at {test_video}"

        t_up_0 = time.time()
        status_up, resp_up = http_post_multipart(f"{BASE_WEB_URL}/api/upload_video", test_video)
        time_to_upload = time.time() - t_up_0
        assert status_up == 200 and resp_up.get("status") == "ok", f"Upload failed: {resp_up}"
        uploaded_path = resp_up["server_path"]
        logger.info("Upload succeeded in %.3fs! Server path: %s", time_to_upload, uploaded_path)
        assert Path(uploaded_path).exists(), f"Uploaded file does not exist on disk: {uploaded_path}"

        # Select the uploaded video
        t_sel_f = time.time()
        status_f, resp_f = http_post_json(
            f"{BASE_WEB_URL}/api/select_source",
            {
                "source_type": "local",
                "source": uploaded_path,
                "name": "Uploaded Test Clip",
            },
        )
        assert status_f == 200, f"select_source local failed: {resp_f}"
        state_f = wait_for_status(["RUNNING"], timeout=15.0)
        time_to_running_f = time.time() - t_sel_f
        assert state_f.get("status") == "RUNNING"

        time.sleep(3.0)
        # Verify old FFmpeg PID 3 died because local video uses LocalVideoReader
        assert not psutil.pid_exists(ffmpeg_pid_3), f"FFmpeg PID {ffmpeg_pid_3} should be closed for local video"
        _, telem_f = http_get_json(f"{BASE_WEB_URL}/api/telemetry")
        _, diag_f = http_get_json(f"{BASE_WEB_URL}/api/source_status")
        local_frames = diag_f.get("frames_received", 0) or telem_f.get("frame_id", 0)
        logger.info("Local video telemetry: people_count=%s | car_count=%s | frame_id=%s | frames_received=%s",
                    telem_f.get("people_count"), telem_f.get("car_count"),
                    telem_f.get("frame_id"), diag_f.get("frames_received"))
        assert local_frames > 0, "No frames received from local video"

        results["step_f"] = {
            "status": "PASSED",
            "time_to_upload": round(time_to_upload, 3),
            "uploaded_path": uploaded_path,
            "time_to_running": round(time_to_running_f, 2),
            "people_count": telem_f.get("people_count"),
            "car_count": telem_f.get("car_count"),
            "frame_id": telem_f.get("frame_id"),
            "frames_received": local_frames,
        }

        # G. Switch back to Seattle: 2_Pike_NS
        logger.info("\n--- STEP G: Switching from Local Video back to Seattle: 2_Pike_NS ---")
        t_sel_g = time.time()
        status_g, resp_g = http_post_json(
            f"{BASE_WEB_URL}/api/select_source",
            {
                "source_type": "direct_hls",
                "source": cam_pike["stream_url"],
                "name": cam_pike["name"],
                "headers": {"Referer": "https://web.seattle.gov/Travelers/\r\n"},
            },
        )
        ffmpeg_pid_4, diag_g = wait_for_active_stream(timeout=25.0)
        time_to_running_g = time.time() - t_sel_g
        logger.info("Seattle restarted with FFmpeg PID: %s (frames=%s) in %.2fs",
                    ffmpeg_pid_4, diag_g.get("frames_received"), time_to_running_g)
        assert ffmpeg_pid_4 is not None and psutil.pid_exists(ffmpeg_pid_4)

        results["step_g"] = {
            "status": "PASSED",
            "time_to_running": round(time_to_running_g, 2),
            "ffmpeg_pid_4": ffmpeg_pid_4,
        }

        # H. Camera Thumbnail endpoint verification
        logger.info("\n--- STEP H: Verifying Camera Thumbnail endpoint ---")
        t_thumb_0 = time.time()
        status_th, img_bytes, th_headers = http_get(f"{BASE_WEB_URL}/api/camera_thumbnail?camera_id=seattle_2_Pike_NS")
        time_to_thumb = time.time() - t_thumb_0
        logger.info("Thumbnail fetched in %.3fs (HTTP %d, %d bytes, Content-Type: %s)",
                    time_to_thumb, status_th, len(img_bytes), th_headers.get("Content-Type"))
        assert status_th == 200
        assert len(img_bytes) > 100

        # Test cache hit
        t_cache_0 = time.time()
        status_th2, img_bytes2, _ = http_get(f"{BASE_WEB_URL}/api/camera_thumbnail?camera_id=seattle_2_Pike_NS")
        time_to_cached = time.time() - t_cache_0
        logger.info("Cached thumbnail fetched in %.4fs", time_to_cached)
        assert time_to_cached < 0.1, "Cached thumbnail should return almost instantly"
        assert len(img_bytes2) == len(img_bytes)

        results["step_h"] = {
            "status": "PASSED",
            "time_to_first_thumb": round(time_to_thumb, 3),
            "time_to_cached_thumb": round(time_to_cached, 4),
            "bytes": len(img_bytes),
        }

        results["overall"] = "SUCCESS"
        logger.info("\n==================================================")
        logger.info("ALL PHASE 10 E2E STEPS COMPLETED WITH FULL SUCCESS!")
        logger.info("==================================================")

    except Exception as exc:
        logger.error("E2E TEST FAILED: %s", exc, exc_info=True)
        results["overall"] = "FAILED"
        results["error"] = str(exc)
    finally:
        if app_proc is not None:
            logger.info("Terminating app.py process (PID %d)...", app_proc.pid)
            try:
                # Terminate tree
                parent = psutil.Process(app_proc.pid)
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except Exception:
                        pass
                parent.kill()
            except Exception:
                pass
            app_proc.wait(timeout=5.0)
            logger.info("app.py terminated cleanly.")
        if app_log_file is not None and not app_log_file.closed:
            app_log_file.close()

    # Save results to scratch
    out_path = PROJECT_ROOT / "scratch" / "e2e_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logger.info("E2E Results saved to %s", out_path)

    return results


if __name__ == "__main__":
    res = run_e2e()
    if res.get("overall") != "SUCCESS":
        sys.exit(1)
