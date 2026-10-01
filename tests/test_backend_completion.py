import io
import os
from uuid import uuid4,UUID
from datetime import timedelta
from unittest.mock import Mock,patch
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from PIL import Image
from src.db.database import Database
from src.db.models import Camera,VideoSource,FaceEvent,Target,VehicleEvent,PlateEvent,VehiclePassage,BusinessEvent,Notification,VehicleWatchlist,utc_now
from src.cameras.api import router as cameras
from src.event_center.api import router as events
from src.cameras import service as cs
from src.notifications.service import NotificationService
from src.notifications.config import EmailConfig
from src.notifications.email import SMTPEmailAdapter
from src.watchlists.vehicles import record_plate_result

@pytest.fixture
def setup(tmp_path,monkeypatch):
    url='sqlite:///'+(tmp_path/'test.db').as_posix()
    for k,v in {'DATT_DATABASE_URL':url,'DATT_REQUIRE_PERSISTENCE':'0','DATT_STORAGE_BACKEND':'local','DATT_STORAGE_ROOT':str(tmp_path)}.items(): monkeypatch.setenv(k,v)
    monkeypatch.delenv('DATT_EMAIL_PASSWORD',raising=False)
    command.upgrade(Config('src/db/alembic.ini'),'head')
    db=Database(url);app=FastAPI();app.include_router(cameras);app.include_router(events)
    with TestClient(app) as client: yield client,db,tmp_path
    db.dispose()


def addcam(c,**kw):
    return c.post('/api/cameras',json=dict(camera_name='Test',source_type='HTTP',source_url='https://example.invalid/camera',**kw))


@pytest.mark.parametrize('camera_id', [str(uuid4()), 'legacy_registry_key', None])
def test_face_history_preserves_event_camera_metadata(setup, camera_id):
    from src.ui.web_server import get_face_events
    from starlette.requests import Request
    import asyncio, json
    client, db, _ = setup
    event_id = uuid4()
    with db.transaction() as session:
        session.add(FaceEvent(id=event_id, camera_id=camera_id, decision='FACE_MATCH'))
    response = asyncio.run(get_face_events(Request({'type': 'http', 'query_string': b''})))
    assert response.status_code == 200
    event = next(e for e in json.loads(response.body)['events'] if e['id'] == str(event_id))
    assert event['camera_id'] == camera_id
    detail = client.get('/api/event_center/events/face:' + str(event_id))
    assert detail.status_code == 200
    assert detail.json()['event']['camera_id'] == camera_id


def test_camera_crud_aliases_selection_restart(setup):
    c,db,_=setup
    r=addcam(c);assert r.status_code==201
    item=r.json()['camera'];ident=item['id']
    assert c.get('/api/cameras/'+ident).json()['camera']['name']=='Test'
    assert c.get('/api/camera_management/cameras').json()['total']==1
    assert c.patch('/api/cameras/'+ident,json={'source_url':'https://example.invalid/new','zone':'Gate'}).status_code==200
    from src.config.camera_config import list_cameras
    assert any(x.id==ident and x.url.endswith('/new') for x in list_cameras())
    assert c.post('/api/cameras/'+ident+'/disable').status_code==200
    with pytest.raises(ValueError,match='DISABLED'):cs.registered_id(ident)
    with pytest.raises(ValueError,match='DISABLED'):cs.registered_id(source='https://example.invalid/new')
    assert c.post('/api/cameras/'+ident+'/enable').status_code==200
    db.dispose();assert cs.registered_id(ident)==ident
    assert c.delete('/api/cameras/'+ident).status_code==200
    assert c.get('/api/cameras/'+ident).status_code==404


@pytest.mark.parametrize('body',[{}, {'camera_name':'x','source_type':'bad','source_url':'x'},
    {'camera_name':'x','source_type':'http','source_url':'file:///etc/passwd'},
    {'camera_name':'x','source_type':'file','source_url':'../secret'},
    {'camera_name':'x','source_type':'youtube','source_url':'https://other.invalid/video'}])
def test_camera_invalid_sources(setup,body): assert setup[0].post('/api/cameras',json=body).status_code==400


def test_camera_active_delete_disable_validation(setup):
    c,db,_=setup;ident=addcam(c).json()['camera']['id']
    with db.transaction() as s:s.get(Camera,UUID(ident)).active_until=utc_now()+timedelta(minutes=1)
    assert c.delete('/api/cameras/'+ident).status_code==409
    assert c.post('/api/cameras/'+ident+'/disable').status_code==409
    assert c.patch('/api/cameras/'+ident,json={'source_url':'https://example.invalid/next'}).status_code==200


