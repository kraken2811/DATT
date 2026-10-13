"""Unit and integration tests for Automated Shift Handover Reporting Engine."""

from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest

from src.agent.tools.shift_reports import (
    resolve_shift_bounds,
    generate_shift_handover_report,
    LOCAL_TZ,
)
from src.db.database import Database
from src.db.models import (
    Base,
    Camera,
    VehiclePassage,
    AnalyticsAggregate,
    FaceEvent,
    PlateEvent,
    Notification,
    Target,
    VehicleWatchlist,
    DetectionEvent,
    VehicleEvent,
)


@pytest.fixture
def shift_test_db(tmp_path):
    """Isolated SQLite database for shift handover report tests."""
    db_file = tmp_path / "shift_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    db = Database(url=db_url)
    Base.metadata.create_all(db.engine)
    try:
        yield db
    finally:
        db.dispose()


def test_resolve_shift_bounds_boundaries():
    """Verify exact time boundaries for Morning, Afternoon, and Night shifts."""
    target_date = "2026-10-15"

    # Morning: 06:00 to 14:00 ICT
    m_start, m_end, m_lbl, m_dt = resolve_shift_bounds("morning", target_date)
    assert "Ca Sáng" in m_lbl
    assert m_dt == "15/10/2026"
    assert m_start.astimezone(LOCAL_TZ).hour == 6
    assert m_end.astimezone(LOCAL_TZ).hour == 14
    assert (m_end - m_start).total_seconds() == 8 * 3600

    # Afternoon: 14:00 to 22:00 ICT
    a_start, a_end, a_lbl, a_dt = resolve_shift_bounds("afternoon", target_date)
    assert "Ca Chiều" in a_lbl
    assert a_start.astimezone(LOCAL_TZ).hour == 14
    assert a_end.astimezone(LOCAL_TZ).hour == 22
    assert (a_end - a_start).total_seconds() == 8 * 3600

    # Night: 22:00 to 06:00 next day ICT (cross-date boundary)
    n_start, n_end, n_lbl, n_dt = resolve_shift_bounds("night", target_date)
    assert "Ca Đêm" in n_lbl
    assert n_start.astimezone(LOCAL_TZ).hour == 22
    assert n_start.astimezone(LOCAL_TZ).day == 15
    assert n_end.astimezone(LOCAL_TZ).hour == 6
    assert n_end.astimezone(LOCAL_TZ).day == 16
    assert (n_end - n_start).total_seconds() == 8 * 3600


