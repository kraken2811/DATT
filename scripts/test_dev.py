"""Run the dev preparation regression suite in disposable SQLite/local Storage."""
import os
from pathlib import Path
import sys
import tempfile
import secrets

ROOT = Path(__file__).resolve().parents[1]
SUITE = (
    'event_policy', 'camera_capture', 'snapshot_proxy', 'vehicle_watchlists',
    'notifications', 'alerts', 'colab_install', 'colab_runtime_cell', 'colab_startup', 'colab_source',
    'database_pool_lifecycle', 'select_source_proxy', 'supabase_storage',
    'cli', 'web_server', 'youtube_vod_workflow',
    'vehicle_color_flow', 'plate_consensus', 'async_plate_scheduling',
    'plate_reading_recovery', 'frame_packet',
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
            DATT_EVENT_AUDIT_ONLY='1', DATT_AGENT_LLM_PROVIDER='mock',
            AGENT_LLM_PROVIDER='mock', DATT_AGENT_EMBEDDING_PROVIDER='mock',
            DATT_AGENT_LLM_FALLBACK_PROVIDER='', DATT_AGENT_LLM_FALLBACK_MODEL='',
            DATT_ENVIRONMENT='test', DATT_STRICT_AUTH='0', DATT_REQUIRE_OPERATIONAL_AUTH='0',
            DATT_AGENT_AUTH_SECRET=secrets.token_urlsafe(32), DATT_SECRET_KEY='', DATT_TRUSTED_PROXY_SECRET='',
            OPENAI_API_KEY='', GEMINI_API_KEY='', GOOGLE_API_KEY='', SUPABASE_URL='',
            SUPABASE_SERVICE_ROLE_KEY='', DATT_EMAIL_PASSWORD='', DATT_EMAIL_USERNAME='', DATT_EMAIL_TO='',
            DATT_TEST_POSTGRES_URL='', DATT_TEST_POSTGRES_RESTART='0', DATT_RUN_SUPABASE_MEDIA_TEST='0',
        )
        # Camera API/source-selection tests need the existing schema, not an
        # empty database. Never create tables in the project's configured DB.
        from src.db.database import Database
        from src.db.models import Base
        db = Database()
        Base.metadata.create_all(db.engine)
        db.dispose()
        # Checkpoint discovery otherwise falls back to reading the production .env.
        from src.agent.memory import checkpoint
        checkpoint.get_postgres_connection_string = lambda: None
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
