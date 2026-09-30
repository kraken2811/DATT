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
from src.db.repositories import (
    CameraRepository, ZoneRepository, TargetRepository,
    DetectionEventRepository, VehicleEventRepository, PlateEventRepository, FaceEventRepository,
    TargetEmbeddingRepository,
)

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
        scoped = parsed.update_query_dict({"options": f"-csearch_path={schema},public"})
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
        target_emb = TargetEmbeddingRepository(session).create(
            target_id=target.id,
            embedding=[0.1] * 512,
            model_name="arcface",
            model_version="1.0",
        )
        detection = DetectionEventRepository(session).create(camera_id=camera.id, event_type="vehicle",
            frame_id=42, track_id=7, event_metadata={"backend": "postgresql"})
        vehicle = VehicleEventRepository(session).create(detection_event_id=detection.id,
            vehicle_class="car", track_id=7, zone_id=str(zone.id))
        plate = PlateEventRepository(session).create(vehicle_event_id=vehicle.id, plate_text="30A12345")
        face = FaceEventRepository(session).create(detection_event_id=detection.id, target_id=target.id,
            track_id=7, similarity=0.95, decision="matched")
    return camera.id, zone.id, target.id, detection.id, vehicle.id, plate.id, face.id, target_emb.id


def assert_graph(database, ids):
    camera, zone, target, detection, vehicle, plate, face, target_emb = ids
    with database.transaction() as session:
        assert CameraRepository(session).get(camera).name == "PG camera"
        assert ZoneRepository(session).list(camera_id=camera)[0].polygon == [[0, 0], [1, 0], [1, 1]]
        assert TargetEmbeddingRepository(session).get(target_emb).model_name == "arcface"
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
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
        assert connection.scalar(text("SELECT data_type FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='zones' AND column_name='polygon'")) == "jsonb"
        assert connection.scalar(text("SELECT extname FROM pg_extension WHERE extname = 'vector'")) == "vector"
        assert connection.scalar(text("SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='target_embeddings' AND column_name='embedding'")) == "vector"
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


def test_pgvector_crud_and_validation(pg):
    """Test insert VECTOR(512), reject wrong dimension, and basic CRUD."""
    database, _ = pg
    with database.transaction() as session:
        target = TargetRepository(session).create(name="Jane Doe", target_type="face")
        repo = TargetEmbeddingRepository(session)

        # Reject wrong dimension (not 512)
        with pytest.raises(ValueError, match="512"):
            repo.create(target_id=target.id, embedding=[0.1] * 128, model_name="arcface")

        # Reject NaN or Inf
        with pytest.raises(ValueError, match="invalid"):
            repo.create(target_id=target.id, embedding=[float("nan")] * 512, model_name="arcface")

        # Insert VECTOR(512)
        emb_vec = [0.0] * 512
        emb_vec[0] = 1.0
        embedding = repo.create(
            target_id=target.id,
            embedding=emb_vec,
            model_name="arcface",
            model_version="1.0",
            source_image_path="/images/jane.jpg",
        )
        assert embedding.id is not None
        assert embedding.target_id == target.id
        assert embedding.model_name == "arcface"

    with database.transaction() as session:
        repo = TargetEmbeddingRepository(session)
        # Read
        fetched = repo.get(embedding.id)
        assert fetched is not None
        assert len(fetched.embedding) == 512
        assert fetched.model_name == "arcface"

        # Update
        updated = repo.update(embedding.id, model_version="1.1")
        assert updated.model_version == "1.1"

        # Delete
        assert repo.delete(embedding.id) is True
        assert repo.get(embedding.id) is None


def test_pgvector_cascade_delete(pg):
    """Test cascade delete of embeddings when parent target is deleted."""
    database, _ = pg
    with database.transaction() as session:
        target = TargetRepository(session).create(name="John Cascade", target_type="face")
        repo = TargetEmbeddingRepository(session)
        emb = repo.create(target_id=target.id, embedding=[0.5] * 512, model_name="arcface")
        emb_id = emb.id

    with database.transaction() as session:
        # Delete parent target
        TargetRepository(session).delete(target.id)

    with database.transaction() as session:
        # Child embedding must be deleted via CASCADE
        assert TargetEmbeddingRepository(session).get(emb_id) is None


def test_pgvector_cosine_search_and_top_k(pg):
    """Test cosine nearest-neighbor search, top-k ordering, and distance filtering."""
    database, _ = pg
    with database.transaction() as session:
        target1 = TargetRepository(session).create(name="Target Exact", target_type="face")
        target2 = TargetRepository(session).create(name="Target Orthogonal", target_type="face")
        target3 = TargetRepository(session).create(name="Target Opposite", target_type="face")

        repo = TargetEmbeddingRepository(session)

        # Vector A: [1, 0, 0, ...]
        vec_a = [0.0] * 512
        vec_a[0] = 1.0

        # Vector B (Close to A): [0.99, 0.14, 0, ...]
        vec_b = [0.0] * 512
        vec_b[0] = 0.99
        vec_b[1] = 0.14

        # Vector C (Orthogonal to A): [0, 1, 0, ...]
        vec_c = [0.0] * 512
        vec_c[1] = 1.0

        # Vector D (Opposite to A): [-1, 0, 0, ...]
        vec_d = [0.0] * 512
        vec_d[0] = -1.0

        emb_b = repo.create(target_id=target1.id, embedding=vec_b, model_name="arcface", model_version="v1")
        emb_c = repo.create(target_id=target2.id, embedding=vec_c, model_name="arcface", model_version="v1")
        emb_d = repo.create(target_id=target3.id, embedding=vec_d, model_name="arcface", model_version="v1")

    with database.transaction() as session:
        repo = TargetEmbeddingRepository(session)

        # Query with vec_a
        results = repo.search_similar(vec_a, limit=3)
        assert len(results) == 3

        # Top 1 must be emb_b (closest to vec_a, cosine distance ~ 0)
        assert results[0].target_embedding_id == emb_b.id
        assert results[0].target_id == target1.id
        assert results[0].distance < 0.05
        assert results[0].similarity > 0.95

        # Top 2 must be emb_c (orthogonal to vec_a, cosine distance = 1.0)
        assert results[1].target_embedding_id == emb_c.id
        assert abs(results[1].distance - 1.0) < 0.05
        assert abs(results[1].similarity - 0.0) < 0.05

        # Top 3 must be emb_d (opposite to vec_a, cosine distance = 2.0)
        assert results[2].target_embedding_id == emb_d.id
        assert abs(results[2].distance - 2.0) < 0.05
        assert abs(results[2].similarity - (-1.0)) < 0.05

        # Test max_distance filter
        filtered = repo.search_similar(vec_a, limit=5, max_distance=0.5)
        assert len(filtered) == 1
        assert filtered[0].target_embedding_id == emb_b.id


def test_pgvector_transaction_rollback(pg):
    """Test transaction rollback for vector repository operations."""
    database, _ = pg
    with pytest.raises(RuntimeError):
        with database.transaction() as session:
            target = TargetRepository(session).create(name="Rollback User", target_type="face")
            TargetEmbeddingRepository(session).create(target_id=target.id, embedding=[0.1] * 512, model_name="arcface")
            raise RuntimeError("abort vector transaction")

    with database.transaction() as session:
        assert TargetRepository(session).list(name="Rollback User") == []
        assert TargetEmbeddingRepository(session).list() == []

