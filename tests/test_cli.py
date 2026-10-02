"""CLI tests use isolated SQLite/storage and never production credentials."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from src.ops import checks, cli, process
from src.ops.config import ROOT


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith(('DATT_', 'SUPABASE_')):
            monkeypatch.delenv(name)
    monkeypatch.setenv('DATT_DATABASE_URL', 'sqlite:///' + (tmp_path / 'test.db').as_posix())
    monkeypatch.setenv('DATT_STORAGE_BACKEND', 'local')
    monkeypatch.setenv('DATT_STORAGE_ROOT', str(tmp_path / 'media'))
    monkeypatch.setenv('DATT_RUNTIME_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setenv('DATT_REQUIRE_PERSISTENCE', '0')
    monkeypatch.setattr(cli, 'load_configuration', lambda: None)
    return tmp_path


def test_missing_db_config(isolated, monkeypatch):
    monkeypatch.delenv('DATT_DATABASE_URL')
    assert checks.database_check()['database_configured'] is False


def test_cpu_mode_requires_video_service_health(monkeypatch):
    record = dict(pid=123, port=8501, ai_port=8000, mode='cpu', token='test')
    monkeypatch.setattr(process, 'state', lambda: record)
    monkeypatch.setattr(process, 'owned', lambda value: True)
    monkeypatch.setattr(process, 'http', lambda port, *args, **kwargs: 200 if port == 8501 else 0)
    assert process.status()['health'] == 'FAIL'
    monkeypatch.setattr(process, 'http', lambda *args, **kwargs: 200)
    assert process.status()['health'] == 'PASS'


def test_cli_accepts_cpu_runtime(isolated, monkeypatch):
    calls = []
    def start(mode, port, ai_port, timeout):
        calls.append((mode, port, ai_port))
        return {'health': 'PASS'}
    monkeypatch.setattr(process, 'start', start)
    assert cli.main(['start', '--mode', 'cpu']) == 0
    assert calls == [('cpu', 8501, 8000)]


def test_configuration_precedence_and_colab_child(isolated, monkeypatch):
    import types
    from src.ops import config
    monkeypatch.setattr(config, 'ROOT', isolated)
    (isolated / '.env').write_text('DATT_STORAGE_BACKEND=supabase\nDATT_STORAGE_BUCKET=test-bucket\n')
    monkeypatch.setattr(config, 'environment', lambda: 'colab')
    monkeypatch.setitem(sys.modules, 'IPython', types.SimpleNamespace(get_ipython=lambda: None))
    config.load_configuration()
    assert os.environ['DATT_STORAGE_BACKEND'] == 'local'
    assert os.environ['DATT_STORAGE_BUCKET'] == 'test-bucket'


def test_missing_storage_config(isolated, monkeypatch):
    monkeypatch.setenv('DATT_STORAGE_BACKEND', 'supabase')
    result = checks.storage_check()
    assert result['storage_configured'] is False
    assert result['storage_connected'] is False


def test_doctor_local_no_gpu(isolated, monkeypatch, capsys):
    checks.migrate()
    def bounded(action, timeout):
        return {'gpu_available': False, 'cuda_available': False, 'gpu_name': 'none'} if action == 'gpu-check' else cli.worker(action)
    monkeypatch.setattr(cli, 'bounded', bounded)
    result = cli.doctor(10)
    assert result['ready_for_local'] is True
    assert result['ready_for_gpu'] is False
    assert '[DATT_DOCTOR]' in capsys.readouterr().out


def test_stale_pid_does_not_signal_other_process(isolated):
    path = process.runtime_dir() / 'backend.json'
    path.write_text(json.dumps(dict(pid=os.getpid(), created=0, token='foreign', port=1234, mode='api')))
    assert process.status()['stale_pid']
    assert process.stop(.1)['status'] == 'STOPPED'
    assert not (path.parent / 'foreign.stop').exists()


def test_worker_timeout(monkeypatch):
    def timeout(*a, **k):
        raise subprocess.TimeoutExpired('private', 1)
    monkeypatch.setattr(cli, 'run_bounded', timeout)
    assert cli.bounded('db-check', .1) == {'error': 'db-check:TIMEOUT'}


def test_timeout_reaps_owned_descendants(tmp_path):
    import psutil
    from src.ops.subprocesses import run_bounded
    marker = tmp_path / 'child.json'
    code = (
        "import subprocess,sys,time,json,psutil; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "Path(sys.argv[1]).write_text(json.dumps([p.pid,psutil.Process(p.pid).create_time()])); "
        "time.sleep(30)"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, '-c', code, str(marker)], timeout=3, capture_output=True)
    pid, created = json.loads(marker.read_text())
    assert not psutil.pid_exists(pid) or psutil.Process(pid).create_time() != created


def test_bootstrap_idempotent(isolated):
    assert cli.main(['bootstrap', '--timeout', '20']) == 0
    assert cli.main(['bootstrap', '--timeout', '20']) == 0


def test_no_gpu_command_skips(isolated, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'bounded', lambda *a: {'gpu_available': False, 'cv_status': 'SKIPPED_GPU_NOT_AVAILABLE'})
    assert cli.main(['start', '--mode', 'gpu']) == 0
    assert process.state() is None
    assert 'SKIPPED_GPU_NOT_AVAILABLE' in capsys.readouterr().out


def test_worker_error_does_not_expose_secret(isolated, monkeypatch, capsys):
    def failure(*args):
        raise ValueError('do-not-print-test-secret')
    monkeypatch.setattr(cli, 'worker', failure)
    assert cli.main(['db-check', '--worker']) == 1
    output = capsys.readouterr().out
    assert 'do-not-print' not in output
    assert json.loads(output)['error'] == 'db-check:ValueError'


def test_e2e_failure_reports(isolated, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'bounded', lambda *a, **k: {'error': 'TIMEOUT'})
    assert cli.main(['e2e', '--allow-local']) == 1
    output = capsys.readouterr().out
    assert '[DATT_CLI_E2E]' in output and 'PERSISTENCE_STATUS=FAIL' in output


def test_fixture_fresh_read_and_cleanup(isolated):
    from uuid import uuid4
    checks.migrate()
    identity = str(uuid4())
    assert checks.fixture('create', identity)['fixture_create'] == 'PASS'
    assert cli.bounded('fixture-verify', 20, identity)['fixture_verify'] == 'PASS'
    assert checks.fixture('cleanup', identity)['fixture_cleanup'] == 'PASS'
    assert checks.fixture('cleanup', identity)['fixture_cleanup'] == 'PASS'


def test_api_backend_already_running_restart_and_e2e(isolated, capsys):
    checks.migrate()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    try:
        with process.locked():
            first = process.start(port=port, timeout=30)
            again = process.start(port=port, timeout=30)
        assert first['pid'] == again['pid'] and first['health'] == 'PASS'
        assert cli.main(['e2e', '--allow-local', '--port', str(port), '--timeout', '30']) == 0
        assert process.state()['pid'] != first['pid']
        assert 'PERSISTENCE_STATUS=PASS' in capsys.readouterr().out
    finally:
        process.stop(15)


def test_occupied_port_no_launch(isolated):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        with pytest.raises(OSError):
            process.start(port=sock.getsockname()[1], timeout=1)
    assert process.state() is None


def test_log_redaction(monkeypatch):
    import io
    from src.ops.runner import SafeOutput
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'test-secret-key')
    sink = io.StringIO()
    output = SafeOutput(sink)
    output.write('test-secret-key https://user:password@example.invalid/private')
    assert 'test-secret-key' not in sink.getvalue()
    assert 'password' not in sink.getvalue()
