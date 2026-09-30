"""Alembic entry point; shares URL handling with the database layer."""
import os

from alembic import context
from sqlalchemy import JSON
from sqlalchemy.engine import make_url
from pgvector.sqlalchemy import Vector

from src.db.database import Database
from src.db.models import Base, UTCDateTime


def render_item(kind, obj, autogen_context):
    # Keep future revisions independent from application model implementations.
    if kind == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    if kind == "type" and isinstance(obj, JSON):
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return "sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')"
    if kind == "type" and isinstance(obj, Vector):
        autogen_context.imports.add("from pgvector.sqlalchemy import Vector")
        return f"Vector({obj.dim})"
    return False


def compare_type(context, inspected_column, metadata_column, inspected_type, metadata_type):
    # SQLite has no native VECTOR type and reflects Vector(N) as NUMERIC(precision=N)
    if isinstance(metadata_type, Vector) and context.connection and context.connection.dialect.name == "sqlite":
        return False
    return None

def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name == "alembic_version":
        return False
    return True


config = context.config
url = os.environ.get("DATT_DATABASE_URL")
if not url:
    from pathlib import Path
    env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATT_DATABASE_URL=") and len(line) > len("DATT_DATABASE_URL="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    url = val
                    break
url = url or config.get_main_option("sqlalchemy.url")
target_metadata = Base.metadata

if context.is_offline_mode():
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    context.configure(url=parsed, target_metadata=target_metadata, literal_binds=True, compare_type=compare_type, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()
else:
    database = Database(url)
    try:
        with database.engine.connect() as connection:
            kwargs = {}
            if connection.dialect.name == "postgresql":
                from sqlalchemy import text as sa_text
                schema = connection.scalar(sa_text("SELECT current_schema()"))
                if schema:
                    kwargs["version_table_schema"] = schema
            context.configure(connection=connection, target_metadata=target_metadata,
                              compare_type=compare_type, render_item=render_item,
                              include_object=include_object,
                              render_as_batch=connection.dialect.name == "sqlite",
                              **kwargs)
            with context.begin_transaction():
                context.run_migrations()
            connection.commit()
    finally:
        database.dispose()
