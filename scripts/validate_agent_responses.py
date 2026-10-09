"""Run all Agent regressions against disposable, credential-free fixtures."""
import os
from pathlib import Path
import sys
import tempfile
import secrets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    with tempfile.TemporaryDirectory(prefix='datt-agent-tests-') as directory:
        os.environ.update({
            'DATT_DATABASE_URL': 'sqlite:///' + (Path(directory) / 'agent.db').as_posix(),
            'DATT_REQUIRE_PERSISTENCE': '0', 'DATT_AGENT_LLM_PROVIDER': 'mock',
            'DATT_AGENT_EMBEDDING_PROVIDER': 'mock', 'DATT_STORAGE_BACKEND': 'local',
            'OPENAI_API_KEY': '', 'GEMINI_API_KEY': '', 'GOOGLE_API_KEY': '',
            'SUPABASE_URL': '', 'SUPABASE_SERVICE_ROLE_KEY': '',
            'DATT_STRICT_AUTH': '0', 'DATT_REQUIRE_OPERATIONAL_AUTH': '0',
            'DATT_ENVIRONMENT': 'test', 'DATT_AGENT_AUTH_SECRET': secrets.token_urlsafe(32),
            'DATT_SECRET_KEY': '', 'DATT_TRUSTED_PROXY_SECRET': '',
        })
        from src.db.database import Database
        from src.db.models import Base
        db = Database()
        Base.metadata.create_all(db.engine)
        db.dispose()
        import pytest
        tests = sorted(str(p) for p in (ROOT / 'tests').glob('test_agent_*.py'))
        return pytest.main([*tests, '-q', '--tb=short', *sys.argv[1:]])

if __name__ == '__main__':
    raise SystemExit(main())
