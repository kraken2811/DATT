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
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import sys
import struct
import time
from typing import Any
import urllib.parse
import uuid

from fastapi import FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import cv2
import httpx
import numpy as np
import uvicorn
# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.storage import get_storage, validate_key, StorageUploadTooLarge
from src.face.face_embedder import decode_face_image_bytes
from src.recognition.target_matcher import TargetRegistrationError, target_manager
from src.stream.caltrans_service import caltrans_service
from src.stream.preview_manager import preview_manager
from src.stream.seattle_sdot_service import seattle_service

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

from src.ui.camera_capture import router as camera_capture_router
app.include_router(camera_capture_router)


@app.get('/api/runtime_devices')
def runtime_devices(instrument: bool = False):
    from src.runtime.device_audit import snapshot
    return snapshot(instrument=instrument)

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


_backend_client: httpx.AsyncClient | None = None


def get_backend_http_client() -> httpx.AsyncClient:
    """Return persistent, connection-pooled AsyncClient for low-latency backend requests (Phase D)."""
    global _backend_client
    if _backend_client is None or _backend_client.is_closed:
        _backend_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=2.0, read=4.0, write=4.0, pool=4.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
    return _backend_client


@app.on_event("shutdown")
async def shutdown_backend_client() -> None:
    global _backend_client
    if _backend_client is not None and not _backend_client.is_closed:
        await _backend_client.aclose()
        _backend_client = None


# -----------------------------------------------------------------------------
# Static & HTML Delivery
# -----------------------------------------------------------------------------

# Mount /static for CSS, JS, icons
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

REACT_DIST = STATIC_DIR / "react_dist"
if (REACT_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=str(REACT_DIST / "assets")), name="react_assets")


def get_index_path() -> Path:
    if (REACT_DIST / "index.html").is_file():
        return REACT_DIST / "index.html"
    return STATIC_DIR / "index.html"


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    """Serve favicon.ico or return 204 No Content."""
    favicon_path = STATIC_DIR / "favicon.ico"
    if favicon_path.is_file():
        return FileResponse(str(favicon_path), media_type="image/x-icon")
    return Response(status_code=204)


