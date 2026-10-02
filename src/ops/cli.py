import argparse
import contextlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tempfile
from uuid import uuid4

from .config import ROOT, environment, load_configuration, runtime_dir
from .subprocesses import run_bounded

COMMANDS = ['doctor', 'bootstrap', 'migrate', 'storage-check', 'db-check', 'start',
            'stop', 'restart', 'status', 'test', 'e2e', 'gpu-check', 'cv-check', 'models']


def report(title, result):
    print('[' + title + ']', flush=True)
    for key, value in result.items():
        print(f'{key}={str(value).lower() if isinstance(value, bool) else value}', flush=True)


def worker(action, identity=None):
    from . import checks
    if action == 'test-environment':
        import imageio_ffmpeg
        return {'ffmpeg': imageio_ffmpeg.get_ffmpeg_exe()}
    actions = {'dependencies': checks.dependencies_check, 'db-check': checks.database_check, 'storage-check': checks.storage_check,
               'migrate': checks.migrate, 'gpu-check': checks.gpu_check, 'cv-check': checks.cv_check}
    if action.startswith('fixture-'):
        return checks.fixture(action.split('-', 1)[1], identity)
    if action == 'models':
        import shutil
        from pathlib import Path
        from ultralytics.utils.downloads import attempt_download_asset
        from huggingface_hub import hf_hub_download
        models = ROOT / 'models'
        models.mkdir(exist_ok=True)
        for name, download in (
            ('yolo11s.pt', lambda: attempt_download_asset('yolo11s.pt')),
            ('yolov8n-license-plate.pt', lambda: hf_hub_download(repo_id='joker5914/yolov8n-license-plate', filename='best.pt'))):
            target = models / name
            if not target.exists() or not target.stat().st_size:
                source = Path(download())
                if source.resolve() != target.resolve():
                    shutil.copy2(source, target)
        return {'models': 'PASS'}
    return actions[action]()


def bounded(action, timeout=60, identity=None):
    """Bound whole operations, including third-party connection/download retries."""
    print('checking=' + action, flush=True)
    command = [sys.executable, '-u', str(ROOT / 'scripts/datt.py'), action, '--worker']
    if identity:
        command += ['--identity', identity]
    try:
        child = run_bounded(command, cwd=ROOT, env=os.environ.copy(),
                               capture_output=True, text=True, timeout=timeout)
        # Worker emits only a sanitized JSON object, including on import failures.
        return json.loads(child.stdout)
    except subprocess.TimeoutExpired:
        return {'error': action + ':TIMEOUT'}
    except (ValueError, OSError):
        return {'error': action + ':WORKER_FAILED'}


def db_ok(result, persistent=False):
    return bool(result.get('database_connected') and result.get('tables_verified')
                and result.get('alembic') == 'PASS' and (not persistent or
                result.get('database_type') == 'postgresql' and result.get('pgvector') == 'PASS'))


def git_value(*args):
    try:
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def doctor(timeout):
    from .process import status
    db = bounded('db-check', timeout)
    storage = bounded('storage-check', timeout)
    gpu = bounded('gpu-check', timeout)
    cv = bounded('cv-check', timeout) if gpu.get('gpu_available') else {'cv_status': 'SKIPPED_GPU_NOT_AVAILABLE'}
    dependencies = all(importlib.util.find_spec(name) for name in
                       ('sqlalchemy', 'alembic', 'requests', 'psutil', 'fastapi', 'uvicorn', 'cv2', 'httpx'))
    backend = status()
    ready = dependencies and db_ok(db, persistent=db.get('database_type') == 'postgresql') and storage.get('storage_connected', False)
    result = dict(environment=environment(), python=platform.python_version(),
                  git_branch=git_value('branch', '--show-current'), git_commit=git_value('rev-parse', 'HEAD'),
                  gpu_available=False, gpu_name='none', cuda_available=False,
                  database_configured=bool(os.getenv('DATT_DATABASE_URL')), database_connected=False,
                  database_type='unknown', pgvector_version='unknown', alembic_revision='unknown',
                  storage_backend=os.getenv('DATT_STORAGE_BACKEND', 'local'), storage_configured=False,
                  storage_connected=False)
    for label, values in [('database', db), ('storage', storage), ('gpu', gpu)]:
        result.update({k: v for k, v in values.items() if k != 'error'})
        if 'error' in values:
            result[label + '_error'] = values['error']
    result.update(backend_status=backend['status'], backend_port=backend['port'],
                  cv_status=cv.get('cv_status', 'FAIL'),
                  ready_for_local=bool(ready), ready_for_gpu=bool(ready and cv.get('cv_status') == 'PASS'))
    report('DATT_DOCTOR', result)
    return result


