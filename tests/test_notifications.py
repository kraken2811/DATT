from datetime import timedelta
import logging
from types import SimpleNamespace
from uuid import uuid4
import io
import threading
import time
from unittest.mock import Mock
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, inspect
from src.db.database import Database
from src.db.models import Target, FaceEvent, Notification, utc_now
from src.notifications.config import EmailConfig
from src.notifications.service import NotificationService
from src.notifications.email import SMTPEmailAdapter


@pytest.fixture
def setup(tmp_path, monkeypatch):
    url = 'sqlite:///' + (tmp_path/'notifications.db').as_posix()
    monkeypatch.setenv('DATT_DATABASE_URL', url)
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '0')
    monkeypatch.delenv('DATT_EMAIL_HOST', raising=False)
    command.upgrade(Config('src/db/alembic.ini'), 'head')
    db = Database(url)
    target = uuid4()
    with db.transaction() as s:
        s.add(Target(id=target, name='Registered person', target_type='face'))
    config = EmailConfig(host='smtp.example.invalid', username='test', password='test-only',
                         sender='from@example.invalid', recipients=('to@example.invalid',),
                         cooldown=300, max_retries=2, retry_seconds=1)
    adapter = Mock()
    service = NotificationService(db, config, {'email': adapter})
    yield db, target, service, adapter
    service.stop()
    db.dispose()


def enqueue(setup, decision='FACE_MATCH', camera='gate', target=True):
    db, ident, service, _ = setup
    event_id = uuid4()
    with db.transaction() as s:
        event = FaceEvent(id=event_id, target_id=ident if target else None,
                          decision=decision, similarity=.87, created_at=utc_now(),
                          face_crop_path='data/events/evidence.jpg')
        s.add(event)
        s.flush()
        service.enqueue_face(s, event, SimpleNamespace(camera_id=camera, target_name='Person'))
    return event_id


def history(setup):
    with setup[0].transaction() as s:
        return list(s.scalars(select(Notification).order_by(Notification.created_at)))


def test_match_history_and_delivery(setup):
    eid = enqueue(setup)
    rows = history(setup)
    assert len(rows)==1 and rows[0].event_id == eid and rows[0].status=='pending'
    assert rows[0].payload['similarity']==.87
    assert rows[0].payload['evidence_key']=='data/events/evidence.jpg'
    assert setup[2].deliver_one()
    assert history(setup)[0].status=='sent' and history(setup)[0].sent_at
    setup[3].send.assert_called_once()


@pytest.mark.parametrize('decision,target',[('UNKNOWN',True),('CHECKING',True),('COLOR_MATCH',True),('FACE_MATCH',False)])
def test_nonmatch_ignored(setup, decision, target):
    enqueue(setup, decision, target=target)
    assert history(setup)==[]
    assert not setup[2].deliver_one()
    setup[3].send.assert_not_called()


def test_cooldown_persists_across_service_restart_and_camera_scope(setup):
    enqueue(setup)
    db, target, service, adapter = setup
    restarted = NotificationService(db, service.config, {'email': adapter})
    new = (db,target,restarted,adapter)
    enqueue(new)
    enqueue(new,camera='other')
    assert [r.status for r in history(setup)]==['pending','suppressed','pending']
    with db.transaction() as s:
        first=s.get(Notification,history(setup)[0].id)
        first.created_at=utc_now()-timedelta(seconds=301)
    enqueue(new)
    assert history(setup)[-1].status=='pending'


def test_bounded_retry_and_failed_delivery_redacts_errors(setup):
    enqueue(setup)
    setup[3].send.side_effect=RuntimeError('secret-password-sensitive')
    now=utc_now()
    for delta in (0,2,5): assert setup[2].deliver_one(now+timedelta(seconds=delta))
    row=history(setup)[0]
    assert row.status=='failed' and row.retry_count==2 and row.error=='delivery_failed'
    assert not setup[2].deliver_one(now+timedelta(days=1))
    assert setup[3].send.call_count==3


def test_retry_success(setup):
    enqueue(setup)
    setup[3].send.side_effect=[OSError('private'),None]
    assert setup[2].deliver_one()
    assert not setup[2].deliver_one(utc_now()-timedelta(seconds=1))
    assert setup[2].deliver_one(utc_now()+timedelta(seconds=2))
    row=history(setup)[0]
    assert row.status=='sent' and row.retry_count==1 and row.error is None


def test_missing_config_no_crash_and_history(setup, caplog):
    db,target,_,adapter=setup
    with caplog.at_level('INFO'):
        service=NotificationService(db,EmailConfig(),{'email':adapter})
    enqueue((db,target,service,adapter))
    service.start()
    assert service._thread is None and not service.deliver_one()
    assert history(setup)[0].error=='CONFIGURED=false'
    assert 'CONFIGURED=false' in caplog.text
    adapter.send.assert_not_called()


