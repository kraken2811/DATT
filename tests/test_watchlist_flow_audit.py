import numpy as np
import pytest
from datetime import datetime
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from alembic import command
from alembic.config import Config
from types import SimpleNamespace

from src.db.database import Database
from src.db.models import Target, TargetEmbedding, FaceEvent, Camera, utc_now
from src.notifications.config import EmailConfig
from src.notifications.service import NotificationService
from src.notifications.alerts import router
from src.recognition.target_matcher import target_manager
from src.recognition.target_selection import restore_persisted_targets, set_persisted_target_selection


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "audit.db").as_posix()
    monkeypatch.setenv("DATT_DATABASE_URL", url)
    monkeypatch.setenv("DATT_REQUIRE_PERSISTENCE", "0")
    monkeypatch.delenv("DATT_EMAIL_HOST", raising=False)
    command.upgrade(Config("src/db/alembic.ini"), "head")
    db = Database(url)
    target_manager.clear()
    yield db
    target_manager.clear()
    db.dispose()


def test_restore_persisted_targets_on_startup(audit_db):
    """Test that active targets with embeddings are restored to memory on startup."""
    active_id = uuid4()
    inactive_id = uuid4()
    fake_vec = np.random.randn(512).astype(np.float32).tolist()

    with audit_db.transaction() as s:
        # Active target with embedding
        t_active = Target(
            id=active_id,
            name="John Doe",
            target_type="face",
            active=True,
            reference_metadata={"selected": True, "embedding_model": "adaface_ir50_ms1mv2"}
        )
        s.add(t_active)
        s.flush()

        emb = TargetEmbedding(
            target_id=active_id,
            model_name="adaface_ir50_ms1mv2",
            embedding=fake_vec
        )
        s.add(emb)

        # Inactive target
        t_inactive = Target(
            id=inactive_id,
            name="Jane Doe",
            target_type="face",
            active=False,
            reference_metadata={"selected": True}
        )
        s.add(t_inactive)

    assert len(target_manager._targets) == 0

    # Execute restore
    restored_count = restore_persisted_targets()
    assert restored_count == 1
    assert str(active_id) in target_manager._targets
    assert str(inactive_id) not in target_manager._targets

    target_obj = target_manager._targets[str(active_id)]
    assert target_obj.name == "John Doe"
    assert target_obj.is_selected is True
    assert target_obj.has_face is True
    assert target_obj.embedding_model == "adaface_ir50_ms1mv2"
    assert target_obj.face_embedding is not None
    assert len(target_obj.face_embedding) == 512
    # Check L2 normalization
    norm = np.linalg.norm(target_obj.face_embedding)
    assert np.isclose(norm, 1.0, atol=1e-4)


def test_set_persisted_target_selection_restores_embedding(audit_db):
    """Test toggling selection dynamically restores embedding from TargetEmbedding table."""
    tid = uuid4()
    fake_vec = np.random.randn(512).astype(np.float32).tolist()

    with audit_db.transaction() as s:
        t = Target(
            id=tid,
            name="Alice",
            target_type="face",
            active=True,
            reference_metadata={"embedding_model": "adaface_ir50_ms1mv2"}
        )
        s.add(t)
        s.flush()
        emb = TargetEmbedding(
            target_id=tid,
            model_name="adaface_ir50_ms1mv2",
            embedding=fake_vec
        )
        s.add(emb)

    # User selects target in UI
    success = set_persisted_target_selection(str(tid), True)
    assert success is True
    assert str(tid) in target_manager._targets
    assert target_manager._targets[str(tid)].is_selected is True
    assert target_manager._targets[str(tid)].has_face is True
    assert target_manager._targets[str(tid)].face_embedding is not None

    # User deselects target in UI
    success_desel = set_persisted_target_selection(str(tid), False)
    assert success_desel is True
    assert target_manager._targets[str(tid)].is_selected is False
    # Target still retains its embedding in memory so re-enabling doesn't lose it
    assert target_manager._targets[str(tid)].face_embedding is not None


def test_alert_api_exposes_latency_timestamps_immediately(audit_db):
    """Test that /api/alerts immediately returns PENDING alert with latency metrics."""
    tid = uuid4()
    event_id = uuid4()
    confirmed_at = "2026-10-16T12:00:00.100000+00:00"
    persisted_at = "2026-10-16T12:00:00.150000+00:00"

    with audit_db.transaction() as s:
        s.add(Camera(registry_key="gate", name="Main gate", source_type="rtsp", source="rtsp://private"))
        t = Target(id=tid, name="Bob", target_type="face", active=True)
        s.add(t)
        s.flush()

        event = FaceEvent(
            id=event_id,
            target_id=tid,
            decision="FACE_MATCH",
            similarity=0.89,
            created_at=utc_now(),
            face_crop_path="data/events/crop.jpg"
        )
        s.add(event)
        s.flush()

        config = EmailConfig(
            host="smtp.example.invalid",
            username="user",
            password="pwd",
            sender="no-reply@example.invalid",
            recipients=("ops@example.invalid",),
            cooldown=300
        )
        service = NotificationService(audit_db, config, {})
        match = SimpleNamespace(camera_id="gate", target_name="Bob", metadata={"event_confirmed_at": confirmed_at})

        # Enqueue with latency timestamps
        service.enqueue_face(
            s,
            event,
            match,
            event_persisted_at=persisted_at
        )

    # Query API
    app = FastAPI()
    router._email_config = config
    app.include_router(router)

    with TestClient(app) as client:
        res = client.get("/api/alerts").json()
        assert res["total"] == 1
        alert = res["alerts"][0]
        assert alert["status"] == "PENDING"
        assert alert["event_id"] == str(event_id)
        assert alert["target_name"] == "Bob"
        assert alert["event_confirmed_at"] == confirmed_at
        assert alert["event_persisted_at"] == persisted_at
        assert alert["alert_available_at"] is not None
        # Confirm ISO format timestamp
        datetime.fromisoformat(alert["alert_available_at"])
