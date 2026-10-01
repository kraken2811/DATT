"""One camera registry in PostgreSQL; video_sources owns uploaded files."""
from datetime import timedelta
from uuid import UUID, uuid4
from urllib.parse import urlsplit
from contextlib import contextmanager
import os
import threading
from sqlalchemy import select, or_, update
from src.db.database import Database
from src.db.models import Camera, VideoSource, utc_now

TYPES={'rtsp':'rtsp','hls':'direct_hls','direct_hls':'direct_hls','http':'http','https':'http',
       'youtube':'youtube','file':'file','local':'file','public cctv':'cctv','cctv':'cctv'}

@contextmanager
def database():
    db=Database()
    try: yield db
    finally: db.dispose()


def find(session,ident,lock=False):
    try: query=select(Camera).where(Camera.id==UUID(str(ident)))
    except (ValueError,TypeError): query=select(Camera).where(Camera.registry_key==str(ident))
    return session.scalar(query.with_for_update() if lock else query)


def validate_source(kind,source):
    if not isinstance(source,str) or not source.strip() or len(source)>4096: raise ValueError('INVALID_SOURCE')
    source=source.strip(); parsed=urlsplit(source)
    if kind=='file':
        from src.storage import validate_key
        validate_key(source)
        if not source.startswith('data/uploads/videos/'): raise ValueError('INVALID_FILE_SOURCE')
    else:
        schemes=('rtsp','rtsps') if kind=='rtsp' else ('http','https')
        if parsed.scheme not in schemes or not parsed.hostname: raise ValueError('INVALID_SOURCE')
        try: parsed.port
        except ValueError: raise ValueError('INVALID_PORT') from None
        if kind=='youtube' and parsed.hostname.lower() not in ('youtube.com','www.youtube.com','m.youtube.com','youtu.be'): raise ValueError('INVALID_YOUTUBE_SOURCE')
    return source


def camera_fields(body,existing=None):
    if not isinstance(body,dict): raise ValueError('INVALID_BODY')
    name=body.get('camera_name',body.get('name',existing.name if existing else ''))
    kind=body.get('source_type',existing.source_type if existing else '')
    source=body.get('source_url',body.get('url',existing.source if existing else ''))
    if not isinstance(name,str) or not name.strip() or len(name)>255: raise ValueError('INVALID_NAME')
    if not isinstance(kind,str) or kind.lower() not in TYPES: raise ValueError('INVALID_SOURCE_TYPE')
    kind=TYPES[kind.lower()];source=validate_source(kind,source)
    status=body.get('status', 'enabled' if existing is None or existing.enabled else 'disabled')
    if status not in ('enabled','disabled','online','offline','active'): raise ValueError('INVALID_STATUS')
    location=body.get('zone',body.get('location',existing.location if existing else ''))
    description=body.get('description',existing.description if existing else '')
    if any(v is not None and (not isinstance(v,str) or len(v)>10000) for v in (location,description)): raise ValueError('INVALID_METADATA')
    return dict(name=name.strip(),source_type=kind,source=source,location=location,
                description=description,enabled=status!='disabled')


def serialize(c):
    active=bool(c.active_until and c.active_until>utc_now())
    stamp=lambda d:d.isoformat() if d else None
    return dict(id=str(c.id),camera_id=str(c.id),camera_name=c.name,name=c.name,
        source_url=c.source,url=c.source,type=c.source_type,source_type='hls' if c.source_type=='direct_hls' else c.source_type,
        zone=c.location,location=c.location,description=c.description or '',enabled=c.enabled,
        status='disabled' if not c.enabled else ('online' if active else 'offline'),
        active=active,last_active=stamp(c.last_active),created_at=stamp(c.created_at),updated_at=stamp(c.updated_at),
        thumbnail='/api/cameras/'+str(c.id)+'/thumbnail',thumbnail_url='/api/cameras/'+str(c.id)+'/thumbnail',video_source_id=str(c.video_source_id) if c.video_source_id else None)


def list_records(filters=None):
    filters=filters or {}
    with database() as db,db.transaction() as s:
        items=[serialize(c) for c in s.scalars(select(Camera).order_by(Camera.created_at.desc()))]
    summary={'total':len(items),**{v:sum(c['status']==v for c in items) for v in ('online','offline','disabled')}}
    result=items
    for key in ('status','source_type','zone'):
        value=filters.get(key)
        if value and value!='all': result=[c for c in result if c[key]==value]
    q=filters.get('search','').lower().strip()
    if q: result=[c for c in result if q in ' '.join(str(c.get(k) or '') for k in ('id','name','zone','description')).lower()]
    return dict(status='ok',cameras=result,total=len(result),summary=summary,
        active_camera_id=next((c['id'] for c in items if c['active']),None))


