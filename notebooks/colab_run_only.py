# %% 1. Source and model cache (the canonical cache cell is embedded in the .ipynb)
# Run this file's sections in order in Colab. No regression-test cells are included.
from pathlib import Path
import os, sys, subprocess, json
ROOT = Path('/content/DATT')
APPROVED_COMMIT = 'ac1bc2a57c05e24a19623fc150628416d2f9e02b'

def source_git(*args):
    r = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise RuntimeError('Git failed; existing files preserved. Inspect Git privately.')
    return r.stdout.strip()

if not ROOT.exists():
    r = subprocess.run(['git', 'clone', '--branch', 'dev', 'https://github.com/kraken2811/DATT.git', str(ROOT)], capture_output=True, timeout=180)
    if r.returncode:
        raise RuntimeError('Clone failed; no existing files deleted.')
if not (ROOT / '.git').is_dir():
    raise RuntimeError('/content/DATT is not a Git checkout; existing files preserved.')
if source_git('status', '--porcelain'):
    raise RuntimeError('Checkout has changes; preserve/review them before updating.')
source_git('fetch', 'origin', 'refs/heads/dev:refs/remotes/origin/dev')
if source_git('rev-parse', 'origin/dev') != APPROVED_COMMIT:
    raise RuntimeError('origin/dev changed since verification; review and verify the new commit before deployment.')
if source_git('rev-parse', 'HEAD') != APPROVED_COMMIT:
    r = subprocess.run(['git', 'merge-base', '--is-ancestor', 'HEAD', 'origin/dev'], cwd=ROOT, capture_output=True)
    if r.returncode:
        raise RuntimeError('Checkout diverged; no reset performed.')
    r = subprocess.run([sys.executable, 'scripts/datt.py', 'stop', '--timeout', '120'], cwd=ROOT, capture_output=True, timeout=150)
    if r.returncode:
        raise RuntimeError('Could not stop the owned service safely; source preserved.')
    source_git('switch', 'dev')
    source_git('merge', '--ff-only', 'origin/dev')
print('SOURCE_COMMIT=' + source_git('rev-parse', 'HEAD'))

# %% 2. Dependencies and frontend, preserving the installed CUDA stack
import os, sys, subprocess
from pathlib import Path
ROOT = Path('/content/DATT')
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUN_LOG_DIR = ROOT / '.datt-runtime' / 'colab-run'
RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)

def run_private(args, label, timeout=300, cwd=ROOT):
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(label + ' timed out; rerun after inspecting the private log.') from None
    path = RUN_LOG_DIR / (label + '.log')
    path.write_text(result.stdout + '\n' + result.stderr)
    path.chmod(0o600)
    if result.returncode:
        raise RuntimeError(label + ' failed; inspect ' + str(path) + ' privately.')
    print(label + '=PASS', flush=True)
    return result

run_private([sys.executable, 'scripts/colab_install.py'], 'dependencies', 3000)
for label, args in [('frontend-install', ['npm', 'ci', '--no-audit', '--no-fund']),
                    ('frontend-build', ['npm', 'run', 'build'])]:
    run_private(args, label, 600, ROOT / 'frontend')

# %% 3. Reuse existing .env; upload only when absent; load granted Secrets
import os, sys, contextlib, io
from pathlib import Path
ROOT = Path('/content/DATT')

def configure_runtime(root, upload, read_secret, load_config):
    """Rerunnable loader: existing .env is never overwritten or uploaded again."""
    root = Path(root)
    os.chdir(root)
    path = root / '.env'
    if path.exists() and not path.is_file():
        raise RuntimeError('.env must be a regular file; existing path preserved.')
    if not path.is_file():
        uploaded = upload()
        if set(uploaded) != {'.env'}:
            raise RuntimeError('Select exactly the project .env file; other files are preserved.')
        payload = uploaded['.env']
        if path.exists():
            if path.read_bytes() != payload:
                raise RuntimeError('Existing .env differs; it has been preserved.')
        else:
            # Exclusive creation also protects against a concurrent writer.
            with path.open('xb') as stream:
                stream.write(payload)
        del uploaded, payload
        path.chmod(0o600)
        print('ENV_FILE=UPLOADED')
    else:
        print('ENV_FILE=REUSED')
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    load_config()
    for name in ('DATT_AGENT_AUTH_SECRET', 'DATT_SECRET_KEY', 'DATT_STRICT_AUTH'):
        if not os.environ.get(name):
            value = read_secret(name)
            if value:
                os.environ[name] = value
    # Strict authentication is the deployment default; no key is generated.
    if not os.environ.get('DATT_STRICT_AUTH'):
        os.environ['DATT_STRICT_AUTH'] = '1'
    os.environ['DATT_REQUIRE_PERSISTENCE'] = '1'
    key = os.environ.get('DATT_AGENT_AUTH_SECRET') or os.environ.get('DATT_SECRET_KEY')
    print('SIGNING_KEY=' + ('SET' if key else 'MISSING'))
    print('CONFIG=LOADED; secret_values=WITHHELD; run preflight before startup')

