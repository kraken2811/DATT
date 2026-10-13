"""Unit and integration tests for Traffic and Operational Anomaly Detection Service."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest

from src.db.database import Database
from src.db.models import (
    Base,
    Camera,
    AnalyticsAggregate,
    Notification,
)
from src.analytics.anomalies import TrafficAnomalyDetector


@pytest.fixture
def anomaly_test_db(tmp_path):
    """Isolated SQLite database for anomaly detection engine tests."""
    db_file = tmp_path / "anomaly_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    db = Database(url=db_url)
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        db.dispose()


def test_normal_traffic_no_anomalies(anomaly_test_db):
    """When recent traffic matches historical baseline, 0 anomalies should be reported."""
    db = anomaly_test_db
    now_utc = datetime.now(timezone.utc)
    detector = TrafficAnomalyDetector(db=db)

    with db.transaction() as session:
        cam = Camera(id=uuid4(), registry_key="cam_gate_01", name="Cổng 1", enabled=True, last_active=now_utc, source_type="live", source="rtsp://test")
        session.add(cam)
        session.flush()

        # Seed historical buckets (same hour, e.g. 50 passages per 15-min bucket across 4 weeks)
        for week in range(1, 5):
            t_hist = now_utc - timedelta(days=week * 7)
            session.add(AnalyticsAggregate(
                id=uuid4(),
                camera_id=str(cam.id),
                bucket_start=t_hist,
                bucket_end=t_hist + timedelta(minutes=15),
                vehicle_in_count=25,
                vehicle_out_count=25,
                coverage_ratio=0.95,
            ))

        # Seed recent buckets (past 2 hours, matching ~50 passages)
        for i in range(8):
            t_rec = now_utc - timedelta(minutes=(8 - i) * 15)
            session.add(AnalyticsAggregate(
                id=uuid4(),
                camera_id=str(cam.id),
                bucket_start=t_rec,
                bucket_end=t_rec + timedelta(minutes=15),
                vehicle_in_count=25,
                vehicle_out_count=25,
                coverage_ratio=0.95,
            ))
        session.flush()

    res = detector.detect_anomalies(time_window_hours=2, camera_id="cam_gate_01")
    assert res["status"] == "success"
    assert res["summary"]["total_anomalies"] == 0
    assert len(res["anomalies"]) == 0


def test_traffic_spike_detection(anomaly_test_db):
    """Recent surge (> +100% of historical median) triggers TRAFFIC_SPIKE."""
    db = anomaly_test_db
    now_utc = datetime.now(timezone.utc)
    detector = TrafficAnomalyDetector(db=db)

    with db.transaction() as session:
        cam = Camera(id=uuid4(), registry_key="cam_mall_entrance", name="Cổng Mall", enabled=True, last_active=now_utc, source_type="live", source="rtsp://test")
        session.add(cam)
        session.flush()

        # Baseline: ~20 passages per bucket across 4 historical weeks
        for week in range(1, 5):
            for i in range(4):
                t_hist = (now_utc - timedelta(minutes=(3 - i) * 15 + 5)) - timedelta(days=week * 7)
                session.add(AnalyticsAggregate(
                    id=uuid4(),
                    camera_id=str(cam.id),
                    bucket_start=t_hist,
                    bucket_end=t_hist + timedelta(minutes=15),
                    vehicle_in_count=10,
                    vehicle_out_count=10,
                    coverage_ratio=0.90,
                ))

        # Recent surge: 80 passages per bucket (4x spike, 4 buckets in past 1h)
        for i in range(4):
            t_rec = now_utc - timedelta(minutes=(3 - i) * 15 + 5)
            session.add(AnalyticsAggregate(
                id=uuid4(),
                camera_id=str(cam.id),
                bucket_start=t_rec,
                bucket_end=t_rec + timedelta(minutes=15),
                vehicle_in_count=40,
                vehicle_out_count=40,
                coverage_ratio=0.95,
            ))
        session.flush()

    res = detector.detect_anomalies(time_window_hours=1, camera_id="cam_mall_entrance")
    assert res["status"] == "success"
    assert res["summary"]["total_anomalies"] >= 1

    spikes = [a for a in res["anomalies"] if a["anomaly_type"] == "TRAFFIC_SPIKE"]
    assert len(spikes) == 1
    spike = spikes[0]
    assert spike["severity"] in ("HIGH", "CRITICAL")
    assert spike["observed_value"] == 320  # 4 * 80
    assert spike["deviation_percent"] > 100.0
    assert "cao hơn" in spike["explanation"].lower()


def test_zero_baseline_safety(anomaly_test_db):
    """When historical baseline is near zero, a tiny count (e.g. 2 passages) must NOT trigger CRITICAL spike."""
    db = anomaly_test_db
    now_utc = datetime.now(timezone.utc)
    detector = TrafficAnomalyDetector(db=db)

    with db.transaction() as session:
        cam = Camera(id=uuid4(), registry_key="cam_quiet_gate", name="Cổng Phụ", enabled=True, last_active=now_utc, source_type="live", source="rtsp://test")
        session.add(cam)
        session.flush()

        # Baseline: 0 passages
        for week in range(1, 5):
            t_hist = now_utc - timedelta(days=week * 7)
            session.add(AnalyticsAggregate(
                id=uuid4(),
                camera_id=str(cam.id),
                bucket_start=t_hist,
                bucket_end=t_hist + timedelta(minutes=15),
                vehicle_in_count=0,
                vehicle_out_count=0,
                coverage_ratio=0.95,
            ))

        # Recent: 2 passages (delta < min_delta threshold)
        t_rec = now_utc - timedelta(minutes=15)
        session.add(AnalyticsAggregate(
            id=uuid4(),
            camera_id=str(cam.id),
            bucket_start=t_rec,
            bucket_end=t_rec + timedelta(minutes=15),
            vehicle_in_count=1,
            vehicle_out_count=1,
            coverage_ratio=0.95,
        ))
        session.flush()

    res = detector.detect_anomalies(time_window_hours=1, camera_id="cam_quiet_gate")
    assert res["status"] == "success"
    # Must NOT report false alarm spike for 2 passages
    spikes = [a for a in res["anomalies"] if a["anomaly_type"] == "TRAFFIC_SPIKE"]
    assert len(spikes) == 0


def test_camera_offline_availability_anomaly(anomaly_test_db):
    """Offline camera with no recent data triggers CAMERA_AVAILABILITY_ANOMALY."""
    db = anomaly_test_db
    now_utc = datetime.now(timezone.utc)
    detector = TrafficAnomalyDetector(db=db)

    with db.transaction() as session:
        # Camera has been inactive for 2 hours
        cam = Camera(
            id=uuid4(),
            registry_key="cam_disconnected",
            name="Camera Ngoại Tuyến",
            location="Khu vực B3",
            enabled=True,
            source_type="live",
            source="rtsp://test",
            last_active=now_utc - timedelta(hours=2),
        )
        session.add(cam)
        session.flush()

    res = detector.detect_anomalies(time_window_hours=1, camera_id="cam_disconnected")
    assert res["status"] == "success"
    anoms = res["anomalies"]
    assert len(anoms) == 1
    assert anoms[0]["anomaly_type"] == "CAMERA_AVAILABILITY_ANOMALY"
    assert anoms[0]["severity"] == "HIGH"
    assert "mất kết nối" in anoms[0]["explanation"].lower()
