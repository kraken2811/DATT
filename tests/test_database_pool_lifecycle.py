from sqlalchemy.pool import QueuePool
from src.db.database import Database

def test_postgres_uses_bounded_shared_pool():
    db1 = Database('postgresql://test:test@localhost/test')
    db2 = Database('postgresql://test:test@localhost/test')
    try:
        assert isinstance(db1.engine.pool, QueuePool)
        assert db1.engine.pool.size() == 5
        assert db1.engine.pool._max_overflow == 5
        # Verify both instances share the process-level engine
        assert db1.engine is db2.engine
    finally:
        Database.dispose_shared()

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
        Database.dispose_shared()
