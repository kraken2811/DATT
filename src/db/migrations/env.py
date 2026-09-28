"""Alembic entry point; shares URL handling with the database layer."""
import os

from alembic import context
from sqlalchemy import JSON
from sqlalchemy.engine import make_url

from src.db.database import Database
from src.db.models import Base, UTCDateTime


def render_item(kind, obj, autogen_context):
    # Keep future revisions independent from application model implementations.
    if kind == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    if kind == "type" and isinstance(obj, JSON):
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return "sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')"
    return False

config = context.config
url = os.environ.get("DATT_DATABASE_URL") or config.get_main_option("sqlalchemy.url")
target_metadata = Base.metadata

if context.is_offline_mode():
    parsed = make_url(url)
    if parsed.drivername in ("postgres", "postgresql"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    context.configure(url=parsed, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    database = Database(url)
    try:
        with database.engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata,
                              compare_type=True, render_item=render_item,
                              render_as_batch=connection.dialect.name == "sqlite")
            with context.begin_transaction():
                context.run_migrations()
    finally:
        database.dispose()
