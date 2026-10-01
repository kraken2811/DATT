"""Deployment preflight and redacted persistence diagnostic: python -m src.persistence."""
import argparse
import io
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import inspect, text
from alembic.config import Config
from alembic.script import ScriptDirectory

from src.db.database import Database
from src.storage import get_storage, ExternalStorageBackend, SupabaseStorageBackend

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = {"video_sources", "targets", "target_embeddings", "detection_events",
                   "vehicle_events", "plate_events", "face_events", "business_events",
                   "vehicle_passages", "cameras", "zones"}


def audit(*, require_external=False):
    result = dict(database_type="unconfigured", database_connected=False,
                  database_host="unconfigured", alembic_revision="unknown",
                  pgvector_version="unknown", storage_backend=os.getenv("DATT_STORAGE_BACKEND", "local"),
                  storage_connected=False, video_sources_count="unknown", targets_count="unknown",
                  local_runtime_is_disposable=True)
    errors = []
    db = None
    try:
        if require_external and not os.getenv("DATT_DATABASE_URL"):
            raise RuntimeError("DATT_DATABASE_URL required")
        db = Database()
        result["database_type"] = db.engine.dialect.name
        result["database_host"] = db.engine.url.host or "local"
        if require_external and db.engine.dialect.name != "postgresql":
            raise RuntimeError("PostgreSQL required")
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            result["database_connected"] = True
            if db.engine.dialect.name == "postgresql":
                result["pgvector_version"] = conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")) or "missing"
                if result["pgvector_version"] == "missing":
                    errors.append("pgvector_missing")
            revisions = set(conn.scalars(text("SELECT version_num FROM alembic_version")))
            result["alembic_revision"] = ",".join(sorted(revisions))
            heads = set(ScriptDirectory.from_config(Config(str(ROOT / "src/db/alembic.ini"))).get_heads())
            if revisions != heads:
                errors.append("migration_head_mismatch")
            if not REQUIRED_TABLES.issubset(inspect(conn).get_table_names()):
                errors.append("required_tables_missing")
            for table in ("video_sources", "targets"):
                result[table + "_count"] = conn.scalar(text("SELECT count(*) FROM " + table))
    except Exception as exc:
        # Driver exceptions may embed credentials or URLs: never print their text.
        errors.append("database_check_failed:" + type(exc).__name__)
    finally:
        if db:
            db.dispose()
    try:
        storage = get_storage()
        if require_external and not isinstance(storage, (ExternalStorageBackend, SupabaseStorageBackend)):
            raise RuntimeError("External storage required")
        key = "data/events/persistence_probe_" + uuid4().hex + ".bin"
        payload = os.urandom(32)
        try:
            storage.save(key, io.BytesIO(payload))
            assert storage.exists(key)
            with storage.open(key) as source:
                assert source.read() == payload
        finally:
            storage.delete(key)
        result["storage_connected"] = True
    except Exception as exc:
        errors.append("storage_check_failed:" + type(exc).__name__)
    return result, errors


def print_audit(result, errors):
    print("[DATT_PERSISTENCE_AUDIT]")
    for key, value in result.items():
        print(f"{key}={str(value).lower() if isinstance(value, bool) else value}")
    for error in errors:
        print("check_error=" + error)


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--require-external", action="store_true")
    args = parser.parse_args()
    result, errors = audit(require_external=args.require_external)
    print_audit(result, errors)
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
