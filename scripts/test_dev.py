"""Run the dev preparation regression suite in disposable SQLite/local Storage."""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUITE = (
    'event_policy', 'camera_capture', 'snapshot_proxy', 'vehicle_watchlists',
    'notifications', 'colab_install', 'colab_runtime_cell', 'colab_startup',
    'database_pool_lifecycle', 'select_source_proxy', 'supabase_storage',
    'cli', 'web_server', 'youtube_vod_workflow',
)


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    for key in list(os.environ):
        if key.startswith(('DATT_', 'SUPABASE_')):
            os.environ.pop(key)
    with tempfile.TemporaryDirectory(prefix='datt-dev-tests-') as temp:
        os.environ.update(
            DATT_DATABASE_URL='sqlite:///' + Path(temp, 'tests.db').as_posix(),
            DATT_REQUIRE_PERSISTENCE='0', DATT_STORAGE_BACKEND='local',
            DATT_STORAGE_ROOT=temp, DATT_RUNTIME_DIR=str(Path(temp, 'runtime')),
            DATT_EVENT_AUDIT_ONLY='1',
        )
        # Camera API/source-selection tests need the existing schema, not an
        # empty database. Never create tables in the project's configured DB.
        from src.db.database import Database
        from src.db.models import Base
        db = Database()
        Base.metadata.create_all(db.engine)
        db.dispose()
        import pytest
        try:
            return pytest.main([
                *(sys.argv[1:] or [f'tests/test_{name}.py' for name in SUITE]),
                '-q', '--tb=short',
            ])
        finally:
            module = sys.modules.get('src.events.event_manager')
            if module is not None:
                module.event_manager.stop()


if __name__ == '__main__':
    raise SystemExit(main())
