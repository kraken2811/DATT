"""Isolated production vehicle path; real DB, synthetic OCR and image evidence."""
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from uuid import uuid4
import numpy as np
import pytest
from src.db.database import Database
from src.db.models import Base, VehicleWatchlist, VehicleEvent, PlateEvent, BusinessEvent
from src.events.db_worker import DatabaseWorker
from src.events.event_dto import VehiclePassageDTO
from src.event_center.service import query
from src.watchlists.vehicles import operate, fields
from src.ocr.plate_tracker import VehiclePlateManager
from tests.test_plate_consensus import candidate, tracks


@pytest.fixture
def db(tmp_path):
    db = Database('sqlite:///' + (tmp_path/'vehicle.db').as_posix())
    Base.metadata.create_all(db.engine)
    yield db
    db.dispose()


def test_declared_color_restart_legacy_and_validation(db):
    old=operate(db,'create',body={'plate_number':'29A12345'})['vehicle']
    assert old['vehicle_color'] is None
    updated=operate(db,'update',old['id'],{'vehicle_color':'silver'})['vehicle']
    assert updated['vehicle_color']=='silver'
    fresh=Database(str(db.engine.url))
    try:
        assert operate(fresh,'list')['vehicles'][0]['vehicle_color']=='silver'
    finally: fresh.dispose()
    for bad in ('unknown','pink',[],42):
        with pytest.raises(ValueError): fields({'vehicle_color':bad},partial=True)
    assert operate(db,'update',old['id'],{'vehicle_color':None})['vehicle']['vehicle_color'] is None


@pytest.mark.parametrize('status,plate,active,expected',[
    ('PROVISIONAL','29A12345',True,0),('CONFIRMED','29A99999',True,0),
    ('CONFIRMED','29A12345',False,0),('CONFIRMED','29A12345',True,1)])
def test_match_then_color_one_event(db,tmp_path,status,plate,active,expected):
    target=VehicleWatchlist(plate_number='29A12345',vehicle_color='blue',status='active' if active else 'disabled')
    with db.transaction() as session: session.add(target)
    worker=DatabaseWorker.__new__(DatabaseWorker)
    worker.db=db; worker.snapshot_dir=tmp_path;worker.queue_coalesced=0;worker.write_latencies=[];worker.notifications=Mock()
    now=datetime.now(timezone.utc)
    dto=VehiclePassageDTO(id=uuid4(),session_key=str(uuid4()),camera_id='test',track_id=1,
        first_seen_at=now,last_seen_at=now,plate_text=plate,plate_status=status,plate_confidence=.91,
        vehicle_type='car',is_final=True,finalized_at=now)
    crop=np.full((80,80,3),(0,0,255),np.uint8)
    from src.recognition.color_extractor import analyze_vehicle_color
    saved=[]
    def save(path,frame,params):
        import cv2
        assert cv2.imwrite(path,frame,params)
        saved.append(path)
        return True
    with patch('src.events.db_worker.analyze_vehicle_color',wraps=analyze_vehicle_color) as color, patch('src.events.db_worker.save_image',side_effect=save):
        assert worker._persist_batch([('PASSAGE',dto,(crop,None))])
        assert worker._persist_batch([('PASSAGE',dto,(crop,None))])
        assert color.call_count==expected
        assert len(saved)==expected
    with db.transaction() as session:
        assert session.get(VehicleWatchlist,target.id).vehicle_color=='blue'
        assert session.query(VehicleEvent).count()==session.query(PlateEvent).count()==expected
        assert session.query(BusinessEvent).count()==expected
        result=query(session,{})
        assert result['total']==expected
        if expected:
            event=result['events'][0]
            assert event['detected_vehicle_color']=='red'
            assert event['watchlist_vehicle_color']=='blue'
            assert event['detected_vehicle_color_confidence']==1.0
            assert event['match_type']=='PLATE' and event['plate']=='29A12345'
            assert event['evidence']['url'].endswith('/evidence')
    assert worker.notifications.enqueue_vehicle.call_count==expected


def test_consensus_honors_min_frames_ratio_and_bounded_history():
    reader=Mock(); manager=VehiclePlateManager(reader,eval_interval=10,min_observations=3,history_size=5)
    frame=np.zeros((200,200,3),np.uint8)
    values=['24C14059','24C14058','24C14058','24C14058']
    for index,value in enumerate(values):
        reader.extract_license_plate.return_value=candidate(value)
        state=manager.process_vehicle_tracks(frame,vehicle_tracks=tracks(),frame_id=index*10)[1]
        assert bool(state.confirmed_plate)==(index==3)
    assert state.confirmed_plate=='24C14058'
    assert reader.extract_license_plate.call_count==4
    manager.process_vehicle_tracks(frame,vehicle_tracks=tracks(),frame_id=31)
    assert reader.extract_license_plate.call_count==4
    assert len(state.plate_history)<=5
    assert {'raw_text','normalized_text','frame_id','confidence','crop_quality'} <= state.plate_history[0].keys()


