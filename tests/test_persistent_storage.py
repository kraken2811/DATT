"""Local contract tests; simulated remote storage is NOT cloud E2E evidence."""
import io
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from src.storage import LocalStorageBackend, ExternalStorageBackend, get_storage


@pytest.mark.parametrize("key", ["../private", "/etc/passwd", "data/events/../../secret", "data/events\\secret", "https://host/token", "data/events/./x"])
def test_reject_unsafe_keys(tmp_path, key):
    storage = LocalStorageBackend(tmp_path)
    with pytest.raises(ValueError):
        storage.save_bytes(key, b"secret")


def test_local_contract_and_process_restart(tmp_path):
    key = "data/uploads/videos/a.mp4"
    storage = LocalStorageBackend(tmp_path)
    storage.save_bytes(key, b"local-media")
    assert storage.exists(key)
    with storage.open(key) as source:
        assert source.read() == b"local-media"
        source.seek(0)
        assert storage.save(key, source) == key
    subprocess.run([sys.executable, "-c",
                    "from pathlib import Path; from src.storage import LocalStorageBackend; import sys; "
                    "s=LocalStorageBackend(Path(sys.argv[1])); assert s.materialize(sys.argv[2]).read_bytes()==b'local-media'",
                    str(tmp_path), key], check=True)
    storage.delete(key)
    assert not storage.exists(key)


def test_external_cache_loss_and_delete(tmp_path):
    # Driver contract simulation; production rejects local/memory protocols.
    import fsspec
    fs = fsspec.filesystem("memory")
    with patch.object(fs, "protocol", "test-remote"), patch("fsspec.core.url_to_fs", return_value=(fs, "/datt-test")):
        first = ExternalStorageBackend("test://bucket", {}, tmp_path / "runtime-one")
        key = "data/uploads/videos/restart.mp4"
        first.save_bytes(key, b"persistent-object")
        assert first.materialize(key).read_bytes() == b"persistent-object"
        second = ExternalStorageBackend("test://bucket", {}, tmp_path / "fresh-runtime")
        assert second.materialize(key).read_bytes() == b"persistent-object"
        second.delete(key)
        with pytest.raises(FileNotFoundError):
            first.materialize(key)  # stale first-runtime cache cannot resurrect deletion


def test_missing_config_and_no_local_fallback(monkeypatch):
    monkeypatch.setenv("DATT_STORAGE_BACKEND", "external")
    monkeypatch.delenv("DATT_STORAGE_URL", raising=False)
    with pytest.raises(ValueError, match="DATT_STORAGE_URL"):
        get_storage()
    monkeypatch.setenv("DATT_STORAGE_URL", "file:///tmp/not-cloud")
    with pytest.raises(ValueError, match="durable"):
        get_storage()


def test_strict_database_rejects_sqlite(monkeypatch):
    from src.db.database import Database
    monkeypatch.setenv("DATT_REQUIRE_PERSISTENCE", "1")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        Database("sqlite://")
    monkeypatch.delenv("DATT_DATABASE_URL", raising=False)
    with patch("src.db.database.Path.is_file", return_value=False):
        with pytest.raises(RuntimeError, match="DATT_DATABASE_URL"):
            Database()


def test_missing_database_warns_in_local_mode(monkeypatch, caplog):
    from src.db.database import Database
    monkeypatch.delenv("DATT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATT_REQUIRE_PERSISTENCE", raising=False)
    with patch("src.db.database.Path.is_file", return_value=False):
        db = Database()
        db.dispose()
    assert "DATT_DATABASE_URL missing" in caplog.text


def test_audit_redacts_connection_errors(monkeypatch, capsys):
    from src.persistence import audit, print_audit
    monkeypatch.setenv("DATT_DATABASE_URL", "postgresql+psycopg://user:secret@host/db")
    monkeypatch.setenv("DATT_STORAGE_BACKEND", "external")
    with patch("src.persistence.Database", side_effect=RuntimeError("secret token=private")), patch(
        "src.persistence.get_storage", side_effect=RuntimeError("secret token=private")
    ):
        result, errors = audit(require_external=True)
    print_audit(result, errors)
    out = capsys.readouterr().out
    assert "secret" not in out and "private" not in out
    assert not result["database_connected"] and not result["storage_connected"]


