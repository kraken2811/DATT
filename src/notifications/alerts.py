"""Read-only Alert Center projection of the existing transactional outbox."""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, or_
from sqlalchemy.exc import SQLAlchemyError
from src.cameras.service import database
from src.db.models import Notification, FaceEvent, PlateEvent, Target, VehicleWatchlist, Camera, VehicleWatchlistResult
import logging
import threading
import time
from .config import EmailConfig
from .errors import safe_error, ERROR_MESSAGES, RETRY_ERRORS

logger = logging.getLogger("datt.notifications.alerts")
router = APIRouter()
EVENT_TYPES = ('FACE_WATCHLIST_MATCH', 'VEHICLE_WATCHLIST_MATCH')

ALERT_FALLBACK_LOG_COOLDOWN = 60.0
_FALLBACK_LOG_LOCK = threading.Lock()
_FALLBACK_LAST_LOG_TIME = 0.0
_FALLBACK_SUPPRESSED_COUNT = 0


def _reset_fallback_log_throttle():
    """Helper for testing or resetting cooldown state."""
    global _FALLBACK_LAST_LOG_TIME, _FALLBACK_SUPPRESSED_COUNT
    with _FALLBACK_LOG_LOCK:
        _FALLBACK_LAST_LOG_TIME = 0.0
        _FALLBACK_SUPPRESSED_COUNT = 0


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

    raw_total = params.get('include_total', True)
    if isinstance(raw_total, str):
        include_total = raw_total.strip().lower() not in ('false', '0', 'no', 'f')
    else:
        include_total = bool(raw_total)

    if not ident and include_total:
        if not search:
            count_q = select(func.count(Notification.id))
            if status and status != 'all':
                count_q = count_q.where(Notification.status == status)
            if kind and kind != 'all':
                count_q = count_q.where(Notification.event_id.is_not(None) if kind == EVENT_TYPES[0]
                                        else Notification.plate_event_id.is_not(None))
            if camera and camera != 'all':
                count_q = count_q.where(Notification.camera_id.in_(camera_aliases(camera)))
            total = session.scalar(count_q) or 0
        else:
            total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
    else:
        total = 0 if ident else None
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
        payload = item.payload or {}
        event_confirmed_at = payload.get('event_confirmed_at') or item.created_at.isoformat()
        event_persisted_at = payload.get('event_persisted_at') or item.created_at.isoformat()
        alert_available_at = datetime.now(timezone.utc).isoformat()
        plate_detected_at = payload.get('plate_detected_at')
        ocr_first_candidate_at = payload.get('ocr_first_candidate_at')
        plate_confirmed_at = payload.get('plate_confirmed_at') or event_confirmed_at
        alerts.append(dict(
            id=str(item.id), event_id=event_id, event_center_id=event_key,
            event_type=EVENT_TYPES[0 if is_face else 1], camera_id=item.camera_id,
            camera_name=names.get(item.camera_id), recipient_email=item.recipient,
            channel=item.channel.upper(), status=item.status.upper(),
            created_at=item.created_at.isoformat(), sent_at=item.sent_at.isoformat() if item.sent_at else None,
            event_confirmed_at=event_confirmed_at,
            event_persisted_at=event_persisted_at,
            alert_available_at=alert_available_at,
            plate_detected_at=plate_detected_at,
            ocr_first_candidate_at=ocr_first_candidate_at,
            plate_confirmed_at=plate_confirmed_at,
            error_code=item.error if item.error in ERROR_MESSAGES else ('delivery_failed' if item.error else None),
            error_message=safe_error(item.error), retry_count=item.retry_count,
            retry_scheduled=can_retry, max_retries=email_cfg.max_retries,
            target_id=str(face.target_id) if face and face.target_id else
                      (str(item.vehicle_watchlist_id) if item.vehicle_watchlist_id else None),
            target_name=target.name if target else (vehicle.display_name if vehicle else None),
            vehicle_display_name=vehicle.display_name if vehicle else None,
            plate_number=plate.normalized_plate or plate.plate_text if plate else None,
            event_url='/events?id=' + event_key,
        ))
    if ident:
        return dict(status='ok', alert=alerts[0])

    # Fallback projection: if any confirmed Watchlist events exist without an email Notification record,
    # include them immediately in Alert Center so frontend popup triggers without depending on email delivery.
    if page == 1 and (not status or status in ('all', 'pending')):
        seen_event_ids = {a['event_id'] for a in alerts}
        try:
            # 1. Unnotified Face Events
            if not kind or kind in ('all', EVENT_TYPES[0]):
                unnotified_faces = session.execute(
                    select(FaceEvent, Target)
                    .join(Target, FaceEvent.target_id == Target.id)
                    .outerjoin(Notification, Notification.event_id == FaceEvent.id)
                    .where(
                        FaceEvent.decision == 'FACE_MATCH',
                        FaceEvent.target_id.is_not(None),
                        Notification.id.is_(None)
                    )
                    .order_by(FaceEvent.created_at.desc())
                    .limit(size)
                ).all()

                for fe, tgt in unnotified_faces:
                    eid = str(fe.id)
                    if eid in seen_event_ids:
                        continue
                    if camera and camera != 'all' and fe.camera_id not in camera_aliases(camera):
                        continue
                    seen_event_ids.add(eid)
                    event_key = 'face:' + eid
                    cam_name = names.get(fe.camera_id) if names else fe.camera_id
                    alerts.insert(0, dict(
                        id=eid, event_id=eid, event_center_id=event_key,
                        event_type=EVENT_TYPES[0], camera_id=fe.camera_id,
                        camera_name=cam_name, recipient_email='',
                        channel='IN_APP', status='PENDING',
                        created_at=fe.created_at.isoformat(), sent_at=None,
                        event_confirmed_at=fe.created_at.isoformat(),
                        event_persisted_at=fe.created_at.isoformat(),
                        alert_available_at=datetime.now(timezone.utc).isoformat(),
                        plate_detected_at=None,
                        ocr_first_candidate_at=None,
                        plate_confirmed_at=fe.created_at.isoformat(),
                        error_code=None, error_message=None, retry_count=0,
                        retry_scheduled=False, max_retries=email_cfg.max_retries,
                        target_id=str(fe.target_id),
                        target_name=tgt.name if tgt else None,
                        plate_number=None,
                        event_url='/events?id=' + event_key,
                    ))

            # 2. Unnotified Plate Events
            if not kind or kind in ('all', EVENT_TYPES[1]):
                unnotified_plates = session.execute(
                    select(PlateEvent, VehicleWatchlist, VehicleWatchlistResult)
                    .join(VehicleWatchlistResult, VehicleWatchlistResult.plate_event_id == PlateEvent.id)
                    .join(VehicleWatchlist, VehicleWatchlistResult.watchlist_id == VehicleWatchlist.id)
                    .outerjoin(Notification, Notification.plate_event_id == PlateEvent.id)
                    .where(
                        VehicleWatchlistResult.decision == 'MATCH',
                        Notification.id.is_(None)
                    )
                    .order_by(PlateEvent.created_at.desc())
                    .limit(size)
                ).all()

                for pe, v_wl, v_res in unnotified_plates:
                    eid = str(pe.id)
                    if eid in seen_event_ids:
                        continue
                    cam_id = v_res.camera_id or ''
                    if camera and camera != 'all' and cam_id not in camera_aliases(camera):
                        continue
                    seen_event_ids.add(eid)
                    event_key = 'plate:' + eid
                    cam_name = names.get(cam_id) if names else cam_id
                    alerts.insert(0, dict(
                        id=eid, event_id=eid, event_center_id=event_key,
                        event_type=EVENT_TYPES[1], camera_id=cam_id,
                        camera_name=cam_name, recipient_email='',
                        channel='IN_APP', status='PENDING',
                        created_at=pe.created_at.isoformat(), sent_at=None,
                        event_confirmed_at=pe.created_at.isoformat(),
                        event_persisted_at=pe.created_at.isoformat(),
                        alert_available_at=datetime.now(timezone.utc).isoformat(),
                        plate_detected_at=None,
                        ocr_first_candidate_at=None,
                        plate_confirmed_at=pe.created_at.isoformat(),
                        error_code=None, error_message=None, retry_count=0,
                        retry_scheduled=False, max_retries=email_cfg.max_retries,
                        target_id=str(v_wl.id) if v_wl else None,
                        target_name=v_wl.display_name if v_wl else None,
                        vehicle_display_name=v_wl.display_name if v_wl else None,
                        plate_number=pe.normalized_plate or pe.plate_text,
                        event_url='/events?id=' + event_key,
                    ))
        except Exception as exc:
            global _FALLBACK_LAST_LOG_TIME, _FALLBACK_SUPPRESSED_COUNT
            now = time.monotonic()
            should_log_full = False
            suppressed = 0
            with _FALLBACK_LOG_LOCK:
                if now - _FALLBACK_LAST_LOG_TIME >= ALERT_FALLBACK_LOG_COOLDOWN:
                    should_log_full = True
                    suppressed = _FALLBACK_SUPPRESSED_COUNT
                    _FALLBACK_SUPPRESSED_COUNT = 0
                    _FALLBACK_LAST_LOG_TIME = now
                else:
                    _FALLBACK_SUPPRESSED_COUNT += 1

            if should_log_full:
                if suppressed > 0:
                    logger.warning(
                        "[ALERTS] Fallback unnotified events projection query failed: %s (repeated %d times during cooldown)",
                        exc,
                        suppressed,
                        exc_info=True,
                    )
                else:
                    logger.warning(
                        "[ALERTS] Fallback unnotified events projection query failed: %s",
                        exc,
                        exc_info=True,
                    )

    return dict(status='ok', alerts=alerts, total=len(alerts) if total is not None and len(alerts) > total else total, page=page, page_size=size)


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
