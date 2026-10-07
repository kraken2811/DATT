"""Exact plate lookup and CRUD; independent of OCR and recognition models."""
import re
from uuid import UUID
from sqlalchemy import select, func
from src.db.models import VehicleWatchlist, VehicleWatchlistResult, PlateEvent, VehicleEvent, DetectionEvent, utc_now

VEHICLE_COLORS = frozenset(('black','white','gray','silver','red','blue','green','yellow','orange','brown','other'))


def normalize_plate(value):
    return re.sub(r'[^A-Za-z0-9]', '', value or '').upper()


def fields(body, partial=False):
    if not isinstance(body, dict):
        raise ValueError('INVALID_INPUT')
    result = {}
    defaults = dict(plate_number='', vehicle_type='car', vehicle_color=None, display_name='', owner_info='', notes='', status='active')
    body = dict(body)
    if 'name' in body: body['display_name'] = body['name']
    for key, default in defaults.items():
        if partial and key not in body: continue
        value = body.get(key, default)
        if key == 'vehicle_color':
            if value not in (None, '') and (not isinstance(value, str) or value not in VEHICLE_COLORS):
                raise ValueError('INVALID_VEHICLE_COLOR')
            result[key] = value or None
            continue
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


def serialize_item(item, stats=None):
    count, last = stats.get(item.plate_number, (0, None)) if stats else (0, None)
    def stamp(value): return value.strftime('%Y-%m-%d %H:%M:%S') if value else None
    return dict(id=str(item.id), plate_number=item.plate_number, normalized_plate=item.plate_number,
        vehicle_type=item.vehicle_type, vehicle_color=item.vehicle_color, name=item.display_name, display_name=item.display_name,
        owner_info=item.owner_info, notes=item.notes, status=item.status, image_path=None,
        created_at=stamp(item.created_at), updated_at=stamp(item.updated_at), detection_count=count, last_seen=stamp(last))


def serialize(session, item):
    count, last = session.execute(select(func.count(PlateEvent.id),func.max(PlateEvent.created_at)).where(
        PlateEvent.normalized_plate == item.plate_number)).one()
    def stamp(value): return value.strftime('%Y-%m-%d %H:%M:%S') if value else None
    return dict(id=str(item.id), plate_number=item.plate_number, normalized_plate=item.plate_number,
        vehicle_type=item.vehicle_type, vehicle_color=item.vehicle_color, name=item.display_name, display_name=item.display_name,
        owner_info=item.owner_info, notes=item.notes, status=item.status, image_path=None,
        created_at=stamp(item.created_at), updated_at=stamp(item.updated_at), detection_count=count, last_seen=stamp(last))


def operate(db, action, ident=None, body=None, filters=None):
    with db.transaction() as session:
        if action == 'list':
            from sqlalchemy import or_
            filters = filters or {}
            query = select(VehicleWatchlist)

            # Database -> Filter
            for key in ('status', 'vehicle_type'):
                val = filters.get(key)
                if val and val != 'all':
                    query = query.where(getattr(VehicleWatchlist, key) == val)

            # Database -> Search
            search = (filters.get('search') or filters.get('q') or '').strip()
            if search:
                norm_search = normalize_plate(search)
                search_like = f"%{search}%"
                search_clauses = [
                    VehicleWatchlist.display_name.ilike(search_like),
                    VehicleWatchlist.owner_info.ilike(search_like),
                    VehicleWatchlist.notes.ilike(search_like),
                    VehicleWatchlist.plate_number.ilike(search_like),
                ]
                if norm_search:
                    search_clauses.append(VehicleWatchlist.plate_number.ilike(f"%{norm_search}%"))
                query = query.where(or_(*search_clauses))

            # Database -> Sort
            sort_dir = filters.get('order', filters.get('sort', 'desc')).lower()
            query = query.order_by(VehicleWatchlist.created_at.asc() if sort_dir == 'asc' else VehicleWatchlist.created_at.desc())

            total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))

            # Database -> Pagination
            page = filters.get('page')
            page_size = filters.get('page_size', filters.get('limit', 25))
            try:
                page_size = max(1, min(200, int(page_size)))
            except (ValueError, TypeError):
                page_size = 25

            if page is not None:
                try:
                    page = max(1, int(page))
                except (ValueError, TypeError):
                    page = 1
                items = list(session.scalars(query.offset((page - 1) * page_size).limit(page_size)))
            else:
                items = list(session.scalars(query))

            # Batch load detection stats to eliminate N+1 queries
            plate_numbers = [i.plate_number for i in items if i.plate_number]
            stats_map = {}
            if plate_numbers:
                stat_rows = session.execute(
                    select(
                        PlateEvent.normalized_plate,
                        func.count(PlateEvent.id),
                        func.max(PlateEvent.created_at)
                    )
                    .where(PlateEvent.normalized_plate.in_(plate_numbers))
                    .group_by(PlateEvent.normalized_plate)
                ).all()
                for plate_norm, count, last_time in stat_rows:
                    stats_map[plate_norm] = (count, last_time)

            vehicles = [serialize_item(i, stats_map) for i in items]
            resp = dict(status='ok', total=total, vehicles=vehicles)
            if page is not None:
                resp['page'] = page
                resp['page_size'] = page_size
            return resp
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
