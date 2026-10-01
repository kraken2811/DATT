from datetime import timedelta
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
