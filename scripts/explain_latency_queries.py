"""EXPLAIN ANALYZE the read-only DATT queries involved in navigation latency.

This script never prints DATABASE_URL or credentials. It executes only SELECT
statements and PostgreSQL EXPLAIN (ANALYZE, BUFFERS) around those SELECTs.
"""
from __future__ import annotations

from sqlalchemy import select, func, text

from src.db.database import Database
from src.db.models import Camera, Notification, Target, VehicleWatchlist
from src.event_center.service import projection


def explain(session, name, statement):
    if session.bind.dialect.name != 'postgresql':
        raise RuntimeError('EXPLAIN latency audit requires PostgreSQL')
    compiled = statement.compile(
        dialect=session.bind.dialect,
        compile_kwargs={'literal_binds': True},
    )
    sql = str(compiled).strip()
    if not sql.upper().startswith('SELECT'):
        raise RuntimeError('Refusing to EXPLAIN a non-SELECT statement')
    rows = session.execute(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) ' + sql)).scalars().all()
    print(f'\n=== {name} ===')
    for row in rows:
        print(row)


def main():
    db = Database()
    try:
        with db.transaction() as session:
            events = projection()
            explain(session, 'CAMERAS_PAGE_25', select(Camera).order_by(Camera.created_at.desc()).limit(25))
            explain(session, 'CAMERAS_COUNT', select(func.count(Camera.id)))
            explain(session, 'TARGETS_PAGE_25', select(Target).where(Target.active.is_(True)).order_by(Target.created_at.desc()).limit(25))
            explain(session, 'VEHICLE_WATCHLIST_PAGE_25', select(VehicleWatchlist).order_by(VehicleWatchlist.created_at.desc()).limit(25))
            explain(session, 'ALERTS_COUNT', select(func.count(Notification.id)))
            explain(session, 'ALERTS_PAGE_25', select(Notification).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(25))
            explain(session, 'EVENT_CENTER_PAGE_25', select(events).order_by(events.c.timestamp.desc(), events.c.event_type, events.c.id).limit(25))
            explain(session, 'EVENT_CENTER_FULL_COUNT', select(func.count()).select_from(select(events).subquery()))
    finally:
        db.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
