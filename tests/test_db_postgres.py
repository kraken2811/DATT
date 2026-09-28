"""Opt-in real PostgreSQL tests. Each test owns a disposable isolated schema.

DATT_TEST_POSTGRES_URL enables DB tests. DATT_TEST_POSTGRES_RESTART=1 additionally
authorizes restarting this repository's Compose postgres service (host-only).
"""
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from src.db import Database
from src.db.repositories import (CameraRepository, ZoneRepository, TargetRepository,
    DetectionEventRepository, VehicleEventRepository, PlateEventRepository, FaceEventRepository)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pg(monkeypatch):
    url = os.environ.get("DATT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set DATT_TEST_POSTGRES_URL to run against real PostgreSQL")
    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql", "PostgreSQL URL required"
    schema = "datt_test_" + uuid4().hex
    admin = Database(url)
    database = None
    try:
        with admin.engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        scoped = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
        scoped_url = scoped.render_as_string(hide_password=False)
        monkeypatch.setenv("DATT_DATABASE_URL", scoped_url)
        config = Config(str(ROOT / "src/db/alembic.ini"))
        command.upgrade(config, "head")
        database = Database(scoped_url)
        yield database, config
    finally:
        if database:
            database.dispose()
        with admin.engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def insert_graph(database):
    with database.transaction() as session:
        camera = CameraRepository(session).create(name="PG camera", source_type="file", source="demo.mp4")
        zone = ZoneRepository(session).create(camera_id=camera.id, name="Entry", polygon=[[0, 0], [1, 0], [1, 1]])
        target = TargetRepository(session).create(name="Reference", target_type="face", embedding=[0.1, 0.2])
        detection = DetectionEventRepository(session).create(camera_id=camera.id, event_type="vehicle",
            frame_id=42, track_id=7, event_metadata={"backend": "postgresql"})
        vehicle = VehicleEventRepository(session).create(detection_event_id=detection.id,
            vehicle_class="car", track_id=7, zone_id=str(zone.id))
        plate = PlateEventRepository(session).create(vehicle_event_id=vehicle.id, plate_text="30A12345")
        face = FaceEventRepository(session).create(detection_event_id=detection.id, target_id=target.id,
            track_id=7, similarity=0.95, decision="matched")
    return camera.id, zone.id, target.id, detection.id, vehicle.id, plate.id, face.id


def assert_graph(database, ids):
    camera, zone, target, detection, vehicle, plate, face = ids
    with database.transaction() as session:
        assert CameraRepository(session).get(camera).name == "PG camera"
        assert ZoneRepository(session).list(camera_id=camera)[0].polygon == [[0, 0], [1, 0], [1, 1]]
        rows = DetectionEventRepository(session).query(camera_id=camera, track_id=7, event_type="vehicle")
        assert [row.id for row in rows] == [detection]
        assert rows[0].event_metadata == {"backend": "postgresql"}
        assert rows[0].timestamp.utcoffset().total_seconds() == 0
        assert VehicleEventRepository(session).get(vehicle).zone_id == str(zone)
        assert PlateEventRepository(session).list(plate_text="30A12345")[0].id == plate
        assert FaceEventRepository(session).list(target_id=target)[0].id == face


def test_postgres_migration_insert_query(pg):
    database, config = pg
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
        assert connection.scalar(text("SELECT version()" )).startswith("PostgreSQL")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002"
        assert connection.scalar(text("SELECT data_type FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='zones' AND column_name='polygon'")) == "jsonb"
    command.check(config)
    assert_graph(database, insert_graph(database))


def test_postgres_rollback(pg):
    database, _ = pg
    with pytest.raises(RuntimeError):
        with database.transaction() as session:
            camera = CameraRepository(session).create(name="Rollback", source_type="file", source="demo.mp4")
            ZoneRepository(session).create(camera_id=camera.id, name="Rollback", polygon=[[0, 0], [1, 0], [1, 1]])
            raise RuntimeError("abort batch")
    with database.transaction() as session:
        assert CameraRepository(session).list() == []
        assert ZoneRepository(session).list() == []
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            ZoneRepository(session).create(camera_id=uuid4(), name="Invalid", polygon=[])
    assert_graph(database, insert_graph(database))


def test_postgres_restart_persistence(pg):
    if os.environ.get("DATT_TEST_POSTGRES_RESTART") != "1":
        pytest.skip("Set DATT_TEST_POSTGRES_RESTART=1 on host to authorize Compose restart")
    database, _ = pg
    compose = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]

    def output(args):
        return subprocess.check_output(args, cwd=ROOT, text=True, timeout=90).strip()

    container_id = output([*compose, "ps", "-q", "postgres"])
    assert container_id, "Compose postgres must already be running"
    details = json.loads(output(["docker", "inspect", container_id]))[0]
    url = make_url(os.environ["DATT_TEST_POSTGRES_URL"])
    binding = details["NetworkSettings"]["Ports"]["5432/tcp"]
    assert url.host in ("localhost", "127.0.0.1")
    assert any(int(item["HostPort"]) == (url.port or 5432) for item in binding)
    assert any(m.get("Name") == "datt_postgres_data" and m["Destination"] == "/var/lib/postgresql/data"
               for m in details["Mounts"])
    ids = insert_graph(database)
    assert_graph(database, ids)
    database.dispose()
    subprocess.run([*compose, "restart", "postgres"], cwd=ROOT, check=True, timeout=90)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        after = json.loads(output(["docker", "inspect", container_id]))[0]
        if after["State"].get("Health", {}).get("Status") == "healthy":
            break
        time.sleep(1)
    else:
        pytest.fail("PostgreSQL did not become healthy after restart")
    assert after["State"]["StartedAt"] != details["State"]["StartedAt"]
    assert_graph(database, ids)
