"""One filtered relation for notification rows, totals and rankings (no writes)."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select

from src.db.models import Camera, FaceEvent, Notification, PlateEvent, Target, VehicleWatchlist
from src.notifications.alerts import camera_aliases
from src.watchlists.vehicles import normalize_plate


def plate_expression(column):
    value = func.upper(column)
    for separator in ('-', '.', ' ', '\t'):
        value = func.replace(value, separator, '')
    return value


def literal_pattern(value):
    return '%' + value.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def filtered_notifications(session, *, camera_id=None, status=None, event_type=None, event_id=None,
                           target_id=None, target_name=None, plate_number=None, search=None,
                           start_time=None, end_time=None):
    q = (select(Notification, FaceEvent, PlateEvent, Target, VehicleWatchlist)
         .outerjoin(FaceEvent, Notification.event_id == FaceEvent.id)
         .outerjoin(PlateEvent, Notification.plate_event_id == PlateEvent.id)
         .outerjoin(Target, FaceEvent.target_id == Target.id)
         .outerjoin(VehicleWatchlist, Notification.vehicle_watchlist_id == VehicleWatchlist.id))
    if status and status.strip().lower() != 'all':
        value = status.strip().lower()
        if value not in ('pending', 'sent', 'failed', 'suppressed'):
            raise ValueError('INVALID_STATUS')
        q = q.where(Notification.status == value)
    if event_type and event_type.strip().lower() != 'all':
        kind = event_type.strip().upper()
        if kind == 'FACE_WATCHLIST_MATCH':
            q = q.where(Notification.event_id.is_not(None))
        elif kind == 'VEHICLE_WATCHLIST_MATCH':
            q = q.where(Notification.plate_event_id.is_not(None))
        else:
            raise ValueError('INVALID_EVENT_TYPE')
    if event_id:
        prefix, _, value = event_id.strip().rpartition(':')
        ident = UUID(value if prefix else event_id.strip())
        if prefix:
            if prefix not in ('face', 'plate'):
                raise ValueError('INVALID_EVENT_ID')
            q = q.where((Notification.event_id if prefix == 'face' else Notification.plate_event_id) == ident)
        else:
            q = q.where(or_(Notification.event_id == ident, Notification.plate_event_id == ident))
    if target_id:
        ident = UUID(target_id.strip())
        q = q.where(or_(Notification.target_id == ident, FaceEvent.target_id == ident,
                        Notification.vehicle_watchlist_id == ident))
    if camera_id and camera_id.strip().lower() != 'all':
        keys = set(camera_aliases(camera_id.strip()))
        try:
            ids = [UUID(camera_id.strip())]
        except ValueError:
            ids = []
        cameras = session.scalars(select(Camera).where(or_(Camera.registry_key.in_(keys), Camera.id.in_(ids))))
        for cam in cameras:
            keys.update(k for k in (cam.registry_key, str(cam.id), cam.id.hex) if k)
        q = q.where(Notification.camera_id.in_(keys))
    bounds = []
    for value, column_op in ((start_time, Notification.created_at.__ge__), (end_time, Notification.created_at.__le__)):
        if value:
            dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            bounds.append(dt)
            q = q.where(column_op(dt))
    if len(bounds) == 2 and bounds[0] > bounds[1]:
        raise ValueError('INVALID_TIME_RANGE')
    if target_name and target_name.strip():
        pattern = literal_pattern(target_name)
        q = q.where(or_(Target.name.ilike(pattern, escape='\\'),
                        VehicleWatchlist.display_name.ilike(pattern, escape='\\')))
    if plate_number and plate_number.strip():
        plate = normalize_plate(plate_number)
        if not plate:
            raise ValueError('INVALID_PLATE')
        q = q.where(or_(PlateEvent.normalized_plate == plate,
                        plate_expression(PlateEvent.plate_text) == plate,
                        plate_expression(VehicleWatchlist.plate_number) == plate))
    if search and search.strip():
        pattern = literal_pattern(search)
        columns = (Target.name, VehicleWatchlist.display_name, VehicleWatchlist.plate_number,
                   PlateEvent.plate_text, PlateEvent.normalized_plate, Notification.recipient, Notification.camera_id)
        q = q.where(or_(*(c.ilike(pattern, escape='\\') for c in columns)))
    return q


def status_totals(session, filtered):
    stmt = select(filtered.c.status, func.count()).group_by(filtered.c.status)
    counts = {str(status): int(count) for status, count in session.execute(stmt)}
    return {status: counts.get(status, 0) for status in ('sent', 'failed', 'pending', 'suppressed')}
