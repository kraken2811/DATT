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