@app.get("/legacy", response_class=FileResponse)
async def serve_legacy() -> Response:
    """Serve legacy frontend for Feature Parity comparison."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/", response_class=FileResponse)
@app.get("/dashboard", response_class=FileResponse)
@app.get("/watchlist", response_class=FileResponse)
@app.get("/alerts", response_class=FileResponse)
@app.get("/settings", response_class=FileResponse)
@app.get("/agent", response_class=FileResponse)
@app.get("/cameras/{camera_id}", response_class=FileResponse)
async def serve_index(request: Request) -> Response:
    """Serve the single-page monitoring dashboard (React SPA or fallback)."""
    return FileResponse(str(get_index_path()))


# -----------------------------------------------------------------------------
# Telemetry API (1-second polling)
# -----------------------------------------------------------------------------

@app.get("/telemetry")
@app.get("/api/telemetry")
async def get_telemetry(request: Request) -> JSONResponse:
    """Fetch realtime AI telemetry or return disconnected fallback (Phase D: connection pooled)."""
    b_url = get_backend_url(request).rstrip("/")
    try:
        client = get_backend_http_client()
        resp = await client.get(f"{b_url}/telemetry", timeout=1.5)
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
            "is_fallback": True,
            "frame_id": 0,
            "last_frame_time": 0.0,
            "error_message": f"Connecting to AI pipeline at {b_url}... Ensure 'python src/main.py' is active.",
            "people_count": 0,
            "car_count": 0,
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

def get_index_path() -> Path:
    if (REACT_DIST / "index.html").is_file():
        return REACT_DIST / "index.html"
    return STATIC_DIR / "index.html"


@app.get("/camera-management")
async def get_camera_management_page() -> FileResponse:
    return FileResponse(get_index_path())


@app.get("/cameras")
async def get_cameras(request: Request) -> Response:
    """Fetch list of available cameras and active camera."""
    if "text/html" in request.headers.get("accept", "") and request.url.path == "/cameras":
        return FileResponse(get_index_path())
    b_url = get_backend_url(request).rstrip("/")
    try:
        client = get_backend_http_client()
        resp = await client.get(f"{b_url}/cameras", timeout=2.5)
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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{b_url}/switch_camera?id={encoded_id}")
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"status": "error", "message": f"Camera switch failed: {exc}"},
            status_code=503,
        )


@app.get("/api/zone_mode")
@app.get("/zone_mode")
async def get_zone_mode(request: Request) -> JSONResponse:
    """Get current counting zone mode."""
    from src.runtime.shared_state import shared_state  # noqa: PLC0415
    return JSONResponse({
        "status": "ok",
        "zone_enabled": shared_state.zone_enabled,
        "mode": "Selected Zone" if shared_state.zone_enabled else "Full View",
    })


@app.post("/set_zone_mode")
@app.post("/api/set_zone_mode")
@app.get("/set_zone_mode")
@app.get("/api/set_zone_mode")
async def set_zone_mode(request: Request) -> JSONResponse:
    """Set counting zone mode (toggle between Full View and Selected Zone)."""
    from src.runtime.shared_state import shared_state  # noqa: PLC0415
    enabled = False
    if request.method == "POST":
        try:
            body = await request.json()
            enabled = bool(body.get("zone_enabled", False))
        except Exception:
            enabled = request.query_params.get("zone_enabled", "false").lower() in ("true", "1", "yes")
    else:
        enabled = request.query_params.get("zone_enabled", "false").lower() in ("true", "1", "yes")

    shared_state.set_zone_enabled(enabled)
    b_url = get_backend_url(request).rstrip("/")
    try:
        client = get_backend_http_client()
        await client.post(f"{b_url}/set_zone_mode", json={"zone_enabled": enabled}, timeout=1.0)
    except Exception:
        pass

    return JSONResponse({
        "status": "ok",
        "zone_enabled": shared_state.zone_enabled,
        "mode": "Selected Zone" if shared_state.zone_enabled else "Full View",
    })


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

    v_src_id = body.get("video_source_id") or body.get("id")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{b_url}/set_video_source",
                json={
                    "type": stype,
                    "source": source,
                    "loop": loop,
                    "name": name,
                    "video_source_id": v_src_id,
                },
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


@app.get("/video_sources")
@app.get("/api/video_sources")
async def get_video_sources() -> JSONResponse:
    """Retrieve persisted video sources from DB."""
    try:
        from src.db.database import Database
        from src.db.repositories import VideoSourceRepository
        db = Database()
        with db.transaction() as session:
            sources = VideoSourceRepository(session).list()
            return JSONResponse(
                content={
                    "status": "ok",
                    "sources": [
                        {
                            "id": str(s.id),
                            "original_filename": s.original_filename,
                            "storage_path": s.storage_path,
                            "status": s.status,
                            "file_size_bytes": s.file_size_bytes,
                            "duration_sec": s.duration_sec,
                            "fps": s.fps,
                            "width": s.width,
                            "height": s.height,
                            "created_at": s.created_at.isoformat() if s.created_at else None,
                        }
                        for s in sources
                    ],
                },
                status_code=200,
            )
    except Exception as exc:
        logger.debug("Failed listing video sources: %s", exc)
        return JSONResponse(content={"status": "error", "message": str(exc)}, status_code=500)


@app.delete("/video_sources/{source_id}")
@app.delete("/api/video_sources/{source_id}")
async def delete_video_source(source_id: str) -> JSONResponse:
    """Safely delete video source from DB and local storage."""
    from sqlalchemy.exc import IntegrityError
    try:
        from uuid import UUID
        from src.db.database import Database
        from src.db.repositories import VideoSourceRepository
        db = Database()
        storage_path = None
        with db.transaction() as session:
            repo = VideoSourceRepository(session)
            try:
                src_uuid = UUID(str(source_id))
            except ValueError:
                return JSONResponse(content={"status": "error", "message": "Invalid video source UUID"}, status_code=400)
            rec = repo.get(src_uuid)
            if rec is None:
                return JSONResponse(content={"status": "error", "message": "Video source not found"}, status_code=404)
            from src.db.models import Camera
            from sqlalchemy import select
            if session.scalar(select(Camera.id).where(Camera.video_source_id==src_uuid).limit(1)):
                return JSONResponse(content={"status":"error","message":"Video source is referenced by a camera"},status_code=409)
            storage_path = rec.storage_path
            repo.delete(src_uuid)

        # Unlink file if inside UPLOAD_VIDEO_DIR
        if storage_path:
            try:
                if validate_key(storage_path).startswith("data/uploads/videos/"):
                    get_storage().delete(storage_path)
            except Exception as e:
                logger.warning("[VIDEO_DELETE] Could not unlink file %s: %s", storage_path, e)

        return JSONResponse(content={"status": "ok", "message": "Video source deleted successfully"}, status_code=200)
    except IntegrityError:
        return JSONResponse(content={"status":"error","message":"Video source is referenced by a camera"},status_code=409)
    except Exception as exc:
        return JSONResponse(content={"status": "error", "message": str(exc)}, status_code=500)


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
        # Match switch_camera: DB/Storage-backed initialization can exceed 15s.
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{b_url}/select_source", json=body)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.TimeoutException:
        return JSONResponse(
            content={"status": "error", "code": "BACKEND_TIMEOUT",
                     "message": "AI backend timed out while selecting the camera source. Check source status before retrying."},
            status_code=504,
        )
    except httpx.RequestError:
        return JSONResponse(
            content={"status": "error", "code": "BACKEND_UNAVAILABLE",
                     "message": "Cannot reach the AI backend. Check that the camera pipeline is running in CPU/GPU mode and the backend URL is correct; API-only mode cannot activate cameras."},
            status_code=503,
        )
    except ValueError:
        return JSONResponse(
            content={"status": "error", "code": "BACKEND_INVALID_RESPONSE",
                     "message": "AI backend returned an invalid response. Check the backend URL and any proxy or tunnel."},
            status_code=502,
        )
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


# -----------------------------------------------------------------------------
# Camera Thumbnail API (Fast, Cached, HLS 1-Frame Fallback)
# -----------------------------------------------------------------------------

@app.get("/camera_thumbnail")
@app.get("/api/camera_thumbnail")
async def get_camera_thumbnail(
    request: Request,
    camera_id: str = Query(""),
    stream_url: str = Query(""),
    snapshot_url: str = Query(""),
    provider: str = Query(""),
) -> Response:
    """Fetch or generate camera thumbnail using ThumbnailService.

    Priority A: Provider snapshot if working.
    Priority B: Lightweight 1-frame direct HLS capture via FFmpeg.
    Fallback: Clean SVG placeholder.
    """
    from src.stream.thumbnail_service import thumbnail_service

    loop = asyncio.get_event_loop()
    data, content_type = await loop.run_in_executor(
        None,
        lambda: thumbnail_service.get_thumbnail(
            camera_id=camera_id,
            stream_url=stream_url,
            snapshot_url=snapshot_url,
            provider=provider,
        ),
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=90",
            "Access-Control-Allow-Origin": "*",
        },
    )


# -----------------------------------------------------------------------------
# Local Video File Upload API
# -----------------------------------------------------------------------------

UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
UPLOAD_VIDEO_DIR = UPLOAD_DIR / "videos"
UPLOAD_TARGET_DIR = UPLOAD_DIR / "targets"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_TARGET_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
MAX_VIDEO_SIZE = 500 * 1024 * 1024  # 500 MB


@app.post("/upload_video")
@app.post("/api/upload_video")
async def upload_video(file: UploadFile = File(...)) -> JSONResponse:
    """Handle multipart file upload for local video sources."""
    if not file or not file.filename:
        return JSONResponse(
            content={"status": "error", "message": "No file uploaded"},
            status_code=400,
        )

    original_filename = file.filename
    ext = Path(original_filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        return JSONResponse(
            content={
                "status": "error",
                "message": f"Invalid video format '{ext}'. Allowed formats: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
            },
            status_code=400,
        )

    sanitized_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", original_filename)
    unique_filename = f"{uuid.uuid4().hex[:8]}_{sanitized_name}"
    target_path = UPLOAD_VIDEO_DIR / unique_filename
    rel_storage_path = f"data/uploads/videos/{unique_filename}"

    total_size = 0
    try:
        with open(target_path, "wb") as out_file:
            while chunk := await file.read(1024 * 1024):  # 1MB chunk
                total_size += len(chunk)
                if total_size > MAX_VIDEO_SIZE:
                    out_file.close()
                    target_path.unlink(missing_ok=True)
                    return JSONResponse(
                        content={
                            "status": "error",
                            "message": f"File exceeds maximum allowed size ({MAX_VIDEO_SIZE // (1024 * 1024)}MB)",
                        },
                        status_code=413,
                    )
                out_file.write(chunk)
    except Exception as exc:
        target_path.unlink(missing_ok=True)
        return JSONResponse(
            content={"status": "error", "message": f"Upload failed: {exc}"},
            status_code=500,
        )

    if total_size == 0:
        target_path.unlink(missing_ok=True)
        return JSONResponse(
            content={"status": "error", "message": "Uploaded file is empty"},
            status_code=400,
        )

    width, height, fps, duration = None, None, None, None
    try:
        cap = cv2.VideoCapture(str(target_path))
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            if w > 0 and h > 0:
                width, height = w, h
            fps_val = float(cap.get(cv2.CAP_PROP_FPS))
            frame_cnt = float(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if fps_val > 0:
                fps = round(fps_val, 2)
                if frame_cnt > 0:
                    duration = round(frame_cnt / fps_val, 2)
            cap.release()
    except Exception as e:
        logger.debug("Failed extracting video metadata: %s", e)

    # Persist the object before committing its metadata; local file is staging only.
    try:
        with target_path.open("rb") as source:
            get_storage().save(rel_storage_path, source)
    except StorageUploadTooLarge:
        target_path.unlink(missing_ok=True)
        return JSONResponse(content={"status": "error", "code": "VIDEO_TOO_LARGE_FOR_STORAGE",
            "message": "Video vượt giới hạn dung lượng Storage. Hãy chọn video nhỏ hơn hoặc tăng giới hạn Storage; video chưa được lưu."}, status_code=413)
    except Exception:
        logger.error("[VIDEO_STORAGE_ERROR] Persistent storage write failed")
        return JSONResponse(content={"status": "error", "message": "Video storage unavailable"}, status_code=503)

    video_source_id = None
    try:
        from src.db.database import Database
        from src.db.repositories import VideoSourceRepository
        db = Database()
        with db.transaction() as session:
            repo = VideoSourceRepository(session)
            vs_rec = repo.create(
                original_filename=original_filename,
                storage_path=rel_storage_path,
                status="ready",
                file_size_bytes=total_size,
                duration_sec=duration,
                fps=fps,
                width=width,
                height=height,
                video_metadata={"unique_filename": unique_filename},
            )
            video_source_id = str(vs_rec.id)
            logger.info(
                "[VIDEO_UPLOAD_PERSISTED] id=%s original='%s' storage_path='%s'",
                video_source_id, original_filename, rel_storage_path,
            )
    except Exception as db_exc:
        logger.warning("[VIDEO_UPLOAD_DB_ERROR] Could not persist video metadata (%s)", type(db_exc).__name__)
        return JSONResponse(content={"status": "error", "message": "Video metadata could not be persisted"}, status_code=503)

    return JSONResponse(
        content={
            "status": "ok",
            "id": video_source_id,
            "video_source_id": video_source_id,
            "filename": original_filename,
            "storage_path": rel_storage_path,
            "server_path": str(target_path.resolve()),
            "size": total_size,
        },
        status_code=200,
    )


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
async def get_targets(
    request: Request,
    q: str = Query("", description="Search term"),
    search: str = Query("", description="Search term alias"),
    page: int | None = Query(None, description="Page number (1-based)"),
    page_size: int = Query(25, description="Items per page"),
    limit: int | None = Query(None, description="Limit alias"),
) -> JSONResponse:
    """Retrieve registered targets with direct SQL search, sort, and pagination."""
    from src.db.database import Database
    from src.db.models import Target
    from sqlalchemy import select, func, or_, cast, String

    search_term = (search or q).strip()
    effective_size = limit if limit is not None else page_size
    try:
        effective_size = max(1, min(200, int(effective_size)))
    except (ValueError, TypeError):
        effective_size = 25

    try:
        db = Database()
        with db.transaction() as session:
            query = select(Target).where(Target.active == True)
            if search_term:
                search_like = f"%{search_term}%"
                query = query.where(or_(
                    Target.name.ilike(search_like),
                    cast(Target.id, String).ilike(search_like),
                ))
            query = query.order_by(Target.created_at.desc())

            total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))

            if total == 0 and target_manager.list_targets() and os.environ.get("DATT_REQUIRE_PERSISTENCE") != "1":
                targets = [t.to_dict() for t in target_manager.list_targets()]
                for target in targets:
                    target["selected"] = target.pop("is_selected", True)
                return JSONResponse(content={"status": "ok", "targets": targets, "total": len(targets)}, status_code=200)

            if page is not None and page > 0:
                rows = session.scalars(query.offset((page - 1) * effective_size).limit(effective_size)).all()
            else:
                rows = session.scalars(query).all()

            targets_list = []
            for t in rows:
                meta = t.reference_metadata or {}
                targets_list.append({
                    "id": str(t.id),
                    "name": t.name,
                    "clothing_color": meta.get("clothing_color"),
                    "face_threshold": float(meta.get("threshold", 0.45)),
                    "has_face": True,
                    "source_image_path": t.image_path,
                    "selected": bool(meta.get("selected", True)),
                })

            resp = {"status": "ok", "targets": targets_list, "total": total}
            if page is not None:
                resp["page"] = page
                resp["page_size"] = effective_size
            return JSONResponse(content=resp, status_code=200)
    except Exception as exc:
        logger.warning("Direct DB target query failed (%s), falling back to in-memory...", exc)
        targets = [t.to_dict() for t in target_manager.list_targets()]
        for target in targets:
            target["selected"] = target.pop("is_selected", True)
        return JSONResponse(content={"status": "ok", "targets": targets, "total": len(targets)}, status_code=200)

    return JSONResponse(content={"status": "ok", "targets": targets, "total": total}, status_code=200)


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
    raw_img_bytes: bytes | None = None
    upload_filename = ""
    upload_mime = ""
    upload_bytes_len = 0

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
            upload_filename = getattr(file_obj, "filename", "upload.jpg")
            upload_mime = getattr(file_obj, "content_type", "application/octet-stream")
            raw_img_bytes = await file_obj.read()
            upload_bytes_len = len(raw_img_bytes)

            logger.info(
                "[TARGET_UPLOAD_A1] filename='%s' mime='%s' bytes=%d",
                upload_filename, upload_mime, upload_bytes_len,
            )

            # Validate extension
            ext = Path(upload_filename).suffix.lower()
            if ext and ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                logger.warning("[TARGET_UPLOAD_REJECTED] Unsupported image extension '%s'", ext)
                return JSONResponse(
                    content={
                        "status": "error",
                        "code": "IMAGE_DECODE_FAILED",
                        "message": f"Unsupported image extension '{ext}'. Please upload JPG, PNG, or WEBP.",
                    },
                    status_code=400,
                )

            if raw_img_bytes:
                img, decode_meta = decode_face_image_bytes(raw_img_bytes)
                logger.info(
                    "[TARGET_DECODE_A2] success=%s w=%s h=%s channels=%s dtype=%s orientation=%s debug_path=%s",
                    decode_meta.get("success"),
                    decode_meta.get("width"),
                    decode_meta.get("height"),
                    decode_meta.get("channels"),
                    decode_meta.get("dtype"),
                    decode_meta.get("orientation_tag"),
                    decode_meta.get("debug_path"),
                )
                if not decode_meta.get("success"):
                    return JSONResponse(
                        content={
                            "status": "error",
                            "code": "IMAGE_DECODE_FAILED",
                            "message": decode_meta.get("error") or "Failed to decode uploaded image",
                            "details": decode_meta,
                        },
                        status_code=400,
                    )

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
                raw_img_bytes = base64.b64decode(b64_img)
                upload_bytes_len = len(raw_img_bytes)
                img, decode_meta = decode_face_image_bytes(raw_img_bytes)
                logger.info(
                    "[TARGET_DECODE_A2_BASE64] success=%s w=%s h=%s dtype=%s",
                    decode_meta.get("success"), decode_meta.get("width"), decode_meta.get("height"), decode_meta.get("dtype"),
                )
                if not decode_meta.get("success"):
                    return JSONResponse(
                        content={
                            "status": "error",
                            "code": "IMAGE_DECODE_FAILED",
                            "message": decode_meta.get("error") or "Failed to decode base64 image",
                        },
                        status_code=400,
                    )
            except Exception as exc:
                return JSONResponse(
                    content={"status": "error", "code": "IMAGE_DECODE_FAILED", "message": f"Invalid base64 image: {exc}"},
                    status_code=400,
                )

    if not name:
        return JSONResponse(
            content={"status": "error", "code": "INVALID_NAME", "message": "Target name is required"},
            status_code=400,
        )

    target_disk_path = None
    rel_target_image_path = None
    if raw_img_bytes and len(raw_img_bytes) > 0:
        sanitized_img_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", upload_filename or "target.jpg")
        if not Path(sanitized_img_name).suffix:
            sanitized_img_name += ".jpg"
        unique_target_filename = f"{uuid.uuid4().hex[:8]}_{sanitized_img_name}"
        target_disk_path = UPLOAD_TARGET_DIR / unique_target_filename
        try:
            rel_target_image_path = f"data/uploads/targets/{unique_target_filename}"
            get_storage().save_bytes(rel_target_image_path, raw_img_bytes)
        except Exception as io_err:
            logger.warning("[TARGET_STORAGE] Failed saving original target image (%s)", type(io_err).__name__)
            return JSONResponse(content={"status": "error", "message": "Target storage unavailable"}, status_code=503)

    try:
        target = target_manager.register_target(
            name=name,
            face_image=img,
            clothing_color=color,
            face_threshold=threshold,
            source_image_path=rel_target_image_path,
        )

        if target.face_embedding is not None or os.environ.get("DATT_REQUIRE_PERSISTENCE") == "1":
            try:
                from src.db.database import Database
                from src.db.repositories import TargetRepository, TargetEmbeddingRepository
                from uuid import UUID as _UUID, uuid4 as _uuid4
                db = Database()
                with db.transaction() as session:
                    t_repo = TargetRepository(session)
                    try:
                        t_uuid = _UUID(target.id)
                    except Exception:
                        t_uuid = _uuid4()
                    db_t = t_repo.get(t_uuid)
                    if db_t is None:
                        db_t = t_repo.create(
                            id=t_uuid,
                            name=target.name,
                            target_type="face",
                            image_path=rel_target_image_path,
                            reference_metadata={
                                "clothing_color": target.clothing_color,
                                "threshold": target.face_threshold,
                            },
                            active=True,
                        )
                    if target.face_embedding is not None:
                        te_repo = TargetEmbeddingRepository(session)
                        te_repo.create(
                            target_id=db_t.id,
                            embedding=target.face_embedding,
                            model_name=target.embedding_model,
                            model_version="cvpr2022_ir50_ms1mv2",
                            source_image_path=rel_target_image_path,
                        )
                    target.db_id = str(db_t.id)
                    logger.info(
                        "[TARGET_PERSISTED_DB] target_id=%s db_id=%s source_image_path='%s'",
                        target.id, db_t.id, rel_target_image_path,
                    )
            except Exception as db_exc:
                logger.warning("[TARGET_DB_PERSIST_ERROR] Could not persist target (%s)", type(db_exc).__name__)
                target_manager.remove_target(target.id)
                return JSONResponse(content={"status": "error", "message": "Target metadata could not be persisted"}, status_code=503)

        # Notify backend AI server (:8000) if active so live AI pipeline has the target
        b_url = get_backend_url(request).rstrip("/")
        try:
            import base64
            sync_payload: dict[str, Any] = {
                "id": target.id,
                "name": target.name,
                "color": target.clothing_color,
                "threshold": target.face_threshold,
                "source_image_path": rel_target_image_path,
            }
            if raw_img_bytes:
                sync_payload["face_image_base64"] = base64.b64encode(raw_img_bytes).decode("ascii")

            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(f"{b_url}/api/register_target", json=sync_payload)
                logger.info("[TARGET_SYNC_BACKEND] Synced target '%s' (%s) with backend %s", target.name, target.id, b_url)
        except Exception as sync_exc:
            logger.debug("[TARGET_SYNC_BACKEND_NOTE] Backend sync note (backend may be offline or local): %s", sync_exc)

        return JSONResponse(
            content={
                "status": "ok",
                "target": target.to_dict(),
                "message": f"Target '{target.name}' registered successfully",
            },
            status_code=200,
        )
    except TargetRegistrationError as exc:
        if rel_target_image_path:
            get_storage().delete(rel_target_image_path)
        return JSONResponse(
            content={
                "status": "error",
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            status_code=400,
        )
    except ValueError as exc:
        return JSONResponse(
            content={"status": "error", "code": "VALIDATION_ERROR", "message": str(exc)},
            status_code=400,
        )
    except Exception as exc:
        logger.error("[TARGET_REGISTER_ERROR] Unexpected error: %s", exc, exc_info=True)
        return JSONResponse(
            content={"status": "error", "code": "INTERNAL_ERROR", "message": f"Registration failed: {exc}"},
            status_code=500,
        )


@app.delete("/targets/{target_id}")
@app.delete("/api/targets/{target_id}")
async def delete_target(target_id: str, request: Request) -> JSONResponse:
    """Remove a registered target by ID from memory, DB, and filesystem."""
    b_url = get_backend_url(request).rstrip("/")
    removed = target_manager.remove_target(target_id)

    # Delete from PostgreSQL and unlink image file
    try:
        from uuid import UUID
        from src.db.database import Database
        from src.db.repositories import TargetRepository
        db = Database()
        with db.transaction() as session:
            t_repo = TargetRepository(session)
            try:
                t_uuid = UUID(target_id)
                rec = t_repo.get(t_uuid)
                if rec:
                    img_path = rec.image_path
                    t_repo.delete(t_uuid)
                    removed = True
                    if img_path:
                        try:
                            if validate_key(img_path).startswith("data/uploads/targets/"):
                                get_storage().delete(img_path)
                        except Exception:
                            pass
            except ValueError:
                pass
    except Exception as db_err:
        logger.warning("[TARGET_DELETE_DB] Could not delete target from DB: %s", db_err)

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


@app.get("/targets/{target_id}/image")
@app.get("/api/targets/{target_id}/image")
async def get_target_image(target_id: str) -> Response:
    """Serve original target face image."""
    target = target_manager.get_target(target_id)
    img_path_str = target.source_image_path if target else None
    if not img_path_str:
        try:
            from uuid import UUID
            from src.db.database import Database
            from src.db.repositories import TargetRepository
            db = Database()
            with db.transaction() as session:
                rec = TargetRepository(session).get(UUID(target_id))
                if rec and rec.image_path:
                    img_path_str = rec.image_path
        except Exception:
            pass
    if img_path_str:
        try:
            if validate_key(img_path_str).startswith("data/uploads/targets/"):
                return FileResponse(str(get_storage().materialize(img_path_str)))
        except (FileNotFoundError, ValueError):
            pass
        except Exception:
            return Response(status_code=503)
    return Response(status_code=404)


@app.post("/targets/{target_id}/select")
@app.post("/api/targets/{target_id}/select")
async def toggle_target_select(target_id: str, request: Request) -> JSONResponse:
    """Select or deselect a target for active video search."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    is_sel = bool(body.get("selected", True))
    try:
        from src.recognition.target_selection import set_persisted_target_selection
        ok = set_persisted_target_selection(target_id, is_sel)
    except Exception as exc:
        logger.warning("[TARGET_SELECTION] persistence update failed: %s", type(exc).__name__)
        return JSONResponse(content={"status": "error", "message": "Target selection is unavailable"}, status_code=503)
    if not ok:
        return JSONResponse(content={"status": "error", "message": "Target not found"}, status_code=404)
    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(f"{b_url}/api/targets/{target_id}/select", json={"selected": is_sel})
        if response.status_code >= 400:
            detail = response.json().get("message", "Target selection rejected")
            return JSONResponse(content={"status": "error", "message": detail}, status_code=response.status_code)
    except httpx.HTTPError as exc:
        logger.warning("[TARGET_SELECTION] backend synchronization failed: %s", type(exc).__name__)
        return JSONResponse(content={"status": "error", "message": "Target runtime is unavailable"}, status_code=503)
    return JSONResponse(content={"status": "ok", "target_id": target_id, "selected": is_sel}, status_code=200)


