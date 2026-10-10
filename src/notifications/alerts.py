"""Read-only Alert Center projection of the existing transactional outbox."""
from uuid import UUID
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, or_
from sqlalchemy.exc import SQLAlchemyError
from src.cameras.service import database
from src.db.models import Notification, FaceEvent, PlateEvent, Target, VehicleWatchlist, Camera
from .config import EmailConfig
from .errors import safe_error, ERROR_MESSAGES, RETRY_ERRORS

router = APIRouter()
EVENT_TYPES = ('FACE_WATCHLIST_MATCH', 'VEHICLE_WATCHLIST_MATCH')


def camera_aliases(value):
    try:
        ident = UUID(value)
        return (value, str(ident), ident.hex)
    except ValueError:
        return (value,)


def query(session, params, ident=None):
    q = (select(Notification, FaceEvent, PlateEvent, Target, VehicleWatchlist)
         .outerjoin(FaceEvent, Notification.event_id == FaceEvent.id)
         .outerjoin(PlateEvent, Notification.plate_event_id == PlateEvent.id)
         .outerjoin(Target, FaceEvent.target_id == Target.id)
         .outerjoin(VehicleWatchlist, Notification.vehicle_watchlist_id == VehicleWatchlist.id))
    if ident:
        try:
            q = q.where(Notification.id == UUID(ident))
        except ValueError:
            raise LookupError() from None
    status = params.get('status', '').lower()
    if status and status != 'all':
        if status not in ('pending', 'sent', 'failed', 'suppressed'):
            raise ValueError('INVALID_STATUS')
        q = q.where(Notification.status == status)
    kind = params.get('event_type')
    if kind and kind != 'all':
        if kind not in EVENT_TYPES:
            raise ValueError('INVALID_EVENT_TYPE')
        q = q.where(Notification.event_id.is_not(None) if kind == EVENT_TYPES[0]
                    else Notification.plate_event_id.is_not(None))
    camera = params.get('camera_id')
    if camera and camera != 'all':
        q = q.where(Notification.camera_id.in_(camera_aliases(camera)))
    search = (params.get('search') or params.get('q') or '').strip()
    if search:
        search_like = f"%{search}%"
        q = q.where(or_(
            Notification.recipient.ilike(search_like),
            Target.name.ilike(search_like),
            VehicleWatchlist.display_name.ilike(search_like),
            PlateEvent.plate_text.ilike(search_like),
            PlateEvent.normalized_plate.ilike(search_like),
            Notification.camera_id.ilike(search_like),
        ))
    try:
        page, size = int(params.get('page', 1)), int(params.get('page_size', 25))
    except ValueError:
        raise ValueError('INVALID_PAGINATION') from None
    if page < 1 or not 1 <= size <= 200:
        raise ValueError('INVALID_PAGINATION')
    total = session.scalar(select(func.count()).select_from(q.subquery())) if not ident else 0
    q = q.order_by(Notification.created_at.desc(), Notification.id.desc())
    rows = session.execute(q.limit(1) if ident else q.offset((page - 1) * size).limit(size)).all()
    if ident and not rows:
        raise LookupError()
    # Batch-resolve camera labels; never expose camera source URLs/credentials.
    keys = {r[0].camera_id for r in rows}
    ids = []
    for key in keys:
        try:
            ids.append(UUID(key))
        except ValueError:
            pass
    cameras = session.scalars(select(Camera).where(or_(Camera.registry_key.in_(keys), Camera.id.in_(ids)))) if keys else []
    names = {}
    for cam in cameras:
        for key in (cam.registry_key, str(cam.id), cam.id.hex):
            names[key] = cam.name
    email_cfg = getattr(router, '_email_config', None) or EmailConfig.from_env()
    alerts = []
    for item, face, plate, target, vehicle in rows:
        is_face = item.event_id is not None
        event_id = str(item.event_id if is_face else item.plate_event_id)
        event_key = ('face:' if is_face else 'plate:') + event_id
        is_failed = item.status == 'failed'
        can_retry = (
            is_failed
            and item.error in RETRY_ERRORS
            and item.retry_count < email_cfg.max_retries
        )
        alerts.append(dict(
            id=str(item.id), event_id=event_id, event_center_id=event_key,
            event_type=EVENT_TYPES[0 if is_face else 1], camera_id=item.camera_id,
            camera_name=names.get(item.camera_id), recipient_email=item.recipient,
            channel=item.channel.upper(), status=item.status.upper(),
            created_at=item.created_at.isoformat(), sent_at=item.sent_at.isoformat() if item.sent_at else None,
            error_code=item.error if item.error in ERROR_MESSAGES else ('delivery_failed' if item.error else None),
            error_message=safe_error(item.error), retry_count=item.retry_count,
            retry_scheduled=can_retry, max_retries=email_cfg.max_retries,
            target_id=str(face.target_id) if face and face.target_id else
                      (str(item.vehicle_watchlist_id) if item.vehicle_watchlist_id else None),
            target_name=target.name if target else (vehicle.display_name if vehicle else None),
            plate_number=plate.normalized_plate or plate.plate_text if plate else None,
            event_url='/events?id=' + event_key,
        ))
    if ident:
        return dict(status='ok', alert=alerts[0])
    return dict(status='ok', alerts=alerts, total=total, page=page, page_size=size)


def execute(params, ident=None):
    try:
        with database() as db, db.transaction() as session:
            result = query(session, params, ident)
        return JSONResponse(result, headers={'Cache-Control': 'private, no-store'})
    except LookupError:
        return JSONResponse({'detail': 'ALERT_NOT_FOUND'}, status_code=404)
    except ValueError as exc:
        code = str(exc)
        if code not in ('INVALID_STATUS', 'INVALID_EVENT_TYPE', 'INVALID_PAGINATION'):
            code = 'INVALID_REQUEST'
        return JSONResponse({'detail': code}, status_code=400)
    except SQLAlchemyError:
        return JSONResponse({'detail': 'DATABASE_UNAVAILABLE'}, status_code=503)
    except Exception:
        return JSONResponse({'detail': 'ALERT_CENTER_UNAVAILABLE'}, status_code=503)


@router.get('/api/alerts')
def alerts(request: Request):
    return execute(dict(request.query_params))


@router.get('/api/alerts/{alert_id}')
def alert(alert_id: str):
    return execute({}, alert_id)
