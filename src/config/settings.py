"""Centralized runtime system settings and configuration cache for DATT.

Manages dynamic settings such as crowd_threshold with high-performance in-memory caching
to prevent per-frame database queries.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

logger = logging.getLogger("datt.config.settings")

DEFAULT_CROWD_THRESHOLD: int = 50
_CACHE_TTL_SECONDS: float = 5.0
GLOBAL_SETTINGS_ID: UUID = UUID("00000000-0000-0000-0000-000000000001")

_settings_lock = threading.Lock()
_cached_crowd_threshold: int = DEFAULT_CROWD_THRESHOLD
_cache_loaded_at: float = 0.0


def _get_authoritative_setting(session: Any) -> Any | None:
    """Resolve the single authoritative SystemSetting record deterministically."""
    from src.db.models import SystemSetting

    setting = session.get(SystemSetting, GLOBAL_SETTINGS_ID)
    if setting is not None:
        return setting
    return session.scalars(
        select(SystemSetting).order_by(SystemSetting.created_at.asc()).limit(1)
    ).first()


def get_crowd_threshold(db: Any | None = None) -> int:
    """Retrieve the active crowd alert threshold.

    Uses an in-memory cache to guarantee zero database overhead on realtime video frames.
    Falls back gracefully to DEFAULT_CROWD_THRESHOLD (50) if the database is unavailable.
    """
    global _cached_crowd_threshold, _cache_loaded_at
    now = time.monotonic()
    with _settings_lock:
        if now - _cache_loaded_at < _CACHE_TTL_SECONDS:
            return _cached_crowd_threshold

    try:
        from src.db.database import Database

        database = db or Database()
        with database.transaction() as session:
            setting = _get_authoritative_setting(session)
            val = (
                int(setting.crowd_threshold)
                if setting and setting.crowd_threshold is not None
                else DEFAULT_CROWD_THRESHOLD
            )
            with _settings_lock:
                _cached_crowd_threshold = val
                _cache_loaded_at = now
            return val
    except Exception as exc:
        logger.debug("System settings unavailable from database: %s", exc)
        with _settings_lock:
            return _cached_crowd_threshold


def set_crowd_threshold(threshold: int, db: Any | None = None) -> int:
    """Update the crowd alert threshold in the database and invalidate the in-memory cache.

    Guarantees deterministic singleton resolution and purges any duplicate rows.

    Args:
        threshold: Minimum detected person count to trigger a crowd alert (>= 1).
        db: Optional Database instance.

    Returns:
        int: The validated, saved crowd threshold.

    Raises:
        ValueError: If threshold is not an integer or is less than 1.
    """
    global _cached_crowd_threshold, _cache_loaded_at

    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
        raise ValueError("crowd_threshold must be an integer >= 1")

    try:
        from src.db.database import Database
        from src.db.models import SystemSetting, utc_now

        database = db or Database()
        with database.transaction() as session:
            setting = _get_authoritative_setting(session)
            if setting is None:
                setting = SystemSetting(id=GLOBAL_SETTINGS_ID, crowd_threshold=threshold)
                session.add(setting)
            else:
                setting.crowd_threshold = threshold
                setting.updated_at = utc_now()
                # Deduplicate any accidental extra rows
                extra_rows = session.scalars(
                    select(SystemSetting).where(SystemSetting.id != setting.id)
                ).all()
                for extra in extra_rows:
                    session.delete(extra)
            session.flush()
    except Exception:
        logger.exception("Could not persist crowd threshold to database")
        raise

    with _settings_lock:
        _cached_crowd_threshold = threshold
        _cache_loaded_at = time.monotonic()

    return threshold


def reset_settings_cache(threshold: int = DEFAULT_CROWD_THRESHOLD) -> None:
    """Reset the in-memory cache for deterministic unit test execution."""
    global _cached_crowd_threshold, _cache_loaded_at
    with _settings_lock:
        _cached_crowd_threshold = threshold
        _cache_loaded_at = 0.0