@pytest.mark.parametrize("missing_table", ["business_events", "vehicle_passages", "cameras", "zones"])
def test_audit_rejects_incomplete_event_schema(tmp_path, monkeypatch, missing_table):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from src.db.database import Database
    from src.persistence import audit

    monkeypatch.delenv("DATT_REQUIRE_PERSISTENCE", raising=False)
    monkeypatch.setenv("DATT_DATABASE_URL", "sqlite:///" + (tmp_path / "audit.db").as_posix())
    monkeypatch.setenv("DATT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DATT_STORAGE_ROOT", str(tmp_path))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "src/db/alembic.ini")), "head")
    result, errors = audit()
    assert not errors
    db = Database()
    try:
        with db.engine.begin() as conn:
            conn.execute(text("DROP TABLE " + missing_table))
    finally:
        db.dispose()
    result, errors = audit()
    from alembic.script import ScriptDirectory
    heads = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[1] / "src/db/alembic.ini"))).get_heads()
    assert result["alembic_revision"] == ",".join(sorted(heads))
    assert "required_tables_missing" in errors


def test_video_metadata_and_api_after_local_restart(tmp_path, monkeypatch):
    """Explicit local SQLite compatibility test, not a PostgreSQL substitute."""
    import cv2
    import numpy as np
    from fastapi.testclient import TestClient
    from src.db.database import Database
    from src.db.models import Base
    from src.ui import web_server
    from src.stream.camera_manager import CameraManager
    monkeypatch.delenv("DATT_REQUIRE_PERSISTENCE", raising=False)
    monkeypatch.setenv("DATT_DATABASE_URL", "sqlite:///" + (tmp_path / "local-test.db").as_posix())
    monkeypatch.setenv("DATT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("DATT_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(web_server, "UPLOAD_VIDEO_DIR", tmp_path)
    db = Database()
    Base.metadata.create_all(db.engine)
    clip = tmp_path / "input.mp4"
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 64))
    assert writer.isOpened()
    for _ in range(10):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    client = TestClient(web_server.app)
    response = client.post("/api/upload_video", files={"file": ("input.mp4", clip.read_bytes(), "video/mp4")})
    assert response.status_code == 200, response.text
    row = response.json()
    assert get_storage().exists(row["storage_path"])
    db.dispose()
    # Fresh interpreter reads the same DB and materializes the persisted key.
    subprocess.run([sys.executable, "-c", "from src.db.database import Database; from sqlalchemy import text; "
                    "from src.storage import get_storage; d=Database(); "
                    "c=d.engine.connect(); key=c.scalar(text('SELECT storage_path FROM video_sources')); "
                    "assert get_storage().materialize(key).is_file(); c.close(); d.dispose()"], check=True)
    listed = TestClient(web_server.app).get("/api/video_sources")
    assert listed.status_code == 200 and row["video_source_id"] in listed.text
    manager = CameraManager()
    try:
        camera = manager.set_video_source(source_type="local", source=row["storage_path"], video_source_id=row["video_source_id"])
        assert Path(camera.url) == get_storage().materialize(row["storage_path"])
        assert manager.read_with_meta(timeout=3)[0] is not None
    finally:
        manager.stop_camera()


