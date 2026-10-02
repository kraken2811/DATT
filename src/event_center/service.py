"""SQL UNION projection: no event copies, CV hooks, or binary DB payloads."""
from datetime import datetime,timezone
from uuid import UUID
import json
from sqlalchemy import select,union_all,literal,cast,String,Float,Boolean,func,case,or_
from src.db.models import FaceEvent,PlateEvent,VehicleEvent,VehiclePassage,BusinessEvent,DetectionEvent,Notification,VehicleWatchlistResult
from src.watchlists.vehicles import normalize_plate

KINDS=('face','plate','vehicle','passage','business')


def projection():
    string=lambda col:cast(col,String)
    empty=lambda:cast(literal(None),String)
    notification=lambda kind,eid: select(func.max(case((Notification.status=='failed',4),(Notification.status=='pending',3),
        (Notification.status=='sent',2),(Notification.status=='suppressed',1),else_=0))).where(
        (Notification.event_id==eid) if kind=='face' else (Notification.plate_event_id==eid)).correlate_except(Notification).scalar_subquery()
    def columns(model,kind,ts,camera,obj,target=None,plate=None,confidence=None,matched=None,evidence=None,notice=None,semantic=None,metadata=None,color=None):
        return [string(model.id).label('id'),literal(kind).label('event_type'),ts.label('timestamp'),string(camera).label('camera_id'),
            literal(obj).label('object_type'),string(target).label('target_id') if target is not None else empty().label('target_id'),
            string(plate).label('plate').label('plate') if plate is not None else empty().label('plate'),
            cast(confidence,Float).label('confidence') if confidence is not None else cast(literal(None),Float).label('confidence'),
            cast(matched,Boolean).label('watchlist_match') if matched is not None else literal(False).label('watchlist_match'),
            string(evidence).label('evidence_key') if evidence is not None else empty().label('evidence_key'),
            notice.label('notification_rank') if notice is not None else literal(0).label('notification_rank'),
            (semantic if semantic is not None else literal(kind)).label('semantic_type'),
            (string(metadata) if metadata is not None else literal('{}')).label('metadata'),
            (string(color) if color is not None else empty()).label('detected_color')]
    def marker(model, field):
        return select(field).where(BusinessEvent.id==model.id).correlate(model).scalar_subquery()
    def grouped(model):
        return select(BusinessEvent.id).where(BusinessEvent.passage_id==model.id,
            BusinessEvent.event_type=='VEHICLE_WATCHLIST_MATCH').correlate(model).exists()
    old_camera=select(Notification.camera_id).where(Notification.event_id==FaceEvent.id).order_by(Notification.created_at).limit(1).correlate(FaceEvent).scalar_subquery()
    face=select(*columns(FaceEvent,'face',FaceEvent.created_at,func.coalesce(FaceEvent.camera_id,string(DetectionEvent.camera_id),old_camera),'person',
        target=FaceEvent.target_id,confidence=FaceEvent.similarity,matched=FaceEvent.decision=='FACE_MATCH',evidence=FaceEvent.face_crop_path,notice=notification('face',FaceEvent.id),
        semantic=func.coalesce(marker(FaceEvent,BusinessEvent.event_type),literal('face')),
        metadata=marker(FaceEvent,BusinessEvent.event_metadata))).outerjoin(DetectionEvent,FaceEvent.detection_event_id==DetectionEvent.id)
    plate=select(*columns(PlateEvent,'plate',PlateEvent.created_at,func.coalesce(VehicleWatchlistResult.camera_id,string(DetectionEvent.camera_id)),'plate',
        target=VehicleWatchlistResult.watchlist_id,plate=PlateEvent.plate_text,confidence=PlateEvent.confidence,
        matched=VehicleWatchlistResult.decision=='MATCH',evidence=func.coalesce(PlateEvent.plate_crop_path,VehicleEvent.vehicle_image_path),notice=notification('plate',PlateEvent.id),
        semantic=func.coalesce(marker(PlateEvent,BusinessEvent.event_type),literal('plate')),
        metadata=marker(PlateEvent,BusinessEvent.event_metadata),color=VehicleEvent.vehicle_color)).join(
        VehicleEvent,PlateEvent.vehicle_event_id==VehicleEvent.id).outerjoin(DetectionEvent,VehicleEvent.detection_event_id==DetectionEvent.id).outerjoin(VehicleWatchlistResult,VehicleWatchlistResult.plate_event_id==PlateEvent.id)
    vehicle=select(*columns(VehicleEvent,'vehicle',VehicleEvent.last_seen,DetectionEvent.camera_id,'vehicle',evidence=VehicleEvent.vehicle_image_path,color=VehicleEvent.vehicle_color)).outerjoin(DetectionEvent,VehicleEvent.detection_event_id==DetectionEvent.id).where(~grouped(VehicleEvent))
    passage=select(*columns(VehiclePassage,'passage',VehiclePassage.last_seen_at,VehiclePassage.camera_id,'vehicle',plate=VehiclePassage.plate_text,
        confidence=VehiclePassage.plate_confidence,evidence=VehiclePassage.best_vehicle_image_path,color=VehiclePassage.vehicle_color)).where(~grouped(VehiclePassage))
    business=select(*columns(BusinessEvent,'business',BusinessEvent.event_time,BusinessEvent.camera_id,'business',plate=BusinessEvent.plate_text,
        semantic=BusinessEvent.event_type,metadata=BusinessEvent.event_metadata,
        evidence=BusinessEvent.event_metadata['snapshot_path'].as_string())).where(
            ~or_(
                (BusinessEvent.event_type=='FACE_WATCHLIST_MATCH') &
                    select(FaceEvent.id).where(FaceEvent.id==BusinessEvent.id).correlate(BusinessEvent).exists(),
                (BusinessEvent.event_type=='VEHICLE_WATCHLIST_MATCH') &
                    select(PlateEvent.id).where(PlateEvent.id==BusinessEvent.id).correlate(BusinessEvent).exists()))
    return union_all(face,plate,vehicle,passage,business).subquery('unified_events')


