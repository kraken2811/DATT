"""Predictive Alert Engine for DATT.

Evaluates tomorrow traffic forecasts against configured alert rules.
Generates advance operational warnings (EXPECTED_PEAK_TRAFFIC, EXPECTED_HIGH_TRAFFIC,
EXPECTED_CAPACITY_RISK, FORECAST_DATA_INSUFFICIENT) with data-grounded recommendations.
Integrates with Alert Center and optional Email notifications.
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, and_

from src.db.database import Database
from src.db.models import (
    Camera,
    CameraAnalyticsConfig,
    ForecastAlertRule,
    ForecastAlert,
    TrafficForecast,
)
from src.analytics.forecasting import TomorrowForecastEngine, get_tomorrow_date_local

logger = logging.getLogger("datt.analytics.alerts")
LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh (UTC+7)


class PredictiveAlertService:
    """Service to evaluate forecast rules, generate advance warnings, and persist alerts."""

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        self.forecast_engine = TomorrowForecastEngine(db=self.db)

    def evaluate_forecast_alerts(
        self,
        camera_id: str,
        target_date_str: str | None = None,
        zone_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate tomorrow forecast for a camera and trigger alerts if thresholds exceeded."""
        forecast = self.forecast_engine.forecast_tomorrow(
            camera_id=camera_id,
            target_date_str=target_date_str,
            zone_id=zone_id,
            save_to_db=True,
        )

        target_date = forecast["target_date"]
        weekday_name = forecast["weekday_name"]
        quality_status = forecast.get("data_quality_status", "UNKNOWN")

        with self.db.transaction() as session:
            # 1. Fetch camera configuration and alert rules
            cam_rec = None
            try:
                cam_rec = session.get(Camera, UUID(str(camera_id)))
            except (ValueError, TypeError, AttributeError):
                pass
            if not cam_rec:
                cam_rec = session.scalar(select(Camera).where(Camera.registry_key == str(camera_id)))
            camera_name = cam_rec.name if cam_rec else str(camera_id)

            config = session.scalar(
                select(CameraAnalyticsConfig).where(CameraAnalyticsConfig.camera_id == camera_id)
            )
            capacity = config.capacity if config else None

            rules = list(
                session.scalars(
                    select(ForecastAlertRule).where(
                        ForecastAlertRule.enabled.is_(True),
                        (ForecastAlertRule.camera_id == camera_id) | (ForecastAlertRule.camera_id.is_(None)),
                    )
                ).all()
            )

            # Default fallback rule if none configured
            if not rules:
                default_rule = ForecastAlertRule(
                    id=uuid4(),
                    camera_id=camera_id,
                    high_traffic_threshold=250,
                    peak_traffic_threshold=100,
                    capacity_threshold_ratio=0.85,
                    recipient_emails=[],
                )
                rules = [default_rule]

            generated_alerts: list[dict[str, Any]] = []

            # 2. Case A: Insufficient or Stale Data Alert
            if quality_status in ("INSUFFICIENT_DATA", "STALE_DATA"):
                rule = rules[0]
                rec = "Thu thập thêm dữ liệu camera liên tục để hệ thống kích hoạt tính năng dự báo tự động."
                alert = self._persist_alert(
                    session=session,
                    camera_id=camera_id,
                    zone_id=zone_id,
                    alert_type="FORECAST_DATA_INSUFFICIENT",
                    severity="INFO",
                    target_date=target_date,
                    peak_window=None,
                    expected_traffic={"status": quality_status},
                    threshold_value=None,
                    recommendation=rec,
                    recipient=rule.recipient_emails[0] if rule.recipient_emails else None,
                )
                if alert:
                    generated_alerts.append(alert)
                return generated_alerts

            # 3. Case B: Peak Traffic and High Traffic Rules
            hourly = forecast.get("hourly_forecasts", [])
            peak_hours = forecast.get("peak_hours", [])
            total_exp = forecast.get("total_forecast", {}).get("expected", 0)

            # Find maximum expected single-hour traffic
            max_hour_item = max(hourly, key=lambda x: x["expected_passages"]) if hourly else None
            max_hour_traffic = max_hour_item["expected_passages"] if max_hour_item else 0
            max_hour_slot = max_hour_item["hour_slot"] if max_hour_item else "Chưa rõ"

            for rule in rules:
                # Check Peak Traffic Threshold
                if max_hour_traffic >= rule.peak_traffic_threshold:
                    peak_range_str = (
                        f"{peak_hours[0]['hour_slot']} (dự kiến {peak_hours[0]['range_80']} lượt)"
                        if peak_hours
                        else max_hour_slot
                    )
                    rec = (
                        f"Lưu lượng dự kiến đạt đỉnh {max_hour_traffic} lượt tại khung {max_hour_slot}. "
                        f"Đề xuất tăng cường nhân sự điều tiết tại khu vực {camera_name} trước giờ cao điểm."
                    )
                    alert = self._persist_alert(
                        session=session,
                        camera_id=camera_id,
                        zone_id=zone_id,
                        alert_type="EXPECTED_PEAK_TRAFFIC",
                        severity="HIGH",
                        target_date=target_date,
                        peak_window=max_hour_slot,
                        expected_traffic={
                            "max_hour_traffic": max_hour_traffic,
                            "hour_slot": max_hour_slot,
                            "interval_80": max_hour_item["prediction_interval_80"] if max_hour_item else {},
                        },
                        threshold_value=float(rule.peak_traffic_threshold),
                        recommendation=rec,
                        recipient=rule.recipient_emails[0] if rule.recipient_emails else None,
                    )
                    if alert:
                        generated_alerts.append(alert)

                # Check High Daily Traffic Threshold
                if total_exp >= rule.high_traffic_threshold:
                    rec = (
                        f"Tổng lưu lượng ngày mai ({weekday_name}) dự kiến đạt {total_exp} lượt, "
                        f"vượt ngưỡng cảnh báo {rule.high_traffic_threshold}. Cần chủ động kế hoạch vận hành."
                    )
                    alert = self._persist_alert(
                        session=session,
                        camera_id=camera_id,
                        zone_id=zone_id,
                        alert_type="EXPECTED_HIGH_TRAFFIC",
                        severity="MEDIUM",
                        target_date=target_date,
                        peak_window=max_hour_slot,
                        expected_traffic=forecast.get("total_forecast", {}),
                        threshold_value=float(rule.high_traffic_threshold),
                        recommendation=rec,
                        recipient=rule.recipient_emails[0] if rule.recipient_emails else None,
                    )
                    if alert:
                        generated_alerts.append(alert)

                # Check Capacity Risk (ONLY if verified capacity is defined!)
                if capacity and capacity > 0:
                    cap_threshold = capacity * rule.capacity_threshold_ratio
                    # Compute expected peak net accumulation (or peak influx)
                    if max_hour_traffic >= cap_threshold:
                        rec = (
                            f"Lưu lượng dự kiến {max_hour_traffic} đạt {round((max_hour_traffic/capacity)*100)}% "
                            f"sức chứa thiết kế ({capacity} chỗ) tại {camera_name}. "
                            f"Có nguy cơ quá tải bãi đỗ/khu vực; cần chuẩn bị biển báo và hướng dẫn luồng xe."
                        )
                        alert = self._persist_alert(
                            session=session,
                            camera_id=camera_id,
                            zone_id=zone_id,
                            alert_type="EXPECTED_CAPACITY_RISK",
                            severity="CRITICAL",
                            target_date=target_date,
                            peak_window=max_hour_slot,
                            expected_traffic={"max_hour": max_hour_traffic, "capacity": capacity},
                            threshold_value=float(cap_threshold),
                            recommendation=rec,
                            recipient=rule.recipient_emails[0] if rule.recipient_emails else None,
                        )
                        if alert:
                            generated_alerts.append(alert)

            return generated_alerts

    def _persist_alert(
        self,
        session: Any,
        camera_id: str,
        zone_id: str | None,
        alert_type: str,
        severity: str,
        target_date: str,
        peak_window: str | None,
        expected_traffic: dict[str, Any] | None,
        threshold_value: float | None,
        recommendation: str | None,
        recipient: str | None,
    ) -> dict[str, Any] | None:
        """Persist alert idempotently: one alert per camera, target_date, and alert_type."""
        existing = session.scalar(
            select(ForecastAlert).where(
                ForecastAlert.camera_id == camera_id,
                ForecastAlert.target_date == target_date,
                ForecastAlert.alert_type == alert_type,
            )
        )
        if existing:
            # Update existing alert with latest metrics
            existing.severity = severity
            existing.peak_window = peak_window
            existing.expected_traffic = expected_traffic or {}
            existing.threshold_value = threshold_value
            existing.recommendation = recommendation
            session.flush()
            return {
                "id": str(existing.id),
                "camera_id": camera_id,
                "alert_type": alert_type,
                "severity": severity,
                "target_date": target_date,
                "peak_window": peak_window,
                "recommendation": recommendation,
                "delivery_status": existing.delivery_status,
                "is_new": False,
            }

        new_alert = ForecastAlert(
            id=uuid4(),
            camera_id=camera_id,
            zone_id=zone_id,
            alert_type=alert_type,
            severity=severity,
            target_date=target_date,
            peak_window=peak_window,
            expected_traffic=expected_traffic or {},
            threshold_value=threshold_value,
            recommendation=recommendation,
            delivery_status="pending",
            recipient=recipient,
            created_at=datetime.now(timezone.utc),
        )
        session.add(new_alert)
        session.flush()
        return {
            "id": str(new_alert.id),
            "camera_id": camera_id,
            "alert_type": alert_type,
            "severity": severity,
            "target_date": target_date,
            "peak_window": peak_window,
            "recommendation": recommendation,
            "delivery_status": "pending",
            "is_new": True,
        }

    def generate_all_tomorrow_forecasts_and_alerts(self) -> dict[str, Any]:
        """Scheduled daily workflow (run at 18:00 ICT) across all enabled cameras."""
        target_date, weekday_idx, _ = get_tomorrow_date_local()
        with self.db.transaction() as session:
            cameras = list(session.scalars(select(Camera).where(Camera.enabled.is_(True))).all())

        all_alerts = []
        processed_cameras = []
        for cam in cameras:
            cid = str(cam.id)
            processed_cameras.append(cam.name)
            alerts = self.evaluate_forecast_alerts(camera_id=cid, target_date_str=target_date)
            all_alerts.extend(alerts)

        return {
            "status": "success",
            "target_date": target_date,
            "cameras_processed": len(processed_cameras),
            "camera_names": processed_cameras,
            "total_alerts_generated": len(all_alerts),
            "alerts": all_alerts,
        }
