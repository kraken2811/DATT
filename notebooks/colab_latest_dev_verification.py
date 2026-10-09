# %% 1. Inspect the existing runtime first. Paste each numbered cell into the existing notebook.
import ast
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

ROOT = Path('/content/DATT')
REMOTE = 'https://github.com/kraken2811/DATT.git'
REQUIRED = ('DATT_DATABASE_URL', 'DATT_STORAGE_BACKEND', 'SUPABASE_URL',
            'SUPABASE_SERVICE_ROLE_KEY', 'DATT_STORAGE_BUCKET')
RESULT = {'runtime_accessible': Path('/content').is_dir(), 'stages': {},
          'live_smoke': 'BLOCKED', 'checkpoint': 'BLOCKED', 'ui_browser': 'UNVERIFIED'}
# API mode never activates camera feeds. No GPU processing or paid API calls in these cells.
PORT = 8501
MODE = 'api'
# Required: fill in the reviewed commit AFTER it is approved and published to origin/dev.
# A fetched branch that differs from this exact revision cannot stop or deploy a service.
APPROVED_SOURCE_COMMIT = None
# Leave False until the DBA has verified the database/schema and a usable recovery point.
DATABASE_IDENTITY_CONFIRMED = False
RECOVERY_POINT_CONFIRMED = False
PENDING_MIGRATIONS_REVIEWED = False
ALLOW_MIGRATION = False

class Blocked(Exception):
    pass

def command(args, *, cwd=None, env=None, timeout=120):
    return subprocess.run(args, cwd=cwd, env=env, text=True,
                          capture_output=True, timeout=timeout)

def require(value, reason):
    if not value:
        raise Blocked(reason)

def stage(name, action):
    try:
        action()
        RESULT['stages'][name] = 'PASS'
    except Blocked as exc:
        # Blocked messages below are static labels, never provider/driver exception text.
        RESULT['stages'][name] = 'BLOCKED: ' + str(exc)
    except Exception as exc:
        RESULT['stages'][name] = 'FAIL: ' + type(exc).__name__
    print(name + '=' + RESULT['stages'][name])

def passed(name):
    return RESULT['stages'].get(name) == 'PASS'

def git(*args):
    r = command(['git', *args], cwd=ROOT)
    require(r.returncode == 0, 'GIT_COMMAND_FAILED; local files preserved')
    return r.stdout.strip()

def cli(action, *args, timeout=180):
    r = command([sys.executable, 'scripts/datt.py', action,
                 '--timeout', str(timeout - 15), *args], cwd=ROOT, timeout=timeout)
    fields = {}
    for line in r.stdout.splitlines():
        if '=' in line and not line.startswith('checking='):
            key, value = line.split('=', 1)
            fields[key] = value
    return r.returncode, fields

def occupied(port):
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0

def runtime_path():
    return Path(os.environ.get('DATT_RUNTIME_DIR', ROOT / '.datt-runtime')).resolve()

def owned_record():
    # All ownership checks execute the latest CLI in a fresh process. Never reuse cached src modules
    # from an earlier notebook run after updating the checkout.
    _, status = cli('status')
    path = runtime_path() / 'backend.json'
    require(path.is_file(), 'OWNED_PROCESS_RECORD_MISSING')
    record = json.loads(path.read_text())
    require(status.get('status') == 'RUNNING' and status.get('pid') == str(record['pid'])
            and status.get('mode') == record['mode'] and status.get('port') == str(record['port']),
            'PROCESS_OWNERSHIP_NOT_VERIFIED')
    return record

def postgres_engine():
    # Explicit URL, fresh engine: notebook-cached Database/AgentConfig objects may refer to old settings.
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    url = make_url(os.environ['DATT_DATABASE_URL'])
    require(url.get_backend_name() in ('postgres', 'postgresql'), 'POSTGRESQL_REQUIRED')
    if url.drivername in ('postgres', 'postgresql'):
        url = url.set(drivername='postgresql+psycopg')
    return create_engine(url, connect_args={'connect_timeout': 10})

