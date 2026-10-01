"""Exact plate lookup and CRUD; independent of OCR and recognition models."""
import re
from uuid import UUID
from sqlalchemy import select, func
from src.db.models import VehicleWatchlist, VehicleWatchlistResult, PlateEvent, VehicleEvent, DetectionEvent, utc_now


def normalize_plate(value):
    return re.sub(r'[^A-Za-z0-9]', '', value or '').upper()


def fields(body, partial=False):
    if not isinstance(body, dict):
        raise ValueError('INVALID_INPUT')
    result = {}
    defaults = dict(plate_number='', vehicle_type='car', display_name='', owner_info='', notes='', status='active')
    body = dict(body)
    if 'name' in body: body['display_name'] = body['name']
    for key, default in defaults.items():
        if partial and key not in body: continue
        value = body.get(key, default)
        if not isinstance(value, str): raise ValueError('INVALID_INPUT')
        value = value.strip()
        if key == 'plate_number':
            value = normalize_plate(value)
            if not 3 <= len(value) <= 100: raise ValueError('INVALID_PLATE')
        if key == 'status' and value not in ('active', 'disabled'): raise ValueError('INVALID_STATUS')
        if key == 'vehicle_type' and value not in ('car','motorbike','truck','bus','container','other'): raise ValueError('INVALID_VEHICLE_TYPE')
        if len(value) > (255 if key == 'display_name' else 10000): raise ValueError('INVALID_INPUT')
        result[key] = value
    return result


def record_plate_result(session, event, camera_id=None):
    """Call in the PlateEvent transaction; no external calls or OCR recalculation."""
    event.normalized_plate = normalize_plate(event.plate_text)
    existing = session.scalar(select(VehicleWatchlistResult).where(VehicleWatchlistResult.plate_event_id == event.id))
    if existing: return existing
    target = session.scalar(select(VehicleWatchlist).where(
        VehicleWatchlist.plate_number == event.normalized_plate,
        VehicleWatchlist.status == 'active').with_for_update())
    result = VehicleWatchlistResult(plate_event_id=event.id,
        watchlist_id=target.id if target else None, normalized_plate=event.normalized_plate,
        decision='MATCH' if target else 'NO_MATCH', display_name=target.display_name if target else None,
        camera_id=camera_id, created_at=event.created_at)
    session.add(result); session.flush()
    return result


def get_item(session, ident):
    try: ident = UUID(str(ident))
    except (ValueError, TypeError): raise LookupError('NOT_FOUND') from None
    item = session.get(VehicleWatchlist, ident)
    if item is None: raise LookupError('NOT_FOUND')
    return item


def serialize(session, item):
    count, last = session.execute(select(func.count(PlateEvent.id),func.max(PlateEvent.created_at)).where(
        PlateEvent.normalized_plate == item.plate_number)).one()
    def stamp(value): return value.strftime('%Y-%m-%d %H:%M:%S') if value else None
    return dict(id=str(item.id), plate_number=item.plate_number, normalized_plate=item.plate_number,
        vehicle_type=item.vehicle_type, name=item.display_name, display_name=item.display_name,
        owner_info=item.owner_info, notes=item.notes, status=item.status, image_path=None,
        created_at=stamp(item.created_at), updated_at=stamp(item.updated_at), detection_count=count, last_seen=stamp(last))


def operate(db, action, ident=None, body=None, filters=None):
    with db.transaction() as session:
        if action == 'list':
            query = select(VehicleWatchlist).order_by(VehicleWatchlist.created_at.desc())
            filters = filters or {}
            for key in ('status','vehicle_type'):
                if filters.get(key): query = query.where(getattr(VehicleWatchlist,key)==filters[key])
            items = list(session.scalars(query))
            search = filters.get('search','').strip().lower()
            if search:
                items = [i for i in items if search in ' '.join((i.plate_number,i.display_name,i.owner_info,i.notes)).lower() or
                         (normalize_plate(search) and normalize_plate(search) in i.plate_number)]
            return dict(status='ok', total=len(items), vehicles=[serialize(session,i) for i in items])
        if action == 'create':
            item = VehicleWatchlist(**fields(body)); session.add(item); session.flush()
        else:
            item = get_item(session,ident)
        if action == 'delete':
            session.delete(item)
            return dict(status='ok', message='Vehicle deleted')
        if action == 'update':
            for key,value in fields(body, partial=True).items(): setattr(item,key,value)
            item.updated_at = utc_now(); session.flush()
        if action == 'detections':
            query = select(PlateEvent, VehicleWatchlistResult, DetectionEvent.camera_id).join(
                VehicleEvent, PlateEvent.vehicle_event_id==VehicleEvent.id).outerjoin(
                DetectionEvent, VehicleEvent.detection_event_id==DetectionEvent.id).outerjoin(
                VehicleWatchlistResult, VehicleWatchlistResult.plate_event_id==PlateEvent.id).where(
                PlateEvent.normalized_plate==item.plate_number).order_by(PlateEvent.created_at.desc()).limit(100)
            rows=[]
            for event,result,camera in session.execute(query):
                rows.append(dict(id=str(event.id),plate_text=event.plate_text,confidence=event.confidence,
                    plate_crop_path=event.plate_crop_path,status=event.status,
                    created_at=event.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    camera_id=result.camera_id if result else (str(camera) if camera else None),
                    watchlist_decision=result.decision if result else None,
                    watchlist_id=str(result.watchlist_id) if result and result.watchlist_id else None))
            total=session.scalar(select(func.count(PlateEvent.id)).where(PlateEvent.normalized_plate==item.plate_number))
            return dict(status='ok',vehicle_id=str(item.id),plate_number=item.plate_number,total_detections=total,detections=rows)
        return dict(status='ok', vehicle=serialize(session,item))
