"""Bounded by CLI worker processes. Never return provider exception messages."""
import importlib.util
import io
import os
from uuid import UUID, uuid4

from .config import ROOT


def database_check():
    result = dict(database_configured=bool(os.getenv('DATT_DATABASE_URL')),
                  database_connected=False, database_type='unconfigured',
                  postgresql_version='unknown', pgvector_version='missing',
                  alembic_revision='unknown', pgvector='FAIL', alembic='FAIL',
                  tables_verified=False)
    if not result['database_configured']:
        return result
    from sqlalchemy import inspect, text
    from src.db.database import Database
    from src.db.models import Base
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    db = Database()
    try:
        result['database_type'] = db.engine.dialect.name
        if db.engine.dialect.name == 'sqlite':
            result['pgvector'] = 'NOT_APPLICABLE'
            result['pgvector_version'] = 'not_applicable'
        with db.engine.connect() as conn:
            result['database_connected'] = conn.scalar(text('SELECT 1')) == 1
            if db.engine.dialect.name == 'postgresql':
                result['postgresql_version'] = conn.scalar(text('SHOW server_version'))
                result['pgvector_version'] = conn.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'")) or 'missing'
                result['pgvector'] = 'PASS' if result['pgvector_version'] != 'missing' else 'FAIL'
            tables = set(inspect(conn).get_table_names())
            result['tables_verified'] = set(Base.metadata.tables) <= tables
            if 'alembic_version' in tables:
                revisions = set(conn.scalars(text('SELECT version_num FROM alembic_version')))
                heads = set(ScriptDirectory.from_config(Config(str(ROOT / 'src/db/alembic.ini'))).get_heads())
                result['alembic_revision'] = ','.join(sorted(revisions))
                result['alembic'] = 'PASS' if revisions == heads else 'FAIL'
    finally:
        db.dispose()
    return result


def migrate():
    if not os.getenv('DATT_DATABASE_URL'):
        return {'migration': 'FAIL', 'database_configured': False}
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT / 'src/db/alembic.ini')), 'head')
    return database_check()


def storage_check():
    backend = os.getenv('DATT_STORAGE_BACKEND', 'local')
    configured = (backend == 'local' or
                  backend == 'external' and bool(os.getenv('DATT_STORAGE_URL')) or
                  backend == 'supabase' and all((os.getenv('SUPABASE_URL'),
                      os.getenv('SUPABASE_SERVICE_ROLE_KEY'),
                      os.getenv('DATT_STORAGE_BUCKET') or os.getenv('SUPABASE_STORAGE_BUCKET'))))
    result = dict(storage_backend=backend, storage_configured=bool(configured),
                  storage_connected=False, storage_upload='FAIL', storage_read='FAIL',
                  storage_cleanup='NOT_NEEDED')
    if not configured:
        return result
    from src.storage import get_storage
    storage = get_storage()
    key = 'data/events/cli_probe_' + uuid4().hex + '.bin'
    payload = os.urandom(64)
    try:
        storage.save(key, io.BytesIO(payload))
        result['storage_upload'] = 'PASS'
        assert storage.exists(key)
        with storage.open(key) as stream:
            assert stream.read() == payload
        result['storage_read'] = 'PASS'
        result['storage_connected'] = True
    finally:
        # Only the random object owned by this invocation may be deleted.
        storage.delete(key)
        result['storage_cleanup'] = 'PASS' if not storage.exists(key) else 'FAIL'
    return result


def gpu_check():
    result = dict(gpu_available=False, cuda_available=False, gpu_name='none')
    if importlib.util.find_spec('torch'):
        import torch
        result['cuda_available'] = bool(torch.cuda.is_available())
        result['gpu_available'] = result['cuda_available']
        if result['gpu_available']:
            result['gpu_name'] = torch.cuda.get_device_name(0)
    result['gpu_status'] = 'PASS' if result['gpu_available'] else 'SKIPPED_GPU_NOT_AVAILABLE'
    return result


def cv_check():
    result = gpu_check()
    if not result['gpu_available']:
        return {**result, 'cv_status': 'SKIPPED_GPU_NOT_AVAILABLE'}
    import onnxruntime as ort
    result['onnx_cuda'] = 'CUDAExecutionProvider' in ort.get_available_providers()
    result['models_ready'] = all((ROOT / 'models' / p).is_file() and
                                (ROOT / 'models' / p).stat().st_size > 0
                                for p in ('yolo11s.pt', 'yolov8n-license-plate.pt'))
    result['cv_status'] = 'PASS' if result['onnx_cuda'] and result['models_ready'] else 'FAIL'
    return result


def dependencies_check():
    modules = ('sqlalchemy', 'alembic', 'psycopg', 'pgvector', 'requests',
               'psutil', 'dotenv', 'fastapi', 'uvicorn', 'multipart', 'httpx',
               'cv2', 'numpy', 'imageio_ffmpeg', 'yaml')
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    return {'dependencies_ready': not missing, 'missing_dependencies': ','.join(missing),
            'config_files_ready': (ROOT / 'configs/cameras.yaml').is_file()}


def fixture(action, identity):
    """Independent processes re-open metadata and bytes; no in-memory/cache shortcut."""
    from src.db.database import Database
    from src.db.models import VideoSource
    from src.storage import get_storage
    ident = UUID(identity)
    key = 'data/uploads/videos/cli_e2e_' + ident.hex + '.bin'
    payload = ('DATT CLI persistence ' + str(ident)).encode()
    db, storage = Database(), get_storage()
    try:
        if action == 'create':
            storage.save(key, io.BytesIO(payload))
            with db.transaction() as session:
                session.add(VideoSource(id=ident, original_filename='cli_e2e_' + ident.hex + '.bin',
                                        storage_path=key, status='cli_test',
                                        video_metadata={'datt_cli_fixture': str(ident)}))
        elif action == 'verify':
            with db.transaction() as session:
                record = session.get(VideoSource, ident)
                assert record and record.storage_path == key
                assert record.video_metadata == {'datt_cli_fixture': str(ident)}
            with storage.open(key) as source:
                assert source.read() == payload
        elif action == 'cleanup':
            with db.transaction() as session:
                record = session.get(VideoSource, ident)
                if record:
                    assert record.storage_path == key and record.video_metadata == {'datt_cli_fixture': str(ident)}
                    session.delete(record)
            storage.delete(key)
        return {'fixture_' + action: 'PASS'}
    finally:
        db.dispose()
