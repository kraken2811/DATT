"""Policy boundaries and real isolated persistence; no production data/network."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4
import numpy as np
import pytest

from src.events.policy import ThresholdEpisodes
from src.events.event_dto import FaceEventDTO, VehiclePassageDTO, BusinessEventDTO
from src.events.db_worker import DatabaseWorker
from src.db.database import Database
from src.db.models import Base, Target, VehicleWatchlist, FaceEvent, BusinessEvent, VehiclePassage, VehicleEvent
from src.event_center.service import query


def test_crowd_boundaries_and_timestamp():
    s = ThresholdEpisodes()
    assert s.people('a', 40, 0, 1000) is None
    assert s.people('a', 40, 500, 1500) is None
    assert s.people('a', 41, 600, 1600) is None
    assert s.people('a', 41, 779, 1779) is None
    event = s.people('a', 41, 785, 1785)
    assert event['timestamp'] == 1780
    assert event['duration_seconds'] == 185
    assert s.people('a', 50, 1000, 2000) is None


def test_crowd_continuity_reset_and_future_episode():
    s = ThresholdEpisodes()
    assert s.people('a', 41, 0, 1000) is None
    assert s.people('a', 41, 170, 1170) is None
    assert s.people('a', 40, 171, 1171) is None
    assert s.people('a', 45, 172, 1172) is None
    assert s.people('a', 45, 351, 1351) is None
    first = s.people('a', 45, 352, 1352)
    assert first
    assert s.people('a', 40, 353, 1353) is None
    assert s.people('a', 41, 354, 1354) is None
    second = s.people('a', 41, 534, 1534)
    assert second and second['episode'] != first['episode']


def test_camera_location_isolation_and_congestion_edges():
    s = ThresholdEpisodes()
    s.people('a', 41, 0, 1000, 'zone1')
    assert s.people('b', 41, 180, 1180, 'zone1') is None
    assert s.people('a', 41, 180, 1180, 'zone2') is None
    assert s.people('a', 41, 180, 1180, 'zone1')
    assert s.congestion('a', 40, 0, 1000) is None
    first = s.congestion('a', 41, 1, 1001)
    assert first and first['timestamp'] == 1001
    assert s.congestion('a', 43, 2, 1002) is None
    assert s.congestion('b', 18, 2, 1002) is None
    s.congestion('a', 40, 3, 1003)
    assert s.congestion('a', 41, 4, 1004)['episode'] != first['episode']


@pytest.fixture
def worker(tmp_path):
    db = Database(url='sqlite:///' + (tmp_path / 'policy.db').as_posix())
    Base.metadata.create_all(db.engine)
    w = DatabaseWorker.__new__(DatabaseWorker)
    w.db, w.snapshot_dir = db, tmp_path
    w.queue_coalesced, w.write_latencies = 0, []
    w.notifications = Mock()
    yield w
    db.dispose()


def test_normal_and_disabled_face_do_not_persist(worker):
    inactive = uuid4()
    with worker.db.transaction() as session:
        session.add(Target(id=inactive, name='inactive', target_type='person', active=False))
    for target in (None, inactive):
        dto = FaceEventDTO(id=uuid4(), track_id=1, camera_id='a', target_id=target)
        with patch('src.events.db_worker.save_image') as image:
            assert worker._persist_batch([('FACE_EVENT', dto, np.zeros((40,40,3),np.uint8))])
            image.assert_not_called()
    with worker.db.transaction() as session:
        assert session.query(FaceEvent).count() == session.query(BusinessEvent).count() == 0
    worker.notifications.enqueue_face.assert_not_called()


def test_face_match_one_logical_event_retry_and_historical_preservation(worker):
    target = uuid4()
    old_id = uuid4()
    with worker.db.transaction() as session:
        session.add(Target(id=target, name='active', target_type='person', active=True))
        session.add(BusinessEvent(id=old_id, camera_id='old', event_type='PEOPLE_COUNT_CHANGED',
            event_time=datetime.now(timezone.utc), idempotency_key='historical', event_metadata={'unchanged':True}))
    dto = FaceEventDTO(id=uuid4(), track_id=2, camera_id='a', target_id=target,
        similarity=.6, face_crop_path='data/events/existing-test.jpg',created_at=datetime.now(timezone.utc))
    assert worker._persist_batch([('FACE_EVENT', dto, None)])
    assert worker._persist_batch([('FACE_EVENT', dto, None)])
    with worker.db.transaction() as session:
        result = query(session,{})
        assert result['total'] == 2
        assert len([e for e in result['events'] if e['semantic_type']=='FACE_WATCHLIST_MATCH']) == 1
        assert query(session,{'event_type':'FACE_WATCHLIST_MATCH'})['total'] == 1
        assert session.get(BusinessEvent,old_id).event_metadata == {'unchanged':True}
    worker.notifications.enqueue_face.assert_called_once()


@pytest.mark.parametrize('plate,active,expected', [('12A12345',True,1),('12A12345',False,0),('99Z99999',True,0),(None,True,0)])
def test_vehicle_existing_plate_contract_and_no_normal_evidence(worker,plate,active,expected):
    with worker.db.transaction() as session:
        session.add(VehicleWatchlist(plate_number='12A12345',status='active' if active else 'disabled'))
    now=datetime.now(timezone.utc)
    dto=VehiclePassageDTO(id=uuid4(),session_key=str(uuid4()),camera_id='a',track_id=3,
        first_seen_at=now,last_seen_at=now,is_final=True,finalized_at=now,
        plate_text=plate,plate_status='CONFIRMED',vehicle_color='white',best_vehicle_image_path='data/events/vehicle-test.jpg')
    with patch('src.events.db_worker.save_image') as image:
        assert worker._persist_batch([('PASSAGE',dto,(None,None))])
        assert worker._persist_batch([('PASSAGE',dto,(None,None))])
        image.assert_not_called()
    with worker.db.transaction() as session:
        assert session.query(VehiclePassage).count()==expected
        assert session.query(VehicleEvent).count()==expected
        result=query(session,{})
        assert result['total']==expected
        if expected:
            event=result['events'][0]
            assert event['semantic_type']=='VEHICLE_WATCHLIST_MATCH'
            assert event['match_type']=='PLATE'
            assert event['evidence']['key']=='data/events/vehicle-test.jpg'
    assert worker.notifications.enqueue_vehicle.call_count==expected


def test_legacy_business_and_nonfinal_passage_filtered(worker):
    dto=BusinessEventDTO(id=uuid4(),passage_id=None,camera_id='a',event_type='VEHICLE_ENTER',
        event_time=datetime.now(timezone.utc),idempotency_key=str(uuid4()))
    assert worker._persist_batch([('BUSINESS_EVENT',dto,None)])
    with worker.db.transaction() as session:
        assert query(session,{})['total']==0


def test_standalone_historical_watchlist_business_event_is_preserved(worker):
    with worker.db.transaction() as session:
        session.add(BusinessEvent(id=uuid4(),camera_id='old',event_type='FACE_WATCHLIST_MATCH',
            event_time=datetime.now(timezone.utc),idempotency_key='old-standalone',event_metadata={}))
    with worker.db.transaction() as session:
        assert query(session,{})['total']==1


def test_actual_vehicle_count_classes_and_zone_scope():
    from src.events.event_manager import EventManager
    worker=Mock()
    manager=EventManager(db_worker=worker)
    def tracks(classes):
        return SimpleNamespace(tracker_id=np.arange(len(classes)),class_id=np.array(classes),
            xyxy=np.tile([0,0,40,40],(len(classes),1)),confidence=np.ones(len(classes)))
    assert not manager.process_vehicle_frame('a',tracks([3]*20+[2]*20+[5]*4+[7]*4))
    assert len(manager.process_vehicle_frame('a',tracks([3]*21+[2]*20)))==1
    assert not manager.process_vehicle_frame('a',tracks([3]*21+[2]*20))
    assert not manager.process_vehicle_frame('b',tracks([3]*10+[2]*8))
    assert not manager.process_vehicle_frame('a',tracks([3]*21+[2]*20),in_zone_ids=set(range(40)),zone_id='zone1')
    assert worker.enqueue_business_event.call_count==1


def test_audit_mode_drops_before_queue(worker,monkeypatch):
    monkeypatch.setenv('DATT_EVENT_AUDIT_ONLY','1')
    worker._task_queue=Mock()
    assert worker._put_task(('FACE_EVENT',None,None),True)
    worker._task_queue.put_nowait.assert_not_called()


def test_face_event_manager_dedup_and_notification_chain(worker):
    from src.events.event_manager import EventManager
    from src.notifications.config import EmailConfig
    from src.notifications.service import NotificationService
    from src.db.models import Notification
    target=uuid4()
    with worker.db.transaction() as session:
        session.add(Target(id=target,name='Test target',target_type='person',active=True))
    adapter=Mock()
    worker.notifications=NotificationService(worker.db,EmailConfig(host='smtp.example.invalid',
        username='test',password='test',sender='from@example.invalid',recipients=('to@example.invalid',)),{'email':adapter})
    queue=Mock()
    manager=EventManager(db_worker=queue)
    assert manager.process_face_matches('a',{})==[]
    match=SimpleNamespace(target_id=str(target),target_name='Test target',decision='FACE_MATCH',
        match_type='FACE_MATCH',face_score=.6,score=.6)
    assert len(manager.process_face_matches('a',{1:match}))==1
    assert manager.process_face_matches('a',{1:match})==[]
    dto=queue.enqueue_face_event.call_args.args[0]
    assert worker._persist_batch([('FACE_EVENT',dto,None)])
    with worker.db.transaction() as session:
        notice=session.query(Notification).one()
        assert notice.status=='pending'
        assert query(session,{})['events'][0]['notification_status']=='pending'
    assert worker.notifications.deliver_one()
    adapter.send.assert_called_once()
    with worker.db.transaction() as session:
        assert query(session,{})['events'][0]['notification_status']=='sent'
