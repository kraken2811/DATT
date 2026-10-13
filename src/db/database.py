import os
import logging
import threading
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

_shared_engines: dict[tuple[str, bool], tuple[Engine, sessionmaker]] = {}
_engine_lock = threading.Lock()


class Database:
    def __init__(self, url: str | None = None, *, echo: bool = False, shared: bool = True):
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
                            pass
        if not url:
            if os.environ.get("DATT_REQUIRE_PERSISTENCE") == "1":
                raise RuntimeError("DATT_DATABASE_URL is required; persistent targets, embeddings, video library and events are unavailable")
            logging.getLogger(__name__).warning(
                "DATT_DATABASE_URL missing: using local SQLite for development. "
                "Targets, embeddings, video library and event metadata will not survive runtime deletion. Run migrations explicitly."
            )
        url = url or "sqlite:///datt.db"
        parsed = make_url(url)
        if os.environ.get("DATT_REQUIRE_PERSISTENCE") == "1" and parsed.get_backend_name() not in ("postgres", "postgresql"):
            raise RuntimeError("Persistent deployment requires PostgreSQL; SQLite is only for local/test use")
        if parsed.drivername in ("postgres", "postgresql"):
            parsed = parsed.set(drivername="postgresql+psycopg")

        self._is_shared = shared
        self.url = parsed

        if shared:
            cache_key = (str(parsed), echo)
            with _engine_lock:
                if cache_key not in _shared_engines:
                    _shared_engines[cache_key] = self._create_engine_and_sessions(parsed, echo=echo)
                self.engine, self._sessions = _shared_engines[cache_key]
        else:
            self.engine, self._sessions = self._create_engine_and_sessions(parsed, echo=echo)

    @staticmethod
    def _create_engine_and_sessions(parsed, *, echo: bool = False) -> tuple[Engine, sessionmaker]:
        backend = parsed.get_backend_name()
        if backend == "postgresql":
            # Process-level bounded pool: eliminates repeated TCP/TLS/auth roundtrips
            # while strictly capping total pooler connections at 5 (+5 max overflow).
            engine = create_engine(
                parsed,
                echo=echo,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=5,
                pool_timeout=15.0,
                pool_recycle=300,
                pool_pre_ping=True,
            )
        else:
            engine = create_engine(parsed, echo=echo, pool_pre_ping=True)
            if backend == "sqlite":
                @event.listens_for(engine, "connect")
                def configure_sqlite(connection, _record):
                    cursor = connection.cursor()
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.execute("PRAGMA busy_timeout=5000")
                    cursor.close()

        sessions = sessionmaker(engine, expire_on_commit=False)
        return engine, sessions

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """One session per unit of work; commit on success, rollback on error.

        Sessions must never be shared across threads. Repository methods flush
        but do not commit, allowing related events to be persisted atomically.
        """
        with self._sessions.begin() as session:
            yield session

    def dispose(self) -> None:
        """Dispose the underlying engine if this instance owns an unshared engine.

        For shared instances (default), engine disposal is deferred to process
        termination or Database.dispose_shared() to preserve the warm pool.
        """
        if not self._is_shared:
            self.engine.dispose()

    @classmethod
    def dispose_shared(cls) -> None:
        """Explicitly dispose all shared engines (useful in test teardown)."""
        with _engine_lock:
            for engine, _ in _shared_engines.values():
                engine.dispose()
            _shared_engines.clear()