from google.colab import files, userdata
from scripts.colab_startup import load_configuration

def granted_secret(name):
    try:
        return userdata.get(name)
    except (userdata.SecretNotFoundError, userdata.NotebookAccessError):
        return None

configure_runtime(ROOT, files.upload, granted_secret, load_configuration)

# %% 4. Mandatory deployment preflight; no migrations, regression suites or paid calls
import json, os, sys, subprocess, hashlib
from pathlib import Path
ROOT = Path('/content/DATT')
DEPLOYMENT = None

def require_ready(ok, message):
    if not ok:
        raise RuntimeError(message)

def cli_fields(action, timeout=120):
    r = run_private([sys.executable, 'scripts/datt.py', action, '--timeout', str(timeout)], action, timeout + 30)
    return dict(line.split('=', 1) for line in r.stdout.splitlines() if '=' in line)

def configuration_signature():
    names = sorted(k for k in os.environ if k.startswith(('DATT_', 'SUPABASE_', 'AGENT_'))
                   or k in ('GOOGLE_API_KEY', 'OPENAI_API_KEY', 'GEMINI_API_KEY'))
    return hashlib.sha256(json.dumps([(k, os.environ[k]) for k in names]).encode()).hexdigest()

source_git('fetch', 'origin', 'refs/heads/dev:refs/remotes/origin/dev')
require_ready(source_git('rev-parse', 'HEAD') == source_git('rev-parse', 'origin/dev') == APPROVED_COMMIT,
              'Source changed; review the latest dev and rerun from cell 1.')
require_ready(not source_git('status', '--porcelain'), 'Checkout changed; review before startup.')
auth_probe = '''import json
from src.agent.api.auth import validate_auth_configuration, configured_auth_secret
from src.agent.config import agent_config as c
try:
 validate_auth_configuration(); configured_auth_secret()
 print(json.dumps(dict(auth='PASS',provider=c.llm_provider,model=c.model_name,embedding_provider=c.embedding_provider)))
except RuntimeError:
 print(json.dumps(dict(auth='BLOCKED')))
'''
r = run_private([sys.executable, '-c', auth_probe], 'authentication', 120)
auth = json.loads(r.stdout.splitlines()[-1])
require_ready(auth.get('auth') == 'PASS' and os.environ.get('DATT_STRICT_AUTH') == '1',
              'Authentication blocked. Personally add your private DATT_AGENT_AUTH_SECRET (at least 32 characters) '
              'in Colab Secrets and enable notebook access, then rerun cell 3. Do not send it in chat.')
print('AGENT=' + json.dumps(auth))
db = cli_fields('db-check')
require_ready(db.get('database_connected') == 'true' and db.get('database_type') == 'postgresql'
              and db.get('pgvector') == 'PASS' and db.get('tables_verified') == 'true'
              and db.get('alembic') == 'PASS' and db.get('alembic_revision') == db.get('repository_head'),
              'Database preflight failed or schema is behind; no migration is run automatically.')
print('DATABASE=PASS; revision=' + db['alembic_revision'])
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
engine = create_engine(make_url(os.environ['DATT_DATABASE_URL']), connect_args={'connect_timeout': 15})
try:
    with engine.connect() as conn:
        missing = {'agent_conversations', 'checkpoints', 'checkpoint_blobs', 'checkpoint_writes', 'checkpoint_migrations'} - set(inspect(conn).get_table_names())
    require_ready(not missing, 'Persistent conversation tables missing; database setup requires review.')
except RuntimeError:
    raise
except Exception as exc:
    raise RuntimeError('Database inspection failed: ' + type(exc).__name__ + '; provider details withheld.') from None
finally:
    engine.dispose()
import requests
from urllib.parse import quote
try:
    key = os.environ['SUPABASE_SERVICE_ROLE_KEY']
    response = requests.get(os.environ['SUPABASE_URL'].rstrip('/') + '/storage/v1/bucket/'
                            + quote(os.environ['DATT_STORAGE_BUCKET'], safe=''),
                            headers={'Authorization': 'Bearer ' + key, 'apikey': key}, timeout=20)
except Exception as exc:
    raise RuntimeError('Storage inspection failed: ' + type(exc).__name__ + '; provider details withheld.') from None
