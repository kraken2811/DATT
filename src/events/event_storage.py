"""SQLite Event Storage & Snapshot Management for DATT.

Phase 4 Version 3: Camera Management & Event Logging.
Persists occupancy events and camera changes to data/events.db and stores
annotated JPEG snapshots in data/events/.
"""

from datetime import datetime, timezone
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
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS vehicle_passages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        camera_id TEXT NOT NULL,
                        track_id INTEGER NOT NULL,
                        vehicle_type TEXT,
                        vehicle_color TEXT,
                        zone_id TEXT,
                        plate_text TEXT,
                        plate_status TEXT,
                        plate_confidence REAL,
                        direction TEXT,
                        first_seen REAL,
                        last_seen REAL,
                        duration REAL,
                        best_vehicle_path TEXT,
                        best_plate_path TEXT,
                        created_at TEXT
                    );
                    """
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_passages_track ON vehicle_passages(track_id);"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_passages_camera ON vehicle_passages(camera_id);"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_passages_plate ON vehicle_passages(plate_text);"
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
        try:
            from src.db.database import Database
            from src.db.repositories import BusinessEventRepository
            db = Database()
            if db.engine.url.get_backend_name() == "postgresql":
                with db.transaction() as session:
                    repo = BusinessEventRepository(session)
                    events = repo.query_events(camera_id=camera_id, limit=limit)
                    return [
                        {
                            "id": str(e.id),
                            "timestamp": e.event_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "camera_id": e.camera_id,
                            "event_type": e.event_type,
                            "old_value": e.track_id or 0,
                            "new_value": 1,
                            "snapshot_path": e.event_metadata.get("snapshot_path", "") if isinstance(e.event_metadata, dict) else "",
                        }
                        for e in events
                    ]
        except Exception as exc:
            logger.debug("EventStorage: PostgreSQL query fell back to SQLite: %s", exc)

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
        try:
            from src.db.database import Database
            from src.db.models import BusinessEvent
            from sqlalchemy import select, func
            db = Database()
            if db.engine.url.get_backend_name() == "postgresql":
                today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                with db.transaction() as session:
                    stmt = select(func.count(BusinessEvent.id)).where(BusinessEvent.event_time >= today_start)
                    cnt = session.scalar(stmt)
                    return int(cnt or 0)
        except Exception as exc:
            logger.debug("EventStorage: PostgreSQL count fell back to SQLite: %s", exc)

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


    def save_passage(self, passage: Any) -> int:
        """Save a finalized VehiclePassage record and best images to SQLite."""
        best_veh_path = ""
        best_plt_path = ""
        ts_compact = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]

        if getattr(passage, "best_vehicle_image", None) is not None and passage.best_vehicle_image.size > 0:
            fn = f"veh_{ts_compact}_{passage.camera_id}_t{passage.track_id}.jpg"
            dest = self.snapshot_dir / fn
            try:
                cv2.imwrite(str(dest), passage.best_vehicle_image, [cv2.IMWRITE_JPEG_QUALITY, 85])
                best_veh_path = f"data/events/{fn}"
            except Exception as e:
                logger.warning("EventStorage: Failed to save best vehicle image: %s", e)

        if getattr(passage, "best_plate_image", None) is not None and passage.best_plate_image.size > 0:
            fn = f"plate_{ts_compact}_{passage.camera_id}_t{passage.track_id}.jpg"
            dest = self.snapshot_dir / fn
            try:
                cv2.imwrite(str(dest), passage.best_plate_image, [cv2.IMWRITE_JPEG_QUALITY, 90])
                best_plt_path = f"data/events/{fn}"
            except Exception as e:
                logger.warning("EventStorage: Failed to save best plate image: %s", e)

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO vehicle_passages (
                        camera_id, track_id, vehicle_type, vehicle_color, zone_id,
                        plate_text, plate_status, plate_confidence, direction,
                        first_seen, last_seen, duration, best_vehicle_path, best_plate_path, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        passage.camera_id,
                        passage.track_id,
                        getattr(passage, "vehicle_type", "vehicle"),
                        getattr(passage, "vehicle_color", None),
                        getattr(passage, "zone_id", None),
                        getattr(passage, "plate_text", ""),
                        getattr(passage, "plate_status", "SEARCHING"),
                        float(getattr(passage, "plate_confidence", 0.0)),
                        getattr(passage, "direction", "UNKNOWN"),
                        float(getattr(passage, "first_seen", 0.0)),
                        float(getattr(passage, "last_seen", 0.0)),
                        float(getattr(passage, "duration", 0.0)),
                        best_veh_path,
                        best_plt_path,
                        created_at,
                    ),
                )
                conn.commit()
                return cursor.lastrowid or 0


# Global singleton instance
event_storage = EventStorage()
