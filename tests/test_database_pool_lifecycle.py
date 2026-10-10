from sqlalchemy.pool import NullPool, QueuePool
from src.db.database import Database, dispose_shared_engines, postgres_pool_settings


def test_postgres_reuses_small_process_engine(monkeypatch):
    monkeypatch.setenv('DATT_DB_POOL_ENABLED', '1')
    monkeypatch.setenv('DATT_DB_POOL_SIZE', '2')
    monkeypatch.setenv('DATT_DB_MAX_OVERFLOW', '1')
    dispose_shared_engines()
    first = Database('postgresql://test:test@localhost/test')
    second = Database('postgresql://test:test@localhost/test')
    try:
        assert first.engine is second.engine
        assert isinstance(first.engine.pool, QueuePool)
        settings = postgres_pool_settings()
        assert settings['pool_size'] == 2
        assert settings['max_overflow'] == 1
    finally:
        first.dispose()
        second.dispose()
        dispose_shared_engines()


def test_postgres_pool_can_be_disabled_for_ab_benchmark(monkeypatch):
    monkeypatch.setenv('DATT_DB_POOL_ENABLED', '0')
    dispose_shared_engines()
    db = Database('postgresql://test:test@localhost/test')
    try:
        assert isinstance(db.engine.pool, NullPool)
    finally:
        db.dispose()
        dispose_shared_engines()


def test_sqlite_memory_keeps_database_between_transactions(monkeypatch):
    from sqlalchemy import text
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '0')
    db = Database('sqlite:///:memory:')
    try:
        with db.transaction() as session:
            session.execute(text('CREATE TABLE demo (id INTEGER)'))
            session.execute(text('INSERT INTO demo VALUES (1)'))
        with db.transaction() as session:
            assert session.scalar(text('SELECT id FROM demo')) == 1
    finally:
        db.dispose()