def test_upload_storage_failure_is_not_success(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src.ui import web_server
    monkeypatch.setattr(web_server, "UPLOAD_VIDEO_DIR", tmp_path)
    with patch("src.ui.web_server.get_storage", side_effect=OSError("offline")):
        response = TestClient(web_server.app).post("/api/upload_video", files={"file": ("a.mp4", b"invalid", "video/mp4")})
    assert response.status_code == 503


def test_images_and_event_keys_survive_adapter_restart(tmp_path, monkeypatch):
    """Real DB worker + mock remote filesystem; no cloud durability claim."""
    import fsspec
    import numpy as np
    from datetime import datetime, timezone
    from uuid import uuid4
    from src.db.database import Database
    from src.db.models import Base, VehicleEvent, PlateEvent, VehicleWatchlist
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import VehiclePassageDTO
    from src.storage import save_image
    monkeypatch.delenv("DATT_REQUIRE_PERSISTENCE", raising=False)
    url = "sqlite:///" + (tmp_path / "worker-test.db").as_posix()
    db = Database(url)
    Base.metadata.create_all(db.engine)
    with db.transaction() as session:
        session.add(VehicleWatchlist(plate_number="TEST123", vehicle_type="car",
            display_name="Storage test", owner_info="", notes="", status="active"))
    fs = fsspec.filesystem("memory")
    with patch.object(fs, "protocol", "test-remote"), patch("fsspec.core.url_to_fs", return_value=(fs, "/images-test")):
        storage = ExternalStorageBackend("test://images", {}, tmp_path / "cache-one")
        with patch("src.storage.get_storage", return_value=storage):
            image = np.full((40, 40, 3), 120, dtype=np.uint8)
            worker = DatabaseWorker(url, snapshot_dir=tmp_path / "snapshots")
            now = datetime.now(timezone.utc)
            dto = VehiclePassageDTO(id=uuid4(), session_key="storage-test:1", camera_id="test", track_id=1,
                                    first_seen_at=now, last_seen_at=now, finalized_at=now,
                                    vehicle_type="car", vehicle_color="gray", plate_text="TEST123",
                                    plate_status="CONFIRMED", is_final=True)
            try:
                assert worker._persist_batch([("PASSAGE", dto, (image, image))])
            finally:
                worker.stop()
            with db.transaction() as session:
                vehicle = session.get(VehicleEvent, dto.id)
                plate = session.query(PlateEvent).one()
                keys = [vehicle.vehicle_image_path, plate.plate_crop_path]
            assert all(storage.exists(key) for key in keys)
        fresh = ExternalStorageBackend("test://images", {}, tmp_path / "cache-two")
        import cv2
        for key in keys:
            assert cv2.imread(str(fresh.materialize(key))).shape == (40, 40, 3)
            fresh.delete(key)
    db.dispose()


def test_target_image_materializes_after_cache_reset(tmp_path, monkeypatch):
    import fsspec
    import cv2
    import numpy as np
    from fastapi.testclient import TestClient
    from src.db.database import Database
    from src.db.models import Base
    from src.db.repositories import TargetRepository
    from src.ui import web_server
    from src.recognition.target_matcher import target_manager
    monkeypatch.delenv("DATT_REQUIRE_PERSISTENCE", raising=False)
    monkeypatch.setenv("DATT_DATABASE_URL", "sqlite:///" + (tmp_path / "target-test.db").as_posix())
    db = Database()
    Base.metadata.create_all(db.engine)
    fs = fsspec.filesystem("memory")
    key = "data/uploads/targets/reference.jpg"
    with patch.object(fs, "protocol", "test-remote"), patch("fsspec.core.url_to_fs", return_value=(fs, "/target-test")):
        original = ExternalStorageBackend("test://targets", {}, tmp_path / "old-runtime")
        ok, encoded = cv2.imencode(".jpg", np.full((40, 40, 3), 120, dtype=np.uint8))
        assert ok
        original.save_bytes(key, encoded.tobytes())
        with db.transaction() as session:
            target = TargetRepository(session).create(name="Reference", target_type="face", image_path=key)
        db.dispose()
        target_manager.clear()
        fresh = ExternalStorageBackend("test://targets", {}, tmp_path / "new-runtime")
        with patch("src.ui.web_server.get_storage", return_value=fresh):
            response = TestClient(web_server.app).get(f"/api/targets/{target.id}/image")
        assert response.status_code == 200
        assert response.content == encoded.tobytes()
        fresh.delete(key)
