"""Real disposable DB/API, mocked SMTP transport; no external delivery."""
from contextlib import contextmanager
from datetime import timedelta
from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4
import smtplib
import threading
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, IntegrityError
from alembic import command
from alembic.config import Config
from src.db.database import Database
from src.db.models import Notification, FaceEvent, Camera, VehicleEvent, PlateEvent, VehicleWatchlist, VehicleWatchlistResult, utc_now
from src.notifications.alerts import router
from src.notifications.email import SMTPEmailAdapter
from src.notifications.service import NotificationService
from tests.test_notifications import setup, enqueue, history


@pytest.fixture
def client(setup):
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def test_face_event_pending_smtp_sent_and_alert_api(setup, client, monkeypatch):
    db, target, service, _ = setup
    with db.transaction() as s:
        s.add(Camera(registry_key='gate', name='Main gate', source_type='rtsp', source='rtsp://private'))
    event_id = enqueue(setup)
    pending = client.get('/api/alerts').json()['alerts'][0]
    assert pending['status'] == 'PENDING' and pending['sent_at'] is None
    assert pending['recipient_email'] == service.config.recipients[0]
    assert pending['event_id'] == str(event_id) and pending['target_id'] == str(target)
    assert pending['camera_name'] == 'Main gate' and pending['channel'] == 'EMAIL'
    assert pending['event_type'] == 'FACE_WATCHLIST_MATCH'
    smtp = Mock()
    def accept(message):
        # State cannot become SENT before provider acceptance.
        assert history(setup)[0].status == 'pending'
        assert history(setup)[0].sent_at is None
        assert message['To'] == service.config.recipients[0]
        return {}
    smtp.send_message.side_effect = accept
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=smtp)
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr('src.notifications.email.smtplib.SMTP', factory)
    storage = Mock(); storage.open.side_effect = FileNotFoundError()
    service.adapters['email'] = SMTPEmailAdapter(service.config, lambda: storage)
    assert service.deliver_one()
    response = client.get('/api/alerts/' + pending['id'])
    sent = response.json()['alert']
    assert sent['status'] == 'SENT' and sent['sent_at'] and sent['error_message'] is None
    assert sent['event_center_id'] == 'face:' + str(event_id)
    assert 'no-store' in response.headers['cache-control']
    assert not service.deliver_one()
    smtp.send_message.assert_called_once()


@pytest.mark.parametrize('failure,code', [
    (TimeoutError('private-password'), 'smtp_timeout'),
    (smtplib.SMTPAuthenticationError(535, b'private-password'), 'smtp_authentication'),
    (ConnectionError('private-host'), 'smtp_connection'),
    (smtplib.SMTPRecipientsRefused({'private-address': (550, b'private')}), 'invalid_recipient'),
    (RuntimeError('private-password'), 'delivery_failed'),
])
def test_failure_immediately_visible_and_sanitized(setup, client, failure, code):
    enqueue(setup)
    setup[3].send.side_effect = failure
    assert setup[2].deliver_one()
    result = client.get('/api/alerts?status=FAILED').json()
    assert result['total'] == 1
    row = result['alerts'][0]
    assert row['status'] == 'FAILED' and row['sent_at'] is None and row['error_code'] == code
    assert 'private' not in str(result)
    assert row['retry_count'] == 0  # First failure; bounded retries remain eligible.
    assert not setup[2].deliver_one(utc_now() - timedelta(seconds=1))
    enqueue(setup)
    assert history(setup)[1].status == 'suppressed'  # Retry keeps cooldown reservation.


def test_filters_pagination_vehicle_relationship_restart(setup, client):
    db, _, service, _ = setup
    face_id = enqueue(setup)
    assert service.deliver_one()
    with db.transaction() as s:
        cam = Camera(name='Vehicle gate', source_type='file', source='private')
        target = VehicleWatchlist(plate_number='29A12345', display_name='Test vehicle')
        vehicle = VehicleEvent(vehicle_class='car', track_id=1)
        s.add_all([cam, target, vehicle]); s.flush()
        plate = PlateEvent(vehicle_event_id=vehicle.id, plate_text='29A12345', normalized_plate='29A12345', created_at=utc_now())
        s.add(plate); s.flush()
        match = VehicleWatchlistResult(plate_event_id=plate.id, watchlist_id=target.id, normalized_plate=plate.normalized_plate,
                                      display_name=target.display_name, camera_id=str(cam.id), decision='MATCH')
        s.add(match); s.flush()
        service.enqueue_vehicle(s, plate, match)
        service.enqueue_vehicle(s, plate, match)
    assert len(history(setup)) == 2
    result = client.get('/api/alerts?page_size=1').json()
    row = result['alerts'][0]
    assert result['total'] == 2 and row['event_id'] == str(plate.id)
    assert row['camera_name'] == cam.name and row['target_name'] == target.display_name
    assert row['target_id'] == str(target.id) and row['plate_number'] == plate.normalized_plate
    assert client.get('/api/alerts?page_size=1&page=2').json()['alerts'][0]['event_id'] == str(face_id)
    for params in ('status=SENT', 'status=PENDING', 'event_type=VEHICLE_WATCHLIST_MATCH', 'event_type=FACE_WATCHLIST_MATCH',
                   'camera_id=gate', 'camera_id=' + cam.id.hex):
        assert client.get('/api/alerts?' + params).json()['total'] == 1
    assert client.get('/api/alerts?camera_id=missing').json()['alerts'] == []
    # A new engine, worker and API application reload durable state from disk.
    db.dispose()
    fresh = Database(str(db.engine.url))
    try:
        worker = NotificationService(fresh, service.config, {'email': Mock()})
        assert worker.deliver_one()
        app = FastAPI(); app.include_router(router)
        with TestClient(app) as restarted:
            assert restarted.get('/api/alerts?status=SENT').json()['total'] == 2
    finally:
        fresh.dispose()


