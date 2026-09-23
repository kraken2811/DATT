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
import httpx
import uvicorn

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