@app.post("/targets/select")
@app.post("/api/targets/select")
async def bulk_select_targets(request: Request) -> JSONResponse:
    """Set selected targets list."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    target_ids = body.get("target_ids", [])
    target_manager.select_targets(target_ids)
    b_url = get_backend_url(request).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(f"{b_url}/api/targets/select", json={"target_ids": target_ids})
    except Exception:
        pass
    return JSONResponse(content={"status": "ok", "selected_ids": target_ids}, status_code=200)


# -----------------------------------------------------------------------------
# Vehicle Watchlist Management API
# -----------------------------------------------------------------------------

from src.watchlists.vehicle_api import router as vehicle_watchlist_router
app.include_router(vehicle_watchlist_router)


# -----------------------------------------------------------------------------
# Camera Management CRUD & Connection Testing API (Phase 1)
# -----------------------------------------------------------------------------

from src.cameras.api import router as cameras_router
app.include_router(cameras_router)
from src.event_center.api import router as event_center_router
app.include_router(event_center_router)
from src.notifications.alerts import router as alerts_router
app.include_router(alerts_router)
from src.agent.api import router as agent_router
app.include_router(agent_router)

# Cache mapping event_id -> snapshot_path for fast lookup
event_snapshot_cache: dict[str, str] = {}



# -----------------------------------------------------------------------------
# Event API (10-second polling)
# -----------------------------------------------------------------------------

@app.get("/events")
@app.get("/api/events")
async def get_events(request: Request) -> Response:
    """Fetch recent occupancy events (latest 5 only) or serve SPA page on browser navigation."""
    if "text/html" in request.headers.get("accept", "") and request.url.path == "/events":
        return FileResponse(get_index_path())
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
                        "event_type": ev.get("event_type", "PEOPLE_COUNT_CHANGED"),
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
                "event_type": ev.get("event_type", "PEOPLE_COUNT_CHANGED"),
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


@app.get("/events/vehicles")
@app.get("/api/events/vehicles")
async def get_vehicle_events(request: Request) -> JSONResponse:
    """Query vehicle events from DB."""
    try:
        from uuid import UUID
        from src.db.database import Database
        from src.db.repositories import VehicleEventRepository
        limit = min(max(int(request.query_params.get("limit", 50)), 1), 500)
        offset = max(int(request.query_params.get("offset", 0)), 0)
        v_class = request.query_params.get("vehicle_class")
        v_color = request.query_params.get("vehicle_color")
        v_src = request.query_params.get("video_source_id")
        v_src_uuid = UUID(v_src) if v_src else None
        t_id = request.query_params.get("track_id")
        track_id = int(t_id) if t_id is not None else None

        db = Database()
        with db.transaction() as session:
            repo = VehicleEventRepository(session)
            events = repo.query_events(
                vehicle_class=v_class,
                vehicle_color=v_color,
                video_source_id=v_src_uuid,
                track_id=track_id,
                limit=limit,
                offset=offset,
            )
            return JSONResponse(
                content={
                    "status": "ok",
                    "events": [
                        {
                            "id": str(e.id),
                            "video_source_id": str(e.video_source_id) if e.video_source_id else None,
                            "detection_event_id": str(e.detection_event_id) if e.detection_event_id else None,
                            "vehicle_class": e.vehicle_class,
                            "vehicle_color": e.vehicle_color,
                            "track_id": e.track_id,
                            "zone_id": e.zone_id,
                            "vehicle_image_path": e.vehicle_image_path,
                            "first_seen": e.first_seen.isoformat() if e.first_seen else None,
                            "last_seen": e.last_seen.isoformat() if e.last_seen else None,
                        }
                        for e in events
                    ],
                },
                status_code=200,
            )
    except Exception as exc:
        return JSONResponse(content={"status": "error", "message": str(exc)}, status_code=500)


@app.get("/events/plates")
@app.get("/api/events/plates")
async def get_plate_events(request: Request) -> JSONResponse:
    """Query plate events from DB."""
    try:
        from uuid import UUID
        from src.db.database import Database
        from src.db.repositories import PlateEventRepository
        limit = min(max(int(request.query_params.get("limit", 50)), 1), 500)
        offset = max(int(request.query_params.get("offset", 0)), 0)
        ve_id = request.query_params.get("vehicle_event_id")
        ve_uuid = UUID(ve_id) if ve_id else None
        p_text = request.query_params.get("plate_text")
        status = request.query_params.get("status")

        db = Database()
        with db.transaction() as session:
            repo = PlateEventRepository(session)
            events = repo.query_events(
                vehicle_event_id=ve_uuid,
                plate_text=p_text,
                status=status,
                limit=limit,
                offset=offset,
            )
            return JSONResponse(
                content={
                    "status": "ok",
                    "events": [
                        {
                            "id": str(e.id),
                            "vehicle_event_id": str(e.vehicle_event_id),
                            "plate_text": e.plate_text,
                            "confidence": e.confidence,
                            "plate_crop_path": e.plate_crop_path,
                            "status": e.status,
                            "created_at": e.created_at.isoformat() if e.created_at else None,
                        }
                        for e in events
                    ],
                },
                status_code=200,
            )
    except Exception as exc:
        return JSONResponse(content={"status": "error", "message": str(exc)}, status_code=500)


@app.get("/events/faces")
@app.get("/api/events/faces")
async def get_face_events(request: Request) -> JSONResponse:
    """Query face recognition events from DB."""
    try:
        from uuid import UUID
        from src.db.database import Database
        from src.db.repositories import FaceEventRepository
        limit = min(max(int(request.query_params.get("limit", 50)), 1), 500)
        offset = max(int(request.query_params.get("offset", 0)), 0)
        t_id = request.query_params.get("target_id")
        target_uuid = UUID(t_id) if t_id else None
        v_src = request.query_params.get("video_source_id")
        v_src_uuid = UUID(v_src) if v_src else None
        decision = request.query_params.get("decision")
        tr_id = request.query_params.get("track_id")
        track_id = int(tr_id) if tr_id is not None else None

        db = Database()
        with db.transaction() as session:
            repo = FaceEventRepository(session)
            events = repo.query_events(
                target_id=target_uuid,
                video_source_id=v_src_uuid,
                track_id=track_id,
                decision=decision,
                limit=limit,
                offset=offset,
            )
            return JSONResponse(
                content={
                    "status": "ok",
                    "events": [
                        {
                            "id": str(e.id),
                            "target_id": str(e.target_id) if e.target_id else None,
                            "video_source_id": str(e.video_source_id) if e.video_source_id else None,
                            "camera_id": e.camera_id,
                            "track_id": e.track_id,
                            "frame_id": e.frame_id,
                            "similarity": e.similarity,
                            "decision": e.decision,
                            "face_crop_path": e.face_crop_path,
                            "created_at": e.created_at.isoformat() if e.created_at else None,
                        }
                        for e in events
                    ],
                },
                status_code=200,
            )
    except Exception as exc:
        return JSONResponse(content={"status": "error", "message": str(exc)}, status_code=500)


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

    # Resolve durable UUIDs from PostgreSQL after a process/cache restart.
    if not rel_path and event_id:
        try:
            from uuid import UUID
            from src.db.database import Database
            from src.db.models import BusinessEvent, DetectionEvent, VehicleEvent, PlateEvent, FaceEvent
            event_uuid = UUID(event_id)
            db = Database()
            try:
                with db.transaction() as session:
                    for model, field in ((DetectionEvent, 'snapshot_path'),
                                         (VehicleEvent, 'vehicle_image_path'),
                                         (PlateEvent, 'plate_crop_path'), (FaceEvent, 'face_crop_path')):
                        record = session.get(model, event_uuid)
                        if record and getattr(record, field, None):
                            rel_path = getattr(record, field)
                            break
                    if not rel_path:
                        record = session.get(BusinessEvent, event_uuid)
                        if record and isinstance(record.event_metadata, dict):
                            rel_path = record.event_metadata.get('snapshot_path', '')
            finally:
                db.dispose()
        except ValueError:
            pass  # Numeric legacy IDs retain the existing SQLite lookup.
        except Exception:
            raise HTTPException(status_code=503, detail='Event metadata unavailable') from None

    # Resolve legacy IDs from memory cache or SQLite.
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
    if not rel_path:
        raise HTTPException(status_code=404, detail="Event snapshot not found")

    # Security check: resolve strictly within data/events/
    target_file = None
    try:
        valid_event_key = rel_path and validate_key(rel_path).startswith("data/events/")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid event image key") from None
    if valid_event_key:
        try:
            target_file = get_storage().materialize(rel_path)
        except FileNotFoundError:
            pass
        except Exception:
            raise HTTPException(status_code=503, detail="Event image storage unavailable") from None

    if target_file is not None:
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
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Snapshot backend timed out") from None
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Snapshot backend unavailable") from None


# -----------------------------------------------------------------------------
# Video Stream API (Native MJPEG Relay)
# -----------------------------------------------------------------------------

@app.get("/frame_packet")
@app.get("/api/frame_packet")
async def frame_packet(request: Request) -> Response:
    """Relay one indivisible image/metrics response without resampling telemetry."""
    try:
        client = get_backend_http_client()
        response = await client.get(
            f"{get_backend_url(request).rstrip('/')}/frame_packet", timeout=3.0
        )
        headers = {"Cache-Control": "no-store"}
        if "X-Frame-Telemetry" in response.headers:
            headers["X-Frame-Telemetry"] = response.headers["X-Frame-Telemetry"]
        return Response(content=response.content, status_code=response.status_code,
                        media_type="image/jpeg", headers=headers)
    except httpx.HTTPError:
        return Response(status_code=503, headers={"Cache-Control": "no-store"})


def _encode_frame_stream_packet(metrics: dict, jpeg: bytes = b"") -> bytes:
    metadata = json.dumps(metrics, separators=(",", ":")).encode("utf-8")
    if len(metadata) > 65536 or len(jpeg) > 4 * 1024 * 1024:
        raise ValueError("Frame packet exceeds preview limits")
    return struct.pack("!II", len(metadata), len(jpeg)) + metadata + jpeg


@app.get("/frame_stream")
@app.get("/api/frame_stream")
async def frame_stream(request: Request) -> StreamingResponse:
    """Keep image/metrics together without a browser-to-Colab RTT per frame."""
    target = f"{get_backend_url(request).rstrip('/')}/frame_packet"
    client = get_backend_http_client()

    async def frames():
        last_key = None
        heartbeat = 0.0
        while not await request.is_disconnected():
            started = time.monotonic()
            try:
                response = await client.get(target, timeout=3.0)
                if response.status_code == 200:
                    metrics = json.loads(response.headers.get("X-Frame-Telemetry", "null"))
                    if not isinstance(metrics, dict):
                        raise ValueError("Missing frame metadata")
                    key = (metrics.get("source_generation"), metrics.get("frame_id"))
                    if key != last_key and float(metrics.get("frame_age_ms", 0)) <= 3000:
                        packet = _encode_frame_stream_packet(metrics, response.content)
                        last_key = key
                        yield packet
                        heartbeat = time.monotonic()
            except (httpx.HTTPError, ValueError, TypeError):
                # The client watchdog exposes stale images. Keep retrying the
                # backend without accumulating queued frames or stale payloads.
                await asyncio.sleep(.25)
            if time.monotonic() - heartbeat >= 1.0:
                yield _encode_frame_stream_packet({"idle": True})
                heartbeat = time.monotonic()
            await asyncio.sleep(max(0.005, 1 / 30 - (time.monotonic() - started)))

    return StreamingResponse(frames(), media_type="application/octet-stream",
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no",
                 "X-DATT-Frame-Protocol": "1"})


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
        client = get_backend_http_client()
        resp = await client.get(f"{b_url}/status", timeout=1.5)
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