def test_connection_bounded_and_structured(setup,monkeypatch):
    from src.cameras.probe import probe
    import subprocess
    with patch('src.cameras.probe.subprocess.run',return_value=Mock(returncode=0)) as run:
        assert probe('RTSP','rtsp://example.invalid/live')['success']
        assert run.call_args.kwargs['timeout']==10
    with patch('src.cameras.probe.subprocess.run',side_effect=subprocess.TimeoutExpired('probe',10)):
        assert probe('HLS','https://example.invalid/a.m3u8')['code']=='TIMEOUT'
    ident=addcam(setup[0]).json()['camera']['id']
    monkeypatch.setattr('src.cameras.api.probe',lambda *a:dict(success=True,status='ok',code='FRAME_READ'))
    assert setup[0].post('/api/cameras/'+ident+'/test').json()['success']


def test_camera_manager_registered_reader_monitoring(setup,monkeypatch):
    from src.stream.camera_manager import CameraManager
    c,db,_=setup;ident=addcam(c).json()['camera']['id']
    reader=Mock(status='RUNNING',stream_alive=True)
    monkeypatch.setattr('src.stream.camera_manager.CameraReader',lambda **kw:reader)
    manager=CameraManager()
    try:
        cam=manager.start_camera(ident)
        assert cam.id==ident and manager.active_camera_id==ident
        assert c.delete('/api/cameras/'+ident).status_code==409
        c.patch('/api/cameras/'+ident,json={'source_url':'https://example.invalid/new'})
        manager.stop_camera();cam=manager.start_camera(ident)
        assert cam.url.endswith('/new')
        manager.stop_camera();c.post('/api/cameras/'+ident+'/disable')
        with pytest.raises(ValueError,match='DISABLED'):manager.start_camera(ident)
        with pytest.raises(ValueError,match='DISABLED'):manager.set_video_source('http',cam.url)
        reader.start.assert_called()
    finally:manager.stop_camera()


def seed(setup):
    c,db,tmp=setup;now=utc_now();target=uuid4()
    with db.transaction() as s:
        s.add(Target(id=target,name='Synthetic',target_type='face'));s.flush()
        f=FaceEvent(target_id=target,camera_id='gate',decision='FACE_MATCH',similarity=.8,created_at=now,face_crop_path='data/events/test.jpg');s.add(f)
        v=VehicleEvent(vehicle_class='car',track_id=1,first_seen=now,last_seen=now);s.add(v);s.flush()
        watch=VehicleWatchlist(plate_number='29A12345',vehicle_type='car',display_name='Watch');s.add(watch);s.flush()
        p=PlateEvent(vehicle_event_id=v.id,plate_text='29a-123.45',confidence=.9,created_at=now,plate_crop_path='data/events/test.jpg');s.add(p);s.flush()
        match=record_plate_result(s,p,'gate')
        s.add(VehiclePassage(session_key='session',camera_id='gate',track_id=1,vehicle_type='car',first_seen_at=now,last_seen_at=now,plate_text=p.plate_text))
        s.add(BusinessEvent(camera_id='gate',event_type='PLATE_RECOGNIZED',event_time=now,idempotency_key='business',plate_text=p.plate_text))
        config=EmailConfig(host='smtp.invalid',username='test',password='fake',sender='test@example.invalid',recipients=('to@example.invalid',),max_retries=1,retry_seconds=1)
        adapter=Mock();service=NotificationService(db,config,{'email':adapter})
        service.enqueue_vehicle(s,p,match)
        fid,pid,wid=f.id,p.id,watch.id
    return fid,pid,wid,service,adapter


