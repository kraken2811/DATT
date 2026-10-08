"""Focused tests for the persisted target-selection API contract."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config

from src.db.database import Database
from src.db.models import Target
from src.recognition.target_matcher import target_manager
from src.recognition.target_selection import set_persisted_target_selection


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_selection_persists_and_survives_runtime_cache_refresh() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {
        "DATT_DATABASE_URL": "sqlite:///" + (Path(tmpdir) / "targets.db").as_posix(),
        "DATT_REQUIRE_PERSISTENCE": "0",
    }):
        command.upgrade(Config(str(PROJECT_ROOT / "src/db/alembic.ini")), "head")
        target_id = uuid4()
        db = Database()
        with db.transaction() as session:
            session.add(Target(
                id=target_id,
                name="Persisted target",
                target_type="person",
                embedding=None,
                reference_metadata={"clothing_color": "blue", "threshold": 0.45},
                image_path=None,
                active=True,
            ))

        target_manager.clear()
        assert set_persisted_target_selection(str(target_id), False) is True
        assert target_manager.get_target(str(target_id)).is_selected is False

        # Simulate a process restart: the DB remains the canonical selection state.
        target_manager.clear()
        with db.transaction() as session:
            stored = session.get(Target, target_id)
            assert stored.reference_metadata["selected"] is False

        assert set_persisted_target_selection(str(target_id), True) is True
        with db.transaction() as session:
            stored = session.get(Target, target_id)
            assert stored.reference_metadata["selected"] is True
        db.dispose()
        target_manager.clear()


def test_selection_rejects_missing_or_inactive_target() -> None:
    with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {
        "DATT_DATABASE_URL": "sqlite:///" + (Path(tmpdir) / "targets.db").as_posix(),
        "DATT_REQUIRE_PERSISTENCE": "0",
    }):
        command.upgrade(Config(str(PROJECT_ROOT / "src/db/alembic.ini")), "head")
        assert set_persisted_target_selection(str(uuid4()), True) is False
