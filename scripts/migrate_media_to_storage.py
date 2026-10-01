"""Copy existing media without deleting local files or overwriting remote objects.

Run with remote Storage environment configured before switching the backend.
Every existing and uploaded object is compared byte-for-byte by SHA256.
"""
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.storage import get_storage, LocalStorageBackend


def digest(source):
    h = hashlib.sha256()
    for block in iter(lambda: source.read(1024 * 1024), b''):
        h.update(block)
    return h.digest()


def migrate(root=ROOT):
    storage = get_storage()
    if isinstance(storage, LocalStorageBackend):
        raise RuntimeError('Remote Storage required')
    count = 0
    for directory in ('data/uploads/videos', 'data/uploads/targets', 'data/events'):
        for path in sorted((root / directory).rglob('*')):
            if not path.is_file() or path.is_symlink():
                continue
            key = path.relative_to(root).as_posix()
            with path.open('rb') as source:
                expected = digest(source)
                if not storage.exists(key):
                    source.seek(0)
                    storage.save(key, source)
            with storage.open(key) as source:
                if digest(source) != expected:
                    raise RuntimeError('Media conflict; original files retained')
            count += 1
    print('media_objects_verified=' + str(count))


if __name__ == '__main__':
    try:
        migrate()
    except Exception as exc:
        print('media_migration_failed=' + type(exc).__name__)
        raise SystemExit(1)
