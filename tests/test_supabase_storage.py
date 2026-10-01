"""Supabase REST contract tests. Fake transport is not live cloud evidence."""
import io
from unittest.mock import patch

import pytest
import requests

from src.storage import SupabaseStorageBackend


class Response:
    def __init__(self, status=200, content=b""):
        self.status_code, self.content = status, content
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): self.close()
    def iter_content(self, size): yield self.content


@pytest.fixture
def remote(monkeypatch):
    objects = {}
    def request(method, url, **kw):
        assert kw['allow_redirects'] is False
        assert kw['headers']['Authorization'] == 'Bearer test-secret'
        if method == 'POST':
            objects[url] = kw['data'].read()
            return Response()
        if url not in objects: return Response(404)
        if method == 'DELETE':
            del objects[url]
            return Response()
        return Response(content=objects[url])
    monkeypatch.setattr(requests, 'request', request)
    return objects


def backend(cache):
    return SupabaseStorageBackend('https://test.supabase.co', 'test-secret', 'media', cache)


@pytest.mark.parametrize('key', ['data/uploads/videos/a.mp4', 'data/uploads/targets/a.jpg',
                               'data/events/vehicle.jpg', 'data/events/plate.jpg', 'data/events/face.jpg'])
def test_storage_reload_without_original_cache(tmp_path, remote, key):
    first = backend(tmp_path / 'old')
    first.save(key, io.BytesIO(b'persistent-media'))
    assert first.materialize(key).read_bytes() == b'persistent-media'
    fresh = backend(tmp_path / 'new')
    assert fresh.materialize(key).read_bytes() == b'persistent-media'
    fresh.delete(key)
    assert not first.exists(key)
    with pytest.raises(FileNotFoundError): first.materialize(key)


def test_fail_closed_and_redact(tmp_path):
    for response in (Response(401), Response(413), Response(500)):
        with patch('requests.request', return_value=response):
            with pytest.raises(OSError, match='Supabase Storage HTTP'):
                backend(tmp_path).save_bytes('data/events/a.jpg', b'x')
    with patch('requests.request', side_effect=requests.ConnectionError('test-secret')):
        with pytest.raises(OSError) as error:
            backend(tmp_path).exists('data/events/a.jpg')
        assert 'test-secret' not in str(error.value)


def test_modern_secret_uses_apikey_without_jwt_bearer(tmp_path):
    storage = SupabaseStorageBackend('https://test.supabase.co', 'sb_secret_test', 'media', tmp_path)
    with patch('requests.request', return_value=Response()) as request:
        assert storage.exists('data/events/a.jpg')
    headers = request.call_args.kwargs['headers']
    assert headers == {'apikey': 'sb_secret_test', 'Range': 'bytes=0-0'}


def test_supabase_missing_object_400_is_not_auth_failure(tmp_path):
    response = Response(400)
    response.json = lambda: {'code': 'NoSuchKey', 'statusCode': '404'}
    with patch('requests.request', return_value=response) as request:
        assert not backend(tmp_path).exists('data/events/missing.jpg')
        assert request.call_args.args[0] == 'GET'


def test_video_upload_db_remote_reload(tmp_path, monkeypatch, remote):
    """Real upload handler and DB; transport simulated, SQLite explicitly local."""
    from fastapi.testclient import TestClient
    from src.db.database import Database
    from src.db.models import Base, VideoSource
    from src.ui import web_server
    monkeypatch.delenv('DATT_REQUIRE_PERSISTENCE', raising=False)
    monkeypatch.setenv('DATT_DATABASE_URL', 'sqlite:///' + (tmp_path / 'test.db').as_posix())
    monkeypatch.setattr(web_server, 'UPLOAD_VIDEO_DIR', tmp_path / 'staging')
    web_server.UPLOAD_VIDEO_DIR.mkdir()
    first = backend(tmp_path / 'old')
    monkeypatch.setattr(web_server, 'get_storage', lambda: first)
    db = Database()
    Base.metadata.create_all(db.engine)
    response = TestClient(web_server.app).post('/api/upload_video',
        files={'file': ('probe.mp4', b'upload-contract-test', 'video/mp4')})
    assert response.status_code == 200
    with db.transaction() as session:
        key = session.query(VideoSource).one().storage_path
    db.dispose()
    fresh_db = Database()
    with fresh_db.transaction() as session:
        assert session.query(VideoSource).one().storage_path == key
    fresh_db.dispose()
    assert backend(tmp_path / 'new').materialize(key).read_bytes() == b'upload-contract-test'


def test_event_id_resolves_after_memory_loss(tmp_path, monkeypatch, remote):
    from fastapi.testclient import TestClient
    from src.db.database import Database
    from src.db.models import Base, FaceEvent
    from src.ui import web_server
    monkeypatch.delenv('DATT_REQUIRE_PERSISTENCE', raising=False)
    monkeypatch.setenv('DATT_DATABASE_URL', 'sqlite:///' + (tmp_path / 'event.db').as_posix())
    db = Database()
    Base.metadata.create_all(db.engine)
    key = 'data/events/restart-face.jpg'
    backend(tmp_path / 'old').save_bytes(key, b'image-evidence')
    with db.transaction() as session:
        event = FaceEvent(face_crop_path=key, decision='TEST')
        session.add(event)
        session.flush()
        event_id = str(event.id)
    db.dispose()
    web_server.event_snapshot_cache.clear()
    monkeypatch.setattr(web_server, 'get_storage', lambda: backend(tmp_path / 'new'))
    response = TestClient(web_server.app).get('/api/event_snapshot', params={'id': event_id})
    assert response.status_code == 200
    assert response.content == b'image-evidence'


def test_migration_retains_originals_and_rejects_conflict(tmp_path, monkeypatch, remote):
    from scripts import migrate_media_to_storage as migration
    key = 'data/events/existing.jpg'
    original = tmp_path / key
    original.parent.mkdir(parents=True)
    original.write_bytes(b'original')
    storage = backend(tmp_path / 'cache')
    monkeypatch.setattr(migration, 'get_storage', lambda: storage)
    migration.migrate(tmp_path)
    migration.migrate(tmp_path)  # idempotent
    assert original.read_bytes() == b'original'
    storage.save_bytes(key, b'conflicting-object')
    with pytest.raises(RuntimeError, match='conflict'):
        migration.migrate(tmp_path)
    assert original.read_bytes() == b'original'
    with storage.open(key) as source:
        assert source.read() == b'conflicting-object'