def inspect_runtime():
    require(RESULT['runtime_accessible'], 'RUN_IN_EXISTING_COLAB_RUNTIME')
    RESULT.update(python=sys.version.split()[0], working_directory=str(Path.cwd()),
                  kernel_pid=os.getpid(), checkout_exists=ROOT.exists(),
                  drive_mounted=os.path.ismount('/content/drive'))
    print(json.dumps({k: v for k, v in RESULT.items() if k not in ('stages',)}, indent=2))
    names = ('torch', 'torchvision', 'torchaudio', 'onnxruntime-gpu', 'onnxruntime',
             'fastapi', 'langchain-core', 'langgraph', 'langgraph-checkpoint-postgres',
             'psycopg', 'fastembed', 'ultralytics', 'supervision', 'insightface', 'easyocr')
    RESULT['installed'] = {}
    for name in names:
        try:
            RESULT['installed'][name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            RESULT['installed'][name] = 'MISSING'
    print(json.dumps(RESULT['installed'], indent=2))
    probe = command([sys.executable, '-c', '''import json
import torch
r={'torch':torch.__version__,'cuda_build':torch.version.cuda,'cuda':torch.cuda.is_available()}
if r['cuda']:
    r.update(gpu=torch.cuda.get_device_name(0),memory_bytes=torch.cuda.get_device_properties(0).total_memory,
             tensor_ok=bool((torch.ones(2,device='cuda')+1).sum().item()==4))
try:
    import onnxruntime as ort
    r['onnx_providers']=ort.get_available_providers()
except ImportError:
    r['onnx_providers']=[]
print(json.dumps(r))'''], timeout=90)
    if probe.returncode == 0:
        RESULT['gpu'] = json.loads(probe.stdout.splitlines()[-1])
        print(json.dumps(RESULT['gpu'], indent=2))
    else:
        RESULT['gpu'] = {'status': 'IMPORT_OR_CUDA_PROBE_FAILED'}
        print('GPU_PROBE=FAILED; no package replacement performed')
    values = {}
    if (ROOT / '.env').is_file():
        try:
            from dotenv import dotenv_values
            values = dotenv_values(ROOT / '.env', interpolate=False)
        except ImportError:
            print('DOTENV_INSPECTION=MISSING_DEPENDENCY')
    for name in REQUIRED:
        print(name + '=' + ('SET' if os.environ.get(name) or values.get(name) else 'MISSING'))
    print('LISTENERS=' + json.dumps({str(p): occupied(p) for p in (8000, 8501)}))
    if (ROOT / 'scripts/datt.py').is_file():
        _, fields = cli('status')
        RESULT['previous_backend'] = {k: fields.get(k) for k in ('pid', 'status', 'port', 'mode', 'health')}
        print('DATT_STATUS=' + json.dumps(RESULT['previous_backend']))

stage('environment', inspect_runtime)

# %% 2. Inspect and safely synchronize actual latest remote dev. Never use the Drive Git mirror.
def sync_source():
    require(passed('environment'), 'ENVIRONMENT_INSPECTION_REQUIRED')
    require(isinstance(APPROVED_SOURCE_COMMIT, str) and re.fullmatch(r'[0-9a-f]{40}', APPROVED_SOURCE_COMMIT),
            'APPROVED_COMMIT_REQUIRED; review local fixes before publishing to dev')
    if not ROOT.exists():
        advertised = command(['git', 'ls-remote', REMOTE, 'refs/heads/dev'], cwd='/content')
        require(advertised.returncode == 0 and advertised.stdout.split()
                and advertised.stdout.split()[0] == APPROVED_SOURCE_COMMIT,
                'REMOTE_DEV_NOT_APPROVED; no clone or service change performed')
        require(not occupied(8000) and not occupied(PORT), 'UNKNOWN_LISTENER; not stopped')
        r = command(['git', 'clone', '--branch', 'dev', REMOTE, str(ROOT)], cwd='/content', timeout=180)
        require(r.returncode == 0, 'CLONE_FAILED; inspect partial checkout manually')
        RESULT['previous_commit'] = 'NO_CHECKOUT'
    else:
        require(ROOT.resolve() == ROOT and (ROOT / '.git').is_dir(), 'LOCAL_GIT_CHECKOUT_REQUIRED')
        require(Path(git('rev-parse', '--show-toplevel')).resolve() == ROOT, 'WRONG_GIT_ROOT')
        RESULT['previous_commit'] = git('rev-parse', 'HEAD')
        RESULT['previous_branch'] = git('branch', '--show-current')
        canonical = git('remote', 'get-url', 'origin').removesuffix('.git').rstrip('/')
        require(canonical in ('https://github.com/kraken2811/DATT', 'git@github.com:kraken2811/DATT'),
                'UNEXPECTED_ORIGIN; review remote without exposing credentials')
        dirty = git('status', '--short')
        RESULT['dirty_working_tree'] = bool(dirty)
        # Include untracked files: stop rather than overwrite a runtime patch.
        if dirty:
            print('LOCAL_CHANGES_PRESERVED:\n' + dirty)
            raise Blocked('DIRTY_CHECKOUT; resolve tracked/untracked changes before sync')
        git('fetch', 'origin', 'refs/heads/dev:refs/remotes/origin/dev')
        target = git('rev-parse', 'origin/dev')
        RESULT['latest_remote_dev'] = target
        require(target == APPROVED_SOURCE_COMMIT, 'REMOTE_DEV_NOT_APPROVED; owned service and checkout preserved')
        ancestor = command(['git', 'merge-base', '--is-ancestor', 'HEAD', target], cwd=ROOT)
        require(ancestor.returncode == 0, 'NON_FAST_FORWARD; local commits preserved')
        if git('rev-parse', 'HEAD') != target or git('branch', '--show-current') != 'dev':
            # Existing process manager validates PID, creation time, command and random token.
            _, fields = cli('status')
            if fields.get('status') == 'RUNNING':
                code, _ = cli('stop')
                require(code == 0, 'OWNED_SERVICE_STOP_FAILED; no forced termination')
            require(not occupied(8000) and not occupied(PORT), 'LISTENER_REMAINS; no port-wide kill')
            # Reuse the reviewed source refresh function without its Drive mount/model-copy side effects.
            source = (ROOT / 'notebooks/colab_drive_cache_cell.py').read_text(encoding='utf-8-sig')
            tree = ast.parse(source)
            fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'refresh_source')
            ns = {'Path': Path, 'subprocess': subprocess, 'sys': sys}
            exec(compile(ast.Module(body=[fn], type_ignores=[]), '<existing-refresh-source>', 'exec'), ns)
            ns['refresh_source'](ROOT, REMOTE)
    git('fetch', 'origin', 'refs/heads/dev:refs/remotes/origin/dev')
    RESULT['latest_remote_dev'] = git('rev-parse', 'origin/dev')
    RESULT['source_commit'] = git('rev-parse', 'HEAD')
    RESULT['dirty_working_tree'] = bool(git('status', '--short'))
    require(RESULT['latest_remote_dev'] == APPROVED_SOURCE_COMMIT, 'REMOTE_MOVED_FROM_APPROVED_COMMIT; deployment blocked')
    require(RESULT['source_commit'] == RESULT['latest_remote_dev'], 'REMOTE_MOVED; rerun sync before deployment')
    require(git('branch', '--show-current') == 'dev', 'DEV_BRANCH_REQUIRED')
    modules = ('src/agent/face_history.py', 'src/agent/vehicle_history.py', 'src/agent/conversations.py',
               'src/agent/tools/analytics.py', 'src/agent/tools/alerts.py', 'src/agent/tools/notifications.py',
               'src/agent/tools/reports.py', 'src/agent/security.py', 'src/agent/tools/notification_queries.py',
               'src/db/migrations/versions/0014_agent_conversations.py')
    require(all((ROOT / p).is_file() for p in modules), 'LATEST_AGENT_MODULE_MISSING')
    index = ROOT / 'src/ui/static/react_dist/index.html'
    require(index.is_file(), 'REACT_PRODUCTION_INDEX_MISSING')
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', index.read_text())
    require(assets and all((index.parent / p.lstrip('/')).is_file() for p in assets), 'REACT_PRODUCTION_ASSET_MISSING')
    print('SOURCE_COMMIT=' + RESULT['source_commit'])
    print('LATEST_REMOTE_DEV=' + RESULT['latest_remote_dev'])

