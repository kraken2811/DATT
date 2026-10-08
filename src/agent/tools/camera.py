"""Camera inspection and status tools for DATT AI Agent."""

from typing import Any
from langchain_core.tools import tool

from src.cameras.service import database, find, serialize
from src.config.camera_config import load_cameras
from src.db.models import Camera, utc_now


@tool
def get_camera(camera_id: str | None = None, camera: str | None = None) -> dict[str, Any]:
    """Retrieve detailed configuration and metadata for a specific camera.

    Args:
        camera_id: Camera UUID or registry key (e.g. 'camera_01', 'CAM01', or UUID).
        camera: Optional alias for camera_id.

    Returns:
        Structured camera record containing name, source type, URL, zone/location, and enabled state.
    """
    clean_id = (camera_id or camera or "").strip()
    if not clean_id:
        return {"status": "error", "message": "camera_id is required"}

    # 1. Try finding in database
    try:
        with database() as db, db.transaction() as session:
            cam = find(session, clean_id)
            if cam is not None:
                return {"status": "success", "camera": serialize(cam)}
    except Exception as exc:
        pass

    # 2. Fallback to YAML configuration
    try:
        cameras = load_cameras()
        if clean_id in cameras:
            c = cameras[clean_id]
            return {"status": "success", "camera": c.to_dict()}
        # Case-insensitive match on name or ID
        for k, c in cameras.items():
            if k.lower() == clean_id.lower() or c.name.lower() == clean_id.lower():
                return {"status": "success", "camera": c.to_dict()}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to retrieve camera: {exc}"}

    return {
        "status": "not_found",
        "message": f"Camera '{clean_id}' was not found in the camera registry.",
    }


def get_troubleshooting_guidance(source_type: str | None, source: str | None = None) -> dict[str, Any]:
    """Provide source-type specific troubleshooting procedures based on camera ingestion type."""
    st = (source_type or "").lower().strip()
    if st in ("file", "local"):
        return {
            "source_category": "local_file",
            "is_network_stream": False,
            "steps": [
                "1. Kiểm tra file video tồn tại trên đĩa cục bộ / đường dẫn lưu trữ DATT.",
                "2. Kiểm tra định dạng video tương thích (MP4, MKV; codec H.264) và quyền đọc file.",
                "3. Kiểm tra tiến trình ingestion worker của camera có đang chạy không (khởi động pipeline).",
            ],
            "caution": "Đây là file video cục bộ. KHÔNG kiểm tra kết nối mạng, router, IP camera hay cổng RTSP 554.",
        }
    elif st in ("rtsp",):
        return {
            "source_category": "rtsp_network_stream",
            "is_network_stream": True,
            "steps": [
                "1. Kiểm tra nguồn điện và kết nối cáp mạng của thiết bị camera IP.",
                "2. Kiểm tra ping địa chỉ IP của camera để xác nhận thiết bị còn hoạt động trong mạng nội bộ.",
                "3. Kiểm tra cổng RTSP 554 không bị chặn bởi firewall mạng.",
                "4. Xác minh thông tin tài khoản (username/password) trong RTSP URL và định dạng luồng H.264.",
                "5. Kiểm tra tiến trình ingestion worker DATT đang gán với camera này.",
            ],
            "caution": "Tình trạng 'offline' trong CSDL chỉ phản ánh heartbeat lease của worker; cần xác minh kết nối mạng trực tiếp tới camera trước khi kết luận đứt cáp.",
        }
    elif st in ("direct_hls", "hls", "http", "https", "cctv"):
        return {
            "source_category": "http_hls_stream",
            "is_network_stream": True,
            "steps": [
                "1. Kiểm tra URL playlist (.m3u8) có tải được qua trình duyệt hoặc curl không.",
                "2. Kiểm tra kết nối Internet / mạng WAN tới máy chủ stream.",
                "3. Kiểm tra chứng chỉ SSL/HTTPS và cấu hình proxy/CORS nếu có.",
                "4. Kiểm tra tiến trình ingestion worker DATT.",
            ],
            "caution": "Kiểm tra endpoint HTTP/HLS trước khi báo lỗi camera.",
        }
    elif st in ("youtube",):
        return {
            "source_category": "youtube_live",
            "is_network_stream": True,
            "steps": [
                "1. Kiểm tra video hoặc luồng livestream trên YouTube còn đang hoạt động không.",
                "2. Kiểm tra kết nối Internet trên máy chủ DATT.",
                "3. Cập nhật gói yt-dlp lên phiên bản mới nhất để tránh thay đổi từ phía YouTube.",
                "4. Kiểm tra tiến trình ingestion worker DATT.",
            ],
            "caution": "Các luồng YouTube livestream có thể bị ngắt từ phía kênh phát sóng.",
        }
    else:
        return {
            "source_category": "general",
            "is_network_stream": False,
            "steps": [
                "1. Kiểm tra cấu hình camera trong CSDL hoặc cameras.yaml.",
                "2. Kiểm tra tiến trình ingestion worker DATT.",
            ],
            "caution": "Trạng thái offline trong DB phản ánh worker chưa giữ active lease.",
        }


