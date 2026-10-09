"""Exercise local Colab Git refresh without Drive, network, or production data."""
import ast
from pathlib import Path
import subprocess
import sys
import pytest
from tests.test_colab_source import checkout, git

def refresh(root, remote):
    source = Path('notebooks/colab_drive_cache_cell.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'refresh_source')
    namespace = dict(Path=Path, subprocess=subprocess, sys=sys)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'source-refresh', 'exec'), namespace)
    return namespace['refresh_source'](root, str(remote))

def test_fresh_source_clones_locally(tmp_path, checkout):
    _, upstream = checkout
    root = tmp_path / 'fresh-runtime'
    assert refresh(root, upstream) == git(upstream, 'rev-parse', 'HEAD')
    assert git(root, 'remote', 'get-url', 'origin') == str(upstream)
    assert git(root, 'branch', '--show-current') == 'dev'

def test_refresh_preserves_ignored_runtime_files(checkout):
    root, upstream = checkout
    (upstream / 'revision').write_text('updated')
    git(upstream, 'add', 'revision')
    git(upstream, 'commit', '-m', 'update')
    assert refresh(root, upstream) == git(upstream, 'rev-parse', 'HEAD')
    assert (root / 'stopped').is_file()
    for name in ('.env', 'models/model.bin', 'data/database.bin'):
        assert (root / name).read_bytes() == b'preserve'
    (root / 'stopped').unlink()
    refresh(root, upstream)
    assert not (root / 'stopped').exists()

def test_dirty_source_stops_before_fetch(checkout):
    root, upstream = checkout
    (root / 'revision').write_text('local edits')
    with pytest.raises(RuntimeError, match='Tracked local changes'):
        refresh(root, upstream)
    assert (root / 'revision').read_text() == 'local edits'
    assert not (root / 'stopped').exists()

def test_divergence_is_not_reset(checkout):
    root, upstream = checkout
    for repo, value in ((root, 'local'), (upstream, 'remote')):
        (repo / 'revision').write_text(value)
        git(repo, 'add', 'revision')
        git(repo, 'commit', '-m', value)
    original = git(root, 'rev-parse', 'HEAD')
    with pytest.raises(RuntimeError, match='diverges'):
        refresh(root, upstream)
    assert git(root, 'rev-parse', 'HEAD') == original

def test_existing_non_checkout_is_preserved(tmp_path):
    root = tmp_path / 'DATT'
    root.mkdir()
    (root / '.env').write_bytes(b'preserve')
    with pytest.raises(RuntimeError, match='not a Git checkout'):
        refresh(root, tmp_path / 'absent-upstream')
    assert (root / '.env').read_bytes() == b'preserve'
