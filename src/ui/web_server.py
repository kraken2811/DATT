"""FastAPI Web UI Server for DATT - AI People Counter.

Phase 4.4: Stable Browser-based Vision Monitor & Camera Manager.
Replaces Streamlit with a high-performance, long-runtime FastAPI server
serving pure HTML/CSS/JavaScript.

Routes:
- GET /                    : Serves static/index.html
- /static/*                : Static assets (style.css, app.js)
- GET /telemetry           : Realtime AI telemetry JSON
- GET /cameras             : Camera configuration & active camera
- GET/POST /switch_camera  : Dynamic camera switching
- GET /events              : Latest 5 occupancy events
- GET /event_snapshot      : Image snapshot retrieval
- GET /video_feed          : Native multipart/x-mixed-replace MJPEG stream

Usage:
    python src/ui/web_server.py --host 0.0.0.0 --port 8501 --backend-url http://localhost:8000
"""

import argparse
import asyncio
import logging
import os
from pathlib import Path
import sys
from typing import Any
import urllib.parse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import cv2
import httpx
import numpy as np
import uvicorn

from src.recognition.target_matcher import target_manager
from src.stream.caltrans_service import caltrans_service
from src.stream.preview_manager import preview_manager
from src.stream.seattle_sdot_service import seattle_service

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("datt.web_server")

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="DATT AI Vision Monitor & Camera Manager",
    description="FastAPI Web UI replacing Streamlit for continuous, rock-solid monitoring on Colab and Server.",
    version="4.4.0",
)

# Enable CORS for maximum flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Default backend URL
app.state.backend_url = os.environ.get("AI_SERVER_URL", "http://localhost:8000")


def get_backend_url(request: Request) -> str:
    """Resolve backend AI server URL with request header/param override support."""
    param_url = request.query_params.get("backend_url")
    header_url = request.headers.get("X-Backend-URL")
    if param_url:
        return param_url
    if header_url:
        return header_url
    return getattr(request.app.state, "backend_url", "http://localhost:8000")


# -----------------------------------------------------------------------------
# Static & HTML Delivery
# -----------------------------------------------------------------------------

# Mount /static for CSS, JS, icons
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Serve favicon.ico or return 204 No Content."""
    favicon_path = STATIC_DIR / "favicon.ico"
    if favicon_path.is_file():
        return FileResponse(str(favicon_path), media_type="image/x-icon")
    return Response(status_code=204)


@app.get("/", response_class=FileResponse)
async def serve_index() -> Response:
    """Serve the single-page monitoring dashboard."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.is_file():
        return Response(
            content="""<!DOCTYPE html>
<html>
<head><title>DATT UI Starting...</title></head>
<body style="background:#0e1117;color:#fff;font-family:sans-serif;padding:2rem;">
    <h2>DATT AI Vision Monitor (Phase 4.4)</h2>
    <p>Waiting for static assets to initialize at <code>src/ui/static/index.html</code>...</p>
</body>
</html>""",
            media_type="text/html",
        )
    return FileResponse(str(index_file))


# -----------------------------------------------------------------------------
# Telemetry API (1-second polling)
# -----------------------------------------------------------------------------

