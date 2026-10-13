"""Unit tests for Tomorrow Forecasting Engine."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest

from src.db.database import Database
from src.db.models import CrossingEvent, Base
from src.analytics.forecasting import TomorrowForecastEngine, get_tomorrow_date_local, LOCAL_TZ


@pytest.fixture
def forecast_test_db(tmp_path):
    """Isolated SQLite database for forecast testing."""
    db_file = tmp_path / "forecast_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    db = Database(url=db_url)
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        db.dispose()


def test_tomorrow_date_calculation():
    d_str, w_idx, dt = get_tomorrow_date_local()
    assert len(d_str) == 10
    assert 0 <= w_idx <= 6
    assert dt.tzinfo is not None


def test_insufficient_data_returns_explicit_state_and_vietnamese_message(forecast_test_db):
    db = forecast_test_db
    engine = TomorrowForecastEngine(db=db)

    # Empty database for camera
    res = engine.forecast_tomorrow(camera_id="cam_empty_mall")
    assert res["data_quality_status"] == "INSUFFICIENT_DATA"
    assert "Chưa đủ dữ liệu lịch sử đáng tin cậy để dự báo lưu lượng ngày mai" in res["message"]
    assert res["historical_days_used"] == 0
    assert res["total_forecast"]["expected"] == 0
    assert len(res["hourly_forecasts"]) == 0


def test_weighted_forecasting_with_sufficient_data(forecast_test_db):
    db = forecast_test_db
    engine = TomorrowForecastEngine(db=db)

    # Generate 4 past weeks of matching weekday data
    d_str, target_weekday, tomorrow_dt = get_tomorrow_date_local()
    cam_id = "cam_gate_mall"

    with db.transaction() as session:
        for week_idx in range(1, 5):  # 1 week ago, 2 weeks ago, 3 weeks ago, 4 weeks ago
            past_date = tomorrow_dt.date() - timedelta(weeks=week_idx)
            # Seed 10 crossings at 17:00 ICT and 20 crossings at 18:00 ICT
            t_17 = datetime.combine(past_date, datetime.min.time(), tzinfo=LOCAL_TZ) + timedelta(hours=17, minutes=30)
            t_18 = datetime.combine(past_date, datetime.min.time(), tzinfo=LOCAL_TZ) + timedelta(hours=18, minutes=30)

            t_17_utc = t_17.astimezone(timezone.utc)
            t_18_utc = t_18.astimezone(timezone.utc)

            for i in range(10):
                session.add(CrossingEvent(
                    id=uuid4(), camera_id=cam_id, object_type="person", object_class="person",
                    direction="in", track_id=i, tracking_session_id=f"w{week_idx}",
                    event_time=t_17_utc, idempotency_key=f"ev_17_{week_idx}_{i}",
                ))
            for i in range(20):
                session.add(CrossingEvent(
                    id=uuid4(), camera_id=cam_id, object_type="person", object_class="person",
                    direction="in", track_id=i+100, tracking_session_id=f"w{week_idx}",
                    event_time=t_18_utc, idempotency_key=f"ev_18_{week_idx}_{i}",
                ))

    # Run forecast
    res = engine.forecast_tomorrow(camera_id=cam_id)
    assert res["status"] == "success"
    assert res["data_quality_status"] == "READY"
    assert res["historical_days_used"] == 4

    # Total forecast expected should be around 30 (10 + 20)
    exp_total = res["total_forecast"]["expected"]
    assert 28 <= exp_total <= 32
    assert res["total_forecast"]["lower_bound_80"] <= exp_total <= res["total_forecast"]["upper_bound_80"]

    # Hourly forecast
    hourly = res["hourly_forecasts"]
    assert len(hourly) == 24
    h17 = hourly[17]
    h18 = hourly[18]
    assert h17["expected_passages"] == 10
    assert h18["expected_passages"] == 20

    # Peak hour should be 18:00
    peaks = res["peak_hours"]
    assert len(peaks) > 0
    assert any(p["hour"] == 18 for p in peaks)

    # Backtesting metrics should be present and finite
    bm = res["backtest_metrics"]
    assert bm is not None
    assert bm["evaluation_method"] == "rolling_origin_chronological"
    assert bm["mae"] >= 0.0
    assert bm["wape_percent"] >= 0.0