def test_rollback_has_no_email(setup):
    db,target,service,adapter=setup
    with pytest.raises(RuntimeError):
        with db.transaction() as s:
            event=FaceEvent(target_id=target,decision='FACE_MATCH',created_at=utc_now())
            s.add(event); s.flush()
            service.enqueue_face(s,event,SimpleNamespace(camera_id='gate',target_name='Person'))
            raise RuntimeError('rollback')
    assert history(setup)==[] and not service.deliver_one()
    adapter.send.assert_not_called()


def test_idempotent_enqueue(setup):
    eid=enqueue(setup)
    with setup[0].transaction() as s:
        setup[2].enqueue_face(s,s.get(FaceEvent,eid),SimpleNamespace(camera_id='gate',target_name='Person'))
    assert len(history(setup))==1


def test_optional_evidence_and_email_fields(setup):
    enqueue(setup)
    row=history(setup)[0]
    storage=Mock(); storage.open.return_value=io.BytesIO(b'jpeg-fixture')
    adapter=SMTPEmailAdapter(setup[2].config,lambda:storage)
    message=adapter.message(row)
    assert len(list(message.iter_attachments()))==1
    body=message.get_body().get_content()
    for value in ('Person','gate',str(row.event_id),str(row.target_id),'0.87'): assert value in body
    storage.open.side_effect=FileNotFoundError()
    assert 'Evidence: unavailable' in adapter.message(row).get_body().get_content()


def test_worker_is_async(setup):
    enqueue(setup)
    entered=threading.Event(); release=threading.Event()
    def send(item): entered.set(); release.wait(2)
    setup[3].send.side_effect=send
    before=time.monotonic(); setup[2].start()
    assert time.monotonic()-before < .5 and entered.wait(2)
    release.set()
    setup[2].stop(3)
    assert history(setup)[0].status=='sent'


def test_db_worker_hook_uses_persisted_face_event(setup,tmp_path):
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import FaceEventDTO
    worker=DatabaseWorker(str(setup[0].engine.url),snapshot_dir=tmp_path/'evidence')
    worker.notifications=setup[2]
    dto=FaceEventDTO(id=uuid4(),track_id=1,camera_id='gate',target_id=setup[1],created_at=utc_now())
    try:
        assert worker._persist_batch([('FACE_EVENT',dto,None)])
        assert history(setup)[0].event_id==dto.id
    finally: worker.stop()


def test_migration_history(setup):
    assert 'notifications' in inspect(setup[0].engine).get_table_names()
    with setup[0].transaction() as s:
        from sqlalchemy import text
        from alembic.script import ScriptDirectory
        assert s.scalar(text('select version_num from alembic_version'))==ScriptDirectory.from_config(Config('src/db/alembic.ini')).get_current_head()


def test_invalid_configuration(monkeypatch):
    monkeypatch.setenv('DATT_EMAIL_PORT','invalid')
    assert not EmailConfig.from_env().configured


def test_smtp_tls_transport_is_mocked(setup, monkeypatch):
    enqueue(setup)
    storage=Mock(); storage.open.side_effect=FileNotFoundError()
    smtp=Mock(); smtp.send_message.return_value={}
    factory=Mock(); factory.return_value.__enter__=Mock(return_value=smtp)
    factory.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr('src.notifications.email.smtplib.SMTP',factory)
    SMTPEmailAdapter(setup[2].config,lambda:storage).send(history(setup)[0])
    factory.assert_called_once_with('smtp.example.invalid',587,timeout=15)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with('test','test-only')
    smtp.send_message.assert_called_once()


def test_pending_reloaded_by_new_worker(setup):
    enqueue(setup)
    db,target,old,adapter=setup
    fresh=NotificationService(db,old.config,{'email':adapter})
    assert fresh.deliver_one()
    assert history(setup)[0].status=='sent'


def test_missing_notification_schema_does_not_lose_face_event(setup,tmp_path):
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import FaceEventDTO
    Notification.__table__.drop(setup[0].engine)
    worker=DatabaseWorker(str(setup[0].engine.url),snapshot_dir=tmp_path/'evidence')
    dto=FaceEventDTO(id=uuid4(),track_id=1,camera_id='gate',target_id=setup[1],created_at=utc_now())
    try:
        assert worker._persist_batch([('FACE_EVENT',dto,None)])
        with setup[0].transaction() as s: assert s.get(FaceEvent,dto.id) is not None
    finally: worker.stop()


