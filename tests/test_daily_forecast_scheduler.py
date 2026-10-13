"""Integration tests for DailyForecastScheduler and scheduler endpoints."""

import time
import pytest
from starlette.testclient import TestClient

from src.db.database import Database
from src.db.models import Camera, Base
from src.analytics.scheduler import DailyForecastScheduler
from src.ui.web_server import app


@pytest.fixture
def scheduler_test_db(tmp_path):
    db_file = tmp_path / "scheduler_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    db = Database(url=db_url)
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        db.dispose()


def test_daily_forecast_scheduler_lifecycle_and_trigger(scheduler_test_db):
    db = scheduler_test_db

    # Seed 1 active camera
    with db.transaction() as session:
        cam = Camera(name="Cổng chính", source_type="live", source="cam1", enabled=True)
        session.add(cam)

    scheduler = DailyForecastScheduler(db=db, target_hour_ict=18)

    # 1. Initial status
    status = scheduler.get_status()
    assert status["running"] is False
    assert status["target_hour_ict"] == 18
    assert status["has_run_today"] is False

    # 2. Start scheduler worker
    scheduler.start()
    assert scheduler.get_status()["running"] is True

    # 3. Duplicate start is safe
    scheduler.start()
    assert scheduler.get_status()["running"] is True

    # 4. Trigger on-demand job execution
    res = scheduler.trigger_now()
    assert res["status"] == "success"
    assert res["cameras_processed"] >= 1
    assert scheduler.last_run_date is not None
    assert scheduler.last_run_time is not None

    status_after = scheduler.get_status()
    assert status_after["last_cameras_processed"] >= 1

    # 5. Stop worker
    scheduler.stop(timeout=2.0)
    assert scheduler.get_status()["running"] is False


def test_scheduler_api_endpoints():
    client = TestClient(app)

    # GET /api/analytics/scheduler/status
    res = client.get("/api/analytics/scheduler/status")
    assert res.status_code == 200
    data = res.json()
    assert "target_hour_ict" in data
    assert "running" in data
    assert "today_date_ict" in data

    # POST /api/analytics/scheduler/trigger
    res_trig = client.post("/api/analytics/scheduler/trigger")
    assert res_trig.status_code == 200
    trig_data = res_trig.json()
    assert trig_data.get("status") in ("success", "warning")