stage('source', sync_source)

# %% 3. Review and run the existing bounded installer; retain CUDA Torch and GPU ORT.
def install_dependencies():
    require(passed('source'), 'SOURCE_SYNC_REQUIRED')
    before = {n: metadata.version(n) for n in ('torch', 'torchvision', 'torchaudio')}
    require(RESULT.get('gpu', {}).get('tensor_ok'), 'CUDA_TENSOR_REQUIRED; select GPU manually, do not reset runtime')
    require(RESULT['installed'].get('onnxruntime') == 'MISSING', 'CPU_ORT_COLLISION; review manually')
    # Review compatibility without importing the installer into the persistent notebook kernel.
    review = command([sys.executable, '-c', '''import importlib.util,json
s=importlib.util.spec_from_file_location('installer','scripts/colab_install.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
missing,incompatible=m.plan()
print(json.dumps({'missing':missing,'incompatible':incompatible,'cuda_ready':m.cuda_torch_ready()}))'''], cwd=ROOT, timeout=120)
    require(review.returncode == 0, 'INSTALLER_REVIEW_FAILED')
    plan = json.loads(review.stdout.splitlines()[-1])
    print('INSTALL_PLAN=' + json.dumps(plan))
    require(not plan['incompatible'] and plan['cuda_ready'], 'INSTALLER_COMPATIBILITY_BLOCKED')
    _, backend = cli('status')
    print('PRE_INSTALL_SERVICE=' + json.dumps({k: backend.get(k) for k in ('pid', 'status', 'port', 'mode', 'health')}))
    if plan['missing'] and (occupied(8000) or occupied(PORT)):
        owned_record()  # The installer also checks every listener PID before stopping its owned service.
    r = command([sys.executable, 'scripts/colab_install.py'], cwd=ROOT, timeout=3600)
    require(r.returncode == 0, 'INSTALL_FAILED; inspect .datt-runtime/install locally; do not reset runtime')
    after = {n: metadata.version(n) for n in before}
    require(before == after, 'TORCH_VERSIONS_CHANGED; deployment stopped')
    gpu = command([sys.executable, '-c', '''import torch,onnxruntime as ort,json
assert torch.cuda.is_available()
assert (torch.ones(2,device='cuda')+1).sum().item()==4
assert 'CUDAExecutionProvider' in ort.get_available_providers()
print(json.dumps({'torch':torch.__version__,'gpu':torch.cuda.get_device_name(0),'providers':ort.get_available_providers()}))'''], cwd=ROOT, timeout=90)
    require(gpu.returncode == 0, 'GPU_IMPORT_FAILED; possible restart requirement, no automatic restart')
    RESULT['dependencies'] = 'PASS'
    RESULT['gpu_verified'] = json.loads(gpu.stdout.splitlines()[-1])
    print(json.dumps(RESULT['gpu_verified']))
    print('CV_MODELS=NOT_INITIALIZED; API mode selected; no camera/video processing authorized')

stage('dependencies', install_dependencies)

# %% 4. Credential-free regression suites. PostgreSQL is never used by these tests.
def test_suites():
    require(passed('source'), 'SOURCE_SYNC_REQUIRED')
    # Existing runner overrides DB/provider/API keys and creates disposable SQLite tables.
    output_dir = ROOT / '.datt-runtime' / ('verify-dev-' + uuid.uuid4().hex[:12])
    output_dir.mkdir(parents=True)
    RESULT['test_output_directory'] = str(output_dir)
    suites = {
        'agent': [sys.executable, 'scripts/validate_agent_responses.py'],
        'backend_colab': [sys.executable, 'scripts/test_dev.py',
            'tests/test_backend_completion.py', 'tests/test_colab_startup.py',
            'tests/test_colab_source.py', 'tests/test_colab_install.py',
            'tests/test_colab_drive_cache.py', 'tests/test_migration_head.py',
            'tests/test_database_pool_lifecycle.py', 'tests/test_web_server.py', 'tests/test_alerts.py',
            'tests/test_notifications.py', 'tests/test_cli.py', 'tests/test_colab_latest_dev_verification.py'],
    }
    RESULT['tests'] = {}
    for label, args in suites.items():
        with tempfile.TemporaryDirectory(prefix='datt-dev-isolated-') as temporary:
            env = {k: v for k, v in os.environ.items() if not k.startswith(('DATT_', 'SUPABASE_', 'AGENT_'))}
            env.update(DATT_DATABASE_URL='sqlite:///' + (Path(temporary) / 'test.db').as_posix(),
                DATT_ENVIRONMENT='test', DATT_REQUIRE_PERSISTENCE='0', DATT_STORAGE_BACKEND='local', DATT_STORAGE_ROOT=temporary,
                DATT_RUNTIME_DIR=temporary, DATT_AGENT_LLM_PROVIDER='mock', DATT_AGENT_EMBEDDING_PROVIDER='mock',
                DATT_AGENT_AUTH_SECRET=uuid.uuid4().hex, DATT_STRICT_AUTH='0', DATT_REQUIRE_OPERATIONAL_AUTH='0',
                OPENAI_API_KEY='', GEMINI_API_KEY='', GOOGLE_API_KEY='', SUPABASE_URL='',
                SUPABASE_SERVICE_ROLE_KEY='', DATT_EMAIL_PASSWORD='', DATT_EMAIL_USERNAME='', DATT_EMAIL_TO='')
            xml = output_dir / (label + '.xml')
            r = command([*args, '--junitxml=' + str(xml)], cwd=ROOT, env=env, timeout=1200)
            (output_dir / (label + '.log')).write_text(r.stdout + r.stderr, encoding='utf-8')
            if not xml.is_file():
                RESULT['tests'][label] = {'exit': r.returncode, 'status': 'NO_TEST_REPORT'}
                continue
            cases = ET.parse(xml).findall('.//testcase')
            counts = {'passed': 0, 'failed': 0, 'skipped': 0, 'exit': r.returncode}
            by_suite = {}
            for case in cases:
                status = 'failed' if case.find('failure') is not None or case.find('error') is not None else (
                    'skipped' if case.find('skipped') is not None else 'passed')
                counts[status] += 1
                group = case.get('classname', 'unknown')
                by_suite.setdefault(group, {'passed': 0, 'failed': 0, 'skipped': 0})[status] += 1
                if status == 'failed':
                    print('FAILED=' + group + '::' + case.get('name', 'unknown'))
            counts['suites'] = by_suite
            RESULT['tests'][label] = counts
            print(label + '=' + json.dumps(counts))
    require(all(v.get('exit') == 0 and v.get('failed') == 0 and v.get('passed', 0) > 0
                for v in RESULT['tests'].values()), 'REGRESSIONS_FAILED; no deployment until a reviewed DEV passes')