def mask_source_url(source: str | None) -> str | None:
    """Mask credentials in RTSP/HTTP URLs for safe display."""
    if not source:
        return None
    import re
    return re.sub(r":([^:@]+)@", r":***@", source)


@tool
def get_camera_status(camera_id: str | None = None, camera: str | None = None) -> dict[str, Any]:
    """Retrieve the real-time operational status (online/offline/disabled) of a camera.

    Grounding distinctions:
    - Status in database reflects the ingestion worker's heartbeat lease (`active_until`),
      NOT a live network probe of the physical stream URL.
    - Troubleshooting advice is strictly adapted to source_type (local file, RTSP, HLS, YouTube).

    Args:
        camera_id: Camera identifier or registry key (e.g. 'camera_01').
        camera: Optional alias for camera_id.

    Returns:
        Current status ('online', 'offline', 'disabled'), status basis, reachability flag,
        source type, and tailored troubleshooting guidance.
    """
    clean_id = (camera_id or camera or "").strip()
    if not clean_id:
        return {"status": "error", "message": "camera_id is required"}

    # Check database status
    try:
        with database() as db, db.transaction() as session:
            cam = find(session, clean_id)
            if cam is not None:
                active = bool(cam.active_until and cam.active_until > utc_now())
                status = "disabled" if not cam.enabled else ("online" if active else "offline")
                guidance = get_troubleshooting_guidance(cam.source_type, cam.source)
                return {
                    "status": "success",
                    "camera_id": str(cam.id),
                    "name": cam.name,
                    "operational_status": status,
                    "is_active": active,
                    "enabled": cam.enabled,
                    "last_active": cam.last_active.isoformat() if cam.last_active else None,
                    "source_type": cam.source_type,
                    "source_masked": mask_source_url(cam.source),
                    "location": cam.location,
                    "status_basis": "database_heartbeat_lease",
                    "status_basis_description": (
                        "Trạng thái dựa trên lease gia hạn 'active_until' của ingestion worker trong CSDL. "
                        "Trạng thái 'offline' cho thấy worker chưa/không còn giữ lease hợp lệ; "
                        "hệ thống chưa thực hiện probe kết nối mạng trực tiếp tới URL stream."
                    ),
                    "stream_reachability_verified": False,
                    "troubleshooting_guidance": guidance,
                }
    except Exception as exc:
        pass

    # Check YAML / local cameras fallback
    try:
        cameras = load_cameras()
        for k, c in cameras.items():
            if k.lower() == clean_id.lower() or c.name.lower() == clean_id.lower():
                guidance = get_troubleshooting_guidance(c.type, c.url)
                return {
                    "status": "success",
                    "camera_id": c.id,
                    "name": c.name,
                    "operational_status": c.status,
                    "is_active": c.status == "online",
                    "enabled": c.enabled,
                    "last_active": None,
                    "source_type": c.type,
                    "source_masked": mask_source_url(c.url),
                    "location": c.location,
                    "status_basis": "static_yaml_registry",
                    "status_basis_description": "Trạng thái lấy từ file cấu hình static cameras.yaml.",
                    "stream_reachability_verified": False,
                    "troubleshooting_guidance": guidance,
                }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to query camera status: {exc}"}

    return {
        "status": "not_found",
        "message": f"Camera '{clean_id}' was not found.",
    }