def mutate(action,ident=None,body=None):
    with database() as db,db.transaction() as s:
        c=find(s,ident,True) if ident else None
        if ident and c is None: raise LookupError('CAMERA_NOT_FOUND')
        if action=='get': return dict(status='ok',camera=serialize(c))
        if action in ('delete','disable') or (action=='update' and body.get('status')=='disabled'):
            if c.active_until and c.active_until>utc_now(): raise RuntimeError('CAMERA_ACTIVE_STOP_FIRST')
        if action=='delete': s.delete(c);s.flush();return dict(status='ok')
        if action in ('enable','disable'): c.enabled=action=='enable'
        else:
            values=camera_fields(body,c)
            if c is None: c=Camera(**values);s.add(c)
            else:
                for key,value in values.items(): setattr(c,key,value)
            if c.source_type=='file':
                v=s.scalar(select(VideoSource).where(VideoSource.storage_path==c.source,VideoSource.status=='ready'))
                if v is None: raise ValueError('VIDEO_SOURCE_NOT_REGISTERED')
                c.video_source_id=v.id
            else: c.video_source_id=None
        c.updated_at=utc_now();s.flush()
        return dict(status='ok',camera=serialize(c),last_active=c.last_active.isoformat() if c.last_active else None)


def registered_id(ident=None,source=None):
    if not os.environ.get('DATT_DATABASE_URL') and os.environ.get('DATT_REQUIRE_PERSISTENCE')!='1': return None
    with database() as db,db.transaction() as s:
        c=find(s,ident) if ident else s.scalar(select(Camera).where(Camera.source==source).order_by(Camera.enabled.asc()).limit(1))
        if c:
            if not c.enabled: raise ValueError('CAMERA_DISABLED')
            return str(c.id)
        if ident:
            try: UUID(str(ident))
            except ValueError: return None
            raise LookupError('CAMERA_NOT_FOUND')
    return None


def release(manager):
    lease=getattr(manager,'_registry_lease',None)
    manager._registry_lease=None
    if lease:
        ident,token,stop=lease;stop.set()
        try:
            with database() as db,db.transaction() as s:
                s.execute(update(Camera).where(Camera.id==ident,Camera.active_token==token).values(active_until=None,active_token=None))
        except Exception:
            # Reader shutdown must still happen; crashed leases expire without renewal.
            pass


def activate(manager,ident):
    from dataclasses import replace
    # Release and stop the previous reader before locking the next camera.
    manager._stop_reader_internal()
    manager._active_camera=None
    manager._status='STOPPED'
    try:
        with database() as db,db.transaction() as s:
            c=find(s,ident,True)
            if c is None: raise LookupError('CAMERA_NOT_FOUND')
            if not c.enabled: raise ValueError('CAMERA_DISABLED')
            if c.active_until and c.active_until>utc_now(): raise RuntimeError('CAMERA_ALREADY_ACTIVE')
            source=validate_source(c.source_type,c.source)
            if c.source_type=='file' and not s.get(VideoSource,c.video_source_id): raise ValueError('VIDEO_SOURCE_NOT_REGISTERED')
            kind='http' if c.source_type=='cctv' else c.source_type
            cam=manager.set_video_source(kind,source,name=c.name,video_source_id=str(c.video_source_id) if c.video_source_id else None,_registry_checked=True)
            cam=replace(cam,id=str(c.id),description=c.description or '')
            manager._active_camera=cam
            token=uuid4().hex;c.active_token=token;c.last_active=utc_now();c.active_until=utc_now()+timedelta(seconds=90)
            ident=c.id
    except Exception:
        manager._stop_reader_internal();manager._active_camera=None;manager._status='ERROR'
        raise
    stop=threading.Event();manager._registry_lease=(ident,token,stop)
    def fail_closed():
        with manager._lock:
            current=getattr(manager,'_registry_lease',None)
            if current and current[1]==token: manager.stop_camera()
    def heartbeat():
        while not stop.wait(10):
            try:
                with database() as db,db.transaction() as s:
                    count=s.execute(update(Camera).where(Camera.id==ident,Camera.active_token==token).values(
                        active_until=utc_now()+timedelta(seconds=90),last_active=utc_now())).rowcount
                if count!=1:
                    fail_closed();return
            except Exception:
                fail_closed();return
    threading.Thread(target=heartbeat,name='CameraLease',daemon=True).start()
    return cam