stage('isolated_tests', test_suites)

# %% 5. Load existing granted configuration. Only SET/MISSING is printed; .env is read-only.
def load_existing_configuration():
    require(passed('source'), 'SOURCE_SYNC_REQUIRED')
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False, interpolate=False)
    # Reuse the existing secret loader without running its install/migration/start main() or cached imports.
    source = (ROOT / 'scripts/colab_bootstrap.py').read_text(encoding='utf-8-sig')
    fn = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'load_secrets')
    namespace = {'os': os}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<existing-load-secrets>', 'exec'), namespace)
    namespace['load_secrets']()
    # Read only existing, explicitly granted auth secrets; do not generate users or tokens here.
    from google.colab import userdata
    for name in ('DATT_AGENT_AUTH_SECRET', 'DATT_SECRET_KEY', 'DATT_TRUSTED_PROXY_SECRET', 'DATT_STRICT_AUTH'):
        if not os.environ.get(name):
            try:
                value = userdata.get(name)
                if value:
                    os.environ[name] = value
            except (userdata.SecretNotFoundError, userdata.NotebookAccessError):
                pass
    for name in REQUIRED:
        print(name + '=' + ('SET' if os.environ.get(name) else 'MISSING'))
    require(all(os.environ.get(n) for n in REQUIRED), 'PERSISTENT_CONFIGURATION_MISSING')
    from sqlalchemy.engine import make_url
    require(make_url(os.environ['DATT_DATABASE_URL']).get_backend_name() in ('postgres', 'postgresql'),
            'REAL_POSTGRESQL_REQUIRED; SQLite is only a test fixture')
    require(os.environ['DATT_STORAGE_BACKEND'] == 'supabase', 'SUPABASE_STORAGE_REQUIRED')
    os.environ['DATT_REQUIRE_PERSISTENCE'] = '1'

stage('configuration', load_existing_configuration)

# %% 6. Read-only PostgreSQL/storage/migration inspection. Upgrade is gated by DBA confirmations above.
def database_preflight():
    require(passed('configuration'), 'PERSISTENT_CONFIGURATION_REQUIRED')
    code, fields = cli('db-check')
    safe = ('database_connected', 'database_type', 'postgresql_version', 'pgvector',
            'pgvector_version', 'repository_head', 'alembic_revision', 'alembic', 'tables_verified')
    RESULT['database'] = {k: fields.get(k, 'unknown') for k in safe}
    print('DATABASE=' + json.dumps(RESULT['database']))
    require(fields.get('database_type') == 'postgresql' and fields.get('database_connected') == 'true',
            'POSTGRESQL_CONNECTION_FAILED')
    # Inspect with SQLAlchemy only; no checkpointer initialization (saver.setup() writes tables).
    from sqlalchemy import inspect, text
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    engine = postgres_engine()
    try:
        with engine.connect() as conn:
            tables = set(inspect(conn).get_table_names())
            expected = {'cameras', 'targets', 'face_events', 'vehicle_events', 'plate_events',
                        'vehicle_passages', 'notifications', 'agent_conversations',
                        'checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations'}
            RESULT['missing_tables'] = sorted(expected - tables)
            print('MISSING_TABLES=' + json.dumps(RESULT['missing_tables']))
            schema = conn.scalar(text('SELECT current_schema()'))
            # Print a fingerprint, not the configured database/server or credentials.
            identity = str(engine.url.set(password=None)) + ':' + str(schema)
            print('DATABASE_SCHEMA_FINGERPRINT=' + hashlib.sha256(identity.encode()).hexdigest())
            if 'knowledge_chunks' in tables:
                vector_type = conn.scalar(text("SELECT format_type(a.atttypid,a.atttypmod) FROM pg_attribute a "
                    "JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE c.relname='knowledge_chunks' AND n.nspname=current_schema() AND a.attname='embedding'"))
                RESULT['rag_vector_type'] = vector_type
                print('RAG_VECTOR_TYPE=' + str(vector_type))
    finally:
        engine.dispose()
    # Supabase bucket metadata GET; do not upload test objects or run doctor yet.
    import requests
    url = os.environ['SUPABASE_URL'].rstrip('/') + '/storage/v1/bucket/'
    from urllib.parse import quote
    key = os.environ['SUPABASE_SERVICE_ROLE_KEY']
    response = requests.get(url + quote(os.environ['DATT_STORAGE_BUCKET'], safe=''),
        headers={'Authorization': 'Bearer ' + key, 'apikey': key}, timeout=20)
    RESULT['storage_http'] = response.status_code
    print('SUPABASE_BUCKET_HTTP=' + str(response.status_code))
    require(response.status_code == 200, 'SUPABASE_BUCKET_READ_FAILED')
    scripts = ScriptDirectory.from_config(Config(str(ROOT / 'src/db/alembic.ini')))
    head = scripts.get_current_head()
    print('ACTUAL_ALEMBIC_HEAD=' + str(head))
    current = fields.get('alembic_revision')
    for action in ('current', 'heads'):
        r = command([sys.executable, '-m', 'alembic', '-c', 'src/db/alembic.ini', action], cwd=ROOT)
        print('ALEMBIC_' + action.upper() + '_EXIT=' + str(r.returncode))
        require(r.returncode == 0, 'ALEMBIC_INSPECTION_FAILED')
    if current != head:
        require(current not in (None, 'unknown') and ',' not in current, 'UNKNOWN_OR_MULTIPLE_DB_REVISIONS; DBA review required')
        pending = list(scripts.iterate_revisions(head, current))
        for revision in reversed(pending):
            path = Path(revision.path)
            source = path.read_text(encoding='utf-8-sig')
            upgrade = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'upgrade')
            operations = [ast.unparse(n.func) for n in ast.walk(upgrade) if isinstance(n, ast.Call)]
            print('PENDING=' + json.dumps({'revision': revision.revision, 'file': str(path.relative_to(ROOT)),
                'sha256': hashlib.sha256(source.encode()).hexdigest(), 'calls': operations}))
        require(ALLOW_MIGRATION and DATABASE_IDENTITY_CONFIRMED and RECOVERY_POINT_CONFIRMED
                and PENDING_MIGRATIONS_REVIEWED, 'PENDING_MIGRATIONS; review upgrade bodies, backup and DB identity first')
        # Do not regard the call list as proof of non-destructiveness: DBA must review the full upgrade.
        require(passed('isolated_tests'), 'TESTS_MUST_PASS_BEFORE_SCHEMA_UPGRADE')
        code, fields = cli('migrate')
        require(code == 0 and fields.get('alembic') == 'PASS', 'SUPPORTED_MIGRATION_FAILED')
        raise Blocked('MIGRATION_APPLIED; rerun this cell to inspect all tables')
    require(fields.get('pgvector') == 'PASS' and not RESULT['missing_tables'], 'PGVECTOR_OR_REQUIRED_TABLES_MISSING')
    require(code == 0 and fields.get('tables_verified') == 'true', 'DATABASE_PREFLIGHT_FAILED')