@app.get("/telemetry")
@app.get("/api/telemetry")
async def get_telemetry(request: Request) -> JSONResponse:
    """Fetch realtime AI telemetry or return disconnected fallback."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{b_url}/telemetry")
            if resp.status_code == 200:
                data = resp.json()
                if "camera_status" not in data:
                    data["camera_status"] = data.get("status", "RUNNING")
                if "stream_alive" not in data:
                    data["stream_alive"] = data["camera_status"] in ("RUNNING", "WARNING")
                if "last_frame_time" not in data:
                    data["last_frame_time"] = data.get("timestamp", 0.0)
                if "error_message" not in data or not data["error_message"]:
                    data["error_message"] = None
                return JSONResponse(content=data, status_code=200)
    except Exception as exc:
        logger.debug("Backend telemetry unreachable (%s): %s", b_url, exc)

    # Disconnected payload matching SharedRuntimeState schema
    return JSONResponse(
        content={
            "status": "DISCONNECTED",
            "camera_status": "DISCONNECTED",
            "stream_alive": False,
            "last_frame_time": 0.0,
            "error_message": f"Connecting to AI pipeline at {b_url}... Ensure 'python src/main.py' is active.",
            "people_count": 0,
            "detection_count": 0,
            "track_count": 0,
            "stream_fps": 0.0,
            "processing_fps": 0.0,
            "yolo_latency_ms": 0.0,
            "pipeline_latency_ms": 0.0,
            "device": "N/A",
            "gpu_name": "N/A",
            "vram_mb": 0.0,
            "model_name": "YOLO11s",
            "input_size": "640x640",
            "camera_id": "N/A",
            "camera_name": "Disconnected",
            "last_event": "None",
            "event_count_today": 0,
            "filtered_event_count": 0,
            "last_event_time": "None",
            "last_saved_people_count": 0,
        },
        status_code=200,
    )


# -----------------------------------------------------------------------------
# Camera API
# -----------------------------------------------------------------------------

@app.get("/cameras")
@app.get("/api/cameras")
async def get_cameras(request: Request) -> JSONResponse:
    """Fetch list of available cameras and active camera."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(f"{b_url}/cameras")
            if resp.status_code == 200:
                return JSONResponse(content=resp.json(), status_code=200)
    except Exception as exc:
        logger.debug("Backend cameras unreachable (%s): %s", b_url, exc)

    # Fallback to local camera config file
    try:
        from src.config.camera_config import list_cameras
        cams = [c.to_dict() for c in list_cameras()]
        return JSONResponse(
            content={
                "status": "ok",
                "active_camera_id": "camera_01",
                "cameras": cams,
            },
            status_code=200,
        )
    except Exception as exc:
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Cameras unavailable: {exc}",
                "cameras": [],
            },
            status_code=503,
        )


@app.get("/switch_camera")
@app.get("/api/switch_camera")
@app.post("/switch_camera")
@app.post("/api/switch_camera")
async def switch_camera(request: Request) -> JSONResponse:
    """Switch active camera on the AI streaming server."""
    b_url = get_backend_url(request).rstrip("/")
    cam_id = request.query_params.get("id") or request.query_params.get("camera_id")

    if not cam_id and request.method == "POST":
        try:
            body = await request.json()
            cam_id = body.get("camera_id") or body.get("id")
        except Exception:
            pass

    if not cam_id:
        return JSONResponse(
            content={"status": "error", "message": "Missing camera_id or id parameter"},
            status_code=400,
        )

    try:
        encoded_id = urllib.parse.quote(str(cam_id))
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(f"{b_url}/switch_camera?id={encoded_id}")
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"status": "error", "message": f"Camera switch failed: {exc}"},
            status_code=503,
        )


# -----------------------------------------------------------------------------
# Video Source Management API
# -----------------------------------------------------------------------------

@app.post("/set_video_source")
@app.post("/api/set_video_source")
async def set_video_source(request: Request) -> JSONResponse:
    """Set active video source to Local MP4 or YouTube VOD."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        body = await request.json()
    except Exception:
        body = {}

    stype = str(body.get("type") or body.get("source_type") or "local").lower().strip()
    source = str(body.get("source", "")).strip()
    loop = bool(body.get("loop", True))
    name = body.get("name")

    if not source:
        return JSONResponse(
            content={"status": "error", "message": "Source path or URL cannot be empty"},
            status_code=400,
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{b_url}/set_video_source",
                json={"type": stype, "source": source, "loop": loop, "name": name},
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"status": "error", "message": f"Failed setting video source on backend: {exc}"},
            status_code=503,
        )


@app.get("/video_source")
@app.get("/api/video_source")
async def get_video_source(request: Request) -> JSONResponse:
    """Get active video source info."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{b_url}/video_source")
            if resp.status_code == 200:
                return JSONResponse(content=resp.json(), status_code=200)
    except Exception as exc:
        logger.debug("Backend video_source unreachable: %s", exc)

    return JSONResponse(
        content={"status": "ok", "source": {"type": "default", "status": "RUNNING"}},
        status_code=200,
    )


# -----------------------------------------------------------------------------
# Public CCTV Cameras & Source Selection API
# -----------------------------------------------------------------------------

