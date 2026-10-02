from unittest.mock import patch
from uuid import UUID
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.db.database import Database
from src.db.models import Base, BusinessEvent
from src.runtime.shared_state import SharedRuntimeState
from src.storage import LocalStorageBackend, StorageUploadTooLarge
from src.ui import camera_capture, web_server


@pytest.fixture
def capture_setup(tmp_path, monkeypatch):
    monkeypatch.delenv('DATT_REQUIRE_PERSISTENCE', raising=False)
    monkeypatch.setenv('DATT_DATABASE_URL', 'sqlite:///' + (tmp_path / 'capture.db').as_posix())
    db = Database()
    Base.metadata.create_all(db.engine)
    state = SharedRuntimeState()
    monkeypatch.setattr(camera_capture, 'shared_state', state)
    storage = LocalStorageBackend(tmp_path)
    monkeypatch.setattr(camera_capture, 'get_storage', lambda: storage)
    yield TestClient(web_server.app), state, storage, db
    db.dispose()


def test_capture_persists_raw_image_and_metadata(capture_setup):
    client, state, storage, db = capture_setup
    raw = np.full((24, 32, 3), 100, dtype=np.uint8)
    state.update(frame_id=7, latest_frame=raw, annotated_frame=np.zeros_like(raw),
                 people_count=2, camera_id='test-camera')
    response = client.post('/api/camera_capture')
    assert response.status_code == 200
    data = response.json()
    image = cv2.imread(str(storage.materialize(data['snapshot_path'])))
    assert image.mean() == pytest.approx(100, abs=1)
    with db.transaction() as session:
        event = session.get(BusinessEvent, UUID(data['id']))
        assert event is None  # Manual photographs are not policy events.
        assert data['image_url'] == '/api/event_snapshot?path=' + data['snapshot_path']


def test_capture_rejects_missing_or_stale_frame(capture_setup):
    client, state, storage, db = capture_setup
    assert client.post('/api/camera_capture').status_code == 409
    state.update(frame_id=1, latest_frame=np.zeros((4, 4, 3), np.uint8))
    state._timestamp = time.time() - 10
    assert client.post('/api/camera_capture').status_code == 409
    assert not list(storage.root.rglob('*.jpg'))


def test_storage_failure_does_not_report_success(capture_setup):
    client, state, storage, db = capture_setup
    state.update(frame_id=1, latest_frame=np.zeros((4, 4, 3), np.uint8))
    with patch.object(storage, 'save_bytes', side_effect=OSError('private-secret')):
        response = client.post('/api/camera_capture')
    assert response.status_code == 503
    assert 'private-secret' not in response.text
    with db.transaction() as session:
        assert session.query(BusinessEvent).count() == 0


def test_upload_size_rejection_is_413(tmp_path, monkeypatch):
    monkeypatch.setattr(web_server, 'UPLOAD_VIDEO_DIR', tmp_path)
    with patch.object(web_server, 'get_storage') as storage:
        storage.return_value.save.side_effect = StorageUploadTooLarge('limit')
        response = TestClient(web_server.app).post('/api/upload_video',
            files={'file': ('too-large.mp4', b'test', 'video/mp4')})
    assert response.status_code == 413
    assert response.json()['code'] == 'VIDEO_TOO_LARGE_FOR_STORAGE'
    assert not list(tmp_path.glob('*.mp4'))


def test_occupancy_worker_persists_snapshot_and_retries_failure(capture_setup):
    from datetime import datetime, timezone
    from uuid import uuid4
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import BusinessEventDTO
    client, state, storage, db = capture_setup
    # Exercise the real batch transaction without background threads/notifications.
    worker = DatabaseWorker.__new__(DatabaseWorker)
    worker.db = db
    worker.snapshot_dir = storage.root
    worker.queue_coalesced = worker.db_failures = 0
    worker.write_latencies = []
    dto = BusinessEventDTO(id=uuid4(), passage_id=None, camera_id='camera-test',
        event_type='CROWD_THRESHOLD', event_time=datetime.now(timezone.utc),
        idempotency_key=str(uuid4()), metadata={'people_count': 41, 'duration_seconds': 180})
    frame = np.full((20, 20, 3), 80, np.uint8)
    def save(path, image, params):
        ok, encoded = cv2.imencode('.jpg', image, params)
        storage.save_bytes('data/events/' + __import__('pathlib').Path(path).name, encoded.tobytes())
        return ok
    with patch('src.events.db_worker.save_image', side_effect=OSError('unavailable')):
        assert worker._persist_batch([('BUSINESS_EVENT', dto, frame)]) is False
    with db.transaction() as session:
        assert session.get(BusinessEvent, dto.id) is None
    with patch('src.events.db_worker.save_image', side_effect=save):
        assert worker._persist_batch([('BUSINESS_EVENT', dto, frame)]) is True
        assert worker._persist_batch([('BUSINESS_EVENT', dto, frame)]) is True
    with db.transaction() as session:
        assert session.query(BusinessEvent).count() == 1
        event = session.get(BusinessEvent, dto.id)
        assert storage.exists(event.event_metadata['snapshot_path'])
