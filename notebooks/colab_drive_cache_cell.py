"""Optional pre-startup Colab cell: reuse public source, wheels, and model files from Drive.

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

ROOT = Path('/content/DATT')
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
        print('PIP_CACHE=CONFIGURED')
    except Exception as exc:
        print(f'CACHE_DIR_INIT_WARNING: {exc}')
        CACHE = None
else:
    CACHE = None
    print('DRIVE_CACHE=DISABLED (running in standalone mode)')

# Source restoration / fallback
if not ROOT.exists():
    restored = False
    if CACHE is not None:
        mirror = CACHE / 'dev.git'
        try:
            if not mirror.exists():
                subprocess.run(['git', 'clone', '--mirror', remote, str(mirror)], check=True, timeout=180)
                print('SOURCE_CACHE=CREATED')
            else:
                subprocess.run(['git', '-C', str(mirror), 'remote', 'update', '--prune'], check=True, timeout=120)
                print('SOURCE_CACHE=UPDATED')
            subprocess.run(['git', 'clone', '--branch', 'dev', str(mirror), str(ROOT)], check=True, timeout=120)
            subprocess.run(['git', '-C', str(ROOT), 'remote', 'set-url', 'origin', remote], check=True)
            print('SOURCE_CACHE=RESTORED')
            restored = True
        except Exception as exc:
            print(f'SOURCE_CACHE_WARNING: Mirror clone failed ({exc}); falling back to direct clone.')
            if ROOT.exists():
                shutil.rmtree(ROOT, ignore_errors=True)
    if not restored and not ROOT.exists():
        try:
            subprocess.run(['git', 'clone', '--branch', 'dev', remote, str(ROOT)], check=True, timeout=180)
            print('SOURCE_DIRECT_CLONE=RESTORED')
        except Exception as exc:
            print(f'SOURCE_CLONE_ERROR: {exc}')
else:
    print('SOURCE_CACHE=EXISTING_RUNTIME')

# Model restoration from cache
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