@app.get("/public_cameras")
@app.get("/api/public_cameras")
async def get_public_cameras(request: Request) -> JSONResponse:
    """Retrieve Public CCTV camera catalog (Caltrans or Seattle SDOT)."""
    q = request.query_params.get("q") or request.query_params.get("query", "")
    force_refresh = request.query_params.get("refresh", "false").lower() in ("true", "1")
    provider = request.query_params.get("provider", "").lower().strip()
    b_url = get_backend_url(request).rstrip("/")

    try:
        if provider in ("seattle", "seattle_sdot", "sdot"):
            cams = seattle_service.get_cameras(force_refresh=force_refresh, query=q)
        elif provider in ("all", "*"):
            seattle_cams = seattle_service.get_cameras(force_refresh=force_refresh, query=q)
            caltrans_cams = caltrans_service.get_cameras(force_refresh=force_refresh, query=q)
            cams = seattle_cams + caltrans_cams
        else:
            cams = caltrans_service.get_cameras(force_refresh=force_refresh, query=q)

        return JSONResponse(
            content={"status": "ok", "cameras": cams, "total": len(cams), "provider": provider or "caltrans"},
            status_code=200,
        )
    except Exception as exc:
        logger.debug("Local public camera fetch failed (%s), proxying to backend...", exc)

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                f"{b_url}/public_cameras?provider={urllib.parse.quote(provider)}&q={urllib.parse.quote(q)}"
            )
            if resp.status_code == 200:
                return JSONResponse(content=resp.json(), status_code=200)
    except Exception as exc:
        logger.debug("Backend public_cameras failed: %s", exc)

    if provider in ("seattle", "seattle_sdot", "sdot"):
        cams = seattle_service.get_cameras(query=q)
    else:
        cams = caltrans_service.get_cameras(query=q)
    return JSONResponse(
        content={"status": "ok", "cameras": cams, "total": len(cams), "provider": provider or "caltrans"},
        status_code=200,
    )


@app.post("/select_source")
@app.post("/api/select_source")
async def select_source(request: Request) -> JSONResponse:
    """Safely select and activate a camera source (Direct HLS, Local, YouTube)."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        body = await request.json()
    except Exception:
        body = {}

    preview_manager.stop_preview()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{b_url}/select_source", json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"status": "error", "message": f"Failed selecting camera source on backend: {exc}"},
            status_code=503,
        )


@app.post("/stop_camera")
@app.post("/api/stop_camera")
async def stop_camera(request: Request) -> JSONResponse:
    """Safely stop active camera and return to IDLE/selection state."""
    b_url = get_backend_url(request).rstrip("/")
    preview_manager.stop_preview()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(f"{b_url}/stop_camera")
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"status": "error", "message": f"Failed stopping camera on backend: {exc}"},
            status_code=503,
        )


@app.get("/source_status")
@app.get("/api/source_status")
async def get_source_status(request: Request) -> JSONResponse:
    """Get active source connection verification status."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(f"{b_url}/source_status")
            if resp.status_code == 200:
                return JSONResponse(content=resp.json(), status_code=200)
    except Exception as exc:
        logger.debug("Backend source_status unreachable: %s", exc)

    return JSONResponse(
        content={
            "status": "STOPPED",
            "is_ready": False,
            "frames_received": 0,
            "frame_age_seconds": 999.0,
            "stream_alive": False,
            "error_reason": "Backend unreachable",
        },
        status_code=200,
    )


@app.get("/camera_snapshot")
@app.get("/api/camera_snapshot")
async def get_camera_snapshot(request: Request) -> Response:
    """Proxy remote camera snapshot JPEG image."""
    url = request.query_params.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="Missing snapshot url")

    data = preview_manager.fetch_snapshot_image(url)
    if data is not None:
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=30", "Access-Control-Allow-Origin": "*"},
        )

    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{b_url}/camera_snapshot?url={urllib.parse.quote(url)}")
            if resp.status_code == 200:
                return Response(
                    content=resp.content,
                    media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=30", "Access-Control-Allow-Origin": "*"},
                )
    except Exception:
        pass
    raise HTTPException(status_code=404, detail="Snapshot image unavailable")


