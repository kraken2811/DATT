# @title START DATT
# Production UI is 8501. Port 8000 is the internal AI stream, never OPEN DATT.
import contextlib, html, io, json, os, re, subprocess, sys, time
from pathlib import Path
from urllib.parse import quote, urlsplit
import psutil, requests
from dotenv import load_dotenv
from IPython.display import HTML, display

ROOT = Path('/content/DATT')
PORT, AI_PORT = 8501, 8000
COMMAND = [sys.executable, 'scripts/datt.py', 'start', '--mode', 'gpu',
           '--port', str(PORT), '--ai-port', str(AI_PORT), '--timeout', '300']
report = dict(legacy_entrypoint='src.ui.video_stream.StreamRequestHandler via app.run_pipeline',
              legacy_port=AI_PORT, production_entrypoint='src.ops.runner -> src.main -> src.ui.web_server:app',
              production_command='python scripts/datt.py start --mode gpu --port 8501 --ai-port 8000 --timeout 300',
              production_port=PORT, stale_process='NONE', stale_process_stopped='NO', backend_http=0,
              camera_management='FAIL', vision_monitor='FAIL', face_watchlist='FAIL',
              vehicle_watchlist='FAIL', event_center='FAIL', YOLO_DEVICE='UNVERIFIED',
              SCRFD_PROVIDER='UNVERIFIED', ADAFACE_DEVICE='UNVERIFIED', OCR_DEVICE='UNVERIFIED',
              START_CELL_CREATED='YES', APPLICATION_URL='', SYSTEM_READY='NO')

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def get(path, port=PORT):
    response = requests.get(f'http://127.0.0.1:{port}' + path, timeout=15)
    require(response.status_code == 200, 'HTTP check failed: ' + path)
    return response

def listeners():
    return {c.pid for c in psutil.net_connections('tcp')
            if c.status == 'LISTEN' and c.laddr.port in (PORT, AI_PORT)}

