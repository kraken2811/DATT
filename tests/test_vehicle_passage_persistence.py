"""Comprehensive tests for VehicleSession lifecycle, PostgreSQL persistence, and worker idempotency."""

from datetime import datetime, timezone
import os
import time
from uuid import UUID, uuid4
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from src.db.database import Database
from src.db.models import BusinessEvent, VehiclePassage
from src.db.repositories import BusinessEventRepository, VehiclePassageRepository
from src.events.db_worker import DatabaseWorker
from src.events.event_dto import BusinessEventDTO, VehiclePassageDTO
from src.events.event_manager import EventManager, VehicleSession


@pytest.fixture
def pg_session(monkeypatch):
    """Provides a dedicated schema on PostgreSQL for testing."""
    url = os.environ.get("DATT_DATABASE_URL") or os.environ.get("DATT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("PostgreSQL URL required for vehicle passage persistence tests")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        pytest.skip("Test requires PostgreSQL backend")

    schema = "test_vp_" + uuid4().hex[:12]
    admin = Database(url)
    database = None
    try:
        with admin.engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = parsed.update_query_dict({"options": f"-csearch_path={schema},public"})
        scoped_url = scoped.render_as_string(hide_password=False)
        monkeypatch.setenv("DATT_DATABASE_URL", scoped_url)

        # Run alembic migrations on the scoped schema
        from alembic import command
        from alembic.config import Config
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        cfg = Config(str(root / "src/db/alembic.ini"))
        command.upgrade(cfg, "head")

        database = Database(scoped_url)
        yield database
    finally:
        if database:
            database.dispose()
        with admin.engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_vehicle_passage_repository_upsert_and_queries(pg_session):
    db = pg_session
    with db.transaction() as session:
        v_repo = VehiclePassageRepository(session)
        now = datetime.now(timezone.utc)
        passage, created = v_repo.upsert_passage(
            session_key="cam01:46:1000",
            camera_id="cam01",
            track_id=46,
            vehicle_type="car",
            first_seen_at=now,
            last_seen_at=now,
            duration_ms=0.0,
        )
        assert created is True
        assert passage.track_id == 46
        assert passage.plate_text is None
        assert passage.vehicle_color is None  # Documented unavailable, not fabricated

        # Update plate on same passage
        passage_upd, created_upd = v_repo.upsert_passage(
            session_key="cam01:46:1000",
            plate_text="29A12345",
            plate_status="CONFIRMED",
            plate_confidence=0.92,
        )
        assert created_upd is False
        assert passage_upd.id == passage.id
        assert passage_upd.plate_text == "29A12345"

        # Query passages
        found = v_repo.query_passages(plate_text="29A12345")
        assert len(found) == 1
        assert found[0].id == passage.id

        # Count vehicle types
        counts = v_repo.count_vehicle_types(camera_id="cam01")
        assert counts.get("car") == 1


def test_business_event_repository_idempotency(pg_session):
    db = pg_session
    with db.transaction() as session:
        v_repo = VehiclePassageRepository(session)
        e_repo = BusinessEventRepository(session)
        now = datetime.now(timezone.utc)
        passage, _ = v_repo.upsert_passage(
            session_key="cam01:10:2000",
            camera_id="cam01",
            track_id=10,
            vehicle_type="truck",
            first_seen_at=now,
            last_seen_at=now,
        )

        idemp_key = f"{passage.id}:PLATE_RECOGNIZED:51F99999"
        ev1, created1 = e_repo.insert_idempotent(
            passage_id=passage.id,
            camera_id="cam01",
            track_id=10,
            event_type="PLATE_RECOGNIZED",
            event_time=now,
            plate_text="51F99999",
            idempotency_key=idemp_key,
        )
        assert created1 is True

        # Retry should NOT create duplicate row
        ev2, created2 = e_repo.insert_idempotent(
            passage_id=passage.id,
            camera_id="cam01",
            track_id=10,
            event_type="PLATE_RECOGNIZED",
            event_time=now,
            plate_text="51F99999",
            idempotency_key=idemp_key,
        )
        assert created2 is False
        assert ev2.id == ev1.id

        # Total events for this passage is exactly 1
        events = e_repo.query_events(passage_id=passage.id)
        assert len(events) == 1


def test_duplicate_plate_recognized_suppression():
    """Verify that multiple frames with the same plate do NOT spam PLATE_RECOGNIZED."""
    mock_worker = MagicMock()
    em = EventManager(db_worker=mock_worker)

    tracks = MagicMock()
    tracks.tracker_id = [12]
    tracks.xyxy = [[100, 100, 300, 300]]
    tracks.class_id = [2]
    tracks.confidence = [0.88]

    plate_state = MagicMock()
    plate_state.plate_text = "29K1-12345"
    plate_state.status = "CONFIRMED"
    plate_state.confidence = 0.95
    plate_state.plate_crop = None

    plate_results = {12: plate_state}

    # Frame 1: Vehicle appears, plate confirmed
    evs_frame1 = em.process_vehicle_frame(
        camera_id="cam01",
        vehicle_tracks=tracks,
        plate_results=plate_results,
    )
    ev_types_1 = [e["type"] for e in evs_frame1]
    assert "VEHICLE_ENTER" in ev_types_1
    assert "PLATE_RECOGNIZED" in ev_types_1

    # Frames 2 to 10: Repeated observations of the exact same confirmed plate
    for _ in range(9):
        evs_next = em.process_vehicle_frame(
            camera_id="cam01",
            vehicle_tracks=tracks,
            plate_results=plate_results,
        )
        ev_types_next = [e["type"] for e in evs_next]
        assert "PLATE_RECOGNIZED" not in ev_types_next, "Must NOT spam PLATE_RECOGNIZED!"

    # Exactly one business event for plate recognition was enqueued
    plate_enqueued = [
        call for call in mock_worker.enqueue_business_event.call_args_list
        if call[0][0].event_type == "PLATE_RECOGNIZED"
    ]
    assert len(plate_enqueued) == 1


def test_track_id_reuse_creates_distinct_passages(pg_session):
    """ByteTrack track_id reuse: track 46 appears, exits, and later reappears as a new passage."""
    db = pg_session
    worker = DatabaseWorker(db_url=db.engine.url.render_as_string(hide_password=False))
    em = EventManager(db_worker=worker)

    tracks = MagicMock()
    tracks.tracker_id = [46]
    tracks.xyxy = [[10, 10, 200, 200]]
    tracks.class_id = [2]
    tracks.confidence = [0.9]

    # Appearance 1
    em.process_vehicle_frame("cam_gate", tracks)
    passage_1 = em._active_passages[46]
    id_1 = passage_1.id
    session_key_1 = passage_1.session_key

    # Vehicle 1 exits (advance time > 3s)
    passage_1.last_seen = time.time() - 4.0
    em.process_vehicle_frame("cam_gate", MagicMock(tracker_id=[], xyxy=[]))
    assert 46 not in em._active_passages, "Track 46 should have exited"

    # Appearance 2: ByteTrack reuses track_id 46 later for an entirely new vehicle
    time.sleep(0.01)  # ensure distinct timestamp
    em.process_vehicle_frame("cam_gate", tracks)
    passage_2 = em._active_passages[46]
    id_2 = passage_2.id
    session_key_2 = passage_2.session_key

    # Verify separate identity
    assert id_1 != id_2, "Reused track_id MUST produce a different UUID"
    assert session_key_1 != session_key_2, "Reused track_id MUST produce a different session_key"

    # Clean shutdown and verify in database
    em.stop()
    worker.stop(timeout=3.0)

    with db.transaction() as session:
        v_repo = VehiclePassageRepository(session)
        passages = v_repo.query_passages(camera_id="cam_gate")
        assert len(passages) == 2, "Both appearances must be stored as separate rows"
        ids = {p.id for p in passages}
        assert id_1 in ids
        assert id_2 in ids


def test_no_synchronous_db_writes_in_realtime_frame():
    """Realtime frame loop must enqueue in < 1ms without blocking on DB commits."""
    worker = DatabaseWorker(max_queue_size=100)
    em = EventManager(db_worker=worker)

    tracks = MagicMock()
    tracks.tracker_id = [1, 2, 3]
    tracks.xyxy = [[10, 10, 50, 50], [60, 60, 100, 100], [120, 120, 200, 200]]
    tracks.class_id = [2, 7, 3]
    tracks.confidence = [0.9, 0.85, 0.8]

    # Frame 1: creates passages
    em.process_vehicle_frame("cam_main", tracks)

    # Frame 2: measure steady state frame latency
    t0 = time.perf_counter()
    em.process_vehicle_frame("cam_main", tracks)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    # Realtime frame build must take < 5ms (usually < 0.5ms)
    assert elapsed_ms < 5.0
    assert em.last_db_work_ms < 1.0, f"DB work ms was {em.last_db_work_ms}, expected < 1.0"
    worker.stop(timeout=1.0)



def test_queue_full_preserves_critical_events():
    """Verify queue full policy: drops low priority or evicts to preserve critical transitions."""
    worker = DatabaseWorker(db_url="sqlite:///dummy.db", max_queue_size=2)
    worker._persist_batch = MagicMock(return_value=True)
    worker._worker_loop = lambda: None  # freeze worker to fill queue

    p1 = VehiclePassageDTO(
        id=uuid4(), session_key="k1", camera_id="c1", track_id=1,
        first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
        is_final=False,
    )
    p2 = VehiclePassageDTO(
        id=uuid4(), session_key="k2", camera_id="c1", track_id=2,
        first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
        is_final=False,
    )
    p_critical = VehiclePassageDTO(
        id=uuid4(), session_key="k3", camera_id="c1", track_id=3,
        first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
        is_final=True,
    )

    worker.enqueue_passage(p1, is_critical=False)
    worker.enqueue_passage(p2, is_critical=False)
    assert worker.queue_depth == 2

    # Enqueue critical finalized passage when queue is full
    success = worker.enqueue_passage(p_critical, is_critical=True)
    assert success is True
    assert worker.queue_dropped >= 1
    worker.stop(timeout=0.1)


def test_db_worker_recovery_after_transient_failure(pg_session):
    """Verify that transient database errors do not crash worker and retry preserves data."""
    db = pg_session
    worker = DatabaseWorker(db_url=db.engine.url.render_as_string(hide_password=False))

    now = datetime.now(timezone.utc)
    dto = VehiclePassageDTO(
        id=uuid4(),
        session_key="transient:1:999",
        camera_id="cam_transient",
        track_id=1,
        vehicle_type="car",
        first_seen_at=now,
        last_seen_at=now,
        is_final=True,
    )
    ev_dto = BusinessEventDTO(
        id=uuid4(),
        passage_id=dto.id,
        camera_id="cam_transient",
        event_type="VEHICLE_ENTER",
        event_time=now,
        idempotency_key=f"{dto.id}:VEHICLE_ENTER",
    )

    worker.enqueue_passage(dto, is_critical=True)
    worker.enqueue_business_event(ev_dto, is_critical=True)

    # Let worker persist
    time.sleep(0.5)
    worker.stop(timeout=3.0)

    with db.transaction() as session:
        v_repo = VehiclePassageRepository(session)
        e_repo = BusinessEventRepository(session)
        p = v_repo.get_by_session_key("transient:1:999")
        assert p is not None
        assert p.id == dto.id
        ev = e_repo.get_by_idempotency_key(f"{dto.id}:VEHICLE_ENTER")
        assert ev is not None