@app.post("/stop_preview")
@app.post("/api/stop_preview")
async def stop_preview_route(request: Request) -> JSONResponse:
    """Safely terminate preview resources."""
    preview_manager.stop_preview()
    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{b_url}/stop_preview")
    except Exception:
        pass
    return JSONResponse(content={"status": "ok", "message": "Preview stopped"})


@app.get("/preview_feed")
@app.get("/api/preview_feed")
async def preview_feed(request: Request) -> Response:
    """Relay lightweight preview MJPEG stream without AI."""
    b_url = get_backend_url(request).rstrip("/")
    stream_url = request.query_params.get("url", "")
    target_url = f"{b_url}/preview_feed?url={urllib.parse.quote(stream_url)}"

    try:
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=3.0, read=None, write=5.0, pool=None))
        req = client.build_request("GET", target_url)
        resp = await client.send(req, stream=True)
        if resp.status_code != 200:
            await resp.aclose()
            await client.aclose()
            return Response(content=b"Preview stream unavailable", status_code=503, media_type="text/plain")
    except Exception:
        return Response(content=b"Preview feed offline", status_code=503, media_type="text/plain")

    async def stream_mjpeg():
        try:
            async for chunk in resp.aiter_raw():
                if await request.is_disconnected():
                    break
                yield chunk
        except Exception:
            pass
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, private, no-store", "Access-Control-Allow-Origin": "*"},
    )


# -----------------------------------------------------------------------------
# Target Registration & Management API
# -----------------------------------------------------------------------------

@app.get("/targets")
@app.get("/api/targets")
async def get_targets() -> JSONResponse:
    """Retrieve all registered targets."""
    targets = [t.to_dict() for t in target_manager.list_targets()]
    return JSONResponse(content={"status": "ok", "targets": targets}, status_code=200)


