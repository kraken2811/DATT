"""Unit tests for Predictive Alerts Engine."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest

from src.db.database import Database
from src.db.models import (
    Base,
    Camera,
    CameraAnalyticsConfig,
    ForecastAlertRule,
    ForecastAlert,
    CrossingEvent,
)
from src.analytics.alerts import PredictiveAlertService
from src.analytics.forecasting import get_tomorrow_date_local, LOCAL_TZ


@pytest.fixture
def alert_test_db(tmp_path):
    """Isolated SQLite database for predictive alerts testing."""
    db_file = tmp_path / "alerts_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    db = Database(url=db_url)
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        db.dispose()


def test_insufficient_data_emits_info_alert(alert_test_db):
    db = alert_test_db
    svc = PredictiveAlertService(db=db)

    # Empty camera
    alerts = svc.evaluate_forecast_alerts(camera_id="cam_new")
    assert len(alerts) == 1
    a = alerts[0]
    assert a["alert_type"] == "FORECAST_DATA_INSUFFICIENT"
    assert a["severity"] == "INFO"
    assert "Thu thập thêm dữ liệu" in a["recommendation"]


def test_high_traffic_and_capacity_risk_alerts(alert_test_db):
    db = alert_test_db
    svc = PredictiveAlertService(db=db)

    cam_id = "cam_parking_gate"
    d_str, target_weekday, tomorrow_dt = get_tomorrow_date_local()

    with db.transaction() as session:
        # Camera
        cam = Camera(id=uuid4(), name="Cổng Bãi Xe A", registry_key=cam_id, source_type="live", source="rtsp://")
        session.add(cam)

        # Config with capacity = 100 vehicles
        cfg = CameraAnalyticsConfig(
            id=uuid4(), camera_id=cam_id, enabled=True, capacity=100
        )
        session.add(cfg)

        # Alert rule: peak threshold = 50, high daily threshold = 100, capacity ratio = 0.80 (80 vehicles)
        rule = ForecastAlertRule(
            id=uuid4(),
            camera_id=cam_id,
            enabled=True,
            peak_traffic_threshold=50,
            high_traffic_threshold=100,
            capacity_threshold_ratio=0.80,
            recipient_emails=["admin@datt.ai"],
        )
        session.add(rule)

        # Seed 4 weeks of high traffic: 90 vehicles entering at 17:00 ICT each week
        for w in range(1, 5):
            past_date = tomorrow_dt.date() - timedelta(weeks=w)
            t_17_local = datetime.combine(past_date, datetime.min.time(), tzinfo=LOCAL_TZ) + timedelta(hours=17, minutes=15)
            t_17_utc = t_17_local.astimezone(timezone.utc)

            for i in range(90):
                session.add(CrossingEvent(
                    id=uuid4(), camera_id=cam_id, object_type="vehicle", object_class="car",
                    direction="in", track_id=i, tracking_session_id=f"sess_{w}",
                    event_time=t_17_utc, idempotency_key=f"veh_{w}_{i}",
                ))

    # Evaluate alerts
    alerts = svc.evaluate_forecast_alerts(camera_id=cam_id)
    assert len(alerts) >= 2

    alert_types = [a["alert_type"] for a in alerts]
    assert "EXPECTED_PEAK_TRAFFIC" in alert_types
    assert "EXPECTED_CAPACITY_RISK" in alert_types

    # Find capacity alert
    cap_alert = next(a for a in alerts if a["alert_type"] == "EXPECTED_CAPACITY_RISK")
    assert cap_alert["severity"] == "CRITICAL"
    assert "nguy cơ quá tải" in cap_alert["recommendation"]

    # Verify idempotency: running evaluation again updates existing alert without duplicates
    alerts_round2 = svc.evaluate_forecast_alerts(camera_id=cam_id)
    with db.transaction() as session:
        from sqlalchemy import select, func
        total_in_db = session.scalar(select(func.count(ForecastAlert.id)).where(ForecastAlert.camera_id == cam_id))
        assert total_in_db == len(alerts)  # Idempotent!