require_ready(response.status_code == 200, 'Supabase bucket unavailable; HTTP ' + str(response.status_code))
print('STORAGE=PASS')
cli_fields('models', 600)
cv = cli_fields('cv-check', 120)
require_ready(cv.get('cv_status') == 'PASS', 'CUDA/models unavailable; select a GPU runtime and inspect private cv-check log.')
r = run_private([sys.executable, '-m', 'scripts.colab_startup', '--model-probe'], 'model-initialization', 600)
models = json.loads(r.stdout)
require_ready(models.get('models') == 'PASS' and models.get('onnx_cuda'), 'Model initialization failed.')
print('MODELS=' + json.dumps({k: models.get(k) for k in ('models', 'yolo_provider', 'scrfd_provider', 'adaface_provider', 'plate_ocr')}))
if callable(globals().get('save_model_cache')):
    save_model_cache()
DEPLOYMENT = {'commit': APPROVED_COMMIT, 'configuration': configuration_signature()}
print('PREFLIGHT=PASS; migrations=0; paid_calls=0')

# %% 5. Start/restart only the CLI-owned GPU service with the current configuration
import json, sys, subprocess, time, requests
START_READY = None
require_ready(DEPLOYMENT is not None and DEPLOYMENT['configuration'] == configuration_signature(),
              'Run configuration and preflight cells first; configuration changed.')
source_git('fetch', 'origin', 'refs/heads/dev:refs/remotes/origin/dev')
require_ready(source_git('rev-parse', 'HEAD') == source_git('rev-parse', 'origin/dev') == DEPLOYMENT['commit']
              and not source_git('status', '--porcelain'), 'Source changed after preflight; rerun from cell 1.')
owner_probe = '''import json
from src.ops import process
print(json.dumps(dict(owned=process.owned(process.state()))))'''
r = run_private([sys.executable, '-c', owner_probe], 'service-ownership', 30)
if json.loads(r.stdout)['owned']:
    cli_fields('stop', 120)
# The CLI refuses unknown listeners; it never kills or adopts them.
r = run_private([sys.executable, 'scripts/datt.py', 'start', '--mode', 'gpu', '--port', '8501', '--timeout', '300'], 'start', 340)
fields = dict(line.split('=', 1) for line in r.stdout.splitlines() if '=' in line)
require_ready(fields.get('health') == 'PASS' and fields.get('mode') == 'gpu', 'GPU backend did not become healthy.')
BASE = 'http://127.0.0.1:8501'
health = requests.get(BASE + '/healthz', timeout=20)
h = health.json()
require_ready(health.status_code == 200 and h.get('commit') == DEPLOYMENT['commit'] and h.get('mode') == 'gpu',
              'Live backend source/mode differs.')
deadline = time.monotonic() + 30
while True:
    workers = requests.get(BASE + '/startup-health', timeout=20).json()
    if all(workers.get(k) == 'RUNNING' for k in ('notification_worker', 'persistence_worker')) or time.monotonic() >= deadline:
        break
    time.sleep(1)
require_ready(all(workers.get(k) == 'RUNNING' for k in ('notification_worker', 'persistence_worker')),
              'Workers are not ready; inspect the private backend log.')
statuses = {p: requests.get(BASE + p, timeout=20).status_code for p in
            ('/api/cameras', '/api/targets', '/api/watchlist/vehicles', '/api/event_center/events', '/api/agent/conversations')}
if not all(code in (401, 403) for code in statuses.values()):
    cli_fields('stop', 120)
    raise RuntimeError('Sensitive endpoint authentication failed; owned service stopped.')
START_READY = DEPLOYMENT['commit']
print('DATT=RUNNING; GPU=PASS; strict_auth=ENABLED')
print('WORKERS=' + json.dumps(workers))

# %% 6. Open the existing authenticated Colab proxy
from google.colab import output
from IPython.display import display, HTML
from urllib.parse import urlparse
import html, requests
require_ready(START_READY == APPROVED_COMMIT, 'Start DATT successfully in cell 5 first.')
health = requests.get('http://127.0.0.1:8501/healthz', timeout=20)
require_ready(health.status_code == 200 and health.json().get('commit') == START_READY, 'Backend is no longer healthy.')
url = output.eval_js('google.colab.kernel.proxyPort(8501)')
parsed = urlparse(url)
require_ready(parsed.scheme == 'https' and parsed.hostname and parsed.hostname.endswith('.colab.dev'), 'Unexpected proxy destination.')
url = url.rstrip('/')
display(HTML('<a target="_blank" rel="noopener" href="' + html.escape(url, quote=True) + '">Mở DATT</a> · '
             '<a target="_blank" rel="noopener" href="' + html.escape(url + '/agent', quote=True) + '">Mở AI Agent</a>'))
print('UI_URL=' + url)
print('Operational data and chat require an existing authorized account token. No token was generated.')
