"""End-to-end tests for Multi-Tool Entity Investigation and Timeline Reconstruction."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest

from src.db.database import Database
from src.db.models import (
    Base,
    Camera,
    DetectionEvent,
    FaceEvent,
    Notification,
    PlateEvent,
    Target,
    VehicleEvent,
    VehiclePassage,
    VehicleWatchlist,
)
from src.agent.investigation.entity_investigation import (
    investigate_vehicle_entity,
    investigate_face_entity,
)


@pytest.fixture
def investigation_db(tmp_path):
    """Isolated SQLite database for investigation engine tests."""
    db_file = tmp_path / "investigation_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    db = Database(url=db_url)
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        db.dispose()


def test_vehicle_observed_across_three_cameras(investigation_db):
    """Verify chronological timeline across 3 cameras with location metadata."""
    db = investigation_db
    now_utc = datetime.now(timezone.utc)

    with db.transaction() as session:
        # Seed 3 cameras
        cam1 = Camera(id=uuid4(), registry_key="cam_gate_north", name="Camera Cổng Bắc", location="Cổng kiểm soát số 1", source_type="live", source="rtsp://test1")
        cam2 = Camera(id=uuid4(), registry_key="cam_junction_2", name="Camera Ngã tư 2", location="Ngã tư trung tâm", source_type="live", source="rtsp://test2")
        cam3 = Camera(id=uuid4(), registry_key="cam_parking", name="Camera Bãi xe", location="Bãi đỗ P1", source_type="live", source="rtsp://test3")
        # 1. Parents: Cameras & Watchlists
        wl = VehicleWatchlist(id=uuid4(), plate_number="30A12345", display_name="Xe VIP 123", status="active", vehicle_type="car")
        session.add_all([cam1, cam2, cam3, wl])
        session.flush()

        t1 = now_utc - timedelta(hours=3)
        t2 = now_utc - timedelta(hours=2)
        t3 = now_utc - timedelta(hours=1)

        # 2. Level 1 children: DetectionEvents
        de1 = DetectionEvent(id=uuid4(), camera_id=cam1.id, frame_id=10, event_type="plate", timestamp=t1)
        de2 = DetectionEvent(id=uuid4(), camera_id=cam2.id, frame_id=20, event_type="plate", timestamp=t2)
        de3 = DetectionEvent(id=uuid4(), camera_id=cam3.id, frame_id=30, event_type="plate", timestamp=t3)
        session.add_all([de1, de2, de3])
        session.flush()

        # 3. Level 2 children: VehicleEvents
        ve1 = VehicleEvent(id=uuid4(), detection_event_id=de1.id, vehicle_class="car", track_id=1)
        ve2 = VehicleEvent(id=uuid4(), detection_event_id=de2.id, vehicle_class="car", track_id=2)
        ve3 = VehicleEvent(id=uuid4(), detection_event_id=de3.id, vehicle_class="car", track_id=3)
        session.add_all([ve1, ve2, ve3])
        session.flush()

        # 4. Level 3 children: PlateEvents
        pe1 = PlateEvent(id=uuid4(), vehicle_event_id=ve1.id, plate_text="30A-12345", normalized_plate="30A12345", confidence=0.95, created_at=t1)
        pe2 = PlateEvent(id=uuid4(), vehicle_event_id=ve2.id, plate_text="30A-123.45", normalized_plate="30A12345", confidence=0.88, created_at=t2)
        pe3 = PlateEvent(id=uuid4(), vehicle_event_id=ve3.id, plate_text="30A-12345", normalized_plate="30A12345", confidence=0.92, created_at=t3)
        session.add_all([pe1, pe2, pe3])
        session.flush()

        # 5. Level 4 children: Notifications
        notif = Notification(
            id=uuid4(),
            plate_event_id=pe1.id,
            vehicle_watchlist_id=wl.id,
            camera_id=str(cam1.id),
            status="sent",
            channel="email",
            recipient="security@datt.vn",
            payload={"plate": "30A12345"},
            created_at=t1,
            sent_at=t1 + timedelta(seconds=2),
        )
        session.add(notif)
        session.flush()

    # Run investigation
    res = investigate_vehicle_entity(
        db=db,
        plate_number="30A-12345",
        include_watchlist=True,
        include_alerts=True,
        include_notifications=True,
    )

    assert res["status"] == "success"
    assert res["target_plate"] == "30A-12345"
    assert res["normalized_plate"] == "30A12345"

    summary = res["summary"]
    assert summary["total_observations"] == 3
    assert summary["distinct_cameras"] == 3
    assert summary["watchlist_status"] == "active"
    assert summary["watchlist_record"]["display_name"] == "Xe VIP 123"
    assert summary["total_alerts"] == 1
    assert summary["notifications_sent"] == 1

    # Verify chronological timeline sorting
    timeline = res["timeline"]
    assert len(timeline) == 3
    assert timeline[0]["camera_name"] == "Camera Cổng Bắc"
    assert timeline[0]["camera_location"] == "Cổng kiểm soát số 1"
    assert timeline[0]["associated_alert"] is True

    assert timeline[1]["camera_name"] == "Camera Ngã tư 2"
    assert timeline[2]["camera_name"] == "Camera Bãi xe"

    # Verify provenance statement
    assert "hành trình quan sát được" in res["provenance_notes"].lower()


def test_duplicate_observations_clustering(investigation_db):
    """Multiple frames within 30s on same camera are clustered to avoid noisy timelines."""
    db = investigation_db
    now_utc = datetime.now(timezone.utc)

    with db.transaction() as session:
        cam = Camera(id=uuid4(), name="Cổng Bắc", source_type="live", source="cam1")
        session.add(cam)
        session.flush()

        # 3 detections on same camera within 10 seconds
        t0 = now_utc - timedelta(minutes=10)
        for i in range(3):
            t_i = t0 + timedelta(seconds=i * 4)
            de = DetectionEvent(id=uuid4(), camera_id=cam.id, frame_id=i, event_type="plate", timestamp=t_i)
            session.add(de)
            session.flush()
            ve = VehicleEvent(id=uuid4(), detection_event_id=de.id, vehicle_class="car", track_id=1)
            session.add(ve)
            session.flush()
            pe = PlateEvent(id=uuid4(), vehicle_event_id=ve.id, plate_text="51F-9999", normalized_plate="51F9999", confidence=0.80 + i * 0.05, created_at=t_i)
            session.add(pe)
            session.flush()

    res = investigate_vehicle_entity(db=db, plate_number="51F-9999")
    assert res["status"] == "success"
    # Clustered into 1 trip observation with count = 3 and max OCR confidence = 0.90
    assert len(res["timeline"]) == 1
    assert res["timeline"][0]["observation_count"] == 3
    assert res["timeline"][0]["ocr_confidence"] == pytest.approx(0.90, rel=1e-2)


def test_vehicle_not_found(investigation_db):
    """Non-existent vehicle returns clean empty result without errors."""
    db = investigation_db
    res = investigate_vehicle_entity(db=db, plate_number="99Z-00000")
    assert res["status"] == "success"
    assert res["summary"]["total_observations"] == 0
    assert res["summary"]["watchlist_status"] == "not_in_watchlist"
    assert len(res["timeline"]) == 0


def test_face_investigation_and_disambiguation(investigation_db):
    """Test face investigation, similarity scores, and name disambiguation."""
    db = investigation_db
    now_utc = datetime.now(timezone.utc)

    with db.transaction() as session:
        cam = Camera(id=uuid4(), name="Camera Sảnh A", source_type="live", source="cam1")
        session.add(cam)
        session.flush()

        # Two targets with same name prefix "Nguyễn Văn"
        t1 = Target(id=uuid4(), name="Nguyễn Văn An", target_type="person", active=True)
        t2 = Target(id=uuid4(), name="Nguyễn Văn Bình", target_type="person", active=True)
        session.add_all([t1, t2])
        session.flush()

        # Event for Target 1
        fe = FaceEvent(
            id=uuid4(),
            camera_id=str(cam.id),
            target_id=t1.id,
            similarity=0.94,
            decision="match",
            created_at=now_utc - timedelta(hours=1),
        )
        session.add(fe)
        session.flush()

    # 1. Ambiguous query -> Disambiguation needed
    res_ambig = investigate_face_entity(db=db, name="Nguyễn Văn")
    assert res_ambig["status"] == "disambiguation_needed"
    assert len(res_ambig["candidates"]) == 2

    # 2. Specific name query -> Single target resolved
    res_single = investigate_face_entity(db=db, name="Nguyễn Văn An")
    assert res_single["status"] == "success"
    assert res_single["target"]["name"] == "Nguyễn Văn An"
    assert res_single["summary"]["total_observations"] == 1
    assert res_single["timeline"][0]["similarity"] == 0.94
    assert res_single["timeline"][0]["camera_name"] == "Camera Sảnh A"

    # 3. Invalid UUID query -> Gracefully rejected
    res_invalid_uuid = investigate_face_entity(db=db, target_id="not-a-valid-uuid")
    assert res_invalid_uuid["status"] == "error"
    assert "UUID hợp lệ" in res_invalid_uuid["message"]
