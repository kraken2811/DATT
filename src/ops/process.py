"""Own only processes whose PID, creation time, command and random token match."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from uuid import uuid4

from .config import ROOT, runtime_dir


@contextmanager
def locked():
    # OS releases this lock even if the CLI crashes; no stale lock deletion race.
    with (runtime_dir() / 'operation.lock').open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            if not stream.read(1):
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def state():
    try:
        return json.loads((runtime_dir() / 'backend.json').read_text())
    except FileNotFoundError:
        return None


def owned(record):
    if not record:
        return False
    import psutil
    try:
        process = psutil.Process(record['pid'])
        cmd = process.cmdline()
        return (abs(process.create_time() - record['created']) < .01
                and 'src.ops.runner' in cmd and record['token'] in cmd
                and process.status() != psutil.STATUS_ZOMBIE)
    except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
        return False


def http(port, path='/healthz', token=None):
    import requests
    try:
        r = requests.get(f'http://127.0.0.1:{port}{path}', timeout=2)
        if token and (r.status_code != 200 or r.json().get('instance') != token):
            return 0
        if path == '/api/video_sources' and r.status_code == 200 and r.json().get('status') != 'ok':
            return 0
        return r.status_code
    except (requests.RequestException, ValueError):
        return 0


def status():
    record = state()
    running = owned(record)
    code = http(record['port'], token=record['token']) if running else 0
    if running and record['mode'] != 'api' and http(record['ai_port'], '/telemetry') != 200:
        code = 0
    return dict(pid=record['pid'] if record else None, status='RUNNING' if running else 'STOPPED',
                port=record['port'] if record else 8501,
                mode=record['mode'] if record else 'none',
                stale_pid=bool(record and not running), health='PASS' if code == 200 else 'FAIL',
                http_status=code)


def start(mode='api', port=8501, ai_port=8000, timeout=90):
    record = state()
    if owned(record):
        if (record['mode'], record['port'], record['ai_port']) != (mode, port, ai_port):
            raise RuntimeError('running_configuration_differs')
        return status()
    for check_port in ([port, ai_port] if mode != 'api' else [port]):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', check_port))
    import psutil
    token = uuid4().hex
    command = [sys.executable, '-u', '-m', 'src.ops.runner', '--token', token,
               '--mode', mode, '--port', str(port), '--ai-port', str(ai_port)]
    options = {'start_new_session': True} if os.name != 'nt' else {
        'creationflags': subprocess.CREATE_NO_WINDOW}
    with (runtime_dir() / 'backend.log').open('a', encoding='utf-8') as log:
        child = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(),
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, **options)
    record = dict(pid=child.pid, created=psutil.Process(child.pid).create_time(),
                  token=token, port=port, ai_port=ai_port, mode=mode)
    path = runtime_dir() / 'backend.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record))
    temporary.replace(path)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('backend_exited')
        if http(port, token=token) == 200 and (mode == 'api' or http(ai_port, '/telemetry') == 200):
            return status()
        time.sleep(.2)
    stop(timeout=min(timeout, 15))
    raise TimeoutError('backend_start_timeout')


def stop(timeout=30):
    record = state()
    if not owned(record):
        return status()
    # Runner observes an instance-specific stop file, works without Windows consoles.
    marker = runtime_dir() / (record['token'] + '.stop')
    marker.touch()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not owned(record):
            marker.unlink(missing_ok=True)
            (runtime_dir() / 'backend.json').unlink(missing_ok=True)
            return status()
        time.sleep(.2)
    # Never forcibly terminate an unknown or wedged process.
    raise TimeoutError('graceful_stop_timeout')


def restart(mode='api', port=8501, ai_port=8000, timeout=90):
    record = state()
    if owned(record):
        mode, port, ai_port = record['mode'], record['port'], record['ai_port']
    stop(timeout)
    return start(mode, port, ai_port, timeout)