def test_weak_ocr_never_confirms_and_history_is_bounded():
    reader=Mock();reader.extract_license_plate.return_value=candidate('29A12345',confidence=.1)
    manager=VehiclePlateManager(reader,eval_interval=10,history_size=5)
    for frame_id in range(0,200,10):
        state=manager.process_vehicle_tracks(np.zeros((200,200,3),np.uint8),vehicle_tracks=tracks(),frame_id=frame_id)[1]
    assert len(state.plate_history)==5
    assert not state.confirmed_plate


def test_event_manager_waits_for_confirmed_and_collects_late_result():
    from src.events.event_manager import EventManager
    from types import SimpleNamespace
    worker=Mock(); manager=EventManager(db_worker=worker)
    state=SimpleNamespace(status='PROVISIONAL',plate_text='29A99999',confirmed_plate='',confidence=.9,plate_crop=None)
    manager.process_vehicle_frame('test',tracks(),{1:state},frame=np.zeros((200,200,3),np.uint8),frame_id=1)
    passage=manager._active_passages[('test',1)]
    assert passage.plate_text=='' and passage.best_vehicle_frame_id==1
    state.status='CONFIRMED';state.confirmed_plate='29A12345'
    manager.reset()
    assert worker.enqueue_passage.call_count==1
    assert worker.enqueue_passage.call_args.args[0].plate_text=='29A12345'
    assert worker.enqueue_passage.call_args.args[0].vehicle_color is None


def test_existing_notification_outbox_traces_same_event(db,tmp_path):
    from src.notifications.config import EmailConfig
    from src.notifications.service import NotificationService
    from src.db.models import Notification
    target=VehicleWatchlist(plate_number='29A12345',vehicle_color='silver',status='active')
    with db.transaction() as session: session.add(target)
    adapter=Mock()
    config=EmailConfig(host='smtp.example.invalid',username='test',password='test-only',
        sender='from@example.invalid',recipients=('to@example.invalid',),cooldown=300,max_retries=2,retry_seconds=1)
    worker=DatabaseWorker.__new__(DatabaseWorker)
    worker.db=db;worker.snapshot_dir=tmp_path;worker.queue_coalesced=0;worker.write_latencies=[]
    worker.notifications=NotificationService(db,config,{'email':adapter})
    now=datetime.now(timezone.utc)
    dto=VehiclePassageDTO(id=uuid4(),session_key=str(uuid4()),camera_id='test',track_id=5,
        first_seen_at=now,last_seen_at=now,plate_text='29A12345',plate_status='CONFIRMED',
        plate_confidence=.9,is_final=True,finalized_at=now,best_plate_image_path='data/events/test.jpg')
    assert worker._persist_batch([('PASSAGE',dto,None)])
    assert worker._persist_batch([('PASSAGE',dto,None)])
    with db.transaction() as session:
        notification=session.query(Notification).one()
        event=query(session,{})['events'][0]
        assert event['source_event_id']==str(notification.plate_event_id)
        assert notification.payload['event_id']==event['source_event_id']
        assert event['notification_status']=='pending'
    assert worker.notifications.deliver_one()
    assert adapter.send.call_count==1
    with db.transaction() as session:
        assert query(session,{})['events'][0]['notification_status']=='sent'


def test_nullable_migration_preserves_old_watchlist(tmp_path,monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    url='sqlite:///'+(tmp_path/'legacy.db').as_posix()
    monkeypatch.setenv('DATT_DATABASE_URL',url)
    cfg=Config('src/db/alembic.ini');command.upgrade(cfg,'0010')
    legacy=Database(url);ident=uuid4().hex
    with legacy.transaction() as session:
        session.execute(text("INSERT INTO vehicle_watchlists (id,plate_number,vehicle_type,display_name,owner_info,notes,status,created_at,updated_at) VALUES (:id,'29A12345','car','old name','old owner','old notes','active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),{'id':ident})
    command.upgrade(cfg,'head')
    item=operate(legacy,'list')['vehicles'][0]
    assert item['vehicle_color'] is None and item['display_name']=='old name' and item['owner_info']=='old owner'
    legacy.dispose()


def test_reused_track_generation_cannot_inherit_confirmed_plate():
    from src.events.event_manager import EventManager
    from types import SimpleNamespace
    worker=Mock();manager=EventManager(db_worker=worker)
    first=SimpleNamespace(generation=1,status='CONFIRMED',confirmed_plate='29A12345',confidence=.9,plate_crop=None)
    second=SimpleNamespace(generation=2,status='PROVISIONAL',confirmed_plate='',confidence=.9,plate_crop=None)
    manager.process_vehicle_frame('test',tracks(),{1:first},frame_id=1)
    manager.process_vehicle_frame('test',tracks(),{1:second},frame_id=90)
    assert worker.enqueue_passage.call_count==1
    assert manager._active_passages[('test',1)].confirmed_plate==''
    manager.reset()
    assert worker.enqueue_passage.call_count==1