def test_event_center_types_filters_pagination_detail_evidence(setup):
    c,db,tmp=setup;fid,pid,wid,_,_=seed(setup)
    r=c.get('/api/event_center/events');assert r.status_code==200,r.text
    data=r.json();assert data['total']==5 and {e['event_type'] for e in data['events']}=={'face','plate','vehicle','passage','business'}
    assert c.get('/api/event_center/events',params={'watchlist_match':'true'}).json()['total']==2
    assert c.get('/api/event_center/events',params={'notification_status':'pending'}).json()['total']==1
    assert c.get('/api/event_center/events',params={'event_type':'plate','plate':'29A 12345','target_id':str(wid)}).json()['total']==1
    assert c.get('/api/event_center/events',params={'camera':'gate'}).json()['total']==4
    assert c.get('/api/event_center/events',params={'from':'2099-01-01T00:00:00Z'}).json()['total']==0
    assert c.get('/api/event_center/events',params={'from':'yesterday'}).status_code==400
    assert c.get('/api/event_center/events',params={'page_size':2,'page':2,'sort':'asc'}).json()['total']==5
    detail=c.get('/api/event_center/events/face:'+str(fid));assert detail.status_code==200,detail.text
    assert detail.json()['event']['similarity']==.8
    assert c.get('/api/event_center/events/face:'+str(uuid4())).status_code==404
    from src.storage import get_storage
    img=Image.new('RGB',(20,20),'white');b=io.BytesIO();img.save(b,format='JPEG');get_storage().save_bytes('data/events/test.jpg',b.getvalue())
    response=c.get(detail.json()['event']['evidence']['url']);assert response.status_code==200
    assert response.headers['x-content-type-options']=='nosniff'
    with db.transaction() as s:s.get(FaceEvent,fid).face_crop_path='../private'
    assert c.get(detail.json()['event']['evidence']['url']).status_code==400


def test_vehicle_notification_cooldown_retry_reload_evidence(setup):
    _,db,_=setup;fid,pid,wid,service,adapter=seed(setup)
    with db.transaction() as s:
        row=s.scalar(select(Notification).where(Notification.plate_event_id==pid))
        assert row.status=='pending' and row.event_id is None
        s.add(PlateEvent(vehicle_event_id=s.get(PlateEvent,pid).vehicle_event_id,plate_text='29A12345',created_at=utc_now()))
        s.flush();p=s.scalars(select(PlateEvent).order_by(PlateEvent.created_at.desc())).first()
        match=record_plate_result(s,p,'gate');service.enqueue_vehicle(s,p,match);service.enqueue_vehicle(s,p,match)
        assert len(list(s.scalars(select(Notification))))==2
        assert s.scalar(select(Notification.status).where(Notification.plate_event_id==p.id))=='suppressed'
        message=SMTPEmailAdapter(service.config,lambda:Mock(open=lambda _:io.BytesIO(b'fake-jpeg'))).message(row)
        assert 'Vehicle' in message['Subject'] and '29A12345' in message.get_body().get_content()
        assert len(list(message.iter_attachments()))==1
    adapter.send.side_effect=[OSError('secret'),None]
    assert service.deliver_one()
    fresh=NotificationService(db,service.config,{'email':adapter})
    assert fresh.deliver_one(utc_now()+timedelta(seconds=3))
    with db.transaction() as s:
        row=s.scalar(select(Notification).where(Notification.plate_event_id==pid));assert row.status=='sent' and row.retry_count==1


@pytest.mark.parametrize('disabled,plate',[(True,'29A12345'),(False,'OTHER')])
def test_non_active_match_no_notification(setup,disabled,plate):
    _,db,_=setup;_,pid,wid,service,_=seed(setup)
    with db.transaction() as s:
        watch=s.get(VehicleWatchlist,wid);watch.status='disabled' if disabled else 'active';s.flush()
        p=PlateEvent(vehicle_event_id=s.get(PlateEvent,pid).vehicle_event_id,plate_text=plate,created_at=utc_now());s.add(p);s.flush()
        service.enqueue_vehicle(s,p,record_plate_result(s,p,'gate'))
        assert not s.scalar(select(Notification.id).where(Notification.plate_event_id==p.id))


def test_event_order_time_bounds_empty_and_page_consistency(setup):
    c,db,_=setup
    assert c.get('/api/event_center/events').json()['events']==[]
    seed(setup)
    with db.transaction() as s:
        face=s.scalar(select(FaceEvent));face.created_at=utc_now()-timedelta(days=1)
    ascending=c.get('/api/event_center/events',params={'sort':'asc'}).json()['events']
    descending=c.get('/api/event_center/events',params={'sort':'desc'}).json()['events']
    assert ascending[0]['event_type']=='face' and descending[-1]['event_type']=='face'
    page1=c.get('/api/event_center/events',params={'page_size':2,'page':1}).json()['events']
    page2=c.get('/api/event_center/events',params={'page_size':2,'page':2}).json()['events']
    assert not {r['event_id'] for r in page1}&{r['event_id'] for r in page2}
    assert c.get('/api/event_center/events',params={'to':(utc_now()-timedelta(hours=1)).isoformat()}).json()['total']==1
    assert c.get('/api/event_center/events',params={'page_size':1000}).status_code==400


