"""Automated Shift Handover Reporting Tool for DATT Operations.

Supports configurable shifts in Asia/Ho_Chi_Minh (UTC+7):
- Morning shift:   06:00 - 14:00
- Afternoon shift: 14:00 - 22:00
- Night shift:     22:00 - 06:00 (cross-date boundary)
- Current shift:   dynamic based on current ICT time

Produces structured metrics and executive Vietnamese handover summaries covering:
1. Camera fleet infrastructure and health
2. Traffic flow and classification
3. Security watchlist events and critical alerts
4. Email notification delivery and retry status
5. Operational handover checklist and outstanding issues
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from sqlalchemy import func, select, or_, and_, desc

from src.agent.config import agent_config
from src.db.models import (
    AnalyticsAggregate,
    Camera,
    FaceEvent,
    Notification,
    PlateEvent,
    VehiclePassage,
    VehicleWatchlist,
)

logger = logging.getLogger("datt.agent.shift_reports")
LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh (UTC+7)


def utc_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def format_ict_time(dt: datetime | None) -> str:
    if dt is None:
        return "N/A"
    dt_utc = utc_timestamp(dt)
    dt_ict = dt_utc.astimezone(LOCAL_TZ)
    return dt_ict.strftime("%H:%M:%S %d/%m/%Y")


def resolve_shift_bounds(
    shift_type: str = "current",
    shift_date: str | None = None,
) -> tuple[datetime, datetime, str, str]:
    """Calculate exact UTC boundaries for requested shift in Asia/Ho_Chi_Minh.

    Returns:
        (start_utc, end_utc, shift_label, date_label)
    """
    now_utc = datetime.now(timezone.utc)
    now_ict = now_utc.astimezone(LOCAL_TZ)

    # Resolve target base date
    if shift_date:
        try:
            target_dt = datetime.strptime(shift_date.strip(), "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
        except ValueError:
            try:
                target_dt = datetime.strptime(shift_date.strip(), "%d/%m/%Y").replace(tzinfo=LOCAL_TZ)
            except ValueError:
                target_dt = now_ict
    else:
        target_dt = now_ict

    st = (shift_type or "current").lower().strip()

    if st in ("current", "hien_tai", "hien tai"):
        hour = now_ict.hour
        if 6 <= hour < 14:
            st = "morning"
        elif 14 <= hour < 22:
            st = "afternoon"
        else:
            st = "night"
            # If after midnight (00:00 - 05:59), the night shift started yesterday at 22:00
            if hour < 6:
                target_dt = target_dt - timedelta(days=1)

    base_day = target_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    if st in ("morning", "sang", "ca_sang", "ca sang"):
        shift_label = "Ca Sáng (06:00 - 14:00)"
        start_ict = base_day.replace(hour=6, minute=0, second=0)
        end_ict = base_day.replace(hour=14, minute=0, second=0)
    elif st in ("afternoon", "chieu", "ca_chieu", "ca chieu"):
        shift_label = "Ca Chiều (14:00 - 22:00)"
        start_ict = base_day.replace(hour=14, minute=0, second=0)
        end_ict = base_day.replace(hour=22, minute=0, second=0)
    elif st in ("night", "toi", "dem", "ca_toi", "ca toi", "ca_dem", "ca dem"):
        shift_label = "Ca Đêm (22:00 - 06:00 ngày hôm sau)"
        start_ict = base_day.replace(hour=22, minute=0, second=0)
        end_ict = (base_day + timedelta(days=1)).replace(hour=6, minute=0, second=0)
    else:
        # Default fallback to morning
        shift_label = f"Ca Tùy chỉnh: {shift_type}"
        start_ict = base_day.replace(hour=6, minute=0, second=0)
        end_ict = base_day.replace(hour=14, minute=0, second=0)

    date_label = start_ict.strftime("%d/%m/%Y")
    return start_ict.astimezone(timezone.utc), end_ict.astimezone(timezone.utc), shift_label, date_label


@tool
def generate_shift_handover_report(
    shift_type: str = "current",
    shift_date: str | None = None,
    camera_id: str | None = None,
) -> dict[str, Any]:
    """Generate an automated, comprehensive Shift Handover Report (Báo cáo bàn giao ca trực).

    Aggregates operational state for the designated shift period (Morning 06:00-14:00,
    Afternoon 14:00-22:00, or Night 22:00-06:00 next day in Asia/Ho_Chi_Minh).

    Sections:
    1. Camera Infrastructure: Fleet availability, online/offline count, and last active status.
    2. Traffic: Total person/vehicle passages, peak traffic hour, busiest camera, vehicle classification breakdown.
    3. Security: Face Watchlist matches, Vehicle Watchlist matches, critical alert counts.
    4. Notifications: Dispatched outbox deliveries, pending items, failures, retry counts.
    5. Handover Summary: Outstanding incidents, unresolved items, and follow-up recommendations.

    Args:
        shift_type: Shift period: 'morning', 'afternoon', 'night', or 'current' (default: 'current').
        shift_date: Target date string ('YYYY-MM-DD' or 'DD/MM/YYYY', default: today).
        camera_id: Optional camera identifier to scope the report to a single camera.

    Returns:
        Structured shift handover metrics and a formatted Vietnamese operational Markdown report.
    """
    start_utc, end_utc, shift_label, date_label = resolve_shift_bounds(shift_type, shift_date)
    db = agent_config.get_database()

    try:
        with db.transaction() as session:
            # 1. Camera Infrastructure
            cam_query = select(Camera)
            if camera_id:
                clean_cid = camera_id.strip()
                try:
                    cuuid = UUID(clean_cid)
                    cam_query = cam_query.where(or_(Camera.id == cuuid, Camera.registry_key == clean_cid))
                except ValueError:
                    cam_query = cam_query.where(Camera.registry_key == clean_cid)

            cameras = session.scalars(cam_query).all()
            total_cameras = len(cameras)
            now_utc = datetime.now(timezone.utc)

            online_cams = 0
            offline_cams = 0
            offline_list: list[str] = []

            for c in cameras:
                l_act = utc_timestamp(c.last_active)
                is_on = (
                    c.enabled
                    and (
                        (l_act and (now_utc - l_act).total_seconds() < 300)
                        or (c.active_until and utc_timestamp(c.active_until) > now_utc)
                    )
                )
                if is_on:
                    online_cams += 1
                else:
                    offline_cams += 1
                    offline_list.append(c.name or str(c.id)[:8])

            # 2. Traffic Flow & Passages during the shift
            # Query VehiclePassages
            vp_stmt = (
                select(VehiclePassage)
                .where(VehiclePassage.first_seen_at >= start_utc)
                .where(VehiclePassage.first_seen_at <= end_utc)
            )
            if camera_id:
                vp_stmt = vp_stmt.where(VehiclePassage.camera_id == camera_id)

            vehicle_passages = session.scalars(vp_stmt).all()
            total_vehicle_passages = len(vehicle_passages)

            # Vehicle classification breakdown
            class_counts: dict[str, int] = {}
            for vp in vehicle_passages:
                v_type = vp.vehicle_type or "vehicle"
                class_counts[v_type] = class_counts.get(v_type, 0) + 1

            # Query AnalyticsAggregates for person count and peak hour
            agg_stmt = (
                select(AnalyticsAggregate)
                .where(AnalyticsAggregate.bucket_start >= start_utc)
                .where(AnalyticsAggregate.bucket_start <= end_utc)
            )
            if camera_id:
                agg_stmt = agg_stmt.where(AnalyticsAggregate.camera_id == camera_id)
            aggregates = session.scalars(agg_stmt).all()

            total_person_passages = sum(
                (a.person_in_count or 0) + (a.person_out_count or 0) for a in aggregates
            )

            # Calculate peak traffic hour in ICT
            hourly_traffic: dict[int, int] = {}
            camera_traffic: dict[str, int] = {}

            for a in aggregates:
                h_ict = utc_timestamp(a.bucket_start).astimezone(LOCAL_TZ).hour
                vol = (
                    (a.person_in_count or 0)
                    + (a.person_out_count or 0)
                    + (a.vehicle_in_count or 0)
                    + (a.vehicle_out_count or 0)
                )
                hourly_traffic[h_ict] = hourly_traffic.get(h_ict, 0) + vol
                c_key = a.camera_id or "unknown"
                camera_traffic[c_key] = camera_traffic.get(c_key, 0) + vol

            cam_name_map = {str(c.id): (c.name or c.registry_key or str(c.id)[:8]) for c in cameras}
            for c in cameras:
                if c.registry_key:
                    cam_name_map[c.registry_key] = c.name or c.registry_key

            peak_hour_ict = max(hourly_traffic, key=hourly_traffic.get) if hourly_traffic else None
            peak_traffic_val = hourly_traffic[peak_hour_ict] if peak_hour_ict is not None else 0
            busiest_camera_id = max(camera_traffic, key=camera_traffic.get) if camera_traffic else None
            busiest_traffic_val = camera_traffic[busiest_camera_id] if busiest_camera_id else 0
            busiest_camera_name = cam_name_map.get(busiest_camera_id, busiest_camera_id) if busiest_camera_id else "Chưa xác định"

            # 3. Security Watchlist & Alert Center
            # Face Watchlist matches during shift
            face_match_stmt = (
                select(func.count(FaceEvent.id))
                .where(FaceEvent.created_at >= start_utc)
                .where(FaceEvent.created_at <= end_utc)
                .where(FaceEvent.target_id != None)
            )
            face_matches = session.scalar(face_match_stmt) or 0

            # Vehicle Watchlist matches during shift
            plate_match_stmt = (
                select(func.count(PlateEvent.id))
                .where(PlateEvent.created_at >= start_utc)
                .where(PlateEvent.created_at <= end_utc)
                .where(PlateEvent.status == "matched")
            )
            vehicle_matches = session.scalar(plate_match_stmt) or 0

            # Total alerts & critical alerts
            alert_stmt = (
                select(Notification)
                .where(Notification.created_at >= start_utc)
                .where(Notification.created_at <= end_utc)
            )
            shift_alerts = session.scalars(alert_stmt).all()
            total_alerts = len(shift_alerts)

            # 4. Notifications Outbox Health
            notif_sent = sum(1 for n in shift_alerts if n.status == "sent")
            notif_pending = sum(1 for n in shift_alerts if n.status == "pending")
            notif_failed = sum(1 for n in shift_alerts if n.status == "failed")
            notif_suppressed = sum(1 for n in shift_alerts if n.status == "suppressed")

            # 5. Handover Checklist & Outstanding Issues
            outstanding_issues: list[str] = []
            if offline_cams > 0:
                outstanding_issues.append(f"Có {offline_cams} camera offline cần kiểm tra luồng video: {', '.join(offline_list[:3])}")
            if notif_failed > 0:
                outstanding_issues.append(f"Có {notif_failed} thông báo gửi thất bại trong outbox cần xử lý hoặc thử lại.")
            if total_alerts > 0:
                outstanding_issues.append(f"Ghi nhận {total_alerts} cảnh báo an ninh trong ca trực cần đối chiếu nhật ký trực.")
            if not outstanding_issues:
                outstanding_issues.append("Ca trực hoạt động ổn định, không có sự cố kỹ thuật nghiêm trọng tồn đọng.")

            # Build Formatted Vietnamese Markdown Report
            report_md = (
                f"# 📋 BÁO CÁO BÀN GIAO CA TRỰC — DATT VISION OPS\n\n"
                f"**Ca trực:** {shift_label} — **Ngày:** {date_label}\n"
                f"**Khoảng thời gian (ICT):** {format_ict_time(start_utc)} đến {format_ict_time(end_utc)}\n\n"
                f"---\n\n"
                f"### 1. 📡 Hạ tầng Camera Giám sát\n"
                f"- **Tổng số camera quản lý:** {total_cameras}\n"
                f"- **Đang hoạt động (Online):** {online_cams} ({round((online_cams / total_cameras * 100), 1) if total_cameras > 0 else 0}%)\n"
                f"- **Ngoại tuyến (Offline):** {offline_cams}\n"
            )
            if offline_list:
                report_md += f"- **Danh sách camera offline:** {', '.join(offline_list)}\n"

            report_md += (
                f"\n### 2. 🚗 Lưu lượng & Phân loại Phương tiện\n"
                f"- **Tổng lượt người qua lại:** {total_person_passages:,}\n"
                f"- **Tổng lượt phương tiện:** {total_vehicle_passages:,}\n"
                f"- **Khung giờ cao điểm:** {f'{peak_hour_ict}:00 - {peak_hour_ict+1}:00 ({peak_traffic_val:,} lượt)' if peak_hour_ict is not None else 'Không có dữ liệu'}\n"
                f"- **Camera lưu lượng lớn nhất:** {busiest_camera_name} ({busiest_traffic_val:,} lượt)\n"
                f"- **Phân loại phương tiện:**\n"
            )
            for v_cls, v_cnt in class_counts.items():
                report_md += f"  - `{v_cls}`: {v_cnt:,} lượt\n"
            if not class_counts:
                report_md += "  - Chưa có lượt xe ghi nhận trong ca.\n"

            report_md += (
                f"\n### 3. 🚨 An ninh & Danh sách Theo dõi (Watchlist)\n"
                f"- **Khớp danh sách theo dõi khuôn mặt (Face):** {face_matches} lần\n"
                f"- **Khớp danh sách theo dõi biển số (Vehicle):** {vehicle_matches} lần\n"
                f"- **Tổng số cảnh báo kích hoạt:** {total_alerts}\n\n"
                f"### 4. ✉️ Trạng thái Thông báo (Notification Delivery)\n"
                f"- **Đã gửi (Sent):** {notif_sent}\n"
                f"- **Đang chờ (Pending):** {notif_pending}\n"
                f"- **Thất bại (Failed):** {notif_failed}\n"
                f"- **Tạm dừng (Suppressed - Cooldown):** {notif_suppressed}\n"
                f"> *Lưu ý: Trạng thái 'Sent' biểu thị hệ thống đã chuyển phát thành công qua SMTP relay; không phải bằng chứng người nhận đã mở email.*\n\n"
                f"### 5. ✅ Tồn đọng & Bàn giao Ca kế tiếp\n"
            )
            for iss in outstanding_issues:
                report_md += f"- {iss}\n"

            return {
                "status": "success",
                "shift_label": shift_label,
                "shift_date": date_label,
                "time_bounds_ict": f"{format_ict_time(start_utc)} - {format_ict_time(end_utc)}",
                "infrastructure": {
                    "total_cameras": total_cameras,
                    "online_cameras": online_cams,
                    "offline_cameras": offline_cams,
                    "offline_camera_names": offline_list,
                },
                "traffic": {
                    "total_person_passages": total_person_passages,
                    "total_vehicle_passages": total_vehicle_passages,
                    "peak_hour_ict": peak_hour_ict,
                    "peak_traffic_volume": peak_traffic_val,
                    "busiest_camera": busiest_camera_name,
                    "busiest_camera_id": busiest_camera_id,
                    "vehicle_classification": class_counts,
                },
                "security": {
                    "face_watchlist_matches": face_matches,
                    "vehicle_watchlist_matches": vehicle_matches,
                    "total_alerts": total_alerts,
                },
                "notifications": {
                    "sent": notif_sent,
                    "pending": notif_pending,
                    "failed": notif_failed,
                    "suppressed": notif_suppressed,
                },
                "handover_checklist": outstanding_issues,
                "report_markdown": report_md,
            }
    finally:
        db.dispose()
