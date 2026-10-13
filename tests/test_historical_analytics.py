"""Unit and integration tests for Historical Analytics Engine."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest

from src.db.database import Database
from src.db.models import CrossingEvent, AnalyticsAggregate, Camera
from src.analytics.service import HistoricalAnalyticsService, parse_analytics_time_bounds, LOCAL_TZ


@pytest.fixture
def analytics_test_db(tmp_path):
    """Isolated SQLite database with analytics tables for testing."""
    db_file = tmp_path / "analytics_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    db = Database(url=db_url)
    from src.db.models import Base
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        db.dispose()


def test_time_bounds_parsing():
    start_utc, end_utc, label = parse_analytics_time_bounds("today")
    assert "Hôm nay" in label
    assert start_utc <= end_utc

    start_7d, end_7d, label_7d = parse_analytics_time_bounds("7_days")
    assert "7 ngày" in label_7d
    assert (end_7d - start_7d).days >= 6


def test_historical_aggregation_and_breakdowns(analytics_test_db):
    db = analytics_test_db
    svc = HistoricalAnalyticsService(db=db)

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(LOCAL_TZ)

    # Seed crossing events across 2 cameras and different hours
    with db.transaction() as session:
        # Camera 1
        cam1 = Camera(id=uuid4(), name="Cổng chính Mall", source_type="live", source="cam1")
        session.add(cam1)
        # Camera 2
        cam2 = Camera(id=uuid4(), name="Cổng Bãi xe", source_type="live", source="cam2")
        session.add(cam2)
        session.flush()

        cam1_id = str(cam1.id)
        cam2_id = str(cam2.id)

        # 5 people entering Cam 1 at 08:15 ICT
        time_8h = now_local.replace(hour=8, minute=15, second=0).astimezone(timezone.utc)
        for i in range(5):
            session.add(CrossingEvent(
                id=uuid4(), camera_id=cam1_id, object_type="person", object_class="person",
                direction="in", track_id=i, tracking_session_id="s1", event_time=time_8h,
                idempotency_key=f"c1_{i}",
            ))

        # 3 people exiting Cam 1 at 09:20 ICT
        time_9h = now_local.replace(hour=9, minute=20, second=0).astimezone(timezone.utc)
        for i in range(3):
            session.add(CrossingEvent(
                id=uuid4(), camera_id=cam1_id, object_type="person", object_class="person",
                direction="out", track_id=i+10, tracking_session_id="s1", event_time=time_9h,
                idempotency_key=f"c1_out_{i}",
            ))

        # 8 cars entering Cam 2 at 11:30 ICT (peak hour)
        time_11h = now_local.replace(hour=11, minute=30, second=0).astimezone(timezone.utc)
        for i in range(8):
            session.add(CrossingEvent(
                id=uuid4(), camera_id=cam2_id, object_type="vehicle", object_class="car",
                direction="in", track_id=i+20, tracking_session_id="s2", event_time=time_11h,
                idempotency_key=f"c2_{i}",
            ))

    # Query historical analytics for today
    res = svc.get_historical_analytics(time_range="today")
    assert res["status"] == "success"
    metrics = res["metrics"]
    assert metrics["total_passages"] == 16
    assert metrics["person_passages"] == 8
    assert metrics["person_in"] == 5
    assert metrics["person_out"] == 3
    assert metrics["vehicle_passages"] == 8
    assert metrics["vehicle_in"] == 8
    assert metrics["net_flow"] == (5 + 8) - 3  # 10 net flow

    # Verify peak hour detection
    assert "11:00 - 12:00" in metrics["peak_hour_slot"]
    assert metrics["peak_hour_passages"] == 8

    # Verify camera rankings
    rankings = res["camera_rankings"]
    assert len(rankings) == 2
    # Cam 1 (8) and Cam 2 (8)
    assert sum(r["total"] for r in rankings) == 16


def test_comparison_zero_baseline_safety(analytics_test_db):
    db = analytics_test_db
    svc = HistoricalAnalyticsService(db=db)

    # Empty baseline should not raise ZeroDivisionError
    res = svc.get_historical_analytics(time_range="today", compare_with="yesterday")
    comp = res["comparison"]
    assert comp is not None
    assert comp["difference"] == 0
    assert comp["percent_change"] is None
    assert "không có dữ liệu mốc đối chứng" in comp["trend_description"]


def test_peak_hours_analysis(analytics_test_db):
    db = analytics_test_db
    svc = HistoricalAnalyticsService(db=db)

    # When no data exists
    res = svc.get_peak_traffic_hours(camera_id="cam_empty", days_back=7)
    assert res["has_data"] is False
    assert len(res["typical_peak_hours"]) == 0