try:
    require((ROOT / 'scripts/datt.py').is_file(), 'Missing /content/DATT source')
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    with contextlib.redirect_stderr(io.StringIO()):
        load_dotenv(ROOT / '.env', override=False, interpolate=False)
    require(all(os.getenv(k) for k in ('DATT_DATABASE_URL', 'SUPABASE_URL',
                'SUPABASE_SERVICE_ROLE_KEY', 'DATT_STORAGE_BUCKET')), 'Existing persistence configuration missing')
    require(os.getenv('DATT_STORAGE_BACKEND') == 'supabase', 'Expected existing Supabase backend')
    from src.ops import process as owner
    record = owner.state()
    # Never infer process identity from a PID file or the page on port 8000 alone.
    if owner.owned(record):
        require((record['mode'], record['port'], record['ai_port']) == ('gpu', PORT, AI_PORT),
                'Owned DATT configuration differs; inspect before stopping')
        if owner.status()['health'] != 'PASS':
            report['stale_process'] = str(record['pid']) + ':unhealthy_owned_DATT'
            with owner.locked():
                owner.stop(timeout=30)
            report['stale_process_stopped'] = 'YES'
    record = owner.state()
    for pid in listeners():
        if owner.owned(record) and pid == record['pid']:
            continue  # One healthy production runner legitimately owns BOTH ports.
        require(pid is not None and pid != os.getpid(), 'Unknown listener; no process stopped')
        p = psutil.Process(pid)
        before = (p.create_time(), p.cmdline(), p.cwd())
        cmd = before[1]
        # Only a proven standalone legacy app.py --ui in this checkout is obsolete.
        scripts = [Path(a) if Path(a).is_absolute() else Path(before[2]) / a for a in cmd[1:] if a.endswith('.py')]
        legacy = (Path(before[2]).resolve() == ROOT.resolve()
                  and (ROOT / 'app.py') in [a.resolve() for a in scripts]
                  and '--ui' in cmd and 'src.ops.runner' not in cmd)
        require(legacy, 'Unrecognized port owner PID ' + str(pid) + '; left untouched')
        require('AI People Counter Monitor' in get('/', AI_PORT).text, 'Legacy identity not confirmed')
        require(before == (p.create_time(), p.cmdline(), p.cwd()), 'Process identity changed')
        report['stale_process'] = str(pid) + ':standalone_legacy_DATT'
        p.terminate()  # PID + creation time + command + checkout verified; no process-group kill.
        p.wait(timeout=30)
        report['stale_process_stopped'] = 'YES'
    # Canonical CLI is idempotent: it reuses a healthy owned GPU runner.
    # No dependency install, migration, storage-check, camera activation, or test event.
    logdir = ROOT / '.datt-runtime'
    logdir.mkdir(exist_ok=True)
    with (logdir / 'start-cell.log').open('w') as log:
        started = subprocess.run(COMMAND, cwd=ROOT, env=os.environ.copy(),
                                 stdout=log, stderr=subprocess.STDOUT, timeout=360)
    require(started.returncode == 0, 'Canonical CLI failed; inspect .datt-runtime/start-cell.log')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if owner.status()['health'] == 'PASS':
            break
        time.sleep(1)
    record = owner.state()
    require(owner.owned(record), 'Production ownership check failed')
    health = get('/healthz')
    require(health.json().get('instance') == record['token'] and health.json().get('mode') == 'gpu',
            'Health endpoint is not the owned production GPU runner')
    report['backend_http'] = health.status_code
    require(listeners() == {record['pid']}, 'Unexpected port owner')
    page = get('/')
    require(page.content == (ROOT / 'src/ui/static/index.html').read_bytes(), 'Served frontend differs from current repository')
    require('AI People Counter Monitor' not in page.text, 'Legacy frontend detected')
    for label, marker, route in (
        ('camera_management', 'cameraManagementScreen', '/api/cameras'),
        ('vision_monitor', 'monitoringScreen', '/api/source_status'),
        ('face_watchlist', 'paneFaceWatchlist', '/api/targets'),
        ('vehicle_watchlist', 'paneVehicleWatchlist', '/api/watchlist/vehicles'),
        ('event_center', 'eventCenterScreen', '/api/event_center/events')):
        require('id="' + marker + '"' in page.text, 'Missing frontend: ' + label)
        body = get(route).json()
        require(isinstance(body, dict) and body.get('status') not in ('error', 'failed'), 'API failed: ' + label)
        report[label] = 'PASS'
    workers = get('/startup-health').json()
    require(all(workers.get(k) == 'RUNNING' for k in ('notification_worker', 'persistence_worker')),
            'Production worker not running')
    # Read-only persistence checks. No migrations, probe objects, or business writes.
    from src.db.database import Database
    from sqlalchemy import text
    db = Database()
    try:
        require(db.engine.dialect.name == 'postgresql', 'PostgreSQL required')
        with db.engine.connect() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            require(connection.scalar(text('SELECT 1')) == 1, 'Database unavailable')
    finally:
        db.dispose()
    from src.storage import get_storage, SupabaseStorageBackend
    storage = get_storage()
    require(isinstance(storage, SupabaseStorageBackend), 'Production storage adapter mismatch')
    bucket_url = os.environ['SUPABASE_URL'].rstrip('/') + '/storage/v1/bucket/' + quote(os.environ['DATT_STORAGE_BUCKET'], safe='')
    with requests.get(bucket_url, headers=storage.headers, timeout=20, allow_redirects=False) as response:
        require(response.status_code == 200, 'Storage read-only bucket check failed')
    # Lazy face/OCR models have no live device endpoint. Verify the unchanged
    # production classes in an isolated child; do not activate a camera to test them.
    probe_code = '''
import contextlib, io, json
with contextlib.redirect_stdout(io.StringIO()):
    import config
    from src.detector.yolo_detector import YOLODetector
    from src.face.face_embedder import FaceEmbedder
    from src.face.adaptive_pipeline import AdaptiveFacePipeline
    from src.ocr.plate_reader import LicensePlateReader
    y = YOLODetector(config); y.warmup()
    s = FaceEmbedder.get_instance(); assert s.initialize()
    a = AdaptiveFacePipeline().embedder; assert a.initialize()
    o = LicensePlateReader.get_instance(); assert o.initialize()
    result = dict(YOLO_DEVICE=str(y.device), SCRFD_PROVIDER=s.execution_provider,
                  ADAFACE_DEVICE=a.execution_provider, OCR_DEVICE=o.device)
print(json.dumps(result))
'''
    devices = subprocess.run([sys.executable, '-c', probe_code], cwd=ROOT,
                             env=os.environ.copy(), capture_output=True, text=True, timeout=180)
    (logdir / 'start-cell-devices.log').write_text(devices.stderr, encoding='utf-8')
    require(devices.returncode == 0, 'Production model device probe failed')
    report.update(json.loads(devices.stdout))
    require(report['YOLO_DEVICE'].startswith('cuda') and report['SCRFD_PROVIDER'] == 'CUDAExecutionProvider'
            and report['ADAFACE_DEVICE'] == 'CUDAExecutionProvider' and report['OCR_DEVICE'] == 'CUDA',
            'GPU model verification failed')
    print('DEVICE_VERIFICATION=production classes in isolated subprocess; lazy live sessions are not introspected')
    telemetry = get('/telemetry').json()
    print('LIVE_TELEMETRY_DEVICE=' + str(telemetry.get('device')) + '; status=' + str(telemetry.get('status')))
    print('production_pid=' + str(record['pid']) + '; notification_worker=RUNNING; persistence_worker=RUNNING')
    from google.colab import output
    url = output.eval_js('google.colab.kernel.proxyPort(8501)')
    parsed = urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname and parsed.hostname.startswith('8501-')
            and parsed.hostname.endswith('.colab.dev'), 'Unexpected Colab proxy URL')
    report['APPLICATION_URL'] = url
    report['SYSTEM_READY'] = 'YES'
except Exception as exc:
    print('STARTUP_BLOCKER=' + (str(exc) if type(exc) is RuntimeError else type(exc).__name__))
finally:
    print('[DATT_STARTUP_FIX]')
    for key, value in report.items():
        print(str(key) + '=' + str(value))
if report['SYSTEM_READY'] == 'YES':
    display(HTML('<a target="_blank" rel="noopener noreferrer" style="display:inline-block;padding:14px 24px;background:#12674a;color:white;border-radius:8px;font-weight:bold" href="'
                 + html.escape(report['APPLICATION_URL'], quote=True) + '">OPEN DATT</a>'))
else:
    raise RuntimeError('DATT startup verification incomplete; see the report above.')