stage('database', database_preflight)

# %% 7. Tool imports/provider/dimension and source risks. No LLM, embedding or recognition calls.
def inspect_agent():
    require(passed('source'), 'SOURCE_SYNC_REQUIRED')
    # Behavioral regressions are the gate; a literal scan cannot prove security or distinguish
    # rejection of a legacy key from an unsafe signing-key fallback.
    require(passed('isolated_tests'), 'CURRENT_DEV_REGRESSION_FAILURES_BLOCK_STARTUP')
    require(passed('configuration'), 'CONFIGURATION_REQUIRED')
    probe = command([sys.executable, '-c', '''import json
from src.agent.config import agent_config as c
from src.agent.tools import ALL_AGENT_TOOLS
from src.agent.api.auth import validate_auth_configuration
from src.agent.security import operational_auth_required, persistent_history_required
validate_auth_configuration()
assert operational_auth_required() and persistent_history_required()
print(json.dumps({'tools':[t.name for t in ALL_AGENT_TOOLS],'provider':c.llm_provider,
 'model':c.model_name,'embedding_provider':c.embedding_provider,'embedding_model':c.embedding_model,
 'embedding_dim':c.embedding_dim}))'''], cwd=ROOT, timeout=120)
    require(probe.returncode == 0, 'AGENT_IMPORT_FAILED')
    RESULT['auth_policy'] = 'PASS: fresh process validated signing configuration and required guards'
    RESULT['agent'] = json.loads(probe.stdout.splitlines()[-1])
    print('AGENT=' + json.dumps(RESULT['agent']))
    expected = {'get_camera', 'get_camera_status', 'get_event', 'search_events', 'search_watchlist',
        'get_event_statistics', 'get_traffic_analytics', 'get_alerts', 'get_notifications_status',
        'generate_operational_report', 'get_knowledge'}
    require(set(RESULT['agent']['tools']) == expected, 'ELEVEN_TOOLS_REQUIRED')
    if RESULT['agent']['provider'] == 'mock':
        print('ACTIVE_MODEL=MockChatModel; configured model name does not enable Gemini')
    secret = os.environ.get('DATT_AGENT_AUTH_SECRET') or os.environ.get('DATT_SECRET_KEY')
    require(secret and secret != 'datt_secure_internal_secret_key' and len(secret) >= 32,
            'CUSTOM_AUTH_SECRET_REQUIRED; configure an existing authorized account, never print the secret')
    require(os.environ.get('DATT_STRICT_AUTH') == '1', 'STRICT_AUTH_REQUIRED')
    print('REAL_PROVIDER_SMOKE=SKIPPED; these cells have no paid API authorization')
    require(RESULT['agent']['provider'] == 'mock', 'LIVE_CHAT_SKIPPED; real provider needs separate usage authorization')
    require(RESULT.get('rag_vector_type') == 'vector(' + str(RESULT['agent']['embedding_dim']) + ')',
            'RAG_VECTOR_DIMENSION_MISMATCH')
    require(RESULT['agent']['embedding_provider'] != 'openai', 'PAID_EMBEDDING_CALLS_NOT_AUTHORIZED')
    print('RAG_MODEL_COMPATIBILITY=UNVERIFIED until real retrieval; equal dimensions alone do not prove same model')
    require(passed('isolated_tests'), 'CURRENT_DEV_REGRESSION_FAILURES_BLOCK_STARTUP')

stage('agent', inspect_agent)