def test_missing_notification_schema_does_not_lose_plate_event(setup, tmp_path):
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import VehiclePassageDTO
    from src.db.models import PlateEvent, VehicleWatchlist, VehicleWatchlistResult

    # Add active vehicle watchlist target
    with setup[0].transaction() as s:
        s.add(VehicleWatchlist(id=uuid4(), plate_number='30A10010', display_name='Xe test', status='active'))

    # Drop notifications table to simulate missing/broken schema
    Notification.__table__.drop(setup[0].engine)

    worker = DatabaseWorker(str(setup[0].engine.url), snapshot_dir=tmp_path / 'evidence')
    now = utc_now()
    dto = VehiclePassageDTO(
        id=uuid4(),
        session_key='session-plate-fail',
        camera_id='gate',
        track_id=88,
        first_seen_at=now,
        last_seen_at=now,
        plate_text='30A10010',
        vehicle_type='car',
        is_final=True,
        created_at=now,
        updated_at=now,
        finalized_at=now,
        plate_status='CONFIRMED',
    )
    try:
        assert worker._persist_batch([('PASSAGE', dto, None)])
        with setup[0].transaction() as s:
            results = list(s.scalars(select(VehicleWatchlistResult)))
            assert len(results) >= 1
            plate = s.get(PlateEvent, results[0].plate_event_id)
            assert plate is not None
            assert plate.plate_text == '30A10010'
    finally:
        worker.stop()


def test_notification_insert_failure_does_not_rollback_face_or_plate(setup, tmp_path):
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import FaceEventDTO, VehiclePassageDTO
    from src.db.models import PlateEvent, VehicleWatchlist, VehicleWatchlistResult

    with setup[0].transaction() as s:
        s.add(VehicleWatchlist(id=uuid4(), plate_number='29A99999', display_name='Xe test 2', status='active'))

    worker = DatabaseWorker(str(setup[0].engine.url), snapshot_dir=tmp_path / 'evidence')
    # Mock notifications to fail during enqueue (simulating unexpected runtime / insert failure)
    worker.notifications.enqueue_face = Mock(side_effect=RuntimeError("Simulated face notification failure"))
    worker.notifications.enqueue_vehicle = Mock(side_effect=RuntimeError("Simulated vehicle notification failure"))

    now = utc_now()
    face_dto = FaceEventDTO(id=uuid4(), track_id=2, camera_id='gate', target_id=setup[1], created_at=now)
    passage_dto = VehiclePassageDTO(
        id=uuid4(),
        session_key='session-fail-2',
        camera_id='gate',
        track_id=89,
        first_seen_at=now,
        last_seen_at=now,
        plate_text='29A99999',
        vehicle_type='car',
        is_final=True,
        created_at=now,
        updated_at=now,
        finalized_at=now,
        plate_status='CONFIRMED',
    )
    try:
        # Persist face event despite notification failure
        assert worker._persist_batch([('FACE_EVENT', face_dto, None)])
        with setup[0].transaction() as s:
            assert s.get(FaceEvent, face_dto.id) is not None

        # Persist vehicle passage despite notification failure
        assert worker._persist_batch([('PASSAGE', passage_dto, None)])
        with setup[0].transaction() as s:
            results = list(s.scalars(select(VehicleWatchlistResult).where(VehicleWatchlistResult.normalized_plate == '29A99999')))
            assert len(results) == 1
            assert s.get(PlateEvent, results[0].plate_event_id) is not None
    finally:
        worker.stop()


