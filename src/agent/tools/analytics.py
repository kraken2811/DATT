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


def parse_time_bounds(
    time_range: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
) -> tuple[datetime, datetime, str]:
    """Parse time bounds in ICT (UTC+7) timezone.

    Returns:
        (start_utc, end_utc, label_ict)
    """
    now_utc = datetime.now(timezone.utc)
    now_ict = now_utc.astimezone(LOCAL_TZ)

    tr = (time_range or "").lower().strip()
    if tr in ("today", "hom_nay", "hom nay"):
        start_ict = now_ict.replace(hour=0, minute=0, second=0, microsecond=0)
        end_ict = now_ict
        label = "Hôm nay (từ 00:00 ICT đến hiện tại)"
    elif tr in ("yesterday", "hom_qua", "hom qua"):
        today_0 = now_ict.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ict = today_0 - timedelta(days=1)
        end_ict = today_0 - timedelta(microseconds=1)
        label = f"Hôm qua ({start_ict.strftime('%d/%m/%Y')} ICT)"
    elif tr in ("7_days", "7_ngay", "7 ngay", "7 days", "tuan_qua", "tuan qua"):
        start_ict = now_ict - timedelta(days=7)
        end_ict = now_ict
        label = "7 ngày gần đây"
    elif tr in ("this_week", "tuan_nay", "tuan nay"):
        start_ict = (now_ict - timedelta(days=now_ict.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end_ict = now_ict
        label = "Tuần này"
    elif tr in ("last_week", "tuan_truoc", "tuan truoc"):
        start_this_week = (now_ict - timedelta(days=now_ict.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start_ict = start_this_week - timedelta(days=7)
        end_ict = start_this_week - timedelta(microseconds=1)
        label = f"Tuần trước ({start_ict.strftime('%d/%m/%Y')} - {end_ict.strftime('%d/%m/%Y')})"
    elif from_time:
        start_dt = parse_iso_time(from_time, now_utc - timedelta(days=1))
        end_dt = parse_iso_time(to_time, now_utc)
        return start_dt, end_dt, f"Từ {start_dt.isoformat()} đến {end_dt.isoformat()}"
    else:
        start_ict = now_ict - timedelta(hours=24)
        end_ict = now_ict
        label = "24 giờ qua (rolling 24h)"

    start_utc = start_ict.astimezone(timezone.utc)
    end_utc = end_ict.astimezone(timezone.utc)
    return start_utc, end_utc, label


@tool
def get_traffic_analytics(
    camera_id: str | None = None,
    time_range: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    group_by: str = "camera",
    compare_with: str | None = None,
) -> dict[str, Any]:
    """Retrieve detailed vehicle traffic analytics, peak hours, and period-over-period comparisons.

    Distinguishes:
    1. VehiclePassage sessions (distinct physical passages through a camera) vs raw detection frames.
    2. Grouping by camera, hour of day, day, or vehicle classification.
    3. Peak traffic hours and busiest camera identification strictly from recorded data.
    4. Comparisons with baseline periods (e.g. today vs yesterday, this week vs last week),
       safely handling zero baseline without mathematical division errors.
    5. Notice: Cumulative historical passages do not represent live instantaneous occupancy.

    Args:
        camera_id: Optional camera ID or registry key (e.g. 'camera_01', 'CAM01') to filter by.
        time_range: Preset interval: 'today', 'yesterday', '7_days', 'this_week', 'last_week', or 'custom'.
        from_time: Optional start ISO timestamp / date string.
        to_time: Optional end ISO timestamp / date string.
        start_time: Optional alias for from_time.
        end_time: Optional alias for to_time.
        group_by: Aggregation dimension: 'camera', 'hour', 'day', 'type' (vehicle type), or 'camera_and_type'.
        compare_with: Optional comparison baseline: 'yesterday' or 'last_week'.

    Returns:
        Structured traffic analysis containing total passages, unique plates, grouped breakdowns,
        peak hours, and period comparisons.
    """
    eff_start = from_time or start_time
    eff_end = to_time or end_time
    start_utc, end_utc, time_label = parse_time_bounds(time_range, eff_start, eff_end)

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            # 1. Total passages in requested interval
            base_q = select(func.count(VehiclePassage.id)).where(
                VehiclePassage.first_seen_at >= start_utc,
                VehiclePassage.first_seen_at <= end_utc,
            )
            if camera_id and camera_id.strip():
                base_q = base_q.where(VehiclePassage.camera_id == camera_id.strip())
            total_passages = session.scalar(base_q) or 0

            # 2. Unique plates in requested interval
            unique_plates_q = select(func.count(func.distinct(VehiclePassage.plate_text))).where(
                VehiclePassage.first_seen_at >= start_utc,
                VehiclePassage.first_seen_at <= end_utc,
                VehiclePassage.plate_text.is_not(None),
                VehiclePassage.plate_text != "",
            )
            if camera_id and camera_id.strip():
                unique_plates_q = unique_plates_q.where(VehiclePassage.camera_id == camera_id.strip())
            unique_plates = session.scalar(unique_plates_q) or 0

            # 3. Vehicle type breakdown
            type_q = (
                select(VehiclePassage.vehicle_type, func.count(VehiclePassage.id))
                .where(
                    VehiclePassage.first_seen_at >= start_utc,
                    VehiclePassage.first_seen_at <= end_utc,
                )
            )
            if camera_id and camera_id.strip():
                type_q = type_q.where(VehiclePassage.camera_id == camera_id.strip())
            type_counts = {str(r[0] or "unknown"): int(r[1]) for r in session.execute(type_q.group_by(VehiclePassage.vehicle_type)).all()}

            # 4. Dialect-aware grouped data
            is_pg = session.bind.dialect.name == "postgresql"
            grouped_data: list[dict[str, Any]] = []
            busiest_item: dict[str, Any] | None = None

            grp = group_by.lower().strip()
            if grp in ("camera", "cameras"):
                cam_q = (
                    select(VehiclePassage.camera_id, func.count(VehiclePassage.id))
                    .where(
                        VehiclePassage.first_seen_at >= start_utc,
                        VehiclePassage.first_seen_at <= end_utc,
                    )
                    .group_by(VehiclePassage.camera_id)
                    .order_by(func.count(VehiclePassage.id).desc())
                )
                cam_rows = session.execute(cam_q).all()
                for cid, cnt in cam_rows:
                    grouped_data.append({"camera_id": str(cid), "passage_count": int(cnt)})
                if grouped_data:
                    busiest_item = {
                        "dimension": "camera",
                        "camera_id": grouped_data[0]["camera_id"],
                        "passage_count": grouped_data[0]["passage_count"],
                    }

            elif grp in ("hour", "peak_hour", "peak_hours"):
                if is_pg:
                    hour_expr = func.to_char(func.timezone("Asia/Ho_Chi_Minh", VehiclePassage.first_seen_at), "HH24")
                else:
                    hour_expr = func.strftime("%H", func.datetime(VehiclePassage.first_seen_at, "+7 hours"))

                hq = (
                    select(hour_expr, func.count(VehiclePassage.id))
                    .where(
                        VehiclePassage.first_seen_at >= start_utc,
                        VehiclePassage.first_seen_at <= end_utc,
                    )
                )
                if camera_id and camera_id.strip():
                    hq = hq.where(VehiclePassage.camera_id == camera_id.strip())
                hq = hq.group_by(hour_expr).order_by(func.count(VehiclePassage.id).desc())

                h_rows = session.execute(hq).all()
                for hr, cnt in h_rows:
                    h_str = f"{int(hr):02d}:00 - {int(hr)+1:02d}:00" if hr is not None else "chưa rõ"
                    grouped_data.append({"hour_slot": h_str, "hour_24": str(hr), "passage_count": int(cnt)})
                if grouped_data:
                    busiest_item = {
                        "dimension": "hour",
                        "peak_hour": grouped_data[0]["hour_slot"],
                        "passage_count": grouped_data[0]["passage_count"],
                    }

            elif grp in ("day", "daily"):
                if is_pg:
                    day_expr = func.to_char(func.timezone("Asia/Ho_Chi_Minh", VehiclePassage.first_seen_at), "YYYY-MM-DD")
                else:
                    day_expr = func.strftime("%Y-%m-%d", func.datetime(VehiclePassage.first_seen_at, "+7 hours"))

                dq = (
                    select(day_expr, func.count(VehiclePassage.id))
                    .where(
                        VehiclePassage.first_seen_at >= start_utc,
                        VehiclePassage.first_seen_at <= end_utc,
                    )
                )
                if camera_id and camera_id.strip():
                    dq = dq.where(VehiclePassage.camera_id == camera_id.strip())
                dq = dq.group_by(day_expr).order_by(day_expr.asc())

                d_rows = session.execute(dq).all()
                for d_val, cnt in d_rows:
                    grouped_data.append({"date": str(d_val), "passage_count": int(cnt)})

            elif grp in ("camera_and_type", "type_by_camera"):
                cq = (
                    select(VehiclePassage.camera_id, VehiclePassage.vehicle_type, func.count(VehiclePassage.id))
                    .where(
                        VehiclePassage.first_seen_at >= start_utc,
                        VehiclePassage.first_seen_at <= end_utc,
                    )
                    .group_by(VehiclePassage.camera_id, VehiclePassage.vehicle_type)
                    .order_by(VehiclePassage.camera_id.asc(), func.count(VehiclePassage.id).desc())
                )
                for cid, vtype, cnt in session.execute(cq).all():
                    grouped_data.append({
                        "camera_id": str(cid),
                        "vehicle_type": str(vtype or "unknown"),
                        "passage_count": int(cnt),
                    })
            else:
                grouped_data = [{"vehicle_type": k, "passage_count": v} for k, v in type_counts.items()]

            # 5. Period-over-period comparison
            comparison: dict[str, Any] | None = None
            if compare_with:
                cw = compare_with.lower().strip()
                shift_delta = timedelta(days=1) if cw in ("yesterday", "previous_day") else timedelta(days=7)
                baseline_start = start_utc - shift_delta
                baseline_end = end_utc - shift_delta

                comp_q = select(func.count(VehiclePassage.id)).where(
                    VehiclePassage.first_seen_at >= baseline_start,
                    VehiclePassage.first_seen_at <= baseline_end,
                )
                if camera_id and camera_id.strip():
                    comp_q = comp_q.where(VehiclePassage.camera_id == camera_id.strip())
                baseline_total = session.scalar(comp_q) or 0

                diff = total_passages - baseline_total
                if baseline_total > 0:
                    pct_change = round((diff / baseline_total) * 100, 1)
                    trend = "tăng" if diff > 0 else ("giảm" if diff < 0 else "không đổi")
                else:
                    pct_change = None
                    trend = "không có dữ liệu mốc đối chứng (baseline = 0)"

                comparison = {
                    "baseline_period": f"{cw} (lùi {shift_delta.days} ngày)",
                    "baseline_total_passages": baseline_total,
                    "current_total_passages": total_passages,
                    "difference": diff,
                    "percent_change": pct_change,
                    "trend_description": trend,
                    "zero_baseline": baseline_total == 0,
                }

            return {
                "status": "success",
                "time_range": time_label,
                "timezone": "ICT (UTC+7)",
                "interval_utc": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
                "camera_filter": camera_id or "all_cameras",
                "total_vehicle_passages": total_passages,
                "unique_plates_count": unique_plates,
                "vehicle_type_breakdown": type_counts,
                "group_by": group_by,
                "grouped_analytics": grouped_data,
                "busiest_period": busiest_item,
                "comparison": comparison,
                "distinction_note": (
                    "Số liệu 'lượt xe' (VehiclePassage) ghi nhận từng phiên xe di chuyển qua camera; "
                    "không đo lường số xe hiện diện tĩnh (occupancy) tại một thời điểm."
                ),
            }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to compute traffic analytics: {exc}"}
    finally:
        db.dispose()
