"""Exercise fresh/reused Colab runtimes without installing packages or a GPU."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

SOURCE = Path('notebooks/colab_runtime_cell.py').read_text(encoding='utf-8')
EXPECTED = {'torch': '2.11.0+cu126', 'torchvision': '0.26.0+cu126', 'torchaudio': '2.11.0+cu126'}


@pytest.mark.parametrize('old_cuda,installs', [('cu130', 1), ('cu126', 0)])
def test_runtime_provisions_only_when_needed(monkeypatch, tmp_path, old_cuda, installs):
    calls = []
    versions = {k: v.replace('cu126', old_cuda) for k, v in EXPECTED.items()}
    def run(command, **kwargs):
        calls.append(command)
        if 'packages_distributions' in command[-1]:
            return SimpleNamespace(returncode=0, stdout=json.dumps(versions))
        return SimpleNamespace(returncode=0, stdout=json.dumps(dict(
            EXPECTED, gpu='Tesla T4', cuda='12.6', available=True, tensor_ok=True)))
    monkeypatch.setattr(subprocess, 'run', run)
    for name in (*EXPECTED, 'onnxruntime'):
        monkeypatch.delitem(sys.modules, name, raising=False)
    import socket
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def settimeout(self, value): pass
        def connect_ex(self, addr): return 1
    monkeypatch.setattr(socket, 'socket', Socket)
    namespace = {}
    exec(compile(SOURCE.replace('/content/', tmp_path.as_posix() + '/'), '<cell1>', 'exec'), namespace)
    assert sum('pip' in cmd for cmd in calls) == installs
    assert namespace['runtime']['cuda'] == '12.6'
    if installs:
        command = next(cmd for cmd in calls if 'pip' in cmd)
        assert 'https://download.pytorch.org/whl/cu126' in command
        assert all(n + '==' + v in command for n, v in EXPECTED.items())


def test_loaded_native_library_blocks_replacement(monkeypatch):
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace())
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='{}')
    monkeypatch.setattr(subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='Restart session'):
        exec(compile(SOURCE, '<cell1>', 'exec'), {})
    assert len(calls) == 1


def test_notebook_uses_runtime_cell():
    notebook = json.loads(Path('notebooks/DATT_Colab_GPU.ipynb').read_text(encoding='utf-8'))
    assert ''.join(notebook['cells'][1]['source']) == SOURCE


def test_failed_tensor_probe_does_not_publish_runtime(monkeypatch):
    results = iter([
        SimpleNamespace(returncode=0, stdout=json.dumps(EXPECTED)),
        SimpleNamespace(returncode=0, stdout=json.dumps(dict(
            EXPECTED, gpu='Tesla T4', cuda='12.6', available=True, tensor_ok=False))),
    ])
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: next(results))
    namespace = {}
    with pytest.raises(RuntimeError, match='tensor test PASS'):
        exec(compile(SOURCE, '<cell1>', 'exec'), namespace)
    assert namespace['runtime'] is None
