"""Unit and integration tests for configurable Crowd Alert Threshold flow.

Verifies:
Case 1: crowd_threshold = 50, person_count = 49 -> No Crowd Event
Case 2: crowd_threshold = 50, person_count = 50 -> Crowd Event
Case 3: crowd_threshold = 30, person_count = 29 -> No Crowd Event
Case 4: crowd_threshold = 30, person_count = 30 -> Crowd Event
Case 5: Change Settings: 50 -> 20, person_count = 25 -> Crowd Event with configured value
Case 6: Invalid value: crowd_threshold = 0 -> Validation error
And preserves existing Crowd duration, cooldown, and deduplication behavior.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.config.settings import (
    DEFAULT_CROWD_THRESHOLD,
    get_crowd_threshold,
    reset_settings_cache,
    set_crowd_threshold,
)
from src.events.policy import PEOPLE_DURATION_THRESHOLD, ThresholdEpisodes
from src.ui.web_server import app


@pytest.fixture(autouse=True)
def clean_settings():
    """Ensure clean in-memory settings cache before and after every test."""
    reset_settings_cache(DEFAULT_CROWD_THRESHOLD)
    yield
    reset_settings_cache(DEFAULT_CROWD_THRESHOLD)


def test_case_1_threshold_50_count_49_no_event():
    """Case 1: crowd_threshold = 50, person_count = 49 -> Expected: No Crowd Event."""
    episodes = ThresholdEpisodes()
    set_crowd_threshold(50)

    # Below threshold at start
    assert episodes.people("cam_1", count=49, now=0.0, wall=1000.0) is None
    # Still below threshold even after duration exceeds 180s
    assert episodes.people("cam_1", count=49, now=200.0, wall=1200.0) is None
    assert ("cam_1", None) not in episodes.crowds


def test_case_2_threshold_50_count_50_crowd_event():
    """Case 2: crowd_threshold = 50, person_count = 50 -> Expected: Crowd Event."""
    episodes = ThresholdEpisodes()
    set_crowd_threshold(50)

    # Count reaches exactly threshold 50 -> episode starts, but duration not yet met
    assert episodes.people("cam_1", count=50, now=0.0, wall=1000.0) is None
    assert episodes.people("cam_1", count=50, now=100.0, wall=1100.0) is None

    # Sustained for >= 180 seconds -> triggers crowd event
    event = episodes.people("cam_1", count=50, now=185.0, wall=1185.0)
    assert event is not None
    assert event["event_type"] == "CROWD_THRESHOLD"
    assert event["people_count"] == 50
    assert event["threshold"] == 50
    assert event["duration_seconds"] == 185.0


def test_case_3_threshold_30_count_29_no_event():
    """Case 3: crowd_threshold = 30, person_count = 29 -> Expected: No Crowd Event."""
    episodes = ThresholdEpisodes()
    set_crowd_threshold(30)

    assert episodes.people("cam_1", count=29, now=0.0, wall=1000.0) is None
    assert episodes.people("cam_1", count=29, now=300.0, wall=1300.0) is None
    assert ("cam_1", None) not in episodes.crowds


def test_case_4_threshold_30_count_30_crowd_event():
    """Case 4: crowd_threshold = 30, person_count = 30 -> Expected: Crowd Event."""
    episodes = ThresholdEpisodes()
    set_crowd_threshold(30)

    assert episodes.people("cam_1", count=30, now=0.0, wall=1000.0) is None
    event = episodes.people("cam_1", count=30, now=180.0, wall=1180.0)
    assert event is not None
    assert event["event_type"] == "CROWD_THRESHOLD"
    assert event["people_count"] == 30
    assert event["threshold"] == 30


def test_case_5_dynamic_settings_change_50_to_20_count_25_triggers():
    """Case 5: Change Settings: 50 -> 20. Then: person_count = 25 -> Expected: Crowd Event."""
    episodes = ThresholdEpisodes()
    set_crowd_threshold(50)

    # With threshold=50, 25 people does NOT trigger
    assert episodes.people("cam_1", count=25, now=0.0, wall=1000.0) is None
    assert episodes.people("cam_1", count=25, now=200.0, wall=1200.0) is None

    # Now change settings to 20
    set_crowd_threshold(20)
    assert get_crowd_threshold() == 20

    # With new threshold 20, 25 people starts and triggers episode
    assert episodes.people("cam_1", count=25, now=300.0, wall=1300.0) is None
    event = episodes.people("cam_1", count=25, now=485.0, wall=1485.0)
    assert event is not None
    assert event["event_type"] == "CROWD_THRESHOLD"
    assert event["people_count"] == 25
    assert event["threshold"] == 20


def test_case_6_invalid_values_validation():
    """Case 6: Invalid value: crowd_threshold = 0 or negative -> Expected: Validation error."""
    with pytest.raises(ValueError, match="crowd_threshold must be an integer >= 1"):
        set_crowd_threshold(0)

    with pytest.raises(ValueError, match="crowd_threshold must be an integer >= 1"):
        set_crowd_threshold(-5)

    with pytest.raises(ValueError, match="crowd_threshold must be an integer >= 1"):
        set_crowd_threshold(True)  # bool is subclass of int in Python, must be rejected

    with pytest.raises(ValueError, match="crowd_threshold must be an integer >= 1"):
        set_crowd_threshold("50")  # type: ignore


def test_api_settings_get_and_patch():
    """Verify HTTP GET /api/settings and PATCH /api/settings endpoints."""
    client = TestClient(app)

    # 1. GET settings returns default or current value
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "crowd_threshold" in data
    assert isinstance(data["crowd_threshold"], int)

    # 2. PATCH settings with valid threshold
    patch_resp = client.patch("/api/settings", json={"crowd_threshold": 35})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["crowd_threshold"] == 35
    assert get_crowd_threshold() == 35

    # 3. GET reflects updated threshold
    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    assert get_resp.json()["crowd_threshold"] == 35

    # 4. PATCH with invalid value 0 returns 422
    err_resp = client.patch("/api/settings", json={"crowd_threshold": 0})
    assert err_resp.status_code == 422

    # 5. PATCH with invalid type returns 422
    err_resp2 = client.patch("/api/settings", json={"crowd_threshold": "not_a_number"})
    assert err_resp2.status_code == 422


def test_crowd_cooldown_and_deduplication():
    """Verify that deduplication (once per episode) and reset on drop below threshold still work."""
    episodes = ThresholdEpisodes()
    set_crowd_threshold(30)

    # Start episode at t=0
    assert episodes.people("cam_1", count=35, now=0.0, wall=1000.0) is None

    # Emit crowd event at t=180
    first = episodes.people("cam_1", count=35, now=180.0, wall=1180.0)
    assert first is not None

    # While still crowded (>30), subsequent calls are deduplicated (return None)
    assert episodes.people("cam_1", count=35, now=200.0, wall=1200.0) is None
    assert episodes.people("cam_1", count=40, now=250.0, wall=1250.0) is None

    # Count drops below threshold (28 < 30) -> resets episode
    assert episodes.people("cam_1", count=28, now=260.0, wall=1260.0) is None
    assert ("cam_1", None) not in episodes.crowds

    # Count rises again (32 >= 30) -> starts NEW episode
    assert episodes.people("cam_1", count=32, now=300.0, wall=1300.0) is None
    second = episodes.people("cam_1", count=32, now=480.0, wall=1480.0)
    assert second is not None
    assert second["episode"] != first["episode"]


def test_deterministic_singleton_persistence():
    """Verify that SystemSetting always resolves to exactly ONE authoritative row."""
    from src.db.database import Database
    from src.db.models import SystemSetting
    from sqlalchemy import select

    db = Database()
    # Update threshold multiple times
    set_crowd_threshold(22, db=db)
    set_crowd_threshold(33, db=db)
    set_crowd_threshold(44, db=db)

    with db.transaction() as session:
        all_rows = list(session.scalars(select(SystemSetting)).all())
        assert len(all_rows) == 1, f"Must have exactly 1 singleton row, found {len(all_rows)}"
        assert all_rows[0].crowd_threshold == 44

    # Reset cache and verify fresh DB read resolves the exact same authoritative value
    reset_settings_cache()
    assert get_crowd_threshold(db=db) == 44


def test_persistence_failure_does_not_update_cache():
    """Required Test Case A: Database transaction failure re-raises and preserves in-memory cache."""
    from unittest.mock import MagicMock

    set_crowd_threshold(50)
    assert get_crowd_threshold() == 50

    mock_db = MagicMock()
    mock_db.transaction.side_effect = RuntimeError("Simulated DB connection failure")

    with pytest.raises(RuntimeError, match="Simulated DB connection failure"):
        set_crowd_threshold(20, db=mock_db)

    # Invariant: Cache must NEVER represent a value that failed to persist
    assert get_crowd_threshold() == 50


def test_api_patch_db_failure_returns_error_and_preserves_state():
    """Required Test Case B: DB write failure during PATCH /api/settings returns non-2xx and preserves state."""
    from unittest.mock import patch
    from sqlalchemy import select
    from src.db.database import Database
    from src.db.models import SystemSetting

    # Initial persisted value: 50
    set_crowd_threshold(50)
    assert get_crowd_threshold() == 50

    client = TestClient(app)

    with patch("src.db.database.Database.transaction") as mock_transaction:
        mock_transaction.side_effect = RuntimeError("Simulated DB write failure")

        resp = client.patch("/api/settings", json={"crowd_threshold": 20})
        # HTTP response is not 2xx (returns 500)
        assert resp.status_code != 200
        assert resp.status_code == 500
        # API does not report crowd_threshold = 20 as successfully saved
        assert resp.json().get("crowd_threshold") != 20

    # In-memory cache remains unchanged (50)
    assert get_crowd_threshold() == 50

    # Persisted value remains unchanged in DB (50)
    db = Database()
    with db.transaction() as session:
        setting = session.scalars(select(SystemSetting)).first()
        assert setting is not None
        assert setting.crowd_threshold == 50


def test_successful_save_persists_to_db_and_cache():
    """Required Test Case C: Successful save (50 -> 20) updates DB, cache, and returns 20."""
    from sqlalchemy import select
    from src.db.database import Database
    from src.db.models import SystemSetting

    # Initial persisted value: 50
    set_crowd_threshold(50)
    assert get_crowd_threshold() == 50

    client = TestClient(app)
    resp = client.patch("/api/settings", json={"crowd_threshold": 20})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["crowd_threshold"] == 20

    # Cache is updated to 20
    assert get_crowd_threshold() == 20

    # DB is updated to 20
    db = Database()
    with db.transaction() as session:
        setting = session.scalars(select(SystemSetting)).first()
        assert setting is not None
        assert setting.crowd_threshold == 20


