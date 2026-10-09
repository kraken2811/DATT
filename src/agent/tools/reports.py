"""Automated operational report generation tools for DATT AI Agent."""

from datetime import datetime, timezone
from typing import Any
from langchain_core.tools import tool
from sqlalchemy import func, select, or_
from uuid import UUID
from src.notifications.alerts import camera_aliases

from src.agent.config import agent_config
from src.agent.tools.analytics import parse_time_bounds
from src.db.models import (
    Camera,
    FaceEvent,
    Notification,
    PlateEvent,
    VehiclePassage,
    VehicleWatchlistResult,
)


def utc_timestamp(value):
    # SQLite fixtures and older records may return naive UTC; PostgreSQL returns aware values.
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


@tool
def generate_operational_report(
    period: str = "today",
    camera_id: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    """Generate a comprehensive, executive operational report of the DATT vision system.

    Aggregates:
    1. Monitored camera fleet status (enabled, active, offline).
    2. Vehicle traffic passages, unique plates, and vehicle classification breakdown.
    3. Watchlist security events (face and vehicle match counts).
    4. Alert Center event volume and status (pending, sent, failed, suppressed).
    5. Email notification delivery health and retry statistics.
    6. Peak traffic hours and busiest camera locations.
    7. Data-driven operational recommendations based strictly on recorded metrics.

    Args:
        period: Time period preset: 'today', '24h', 'yesterday', '7_days', or 'custom'.
        camera_id: Optional camera identifier to scope the report to a single camera.
        from_time: Optional custom start time (ISO timestamp).
        to_time: Optional custom end time (ISO timestamp).
        start_time: Optional alias for from_time.
        end_time: Optional alias for to_time.

    Returns:
        Structured operational metrics and a formatted Vietnamese Markdown report.
    """
    eff_start = from_time or start_time
    eff_end = to_time or end_time
    db = None
    try:
        if period not in ('today', '24h', 'yesterday', '7_days', 'custom') or (period == 'custom' and not eff_start):
            raise ValueError('INVALID_REPORT_PERIOD')
        for value in (eff_start, eff_end):
            if value:
                datetime.fromisoformat(value.replace('Z', '+00:00'))
        # Explicit bounds take precedence over a preset, rather than silently ignoring a requested date.
        start_utc, end_utc, time_label = parse_time_bounds(None if eff_start else period, eff_start, eff_end)
        if start_utc > end_utc:
            raise ValueError('INVALID_TIME_RANGE')
        db = agent_config.get_database()
        with db.transaction() as session:
            # 1. Camera Fleet Status
            cam_query = select(Camera)
            camera_keys = None
            if camera_id and camera_id.strip():
                camera_keys = set(camera_aliases(camera_id.strip()))
                try:
                    ids = [UUID(camera_id.strip())]
                except ValueError:
                    ids = []
                cam_query = cam_query.where(or_(Camera.registry_key.in_(camera_keys), Camera.id.in_(ids)))
            all_cams = session.scalars(cam_query).all()
            if camera_keys is not None:
                for cam in all_cams:
                    camera_keys.update(k for k in (cam.registry_key, str(cam.id), cam.id.hex) if k)
            total_cameras = len(all_cams)
            enabled_cameras = sum(1 for c in all_cams if c.enabled)
            now_utc = datetime.now(timezone.utc)
            # A camera is considered online if last_active is within 5 minutes or active_until > now
            online_cameras = sum(
                1
                for c in all_cams
                if c.enabled and (
                    (c.last_active and 0 <= (now_utc - utc_timestamp(c.last_active)).total_seconds() < 300)
                    or (c.active_until and utc_timestamp(c.active_until) > now_utc)
                )
            )
            offline_cameras = max(0, total_cameras - online_cameras)

            # 2. Vehicle Traffic Aggregations
            v_base = select(func.count(VehiclePassage.id)).where(
                VehiclePassage.first_seen_at >= start_utc,
                VehiclePassage.first_seen_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                v_base = v_base.where(VehiclePassage.camera_id.in_(camera_keys))
            total_passages = session.scalar(v_base) or 0

            # Unique plates
            up_q = select(func.count(func.distinct(VehiclePassage.plate_text))).where(
                VehiclePassage.first_seen_at >= start_utc,
                VehiclePassage.first_seen_at <= end_utc,
                VehiclePassage.plate_text.is_not(None),
                VehiclePassage.plate_text != "",
            )
            if camera_id and camera_id.strip():
                up_q = up_q.where(VehiclePassage.camera_id.in_(camera_keys))
            unique_plates = session.scalar(up_q) or 0

            # Vehicle classification breakdown
            vc_q = (
                select(VehiclePassage.vehicle_type, func.count(VehiclePassage.id))
                .where(
                    VehiclePassage.first_seen_at >= start_utc,
                    VehiclePassage.first_seen_at <= end_utc,
                )
            )
            if camera_id and camera_id.strip():
                vc_q = vc_q.where(VehiclePassage.camera_id.in_(camera_keys))
            type_counts = {str(r[0] or "unknown"): int(r[1]) for r in session.execute(vc_q.group_by(VehiclePassage.vehicle_type)).all()}

            # 3. Security & Watchlist Matches
            f_match_q = select(func.count(FaceEvent.id)).where(
                FaceEvent.decision.in_(("FACE_MATCH", "MATCH")),
                FaceEvent.created_at >= start_utc,
                FaceEvent.created_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                f_match_q = f_match_q.where(FaceEvent.camera_id.in_(camera_keys))
            face_matches = session.scalar(f_match_q) or 0

            p_match_q = select(func.count(VehicleWatchlistResult.id)).where(
                VehicleWatchlistResult.decision == "MATCH",
                VehicleWatchlistResult.created_at >= start_utc,
                VehicleWatchlistResult.created_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                p_match_q = p_match_q.where(VehicleWatchlistResult.camera_id.in_(camera_keys))
            vehicle_matches = session.scalar(p_match_q) or 0

            # 4. Alert Center & Notification Health
            n_status_q = select(Notification.status, func.count(Notification.id)).where(
                Notification.created_at >= start_utc,
                Notification.created_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                n_status_q = n_status_q.where(Notification.camera_id.in_(camera_keys))
            alert_counts = {str(r[0]): int(r[1]) for r in session.execute(n_status_q.group_by(Notification.status)).all()}
            total_alerts = sum(alert_counts.values())

            # 5. Busiest Camera
            cam_traffic_q = (
                select(VehiclePassage.camera_id, func.count(VehiclePassage.id))
                .where(
                    VehiclePassage.first_seen_at >= start_utc,
                    VehiclePassage.first_seen_at <= end_utc,
                )
                .group_by(VehiclePassage.camera_id)
                .order_by(func.count(VehiclePassage.id).desc())
                .limit(5)
            )
            if camera_keys is not None:
                cam_traffic_q = cam_traffic_q.where(VehiclePassage.camera_id.in_(camera_keys))
            busiest_cams = [{"camera_id": str(r[0]), "passages": int(r[1])} for r in session.execute(cam_traffic_q).all()]
            top_cam_label = busiest_cams[0]["camera_id"] if busiest_cams else "Chưa có dữ liệu"

            # 6. Generate Actionable Recommendations based strictly on data
            recommendations = []
            if total_cameras == 0:
                recommendations.append('Chưa có camera cấu hình trong phạm vi báo cáo; chưa thể đánh giá trạng thái giám sát.')
            if not (total_passages or face_matches or vehicle_matches or total_alerts):
                recommendations.append('Chưa ghi nhận hoạt động trong khoảng yêu cầu; cần phân biệt không có hoạt động với thiếu dữ liệu ingest.')
            if offline_cameras > 0:
                recommendations.append(f"Kiểm tra kết nối và nguồn điện cho {offline_cameras} camera đang ở trạng thái offline.")
            if alert_counts.get("failed", 0) > 0:
                recommendations.append(f"Khắc phục sự cố chuyển phát email cho {alert_counts['failed']} thông báo bị lỗi (kiểm tra cấu hình SMTP outbox).")
            if alert_counts.get("pending", 0) > 0:
                recommendations.append(f"Hệ thống có {alert_counts['pending']} cảnh báo đang chờ xử lý hoặc đang chờ gửi.")
            if face_matches > 0 or vehicle_matches > 0:
                recommendations.append(f"Rà soát {face_matches + vehicle_matches} sự kiện khớp Watchlist để xác nhận nghiệp vụ an ninh.")
            if not recommendations:
                recommendations.append('Không ghi nhận cảnh báo cần xử lý trong phạm vi này; số liệu lịch sử không đủ để kết luận hệ thống khỏe.')
            recommendations.append('Trạng thái sức khỏe hệ thống chưa được xác minh; cần kiểm tra worker, kết nối và luồng video thực tế.')
            availability = online_cameras / total_cameras * 100 if total_cameras else None
            availability_text = f'{availability:.1f}% (trên tổng số camera quản lý)' if availability is not None else 'Chưa xác định (không có camera)'

            # 7. Build rich Markdown Report
            type_lines = "\n".join(f"- **{k.title()}**: {v:,} lượt" for k, v in sorted(type_counts.items(), key=lambda x: -x[1])) if type_counts else "- Chưa ghi nhận phân loại"
            cam_lines = "\n".join(f"- **{c['camera_id']}**: {c['passages']:,} lượt" for c in busiest_cams) if busiest_cams else "- Chưa có dữ liệu"
            rec_lines = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendations))

            markdown_report = f"""# BÁO CÁO VẬN HÀNH HỆ THỐNG DATT (AI OPERATIONS REPORT)

**Thời gian báo cáo:** {time_label}  
**Múi giờ:** ICT (UTC+7)  
**Phạm vi:** {"Camera " + camera_id if camera_id else "Toàn bộ hệ thống"}  

---

### 1. Trạng Thái Hạ Tầng Camera
- **Tổng số camera quản lý:** {total_cameras}
- **Camera trực tuyến (Online):** {online_cameras}
- **Camera mất tín hiệu (Offline/Chưa kết nối):** {offline_cameras}
- **Tỷ lệ camera có heartbeat/lease hoạt động:** {availability_text}

### 2. Lưu Lượng & Phân Loại Phương Tiện
- **Tổng lượt xe qua khung hình (VehiclePassage):** {total_passages:,} lượt
- **Số biển số nhận diện duy nhất (Unique Plates):** {unique_plates:,} xe
- **Phân loại phương tiện:**
{type_lines}

### 3. An Ninh & Giám Sát Danh Sách Theo Dõi (Watchlist)
- **Cảnh báo trùng khớp biển số (Vehicle Watchlist):** {vehicle_matches} lượt
- **Cảnh báo trùng khớp khuôn mặt (Face Watchlist):** {face_matches} lượt
- **Tổng số sự kiện an ninh trọng yếu:** {vehicle_matches + face_matches} sự kiện

### 4. Tình Trạng Cảnh Báo & Chuyển Phát Email (Alerts & Notifications)
- **Tổng số cảnh báo phát sinh:** {total_alerts}
- **Email gửi thành công (Sent):** {alert_counts.get("sent", 0)}
- **Email gửi thất bại (Failed):** {alert_counts.get("failed", 0)}
- **Cảnh báo đang chờ (Pending):** {alert_counts.get("pending", 0)}
- **Cảnh báo bị nén/tránh lặp (Suppressed):** {alert_counts.get("suppressed", 0)}

### 5. Camera Hoạt Động Cao Nhất
- **Camera đông xe nhất:** **{top_cam_label}**
- **Top camera theo lưu lượng:**
{cam_lines}

---

### 6. Khuyến Nghị Vận Hành
{rec_lines}

*(Ghi chú: Số liệu lượt xe là tổng số phiên xe di chuyển qua camera; không đo lường số xe đang đỗ tĩnh tại một thời điểm).*
"""

            return {
                "status": "success",
                "period": period,
                "time_label": time_label,
                "timezone": "ICT (UTC+7)",
                "scope": camera_id or "all_cameras",
                "data_availability": {"camera_records": bool(total_cameras),
                    "recorded_activity": bool(total_passages or face_matches or vehicle_matches or total_alerts),
                    "health_verified": False},
                "metrics": {
                    "cameras": {
                        "total": total_cameras,
                        "online": online_cameras,
                        "offline": offline_cameras,
                        "enabled": enabled_cameras,
                        "availability_percent": availability,
                    },
                    "traffic": {
                        "total_passages": total_passages,
                        "unique_plates": unique_plates,
                        "type_breakdown": type_counts,
                        "busiest_cameras": busiest_cams,
                    },
                    "security": {
                        "face_matches": face_matches,
                        "vehicle_matches": vehicle_matches,
                        "total_matches": face_matches + vehicle_matches,
                    },
                    "alerts_and_notifications": {
                        "total_alerts": total_alerts,
                        "sent": alert_counts.get("sent", 0),
                        "failed": alert_counts.get("failed", 0),
                        "pending": alert_counts.get("pending", 0),
                        "suppressed": alert_counts.get("suppressed", 0),
                    },
                    "recommendations": recommendations,
                },
                "report_markdown": markdown_report,
            }
    except Exception as exc:
        return {"status": "error", "message": "Chưa thể tạo báo cáo hoặc bộ lọc không hợp lệ; không đủ dữ liệu đã xác minh."}
    finally:
        if db is not None:
            db.dispose()
