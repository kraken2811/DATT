"""Historical Analytics Engine for DATT.

Aggregates physical passages (CrossingEvent and AnalyticsAggregate),
identifies peak hours, weekday vs weekend patterns, and camera/zone comparisons.
Converts UTC stored timestamps to Asia/Ho_Chi_Minh (ICT, UTC+7).
"""

from datetime import datetime, timezone, timedelta
from typing import Any
import math

from sqlalchemy import func, select, or_, and_, desc
from sqlalchemy.orm import Session

from src.db.database import Database
from src.db.models import CrossingEvent, AnalyticsAggregate, Camera, Zone, CameraAnalyticsConfig

LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh (UTC+7)


def get_local_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(LOCAL_TZ)


def to_local_datetime(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def parse_analytics_time_bounds(
    time_range: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
) -> tuple[datetime, datetime, str]:
    """Parse time bounds in Asia/Ho_Chi_Minh (UTC+7).

    Returns:
        (start_utc, end_utc, label_ict)
    """
    now_local = get_local_now()

    tr = (time_range or "").lower().strip()
    if tr in ("today", "hom_nay", "hom nay"):
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        label = "Hôm nay"
    elif tr in ("yesterday", "hom_qua", "hom qua"):
        today_0 = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_local = today_0 - timedelta(days=1)
        end_local = today_0 - timedelta(microseconds=1)
        label = f"Hôm qua ({start_local.strftime('%d/%m/%Y')})"
    elif tr in ("7_days", "7_ngay", "7 ngay", "7 days", "tuan_qua", "tuan qua"):
        start_local = (now_local - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = now_local
        label = "7 ngày qua"
    elif tr in ("30_days", "30_ngay", "30 ngay", "30 days", "thang_qua"):
        start_local = (now_local - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = now_local
        label = "30 ngày qua"
    elif tr in ("this_week", "tuan_nay", "tuan nay"):
        start_local = (now_local - timedelta(days=now_local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = now_local
        label = "Tuần này"
    elif tr in ("last_week", "tuan_truoc", "tuan truoc"):
        this_week_0 = (now_local - timedelta(days=now_local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        start_local = this_week_0 - timedelta(days=7)
        end_local = this_week_0 - timedelta(microseconds=1)
        label = f"Tuần trước ({start_local.strftime('%d/%m/%Y')} - {end_local.strftime('%d/%m/%Y')})"
    elif from_time:
        try:
            start_dt = datetime.fromisoformat(from_time.replace("Z", "+00:00"))
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            start_local = start_dt.astimezone(LOCAL_TZ)
        except Exception:
            start_local = now_local - timedelta(days=7)

        if to_time:
            try:
                end_dt = datetime.fromisoformat(to_time.replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                end_local = end_dt.astimezone(LOCAL_TZ)
            except Exception:
                end_local = now_local
        else:
            end_local = now_local
        label = f"{start_local.strftime('%d/%m/%Y')} - {end_local.strftime('%d/%m/%Y')}"
    else:
        # Default to rolling 7 days
        start_local = (now_local - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = now_local
        label = "7 ngày qua"

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    return start_utc, end_utc, label


class HistoricalAnalyticsService:
    """Core analytical service for calculating volume, peak hours, and patterns."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def get_historical_analytics(
        self,
        camera_id: str | None = None,
        zone_id: str | None = None,
        object_type: str | None = None,  # "person", "vehicle", or None (all)
        vehicle_class: str | None = None,
        direction: str | None = None,  # "in", "out", or None
        time_range: str | None = "7_days",
        from_time: str | None = None,
        to_time: str | None = None,
        group_by: str = "hour",
        compare_with: str | None = None,  # "previous_period", "yesterday", "last_week"
    ) -> dict[str, Any]:
        """Calculate historical traffic volume, patterns, distributions, and comparisons."""
        start_utc, end_utc, label_ict = parse_analytics_time_bounds(time_range, from_time, to_time)
        duration_hours = max(1.0, (end_utc - start_utc).total_seconds() / 3600.0)

        with self.db.transaction() as session:
            # 1. Base filter for CrossingEvent
            base_filters = [
                CrossingEvent.event_time >= start_utc,
                CrossingEvent.event_time <= end_utc,
            ]
            if camera_id and camera_id.strip() and camera_id != "all":
                base_filters.append(CrossingEvent.camera_id == camera_id.strip())
            if zone_id and zone_id.strip() and zone_id != "all":
                base_filters.append(CrossingEvent.zone_id == zone_id.strip())
            if object_type and object_type.strip() and object_type != "all":
                base_filters.append(CrossingEvent.object_type == object_type.strip())
            if vehicle_class and vehicle_class.strip() and vehicle_class != "all":
                base_filters.append(CrossingEvent.object_class == vehicle_class.strip())
            if direction and direction.strip() and direction != "all":
                base_filters.append(CrossingEvent.direction == direction.strip())

            # 2. Aggregations: Total passages, in_count, out_count
            stmt_totals = select(
                CrossingEvent.object_type,
                CrossingEvent.direction,
                func.count(CrossingEvent.id),
            ).where(and_(*base_filters)).group_by(CrossingEvent.object_type, CrossingEvent.direction)

            person_in = 0
            person_out = 0
            vehicle_in = 0
            vehicle_out = 0

            for o_type, o_dir, cnt in session.execute(stmt_totals).all():
                c = int(cnt)
                if o_type == "person":
                    if o_dir == "in":
                        person_in += c
                    else:
                        person_out += c
                elif o_type == "vehicle":
                    if o_dir == "in":
                        vehicle_in += c
                    else:
                        vehicle_out += c

            total_person = person_in + person_out
            total_vehicle = vehicle_in + vehicle_out
            total_passages = total_person + total_vehicle

            # 3. Vehicle class breakdown
            stmt_classes = select(
                CrossingEvent.object_class,
                CrossingEvent.direction,
                func.count(CrossingEvent.id),
            ).where(
                and_(*base_filters),
                CrossingEvent.object_type == "vehicle",
            ).group_by(CrossingEvent.object_class, CrossingEvent.direction)

            vehicle_breakdown: dict[str, dict[str, int]] = {}
            for o_cls, o_dir, cnt in session.execute(stmt_classes).all():
                cls_name = str(o_cls or "vehicle")
                if cls_name not in vehicle_breakdown:
                    vehicle_breakdown[cls_name] = {"in": 0, "out": 0, "total": 0}
                vehicle_breakdown[cls_name][o_dir] = int(cnt)
                vehicle_breakdown[cls_name]["total"] += int(cnt)

            # 4. Hourly distribution (0..23 in local ICT time)
            is_pg = session.bind.dialect.name == "postgresql"
            if is_pg:
                hour_expr = func.extract("hour", func.timezone("Asia/Ho_Chi_Minh", CrossingEvent.event_time))
            else:
                hour_expr = func.strftime("%H", func.datetime(CrossingEvent.event_time, "+7 hours"))

            stmt_hourly = select(
                hour_expr,
                CrossingEvent.direction,
                func.count(CrossingEvent.id),
            ).where(and_(*base_filters)).group_by(hour_expr, CrossingEvent.direction)

            hourly_map = {h: {"hour": h, "hour_slot": f"{h:02d}:00 - {h+1:02d}:00", "in": 0, "out": 0, "total": 0} for h in range(24)}
            for h_val, o_dir, cnt in session.execute(stmt_hourly).all():
                if h_val is not None:
                    h_int = int(h_val)
                    if 0 <= h_int < 24:
                        c = int(cnt)
                        if o_dir == "in":
                            hourly_map[h_int]["in"] += c
                        else:
                            hourly_map[h_int]["out"] += c
                        hourly_map[h_int]["total"] += c

            hourly_distribution = [hourly_map[h] for h in range(24)]

            # 5. Peak hour identification
            sorted_hours = sorted(hourly_distribution, key=lambda x: x["total"], reverse=True)
            peak_hour_slot = sorted_hours[0]["hour_slot"] if sorted_hours and sorted_hours[0]["total"] > 0 else "Chưa ghi nhận"
            peak_hour_count = sorted_hours[0]["total"] if sorted_hours else 0

            # 6. Daily distribution (timeline)
            if is_pg:
                day_expr = func.to_char(func.timezone("Asia/Ho_Chi_Minh", CrossingEvent.event_time), "YYYY-MM-DD")
            else:
                day_expr = func.strftime("%Y-%m-%d", func.datetime(CrossingEvent.event_time, "+7 hours"))

            stmt_daily = select(
                day_expr,
                CrossingEvent.direction,
                func.count(CrossingEvent.id),
            ).where(and_(*base_filters)).group_by(day_expr, CrossingEvent.direction).order_by(day_expr.asc())

            daily_map: dict[str, dict[str, Any]] = {}
            for d_str, o_dir, cnt in session.execute(stmt_daily).all():
                d_key = str(d_str)
                if d_key not in daily_map:
                    daily_map[d_key] = {"date": d_key, "in": 0, "out": 0, "total": 0}
                c = int(cnt)
                if o_dir == "in":
                    daily_map[d_key]["in"] += c
                else:
                    daily_map[d_key]["out"] += c
                daily_map[d_key]["total"] += c

            daily_distribution = sorted(daily_map.values(), key=lambda x: x["date"])

            # 7. Day-of-week & Weekday vs Weekend Comparison
            # 0=Monday .. 6=Sunday
            weekday_totals = {i: {"in": 0, "out": 0, "total": 0, "days_count": set()} for i in range(7)}
            weekday_names = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

            # Map days to weekday
            for d_rec in daily_distribution:
                try:
                    d_obj = datetime.strptime(d_rec["date"], "%Y-%m-%d")
                    w = d_obj.weekday()
                    weekday_totals[w]["in"] += d_rec["in"]
                    weekday_totals[w]["out"] += d_rec["out"]
                    weekday_totals[w]["total"] += d_rec["total"]
                    weekday_totals[w]["days_count"].add(d_rec["date"])
                except Exception:
                    pass

            weekday_comparison = []
            weekday_sum = 0
            weekday_days_sum = 0
            weekend_sum = 0
            weekend_days_sum = 0

            for w_idx in range(7):
                item = weekday_totals[w_idx]
                day_count = max(1, len(item["days_count"]))
                avg_traffic = round(item["total"] / day_count, 1)
                weekday_comparison.append({
                    "weekday_index": w_idx,
                    "weekday_name": weekday_names[w_idx],
                    "total": item["total"],
                    "average_per_day": avg_traffic,
                    "in": item["in"],
                    "out": item["out"],
                    "observed_days": len(item["days_count"]),
                })

                if w_idx < 5:  # Monday to Friday
                    weekday_sum += item["total"]
                    weekday_days_sum += len(item["days_count"])
                else:  # Saturday and Sunday
                    weekend_sum += item["total"]
                    weekend_days_sum += len(item["days_count"])

            weekday_avg = round(weekday_sum / max(1, weekday_days_sum), 1)
            weekend_avg = round(weekend_sum / max(1, weekend_days_sum), 1)

            if weekend_avg > weekday_avg:
                weekend_vs_weekday_summary = f"Cuối tuần đông hơn ngày thường ({weekend_avg} so với {weekday_avg} lượt/ngày, chênh lệch +{round(weekend_avg - weekday_avg, 1)})"
            elif weekday_avg > weekend_avg:
                weekend_vs_weekday_summary = f"Ngày thường đông hơn cuối tuần ({weekday_avg} so với {weekend_avg} lượt/ngày, chênh lệch +{round(weekday_avg - weekend_avg, 1)})"
            else:
                weekend_vs_weekday_summary = "Lưu lượng ngày thường và cuối tuần tương đương nhau"

            # 8. Camera comparison & rankings
            stmt_cams = select(
                CrossingEvent.camera_id,
                CrossingEvent.direction,
                func.count(CrossingEvent.id),
            ).where(and_(*base_filters)).group_by(CrossingEvent.camera_id, CrossingEvent.direction)

            cam_map: dict[str, dict[str, Any]] = {}
            for cid, o_dir, cnt in session.execute(stmt_cams).all():
                c_key = str(cid)
                if c_key not in cam_map:
                    cam_map[c_key] = {"camera_id": c_key, "camera_name": c_key, "in": 0, "out": 0, "total": 0}
                c = int(cnt)
                if o_dir == "in":
                    cam_map[c_key]["in"] += c
                else:
                    cam_map[c_key]["out"] += c
                cam_map[c_key]["total"] += c

            # Resolve camera names
            all_cams = session.scalars(select(Camera)).all()
            cam_name_dict = {c.name: c.name for c in all_cams}
            for c in all_cams:
                cam_name_dict[str(c.id)] = c.name
                if c.registry_key:
                    cam_name_dict[c.registry_key] = c.name

            for c_rec in cam_map.values():
                c_rec["camera_name"] = cam_name_dict.get(c_rec["camera_id"], c_rec["camera_id"])

            camera_rankings = sorted(cam_map.values(), key=lambda x: x["total"], reverse=True)
            busiest_camera = camera_rankings[0] if camera_rankings else None

            # 9. Period-over-period comparison
            comparison = None
            if compare_with:
                cw = compare_with.lower().strip()
                period_delta = end_utc - start_utc
                if cw in ("yesterday", "previous_day"):
                    shift = timedelta(days=1)
                elif cw in ("last_week", "previous_week"):
                    shift = timedelta(days=7)
                else:
                    shift = period_delta

                prev_start_utc = start_utc - shift
                prev_end_utc = end_utc - shift

                prev_filters = [
                    CrossingEvent.event_time >= prev_start_utc,
                    CrossingEvent.event_time <= prev_end_utc,
                ]
                if camera_id and camera_id.strip() and camera_id != "all":
                    prev_filters.append(CrossingEvent.camera_id == camera_id.strip())
                if object_type and object_type.strip() and object_type != "all":
                    prev_filters.append(CrossingEvent.object_type == object_type.strip())

                prev_count = session.scalar(select(func.count(CrossingEvent.id)).where(and_(*prev_filters))) or 0
                diff = total_passages - prev_count
                if prev_count > 0:
                    pct_change = round((diff / prev_count) * 100, 1)
                    trend = "tăng" if diff > 0 else ("giảm" if diff < 0 else "không đổi")
                else:
                    pct_change = None
                    trend = "không có dữ liệu mốc đối chứng (baseline = 0)"

                comparison = {
                    "baseline_label": f"Kỳ trước (lùi {shift.days} ngày)",
                    "baseline_total": prev_count,
                    "current_total": total_passages,
                    "difference": diff,
                    "percent_change": pct_change,
                    "trend_description": trend,
                }

            # 10. Data quality & coverage calculation
            # Calculate coverage from aggregate records or crossing activity
            stmt_agg = select(
                func.sum(AnalyticsAggregate.observed_seconds),
                func.sum(AnalyticsAggregate.expected_seconds),
                func.avg(AnalyticsAggregate.coverage_ratio),
            ).where(
                AnalyticsAggregate.bucket_start >= start_utc,
                AnalyticsAggregate.bucket_end <= end_utc,
            )
            if camera_id and camera_id.strip() and camera_id != "all":
                stmt_agg = stmt_agg.where(AnalyticsAggregate.camera_id == camera_id.strip())

            agg_res = session.execute(stmt_agg).first()
            obs_sec = float(agg_res[0] or 0.0) if agg_res else 0.0
            exp_sec = float(agg_res[1] or 0.0) if agg_res else 0.0
            avg_cov = float(agg_res[2] or 0.0) if agg_res and agg_res[2] is not None else 0.0

            if exp_sec > 0:
                coverage_ratio = min(1.0, round(obs_sec / exp_sec, 2))
            elif total_passages > 0:
                coverage_ratio = 1.0  # Passages exist throughout observed time
            else:
                coverage_ratio = 0.0

            if coverage_ratio >= 0.85:
                quality_status = "EXCELLENT"
            elif coverage_ratio >= 0.60:
                quality_status = "GOOD"
            elif coverage_ratio >= 0.30:
                quality_status = "PARTIAL"
            elif coverage_ratio > 0:
                quality_status = "LOW_COVERAGE"
            else:
                quality_status = "NO_DATA"

            avg_passages_per_hour = round(total_passages / duration_hours, 1)

            return {
                "status": "success",
                "time_range": label_ict,
                "timezone": "Asia/Ho_Chi_Minh (UTC+7)",
                "interval_utc": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
                "duration_hours": round(duration_hours, 1),
                "camera_filter": camera_id or "all_cameras",
                "zone_filter": zone_id or "all_zones",
                "object_type_filter": object_type or "all_objects",
                # Volume metrics
                "metrics": {
                    "total_passages": total_passages,
                    "person_passages": total_person,
                    "person_in": person_in,
                    "person_out": person_out,
                    "vehicle_passages": total_vehicle,
                    "vehicle_in": vehicle_in,
                    "vehicle_out": vehicle_out,
                    "net_flow": (person_in + vehicle_in) - (person_out + vehicle_out),
                    "average_per_hour": avg_passages_per_hour,
                    "peak_hour_slot": peak_hour_slot,
                    "peak_hour_passages": peak_hour_count,
                    "coverage_ratio": coverage_ratio,
                    "data_quality_status": quality_status,
                },
                # Detailed breakdowns
                "vehicle_type_breakdown": vehicle_breakdown,
                "hourly_distribution": hourly_distribution,
                "daily_distribution": daily_distribution,
                "weekday_comparison": weekday_comparison,
                "weekday_vs_weekend": {
                    "weekday_average_per_day": weekday_avg,
                    "weekend_average_per_day": weekend_avg,
                    "summary": weekend_vs_weekday_summary,
                },
                "camera_rankings": camera_rankings,
                "busiest_camera": busiest_camera,
                "comparison": comparison,
                "methodology_note": (
                    "Số liệu đo lường số lượt di chuyển thực tế (CrossingEvent) qua vạch đếm; "
                    "được phân loại hai chiều IN/OUT bằng tracking đa đối tượng ByteTrack."
                ),
            }

    def get_peak_traffic_hours(
        self,
        camera_id: str | None = None,
        zone_id: str | None = None,
        object_type: str | None = None,
        days_back: int = 14,
    ) -> dict[str, Any]:
        """Identify typical and recurring peak hours across historical observations."""
        now_local = get_local_now()
        start_local = (now_local - timedelta(days=days_back)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = now_local.astimezone(timezone.utc)

        analytics = self.get_historical_analytics(
            camera_id=camera_id,
            zone_id=zone_id,
            object_type=object_type,
            from_time=start_utc.isoformat(),
            to_time=end_utc.isoformat(),
            group_by="hour",
        )

        hourly = analytics.get("hourly_distribution", [])
        if not hourly or all(h["total"] == 0 for h in hourly):
            return {
                "status": "success",
                "camera_id": camera_id or "all_cameras",
                "has_data": False,
                "message": "Chưa có đủ dữ liệu lưu lượng trong khoảng thời gian yêu cầu để xác định giờ cao điểm.",
                "typical_peak_hours": [],
            }

        # Calculate mean and standard deviation across 24 hours
        totals = [h["total"] for h in hourly]
        mean_traffic = sum(totals) / 24.0
        variance = sum((x - mean_traffic) ** 2 for x in totals) / 24.0
        std_traffic = math.sqrt(variance)

        # Peak hours are hours where traffic >= mean + 0.75 * std
        peak_threshold = mean_traffic + 0.75 * std_traffic
        peak_slots = [
            h for h in hourly
            if h["total"] >= peak_threshold and h["total"] > 0
        ]
        peak_slots = sorted(peak_slots, key=lambda x: x["total"], reverse=True)

        return {
            "status": "success",
            "camera_id": camera_id or "all_cameras",
            "observation_days": days_back,
            "has_data": True,
            "mean_hourly_traffic": round(mean_traffic, 1),
            "peak_threshold": round(peak_threshold, 1),
            "typical_peak_hours": [
                {
                    "hour": p["hour"],
                    "hour_slot": p["hour_slot"],
                    "total_passages": p["total"],
                    "average_per_day": round(p["total"] / max(1, days_back), 1),
                    "intensity": "Rất cao" if p["total"] >= mean_traffic + 1.5 * std_traffic else "Cao",
                }
                for p in peak_slots
            ],
            "highest_hour": peak_slots[0]["hour_slot"] if peak_slots else "Chưa rõ",
        }
