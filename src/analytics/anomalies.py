"""Deterministic Historical Anomaly Detection Service for DATT.

Analyzes traffic aggregates (AnalyticsAggregate), camera availability, and alert frequencies
against comparable historical baselines (same hour of day and day of week across past weeks).
Detects:
- TRAFFIC_SPIKE
- TRAFFIC_DROP
- SUSTAINED_HIGH_TRAFFIC
- UNUSUAL_OFF_HOURS_ACTIVITY
- CAMERA_AVAILABILITY_ANOMALY
- ABNORMAL_ALERT_FREQUENCY
"""

from datetime import datetime, timezone, timedelta
import logging
import math
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, or_, and_, desc

from src.db.database import Database
from src.db.models import (
    AnalyticsAggregate,
    Camera,
    Notification,
    Zone,
)

logger = logging.getLogger("datt.analytics.anomalies")
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


def compute_median_and_mad(values: list[float]) -> tuple[float, float]:
    """Compute median and Median Absolute Deviation (MAD)."""
    if not values:
        return 0.0, 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    mid = n // 2
    if n % 2 == 1:
        median = sorted_v[mid]
    else:
        median = (sorted_v[mid - 1] + sorted_v[mid]) / 2.0

    abs_deviations = sorted(abs(x - median) for x in values)
    if n % 2 == 1:
        mad = abs_deviations[mid]
    else:
        mad = (abs_deviations[mid - 1] + abs_deviations[mid]) / 2.0

    return median, mad


