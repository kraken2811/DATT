"""Startup orchestration regressions; no production credentials or services."""
import importlib.util
from pathlib import Path
import subprocess
import types
import pytest
from scripts.colab_startup import Startup, Blocker


def session(monkeypatch):
    monkeypatch.setattr(Startup, 'git_commit', staticmethod(lambda: 'test'))
    return Startup({'runtime': 'colab', 'gpu': 'T4', 'cuda': '12.8'})


def test_failure_latches_and_order_is_enforced(monkeypatch):
    s = session(monkeypatch)
    with pytest.raises(Blocker, match='in order'):
        s.run(4)
    monkeypatch.setattr(s, 'cell_3', lambda: (_ for _ in ()).throw(ValueError('SECRET_VALUE')))
    with pytest.raises(Blocker) as error:
        s.run(3)
    assert 'SECRET_VALUE' not in str(error.value)
    assert s.report['SYSTEM_READY'] == 'NO'
    with pytest.raises(Blocker, match='Earlier cell'):
        s.run(3)


def test_healthy_backend_is_reused_without_cli_start(monkeypatch):
    from src.ops import process
    s = session(monkeypatch)
    monkeypatch.setattr(process, 'status', lambda: {'health': 'PASS'})
    monkeypatch.setattr(s, 'cli', lambda *a, **k: pytest.fail('must not launch healthy backend'))
    s.cell_9()


def test_dead_backend_uses_existing_cli(monkeypatch):
    from src.ops import process
    s = session(monkeypatch)
    statuses = iter([{'health': 'FAIL'}, {'health': 'PASS'}])
    monkeypatch.setattr(process, 'status', lambda: next(statuses))
    calls = []
    monkeypatch.setattr(s, 'cli', lambda *a, **k: calls.append((a,k)))
    s.cell_9()
    assert calls == [(('start',), {'mode': 'gpu', 'timeout': 300})]


def test_unowned_listener_is_not_killed(monkeypatch):
    from src.ops import process
    import psutil
    s = session(monkeypatch)
    monkeypatch.setattr(process, 'status', lambda: {'health':'FAIL'})
    monkeypatch.setattr(process, 'state', lambda: None)
    monkeypatch.setattr(process, 'owned', lambda r: False)
    monkeypatch.setattr(psutil, 'net_connections', lambda kind: [types.SimpleNamespace(status='LISTEN',laddr=types.SimpleNamespace(port=8501),pid=99)])
    monkeypatch.setattr(s, 'cli', lambda *a, **k: pytest.fail('must not stop unowned process'))
    with pytest.raises(Blocker, match='unverified process'):
        s.cell_8()


def test_missing_only_dependency_plan(monkeypatch, tmp_path):
    from scripts import colab_install as install
    (tmp_path/'requirements-colab.txt').write_text('present>=1\nabsent>=2\nconflict<2\n')
    (tmp_path/'requirements-cli.txt').write_text('present>=1\n')
    monkeypatch.setattr(install,'ROOT',tmp_path)
    def version(name):
        if name == 'absent': raise install.metadata.PackageNotFoundError(name)
        return '3.0'
    monkeypatch.setattr(install.metadata,'version',version)
    assert install.plan() == (['absent>=2'], ['conflict'])


def test_smoke_uses_only_read_only_routes(monkeypatch):
    s=session(monkeypatch)
    paths=[]
    def get(path, **kwargs):
        paths.append(path)
        return types.SimpleNamespace(json=lambda: {'status':'ok'})
    monkeypatch.setattr(s,'get',get)
    s.cell_12()
    assert len(paths)==7
    assert all('switch' not in p and 'start' not in p and 'stop' not in p for p in paths)
    assert s.report['smoke_tests']=='PASS'


def test_notebook_has_13_ordered_executable_cells():
    import json
    nb=json.loads(Path('notebooks/DATT_Colab_GPU.ipynb').read_text(encoding='utf-8'))
    cells=[c for c in nb['cells'] if c['cell_type']=='code']
    assert len(cells)==13
    for n,c in enumerate(cells,1):
        code=''.join(c['source'])
        compile(code,f'cell-{n}','exec')
        assert f'# CELL {n} ' in code
        assert not c['outputs']


def test_env_upload_same_path_and_rerun(tmp_path):
    from scripts.colab_startup import install_uploaded_env
    env = tmp_path / '.env'
    env.write_text('EXAMPLE=fixture\n')
    for _ in range(2):
        assert install_uploaded_env(env, env) == env.resolve()
        assert env.read_text() == 'EXAMPLE=fixture\n'
    uploaded = tmp_path / 'env'
    uploaded.write_text('EXAMPLE=updated\n')
    install_uploaded_env(uploaded, env)
    assert env.read_text() == uploaded.read_text()


