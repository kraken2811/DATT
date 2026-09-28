"""Explicit engine lifecycle and transaction boundaries (no runtime imports)."""

import os
from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


class Database:
    def __init__(self, url: str | None = None, *, echo: bool = False):
        url = url or os.environ.get("DATT_DATABASE_URL", "sqlite:///datt.db")
        parsed = make_url(url)
        if parsed.drivername in ("postgres", "postgresql"):
            parsed = parsed.set(drivername="postgresql+psycopg")
        self.engine = create_engine(parsed, echo=echo, pool_pre_ping=True)
        if parsed.get_backend_name() == "sqlite":
            @event.listens_for(self.engine, "connect")
            def configure_sqlite(connection, _record):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """One session per unit of work; commit on success, rollback on error.

        Sessions must never be shared across threads. Repository methods flush
        but do not commit, allowing related events to be persisted atomically.
        """
        with self._sessions.begin() as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()