@app.post("/register_target")
@app.post("/api/register_target")
async def register_target(request: Request) -> JSONResponse:
    """Register a new target with face image and/or clothing color.

    Supports both multipart/form-data (file upload) and application/json.
    """
    content_type = request.headers.get("content-type", "").lower()
    name = ""
    color = None
    threshold = 0.45
    img = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        name = str(form.get("name", "")).strip()
        raw_color = form.get("color") or form.get("clothing_color")
        color = str(raw_color).strip() if raw_color else None

        thresh_val = form.get("threshold") or form.get("face_threshold")
        if thresh_val:
            try:
                threshold = float(thresh_val)
            except ValueError:
                threshold = 0.45

        file_obj = form.get("face_image")
        if file_obj is not None and hasattr(file_obj, "read"):
            content = await file_obj.read()
            if content:
                nparr = np.frombuffer(content, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    else:
        try:
            body = await request.json()
        except Exception:
            body = {}
        name = str(body.get("name", "")).strip()
        raw_color = body.get("color") or body.get("clothing_color")
        color = str(raw_color).strip() if raw_color else None
        threshold = float(body.get("threshold", body.get("face_threshold", 0.45)))

        b64_img = body.get("face_image") or body.get("face_image_base64")
        if b64_img and isinstance(b64_img, str):
            try:
                import base64
                if "," in b64_img:
                    b64_img = b64_img.split(",", 1)[1]
                img_bytes = base64.b64decode(b64_img)
                nparr = np.frombuffer(img_bytes, np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            except Exception as exc:
                return JSONResponse(
                    content={"status": "error", "message": f"Invalid base64 image: {exc}"},
                    status_code=400,
                )

    if not name:
        return JSONResponse(
            content={"status": "error", "message": "Target name is required"},
            status_code=400,
        )

    try:
        target = target_manager.register_target(
            name=name,
            face_image=img,
            clothing_color=color,
            face_threshold=threshold,
        )
        return JSONResponse(
            content={
                "status": "ok",
                "target": target.to_dict(),
                "message": f"Target '{target.name}' registered successfully",
            },
            status_code=200,
        )
    except ValueError as exc:
        return JSONResponse(content={"status": "error", "message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse(
            content={"status": "error", "message": f"Registration failed: {exc}"},
            status_code=500,
        )


@app.delete("/targets/{target_id}")
@app.delete("/api/targets/{target_id}")
async def delete_target(target_id: str, request: Request) -> JSONResponse:
    """Remove a registered target by ID."""
    b_url = get_backend_url(request).rstrip("/")
    removed = target_manager.remove_target(target_id)

    # Also notify backend server if remote
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.delete(f"{b_url}/targets/{target_id}")
    except Exception:
        pass

    if removed:
        return JSONResponse(
            content={"status": "ok", "message": f"Target '{target_id}' removed"},
            status_code=200,
        )
    return JSONResponse(
        content={"status": "error", "message": f"Target '{target_id}' not found"},
        status_code=404,
    )


# Cache mapping event_id -> snapshot_path for fast lookup
event_snapshot_cache: dict[str, str] = {}


# -----------------------------------------------------------------------------
# Event API (10-second polling)
# -----------------------------------------------------------------------------

@app.get("/events")
@app.get("/api/events")
async def get_events(request: Request) -> JSONResponse:
    """Fetch recent occupancy events (latest 5 only)."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        limit = int(request.query_params.get("limit", 5))
    except ValueError:
        limit = 5
    limit = min(max(limit, 1), 5)  # Enforce at most 5 latest events

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{b_url}/events?limit={limit}")
            if resp.status_code == 200:
                data = resp.json()
                raw_events = data.get("events", [])[:5]
                normalized = []
                for ev in raw_events:
                    ev_id = ev.get("id")
                    snap_path = ev.get("snapshot_path", "")
                    if ev_id is not None and snap_path:
                        event_snapshot_cache[str(ev_id)] = snap_path

                    normalized.append({
                        "id": ev_id,
                        "snapshot_id": ev_id,
                        "timestamp": ev.get("timestamp"),
                        "camera_id": ev.get("camera_id"),
                        "old_count": ev.get("old_value", 0),
                        "new_count": ev.get("new_value", 0),
                        "old_value": ev.get("old_value", 0),
                        "new_value": ev.get("new_value", 0),
                        "snapshot_path": snap_path,
                    })
                return JSONResponse(
                    content={
                        "status": "ok",
                        "events": normalized,
                        "event_count_today": data.get("event_count_today", 0),
                    },
                    status_code=200,
                )
    except Exception as exc:
        logger.debug("Backend events unreachable (%s): %s", b_url, exc)

    # Fallback to local SQLite events database
    try:
        from src.events.event_storage import event_storage
        events = event_storage.get_recent_events(limit=limit)
        today_count = event_storage.get_event_count_today()
        normalized = []
        for ev in events[:5]:
            ev_id = ev.get("id")
            snap_path = ev.get("snapshot_path", "")
            if ev_id is not None and snap_path:
                event_snapshot_cache[str(ev_id)] = snap_path

            normalized.append({
                "id": ev_id,
                "snapshot_id": ev_id,
                "timestamp": ev.get("timestamp"),
                "camera_id": ev.get("camera_id"),
                "old_count": ev.get("old_value", 0),
                "new_count": ev.get("new_value", 0),
                "old_value": ev.get("old_value", 0),
                "new_value": ev.get("new_value", 0),
                "snapshot_path": snap_path,
            })
        return JSONResponse(
            content={
                "status": "ok",
                "events": normalized,
                "event_count_today": today_count,
            },
            status_code=200,
        )
    except Exception:
        return JSONResponse(
            content={"status": "ok", "events": [], "event_count_today": 0},
            status_code=200,
        )


# -----------------------------------------------------------------------------
# Snapshot API
# -----------------------------------------------------------------------------

@app.get("/event_snapshot")
@app.get("/api/event_snapshot")
async def get_event_snapshot(request: Request) -> Response:
    """Serve snapshot JPEG image requested by id or path."""
    b_url = get_backend_url(request).rstrip("/")
    rel_path = request.query_params.get("path", "")
    event_id = request.query_params.get("id", "")

    # Resolve path from memory cache or SQLite if id provided
    if not rel_path and event_id:
        cached_path = event_snapshot_cache.get(str(event_id))
        if cached_path:
            rel_path = cached_path
        else:
            try:
                from src.events.event_storage import event_storage
                import sqlite3
                with event_storage._lock:
                    with sqlite3.connect(event_storage.db_path) as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT snapshot_path FROM events WHERE id = ?", (event_id,))
                        row = cur.fetchone()
                        if row and row[0]:
                            rel_path = row[0]
                            event_snapshot_cache[str(event_id)] = rel_path
            except Exception as exc:
                logger.debug("Failed resolving snapshot path from id %s: %s", event_id, exc)

    if not rel_path and not event_id:
        raise HTTPException(status_code=400, detail="Missing snapshot path or id")

    # Security check: resolve strictly within data/events/
    target_file = (PROJECT_ROOT / rel_path).resolve()
    snapshot_dir = (PROJECT_ROOT / "data" / "events").resolve()

    if str(target_file).startswith(str(snapshot_dir)) and target_file.is_file():
        return FileResponse(
            path=str(target_file),
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Access-Control-Allow-Origin": "*",
            },
        )

    # Forward request to backend server
    try:
        encoded_path = urllib.parse.quote(rel_path)
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(f"{b_url}/event_snapshot?path={encoded_path}")
            if resp.status_code == 200:
                return Response(
                    content=resp.content,
                    media_type="image/jpeg",
                    headers={
                        "Cache-Control": "public, max-age=86400",
                        "Access-Control-Allow-Origin": "*",
                    },
                )
            raise HTTPException(status_code=resp.status_code, detail="Snapshot not found on backend")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Snapshot unavailable: {exc}")


# -----------------------------------------------------------------------------
# Video Stream API (Native MJPEG Relay)
# -----------------------------------------------------------------------------

@app.get("/video_feed")
@app.get("/api/video_feed")
async def video_feed(request: Request) -> Response:
    """Relay MJPEG stream directly from AI pipeline server."""
    b_url = get_backend_url(request).rstrip("/")
    target_url = f"{b_url}/video_feed"

    try:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.0, read=None, write=5.0, pool=None)
        )
        req = client.build_request("GET", target_url)
        resp = await client.send(req, stream=True)
        if resp.status_code != 200:
            await resp.aclose()
            await client.aclose()
            return Response(
                content=b"Video stream temporarily unavailable",
                status_code=503,
                media_type="text/plain",
            )
    except Exception as exc:
        logger.debug("Failed opening video feed stream to %s: %s", target_url, exc)
        return Response(
            content=b"Video feed offline. Connecting to camera pipeline...",
            status_code=503,
            media_type="text/plain",
        )

    async def stream_mjpeg():
        try:
            async for chunk in resp.aiter_raw():
                if await request.is_disconnected():
                    break
                yield chunk
        except (
            asyncio.CancelledError,
            BrokenPipeError,
            ConnectionResetError,
            OSError,
            httpx.RequestError,
        ):
            pass
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(
        stream_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, private, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Age": "0",
            "Access-Control-Allow-Origin": "*",
        },
    )


# -----------------------------------------------------------------------------
# Status Route
# -----------------------------------------------------------------------------

@app.get("/status")
@app.get("/api/status")
async def get_status(request: Request) -> JSONResponse:
    """Operational status check."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"{b_url}/status")
            if resp.status_code == 200:
                return JSONResponse(content=resp.json(), status_code=200)
    except Exception:
        pass
    return JSONResponse(
        content={"status": "DISCONNECTED", "error_message": "AI pipeline offline"},
        status_code=200,
    )


# -----------------------------------------------------------------------------
# CLI Entry Point
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """Parse command line flags."""
    parser = argparse.ArgumentParser(description="DATT - FastAPI Web UI Server (Phase 4.4)")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host interface (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port to listen on (default: 8501 for Colab compatibility)",
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=os.environ.get("AI_SERVER_URL", "http://localhost:8000"),
        help="Base URL of DATT AI streaming server (default: http://localhost:8000)",
    )
    return parser.parse_args()


def main() -> None:
    """Run Uvicorn ASGI server."""
    args = parse_args()
    app.state.backend_url = args.backend_url
    logger.info("==================================================")
    logger.info("Starting DATT FastAPI Web Dashboard (Phase 4.4)")
    logger.info("Web Dashboard UI: http://%s:%d", args.host, args.port)
    logger.info("AI Pipeline URL:  %s", args.backend_url)
    logger.info("==================================================")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