def configuration_fixture(monkeypatch, tmp_path, secrets):
    import os, sys
    from scripts import colab_startup as module
    for name in module.REQUIRED + module.EMAIL:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(os, 'environ', os.environ.copy())
    (tmp_path / '.env').write_text(
        'DATT_DATABASE_URL=sqlite:///fixture.db\nDATT_STORAGE_BACKEND=supabase\n'
        'SUPABASE_URL=https://example.invalid\nSUPABASE_SERVICE_ROLE_KEY=fixture\n'
        'DATT_STORAGE_BUCKET=fixture\n')
    calls = []
    def get(name):
        calls.append(name)
        if name not in secrets:
            raise RuntimeError('SECRET_PROVIDER_ERROR_VALUE')
        return secrets[name]
    google = types.ModuleType('google')
    colab = types.ModuleType('google.colab')
    colab.userdata = types.SimpleNamespace(get=get)
    google.colab = colab
    monkeypatch.setitem(sys.modules, 'google', google)
    monkeypatch.setitem(sys.modules, 'google.colab', colab)
    return calls


def test_email_secrets_loaded_with_project_defaults_and_redacted(monkeypatch, tmp_path, capsys):
    from scripts.colab_startup import load_configuration
    from src.notifications.config import EmailConfig
    secrets = {'DATT_EMAIL_USERNAME': 'fixture@example.invalid',
               'DATT_EMAIL_PASSWORD': 'PRIVATE_FIXTURE_PASSWORD',
               'DATT_EMAIL_TO': 'recipient@example.invalid'}
    calls = configuration_fixture(monkeypatch, tmp_path, secrets)
    load_configuration()
    assert EmailConfig.from_env().configured
    assert EmailConfig.from_env().cooldown == 300
    assert set(secrets).issubset(calls)
    output = capsys.readouterr().out
    assert 'PRIVATE_FIXTURE_PASSWORD' not in output
    assert 'SECRET_PROVIDER_ERROR_VALUE' not in output
    assert 'DATT_EMAIL_PASSWORD=SET' in output


def test_configuration_precedence_and_idempotence(monkeypatch, tmp_path):
    import os
    from scripts.colab_startup import load_configuration
    calls = configuration_fixture(monkeypatch, tmp_path, {'DATT_EMAIL_PASSWORD': 'secret-fixture'})
    with (tmp_path / '.env').open('a') as stream:
        stream.write('DATT_EMAIL_USERNAME=file@example.invalid\nDATT_EMAIL_TO=file@example.invalid\n')
    monkeypatch.setenv('DATT_EMAIL_USERNAME', 'environment@example.invalid')
    monkeypatch.setenv('DATT_EMAIL_PASSWORD', 'environment-fixture')
    for _ in range(2):
        load_configuration()
    assert os.environ['DATT_EMAIL_USERNAME'] == 'file@example.invalid'
    assert os.environ['DATT_EMAIL_PASSWORD'] == 'environment-fixture'
    assert 'DATT_EMAIL_PASSWORD' not in calls


def test_missing_email_names_are_reported_without_provider_values(monkeypatch, tmp_path):
    from scripts.colab_startup import load_configuration
    configuration_fixture(monkeypatch, tmp_path, {})
    with pytest.raises(Blocker, match='DATT_EMAIL_USERNAME, DATT_EMAIL_PASSWORD, DATT_EMAIL_TO') as error:
        load_configuration()
    assert 'SECRET_PROVIDER_ERROR_VALUE' not in str(error.value)


@pytest.mark.parametrize('worker,expected_stops', [('RUNNING', 0), ('STOPPED', 1)])
def test_owned_backend_reuses_or_restarts_for_email(monkeypatch, worker, expected_stops):
    from src.ops import process
    from src.notifications.config import EmailConfig
    import psutil
    s = session(monkeypatch)
    record = {'pid': 42}
    state = [record]
    monkeypatch.setattr(process, 'status', lambda: {'health': 'PASS', 'mode': 'gpu', 'port': 8501})
    monkeypatch.setattr(process, 'state', lambda: state[0])
    monkeypatch.setattr(process, 'owned', lambda r: r is record)
    monkeypatch.setattr(s, 'get', lambda path: types.SimpleNamespace(json=lambda: {'notification_worker': worker}))
    monkeypatch.setattr(EmailConfig, 'from_env', classmethod(lambda cls: types.SimpleNamespace(configured=True)))
    monkeypatch.setattr(psutil, 'net_connections', lambda kind: [])
    calls = []
    def cli(*args, **kwargs):
        calls.append(args)
        state[0] = None
    monkeypatch.setattr(s, 'cli', cli)
    s.cell_8()
    assert len(calls) == expected_stops
    assert all(args == ('stop',) for args in calls)
