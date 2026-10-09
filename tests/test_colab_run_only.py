"""Rerunnable Colab configuration; no live credentials or external services."""
import ast
import json
import os
from pathlib import Path
import sys

import pytest


SOURCE = Path('notebooks/colab_run_only.py').read_text(encoding='utf-8')


@pytest.fixture
def configure(monkeypatch):
    for key in tuple(os.environ):
        if key.startswith('DATT_'):
            monkeypatch.delenv(key)
    monkeypatch.chdir(Path.cwd())  # restore cwd after the loader changes it
    function = next(n for n in ast.parse(SOURCE).body if isinstance(n, ast.FunctionDef) and n.name == 'configure_runtime')
    namespace = {'Path': Path, 'os': os, 'sys': sys}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<colab-config>', 'exec'), namespace)
    return namespace['configure_runtime']


def test_existing_env_is_reused_on_repeated_runs(configure, tmp_path, capsys):
    original = b'DATT_DATABASE_URL=private-fixture\n'
    (tmp_path / '.env').write_bytes(original)
    loads = []
    def upload():
        pytest.fail('Existing .env must not invoke the upload picker')
    for _ in range(2):
        configure(tmp_path, upload, lambda _: None, lambda: loads.append(True))
    assert (tmp_path / '.env').read_bytes() == original
    assert len(loads) == 2
    assert os.environ['DATT_STRICT_AUTH'] == '1'
    assert os.environ['DATT_REQUIRE_PERSISTENCE'] == '1'
    assert not os.environ.get('DATT_AGENT_AUTH_SECRET')
    output = capsys.readouterr().out
    assert output.count('ENV_FILE=REUSED') == 2
    assert 'private-fixture' not in output


def test_missing_env_is_uploaded_once_and_then_reused(configure, tmp_path):
    calls = []
    def upload():
        calls.append(True)
        return {'.env': b'fixture=private\n'}
    configure(tmp_path, upload, lambda _: None, lambda: None)
    configure(tmp_path, upload, lambda _: None, lambda: None)
    assert calls == [True]
    assert (tmp_path / '.env').read_bytes() == b'fixture=private\n'


def test_colab_upload_already_saved_file_is_accepted(configure, tmp_path):
    def upload():
        (tmp_path / '.env').write_bytes(b'fixture=private\n')
        return {'.env': b'fixture=private\n'}
    configure(tmp_path, upload, lambda _: None, lambda: None)
    assert (tmp_path / '.env').read_bytes() == b'fixture=private\n'


def test_concurrent_different_env_is_preserved(configure, tmp_path):
    def upload():
        (tmp_path / '.env').write_bytes(b'existing-private')
        return {'.env': b'new-private'}
    with pytest.raises(RuntimeError, match='preserved'):
        configure(tmp_path, upload, lambda _: None, lambda: pytest.fail('Do not load a rejected upload'))
    assert (tmp_path / '.env').read_bytes() == b'existing-private'


@pytest.mark.parametrize('uploaded', [{}, {'other.env': b'private'}, {'.env': b'private', 'other': b'private'}])
def test_incorrect_upload_selection_is_rejected(configure, tmp_path, uploaded):
    with pytest.raises(RuntimeError, match='exactly'):
        configure(tmp_path, lambda: uploaded, lambda _: None, lambda: None)
    assert not (tmp_path / '.env').exists()


def test_granted_key_is_loaded_without_disclosure(configure, tmp_path, capsys):
    import secrets
    key = secrets.token_urlsafe(32)
    (tmp_path / '.env').write_bytes(b'fixture=private\n')
    configure(tmp_path, lambda: pytest.fail('No upload'),
              lambda name: key if name == 'DATT_AGENT_AUTH_SECRET' else None, lambda: None)
    assert os.environ['DATT_AGENT_AUTH_SECRET'] == key
    assert key not in capsys.readouterr().out


def test_load_failure_is_not_reported_ready(configure, tmp_path, capsys):
    (tmp_path / '.env').write_bytes(b'fixture=private\n')
    def fail():
        raise RuntimeError('Configuration missing')
    with pytest.raises(RuntimeError, match='missing'):
        configure(tmp_path, lambda: pytest.fail('No upload'), lambda _: None, fail)
    assert 'CONFIG=' not in capsys.readouterr().out


@pytest.mark.parametrize('configured', ['', '0', '1'])
def test_strict_auth_default_preserves_explicit_configuration(configure, tmp_path, monkeypatch, configured):
    monkeypatch.setenv('DATT_STRICT_AUTH', configured)
    (tmp_path / '.env').write_bytes(b'fixture=private\n')
    configure(tmp_path, lambda: pytest.fail('No upload'), lambda _: None, lambda: None)
    assert os.environ['DATT_STRICT_AUTH'] == (configured or '1')


def test_run_notebook_has_only_six_runnable_cells_and_no_outputs():
    notebook = json.loads(Path('notebooks/DATT_Colab_Run.ipynb').read_text(encoding='utf-8'))
    assert len(notebook['cells']) == 6
    for cell in notebook['cells']:
        assert cell['cell_type'] == 'code'
        assert cell['execution_count'] is None and cell['outputs'] == []
        code = ''.join(cell['source'])
        ast.parse(code)
        assert 'pytest' not in code and 'base64' not in code and 'create_auth_token' not in code
    config = ''.join(notebook['cells'][2]['source'])
    assert 'assert not (ROOT' not in config
    assert 'configure_runtime' in config
    preflight = ''.join(notebook['cells'][3]['source'])
    assert 'validate_auth_configuration' in preflight
    assert "cli_fields('migrate'" not in preflight
