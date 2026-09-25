"""SQLite Event Storage & Snapshot Management for DATT.

Phase 4 Version 3: Camera Management & Event Logging.
Persists occupancy events and camera changes to data/events.db and stores
annotated JPEG snapshots in data/events/.
"""

from datetime import datetime
from pathlib import Path
import sqlite3
import threading
from typing import Any

import cv2
import numpy as np

from src.utils.logger import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "events.db"
DEFAULT_SNAPSHOT_DIR = PROJECT_ROOT / "data" / "events"


class EventStorage:
    """Thread-safe SQLite storage for people count events and snapshots."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        snapshot_dir: Path | str | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir else DEFAULT_SNAPSHOT_DIR
        self._lock = threading.Lock()

        self._init_storage()

    def _init_storage(self) -> None:
        """Create database file, parent directories, and schema table."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        camera_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        old_value INTEGER NOT NULL,
                        new_value INTEGER NOT NULL,
                        snapshot_path TEXT
                    );
                    """
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_camera ON events(camera_id);"
                )
                conn.commit()

    def save_event(
        self,
        timestamp: str,
        camera_id: str,
        event_type: str,
        old_value: int,
        new_value: int,
        annotated_frame: np.ndarray | None = None,
    ) -> tuple[int, str]:
        """Save event record and optional image snapshot to SQLite.

        Args:
            timestamp: Formatted timestamp string (e.g. '2026-09-22 10:30:20').
            camera_id: Identifier of the camera.
            event_type: Event category (e.g. 'PEOPLE_COUNT_CHANGED').
            old_value: Previous occupancy count.
            new_value: New occupancy count.
            annotated_frame: Optional image to save as snapshot.

        Returns:
            tuple[int, str]: (event_id, snapshot_relative_path).
        """
        snapshot_rel_path = ""
        if annotated_frame is not None:
            # File naming: 20260922_103020_camera01.jpg
            ts_compact = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
            filename = f"{ts_compact}_{camera_id}.jpg"
            dest_path = self.snapshot_dir / filename
            try:
                cv2.imwrite(str(dest_path), annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                # Store relative path for portability across machines/Colab
                snapshot_rel_path = f"data/events/{filename}"
            except Exception as exc:
                logger.warning("EventStorage: Failed to save snapshot image: %s", exc)

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO events (timestamp, camera_id, event_type, old_value, new_value, snapshot_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (timestamp, camera_id, event_type, old_value, new_value, snapshot_rel_path),
                )
                event_id = cursor.lastrowid or 0
                conn.commit()

        return event_id, snapshot_rel_path

    def get_recent_events(
        self,
        limit: int = 20,
        camera_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch the most recent events ordered by timestamp descending."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                if camera_id:
                    cursor.execute(
                        """
                        SELECT id, timestamp, camera_id, event_type, old_value, new_value, snapshot_path
                        FROM events
                        WHERE camera_id = ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (camera_id, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT id, timestamp, camera_id, event_type, old_value, new_value, snapshot_path
                        FROM events
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (limit,),
                    )

                rows = cursor.fetchall()
                return [dict(row) for row in rows]

    def get_event_count_today(self) -> int:
        """Count total events logged today (local date)."""
        today_prefix = datetime.now().strftime("%Y-%m-%d") + "%"
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM events WHERE timestamp LIKE ?",
                    (today_prefix,),
                )
                res = cursor.fetchone()
                return res[0] if res else 0


# Global singleton instance
event_storage = EventStorage()
