"""Exercise notebook source updates against local Git remotes, without Colab/network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def checkout(tmp_path):
    upstream = tmp_path / 'upstream'
    upstream.mkdir()
    git(upstream, 'init', '-b', 'dev')
    git(upstream, 'config', 'user.name', 'Fixture')
    git(upstream, 'config', 'user.email', 'fixture@example.invalid')
    (upstream / 'scripts').mkdir()
    (upstream / 'scripts/datt.py').write_text("from pathlib import Path\nPath('stopped').write_text('owned-cli-stop')\n")
    (upstream / '.gitignore').write_text('.env\nmodels/\ndata/\nstopped\n')
    (upstream / 'revision').write_text('old')
    git(upstream, 'add', '.')
    git(upstream, 'commit', '-m', 'initial')
    root = tmp_path / 'DATT'
    git(tmp_path, 'clone', str(upstream), str(root))
    git(root, 'config', 'user.name', 'Fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    for name in ('.env', 'models/model.bin', 'data/database.bin'):
        file = root / name
        file.parent.mkdir(exist_ok=True)
        file.write_bytes(b'preserve')
    return root, upstream


def run_source(root):
    notebook = json.loads(Path('notebooks/DATT_Colab_GPU.ipynb').read_text(encoding='utf-8'))
    code = ''.join(notebook['cells'][2]['source']).split('os.chdir(ROOT)')[0]
    exec(compile(code, 'colab-source-cell', 'exec'), dict(
        ROOT=root, runtime={'runtime': 'colab'}, subprocess=subprocess, sys=sys))


def test_fast_forward_stops_owned_service_and_preserves_data(checkout):
    root, upstream = checkout
    (upstream / 'revision').write_text('new')
    git(upstream, 'add', 'revision')
    git(upstream, 'commit', '-m', 'update')
    run_source(root)
    assert git(root, 'rev-parse', 'HEAD') == git(upstream, 'rev-parse', 'HEAD')
    assert git(root, 'branch', '--show-current') == 'dev'
    assert (root / 'stopped').is_file()
    for name in ('.env', 'models/model.bin', 'data/database.bin'):
        assert (root / name).read_bytes() == b'preserve'
    (root / 'stopped').unlink()
    run_source(root)
    assert not (root / 'stopped').exists(), 'Current revision must not stop a healthy service'


def test_dirty_checkout_is_not_discarded(checkout):
    root, _ = checkout
    (root / 'revision').write_text('local edits')
    with pytest.raises(RuntimeError, match='Tracked local changes'):
        run_source(root)
    assert (root / 'revision').read_text() == 'local edits'
    assert not (root / 'stopped').exists()


def test_divergent_checkout_is_not_reset(checkout):
    root, upstream = checkout
    for repo, value in ((root, 'local'), (upstream, 'remote')):
        (repo / 'revision').write_text(value)
        git(repo, 'add', 'revision')
        git(repo, 'commit', '-m', value)
    original = git(root, 'rev-parse', 'HEAD')
    with pytest.raises(RuntimeError, match='diverges'):
        run_source(root)
    assert git(root, 'rev-parse', 'HEAD') == original
    assert not (root / 'stopped').exists()