def test_shift_report_aggregation(shift_test_db, monkeypatch):
    """Verify accurate aggregation of cameras, traffic, security, and notifications."""
    db = shift_test_db
    monkeypatch.setattr("src.agent.tools.shift_reports.agent_config.get_database", lambda: db)

    # Base target date: 2026-10-15 Morning (06:00 - 14:00 ICT)
    start_utc, end_utc, _, _ = resolve_shift_bounds("morning", "2026-10-15")
    mid_shift = start_utc + timedelta(hours=3)  # 09:00 ICT
    outside_shift = start_utc - timedelta(hours=2)  # 04:00 ICT

    with db.transaction() as session:
        # 1. Cameras: 1 online, 1 offline
        cam_on = Camera(
            id=uuid4(),
            registry_key="cam_gate_main",
            name="Cổng Chính",
            enabled=True,
            last_active=datetime.now(timezone.utc),
            source_type="live",
            source="rtsp://test1",
        )
        cam_off = Camera(
            id=uuid4(),
            registry_key="cam_backyard",
            name="Sân Sau",
            enabled=True,
            last_active=datetime.now(timezone.utc) - timedelta(hours=5),
            source_type="live",
            source="rtsp://test2",
        )
        session.add_all([cam_on, cam_off])
        session.flush()

        # 2. Vehicle Passages: 2 inside shift (1 car, 1 motorcycle), 1 outside shift
        session.add_all([
            VehiclePassage(
                id=uuid4(),
                camera_id=str(cam_on.id),
                track_id=101,
                session_key="sess_car_101",
                vehicle_type="car",
                first_seen_at=mid_shift,
                last_seen_at=mid_shift + timedelta(seconds=10),
            ),
            VehiclePassage(
                id=uuid4(),
                camera_id=str(cam_on.id),
                track_id=102,
                session_key="sess_moto_102",
                vehicle_type="motorcycle",
                first_seen_at=mid_shift + timedelta(minutes=15),
                last_seen_at=mid_shift + timedelta(minutes=15, seconds=5),
            ),
            VehiclePassage(
                id=uuid4(),
                camera_id=str(cam_on.id),
                track_id=103,
                session_key="sess_truck_103",
                vehicle_type="truck",
                first_seen_at=outside_shift,
                last_seen_at=outside_shift + timedelta(seconds=10),
            ),
        ])

        # 3. Analytics Aggregates: 25 persons at 09:00 ICT
        session.add(AnalyticsAggregate(
            id=uuid4(),
            camera_id=str(cam_on.id),
            bucket_start=mid_shift,
            bucket_end=mid_shift + timedelta(minutes=15),
            person_in_count=15,
            person_out_count=10,
            vehicle_in_count=2,
            vehicle_out_count=0,
            coverage_ratio=0.98,
        ))

        # 4. Watchlist security matches
        target = Target(id=uuid4(), name="Đối tượng A", target_type="person", active=True)
        vw = VehicleWatchlist(id=uuid4(), plate_number="51F-99999", owner_info="Vip B", status="active")
        session.add_all([target, vw])
        session.flush()

        face_ev = FaceEvent(
            id=uuid4(),
            target_id=target.id,
            camera_id=str(cam_on.id),
            created_at=mid_shift,
            similarity=0.88,
            decision="matched",
        )
        session.add(face_ev)

        det_ev = DetectionEvent(
            id=uuid4(),
            camera_id=cam_on.id,
            event_type="vehicle",
            frame_id=1,
            timestamp=mid_shift,
            confidence=0.95,
        )
        session.add(det_ev)
        session.flush()

        veh_ev = VehicleEvent(
            id=uuid4(),
            detection_event_id=det_ev.id,
            vehicle_class="car",
            track_id=101,
            first_seen=mid_shift,
            last_seen=mid_shift + timedelta(seconds=10),
        )
        session.add(veh_ev)
        session.flush()

        plate_ev = PlateEvent(
            id=uuid4(),
            vehicle_event_id=veh_ev.id,
            plate_text="51F-99999",
            normalized_plate="51F99999",
            status="matched",
            created_at=mid_shift + timedelta(minutes=30),
            confidence=0.95,
        )
        session.add(plate_ev)
        session.flush()

        # 5. Notifications
        session.add_all([
            Notification(
                id=uuid4(),
                event_id=face_ev.id,
                plate_event_id=None,
                camera_id=str(cam_on.id),
                channel="email",
                recipient="ops@company.com",
                status="sent",
                payload={"subject": "Face Alert"},
                created_at=mid_shift,
            ),
            Notification(
                id=uuid4(),
                event_id=None,
                plate_event_id=plate_ev.id,
                camera_id=str(cam_on.id),
                channel="email",
                recipient="security@company.com",
                status="failed",
                payload={"subject": "Plate Alert"},
                created_at=mid_shift + timedelta(minutes=5),
            ),
            # Notification outside shift
            Notification(
                id=uuid4(),
                event_id=None,
                plate_event_id=plate_ev.id,
                camera_id=str(cam_on.id),
                channel="email",
                recipient="night_ops@company.com",
                status="sent",
                payload={"subject": "Outside Shift Alert"},
                created_at=outside_shift,
            ),
        ])
        session.flush()

    # Invoke tool
    report = generate_shift_handover_report.invoke({
        "shift_type": "morning",
        "shift_date": "2026-10-15",
    })

    assert report["status"] == "success"
    assert "Ca Sáng" in report["shift_label"]
    assert report["shift_date"] == "15/10/2026"

    # Infrastructure
    infra = report["infrastructure"]
    assert infra["total_cameras"] == 2
    assert infra["online_cameras"] == 1
    assert infra["offline_cameras"] == 1
    assert "Sân Sau" in infra["offline_camera_names"]

    # Traffic
    traffic = report["traffic"]
    assert traffic["total_vehicle_passages"] == 2  # Excludes outside_shift
    assert traffic["total_person_passages"] == 25
    assert traffic["vehicle_classification"]["car"] == 1
    assert traffic["vehicle_classification"]["motorcycle"] == 1
    assert "truck" not in traffic["vehicle_classification"]

    # Security
    sec = report["security"]
    assert sec["face_watchlist_matches"] == 1
    assert sec["vehicle_watchlist_matches"] == 1
    assert sec["total_alerts"] == 2  # Excludes outside_shift

    # Notifications
    notif = report["notifications"]
    assert notif["sent"] == 1
    assert notif["failed"] == 1

    # Handover checklist & markdown
    assert len(report["handover_checklist"]) >= 2
    md = report["report_markdown"]
    assert "BÁO CÁO BÀN GIAO CA TRỰC" in md
    assert "Cổng Chính" in md or "cam_gate_main" in md
    assert "Sân Sau" in md
    assert "car" in md