def test_camera_file_links_existing_video_source(setup):
    c,db,_=setup;key='data/uploads/videos/test.mp4'
    with db.transaction() as s:
        v=VideoSource(original_filename='test.mp4',storage_path=key);s.add(v);s.flush();ident=v.id
    result=c.post('/api/cameras',json={'name':'File','source_type':'File','url':key})
    assert result.status_code==201 and result.json()['camera']['video_source_id']==str(ident)
    assert c.post('/api/cameras',json={'name':'Missing','source_type':'File','url':'data/uploads/videos/missing.mp4'}).status_code==400


def test_camera_fk_history_prevents_delete(setup):
    from src.db.models import DetectionEvent
    c,db,_=setup;ident=addcam(c).json()['camera']['id']
    with db.transaction() as s:s.add(DetectionEvent(camera_id=UUID(ident),event_type='vehicle',frame_id=0))
    assert c.delete('/api/cameras/'+ident).status_code==409


def test_vehicle_bounded_failure_and_channel_extension(setup):
    _,db,_=setup;_,pid,_,service,adapter=seed(setup)
    adapter.send.side_effect=RuntimeError('private smtp value')
    assert service.deliver_one();assert service.deliver_one(utc_now()+timedelta(seconds=5))
    with db.transaction() as s:
        row=s.scalar(select(Notification).where(Notification.plate_event_id==pid))
        assert row.status=='failed' and row.error=='delivery_failed' and row.retry_count==1
        row.status='pending';row.channel='telegram';row.next_attempt_at=utc_now()
    future_adapter=Mock()
    fresh=NotificationService(db,service.config,{'telegram':future_adapter})
    assert fresh.deliver_one();future_adapter.send.assert_called_once()
    with db.transaction() as s:
        row=s.scalar(select(Notification).where(Notification.plate_event_id==pid));row.status='pending';row.channel='slack';row.next_attempt_at=utc_now()
    slack=Mock();fresh=NotificationService(db,service.config,{'slack':slack})
    assert fresh.deliver_one();slack.send.assert_called_once()


def test_camera_thumbnail_id_only_and_disabled(setup,monkeypatch):
    c,_,_=setup;camera=addcam(c).json()['camera']
    monkeypatch.setattr('src.cameras.thumbnails.subprocess.run',lambda *a,**kw:Mock(returncode=0,stdout=b'\xff\xd8synthetic'))
    r=c.get(camera['thumbnail']);assert r.status_code==200 and r.headers['content-type']=='image/jpeg'
    c.post('/api/cameras/'+camera['id']+'/disable')
    assert c.get(camera['thumbnail']).headers['content-type']=='image/svg+xml'


def test_disabled_camera_request_does_not_clear_monitoring(setup):
    from src.ui.video_stream import StreamRequestHandler
    c,_,_=setup;ident=addcam(c).json()['camera']['id'];c.post('/api/cameras/'+ident+'/disable')
    handler=object.__new__(StreamRequestHandler);handler.camera_manager=Mock();handler.state=Mock();handler._send_json_response=Mock()
    handler._execute_camera_switch(ident)
    assert handler._send_json_response.call_args.kwargs['code']==409
    handler.state.clear_frames.assert_not_called();handler.camera_manager.switch_camera.assert_not_called()


def test_hls_fe_type_alias_is_preserved(setup):
    response=setup[0].post('/api/cameras',json={'name':'HLS','source_type':'hls','url':'https://example.invalid/live.m3u8'})
    assert response.status_code==201
    camera=response.json()['camera']
    assert camera['source_type']=='hls' and camera['type']=='direct_hls'


def test_registered_camera_protects_video_source_media(setup,monkeypatch):
    from src.ui.web_server import app
    from src.storage import get_storage
    _,db,_=setup;key='data/uploads/videos/linked.mp4'
    get_storage().save_bytes(key,b'synthetic')
    with db.transaction() as s:
        video=VideoSource(original_filename='linked.mp4',storage_path=key);s.add(video);s.flush()
        s.add(Camera(name='Linked',source_type='file',source=key,video_source_id=video.id));ident=video.id
    # Existing endpoint opens a Database; capture it to close its pool on Windows.
    created=[]
    def factory():
        item=Database();created.append(item);return item
    monkeypatch.setattr('src.db.database.Database',factory)
    try:
        with TestClient(app) as client:assert client.delete('/api/video_sources/'+str(ident)).status_code==409
        assert get_storage().exists(key)
        with db.transaction() as s:assert s.get(VideoSource,ident) is not None
    finally:
        for item in created:item.dispose()
