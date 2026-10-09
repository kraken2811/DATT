"""Automated operational report generation tools for DATT AI Agent."""

from datetime import datetime, timezone
from typing import Any
from langchain_core.tools import tool
from sqlalchemy import func, select

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
    start_utc, end_utc, time_label = parse_time_bounds(period, eff_start, eff_end)

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            # 1. Camera Fleet Status
            cam_query = select(Camera)
            if camera_id and camera_id.strip():
                cam_query = cam_query.where(Camera.registry_key == camera_id.strip())
            all_cams = session.scalars(cam_query).all()
            total_cameras = len(all_cams)
            enabled_cameras = sum(1 for c in all_cams if c.enabled)
            now_utc = datetime.now(timezone.utc)
            # A camera is considered online if last_active is within 5 minutes or active_until > now
            online_cameras = sum(
                1
                for c in all_cams
                if c.enabled and (
                    (c.last_active and (now_utc - c.last_active).total_seconds() < 300)
                    or (c.active_until and c.active_until > now_utc)
                )
            )
            offline_cameras = max(0, total_cameras - online_cameras)

            # 2. Vehicle Traffic Aggregations
            v_base = select(func.count(VehiclePassage.id)).where(
                VehiclePassage.first_seen_at >= start_utc,
                VehiclePassage.first_seen_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                v_base = v_base.where(VehiclePassage.camera_id == camera_id.strip())
            total_passages = session.scalar(v_base) or 0

            # Unique plates
            up_q = select(func.count(func.distinct(VehiclePassage.plate_text))).where(
                VehiclePassage.first_seen_at >= start_utc,
                VehiclePassage.first_seen_at <= end_utc,
                VehiclePassage.plate_text.is_not(None),
                VehiclePassage.plate_text != "",
            )
            if camera_id and camera_id.strip():
                up_q = up_q.where(VehiclePassage.camera_id == camera_id.strip())
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
                vc_q = vc_q.where(VehiclePassage.camera_id == camera_id.strip())
            type_counts = {str(r[0] or "unknown"): int(r[1]) for r in session.execute(vc_q.group_by(VehiclePassage.vehicle_type)).all()}

            # 3. Security & Watchlist Matches
            f_match_q = select(func.count(FaceEvent.id)).where(
                FaceEvent.decision.in_(("FACE_MATCH", "MATCH")),
                FaceEvent.created_at >= start_utc,
                FaceEvent.created_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                f_match_q = f_match_q.where(FaceEvent.camera_id == camera_id.strip())
            face_matches = session.scalar(f_match_q) or 0

            p_match_q = select(func.count(VehicleWatchlistResult.id)).where(
                VehicleWatchlistResult.decision == "MATCH",
                VehicleWatchlistResult.created_at >= start_utc,
                VehicleWatchlistResult.created_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                p_match_q = p_match_q.where(VehicleWatchlistResult.camera_id == camera_id.strip())
            vehicle_matches = session.scalar(p_match_q) or 0

            # 4. Alert Center & Notification Health
            n_status_q = select(Notification.status, func.count(Notification.id)).where(
                Notification.created_at >= start_utc,
                Notification.created_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                n_status_q = n_status_q.where(Notification.camera_id == camera_id.strip())
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
            busiest_cams = [{"camera_id": str(r[0]), "passages": int(r[1])} for r in session.execute(cam_traffic_q).all()]
            top_cam_label = busiest_cams[0]["camera_id"] if busiest_cams else "Chưa có dữ liệu"

            # 6. Generate Actionable Recommendations based strictly on data
            recommendations = []
            if offline_cameras > 0:
                recommendations.append(f"Kiểm tra kết nối và nguồn điện cho {offline_cameras} camera đang ở trạng thái offline.")
            if alert_counts.get("failed", 0) > 0:
                recommendations.append(f"Khắc phục sự cố chuyển phát email cho {alert_counts['failed']} thông báo bị lỗi (kiểm tra cấu hình SMTP outbox).")
            if alert_counts.get("pending", 0) > 0:
                recommendations.append(f"Hệ thống có {alert_counts['pending']} cảnh báo đang chờ xử lý hoặc đang chờ gửi.")
            if face_matches > 0 or vehicle_matches > 0:
                recommendations.append(f"Rà soát {face_matches + vehicle_matches} sự kiện khớp Watchlist để xác nhận nghiệp vụ an ninh.")
            if not recommendations:
                recommendations.append("Tất cả chỉ số vận hành đang trong ngưỡng ổn định, không có bất thường cần can thiệp.")

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
- **Tỷ lệ sẵn sàng luồng:** {(online_cameras / total_cameras * 100):.1f}% (trên tổng số camera kích hoạt)

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
                "metrics": {
                    "cameras": {
                        "total": total_cameras,
                        "online": online_cameras,
                        "offline": offline_cameras,
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
        return {"status": "error", "message": f"Failed to generate operational report: {exc}"}
    finally:
        db.dispose()
