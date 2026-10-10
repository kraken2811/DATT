"""Database engine/session lifecycle with a small bounded PostgreSQL pool.

PostgreSQL deployments previously used NullPool while request handlers created a
new ``Database()`` per request. That forced a new DBAPI/TLS/authenticated
connection on every transaction. A process-level engine now reuses at most a
small number of PostgreSQL connections. Set ``DATT_DB_POOL_ENABLED=0`` for an
A/B benchmark or emergency rollback to NullPool behavior.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import threading
from time import perf_counter

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from src.db.latency import add_metric


_ENGINE_LOCK = threading.Lock()
_SHARED_ENGINES: dict[tuple, Engine] = {}


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _normalize_url(url: str) -> URL:
    parsed = make_url(url)
    if parsed.drivername == "postgres":
        parsed = parsed.set(drivername="postgresql+psycopg")
    elif parsed.drivername == "postgresql":
        parsed = parsed.set(drivername="postgresql+psycopg")
    return parsed


def postgres_pool_settings() -> dict[str, int | bool]:
    """Return non-sensitive pool settings for diagnostics/tests."""
    return {
        "enabled": _bool_env("DATT_DB_POOL_ENABLED", True),
        "pool_size": _int_env("DATT_DB_POOL_SIZE", 2, 1, 8),
        "max_overflow": _int_env("DATT_DB_MAX_OVERFLOW", 1, 0, 4),
        "pool_timeout": _int_env("DATT_DB_POOL_TIMEOUT_SECONDS", 5, 1, 60),
        "pool_recycle": _int_env("DATT_DB_POOL_RECYCLE_SECONDS", 300, 30, 3600),
    }


def _instrument_engine(engine: Engine) -> None:
    if getattr(engine, "_datt_latency_instrumented", False):
        return

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        context._datt_query_started = perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        started = getattr(context, "_datt_query_started", None)
        if started is not None:
            add_metric("db_query_ms", (perf_counter() - started) * 1000.0)

    engine._datt_latency_instrumented = True


def _create_engine(parsed: URL, *, echo: bool, shared_postgres: bool) -> Engine:
    options: dict = {"pool_pre_ping": True}
    if parsed.get_backend_name() == "postgresql":
        pool = postgres_pool_settings()
        if shared_postgres and pool["enabled"]:
            options.update(
                pool_size=pool["pool_size"],
                max_overflow=pool["max_overflow"],
                pool_timeout=pool["pool_timeout"],
                pool_recycle=pool["pool_recycle"],
                pool_use_lifo=True,
            )
        else:
            options["poolclass"] = NullPool
    engine = create_engine(parsed, echo=echo, **options)
    _instrument_engine(engine)
    return engine


def _shared_postgres_engine(parsed: URL, *, echo: bool) -> Engine:
    settings = postgres_pool_settings()
    key = (
        parsed,
        bool(echo),
        settings["enabled"],
        settings["pool_size"],
        settings["max_overflow"],
        settings["pool_timeout"],
        settings["pool_recycle"],
    )
    with _ENGINE_LOCK:
        engine = _SHARED_ENGINES.get(key)
        if engine is None:
            engine = _create_engine(parsed, echo=echo, shared_postgres=True)
            _SHARED_ENGINES[key] = engine
        return engine


def dispose_shared_engines() -> None:
    """Explicit shutdown hook for tests/process termination."""
    with _ENGINE_LOCK:
        engines = list(_SHARED_ENGINES.values())
        _SHARED_ENGINES.clear()
    for engine in engines:
        engine.dispose()


class Database:
    def __init__(self, url: str | None = None, *, echo: bool = False):
        if not url:
            url = os.environ.get("DATT_DATABASE_URL")
        if not url and os.environ.get("DATT_REQUIRE_PERSISTENCE") == "1":
            raise RuntimeError("DATT_DATABASE_URL is required when DATT_REQUIRE_PERSISTENCE=1")
        url = url or "sqlite:///datt.db"
        parsed = _normalize_url(url)
        self._shared_engine = parsed.get_backend_name() == "postgresql" and postgres_pool_settings()["enabled"]
        if self._shared_engine:
            self.engine = _shared_postgres_engine(parsed, echo=echo)
        else:
            self.engine = _create_engine(parsed, echo=echo, shared_postgres=False)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def transaction(self):
        """Open one transaction and measure connection checkout separately.

        ``session.connection()`` deliberately forces pool checkout before yielding
        so ``db_connect_ms`` captures pool wait/pre-ping/new-connection cost rather
        than mixing it into the first SQL statement.
        """
        session: Session = self._sessions()
        try:
            with session.begin():
                started = perf_counter()
                session.connection()
                add_metric("db_connect_ms", (perf_counter() - started) * 1000.0)
                yield session
        finally:
            session.close()

    def dispose(self):
        # Request-scoped Database wrappers share the process PostgreSQL engine;
        # disposing here would destroy connection reuse. SQLite/NullPool engines
        # remain instance-owned and retain the previous lifecycle semantics.
        if not self._shared_engine:
            self.engine.dispose()