# %% 8. Start/restart only owned API service. doctor performs a disposable storage write.
# The requested doctor is gated by recovery confirmation because it uploads/deletes a random probe object.
def start_application():
    require(all(passed(n) for n in ('source', 'dependencies', 'isolated_tests', 'configuration', 'database', 'agent')),
            'DEPLOYMENT_GATES_NOT_PASSED')
    require(DATABASE_IDENTITY_CONFIRMED and RECOVERY_POINT_CONFIRMED,
            'DB_RECOVERY_CONFIRMATION_REQUIRED; checkpointer setup may create tables')
    require(not git('status', '--short'), 'CHECKOUT_CHANGED_AFTER_TESTS; deployment blocked')
    require(git('rev-parse', 'HEAD') == RESULT.get('source_commit') == APPROVED_SOURCE_COMMIT,
            'SOURCE_CHANGED_AFTER_TESTS; deployment blocked')
    git('fetch', 'origin', 'refs/heads/dev:refs/remotes/origin/dev')
    require(git('rev-parse', 'origin/dev') == APPROVED_SOURCE_COMMIT,
            'REMOTE_MOVED_AFTER_TESTS; rerun review and verification')
    # Current doctor invokes storage-check (random owned object) and cv-check; it does not activate video sources.
    code, doctor = cli('doctor', timeout=240)
    RESULT['doctor'] = {k: doctor.get(k) for k in ('ready_for_local', 'database_connected', 'storage_connected', 'cv_status')}
    print('DOCTOR=' + json.dumps(RESULT['doctor']))
    require(code == 0 and doctor.get('ready_for_local') == 'true', 'DOCTOR_FAILED')
    _, status = cli('status')
    if status.get('status') == 'RUNNING':
        record = owned_record()
        require(record['mode'] == MODE and record['port'] == PORT, 'RUNNING_MODE_DIFFERS; review before restart')
        code, _ = cli('restart', '--mode', MODE, '--port', str(PORT), timeout=240)
    else:
        require(not occupied(PORT), 'UNKNOWN_BACKEND_LISTENER; not stopped')
        code, _ = cli('start', '--mode', MODE, '--port', str(PORT), timeout=240)
    require(code == 0, 'BACKEND_START_FAILED; inspect private sanitized backend log')
    owned_record()
    _, RESULT['backend'] = cli('status')
    require(RESULT['backend']['health'] == 'PASS', 'BACKEND_NOT_HEALTHY')
    print('BACKEND=' + json.dumps(RESULT['backend']))

stage('application', start_application)

# %% 9. Authenticated read-only endpoints; enter the existing authorized test account's Bearer token privately.
def live_endpoints():
    require(passed('application'), 'HEALTHY_OWNED_BACKEND_REQUIRED')
    import getpass
    import requests
    global SESSION, BASE, TEST_TOKEN
    TEST_TOKEN = getpass.getpass('Bearer token for an EXISTING authorized test account (never printed): ').strip()
    require(TEST_TOKEN, 'AUTHORIZED_TEST_TOKEN_REQUIRED')
    SESSION = requests.Session()
    SESSION.headers['Authorization'] = 'Bearer ' + TEST_TOKEN
    BASE = 'http://127.0.0.1:' + str(PORT)
    health = SESSION.get(BASE + '/healthz', timeout=15)
    require(health.status_code == 200, 'HEALTHZ_FAILED')
    h = health.json()
    require(h.get('commit') == RESULT['source_commit'] and h.get('mode') == MODE, 'LIVE_SOURCE_OR_MODE_MISMATCH')
    require(h.get('agent_llm_provider') == 'mock', 'LIVE_PROVIDER_NOT_MOCK; no paid calls made')
    schema = SESSION.get(BASE + '/openapi.json', timeout=20)
    require(schema.status_code == 200, 'LIVE_OPENAPI_FAILED')
    paths = schema.json()['paths']
    expected = {'/api/agent/chat': {'post'}, '/api/agent/conversations': {'get', 'post'},
                '/api/agent/conversations/{thread_id}': {'get', 'patch', 'delete'}}
    require(all(p in paths and methods <= set(paths[p]) for p, methods in expected.items()), 'AGENT_ROUTES_MISSING')
    RESULT['api_http'] = {}
    probes = ('/startup-health', '/api/source_status', '/api/agent/conversations',
              '/api/cameras', '/api/event_center/events', '/api/targets', '/api/watchlist/vehicles')
    for path in probes:
        if path not in paths:
            RESULT['api_http'][path] = 'UNSUPPORTED_ROUTE'
            continue
        r = SESSION.get(BASE + path, timeout=30)
        RESULT['api_http'][path] = r.status_code
        if path == '/startup-health' and r.status_code == 200:
            RESULT['workers'] = r.json()
    print('LIVE_ENDPOINT_HTTP=' + json.dumps(RESULT['api_http']))
    print('WORKERS=' + json.dumps(RESULT.get('workers', {})))
    print('API_MODE_WORKERS=not initialized by API-only runner; no notification email test is sent')
    require(RESULT['api_http'].get('/api/agent/conversations') == 200, 'AUTHORIZED_ACCOUNT_OR_REGISTRY_FAILED')
    require(all(v == 200 for v in RESULT['api_http'].values()), 'ENDPOINT_BLOCKED_OR_UNSUPPORTED; 401/403 is auth, not missing route')

stage('live_endpoints', live_endpoints)

