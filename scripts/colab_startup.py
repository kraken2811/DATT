"""Ordered Colab startup orchestration; business behavior stays in DATT modules/CLI."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('DATT_DATABASE_URL', 'DATT_STORAGE_BACKEND', 'SUPABASE_URL',
            'SUPABASE_SERVICE_ROLE_KEY', 'DATT_STORAGE_BUCKET')
EMAIL = ('DATT_EMAIL_HOST', 'DATT_EMAIL_PORT', 'DATT_EMAIL_USERNAME', 'DATT_EMAIL_PASSWORD',
         'DATT_EMAIL_FROM', 'DATT_EMAIL_TO', 'DATT_EMAIL_TLS', 'DATT_NOTIFICATION_COOLDOWN_SECONDS',
         'DATT_NOTIFICATION_MAX_RETRIES', 'DATT_NOTIFICATION_RETRY_SECONDS')


class Blocker(RuntimeError):
    """Only static, credential-free messages may be placed in this exception."""


def require(ok, message):
    if not ok:
        raise Blocker(message)


def install_uploaded_env(source, destination=None):
    """Accept an uploaded environment file without copying it onto itself."""
    source = Path(source).resolve()
    destination = Path(destination if destination is not None else ROOT / '.env').resolve()
    if source != destination and not (destination.exists() and source.samefile(destination)):
        shutil.copy2(source, destination)
    return destination


def load_configuration():
    """Precedence: .env, existing environment, then granted Colab Secrets."""
    from dotenv import load_dotenv
    from src.notifications.config import EmailConfig, NAMES, load_colab_secrets
    with contextlib.redirect_stderr(io.StringIO()):
        load_dotenv(ROOT / '.env', override=True, interpolate=False)
    try:
        from google.colab import userdata
    except ImportError:
        userdata = None
    for name in REQUIRED:
        if not os.getenv(name) and userdata is not None:
            try:
                value = userdata.get(name)
                if value:
                    os.environ[name] = value
            except Exception:
                pass
    load_colab_secrets()
    for name in REQUIRED + EMAIL:
        print(name + '=' + ('SET' if os.getenv(name) else 'MISSING'))
    missing = [name for name in REQUIRED if not os.getenv(name)]
    require(not missing, 'Missing required configuration: ' + ', '.join(missing))
    require(os.getenv('DATT_STORAGE_BACKEND') == 'supabase', 'Expected DATT_STORAGE_BACKEND=supabase')
    missing_email = [name for name in NAMES if not os.getenv(name)]
    require(not missing_email, 'Missing required email configuration: ' + ', '.join(missing_email))
    require(EmailConfig.from_env().configured,
            'Invalid email configuration; check DATT_EMAIL_HOST, DATT_EMAIL_PORT, DATT_EMAIL_USERNAME, '
            'DATT_EMAIL_FROM, DATT_EMAIL_TO, DATT_EMAIL_TLS and DATT_NOTIFICATION_* values')
    os.environ['DATT_REQUIRE_PERSISTENCE'] = '1'
    print('email_configuration=PASS; omitted optional settings use project defaults')


def model_probe():
    # A disposable subprocess owns these instances and releases VRAM on exit.
    import config
    from src.detector.yolo_detector import YOLODetector
    from src.face.face_embedder import FaceEmbedder
    from src.face.adaptive_pipeline import AdaptiveFacePipeline
    from src.ocr.plate_detector import PlateDetector
    from src.ocr.plate_reader import LicensePlateReader
    yolo = YOLODetector(config)
    yolo.warmup()
    require('cuda' in str(yolo.device).lower(), 'YOLO did not initialize on CUDA')
    face = FaceEmbedder.get_instance()
    require(face.initialize(), 'Production face detector initialization failed')
    require(face.execution_provider == 'CUDAExecutionProvider', 'Face detector CUDA provider unavailable')
    pipeline = AdaptiveFacePipeline()
    if not pipeline.embedder.initialize():
        # Keep the public blocker credential-free while distinguishing a missing
        # file from an ONNX/runtime initialization failure in the private log.
        model_path = getattr(pipeline.embedder, 'model_path', None)
        if model_path is not None and not Path(model_path).is_file():
            raise Blocker('Production face embedding model missing; expected models/face/adaface_ir50_ms1mv2.onnx. Rerun Cell 6 and upload datt-colab-models.zip')
        raise Blocker('Production face embedding model failed to initialize; inspect the private runtime log for the AdaFace/ONNX error')
    require(pipeline.embedder.execution_provider == 'CUDAExecutionProvider', 'Face embedding CUDA provider unavailable')
    require(PlateDetector.get_instance().is_available, 'Production plate model failed to initialize')
    reader = LicensePlateReader.get_instance()
    require(reader.initialize() and reader.device == 'CUDA', 'Production OCR failed to initialize on CUDA')
    return {
        'models': 'PASS', 'yolo': 'PASS', 'face': 'PASS', 'plate_ocr': 'PASS', 'onnx_cuda': True,
        'yolo_provider': str(yolo.device),
        'scrfd_provider': face.execution_provider,
        'adaface_provider': pipeline.embedder.execution_provider,
    }


AGENT_ENDPOINTS = {
    '/api/agent/chat': {'post'},
    '/api/agent/conversations/{thread_id}': {'get', 'delete'},
}


def agent_routes_present(schema):
    paths = schema.get('paths', {})
    return all(methods <= paths.get(path, {}).keys() for path, methods in AGENT_ENDPOINTS.items())


class Startup:
    def __init__(self, runtime):
        self.report = dict(runtime, source='PASS', environment='NOT_CHECKED')
        self.completed = 2
        self.failed = False
        self.report['commit'] = self.git_commit()

    @staticmethod
    def git_commit():
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else 'unavailable'

    def cli(self, action, *, timeout=120, allow_failure=False, **options):
        cmd = [sys.executable, str(ROOT / 'scripts/datt.py'), action, '--timeout', str(timeout)]
        for key, value in options.items():
            cmd += ['--' + key.replace('_', '-'), str(value)]
        from src.ops.subprocesses import run_bounded
        r = run_bounded(cmd, cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True, timeout=timeout + 30)
        # CLI fields are explicitly constructed/redacted. Never print stderr/logs.
        values = {}
        for line in r.stdout.splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                values[k] = v
        require(allow_failure or r.returncode == 0, action + ' failed: ' + values.get('error', 'check reported failure'))
        return values

    def run(self, number):
        require(not self.failed, 'Earlier cell failed; correct the blocker and rerun from Cell 1')
        require(number == self.completed + 1, 'Run startup cells in order from Cell 1')
        try:
            getattr(self, 'cell_' + str(number))()
        except Exception as exc:
            self.failed = True
            self.report['SYSTEM_READY'] = 'NO'
            from src.db.migration_head import MigrationHeadError
            message = str(exc) if isinstance(exc, (Blocker, MigrationHeadError)) else 'Cell ' + str(number) + ': ' + type(exc).__name__ + ' (provider details withheld)'
            print('SYSTEM_READY=NO\nblocker=' + message)
            raise Blocker(message) from None
        self.completed = number

    def cell_3(self):
        from scripts.colab_install import plan
        from src.ops import process
        missing, _ = plan()
        if missing and process.owned(process.state()):
            self.cli('stop', timeout=120)
            print('owned_backend_stopped_for_missing_dependencies=true')
        from scripts.colab_install import main
        try:
            self.report.update(main())
        except RuntimeError as exc:
            raise Blocker(str(exc)) from None
        from src.ops.subprocesses import run_bounded
        result = run_bounded([sys.executable, '-m', 'scripts.agent_smoke'], cwd=ROOT,
                             env=os.environ.copy(), capture_output=True, text=True, timeout=120)
        require(result.returncode == 0, 'Isolated MockChatModel API smoke failed; run python -m scripts.agent_smoke')
        self.report['agent_mock_api'] = 'PASS'
        print('agent_mock_api=PASS; real_llm_calls=0')
        print('dependencies=PASS; dependencies_reused=' + str(self.report['dependencies_reused']).lower())

    def cell_4(self):
        load_configuration()
        self.report['environment'] = 'PASS'

    def cell_5(self):
        from src.db.migration_head import repository_head
        self.report['expected_head'] = repository_head()
        db = self.cli('db-check', allow_failure=True)
        require(db.get('database_connected') == 'true' and db.get('database_type') == 'postgresql', 'PostgreSQL connection failed; check DATT_DATABASE_URL, DNS, TLS and database permissions')
        require(db.get('pgvector') == 'PASS', 'pgvector extension missing; provision it before startup')
        self.report.update(database='PASS', pgvector='PASS')
        for k in ('postgresql_version', 'pgvector_version', 'alembic_revision'):
            print(k + '=' + db.get(k, 'unknown'))
        print('expected_migration_head=' + self.report['expected_head'])
        # A behind-head database is allowed here: Cell 7 runs the existing migration.
        storage = self.cli('storage-check')
        require(storage.get('storage_connected') == 'true' and storage.get('storage_cleanup') == 'PASS', 'Supabase upload/read/delete or temporary-object cleanup failed')
        self.report['storage'] = 'PASS'
        print('database=PASS; pgvector=PASS; storage_upload_read_delete=PASS')

    def cell_6(self):
        self.cli('models', timeout=600)
        check = self.cli('cv-check')
        require(check.get('cv_status') == 'PASS', 'GPU provider or model files failed cv-check')
        from src.ops.subprocesses import run_bounded
        r = run_bounded([sys.executable, '-m', 'scripts.colab_startup', '--model-probe'], cwd=ROOT,
                        env=os.environ.copy(), capture_output=True, text=True, timeout=600)
        try:
            result = json.loads(r.stdout)
        except ValueError:
            raise Blocker('Production model probe failed; no valid diagnostic result') from None
        require(r.returncode == 0, result.get('blocker', 'Production model initialization failed'))
        self.report.update(result)
        print('models=PASS; YOLO=' + self.report['yolo_provider']
              + '; SCRFD=' + self.report['scrfd_provider']
              + '; AdaFace=' + self.report['adaface_provider'] + '; plate_ocr=PASS')

    def cell_7(self):
        from src.db.migration_head import repository_head
        require(self.report['expected_head'] == repository_head(),
                'Repository migration head changed during startup; rerun from Cell 1')
        db = self.cli('migrate')
        require(db.get('alembic') == 'PASS' and db.get('alembic_revision') == self.report['expected_head'], 'Migration did not reach repository head')
        self.report['migration'] = db['alembic_revision']
        print('migration=' + db['alembic_revision'])

    def cell_8(self):
        from src.ops import process
        status = process.status()
        if status['health'] == 'PASS':
            require(status['mode'] == 'gpu' and status['port'] == 8501, 'Healthy backend configuration differs; resolve through DATT CLI')
            require(process.owned(process.state()), 'Backend ownership changed; no process stopped')
            workers = self.get('/startup-health').json()
            health = self.get('/healthz').json()
            revision_ok = (health.get('commit') == self.report['commit']
                           and health.get('application_module') == 'src.ui.web_server')
            schema_ok = agent_routes_present(self.get('/openapi.json').json())
            print('backend_revision_match=' + str(revision_ok).lower())
            print('backend_agent_routes_present=' + str(schema_ok).lower())
            if not revision_ok or not schema_ok:
                self.cli('stop', timeout=120)
                print('owned_backend_stopped_for_stale_revision_or_routes=true')
            elif workers.get('notification_worker') != 'RUNNING':
                from src.notifications.config import EmailConfig
                require(EmailConfig.from_env().configured, 'Valid email configuration required before restarting backend')
                self.cli('stop', timeout=120)
                print('owned_backend_restarted_for_notification_configuration=true')
            else:
                print('healthy_backend_reused=true')
        elif process.owned(process.state()):
            self.cli('stop', timeout=120)
            print('stale_owned_backend_stopped=true')
        # Unknown listeners are never killed or adopted.
        import psutil
        record = process.state()
        for conn in psutil.net_connections('tcp'):
            if conn.status == 'LISTEN' and conn.laddr.port in (8000, 8501):
                require(process.owned(record) and conn.pid == record['pid'], 'DATT port occupied by an unverified process; resolve ownership before startup')

    def cell_9(self):
        from src.ops import process
        if process.status()['health'] != 'PASS':
            self.cli('start', mode='gpu', timeout=300)
        require(process.status()['health'] == 'PASS', 'CLI backend failed startup')
        print('backend=RUNNING')

    def get(self, path, port=8501):
        import requests
        r = requests.get(f'http://127.0.0.1:{port}' + path, timeout=20)
        require(r.status_code == 200, 'HTTP check failed: ' + path + ' status=' + str(r.status_code))
        return r

    def cell_10(self):
        from src.ops import process
        import psutil
        status = process.status()
        record = process.state()
        require(status['health'] == 'PASS' and status['mode'] == 'gpu', 'Backend ownership/health/GPU mode failed')
        listeners = {c.pid for c in psutil.net_connections('tcp') if c.status == 'LISTEN' and c.laddr.port == 8501}
        require(listeners == {record['pid']}, 'Expected exactly one CLI-owned backend listener')
        runners = []
        for candidate in psutil.process_iter(['pid', 'cmdline', 'cwd']):
            info = candidate.info
            if ('src.ops.runner' in (info.get('cmdline') or [])
                    and info.get('cwd') and Path(info['cwd']).resolve() == ROOT.resolve()):
                runners.append(info['pid'])
        require(runners == [record['pid']], 'More than one DATT runner exists in this project')
        db, storage = self.cli('db-check'), self.cli('storage-check')
        require(db.get('database_connected') == 'true' and db.get('alembic') == 'PASS', 'Database health failed')
        require(storage.get('storage_connected') == 'true' and storage.get('storage_cleanup') == 'PASS', 'Storage health/cleanup failed')
        gpu = self.cli('gpu-check')
        require(gpu.get('cuda_available') == 'true', 'CUDA health failed')
        response = self.get('/startup-health').json()
        require(response.get('persistence_worker') == 'RUNNING', 'Database persistence worker is not running')
        worker = response.get('notification_worker', 'UNKNOWN')
        self.report['notification_worker'] = worker
        require(worker == 'RUNNING', 'Notification worker is not running; configure email before starting the CLI backend')
        self.report.update(backend='PASS', backend_pid=record['pid'], backend_http=200)
        print('backend_http=200; single_backend=true; database=PASS; storage=PASS; notification_worker=' + worker)

    def cell_11(self):
        self.get('/')
        self.report['ui_url'] = 'http://127.0.0.1:8501'
        print('local_backend_ui_url=' + self.report['ui_url'])
        try:
            from google.colab.output import eval_js
            url = eval_js('google.colab.kernel.proxyPort(8501)')
            from urllib.parse import urlsplit
            parsed = urlsplit(url)
            if parsed.scheme == 'https' and parsed.hostname and parsed.hostname.endswith('.colab.dev') and not parsed.username and not parsed.query:
                self.report['ui_url'] = url
                print('colab_ui_url=' + url)
        except Exception:
            print('colab_ui_url=unavailable; use the existing Colab port preview')

    def cell_12(self):
        routes = {'camera_api': '/api/cameras', 'camera_selection_api': '/api/video_sources',
                  'monitoring_api': '/api/source_status', 'face_watchlist_api': '/api/targets',
                  'vehicle_watchlist_api': '/api/watchlist/vehicles', 'event_center_api': '/api/event_center/events'}
        for label, path in routes.items():
            body = self.get(path).json()
            require(isinstance(body, dict) and body.get('status') not in ('error', 'failed'), 'API response reported failure: ' + path)
            self.report[label] = 'PASS'
            print(label + '=PASS')
        require(agent_routes_present(self.get('/openapi.json').json()),
                'Agent endpoints missing from live OpenAPI; check revision, module and API base URL')
        health = self.get('/healthz').json()
        require(health.get('commit') == self.report['commit'] and
                health.get('application_module') == 'src.ui.web_server',
                'Live backend revision/module differs from deployed source')
        import requests
        from uuid import uuid4
        with requests.Session() as client:
            from src.agent.api.auth import create_auth_token
            client.headers['Authorization'] = 'Bearer ' + create_auth_token('colab_smoke_' + uuid4().hex)
            history = client.get('http://127.0.0.1:8501/api/agent/conversations/colab_smoke_' + uuid4().hex, timeout=20)
            require(history.status_code == 200 and history.json().get('messages') == [],
                    'Agent conversation retrieval failed')
            invalid = client.post('http://127.0.0.1:8501/api/agent/chat', json={'message': ''}, timeout=20)
            require(invalid.status_code == 422, 'Agent chat validation failed')
        self.report['agent_live_api'] = 'PASS'
        print('agent_live_api=PASS; schema=POST chat,GET/DELETE conversation; real_llm_calls=0')
        self.get('/telemetry', port=8000)
        self.report['smoke_tests'] = 'PASS'

    def cell_13(self):
        # Revalidate liveness instead of reporting a backend that died after Cell 10.
        self.cell_10()
        fields = ('runtime', 'gpu', 'cuda', 'source', 'commit', 'environment', 'database', 'pgvector',
                  'migration', 'storage', 'models', 'yolo_provider', 'scrfd_provider', 'adaface_provider',
                  'backend', 'backend_pid', 'backend_http', 'agent_mock_api', 'agent_live_api', 'camera_api',
                  'face_watchlist_api', 'vehicle_watchlist_api', 'event_center_api', 'notification_worker', 'ui_url')
        require(all(k in self.report for k in fields) and self.report.get('smoke_tests') == 'PASS', 'Startup report is incomplete')
        print('[DATT_COLAB_STARTUP]')
        for k in fields:
            print(k + '=' + str(self.report[k]))
        self.report['SYSTEM_READY'] = 'YES'
        print('SYSTEM_READY=YES')


if __name__ == '__main__':
    # Native libraries may write directly to stdout/stderr; suppress at FD level.
    saved = os.dup(1)
    with open(os.devnull, 'w') as sink:
        os.dup2(sink.fileno(), 1)
        os.dup2(sink.fileno(), 2)
        try:
            result = model_probe()
            code = 0
        except Exception as exc:
            result = {'blocker': str(exc) if isinstance(exc, Blocker) else 'Model probe: ' + type(exc).__name__}
            code = 1
        sys.stdout.flush()
    os.dup2(saved, 1)
    os.close(saved)
    print(json.dumps(result), flush=True)
    raise SystemExit(code)
