"""MJPEG Video Stream & Telemetry Server for DATT.

Phase 4: Level 2 Realtime Monitoring UI.
Provides a high-performance, non-blocking HTTP streaming server serving:
- GET /video_feed : multipart/x-mixed-replace MJPEG stream (20-30 FPS)
- GET /telemetry  : Realtime telemetry JSON for UI metric cards
- GET /status     : Operational status JSON (RUNNING, STOPPED, ERROR)
- GET /           : Lightweight standalone web monitor

Uses strict latest-frame semantics: if client is slower than inference,
old frames are automatically dropped without unbounded queue buffering.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any
import urllib.parse

import cv2
import numpy as np

from src.config.camera_config import list_cameras
from src.events.event_storage import event_storage
from src.runtime.shared_state import SharedRuntimeState, shared_state
from src.stream.camera_manager import CameraManager


class StreamRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MJPEG video streaming, telemetry, and camera control."""

    # References to SharedRuntimeState and CameraManager (set on server class)
    state: SharedRuntimeState = shared_state
    camera_manager: CameraManager | None = None

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress standard HTTP server access logs to keep terminal clean."""
        return

    def do_OPTIONS(self) -> None:
        """Handle CORS pre-flight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:
        """Route GET requests to video feed, telemetry, camera control, or events."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        if path == "/video_feed":
            self.handle_video_feed()
        elif path == "/telemetry":
            self.handle_telemetry()
        elif path == "/status":
            self.handle_status()
        elif path == "/cameras":
            self.handle_cameras()
        elif path == "/switch_camera":
            self.handle_switch_camera(query)
        elif path == "/events":
            self.handle_events(query)
        elif path == "/event_snapshot":
            self.handle_event_snapshot(query)
        elif path == "/":
            self.handle_root()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        """Route POST requests (e.g. switch_camera)."""
        path = self.path.split("?")[0]
        if path == "/switch_camera":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
            try:
                data = json.loads(body)
            except Exception:
                data = {}
            cam_id = data.get("camera_id") or data.get("id")
            self._execute_camera_switch(cam_id)
        else:
            self.send_response(404)
            self.end_headers()

    def handle_video_feed(self) -> None:
        """Stream MJPEG multipart video feed using latest-frame semantics."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        last_frame_id = -1
        # Blank placeholder frame while pipeline warms up
        blank_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        cv2.putText(
            blank_frame,
            "WAITING FOR CAMERA STREAM...",
            (320, 360),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 200, 255),
            2,
            cv2.LINE_AA,
        )
        _, blank_jpeg = cv2.imencode(".jpg", blank_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        blank_bytes = blank_jpeg.tobytes()

        try:
            while getattr(self.server, "running", True):
                frame_id, frame = self.state.get_annotated_frame()

                if frame is None:
                    # Serve blank placeholder once, then wait
                    if last_frame_id == -1:
                        self._write_frame(blank_bytes)
                        last_frame_id = 0
                    time.sleep(0.05)
                    continue

                # If no new frame has been processed by AI yet, sleep briefly
                if frame_id == last_frame_id:
                    time.sleep(0.015)  # ~60 Hz poll, avoiding CPU spin
                    continue

                # New frame available: drop any intermediate frames, encode latest
                last_frame_id = frame_id
                success, encoded_jpg = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80]
                )
                if not success:
                    continue

                self._write_frame(encoded_jpg.tobytes())

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Client closed browser tab or refreshed; clean disconnect
            pass

    def _write_frame(self, frame_bytes: bytes) -> None:
        """Write a single boundary JPEG frame to client socket."""
        self.wfile.write(b"--frame\r\n")
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(frame_bytes)))
        self.end_headers()
        self.wfile.write(frame_bytes)
        self.wfile.write(b"\r\n")

    def handle_telemetry(self) -> None:
        """Return realtime telemetry JSON."""
        telemetry = self.state.get_telemetry().to_dict()
        body = json.dumps(telemetry).encode("utf-8")

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def handle_status(self) -> None:
        """Return operational pipeline status."""
        telemetry = self.state.get_telemetry()
        body = json.dumps({
            "status": telemetry.status,
            "error_message": telemetry.error_message,
            "frame_id": telemetry.frame_id,
            "camera_id": telemetry.camera_id,
            "camera_name": telemetry.camera_name,
            "last_event": telemetry.last_event,
            "event_count_today": telemetry.event_count_today,
        }).encode("utf-8")

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_cameras(self) -> None:
        """Return list of configured cameras."""
        try:
            cameras = [c.to_dict() for c in list_cameras()]
            active_cam = self.camera_manager.get_active_camera() if self.camera_manager else None
            data = {
                "status": "ok",
                "active_camera_id": active_cam.id if active_cam else "camera_01",
                "cameras": cameras,
            }
        except Exception as exc:
            data = {"status": "error", "message": str(exc), "cameras": []}

        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_switch_camera(self, query: dict[str, list[str]]) -> None:
        """Handle camera switch request via GET query param (e.g. /switch_camera?id=camera_02)."""
        cam_id = query.get("id", [""])[0] or query.get("camera_id", [""])[0]
        self._execute_camera_switch(cam_id)

    def _execute_camera_switch(self, camera_id: str | None) -> None:
        """Execute dynamic camera switch on CameraManager."""
        if not camera_id:
            self._send_json_response({"status": "error", "message": "Missing camera_id"}, code=400)
            return

        if self.camera_manager is None:
            self._send_json_response(
                {"status": "error", "message": "CameraManager not connected to server"}, code=503
            )
            return

        try:
            cam_info = self.camera_manager.switch_camera(camera_id)
            self.state.set_camera(cam_info.id, cam_info.name)
            self._send_json_response(
                {
                    "status": "ok",
                    "camera_id": cam_info.id,
                    "camera_name": cam_info.name,
                    "message": f"Switched to camera {cam_info.name}",
                }
            )
        except Exception as exc:
            self.state.set_status("ERROR", f"Camera switch failed: {exc}")
            self._send_json_response({"status": "error", "message": str(exc)}, code=500)

    def handle_events(self, query: dict[str, list[str]]) -> None:
        """Return recent occupancy events from SQLite."""
        try:
            limit = int(query.get("limit", ["20"])[0])
        except ValueError:
            limit = 20
        cam_id = query.get("camera_id", [None])[0]

        events = event_storage.get_recent_events(limit=limit, camera_id=cam_id)
        today_count = event_storage.get_event_count_today()
        self._send_json_response(
            {"status": "ok", "events": events, "event_count_today": today_count}
        )

    def handle_event_snapshot(self, query: dict[str, list[str]]) -> None:
        """Serve JPEG image snapshot from data/events/."""
        rel_path = query.get("path", [""])[0]
        if not rel_path:
            self.send_response(400)
            self.end_headers()
            return

        project_root = Path(__file__).resolve().parent.parent.parent
        target_file = (project_root / rel_path).resolve()
        snapshot_dir = (project_root / "data" / "events").resolve()

        # Prevent directory traversal attacks
        if not str(target_file).startswith(str(snapshot_dir)) or not target_file.is_file():
            self.send_response(404)
            self.end_headers()
            return

        try:
            with open(target_file, "rb") as f:
                img_data = f.read()

            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(img_data)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(img_data)
        except Exception:
            self.send_response(500)
            self.end_headers()

    def _send_json_response(self, data: dict[str, Any], code: int = 200) -> None:
        """Convenience helper to send JSON response."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_root(self) -> None:
        """Serve lightweight web monitoring preview."""
        html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>DATT - AI People Counter Monitor</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0e1117; color: #ffffff; margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #00e5ff; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }
        .card { background: #1a1f2c; border-radius: 8px; padding: 20px; border: 1px solid #2e384d; }
        .stream-box { width: 100%; border-radius: 8px; overflow: hidden; background: #000; }
        .stream-box img { width: 100%; display: block; }
        .metric { margin-bottom: 14px; }
        .metric-title { font-size: 13px; color: #8fa0b5; text-transform: uppercase; }
        .metric-value { font-size: 24px; font-weight: bold; color: #00e5ff; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 13px; }
        .badge-running { background: #059669; color: #fff; }
        .badge-stopped { background: #6b7280; color: #fff; }
        .badge-error { background: #dc2626; color: #fff; }
    </style>
</head>
<body>
    <div class="container">
        <h1>DATT — AI People Counter Monitor</h1>
        <div class="grid">
            <div class="card stream-box">
                <img src="/video_feed" alt="Realtime AI Video Feed">
            </div>
            <div class="card">
                <div class="metric">
                    <div class="metric-title">Pipeline Status</div>
                    <div id="status-badge" class="badge badge-running">RUNNING</div>
                </div>
                <div class="metric">
                    <div class="metric-title">People in View</div>
                    <div class="metric-value" id="val-people">0</div>
                </div>
                <div class="metric">
                    <div class="metric-title">Processing FPS / Stream FPS</div>
                    <div class="metric-value"><span id="val-pfps">0</span> / <span id="val-sfps">0</span></div>
                </div>
                <div class="metric">
                    <div class="metric-title">YOLO / Pipeline Latency</div>
                    <div class="metric-value"><span id="val-yolo">0</span> ms / <span id="val-pipe">0</span> ms</div>
                </div>
                <div class="metric">
                    <div class="metric-title">Hardware / VRAM</div>
                    <div class="metric-value" style="font-size: 18px;"><span id="val-gpu">GPU</span> (<span id="val-vram">0</span> MB)</div>
                </div>
            </div>
        </div>
    </div>
    <script>
        async function updateTelemetry() {
            try {
                const res = await fetch('/telemetry');
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById('val-people').innerText = data.people_count;
                    document.getElementById('val-pfps').innerText = data.processing_fps.toFixed(1);
                    document.getElementById('val-sfps').innerText = data.stream_fps.toFixed(1);
                    document.getElementById('val-yolo').innerText = data.yolo_latency_ms.toFixed(1);
                    document.getElementById('val-pipe').innerText = data.pipeline_latency_ms.toFixed(1);
                    document.getElementById('val-gpu').innerText = data.gpu_name;
                    document.getElementById('val-vram').innerText = data.vram_mb.toFixed(1);
                    const badge = document.getElementById('status-badge');
                    badge.innerText = data.status;
                    badge.className = 'badge badge-' + data.status.toLowerCase();
                }
            } catch (e) {}
        }
        setInterval(updateTelemetry, 200);
    </script>
</body>
</html>"""
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MJPEGServer:
    """Threaded wrapper managing lifecycle of the MJPEG streaming server."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        state: SharedRuntimeState = shared_state,
        camera_manager: CameraManager | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.state = state
        self.camera_manager = camera_manager
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the MJPEG HTTP server in a daemon thread."""
        StreamRequestHandler.state = self.state
        StreamRequestHandler.camera_manager = self.camera_manager

        # Use ThreadingHTTPServer so each stream connection runs concurrently
        self._server = ThreadingHTTPServer((self.host, self.port), StreamRequestHandler)
        setattr(self._server, "running", True)

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="MJPEGServerThread",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Cleanly shutdown the server."""
        if self._server is not None:
            setattr(self._server, "running", False)
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def start_stream_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    state: SharedRuntimeState = shared_state,
    camera_manager: CameraManager | None = None,
) -> MJPEGServer:
    """Convenience helper to instantiate and start MJPEG server."""
    server = MJPEGServer(host=host, port=port, state=state, camera_manager=camera_manager)
    server.start()
    return server

