import os
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


class Database:
    def __init__(self, url: str | None = None, *, echo: bool = False):
        if not url:
            url = os.environ.get("DATT_DATABASE_URL")
        if not url:
            env_file = Path(__file__).resolve().parent.parent.parent / ".env"
            if env_file.is_file():
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("DATT_DATABASE_URL=") and len(line) > len("DATT_DATABASE_URL="):
                        val = line.split("=", 1)[1].strip().strip("'\"")
                        if val:
                            url = val
                            break
        url = url or "sqlite:///datt.db"
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