def e2e(args):
    from . import process
    result = dict(environment=environment(), gpu='unknown', database_connected=False,
                  pgvector='FAIL', alembic='FAIL', storage_connected=False, storage_upload='FAIL',
                  storage_read='FAIL', backend_start='FAIL', backend_http=0, video_sources_api='FAIL',
                  backend_restart='FAIL', database_after_restart='FAIL', media_after_restart='FAIL',
                  cleanup='NOT_NEEDED', PERSISTENCE_STATUS='FAIL')
    identity = str(uuid4())
    fixture_attempted = False
    stage = 'environment'
    try:
        gpu = bounded('gpu-check', args.timeout)
        result['gpu'] = gpu.get('gpu_name', 'unknown')
        if args.mode == 'gpu' and not gpu.get('gpu_available'):
            result['cv_status'] = 'SKIPPED_GPU_NOT_AVAILABLE'
            args.mode = 'api'
        stage = 'database_migration'
        db = bounded('migrate', args.timeout)
        for key in ('database_connected', 'pgvector', 'alembic'):
            result[key] = db.get(key, result[key])
        if not db_ok(db, persistent=not args.allow_local):
            raise RuntimeError('database_preflight')
        if not args.allow_local and os.getenv('DATT_STORAGE_BACKEND') not in ('supabase', 'external'):
            raise RuntimeError('remote_storage_required')
        stage = 'storage'
        storage = bounded('storage-check', args.timeout)
        for key in ('storage_connected', 'storage_upload', 'storage_read'):
            result[key] = storage.get(key, result[key])
        if not storage.get('storage_connected') or storage.get('storage_cleanup') != 'PASS':
            raise RuntimeError('storage_preflight')
        with process.locked():
            stage = 'backend_start'
            backend = process.start(args.mode, args.port, args.ai_port, args.timeout)
            result['backend_http'] = backend['http_status']
            if backend['health'] != 'PASS':
                raise RuntimeError('backend_health')
            result['backend_start'] = 'PASS'
            stage = 'video_sources_api'
            if process.http(args.port, '/api/video_sources') != 200:
                raise RuntimeError('video_sources_api')
            result['video_sources_api'] = 'PASS'
            fixture_attempted = True
            stage = 'fixture_create'
            if bounded('fixture-create', args.timeout, identity).get('fixture_create') != 'PASS':
                raise RuntimeError('fixture_create')
            old = process.state()
            stage = 'backend_restart'
            backend = process.restart(timeout=args.timeout)
            if backend['health'] != 'PASS' or old['token'] == process.state()['token']:
                raise RuntimeError('restart')
            result['backend_restart'] = 'PASS'
            if process.http(backend['port'], '/api/video_sources') != 200:
                raise RuntimeError('api_after_restart')
            stage = 'persistence_reload'
            verified = bounded('fixture-verify', args.timeout, identity)
            if verified.get('fixture_verify') != 'PASS':
                raise RuntimeError('fixture_reload')
            result['database_after_restart'] = result['media_after_restart'] = 'PASS'
            result['PERSISTENCE_STATUS'] = 'PASS'
    except Exception as exc:
        result['error'] = type(exc).__name__
        result['failed_stage'] = stage
    finally:
        if fixture_attempted:
            cleanup = bounded('fixture-cleanup', args.timeout, identity)
            result['cleanup'] = cleanup.get('fixture_cleanup', 'FAIL')
            if result['cleanup'] != 'PASS':
                result['PERSISTENCE_STATUS'] = 'FAIL'
                result['retained_fixture_id'] = identity
        result['scope'] = 'local_development' if args.allow_local else 'external_persistence'
        report('DATT_CLI_E2E', result)
    return int(result['PERSISTENCE_STATUS'] != 'PASS')


