"""Pre-startup Colab cell: reuse source, pip wheels, and complete model assets from Drive.

Never place .env, Colab Secrets, uploads, or biometric media in this cache.
Cache is an optimization: if Drive is unavailable, unmounted, or empty,
the workflow falls back safely without blocking runtime startup.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path('/content/DATT')
cache_cell_started = time.perf_counter()
remote = 'https://github.com/kraken2811/DATT.git'
drive_mounted = False

try:
    from google.colab import drive
    drive.mount('/content/drive', force_remount=False)
    drive_mounted = Path('/content/drive/MyDrive').is_dir()
except Exception as exc:
    print(f'DRIVE_MOUNT_SKIPPED: {exc}')

if drive_mounted:
    CACHE = Path('/content/drive/MyDrive/DATT-Colab-cache')
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        pip_cache = CACHE / 'pip'
        pip_cache.mkdir(parents=True, exist_ok=True)
        os.environ['PIP_CACHE_DIR'] = str(pip_cache)
        os.environ['PIP_NO_CACHE_DIR'] = 'false'
        print('PIP_CACHE=CONFIGURED')
    except Exception as exc:
        print(f'CACHE_DIR_INIT_WARNING: {exc}')
        CACHE = None
else:
    CACHE = None
    print('DRIVE_CACHE=DISABLED (running in standalone mode)')

# Git packfiles must live on Colab's local disk, not Drive's mounted filesystem.
def refresh_source(root, remote):
    root = Path(root)
    def git(*args):
        result = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError('Source update failed; inspect Git privately. Existing files preserved.')
        return result.stdout.strip()

    if not root.exists():
        result = subprocess.run(['git', 'clone', '--branch', 'dev', remote, str(root)],
                                capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError('Direct source clone failed. Partial checkout preserved for inspection.')
        print('SOURCE_DIRECT_CLONE=RESTORED')
    else:
        if not (root / '.git').is_dir():
            raise RuntimeError('Existing source directory is not a Git checkout; no files replaced.')
        if git('status', '--porcelain', '--untracked-files=no'):
            raise RuntimeError('Tracked local changes exist; commit/stash before updating. No changes discarded.')
        git('fetch', remote, 'refs/heads/dev:refs/remotes/origin/dev')
        local = git('rev-parse', 'HEAD')
        target = git('rev-parse', 'origin/dev')
        ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', local, target], cwd=root,
                                  capture_output=True, text=True, timeout=30)
        if ancestor.returncode:
            raise RuntimeError('Checkout diverges from dev; no reset performed.')
        if local != target:
            stop = subprocess.run([sys.executable, str(root / 'scripts/datt.py'), 'stop', '--timeout', '120'],
                                  cwd=root, capture_output=True, text=True, timeout=150)
            if stop.returncode:
                raise RuntimeError('Owned service could not stop safely; source unchanged.')
            git('switch', 'dev')
            git('merge', '--ff-only', 'origin/dev')
        elif git('branch', '--show-current') != 'dev':
            git('switch', 'dev')
        print('SOURCE_DIRECT_REFRESH=PASS')
    git('remote', 'set-url', 'origin', remote)
    revision = git('rev-parse', 'HEAD')
    print('SOURCE_COMMIT=' + revision)
    return revision

refresh_source(ROOT, remote)

# Model restoration from cache
if not ROOT.is_dir():
    raise RuntimeError('DATT source is unavailable; cannot restore models into a deployment')
model_dir = ROOT / 'models'
if CACHE is not None and (CACHE / 'models').is_dir():
    try:
        model_cache = CACHE / 'models'
        restored_count = 0
        for cached in model_cache.rglob('*'):
            if cached.is_file():
                target = model_dir / cached.relative_to(model_cache)
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.stat().st_size != cached.stat().st_size:
                    shutil.copy2(cached, target)
                    restored_count += 1
        print(f'MODEL_CACHE=RESTORED (restored {restored_count} files)')
    except Exception as exc:
        print(f'MODEL_CACHE_RESTORE_WARNING: {exc}')
else:
    print('MODEL_CACHE=EMPTY; models will be fetched/verified during startup')

print('DRIVE_CACHE_READY=YES')
print('drive_cache_setup_seconds=' + str(round(time.perf_counter() - cache_cell_started, 1)))


def restore_model_cache():
    """Restore cached model files into the deployment, replacing missing/size-mismatched files."""
    if CACHE is None or not (CACHE / 'models').is_dir():
        return 0
    restored = 0
    for cached in (CACHE / 'models').rglob('*'):
        if cached.is_file():
            target = model_dir / cached.relative_to(CACHE / 'models')
            if not target.is_file() or target.stat().st_size != cached.stat().st_size:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cached, target)
                restored += 1
    return restored


def save_model_cache():
    """Save verified model assets after Cell 6 succeeds; never cache secrets/media."""
    if CACHE is None:
        print('MODEL_CACHE_SAVE_SKIPPED: Drive cache not active')
        return
    try:
        model_cache = CACHE / 'models'
        model_cache.mkdir(parents=True, exist_ok=True)
        count = 0

        def sha256(path):
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                    digest.update(chunk)
            return digest.digest()

        for source in model_dir.rglob('*'):
            if not source.is_file() or source.name == '.gitkeep' or source.suffix == '.download':
                continue
            target = model_cache / source.relative_to(model_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = sha256(source)
            if target.is_file() and sha256(target) == digest:
                continue
            temporary = target.with_name(target.name + '.tmp')
            shutil.copy2(source, temporary)
            if sha256(temporary) == digest:
                temporary.replace(target)
                count += 1
            else:
                temporary.unlink(missing_ok=True)
        print(f'MODEL_CACHE_SAVED={count}')
    except Exception as exc:
        print(f'MODEL_CACHE_SAVE_WARNING: {exc}')

# Names consumed by the compact production-startup cell.
MODEL_DIR = model_dir
MODEL_CACHE = CACHE / "models" if CACHE is not None else Path("/content/datt-model-cache")