class TrafficAnomalyDetector:
    """Service to detect operational and traffic anomalies with deterministic baselines."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def detect_anomalies(
        self,
        time_window_hours: int = 2,
        camera_id: str | None = None,
        zone_id: str | None = None,
        anomaly_types: list[str] | None = None,
        sensitivity: str = "normal",  # "low", "normal", "high"
    ) -> dict[str, Any]:
        """Detect anomalies across cameras/zones for the specified recent window."""
        window_hours = max(1, min(48, time_window_hours))
        now_utc = datetime.now(timezone.utc)
        window_start_utc = now_utc - timedelta(hours=window_hours)

        # Sensitivity thresholds
        sensitivity_map = {
            "low": {"mad_multiplier": 3.5, "min_pct_spike": 0.80, "min_delta": 20},
            "normal": {"mad_multiplier": 2.5, "min_pct_spike": 0.50, "min_delta": 10},
            "high": {"mad_multiplier": 1.8, "min_pct_spike": 0.30, "min_delta": 5},
        }
        params = sensitivity_map.get(sensitivity.lower(), sensitivity_map["normal"])

        enabled_types = set(
            t.upper()
            for t in (anomaly_types or [
                "TRAFFIC_SPIKE",
                "TRAFFIC_DROP",
                "SUSTAINED_HIGH_TRAFFIC",
                "UNUSUAL_OFF_HOURS_ACTIVITY",
                "CAMERA_AVAILABILITY_ANOMALY",
                "ABNORMAL_ALERT_FREQUENCY",
            ])
        )

        with self.db.transaction() as session:
            # 1. Fetch monitored cameras
            cam_query = select(Camera).where(Camera.enabled == True)
            if camera_id:
                clean_cid = camera_id.strip()
                try:
                    cuuid = UUID(clean_cid)
                    cam_query = cam_query.where(or_(Camera.id == cuuid, Camera.registry_key == clean_cid))
                except ValueError:
                    cam_query = cam_query.where(Camera.registry_key == clean_cid)
            cameras = session.scalars(cam_query).all()

            detected_anomalies: list[dict[str, Any]] = []

            for cam in cameras:
                cam_str_id = str(cam.id)
                cam_key = cam.registry_key or cam_str_id
                cam_name = cam.name or f"Camera {cam_str_id[:8]}"
                cam_location = cam.location or "Chưa cấu hình vị trí"

                # A. Query recent evaluation aggregates
                recent_stmt = (
                    select(AnalyticsAggregate)
                    .where(
                        or_(
                            AnalyticsAggregate.camera_id == cam_str_id,
                            AnalyticsAggregate.camera_id == cam_key,
                        )
                    )
                    .where(AnalyticsAggregate.bucket_start >= window_start_utc)
                    .where(AnalyticsAggregate.bucket_start <= now_utc)
                )
                if zone_id:
                    recent_stmt = recent_stmt.where(AnalyticsAggregate.zone_id == zone_id)
                recent_stmt = recent_stmt.order_by(AnalyticsAggregate.bucket_start.asc())
                recent_buckets = session.scalars(recent_stmt).all()

                # If no aggregates exist for this camera in the window, check camera availability
                if not recent_buckets:
                    if "CAMERA_AVAILABILITY_ANOMALY" in enabled_types:
                        # Check last_active
                        last_act = utc_timestamp(cam.last_active)
                        now_utc_val = datetime.now(timezone.utc)
                        is_offline = (
                            last_act is None
                            or (now_utc_val - last_act).total_seconds() > 600
                        )
                        if is_offline:
                            detected_anomalies.append({
                                "anomaly_type": "CAMERA_AVAILABILITY_ANOMALY",
                                "severity": "HIGH",
                                "camera_id": cam_key,
                                "camera_name": cam_name,
                                "camera_location": cam_location,
                                "metric_name": "camera_connectivity",
                                "observed_value": 0.0,
                                "expected_baseline": 1.0,
                                "deviation_absolute": -1.0,
                                "deviation_percent": -100.0,
                                "time_window_ict": f"{format_ict_time(window_start_utc)} - {format_ict_time(now_utc)}",
                                "explanation": (
                                    f"Camera {cam_name} ({cam_location}) không có dữ liệu phân tích và mất kết nối "
                                    f"(lần hoạt động cuối: {format_ict_time(last_act) if last_act else 'Chưa từng ghi nhận'})."
                                ),
                                "recommendation": "Kiểm tra nguồn video stream RTSP, mạng LAN và worker nhận diện.",
                                "supporting_ids": [str(cam.id)],
                            })
                    continue

                # B. Historical comparison for recent buckets
                # Query historical aggregates from past 28 days for same day-of-week and hours
                hist_start_utc = now_utc - timedelta(days=28)
                hist_stmt = (
                    select(AnalyticsAggregate)
                    .where(
                        or_(
                            AnalyticsAggregate.camera_id == cam_str_id,
                            AnalyticsAggregate.camera_id == cam_key,
                        )
                    )
                    .where(AnalyticsAggregate.bucket_start >= hist_start_utc)
                    .where(AnalyticsAggregate.bucket_start < window_start_utc)
                )
                if zone_id:
                    hist_stmt = hist_stmt.where(AnalyticsAggregate.zone_id == zone_id)
                historical_all = session.scalars(hist_stmt).all()

                # Group historical by (hour_of_day, is_weekend)
                historical_by_hour: dict[int, list[int]] = {}
                for h_agg in historical_all:
                    if h_agg.coverage_ratio < 0.40:
                        continue  # Exclude invalid/downtime buckets
                    h_dt_ict = utc_timestamp(h_agg.bucket_start).astimezone(LOCAL_TZ)
                    hour = h_dt_ict.hour
                    tot_traffic = (
                        (h_agg.vehicle_in_count or 0)
                        + (h_agg.vehicle_out_count or 0)
                        + (h_agg.person_in_count or 0)
                        + (h_agg.person_out_count or 0)
                    )
                    historical_by_hour.setdefault(hour, []).append(tot_traffic)

                # Check recent metrics
                total_observed_traffic = sum(
                    (b.vehicle_in_count or 0) + (b.vehicle_out_count or 0) + (b.person_in_count or 0) + (b.person_out_count or 0)
                    for b in recent_buckets
                )
                avg_coverage = sum(b.coverage_ratio for b in recent_buckets) / max(1, len(recent_buckets))

                # Compute expected baseline across recent hours
                baseline_samples: list[int] = []
                for b in recent_buckets:
                    b_hour = utc_timestamp(b.bucket_start).astimezone(LOCAL_TZ).hour
                    if b_hour in historical_by_hour:
                        baseline_samples.extend(historical_by_hour[b_hour])

                # If exact hour has no samples, fallback to all valid historical buckets for this camera
                if not baseline_samples and historical_all:
                    baseline_samples = [
                        ((h.vehicle_in_count or 0) + (h.vehicle_out_count or 0) + (h.person_in_count or 0) + (h.person_out_count or 0))
                        for h in historical_all if h.coverage_ratio >= 0.40
                    ]

                med_baseline, mad_baseline = compute_median_and_mad([float(x) for x in baseline_samples])
                expected_total_window = med_baseline * len(recent_buckets)
                mad_window = mad_baseline * math.sqrt(len(recent_buckets))

                delta = total_observed_traffic - expected_total_window
                pct_change = ((delta / expected_total_window) * 100.0) if expected_total_window > 0 else (100.0 if total_observed_traffic > 0 else 0.0)

                supporting_bucket_ids = [str(b.id) for b in recent_buckets]

                # Check: CAMERA_AVAILABILITY_ANOMALY
                if "CAMERA_AVAILABILITY_ANOMALY" in enabled_types and avg_coverage < 0.60:
                    detected_anomalies.append({
                        "anomaly_type": "CAMERA_AVAILABILITY_ANOMALY",
                        "severity": "HIGH" if avg_coverage < 0.30 else "MEDIUM",
                        "camera_id": cam_key,
                        "camera_name": cam_name,
                        "camera_location": cam_location,
                        "metric_name": "coverage_ratio",
                        "observed_value": round(avg_coverage, 2),
                        "expected_baseline": 1.0,
                        "deviation_absolute": round(avg_coverage - 1.0, 2),
                        "deviation_percent": round((avg_coverage - 1.0) * 100, 1),
                        "time_window_ict": f"{format_ict_time(window_start_utc)} - {format_ict_time(now_utc)}",
                        "explanation": (
                            f"Độ phủ dữ liệu (coverage ratio) của camera {cam_name} chỉ đạt {round(avg_coverage * 100, 1)}% "
                            f"trong {window_hours}h qua, thấp hơn ngưỡng an toàn 60%."
                        ),
                        "recommendation": "Kiểm tra tính liên tục của luồng video, độ trễ xử lý YOLO và kết nối mạng camera.",
                        "supporting_ids": supporting_bucket_ids[:5],
                    })

                # Check: TRAFFIC_SPIKE
                if "TRAFFIC_SPIKE" in enabled_types:
                    threshold_spike = expected_total_window + max(mad_window * params["mad_multiplier"], params["min_delta"])
                    if total_observed_traffic > threshold_spike and delta >= params["min_delta"]:
                        sev = "CRITICAL" if pct_change >= 100.0 and delta >= 30 else ("HIGH" if pct_change >= 50.0 else "MEDIUM")
                        detected_anomalies.append({
                            "anomaly_type": "TRAFFIC_SPIKE",
                            "severity": sev,
                            "camera_id": cam_key,
                            "camera_name": cam_name,
                            "camera_location": cam_location,
                            "metric_name": "traffic_volume",
                            "observed_value": total_observed_traffic,
                            "expected_baseline": round(expected_total_window, 1),
                            "deviation_absolute": round(delta, 1),
                            "deviation_percent": round(pct_change, 1) if expected_total_window > 0 else None,
                            "historical_sample_size": len(baseline_samples),
                            "time_window_ict": f"{format_ict_time(window_start_utc)} - {format_ict_time(now_utc)}",
                            "explanation": (
                                f"Camera {cam_name} ({cam_location}) ghi nhận lưu lượng {total_observed_traffic} lượt, "
                                f"cao hơn {round(pct_change, 1)}% so với mức trung bình lịch sử ({round(expected_total_window, 1)} lượt) "
                                f"của cùng khung giờ trong 4 tuần qua."
                            ),
                            "recommendation": "Kiểm tra xem có sự kiện tập trung đông người, ùn ứ giao thông hoặc phương tiện vào ra bất thường.",
                            "supporting_ids": supporting_bucket_ids[:5],
                        })

                # Check: TRAFFIC_DROP
                if "TRAFFIC_DROP" in enabled_types and expected_total_window >= 15.0:
                    threshold_drop = expected_total_window - max(mad_window * params["mad_multiplier"], params["min_delta"])
                    if total_observed_traffic < threshold_drop and delta <= -params["min_delta"]:
                        sev = "HIGH" if pct_change <= -70.0 else "MEDIUM"
                        detected_anomalies.append({
                            "anomaly_type": "TRAFFIC_DROP",
                            "severity": sev,
                            "camera_id": cam_key,
                            "camera_name": cam_name,
                            "camera_location": cam_location,
                            "metric_name": "traffic_volume",
                            "observed_value": total_observed_traffic,
                            "expected_baseline": round(expected_total_window, 1),
                            "deviation_absolute": round(delta, 1),
                            "deviation_percent": round(pct_change, 1),
                            "historical_sample_size": len(baseline_samples),
                            "time_window_ict": f"{format_ict_time(window_start_utc)} - {format_ict_time(now_utc)}",
                            "explanation": (
                                f"Lưu lượng tại {cam_name} giảm sâu {round(abs(pct_change), 1)}% "
                                f"(ghi nhận {total_observed_traffic} lượt so với kỳ vọng {round(expected_total_window, 1)} lượt)."
                            ),
                            "recommendation": "Kiểm tra camera có bị che khuất góc nhìn (lens obstruction) hoặc khu vực bị phong tỏa.",
                            "supporting_ids": supporting_bucket_ids[:5],
                        })

                # Check: UNUSUAL_OFF_HOURS_ACTIVITY
                if "UNUSUAL_OFF_HOURS_ACTIVITY" in enabled_types:
                    for b in recent_buckets:
                        b_dt_ict = utc_timestamp(b.bucket_start).astimezone(LOCAL_TZ)
                        if b_dt_ict.hour in (23, 0, 1, 2, 3, 4):
                            b_traffic = (b.vehicle_in_count or 0) + (b.vehicle_out_count or 0) + (b.person_in_count or 0) + (b.person_out_count or 0)
                            if b_traffic >= 5:  # Significant activity in midnight / early morning
                                detected_anomalies.append({
                                    "anomaly_type": "UNUSUAL_OFF_HOURS_ACTIVITY",
                                    "severity": "HIGH" if b_traffic >= 15 else "MEDIUM",
                                    "camera_id": cam_key,
                                    "camera_name": cam_name,
                                    "camera_location": cam_location,
                                    "metric_name": "off_hours_traffic",
                                    "observed_value": b_traffic,
                                    "expected_baseline": 0.0,
                                    "deviation_absolute": b_traffic,
                                    "deviation_percent": None,
                                    "time_window_ict": format_ict_time(b.bucket_start),
                                    "explanation": (
                                        f"Ghi nhận {b_traffic} lượt di chuyển trong khung giờ đêm/ngoài giờ hành chính "
                                        f"({format_ict_time(b.bucket_start)}) tại {cam_name}."
                                    ),
                                    "recommendation": "Kiểm tra xem có hoạt động an ninh trái phép hoặc xe hàng bốc dỡ ban đêm.",
                                    "supporting_ids": [str(b.id)],
                                })
                                break

                # Check: ABNORMAL_ALERT_FREQUENCY
                if "ABNORMAL_ALERT_FREQUENCY" in enabled_types:
                    alert_stmt = (
                        select(func.count(Notification.id))
                        .where(
                            or_(
                                Notification.camera_id == cam_str_id,
                                Notification.camera_id == cam_key,
                            )
                        )
                        .where(Notification.created_at >= window_start_utc)
                        .where(Notification.created_at <= now_utc)
                    )
                    alert_count = session.scalar(alert_stmt) or 0
                    if alert_count >= 5:  # High concentration of alerts
                        detected_anomalies.append({
                            "anomaly_type": "ABNORMAL_ALERT_FREQUENCY",
                            "severity": "CRITICAL" if alert_count >= 10 else "HIGH",
                            "camera_id": cam_key,
                            "camera_name": cam_name,
                            "camera_location": cam_location,
                            "metric_name": "alert_count",
                            "observed_value": alert_count,
                            "expected_baseline": 0.5,
                            "deviation_absolute": alert_count - 0.5,
                            "deviation_percent": None,
                            "time_window_ict": f"{format_ict_time(window_start_utc)} - {format_ict_time(now_utc)}",
                            "explanation": (
                                f"Phát hiện tần suất cảnh báo an ninh cao bất thường ({alert_count} cảnh báo) "
                                f"trong {window_hours}h qua tại {cam_name}."
                            ),
                            "recommendation": "Kiểm tra ngay Alert Center để xem các đối tượng trong Watchlist đang xuất hiện liên tục.",
                            "supporting_ids": [],
                        })

            # Sort detected anomalies by severity
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
            detected_anomalies.sort(key=lambda x: severity_order.get(x["severity"], 4))

            summary = {
                "evaluation_window_hours": window_hours,
                "evaluated_cameras": len(cameras),
                "total_anomalies": len(detected_anomalies),
                "critical_count": sum(1 for a in detected_anomalies if a["severity"] == "CRITICAL"),
                "high_count": sum(1 for a in detected_anomalies if a["severity"] == "HIGH"),
                "medium_count": sum(1 for a in detected_anomalies if a["severity"] == "MEDIUM"),
                "low_count": sum(1 for a in detected_anomalies if a["severity"] == "LOW"),
            }

            return {
                "status": "success",
                "summary": summary,
                "anomalies": detected_anomalies,
            }