def main(argv=None):
    parser = argparse.ArgumentParser(description='DATT operations; API mode never initializes CV models.')
    parser.add_argument('command', metavar='command', help=', '.join(COMMANDS),
                        choices=COMMANDS + ['test-environment', 'dependencies', 'fixture-create', 'fixture-verify', 'fixture-cleanup'])
    parser.add_argument('--mode', choices=['api', 'cpu', 'gpu'], default='api',
                        help='api: data management only; cpu/gpu: full video processing runtime')
    parser.add_argument('--port', type=int, default=8501)
    parser.add_argument('--ai-port', type=int, default=8000)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--allow-local', action='store_true', help='Allow SQLite/local storage in E2E; never claim external persistence')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--identity', help=argparse.SUPPRESS)
    parser.add_argument('--suite', choices=['unit', 'all'], default='unit')
    args = parser.parse_args(argv)
    if args.command not in COMMANDS and not args.worker:
        parser.error('internal operation')
    if args.timeout <= 0 or not 1 <= args.port <= 65535 or not 1 <= args.ai_port <= 65535:
        parser.error('timeout and ports must be positive and valid')
    if args.worker:
        # Suppress third-party logs/tracebacks; return only fields we construct.
        try:
            with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                result = worker(args.command, args.identity)
        except Exception as exc:
            result = {'error': args.command + ':' + type(exc).__name__}
        print(json.dumps(result), flush=True)
        return int('error' in result)
    try:
        load_configuration()
        os.chdir(ROOT)
        if args.command == 'doctor':
            return int(not doctor(args.timeout)['ready_for_local'])
        if args.command == 'e2e':
            return e2e(args)
        if args.command == 'test':
            paths = ['tests'] if args.suite == 'all' else [
                'tests/test_cli.py', 'tests/test_db.py', 'tests/test_video_sources.py',
                'tests/test_persistent_storage.py', 'tests/test_supabase_storage.py']
            # No inherited production credentials; tests opt into their own fixtures.
            env = {k: v for k, v in os.environ.items() if not k.startswith(('DATT_', 'SUPABASE_'))}
            env['DATT_REQUIRE_PERSISTENCE'] = '0'
            # Resolve the installed binary before tests mock subprocess.Popen.
            tooling = bounded('test-environment', min(args.timeout, 20))
            if tooling.get('ffmpeg'):
                env['IMAGEIO_FFMPEG_EXE'] = tooling['ffmpeg']
            with tempfile.TemporaryDirectory(prefix='datt-tests-', ignore_cleanup_errors=True) as temp:
                env['DATT_DATABASE_URL'] = 'sqlite:///' + temp.replace('\\', '/') + '/tests.db'
                env['DATT_STORAGE_BACKEND'] = 'local'
                env['DATT_STORAGE_ROOT'] = temp
                return run_bounded([sys.executable, '-m', 'pytest', *paths, '-q', '--tb=short'], cwd=ROOT,
                                      env=env, timeout=args.timeout).returncode
        if args.command in ('start', 'stop', 'restart', 'status'):
            from . import process
            if args.command in ('start', 'restart') and args.mode == 'gpu':
                cv = bounded('cv-check', args.timeout)
                if cv.get('cv_status') == 'SKIPPED_GPU_NOT_AVAILABLE':
                    report('DATT_CV', cv)
                    return 0
                if cv.get('cv_status') != 'PASS':
                    report('DATT_CV', cv)
                    return 1
            if args.command == 'status':
                result = process.status()
            else:
                with process.locked():
                    if args.command == 'stop':
                        result = process.stop(args.timeout)
                    else:
                        result = getattr(process, args.command)(args.mode, args.port, args.ai_port, args.timeout)
            report('DATT_BACKEND', result)
            return int(args.command != 'stop' and result['health'] != 'PASS')
        if args.command == 'bootstrap':
            runtime_dir()
            for path in ('data/uploads/videos', 'data/uploads/targets', 'data/events', 'models'):
                (ROOT / path).mkdir(parents=True, exist_ok=True)
            dependencies = bounded('dependencies', args.timeout)
            migration = bounded('migrate', args.timeout)
            storage = bounded('storage-check', args.timeout)
            cv = bounded('cv-check', args.timeout) if args.mode == 'gpu' else {'cv_status': 'SKIPPED_API_MODE'}
            success = (dependencies.get('dependencies_ready') and dependencies.get('config_files_ready')
                       and db_ok(migration, persistent=migration.get('database_type') == 'postgresql')
                       and storage.get('storage_connected') and storage.get('storage_cleanup') == 'PASS'
                       and cv.get('cv_status') in ('PASS', 'SKIPPED_API_MODE', 'SKIPPED_GPU_NOT_AVAILABLE'))
            report('DATT_BOOTSTRAP', {**dependencies, **migration, **storage, **cv, 'bootstrap': 'PASS' if success else 'FAIL'})
            return int(not success)
        result = bounded(args.command, args.timeout, args.identity)
        report('DATT_' + args.command.replace('-', '_').upper(), result)
        if args.command in ('db-check', 'migrate'):
            return int(not db_ok(result, persistent=result.get('database_type') == 'postgresql'))
        if args.command == 'storage-check':
            return int(not result.get('storage_connected') or result.get('storage_cleanup') != 'PASS')
        return int('error' in result or result.get('cv_status') == 'FAIL')
    except Exception as exc:
        report('DATT_ERROR', {'command': args.command, 'error': type(exc).__name__})
        return 1
