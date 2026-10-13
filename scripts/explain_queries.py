"""Run EXPLAIN (ANALYZE, BUFFERS) on key queries in read-only transaction."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func, text
from src.db.database import Database
from src.db.models import Camera, Target, VehicleWatchlist, Notification
from src.event_center.service import projection
from src.notifications.alerts import query as alert_query

def run_explain():
    db = Database()
    print("Running EXPLAIN ANALYZE on PostgreSQL backend...")

    with db.transaction() as session:
        # Check backend
        backend = session.bind.dialect.name
        if backend != "postgresql":
            print(f"Backend is {backend}, skipping PostgreSQL EXPLAIN ANALYZE.")
            return

        print("\n" + "="*80)
        print("1. EVENT CENTER: Full UNION ALL count query")
        print("="*80)
        events = projection()
        q = select(events)
        cnt_stmt = select(func.count()).select_from(q.order_by(None).subquery())
        compiled = cnt_stmt.compile(session.bind, compile_kwargs={"literal_binds": True})
        plan = session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled}")).fetchall()
        for row in plan:
            print(row[0])

        print("\n" + "="*80)
        print("2. EVENT CENTER: Paginated UNION ALL (page 1, limit 5) without count")
        print("="*80)
        paged_stmt = select(events).order_by(events.c.timestamp.desc(), events.c.event_type, events.c.id).limit(5)
        compiled_paged = paged_stmt.compile(session.bind, compile_kwargs={"literal_binds": True})
        plan = session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled_paged}")).fetchall()
        for row in plan:
            print(row[0])

        print("\n" + "="*80)
        print("3. ALERT CENTER: Joined count query")
        print("="*80)
        from src.db.models import FaceEvent, PlateEvent
        joined_count = select(func.count()).select_from(
            select(Notification, FaceEvent, PlateEvent, Target, VehicleWatchlist)
            .outerjoin(FaceEvent, Notification.event_id == FaceEvent.id)
            .outerjoin(PlateEvent, Notification.plate_event_id == PlateEvent.id)
            .outerjoin(Target, FaceEvent.target_id == Target.id)
            .outerjoin(VehicleWatchlist, Notification.vehicle_watchlist_id == VehicleWatchlist.id)
            .subquery()
        )
        compiled_ac = joined_count.compile(session.bind, compile_kwargs={"literal_binds": True})
        plan = session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled_ac}")).fetchall()
        for row in plan:
            print(row[0])

        print("\n" + "="*80)
        print("4. ALERT CENTER: Simple notification count query (optimized)")
        print("="*80)
        simple_count = select(func.count(Notification.id))
        compiled_sc = simple_count.compile(session.bind, compile_kwargs={"literal_binds": True})
        plan = session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled_sc}")).fetchall()
        for row in plan:
            print(row[0])

        print("\n" + "="*80)
        print("5. CAMERAS: Current select all vs SQL paginated")
        print("="*80)
        cam_all = select(Camera).order_by(Camera.created_at.desc())
        compiled_cam = cam_all.compile(session.bind, compile_kwargs={"literal_binds": True})
        plan = session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS) {compiled_cam}")).fetchall()
        for row in plan:
            print(row[0])

    db.dispose()

if __name__ == "__main__":
    run_explain()
