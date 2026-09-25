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
import socket

import cv2
import numpy as np

from src.config.camera_config import list_cameras
from src.events.event_storage import event_storage
from src.face.face_embedder import decode_face_image_bytes
from src.recognition.target_matcher import TargetRegistrationError, target_manager
from src.runtime.shared_state import SharedRuntimeState, shared_state
from src.stream.caltrans_service import caltrans_service
from src.stream.camera_manager import CameraManager
from src.stream.preview_manager import preview_manager
from src.stream.seattle_sdot_service import SEATTLE_STREAM_HEADERS, seattle_service


def create_status_placeholder(
    width: int = 1280,
    height: int = 720,
    title: str = "CONNECTING TO CAMERA...",
    subtitle: str = "Waiting for video stream...",
) -> bytes:
    """Render high-contrast, clean status placeholder (Requirement C4).

    Eliminates unexplained black screens with explicit operational state indication.
    """
    img = np.full((height, width, 3), (26, 17, 14), dtype=np.uint8)  # Deep slate #0e111a
    cx = width // 2
    cy = height // 2

    # Draw camera aperture symbol
    cv2.circle(img, (cx, cy - 60), 38, (48, 32, 26), -1)
    cv2.circle(img, (cx, cy - 60), 38, (80, 60, 50), 2, cv2.LINE_AA)
    cv2.circle(img, (cx, cy - 60), 16, (240, 160, 56), -1)  # Cyan center dot

    # Title & Subtitle text rendering
    (tw, th), _ = cv2.getTextSize(title, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    cv2.putText(
        img,
        title,
        (cx - tw // 2, cy + 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (240, 240, 245),
        2,
        cv2.LINE_AA,
    )
    (sw, sh), _ = cv2.getTextSize(subtitle, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
    cv2.putText(
        img,
        subtitle,
        (cx - sw // 2, cy + 55),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (160, 170, 185),
        1,
        cv2.LINE_AA,
    )

    _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return enc.tobytes()


class StreamRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for MJPEG video streaming, telemetry, and camera control."""

    # References to SharedRuntimeState and CameraManager (set on server class)
    state: SharedRuntimeState = shared_state
    camera_manager: CameraManager | None = None

    def setup(self) -> None:
        super().setup()
        # A stalled Colab proxy must not leave this worker in CLOSE_WAIT.
        self.connection.settimeout(15.0)
        self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._video_session = None

    def finish(self) -> None:
        try:
            super().finish()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout):
            pass

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
        elif path in ("/public_cameras", "/api/public_cameras"):
            self.handle_public_cameras(query)
        elif path in ("/source_status", "/api/source_status"):
            self.handle_source_status()
        elif path in ("/camera_snapshot", "/api/camera_snapshot"):
            self.handle_camera_snapshot(query)
        elif path in ("/camera_thumbnail", "/api/camera_thumbnail"):
            self.handle_camera_thumbnail(query)
        elif path in ("/preview_feed", "/api/preview_feed"):
            self.handle_preview_feed(query)
        elif path in ("/video_source", "/api/video_source"):
            self.handle_video_source()
        elif path in ("/targets", "/api/targets"):
            self.handle_targets()
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
        """Route POST requests (switch_camera, set_video_source, select_source, stop_camera, register_target)."""
        path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8", errors="replace") if content_len > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if path in ("/switch_camera", "/api/switch_camera"):
            cam_id = data.get("camera_id") or data.get("id")
            self._execute_camera_switch(cam_id)
        elif path in ("/select_source", "/api/select_source"):
            self._execute_select_source(data)
        elif path in ("/stop_camera", "/api/stop_camera"):
            self._execute_stop_camera()
        elif path in ("/stop_preview", "/api/stop_preview"):
            self._execute_stop_preview()
        elif path in ("/set_video_source", "/api/set_video_source"):
            self._execute_set_video_source(data)
        elif path in ("/register_target", "/api/register_target"):
            self._execute_register_target(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self) -> None:
        """Route DELETE requests (remove target)."""
        path = self.path.split("?")[0]
        if path.startswith("/api/targets/") or path.startswith("/targets/"):
            target_id = path.split("/")[-1]
            removed = target_manager.remove_target(target_id)
            if removed:
                self._send_json_response({"status": "ok", "message": f"Target '{target_id}' removed"})
            else:
                self._send_json_response({"status": "error", "message": f"Target '{target_id}' not found"}, code=404)
        else:
            self.send_response(404)
            self.end_headers()

    def handle_video_feed(self) -> None:
        """Stream MJPEG multipart video feed using latest-frame semantics and stable pacing.

        Requirements C1-C5:
        - Maintains socket connection alive across temporary source gaps (C2).
        - Renders same-source-generation last good frame with buffering indicator during stalls (C3).
        - Prevents cross-generation leaks on source switch (C3).
        - Displays explicit status placeholder instead of black rectangle when initializing (C4).
        - Supports concurrent clients without violent socket eviction (C5).
        """
        self._video_session = self.server.owner.claim_video_client(self)
        if self._video_session is None:
            self.send_response(503)
            self.send_header("Retry-After", "1")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        last_sent_frame_id = -1
        last_sent_time = 0.0
        current_stream_gen = self.state.source_generation
        placeholder_bytes = create_status_placeholder(
            title="CONNECTING TO CAMERA...",
            subtitle="Waiting for video stream...",
        )

        try:
            while getattr(self.server, "running", True) and not getattr(self, "close_connection", False):
                now = time.time()
                frame_id, frame, is_fallback, gen = self.state.get_frame_for_stream()

                # Source generation change (camera switch)
                if gen != current_stream_gen:
                    current_stream_gen = gen
                    last_sent_frame_id = -1
                    last_sent_time = 0.0
                    switch_placeholder = create_status_placeholder(
                        title="SWITCHING CAMERA...",
                        subtitle="Connecting to new video source...",
                    )
                    self._write_frame(switch_placeholder)
                    last_sent_time = now
                    time.sleep(0.05)
                    continue

                # Case A: Fresh new frame available
                if frame is not None and frame_id != last_sent_frame_id and not is_fallback:
                    success, encoded_jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if success:
                        self._write_frame(encoded_jpg.tobytes())
                        last_sent_frame_id = frame_id
                        last_sent_time = now
                        self.state.record_mjpeg_publish(success=True)
                    else:
                        self.state.record_mjpeg_publish(success=False, error="cv2.imencode failed")
                    time.sleep(0.01)
                    continue

                # Case B: Gap or stall in incoming frames (keep MJPEG alive, C2, C3, C4)
                elapsed_since_sent = now - last_sent_time
                if elapsed_since_sent >= 0.5:  # Heartbeat cadence (~2 FPS) to keep socket and proxy alive
                    if frame is not None:
                        # Same-generation frame available: draw subtle warning banner if gap persists
                        display_frame = frame.copy()
                        h, w = display_frame.shape[:2]
                        cv2.rectangle(display_frame, (0, 0), (w, 36), (15, 23, 42), -1)
                        banner_text = "● TEMPORARY SOURCE DELAY - BUFFERING..." if not is_fallback else "● BUFFERING NEXT CHUNK..."
                        cv2.putText(
                            display_frame,
                            banner_text,
                            (20, 24),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.65,
                            (0, 215, 255),
                            2,
                            cv2.LINE_AA,
                        )
                        success, encoded_jpg = cv2.imencode(".jpg", display_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                        if success:
                            self._write_frame(encoded_jpg.tobytes())
                            last_sent_time = now
                            self.state.record_mjpeg_publish(success=True)
                    else:
                        # No valid frame for this generation yet: send explicit placeholder (C4)
                        self._write_frame(placeholder_bytes)
                        last_sent_time = now
                        self.state.record_mjpeg_publish(success=True)

                time.sleep(0.015)

        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout, EOFError):
            pass
        finally:
            self.server.owner.release_video_client(self, self._video_session)
            self._video_session = None
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except (OSError, AttributeError):
                pass
            try:
                self.connection.close()
            except OSError:
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
            self.state.clear_frames(increment_generation=True)
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

    def handle_video_source(self) -> None:
        """Return runtime details of current video source."""
        if self.camera_manager is None:
            self._send_json_response({"status": "error", "message": "CameraManager not connected"}, code=503)
            return
        info = self.camera_manager.get_current_source_info()
        self._send_json_response({"status": "ok", "source": info})

    def handle_targets(self) -> None:
        """Return list of currently registered targets."""
        targets = [t.to_dict() for t in target_manager.list_targets()]
        self._send_json_response({"status": "ok", "targets": targets})

    def _execute_set_video_source(self, data: dict[str, Any]) -> None:
        """Switch video source to Local MP4 or YouTube VOD."""
        if self.camera_manager is None:
            self._send_json_response(
                {"status": "error", "message": "CameraManager not connected to server"}, code=503
            )
            return

        stype = data.get("type") or data.get("source_type") or "local"
        src = data.get("source", "")
        loop = bool(data.get("loop", True))
        name = data.get("name")

        if not src:
            self._send_json_response({"status": "error", "message": "Missing 'source' parameter"}, code=400)
            return

        try:
            self.state.clear_frames(increment_generation=True)
            cam_info = self.camera_manager.set_video_source(source_type=stype, source=src, loop=loop, name=name)
            self.state.set_camera(cam_info.id, cam_info.name)
            self._send_json_response({
                "status": "ok",
                "camera": cam_info.to_dict(),
                "message": f"Successfully set video source: {cam_info.name}",
            })
        except Exception as exc:
            self.state.set_status("ERROR", f"Failed setting video source: {exc}")
            self._send_json_response({"status": "error", "message": str(exc)}, code=400)

    def _execute_register_target(self, data: dict[str, Any]) -> None:
        """Register target via JSON payload."""
        import base64
        name = data.get("name", "")
        color = data.get("color") or data.get("clothing_color")
        threshold = float(data.get("threshold", data.get("face_threshold", 0.45)))
        target_id = data.get("id") or data.get("target_id")
        b64_img = data.get("face_image") or data.get("face_image_base64")

        img = None
        if b64_img and isinstance(b64_img, str):
            try:
                if "," in b64_img:
                    b64_img = b64_img.split(",", 1)[1]
                img_bytes = base64.b64decode(b64_img)
                img, decode_meta = decode_face_image_bytes(img_bytes)
                if not decode_meta.get("success"):
                    self._send_json_response({
                        "status": "error",
                        "code": "IMAGE_DECODE_FAILED",
                        "message": decode_meta.get("error") or "Failed to decode image bytes",
                    }, code=400)
                    return
            except Exception as exc:
                self._send_json_response({"status": "error", "code": "IMAGE_DECODE_FAILED", "message": f"Invalid base64 image: {exc}"}, code=400)
                return

        try:
            target = target_manager.register_target(
                name=name,
                face_image=img,
                clothing_color=color,
                face_threshold=threshold,
                target_id=target_id,
            )
            self._send_json_response({
                "status": "ok",
                "target": target.to_dict(),
                "message": f"Target '{target.name}' registered successfully",
            })
        except TargetRegistrationError as exc:
            self._send_json_response({
                "status": "error",
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }, code=400)
        except Exception as exc:
            self._send_json_response({"status": "error", "code": "VALIDATION_ERROR", "message": str(exc)}, code=400)

    def handle_public_cameras(self, query: dict[str, list[str]]) -> None:
        """Return public CCTV camera catalog for Caltrans and/or Seattle SDOT."""
        search_query = query.get("q", [""])[0] or query.get("query", [""])[0]
        force_refresh = query.get("refresh", ["false"])[0].lower() in ("true", "1")
        provider = query.get("provider", [""])[0].lower().strip()

        try:
            cameras: list[dict[str, Any]] = []
            if provider in ("seattle", "seattle_sdot", "sdot"):
                cameras = seattle_service.get_cameras(force_refresh=force_refresh, query=search_query)
            elif provider in ("all", "*"):
                seattle_cams = seattle_service.get_cameras(force_refresh=force_refresh, query=search_query)
                caltrans_cams = caltrans_service.get_cameras(force_refresh=force_refresh, query=search_query)
                cameras = seattle_cams + caltrans_cams
            else:
                # Default / caltrans: preserves 100% backward compatibility
                cameras = caltrans_service.get_cameras(force_refresh=force_refresh, query=search_query)

            self._send_json_response({
                "status": "ok",
                "cameras": cameras,
                "total": len(cameras),
                "provider": provider or "caltrans",
            })
        except Exception as exc:
            self._send_json_response({"status": "error", "message": str(exc), "cameras": []}, code=500)

    def handle_source_status(self) -> None:
        """Return connection verification status for active video source."""
        if self.camera_manager is None:
            self._send_json_response({
                "status": "STOPPED",
                "is_ready": False,
                "frames_received": 0,
                "frame_age_seconds": 999.0,
                "stream_alive": False,
                "error_reason": "CameraManager not connected",
            })
            return

        source_info = self.camera_manager.get_current_source_info()
        diag = source_info.get("diagnostics", {})
        frames = diag.get("frames_received", 0)
        age = self.camera_manager.frame_age_seconds
        alive = self.camera_manager.stream_alive
        status = self.camera_manager.status
        is_ready = self.camera_manager.is_connection_ready(max_frame_age=5.0)

        self._send_json_response({
            "status": status,
            "is_ready": is_ready,
            "frames_received": frames,
            "frame_age_seconds": round(age, 2),
            "stream_alive": alive,
            "error_reason": self.camera_manager.error_reason,
            "ffmpeg_pid": diag.get("ffmpeg_pid"),
            "diagnostics": diag,
            "camera": {
                "id": source_info.get("id"),
                "name": source_info.get("name"),
                "type": source_info.get("type"),
                "url": source_info.get("url"),
            },
        })

    def handle_camera_snapshot(self, query: dict[str, list[str]]) -> None:
        """Proxy remote camera snapshot JPEG image."""
        snap_url = query.get("url", [""])[0]
        if not snap_url:
            self.send_response(400)
            self.end_headers()
            return

        img_bytes = preview_manager.fetch_snapshot_image(snap_url)
        if img_bytes is None:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(img_bytes)))
        self.send_header("Cache-Control", "public, max-age=30")
        self.end_headers()
        self.wfile.write(img_bytes)

    def handle_camera_thumbnail(self, query: dict[str, list[str]]) -> None:
        """Serve representative camera thumbnail via ThumbnailService."""
        from src.stream.thumbnail_service import thumbnail_service
        cam_id = query.get("camera_id", [""])[0]
        stream_url = query.get("stream_url", [""])[0]
        snapshot_url = query.get("snapshot_url", [""])[0]
        provider = query.get("provider", [""])[0]

        img_bytes, content_type = thumbnail_service.get_thumbnail(
            camera_id=cam_id,
            stream_url=stream_url,
            snapshot_url=snapshot_url,
            provider=provider,
        )

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(img_bytes)))
        self.send_header("Cache-Control", "public, max-age=90")
        self.end_headers()
        self.wfile.write(img_bytes)

    def handle_preview_feed(self, query: dict[str, list[str]]) -> None:
        """Stream lightweight preview MJPEG (zero AI)."""
        stream_url = query.get("url", [""])[0]
        provider = query.get("provider", [""])[0]
        headers = None
        if provider in ("Seattle SDOT", "seattle", "seattle_sdot"):
            headers = dict(SEATTLE_STREAM_HEADERS)

        if stream_url and preview_manager.get_active_url() != stream_url:
            preview_manager.start_preview(stream_url, headers=headers)

        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache, private")
        self.end_headers()

        blank_frame = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(blank_frame, "CONNECTING PREVIEW...", (160, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 229, 255), 2)
        _, blank_jpeg = cv2.imencode(".jpg", blank_frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
        blank_bytes = blank_jpeg.tobytes()

        try:
            self._write_frame(blank_bytes)
            while preview_manager.is_active():
                frame_bytes = preview_manager.get_latest_frame_jpeg()
                if frame_bytes is not None:
                    self._write_frame(frame_bytes)
                    time.sleep(0.06)  # ~15 FPS
                else:
                    time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            pass
        finally:
            self.close_connection = True

    def _execute_select_source(self, data: dict[str, Any]) -> None:
        """Safely switch or start a selected camera source."""
        if self.camera_manager is None:
            self._send_json_response({"status": "error", "message": "CameraManager not connected"}, code=503)
            return

        preview_manager.stop_preview()

        stype = str(data.get("source_type") or data.get("type") or "direct_hls").lower().strip()
        source = str(data.get("source") or data.get("stream_url") or data.get("url") or "").strip()
        name = data.get("name") or data.get("locationName")
        provider = data.get("provider") or ""
        loop = bool(data.get("loop", True))

        headers = data.get("headers")
        if not headers and provider in ("Seattle SDOT", "seattle", "seattle_sdot"):
            headers = dict(SEATTLE_STREAM_HEADERS)

        if not source:
            self._send_json_response({"status": "error", "message": "Source cannot be empty"}, code=400)
            return

        # Enter switching mode: suppress spurious ERROR status from AI pipeline
        # during the brief frame gap while the source is being replaced.
        self.state.set_switching()
        self.state.clear_frames(increment_generation=True)

        try:
            cam_info = self.camera_manager.set_video_source(
                source_type=stype,
                source=source,
                loop=loop,
                name=name,
                headers=headers,
            )
            self.state.set_camera(cam_info.id, cam_info.name)
            self.state.set_status("RUNNING")
            # Start a background timer to clear switching guard after 5s
            # (handles the case where no frame arrives and ERROR needs to propagate)
            import threading
            def _clear_switching_after_delay():
                import time as _time
                _time.sleep(5.0)
                self.state.clear_switching()
            t = threading.Thread(target=_clear_switching_after_delay, daemon=True, name="ClearSwitching")
            t.start()
            self._send_json_response({
                "status": "ok",
                "message": f"Connecting to {cam_info.name}...",
                "camera": cam_info.to_dict(),
            })
        except Exception as exc:
            self.state.clear_switching()
            self.state.set_status("ERROR", str(exc))
            self._send_json_response({"status": "error", "message": str(exc)}, code=500)

    def _execute_stop_camera(self) -> None:
        """Stop active camera and transition pipeline to IDLE state."""
        preview_manager.stop_preview()
        if self.camera_manager is not None:
            self.camera_manager.stop_camera()
        self.state.set_camera("", "")
        self.state.clear_frames()
        self.state.set_status("IDLE")
        self._send_json_response({"status": "ok", "message": "Camera stopped successfully"})

    def _execute_stop_preview(self) -> None:
        """Stop active preview."""
        preview_manager.stop_preview()
        self._send_json_response({"status": "ok", "message": "Preview stopped"})

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
        self._client_lock = threading.Lock()
        self._active_clients: dict[int, StreamRequestHandler] = {}
        self._max_clients = 8
        self._client_generation = 0

    def claim_video_client(self, handler: StreamRequestHandler) -> int:
        """Allow concurrent streams without violent eviction (Requirement C5)."""
        with self._client_lock:
            self._client_generation += 1
            token = self._client_generation
            if len(self._active_clients) >= self._max_clients:
                oldest_token = min(self._active_clients.keys())
                old_handler = self._active_clients.pop(oldest_token, None)
                if old_handler is not None:
                    old_handler.close_connection = True
            self._active_clients[token] = handler
            self.state.set_mjpeg_clients(len(self._active_clients), self._client_generation)
            return token

    def release_video_client(self, handler: StreamRequestHandler, token: int | None) -> None:
        with self._client_lock:
            if token is not None:
                self._active_clients.pop(token, None)
            self.state.set_mjpeg_clients(len(self._active_clients), self._client_generation)

    def start(self) -> None:
        """Start the MJPEG HTTP server in a daemon thread."""
        StreamRequestHandler.state = self.state
        StreamRequestHandler.camera_manager = self.camera_manager

        # Use ThreadingHTTPServer so each stream connection runs concurrently
        self._server = ThreadingHTTPServer((self.host, self.port), StreamRequestHandler)
        self._server.owner = self
        self._server.daemon_threads = True
        self._server.allow_reuse_address = True
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