def test_fallback_notification_failure_logs_warning_and_preserves_events(setup, tmp_path, caplog):
    from unittest.mock import patch
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import FaceEventDTO, VehiclePassageDTO
    from src.db.models import PlateEvent, VehicleWatchlist, VehicleWatchlistResult
    import logging

    with setup[0].transaction() as s:
        s.add(VehicleWatchlist(id=uuid4(), plate_number='51G12345', display_name='Xe test 3', status='active'))

    worker = DatabaseWorker(str(setup[0].engine.url), snapshot_dir=tmp_path / 'evidence')
    # 1. Enqueue fails
    worker.notifications.enqueue_face = Mock(side_effect=RuntimeError("Primary face enqueue failed"))
    worker.notifications.enqueue_vehicle = Mock(side_effect=RuntimeError("Primary vehicle enqueue failed"))

    now = utc_now()
    face_dto = FaceEventDTO(id=uuid4(), track_id=12, camera_id='cam_gate_face', target_id=setup[1], created_at=now)
    passage_dto = VehiclePassageDTO(
        id=uuid4(),
        session_key='session-fail-3',
        camera_id='cam_gate_plate',
        track_id=90,
        first_seen_at=now,
        last_seen_at=now,
        plate_text='51G12345',
        vehicle_type='car',
        is_final=True,
        created_at=now,
        updated_at=now,
        finalized_at=now,
        plate_status='CONFIRMED',
    )

    caplog.set_level(logging.WARNING, logger="datt.events.db_worker")

    # 2. Fallback Notification instantiation also fails (simulating table / constraint / model failure)
    with patch("src.events.db_worker.Notification", side_effect=RuntimeError("Simulated fallback model/schema crash")):
        try:
            # Face event must persist and log warning
            assert worker._persist_batch([('FACE_EVENT', face_dto, None)])
            with setup[0].transaction() as s:
                assert s.get(FaceEvent, face_dto.id) is not None

            # Plate event must persist and log warning
            assert worker._persist_batch([('PASSAGE', passage_dto, None)])
            with setup[0].transaction() as s:
                results = list(s.scalars(select(VehicleWatchlistResult).where(VehicleWatchlistResult.normalized_plate == '51G12345')))
                assert len(results) == 1
                assert s.get(PlateEvent, results[0].plate_event_id) is not None
        finally:
            worker.stop()

    # Verify structured logs were generated without exception propagation
    assert "face fallback in-app alert failed" in caplog.text
    assert "vehicle fallback in-app alert failed" in caplog.text
    assert "FACE_WATCHLIST_MATCH" in caplog.text
    assert "VEHICLE_WATCHLIST_MATCH" in caplog.text
    assert "Simulated fallback model/schema crash" in caplog.text
    assert str(face_dto.id) in caplog.text
    assert str(face_dto.target_id) in caplog.text
    # Data minimization: target_name and plate text must NOT be exposed in fallback warning logs
    assert "target_name=" not in caplog.text
    assert "plate=" not in caplog.text


def test_alert_fallback_projection_log_rate_limiting(caplog):
    """Case A: Fallback unnotified events projection query errors are rate-limited to prevent log spam."""
    from src.notifications.alerts import query as query_alerts, _reset_fallback_log_throttle
    from unittest.mock import MagicMock, patch

    _reset_fallback_log_throttle()
    mock_session = MagicMock()
    mock_session.scalar.return_value = 0
    res_mock = MagicMock()
    res_mock.all.return_value = []

    is_main_query = True

    def fake_execute(*args, **kwargs):
        nonlocal is_main_query
        if is_main_query:
            is_main_query = False
            return res_mock
        is_main_query = True
        raise RuntimeError("DB connection timeout during fallback projection")

    mock_session.execute.side_effect = fake_execute

    caplog.clear()
    caplog.set_level(logging.WARNING, logger="datt.notifications.alerts")

    # 1. First call -> Logs WARNING with full traceback
    res1 = query_alerts(mock_session, {'page': 1, 'page_size': 20})
    assert res1['status'] == 'ok'
    assert len(caplog.records) == 1
    assert "Fallback unnotified events projection query failed" in caplog.text
    assert caplog.records[0].exc_info is not None

    # 2. Second call immediately within cooldown -> Throttled (no additional warning log)
    res2 = query_alerts(mock_session, {'page': 1, 'page_size': 20})
    assert res2['status'] == 'ok'
    assert len(caplog.records) == 1

    # 3. Third call after cooldown expires -> Logs WARNING with repeated count
    with patch("src.notifications.alerts.time.monotonic", return_value=time.monotonic() + 100.0):
        res3 = query_alerts(mock_session, {'page': 1, 'page_size': 20})
        assert res3['status'] == 'ok'
        assert len(caplog.records) == 2
        assert "repeated 1 times during cooldown" in caplog.records[1].message




def test_gmail_defaults_with_three_secrets(monkeypatch):
    for name in ('HOST','PORT','TLS','FROM'):
        monkeypatch.delenv('DATT_EMAIL_'+name,raising=False)
    monkeypatch.setenv('DATT_EMAIL_USERNAME','sender@example.invalid')
    monkeypatch.setenv('DATT_EMAIL_PASSWORD','test-password')
    monkeypatch.setenv('DATT_EMAIL_TO','recipient@example.invalid')
    config=EmailConfig.from_env()
    assert config.configured
    assert (config.host,config.port,config.tls,config.sender)==('smtp.gmail.com',587,'starttls','sender@example.invalid')
    assert 'recipient@example.invalid' not in repr(config)
    monkeypatch.setenv('DATT_EMAIL_HOST','smtp.example.invalid')
    monkeypatch.setenv('DATT_EMAIL_FROM','override@example.invalid')
    assert EmailConfig.from_env().sender=='override@example.invalid'
    assert EmailConfig.from_env().host=='smtp.example.invalid'
