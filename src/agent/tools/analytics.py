"""Analytics and statistical aggregation tools for DATT AI Agent."""

from datetime import datetime, timezone, timedelta
from typing import Any
from langchain_core.tools import tool
from sqlalchemy import func, select

from src.agent.config import agent_config
from src.db.database import Database
from src.db.models import BusinessEvent, FaceEvent, PlateEvent, VehiclePassage, VehicleWatchlistResult

LOCAL_TZ = timezone(timedelta(hours=7))  # ICT (Vietnam, UTC+7)


def get_today_calendar_bounds() -> tuple[datetime, datetime, datetime, datetime]:
    """Compute local calendar day bounds (00:00:00 to now in local ICT timezone).

    Returns:
        (today_start_utc, now_utc, today_start_local, now_local)
    """
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(LOCAL_TZ)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_local.astimezone(timezone.utc)
    return today_start_utc, now_utc, today_start_local, now_local


def parse_iso_time(val: str | None, default: datetime) -> datetime:
    """Parse ISO timestamp with fallback to default."""
    if not val:
        return default
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return default


@tool
def get_event_statistics(
    camera_id: str | None = None,
    camera: str | None = None,
    start_time: str | None = None,
    from_time: str | None = None,
    end_time: str | None = None,
    to_time: str | None = None,
    group_by: str = "type",
) -> dict[str, Any]:
    """Retrieve aggregate statistics on vehicle traffic, watchlist detections, and camera events.

    Distinguishes:
    1. Today's calendar day events (00:00:00 local ICT to now).
    2. Rolling 24-hour vehicle passages and events.
    3. All-time database totals.
    4. Unique vehicles/plates vs cumulative passages vs live occupancy.

    Args:
        camera_id: Optional camera ID to filter statistics for a single stream.
        camera: Optional alias for camera_id.
        start_time: Optional ISO timestamp start of interval (defaults to rolling 24h).
        from_time: Optional alias for start_time.
        end_time: Optional ISO timestamp end of interval (defaults to current time).
        to_time: Optional alias for end_time.
        group_by: Grouping dimension: 'type' (vehicle classification) or 'hour' or 'camera'.

    Returns:
        Structured summary with explicit separation of today's calendar events, 24h rolling traffic,
        unique vehicles, and live occupancy notices.
    """
    eff_camera = camera_id or camera
    eff_start = start_time or from_time
    eff_end = end_time or to_time

    today_start_utc, now_utc, today_start_local, now_local = get_today_calendar_bounds()
    rolling_24h_start_utc = now_utc - timedelta(hours=24)

    # Effective interval for custom requests
    since_custom = parse_iso_time(eff_start, rolling_24h_start_utc)
    until_custom = parse_iso_time(eff_end, now_utc)

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            # -------------------------------------------------------------
            # 1. TODAY'S CALENDAR DAY METRICS (00:00:00 ICT -> now)
            # -------------------------------------------------------------
            # A. Business events today
            b_today_stmt = select(func.count(BusinessEvent.id)).where(BusinessEvent.event_time >= today_start_utc)
            if eff_camera:
                b_today_stmt = b_today_stmt.where(BusinessEvent.camera_id == eff_camera.strip())
            today_biz_count = session.scalar(b_today_stmt) or 0

            # B. Face events today
            f_today_stmt = select(func.count(FaceEvent.id)).where(FaceEvent.created_at >= today_start_utc)
            if eff_camera:
                f_today_stmt = f_today_stmt.where(FaceEvent.camera_id == eff_camera.strip())
            today_face_count = session.scalar(f_today_stmt) or 0

            # C. Plate events today
            p_today_stmt = select(func.count(PlateEvent.id)).where(PlateEvent.created_at >= today_start_utc)
            today_plate_count = session.scalar(p_today_stmt) or 0

            today_total_events = today_biz_count + today_face_count + today_plate_count

            # D. Vehicle passages today
            vp_today_stmt = select(func.count(VehiclePassage.id)).where(VehiclePassage.first_seen_at >= today_start_utc)
            if eff_camera:
                vp_today_stmt = vp_today_stmt.where(VehiclePassage.camera_id == eff_camera.strip())
            today_passages_count = session.scalar(vp_today_stmt) or 0

            # E. Unique plates today
            up_today_stmt = (
                select(func.count(func.distinct(VehiclePassage.plate_text)))
                .where(
                    VehiclePassage.first_seen_at >= today_start_utc,
                    VehiclePassage.plate_text.is_not(None),
                    VehiclePassage.plate_text != "",
                )
            )
            if eff_camera:
                up_today_stmt = up_today_stmt.where(VehiclePassage.camera_id == eff_camera.strip())
            today_unique_plates_count = session.scalar(up_today_stmt) or 0

            # F. Unique tracked vehicle sessions today
            ut_today_stmt = select(func.count(func.distinct(VehiclePassage.track_id))).where(VehiclePassage.first_seen_at >= today_start_utc)
            if eff_camera:
                ut_today_stmt = ut_today_stmt.where(VehiclePassage.camera_id == eff_camera.strip())
            today_unique_tracked_vehicles = session.scalar(ut_today_stmt) or 0

            # -------------------------------------------------------------
            # 2. ROLLING 24-HOUR METRICS (now - 24h -> now)
            # -------------------------------------------------------------
            vp_24h_stmt = select(func.count(VehiclePassage.id)).where(VehiclePassage.first_seen_at >= rolling_24h_start_utc)
            if eff_camera:
                vp_24h_stmt = vp_24h_stmt.where(VehiclePassage.camera_id == eff_camera.strip())
            rolling_24h_passages = session.scalar(vp_24h_stmt) or 0

            b_24h_stmt = select(func.count(BusinessEvent.id)).where(BusinessEvent.event_time >= rolling_24h_start_utc)
            if eff_camera:
                b_24h_stmt = b_24h_stmt.where(BusinessEvent.camera_id == eff_camera.strip())
            rolling_24h_business_events = session.scalar(b_24h_stmt) or 0

            up_24h_stmt = (
                select(func.count(func.distinct(VehiclePassage.plate_text)))
                .where(
                    VehiclePassage.first_seen_at >= rolling_24h_start_utc,
                    VehiclePassage.plate_text.is_not(None),
                    VehiclePassage.plate_text != "",
                )
            )
            if eff_camera:
                up_24h_stmt = up_24h_stmt.where(VehiclePassage.camera_id == eff_camera.strip())
            rolling_24h_unique_plates = session.scalar(up_24h_stmt) or 0

            # -------------------------------------------------------------
            # 3. ALL-TIME DATABASE TOTALS
            # -------------------------------------------------------------
            all_time_biz = session.scalar(select(func.count(BusinessEvent.id))) or 0
            all_time_pass = session.scalar(select(func.count(VehiclePassage.id))) or 0

            # -------------------------------------------------------------
            # 4. CUSTOM / REQUESTED INTERVAL BREAKDOWNS
            # -------------------------------------------------------------
            # Vehicle type breakdown for custom/24h interval
            v_stmt = select(VehiclePassage.vehicle_type, func.count(VehiclePassage.id)).where(
                VehiclePassage.first_seen_at >= since_custom,
                VehiclePassage.first_seen_at < until_custom,
            )
            if eff_camera:
                v_stmt = v_stmt.where(VehiclePassage.camera_id == eff_camera.strip())
            v_stmt = v_stmt.group_by(VehiclePassage.vehicle_type)
            v_counts = {str(r[0] or "unknown"): int(r[1]) for r in session.execute(v_stmt).all()}
            custom_interval_passages = sum(v_counts.values())

            # Watchlist matches for interval
            p_match_stmt = select(func.count(VehicleWatchlistResult.id)).where(
                VehicleWatchlistResult.decision == "MATCH",
                VehicleWatchlistResult.created_at >= since_custom,
                VehicleWatchlistResult.created_at < until_custom,
            )
            if eff_camera:
                p_match_stmt = p_match_stmt.where(VehicleWatchlistResult.camera_id == eff_camera.strip())
            vehicle_matches = session.scalar(p_match_stmt) or 0

            f_match_stmt = select(func.count(FaceEvent.id)).where(
                FaceEvent.decision == "FACE_MATCH",
                FaceEvent.created_at >= since_custom,
                FaceEvent.created_at < until_custom,
            )
            if eff_camera:
                f_match_stmt = f_match_stmt.where(FaceEvent.camera_id == eff_camera.strip())
            face_matches = session.scalar(f_match_stmt) or 0

            # Business events summary for interval
            b_stmt = select(BusinessEvent.event_type, func.count(BusinessEvent.id)).where(
                BusinessEvent.event_time >= since_custom,
                BusinessEvent.event_time < until_custom,
            )
            if eff_camera:
                b_stmt = b_stmt.where(BusinessEvent.camera_id == eff_camera.strip())
            b_stmt = b_stmt.group_by(BusinessEvent.event_type)
            business_counts = {str(r[0]): int(r[1]) for r in session.execute(b_stmt).all()}

            # Camera traffic ranking
            c_stmt = (
                select(VehiclePassage.camera_id, func.count(VehiclePassage.id))
                .where(
                    VehiclePassage.first_seen_at >= since_custom,
                    VehiclePassage.first_seen_at < until_custom,
                )
                .group_by(VehiclePassage.camera_id)
                .order_by(func.count(VehiclePassage.id).desc())
            )
            cam_activity = [
                {"camera_id": str(r[0] or "unknown"), "passage_count": int(r[1])}
                for r in session.execute(c_stmt).all()
            ]
            highest_cam = cam_activity[0]["camera_id"] if cam_activity else None

            return {
                "status": "success",
                "camera_id": eff_camera or "all_cameras",
                # Calendar day metrics (local ICT UTC+7)
                "today_calendar_day": {
                    "timezone": "ICT (UTC+7)",
                    "day_start_local": today_start_local.isoformat(),
                    "day_start_utc": today_start_utc.isoformat(),
                    "total_events_today": today_total_events,
                    "business_events_today": today_biz_count,
                    "face_events_today": today_face_count,
                    "plate_events_today": today_plate_count,
                    "vehicle_passages_today": today_passages_count,
                    "unique_plates_today": today_unique_plates_count,
                    "unique_tracked_vehicles_today": today_unique_tracked_vehicles,
                },
                # Rolling 24-hour metrics
                "rolling_24h_interval": {
                    "start_time": rolling_24h_start_utc.isoformat(),
                    "end_time": now_utc.isoformat(),
                    "vehicle_passages": rolling_24h_passages,
                    "business_events": rolling_24h_business_events,
                    "unique_plates": rolling_24h_unique_plates,
                },
                # Historical database totals
                "all_time_database_totals": {
                    "total_business_events": all_time_biz,
                    "total_vehicle_passages": all_time_pass,
                },
                # Backwards compatible top-level fields
                "total_vehicle_passages": custom_interval_passages if eff_start else rolling_24h_passages,
                "vehicle_type_breakdown": v_counts,
                "busiest_cameras": cam_activity,
                "busiest_cameras_by_traffic": cam_activity,
                "highest_traffic_camera": highest_cam,
                "most_crowded_camera": highest_cam,
                "security_matches": {
                    "vehicle_watchlist_matches": vehicle_matches,
                    "face_watchlist_matches": face_matches,
                    "total_matches": vehicle_matches + face_matches,
                },
                "business_events": business_counts,
                # Clear metric distinctions to prevent LLM hallucinations
                "metric_distinction": (
                    "PHÂN BIỆT RÕ RÀNG:\n"
                    "1. 'Sự kiện hôm nay' (today_calendar_day): tính từ 00:00 giờ địa phương (ICT UTC+7).\n"
                    "2. 'Lượt xe 24h qua' (rolling_24h_interval): tính trượt 24 tiếng lùi lại từ hiện tại.\n"
                    "3. 'Lượt xe' (vehicle_passages) là số phiên xe di chuyển qua khung hình; khác với 'Xe duy nhất' (unique_plates).\n"
                    "4. 'Live occupancy' (số xe/người đang hiện diện tức thời trong khung hình) KHÔNG lưu trong DB lịch sử; "
                    "chỉ có thể quan sát trực tiếp qua video stream thời gian thực hoặc ZoneCounter."
                ),
                "live_occupancy": None,
                "live_occupancy_note": "Live frame occupancy requires active camera video ingest (ZoneCounter/FrameOccupancy); database records represent historical cumulative passages.",
            }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to calculate event statistics: {exc}"}
    finally:
        db.dispose()