# %% 10. Disposable conversations, live mock smoke, real PostgreSQL checkpoint restart, cleanup only owned IDs.
def smoke_and_persistence():
    require(passed('live_endpoints') and passed('database'), 'LIVE_AUTH_AND_POSTGRES_REQUIRED')
    import requests
    from sqlalchemy import text
    # The live strict-auth backend verifies this token; obtain identity from its response, never a client claim.
    account = SESSION.get(BASE + '/api/agent/conversations', timeout=30)
    require(account.status_code == 200 and account.json().get('user_id'), 'VERIFIED_ACCOUNT_REQUIRED')
    verified_user = account.json()['user_id']
    created = []
    engine = postgres_engine()
    backend_log = runtime_path() / 'backend.log'
    def log_position():
        return backend_log.stat().st_size if backend_log.exists() else 0
    def saver_logged_since(position):
        with backend_log.open('rb') as stream:
            stream.seek(position)
            output = stream.read().decode('utf-8', errors='replace')
        return ('PostgresSaver checkpointer initialized successfully' in output
                and 'using MemorySaver' not in output and 'Using MemorySaver' not in output)
    first_log_position = log_position()
    marker_a = 'ALPHA-' + str(int(uuid.uuid4().hex[:8], 16))
    marker_b = 'ALPHA-' + str(int(uuid.uuid4().hex[:8], 16))
    def api(method, path, **kwargs):
        r = SESSION.request(method, BASE + path, timeout=120, **kwargs)
        require(r.status_code == 200 and r.json().get('status') == 'success', 'LIVE_AGENT_API_FAILED')
        return r.json()
    def checkpoint_exists(tid):
        # Current make_thread_config contract; actual rows and restored history must verify it.
        internal = verified_user.strip() + ':' + tid.strip()
        with engine.connect() as conn:
            return conn.scalar(text('SELECT count(*) FROM checkpoints WHERE thread_id=:tid'), {'tid': internal}) > 0
    try:
        for label in ('A', 'B'):
            tid = 'colab_verify_' + uuid.uuid4().hex
            # Register cleanup ownership only after the create response verifies the requested ID.
            r = api('POST', '/api/agent/conversations', json={'thread_id': tid, 'title': 'Disposable verification ' + label})
            require(r['conversation']['thread_id'] == tid, 'DISPOSABLE_THREAD_ID_MISMATCH')
            created.append(tid)
        a, b = created
        api('POST', '/api/agent/chat', json={'thread_id': a, 'message': 'Mã ca trực của tôi là ' + marker_a})
        api('POST', '/api/agent/chat', json={'thread_id': b, 'message': 'Mã ca trực của tôi là ' + marker_b})
        before = api('GET', '/api/agent/conversations/' + a)
        text_a = json.dumps(before.get('messages', []), ensure_ascii=False)
        require(marker_a in text_a and marker_b not in text_a, 'CONVERSATION_SWITCH_ISOLATION_FAILED')
        follow = api('POST', '/api/agent/chat', json={'thread_id': a, 'message': 'Mã ca trực của tôi là gì?'})
        require(marker_a in follow['reply'] and marker_b not in follow['reply'], 'CONTEXT_RECALL_FAILED')
        # A fresh notebook get_checkpointer() would prove only the notebook's checkpointer, not the backend's.
        # Real PG rows for these unique IDs prove this backend persisted its checkpoints.
        require(checkpoint_exists(a) and checkpoint_exists(b),
                'BACKEND_USING_MEMORY_OR_CHECKPOINT_NOT_PERSISTED')
        require(saver_logged_since(first_log_position), 'LIVE_POSTGRES_SAVER_CLASS_NOT_CONFIRMED; do not claim persistence pass')
        record = owned_record()
        require(record['mode'] == MODE and record['port'] == PORT, 'OWNED_API_RESTART_REQUIRED')
        old_token = record['token']
        restart_log_position = log_position()
        code, _ = cli('restart', '--mode', MODE, '--port', str(PORT), timeout=240)
        require(code == 0 and owned_record()['token'] != old_token, 'VERIFIED_RESTART_FAILED')
        restored = api('GET', '/api/agent/conversations/' + a)
        require(marker_a in json.dumps(restored.get('messages', [])) and checkpoint_exists(a), 'PG_RESTORATION_FAILED')
        require(saver_logged_since(restart_log_position), 'POST_RESTART_POSTGRES_SAVER_CLASS_NOT_CONFIRMED')
        follow = api('POST', '/api/agent/chat', json={'thread_id': a, 'message': 'Mã ca trực của tôi là gì?'})
        require(marker_a in follow['reply'] and marker_b not in follow['reply'], 'PG_CONTEXT_AFTER_RESTART_FAILED')
        RESULT['checkpoint'] = 'PASS: PG checkpoint rows and context survived owned restart'
        queries = {
            'camera': 'Camera 01 hiện đang online hay offline?',
            'vehicle': 'Tìm lịch sử xe biển số 30A-12345.',
            'face': 'Tìm lịch sử nhận diện người tên Long.',
            'traffic': 'Trong 7 ngày gần đây camera nào có nhiều lượt xe nhất?',
            'alerts': 'Hôm nay hệ thống có bao nhiêu cảnh báo?',
            'notifications': 'Có bao nhiêu email cảnh báo gửi thất bại hôm nay?',
            'reports': 'Tổng hợp hoạt động hệ thống hôm nay.',
            'rag': 'Theo tài liệu DATT, hệ thống xử lý camera mất kết nối như thế nào?',
            'multi_tool': 'Camera 01 hôm nay có bao nhiêu lượt xe, bao nhiêu cảnh báo và trạng thái gửi email như thế nào?',
        }
        RESULT['live_responses'] = {}
        for name, query in queries.items():
            response = api('POST', '/api/agent/chat', json={'thread_id': b, 'message': query})
            reply = response.get('reply', '')
            tools = response.get('tools_called', [])
            require(reply.strip() and len(tools) == len(set(tools)), 'EMPTY_REPLY_OR_DUPLICATE_BADGES')
            try:
                json.loads(reply)
            except ValueError:
                pass
            else:
                raise Blocked('RAW_JSON_WITHOUT_REQUEST')
            # Do not print real identities/events/plates/citations into a shared notebook output.
            RESULT['live_responses'][name] = {'status': response['status'], 'tools': tools,
                'sources_count': len(response.get('sources', [])), 'reply_characters': len(reply),
                'grounding': 'MANUAL_REVIEW_REQUIRED in authorized UI against recorded facts'}
        print('LIVE_SMOKE=' + json.dumps(RESULT['live_responses']))
        RESULT['live_smoke'] = 'STRUCTURAL_PASS; actual facts/empty results/citations require authorized review'
    finally:
        RESULT['disposable_cleanup'] = {}
        for tid in created:
            try:
                r = SESSION.delete(BASE + '/api/agent/conversations/' + tid, timeout=60)
                require(r.status_code == 200 and r.json().get('cleared'), 'DISPOSABLE_CHECKPOINT_CLEANUP_FAILED')
                with engine.connect() as conn:
                    exists = conn.scalar(text('SELECT count(*) FROM agent_conversations WHERE thread_id=:tid'), {'tid': tid})
                require(exists == 0 and not checkpoint_exists(tid), 'DISPOSABLE_RECORDS_REMAIN')
                RESULT['disposable_cleanup'][tid] = 'PASS'
            except Exception as exc:
                RESULT['disposable_cleanup'][tid] = 'FAILED: ' + type(exc).__name__
        engine.dispose()
        print('DISPOSABLE_CLEANUP=' + json.dumps(RESULT['disposable_cleanup']))
        require(all(v == 'PASS' for v in RESULT['disposable_cleanup'].values()), 'DISPOSABLE_CLEANUP_INCOMPLETE; only printed test IDs may be removed')