@pytest.mark.parametrize('query', ['status=resolved', 'event_type=unknown', 'page=0', 'page=no', 'page_size=201', 'page_size=0'])
def test_invalid_filters(client, query):
    assert client.get('/api/alerts?' + query).status_code == 400


def test_detail_missing_and_legacy_error_redaction(setup, client):
    assert client.get('/api/alerts/not-a-uuid').status_code == 404
    assert client.get('/api/alerts/' + str(uuid4())).status_code == 404
    enqueue(setup)
    with setup[0].transaction() as s:
        row = s.scalar(select(Notification)); row.status = 'failed'; row.error = 'password=old-sensitive-error'
    data = client.get('/api/alerts').json()
    assert 'old-sensitive' not in str(data)
    assert data['alerts'][0]['error_code'] == 'delivery_failed'


def test_db_unavailable_returns_safe_503(client, monkeypatch):
    def broken():
        raise OperationalError('secret-query', {}, Exception('secret-db-password'))
    monkeypatch.setattr('src.notifications.alerts.database', broken)
    response = client.get('/api/alerts')
    assert response.status_code == 503 and 'secret' not in response.text


def test_worker_recovers_from_database_error(setup, caplog, monkeypatch):
    enqueue(setup)
    db, _, service, adapter = setup
    original = db.transaction
    attempts = []
    @contextmanager
    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise OperationalError('sensitive-query', {}, Exception('secret-password'))
        with original() as s:
            yield s
    monkeypatch.setattr(db, 'transaction', flaky)
    done = threading.Event()
    adapter.send.side_effect = lambda item: done.set()
    service.start()
    assert done.wait(4)
    service.stop(3)
    assert history(setup)[0].status == 'sent'
    assert 'worker unavailable' in caplog.text and 'secret-password' not in caplog.text


def test_notification_migration_matches_model(setup):
    # Fixture ran every migration on a disposable DB; no production migration.
    command.check(Config('src/db/alembic.ini'))


def test_invalid_recipient_never_opens_smtp(setup, monkeypatch):
    enqueue(setup)
    item = history(setup)[0]; item.recipient = 'bad\nBcc: other@example.invalid'
    factory = Mock(); monkeypatch.setattr('src.notifications.email.smtplib.SMTP', factory)
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        SMTPEmailAdapter(setup[2].config).send(item)
    factory.assert_not_called()


def test_smtp_refusal_not_success(setup, monkeypatch):
    enqueue(setup)
    smtp = Mock(); smtp.send_message.return_value = {'to@example.invalid': (550, b'refused secret')}
    factory = Mock(); factory.return_value.__enter__ = Mock(return_value=smtp); factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr('src.notifications.email.smtplib.SMTP', factory)
    storage = Mock(); storage.open.side_effect = FileNotFoundError()
    setup[2].adapters['email'] = SMTPEmailAdapter(setup[2].config, lambda: storage)
    assert setup[2].deliver_one()
    row = history(setup)[0]
    assert row.status == 'failed' and row.sent_at is None and row.error == 'invalid_recipient'


def test_unique_constraint_prevents_duplicate_delivery_rows(setup):
    enqueue(setup)
    row = history(setup)[0]
    with pytest.raises(IntegrityError), setup[0].transaction() as s:
        s.add(Notification(event_id=row.event_id, camera_id=row.camera_id, channel=row.channel,
                           recipient=row.recipient, payload={}))
    assert len(history(setup)) == 1


def test_each_configured_recipient_gets_one_delivery(setup, client):
    service = setup[2]
    service.config = replace(service.config, recipients=('one@example.invalid', 'two@example.invalid'))
    event_id = enqueue(setup)
    assert len(history(setup)) == 2
    assert service.deliver_one() and service.deliver_one()
    assert not service.deliver_one()
    rows = client.get('/api/alerts?status=SENT').json()['alerts']
    assert {r['recipient_email'] for r in rows} == set(service.config.recipients)
    assert {r['event_id'] for r in rows} == {str(event_id)}
    assert setup[3].send.call_count == 2
