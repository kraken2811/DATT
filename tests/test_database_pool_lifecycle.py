from sqlalchemy.pool import NullPool
from src.db.database import Database

def test_postgres_does_not_retain_idle_connections():
    db = Database('postgresql://test:test@localhost/test')
    try:
        assert isinstance(db.engine.pool, NullPool)
    finally:
        db.dispose()

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