def timestamp(value):
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError,AttributeError): raise ValueError('INVALID_TIME_REQUIRE_TIMEZONE') from None


def serialize(row):
    ident=str(UUID(row.id))
    event_id=row.event_type+':'+ident
    metadata=json.loads(row.metadata) if row.metadata else {}
    if not isinstance(metadata,dict): metadata={}
    return dict(event_id=event_id,source_event_id=ident,event_type=row.event_type,semantic_type=row.semantic_type,metadata=metadata,
        detected_vehicle_color=metadata.get('detected_vehicle_color', row.detected_color),
        detected_vehicle_color_confidence=metadata.get('detected_vehicle_color_confidence'),
        watchlist_vehicle_color=metadata.get('watchlist_vehicle_color'),
        vehicle_type=metadata.get('vehicle_type'), track_id=metadata.get('track_id'),
        match_type=metadata.get('match_type'),timestamp=row.timestamp.isoformat(),camera_id=row.camera_id,
        object_type=row.object_type,target_id=str(UUID(row.target_id)) if row.target_id else None,plate=row.plate,confidence=row.confidence,
        similarity=row.confidence if row.event_type=='face' else None,watchlist_match=bool(row.watchlist_match),
        evidence={'key':row.evidence_key,'url':'/api/event_center/events/'+event_id+'/evidence'} if row.evidence_key else None,
        notification_status={4:'failed',3:'pending',2:'sent',1:'suppressed'}.get(row.notification_rank))


def query(session,params,ident=None):
    events=projection();q=select(events)
    if ident:
        try:
            kind,raw=ident.split(':',1);UUID(raw)
            if kind not in KINDS: raise ValueError()
        except ValueError: raise LookupError('EVENT_NOT_FOUND') from None
        q=q.where(events.c.event_type==kind,events.c.id==(UUID(raw).hex if session.bind.dialect.name=='sqlite' else str(UUID(raw))))
    kind=params.get('event_type')
    if kind:
        from src.events.policy import MEANINGFUL_EVENTS
        if kind not in KINDS and kind not in MEANINGFUL_EVENTS: raise ValueError('INVALID_EVENT_TYPE')
        q=q.where(events.c.semantic_type==kind) if kind in MEANINGFUL_EVENTS else q.where(events.c.event_type==kind)
    for field in ('camera_id','target_id'):
        if params.get(field):
            value=params[field]
            try: alternative=UUID(value).hex
            except ValueError: alternative=value
            q=q.where(getattr(events.c,field).in_((value,alternative)))
    if params.get('camera'): q=q.where(events.c.camera_id==params['camera'])
    start=params.get('from') or params.get('from_time');end=params.get('to') or params.get('to_time')
    if start: q=q.where(events.c.timestamp>=timestamp(start))
    if end: q=q.where(events.c.timestamp<=timestamp(end))
    if start and end and timestamp(start)>timestamp(end): raise ValueError('INVALID_TIME_RANGE')
    if params.get('watchlist_match') is not None:
        value=params['watchlist_match'].lower()
        if value not in ('true','false'): raise ValueError('INVALID_MATCH_FILTER')
        q=q.where(func.coalesce(events.c.watchlist_match,False)==(value=='true'))
    if params.get('plate'):
        plate=normalize_plate(params['plate'])
        if session.bind.dialect.name=='sqlite':
            session.connection().connection.driver_connection.create_function('datt_normalize_plate',1,normalize_plate)
            expr=func.datt_normalize_plate(events.c.plate)
        else: expr=func.upper(func.regexp_replace(func.coalesce(events.c.plate,''),'[^A-Za-z0-9]','','g'))
        q=q.where(expr==plate)
    if params.get('notification_status'):
        status=params['notification_status']
        if status not in ('pending','sent','failed','suppressed'): raise ValueError('INVALID_NOTIFICATION_STATUS')
        q=q.where(select(Notification.id).where(Notification.status==status,or_(
            (events.c.event_type=='face') & (cast(Notification.event_id,String)==events.c.id),
            (events.c.event_type=='plate') & (cast(Notification.plate_event_id,String)==events.c.id))).exists())
    direction=params.get('sort',params.get('order','desc'))
    if direction not in ('asc','desc','timestamp','-timestamp'): raise ValueError('INVALID_SORT')
    q=q.order_by(events.c.timestamp.asc() if direction in ('asc','timestamp') else events.c.timestamp.desc(),events.c.event_type,events.c.id)
    if ident:
        row=session.execute(q).first()
        if not row: raise LookupError('EVENT_NOT_FOUND')
        return serialize(row)
    try: page=int(params.get('page',1));size=int(params.get('page_size',params.get('limit',50)))
    except ValueError: raise ValueError('INVALID_PAGINATION') from None
    if page<1 or not 1<=size<=200: raise ValueError('INVALID_PAGINATION')
    total=session.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
    rows=session.execute(q.offset((page-1)*size).limit(size)).all()
    return dict(status='ok',events=[serialize(r) for r in rows],page=page,page_size=size,total=total)