stage('live_smoke_persistence', smoke_and_persistence)

# %% 11. Verify served React assets and obtain the genuine existing Colab proxy URL.
def frontend_available():
    require(passed('application'), 'HEALTHY_BACKEND_REQUIRED')
    import requests
    base = 'http://127.0.0.1:' + str(PORT)
    local_index = ROOT / 'src/ui/static/react_dist/index.html'
    page = requests.get(base + '/agent', timeout=15)
    require(page.status_code == 200 and page.content == local_index.read_bytes(), 'SERVED_FRONTEND_NOT_CHECKOUT_ASSET')
    for path in re.findall(r'(?:src|href)="(/assets/[^"]+)"', page.text):
        r = requests.get(base + path, timeout=15)
        require(r.status_code == 200 and r.content == (local_index.parent / path.lstrip('/')).read_bytes(),
                'SERVED_REACT_ASSET_MISMATCH')
    RESULT['frontend_http'] = 'PASS: exact checked-out production bytes'
    from google.colab import output
    from urllib.parse import urlparse
    url = output.eval_js('google.colab.kernel.proxyPort(' + str(PORT) + ')')
    parsed = urlparse(url)
    require(parsed.scheme == 'https' and parsed.hostname and parsed.hostname.endswith(('.colab.dev', '.colab.googleusercontent.com'))
            and not parsed.username and not parsed.password and not parsed.query, 'COLAB_PROXY_URL_UNAVAILABLE')
    RESULT['ui_url'] = url
    print('DATT_UI_URL=' + url)
    print('MANUAL_UI_CHECK: authenticated account, Assistant/sidebar, new/reopen conversation, face/vehicle replies,')
    print('Markdown report, network requests and fatal JavaScript console errors. HTTP assets alone do not prove browser behavior.')

stage('frontend', frontend_available)

# %% 12. Actual results only. Save this output; no credentials or existing conversation content are printed.
sections = {
    'A. Colab Environment': {k: RESULT.get(k, 'UNVERIFIED') for k in
        ('runtime_accessible', 'python', 'kernel_pid', 'working_directory', 'drive_mounted', 'gpu')},
    'B. Git': {k: RESULT.get(k, 'UNVERIFIED') for k in
        ('previous_commit', 'latest_remote_dev', 'source_commit', 'dirty_working_tree')},
    'C. Dependencies': RESULT.get('gpu_verified', 'UNVERIFIED'),
    'D. Database': RESULT.get('database', 'UNVERIFIED'),
    'E. Application': {k: RESULT.get(k, 'UNVERIFIED') for k in
        ('backend', 'api_http', 'workers', 'frontend_http', 'ui_url')},
    'F. Tests': {k: RESULT.get(k, 'UNVERIFIED') for k in ('tests', 'live_smoke', 'checkpoint', 'ui_browser')},
    'G. Outstanding Issues': {'stages': RESULT['stages'], 'auth_policy': RESULT.get('auth_policy', 'UNVERIFIED'),
        'manual_review': 'Live factual grounding, RAG model identity and browser UI remain manual gates; real Gemini and CV processing skipped'},
}
for heading, values in sections.items():
    print('\n' + heading + '\n' + json.dumps(values, ensure_ascii=False, indent=2))
print('\nH. Final Result')
print('SYSTEM_READY=' + ('PARTIAL' if passed('application') else 'NO'))
print('SOURCE_COMMIT=' + RESULT.get('source_commit', 'UNVERIFIED'))
print('AGENT_READY=' + ('ISOLATED_PASS_LIVE_UNVERIFIED' if passed('agent') else 'NO'))
print('POSTGRES_READY=' + ('YES' if passed('database') else 'UNVERIFIED_OR_BLOCKED'))
print('CHECKPOINT_READY=' + RESULT.get('checkpoint', 'UNVERIFIED'))
print('GPU_READY=' + ('YES' if passed('dependencies') else 'UNVERIFIED_OR_BLOCKED'))
print('COLAB_AGENT_TESTS=' + json.dumps(RESULT.get('tests', {}).get('agent', 'NOT_RUN')))
if RESULT.get('ui_url'):
    print('DATT_UI_URL=' + RESULT['ui_url'])
# File execution must also signal failure to a shell/automation caller. Interactive
# notebook cells retain their kernel and already display every blocked stage above.
if Path(sys.argv[0]).name == 'colab_latest_dev_verification.py' and not all(
        passed(n) for n in ('environment', 'source', 'dependencies', 'isolated_tests', 'configuration',
                           'database', 'agent', 'application', 'live_endpoints', 'live_smoke_persistence', 'frontend')):
    raise SystemExit(1)
