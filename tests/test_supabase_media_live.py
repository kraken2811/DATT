"""Opt-in real PostgreSQL/Storage test; retains uniquely named synthetic fixtures.

DATT_RUN_SUPABASE_MEDIA_TEST=1 python -m pytest tests/test_supabase_media_live.py -q
No production records or objects are deleted. Recognition alone is mocked.
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid4, UUID
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skipif(os.getenv('DATT_RUN_SUPABASE_MEDIA_TEST') != '1',
                                reason='Explicit live Supabase configuration required')


def test_upload_db_storage_fresh_process(tmp_path, monkeypatch):
    import cv2
    import numpy as np
    from fastapi.testclient import TestClient
    from src.db.database import Database
    from src.db.models import VehicleEvent, PlateEvent, FaceEvent
    from src.events.db_worker import DatabaseWorker
    from src.events.event_dto import VehiclePassageDTO, FaceEventDTO
    from src.storage import get_storage, SupabaseStorageBackend
    from src.ui import web_server
    assert os.environ['DATT_STORAGE_BACKEND'] == 'supabase'
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '1')
    monkeypatch.setenv('DATT_STORAGE_CACHE', str(tmp_path / 'old-cache'))
    assert isinstance(get_storage(), SupabaseStorageBackend)
    db = Database()
    assert db.engine.dialect.name == 'postgresql'
    tag = uuid4().hex
    image = np.full((64, 64, 3), 120, dtype=np.uint8)
    clip = tmp_path / 'probe.mp4'
    writer = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*'mp4v'), 10, (64, 64))
    assert writer.isOpened()
    for _ in range(10): writer.write(image)
    writer.release()
    client = TestClient(web_server.app)
    uploaded = client.post('/api/upload_video', files={'file': ('persistence_' + tag + '.mp4', clip.read_bytes(), 'video/mp4')})
    assert uploaded.status_code == 200
    video = uploaded.json()
    _, encoded = cv2.imencode('.jpg', image)
    embedding = np.ones(512, dtype=np.float32) / np.sqrt(512)
    with patch('src.recognition.target_matcher.face_embedder.extract_face_embedding', return_value=embedding):
        registered = client.post('/api/register_target', data={'name': 'storage-test-' + tag},
                                 files={'face_image': ('synthetic.jpg', encoded.tobytes(), 'image/jpeg')})
    assert registered.status_code == 200
    target = registered.json()['target']
    now = datetime.now(timezone.utc)
    passage = VehiclePassageDTO(id=uuid4(), session_key='storage-test-' + tag,
        camera_id='storage-test', track_id=1, first_seen_at=now, last_seen_at=now,
        vehicle_type='car', plate_text='TEST', plate_status='CONFIRMED',
        video_source_id=UUID(video['video_source_id']), is_final=True, finalized_at=now)
    face = FaceEventDTO(id=uuid4(), track_id=1, camera_id='storage-test',
                        video_source_id=UUID(video['video_source_id']))
    worker = DatabaseWorker(os.environ['DATT_DATABASE_URL'])
    try:
        assert worker._persist_batch([('PASSAGE', passage, (image, image)), ('FACE_EVENT', face, image)])
    finally:
        worker.stop()
    with db.transaction() as session:
        keys = [session.get(VehicleEvent, passage.id).vehicle_image_path,
                session.query(PlateEvent).filter_by(video_source_id=UUID(video['video_source_id'])).one().plate_crop_path,
                session.get(FaceEvent, face.id).face_crop_path]
    db.dispose()
    for key in keys:
        assert get_storage().exists(key)
    # New process, empty cache, same remote DB. No dependence on staging paths.
    env = os.environ.copy()
    env['DATT_STORAGE_CACHE'] = str(tmp_path / 'fresh-cache')
    code = '''
import sys, cv2
from uuid import UUID
from src.db.database import Database
from src.db.models import VideoSource, Target, VehicleEvent, PlateEvent, FaceEvent
from src.storage import get_storage
from src.ui.web_server import app
from fastapi.testclient import TestClient
d = Database()
with d.transaction() as s:
    video = s.get(VideoSource, UUID(sys.argv[1]))
    target = s.get(Target, UUID(sys.argv[2]))
    vehicle = s.get(VehicleEvent, UUID(sys.argv[3]))
    plate = s.query(PlateEvent).filter_by(video_source_id=video.id).one()
    face = s.get(FaceEvent, UUID(sys.argv[4]))
    keys = [target.image_path, vehicle.vehicle_image_path, plate.plate_crop_path, face.face_crop_path]
    cap = cv2.VideoCapture(str(get_storage().materialize(video.storage_path)))
    assert cap.read()[0]
    cap.release()
    for key in keys:
        assert cv2.imread(str(get_storage().materialize(key))) is not None
        assert not key.startswith(('http:', 'https:', '/content'))
    client = TestClient(app)
    assert client.get('/api/targets/' + str(target.id) + '/image').status_code == 200
    for key in keys[1:]:
        assert client.get('/api/event_snapshot', params={'path': key}).status_code == 200
d.dispose()
'''
    result = subprocess.run([sys.executable, '-c', code, video['video_source_id'], target['id'],
                             str(passage.id), str(face.id)], env=env, capture_output=True)
    assert result.returncode == 0, 'Fresh-process media verification failed (output withheld for credential safety)'
