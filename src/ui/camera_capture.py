"""Manual camera snapshots, independent of identity matching and notifications."""
from uuid import uuid4

import cv2
from fastapi import APIRouter, HTTPException

from src.runtime.shared_state import shared_state
from src.storage import get_storage

router = APIRouter()


@router.post("/api/camera_capture")
def capture_camera():
    captured = shared_state.capture_camera_frame()
    if captured is None:
        raise HTTPException(409, "Chưa có khung hình camera mới để chụp. Hãy bật video trước.")
    frame, info = captured
    event_id = uuid4()
    key = f"data/events/camera_{event_id}.jpg"
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(500, "Không mã hóa được ảnh camera.")
    try:
        get_storage().save_bytes(key, encoded.tobytes())
    except Exception:
        raise HTTPException(503, "Không lưu được ảnh vào Storage.") from None
    # Manual photos remain available without manufacturing an Event Center event.
    return {"status": "ok", "id": str(event_id), "snapshot_path": key,
            "image_url": f"/api/event_snapshot?path={key}"}
