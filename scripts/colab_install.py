"""Missing-only Colab provisioning. Never replace an installed incompatible package."""
import importlib.metadata as metadata
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def requirements(path, seen=None):
    from packaging.requirements import Requirement
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        return
    seen.add(path)
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('-r '):
            yield from requirements(path.parent / line[3:].strip(), seen)
        else:
            req = Requirement(line)
            if req.marker is None or req.marker.evaluate():
                yield req


def plan():
    missing, incompatible = [], []
    for filename in ('requirements-colab.txt', 'requirements-cli.txt'):
        for req in requirements(ROOT / filename):
            try:
                version = metadata.version(req.name)
            except metadata.PackageNotFoundError:
                missing.append(str(req))
                continue
            if req.specifier and version not in req.specifier:
                incompatible.append(req.name)
    return sorted(set(missing)), sorted(set(incompatible))


def main():
    missing, incompatible = plan()
    if incompatible:
        raise RuntimeError('Installed versions conflict with repository requirements: ' + ', '.join(incompatible))
    try:
        metadata.version('onnxruntime')
    except metadata.PackageNotFoundError:
        pass
    else:
        raise RuntimeError('CPU onnxruntime overlaps the GPU package; resolve this conflict before startup')
    if missing:
        import socket
        for port in (8000, 8501):
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1', port)) == 0:
                    raise RuntimeError('Dependencies missing while a service is running; stop its owner before installation')
        # Pin every installed distribution so pip cannot silently upgrade/downgrade
        # the current runtime while resolving the missing requirements.
        constraints = ROOT / '.colab-persistence-constraints.txt'
        pins = {d.metadata['Name']: d.version for d in metadata.distributions() if d.metadata['Name']}
        constraints.write_text(''.join(f'{name}=={version}\n' for name, version in sorted(pins.items())))
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', '-c', str(constraints), *missing],
                                cwd=ROOT, capture_output=True, timeout=1200)
        if result.returncode:
            raise RuntimeError('Missing dependency installation failed; resolver or network conflict (pip output withheld)')
    # Isolate native imports from the notebook kernel, including after pip changes.
    result = subprocess.run([sys.executable, '-c',
        'import torch, torchvision, onnxruntime, ultralytics, insightface, easyocr; '
        'import sqlalchemy, alembic, psycopg, pgvector, fastapi, uvicorn, dotenv, httpx, cv2, yaml; '
        'assert torch.cuda.is_available(); '
        'assert "CUDAExecutionProvider" in onnxruntime.get_available_providers()'],
        cwd=ROOT, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError('Critical dependency import/CUDA verification failed; output withheld')
    return {'dependencies_reused': not missing, 'dependencies': 'PASS'}


if __name__ == '__main__':
    try:
        print(main())
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
