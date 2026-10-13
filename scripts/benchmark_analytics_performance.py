"""Benchmark script for DATT Analytics & Forecasting Subsystem.

Measures:
1. LineCrossingCounter per-frame latency (Analytics Enabled vs Disabled).
2. Database worker enqueue latency (zero-I/O asynchronous contract).
3. Historical aggregation query latency.
4. Tomorrow forecast generation latency.
5. Predictive alert evaluation latency.
6. Memory usage and estimated FPS impact.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import tracemalloc
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from src.counter.line_crossing import LineCrossingCounter
from src.analytics.service import HistoricalAnalyticsService
from src.analytics.forecasting import TomorrowForecastEngine
from src.analytics.alerts import PredictiveAlertService
from src.db.database import Database
from src.db.models import Base, CrossingEvent, CameraAnalyticsConfig, TrafficForecast, ForecastAlertRule, ForecastAlert
from src.events.event_manager import EventManager
from src.events.db_worker import DatabaseWorker
from unittest.mock import MagicMock


def benchmark_line_crossing():
    print("--- 1. LineCrossingCounter Throughput & Overhead ---")
    counter = LineCrossingCounter(
        camera_id="cam_bench",
        line_p1=(0.1, 0.5),
        line_p2=(0.9, 0.5),
        in_direction="normal",
        hysteresis_frames=2,
        cooldown_seconds=3.0,
        enabled=True,
    )
    disabled_counter = LineCrossingCounter(
        camera_id="cam_bench",
        enabled=False,
    )

    num_frames = 1000
    num_tracks = 30  # typical busy frame

    # Create mock detections for 30 tracks
    tracks = MagicMock()
    tracks.tracker_id = list(range(1, num_tracks + 1))
    tracks.class_id = [0] * num_tracks  # 0 is person
    tracks.confidence = [0.9] * num_tracks
    # Pixel coordinates for 1920x1080 frame
    boxes = []
    for i in range(num_tracks):
        x = int(300 + (i * 40) % 1200)
        y = 500
        boxes.append([x, y, x + 50, y + 100])
    tracks.xyxy = boxes

    # Benchmark Disabled
    t0 = time.perf_counter()
    for f in range(num_frames):
        disabled_counter.update(tracks, frame_shape=(1080, 1920, 3), current_time=f * 0.033)
    t_disabled = (time.perf_counter() - t0) * 1000.0 / num_frames

    # Benchmark Enabled
    t0 = time.perf_counter()
    for f in range(num_frames):
        # Shift boxes across the line
        for b in tracks.xyxy:
            b[1] += 1
            b[3] += 1
        counter.update(tracks, frame_shape=(1080, 1920, 3), current_time=f * 0.033)
    t_enabled = (time.perf_counter() - t0) * 1000.0 / num_frames

    print(f"Disabled Counter Latency per frame: {t_disabled:.4f} ms")
    print(f"Enabled Counter Latency per frame (30 tracks): {t_enabled:.4f} ms")
    print(f"Incremental Analytics Overhead per frame: {t_enabled - t_disabled:.4f} ms")
    print(f"Theoretical Max Counter FPS: {1000.0 / max(t_enabled, 0.0001):.1f} FPS")


def benchmark_async_worker():
    print("\n--- 2. Realtime Asynchronous DB Enqueue Latency ---")
    worker = DatabaseWorker(db_url="sqlite:///:memory:")
    em = EventManager(db_worker=worker)

    tracks = MagicMock()
    tracks.tracker_id = [1, 2, 3, 4, 5]
    tracks.xyxy = [[10, 10, 100, 100]] * 5
    tracks.class_id = [2] * 5
    tracks.confidence = [0.9] * 5

    t0 = time.perf_counter()
    trials = 500
    for _ in range(trials):
        em.process_crossings("cam_test", [
            {
                "track_id": 1,
                "direction": "IN",
                "object_type": "person",
                "object_class": "person",
                "timestamp": time.time(),
                "midpoint": (0.5, 0.5),
            }
        ])
    avg_enqueue_ms = ((time.perf_counter() - t0) * 1000.0) / trials
    print(f"EventManager.process_crossings average enqueue time: {avg_enqueue_ms:.4f} ms")
    print(f"Zero synchronous DB blocking confirmed: {'PASS' if avg_enqueue_ms < 1.0 else 'FAIL'}")
    worker.stop(timeout=1.0)


def benchmark_forecasting_and_analytics():
    print("\n--- 3. Analytics Aggregation & Forecasting Latency ---")
    db = Database("sqlite:///:memory:")
    Base.metadata.create_all(db.engine)

    # Seed 14 days of hourly data (336 events)
    base_time = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
    with db.transaction() as session:
        for d in range(14):
            for h in range(24):
                evt_time = base_time + timedelta(days=d, hours=h, minutes=15)
                # Traffic curve peaking at 17:00
                count = 10 + int(30 * (1.0 if 16 <= h <= 19 else 0.2))
                for c in range(count):
                    session.add(CrossingEvent(
                        id=uuid4(),
                        camera_id="cam_mall_entrance",
                        object_type="person",
                        object_class="person",
                        direction="IN" if c % 2 == 0 else "OUT",
                        track_id=c + 1,
                        tracking_session_id=f"sess_{d}_{h}_{c}",
                        event_time=evt_time,
                        source_type="LIVE",
                        idempotency_key=f"cam_mall_entrance:sess_{d}_{h}_{c}",
                    ))

    analytics_svc = HistoricalAnalyticsService(db=db)
    forecast_engine = TomorrowForecastEngine(db=db)
    alert_svc = PredictiveAlertService(db=db)

    # Benchmark Historical Analytics
    t0 = time.perf_counter()
    hist_result = analytics_svc.get_historical_analytics(
        camera_id="cam_mall_entrance",
        from_time="2026-10-01T00:00:00",
        to_time="2026-10-14T23:59:59",
    )
    t_hist = (time.perf_counter() - t0) * 1000.0
    print(f"Historical Aggregation Latency (14 days, {hist_result['metrics']['total_passages']} passages): {t_hist:.2f} ms")

    # Benchmark Tomorrow Forecast
    t0 = time.perf_counter()
    fc_result = forecast_engine.forecast_tomorrow(
        camera_id="cam_mall_entrance",
        target_date_str="2026-10-15",
        save_to_db=False,
    )
    t_fc = (time.perf_counter() - t0) * 1000.0
    print(f"Tomorrow Forecast Generation Latency: {t_fc:.2f} ms (Status: {fc_result.get('data_quality_status')})")

    # Benchmark Alert Evaluation
    t0 = time.perf_counter()
    alerts = alert_svc.evaluate_forecast_alerts(
        camera_id="cam_mall_entrance",
        target_date_str="2026-10-15",
    )
    t_alert = (time.perf_counter() - t0) * 1000.0
    print(f"Predictive Alert Evaluation Latency: {t_alert:.2f} ms (Alerts generated: {len(alerts)})")


if __name__ == "__main__":
    tracemalloc.start()
    benchmark_line_crossing()
    benchmark_async_worker()
    benchmark_forecasting_and_analytics()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"\nMemory Usage: Current: {current / 1024 / 1024:.2f} MB, Peak: {peak / 1024 / 1024:.2f} MB")
