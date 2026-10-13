"""FastAPI Analytics and Tomorrow Forecasting Router for DATT.

Exposes REST endpoints for:
- Historical traffic analytics & comparisons
- Tomorrow traffic forecasts & peak hour predictions
- Predictive alerts & operational recommendations
- Camera analytics configuration (counting line, capacity)
- CSV export
"""

import csv
import io
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from sqlalchemy import select

from src.analytics.service import HistoricalAnalyticsService
from src.analytics.forecasting import TomorrowForecastEngine
from src.analytics.alerts import PredictiveAlertService
from src.db.database import Database
from src.db.models import Camera, CameraAnalyticsConfig, ForecastAlert, ForecastAlertRule
from src.db.repositories.analytics_repository import (
    CameraAnalyticsConfigRepository,
    ForecastAlertRepository,
    ForecastAlertRuleRepository,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
analytics_service = HistoricalAnalyticsService()
forecast_engine = TomorrowForecastEngine()
alert_service = PredictiveAlertService()


class CameraAnalyticsConfigUpdate(BaseModel):
    camera_id: str
    enabled: bool = True
    counting_line: dict[str, Any] | None = None
    in_direction: str = "normal"
    roi_polygon: list[list[float]] | None = None
    supported_classes: list[str] = Field(default_factory=lambda: ["person", "car", "motorcycle", "bus", "truck"])
    min_crossing_distance: float = 0.015
    hysteresis_frames: int = 2
    capacity: int | None = None


@router.get("/historical")
def get_historical_analytics(
    camera_id: str | None = Query(None, description="Camera ID or 'all'"),
    zone_id: str | None = Query(None, description="Zone ID"),
    object_type: str | None = Query(None, description="'person', 'vehicle', or 'all'"),
    vehicle_class: str | None = Query(None, description="'car', 'motorcycle', 'bus', 'truck'"),
    direction: str | None = Query(None, description="'in', 'out', or 'all'"),
    time_range: str | None = Query("7_days", description="Preset: 'today', 'yesterday', '7_days', '30_days', 'this_week', 'last_week'"),
    from_time: str | None = Query(None, description="Start ISO timestamp"),
    to_time: str | None = Query(None, description="End ISO timestamp"),
    group_by: str = Query("hour", description="'hour', 'day', 'weekday', 'camera', 'type'"),
    compare_with: str | None = Query("previous_period", description="'previous_period', 'yesterday', 'last_week'"),
):
    """Retrieve comprehensive historical traffic analytics."""
    try:
        data = analytics_service.get_historical_analytics(
            camera_id=camera_id,
            zone_id=zone_id,
            object_type=object_type,
            vehicle_class=vehicle_class,
            direction=direction,
            time_range=time_range,
            from_time=from_time,
            to_time=to_time,
            group_by=group_by,
            compare_with=compare_with,
        )
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@router.get("/peak_hours")
def get_peak_hours(
    camera_id: str | None = Query(None),
    zone_id: str | None = Query(None),
    object_type: str | None = Query(None),
    days_back: int = Query(14, ge=1, le=90),
):
    """Analyze recurring typical peak hours across historical observations."""
    try:
        data = analytics_service.get_peak_traffic_hours(
            camera_id=camera_id,
            zone_id=zone_id,
            object_type=object_type,
            days_back=days_back,
        )
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@router.get("/forecast")
def get_tomorrow_forecast(
    camera_id: str = Query(..., description="Camera ID to forecast"),
    target_date: str | None = Query(None, description="Target date YYYY-MM-DD (defaults to tomorrow)"),
    zone_id: str | None = Query(None),
    object_type: str | None = Query(None),
):
    """Generate statistical tomorrow traffic forecast with prediction intervals."""
    try:
        data = forecast_engine.forecast_tomorrow(
            camera_id=camera_id,
            target_date_str=target_date,
            zone_id=zone_id,
            object_type=object_type,
            save_to_db=True,
        )
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@router.post("/forecast/generate")
def generate_daily_forecasts():
    """Manually trigger daily forecast generation and predictive alert evaluation across all cameras."""
    try:
        data = alert_service.generate_all_tomorrow_forecasts_and_alerts()
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@router.get("/scheduler/status")
def get_scheduler_status():
    """Get background daily forecast scheduler status."""
    from src.analytics.scheduler import daily_forecast_scheduler
    return JSONResponse(daily_forecast_scheduler.get_status())


@router.post("/scheduler/trigger")
def trigger_scheduler_now():
    """Manually trigger immediate execution of scheduled forecast job."""
    from src.analytics.scheduler import daily_forecast_scheduler
    res = daily_forecast_scheduler.trigger_now()
    return JSONResponse(res)


@router.post("/scheduler/start")
def start_scheduler():
    """Start the daily forecast scheduler daemon worker."""
    from src.analytics.scheduler import daily_forecast_scheduler
    daily_forecast_scheduler.start()
    return JSONResponse({"status": "success", "message": "Scheduler started"})


@router.post("/scheduler/stop")
def stop_scheduler():
    """Stop the daily forecast scheduler daemon worker."""
    from src.analytics.scheduler import daily_forecast_scheduler
    daily_forecast_scheduler.stop()
    return JSONResponse({"status": "success", "message": "Scheduler stopped"})


@router.get("/alerts")
def get_forecast_alerts(
    camera_id: str | None = Query(None),
    target_date: str | None = Query(None),
    status: str | None = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    """Retrieve predictive alerts generated from tomorrow traffic forecasts."""
    db = alert_service.db
    try:
        with db.transaction() as session:
            repo = ForecastAlertRepository(session)
            offset = (page - 1) * page_size
            alerts = repo.query_alerts(
                camera_id=camera_id,
                target_date=target_date,
                status=status,
                limit=page_size,
                offset=offset,
            )

            # Resolve camera names
            cams = {str(c.id): c.name for c in session.scalars(select(Camera)).all()}

            results = []
            for a in alerts:
                results.append({
                    "id": str(a.id),
                    "camera_id": a.camera_id,
                    "camera_name": cams.get(a.camera_id, a.camera_id),
                    "alert_type": a.alert_type,
                    "severity": a.severity,
                    "target_date": a.target_date,
                    "peak_window": a.peak_window,
                    "expected_traffic": a.expected_traffic,
                    "threshold_value": a.threshold_value,
                    "recommendation": a.recommendation,
                    "delivery_status": a.delivery_status,
                    "recipient": a.recipient,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                })
            return JSONResponse({
                "status": "success",
                "alerts": results,
                "page": page,
                "page_size": page_size,
            })
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@router.get("/config")
def get_camera_config(camera_id: str = Query(...)):
    """Get camera analytics configuration (line coordinates, classes, capacity)."""
    db = alert_service.db
    try:
        with db.transaction() as session:
            repo = CameraAnalyticsConfigRepository(session)
            cfg = repo.get_by_camera_id(camera_id)
            if not cfg:
                # Default configuration
                return JSONResponse({
                    "camera_id": camera_id,
                    "enabled": True,
                    "counting_line": {"p1": [0.1, 0.5], "p2": [0.9, 0.5]},
                    "in_direction": "normal",
                    "roi_polygon": None,
                    "supported_classes": ["person", "car", "motorcycle", "bus", "truck"],
                    "min_crossing_distance": 0.015,
                    "hysteresis_frames": 2,
                    "capacity": None,
                })
            return JSONResponse({
                "id": str(cfg.id),
                "camera_id": cfg.camera_id,
                "enabled": cfg.enabled,
                "counting_line": cfg.counting_line or {"p1": [0.1, 0.5], "p2": [0.9, 0.5]},
                "in_direction": cfg.in_direction,
                "roi_polygon": cfg.roi_polygon,
                "supported_classes": cfg.supported_classes,
                "min_crossing_distance": cfg.min_crossing_distance,
                "hysteresis_frames": cfg.hysteresis_frames,
                "capacity": cfg.capacity,
            })
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@router.post("/config")
def update_camera_config(payload: CameraAnalyticsConfigUpdate):
    """Save or update camera analytics configuration."""
    db = alert_service.db
    try:
        with db.transaction() as session:
            repo = CameraAnalyticsConfigRepository(session)
            cfg = repo.upsert_config(
                camera_id=payload.camera_id,
                enabled=payload.enabled,
                counting_line=payload.counting_line,
                in_direction=payload.in_direction,
                roi_polygon=payload.roi_polygon,
                supported_classes=payload.supported_classes,
                min_crossing_distance=payload.min_crossing_distance,
                hysteresis_frames=payload.hysteresis_frames,
                capacity=payload.capacity,
            )
            # Synchronize live event manager counter if available
            try:
                from src.events.event_manager import event_manager
                p1 = tuple(payload.counting_line.get("p1", [0.1, 0.5])) if payload.counting_line else (0.1, 0.5)
                p2 = tuple(payload.counting_line.get("p2", [0.9, 0.5])) if payload.counting_line else (0.9, 0.5)
                roi = [tuple(pt) for pt in payload.roi_polygon] if payload.roi_polygon else None
                event_manager.configure_crossing_counter(
                    camera_id=payload.camera_id,
                    line_p1=p1,
                    line_p2=p2,
                    in_direction=payload.in_direction,
                    roi_polygon=roi,
                    supported_classes=payload.supported_classes,
                    min_crossing_distance=payload.min_crossing_distance,
                    hysteresis_frames=payload.hysteresis_frames,
                    enabled=payload.enabled,
                )
            except Exception:
                pass

            return JSONResponse({
                "status": "success",
                "message": f"Cấu hình phân tích cho camera {payload.camera_id} đã được lưu thành công.",
                "config": {
                    "camera_id": cfg.camera_id,
                    "enabled": cfg.enabled,
                    "counting_line": cfg.counting_line,
                    "capacity": cfg.capacity,
                },
            })
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


@router.get("/export")
def export_historical_csv(
    camera_id: str | None = Query(None),
    time_range: str | None = Query("7_days"),
    from_time: str | None = Query(None),
    to_time: str | None = Query(None),
):
    """Export historical traffic statistics to CSV."""
    data = analytics_service.get_historical_analytics(
        camera_id=camera_id,
        time_range=time_range,
        from_time=from_time,
        to_time=to_time,
        group_by="hour",
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Khung_gio", "Tong_luot", "Luot_vao", "Luot_ra"])

    for h in data.get("hourly_distribution", []):
        writer.writerow([h["hour_slot"], h["total"], h["in"], h["out"]])

    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=traffic_analytics_{time_range}.csv"},
    )
