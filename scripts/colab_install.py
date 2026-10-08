"""Staged, wheel-only Colab provisioning with a protected CUDA stack."""
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
TORCH = {'torch': '2.11.0+cu126', 'torchvision': '0.26.0+cu126', 'torchaudio': '2.11.0+cu126'}
# Wheel-backed versions checked on Python 3.13. Keep the existing ByteTrack API.
PINS = {'ultralytics': '8.4.171', 'supervision': '0.30.3', 'insightface': '2.0',
        'easyocr': '1.7.2', 'onnx': '1.20.1', 'onnxruntime-gpu': '1.26.0',
        'streamlit': '1.64.0'}
STAGES = (
    ('backend', ('fastapi', 'uvicorn[standard]', 'python-multipart', 'httpx', 'python-dotenv', 'psutil', 'PyYAML')),
    ('database', ('SQLAlchemy', 'alembic', 'psycopg[binary]', 'pgvector', 'fsspec', 'requests')),
    ('agent', ('langchain-core>=0.3.0', 'langgraph>=0.2.0',
               'langgraph-checkpoint-postgres>=2.0.0', 'psycopg-pool>=3.2.0',
               'langchain-google-genai>=2.0.0', 'langchain-openai>=0.2.0')),
    ('vision', ('numpy', 'opencv-python-headless', 'ultralytics', 'supervision')),
    ('onnx', ('onnx', 'onnxruntime-gpu')),
    # FastEmbed and InsightFace use the verified GPU ORT distribution.
    ('agent-embeddings', ('fastembed>=0.3.0',)),
    ('face-dependencies', ('opencv-python', 'tqdm', 'scipy', 'scikit-image')),
    ('face', ('insightface',)),
    ('ocr', ('easyocr',)),
    ('application', ('streamlit', 'yt-dlp', 'imageio-ffmpeg', 'huggingface_hub', 'Pillow', 'pytest')),
)


def requirements(path, seen=None):
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


def active_versions():
    # Multiple dist-info records exist in Colab. Last-entry-wins can pin shadowed
    # Ubuntu NumPy 1.26 on Python 3.13 instead of the active NumPy 2.x package.
    names = {canonicalize_name(d.metadata['Name']) for d in metadata.distributions() if d.metadata['Name']}
    return {name: metadata.version(name) for name in sorted(names)}


def audit_plan(report, installed):
    selected = {}
    for item in report.get('install', []):
        name = canonicalize_name(item['metadata']['name'])
        version = item['metadata']['version']
        if name == 'onnxruntime':
            raise RuntimeError('Resolver attempted to install CPU ONNX Runtime')
        if name in installed and version != installed[name]:
            raise RuntimeError('Resolver attempted to replace installed package: ' + name)
        if name in TORCH:
            raise RuntimeError('Resolver attempted to replace the CUDA-verified Torch stack')
        if not item['download_info']['url'].split('?', 1)[0].endswith('.whl'):
            raise RuntimeError('Resolver selected a source build: ' + name)
        selected[name] = version
    return selected


def run_pip(args, label, logdir):
    # Persist private diagnostics, but never print raw pip output/URLs to Colab.
    with (logdir / (label + '.log')).open('w', encoding='utf-8') as log:
        try:
            result = subprocess.run([sys.executable, '-m', 'pip', '--disable-pip-version-check', *args],
                                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=300)
        except subprocess.TimeoutExpired:
            raise RuntimeError('Dependency stage ' + label + ' timed out after 300 seconds; inspect private stage log') from None
    if result.returncode:
        raise RuntimeError('Dependency stage ' + label + ' failed; inspect private stage log')


def stage_requests(names):
    return [name + ('==' + PINS[name] if name in PINS else '') for name in names]


def embedding_dependencies(raw_dependencies):
    result = []
    for raw in raw_dependencies:
        req = Requirement(raw)
        if req.marker is not None and not req.marker.evaluate({'extra': ''}):
            continue
        if canonicalize_name(req.name) == 'onnxruntime':
            req.name = 'onnxruntime-gpu'
        result.append(str(req))
    return result


def validate_dependencies():
    """Validate the application dependency closure, including the ORT substitution."""
    pending = [Requirement(name) for _, names in STAGES for name in names]
    visited = set()
    while pending:
        req = pending.pop()
        name = canonicalize_name(req.name)
        actual = 'onnxruntime-gpu' if name == 'onnxruntime' else name
        version = metadata.version(actual)
        if version not in req.specifier:
            raise RuntimeError('Installed dependency constraint failed: ' + name)
        key = (actual, tuple(sorted(req.extras)))
        if key in visited:
            continue
        visited.add(key)
        for raw in metadata.requires(actual) or []:
            child = Requirement(raw)
            if child.marker is None or any(child.marker.evaluate({'extra': extra}) for extra in ('', *req.extras)):
                pending.append(child)


def cuda_torch_ready():
    """Return whether the currently installed Torch stack passes a GPU tensor probe."""
    probe = subprocess.run([sys.executable, '-c',
        'import torch; x=torch.arange(4,device="cuda"); torch.cuda.synchronize(); '
        'assert torch.cuda.is_available() and x.sum().item()==6'],
        cwd=ROOT, capture_output=True, timeout=90)
    return probe.returncode == 0



def listening_ports():
    import socket
    occupied = []
    for port in (8000, 8501):
        with socket.socket() as sock:
            sock.settimeout(1)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                occupied.append(port)
    return occupied


def stop_owned_service_for_install():
    """Stop only the verified CLI runner; direct installer calls use this too."""
    ports = listening_ports()
    if not ports:
        return
    from src.ops import process
    with process.locked():
        record = process.state()
        if not process.owned(record):
            raise RuntimeError('Unverified service occupies DATT port(s) ' + ','.join(map(str, ports)) +
                               '; no process stopped. Run python scripts/datt.py status and identify the owning service before installing')
        import psutil
        listeners = [conn for conn in psutil.net_connections('tcp')
                     if conn.status == 'LISTEN' and conn.laddr.port in ports]
        if not listeners or any(conn.pid != record['pid'] for conn in listeners):
            raise RuntimeError('DATT port listener does not belong to the verified runner; no process stopped. Identify the owning service before installing')
        try:
            process.stop(timeout=120)
        except TimeoutError:
            raise RuntimeError('Owned DATT service did not stop gracefully; no dependencies installed') from None
        remaining = listening_ports()
        if remaining:
            raise RuntimeError('DATT port(s) still occupied after owned service stopped: ' + ','.join(map(str, remaining)) +
                               '; identify the remaining listener before installing')
    print('owned_backend_stopped_for_missing_dependencies=true', flush=True)


def main():
    installed = active_versions()
    if any(n not in installed for n in TORCH) or not cuda_torch_ready():
        raise RuntimeError('Run Cell 1 until the existing Torch/CUDA stack passes its GPU tensor probe')
    missing, incompatible = plan()
    if incompatible:
        raise RuntimeError('Installed versions conflict with repository requirements: ' + ', '.join(incompatible))
    if 'onnxruntime' in installed:
        raise RuntimeError('CPU ONNX Runtime overlaps the GPU package; resolve ownership before provisioning')
    if missing:
        stop_owned_service_for_install()
    logdir = ROOT / '.datt-runtime' / 'install'
    logdir.mkdir(parents=True, exist_ok=True)
    changed = False
    for label, names in STAGES:
        installed = active_versions()
        constraints = logdir / 'active-constraints.txt'
        constraints.write_text(''.join(f'{n}=={v}\n' for n, v in sorted(installed.items())))
        report = logdir / (label + '-plan.json')
        args = ['install', '--only-binary=:all:', '-c', str(constraints), *stage_requests(names)]
        if label in ('face', 'agent-embeddings'):
            args.append('--no-deps')
        print('dependency_stage=' + label + '; resolving', flush=True)
        run_pip([*args, '--dry-run', '--report', str(report)], label + '-resolve', logdir)
        resolution = json.loads(report.read_text())
        selected = audit_plan(resolution, installed)
        if label == 'agent-embeddings':
            # FastEmbed requires the CPU ORT distribution by name. Supply the
            # already verified GPU ORT instead, while resolving every other dependency.
            raw_dependencies = (resolution['install'][0]['metadata'].get('requires_dist', [])
                                if resolution.get('install') else metadata.requires('fastembed') or [])
            dependencies = embedding_dependencies(raw_dependencies)
            if dependencies:
                dependency_report = logdir / 'agent-embedding-dependencies-plan.json'
                run_pip(['install', '--only-binary=:all:', '-c', str(constraints),
                         *dependencies, '--dry-run', '--report', str(dependency_report)],
                        'agent-embedding-dependencies-resolve', logdir)
                selected.update(audit_plan(json.loads(dependency_report.read_text()), installed))
        if selected:
            # A resolver may discover missing transitive packages even when
            # every top-level requirement is installed. Check before mutation.
            stop_owned_service_for_install()
            # Install precisely the reviewed resolution; do not resolve again.
            run_pip(['install', '--only-binary=:all:', '--no-deps', '-c', str(constraints),
                     *[n + '==' + v for n, v in selected.items()]], label + '-install', logdir)
            changed = True
        print('dependency_stage=' + label + '; PASS', flush=True)
    validate_dependencies()
    after = active_versions()
    if not cuda_torch_ready():
        raise RuntimeError('CUDA Torch verification failed after dependency provisioning')
    result = subprocess.run([sys.executable, '-c',
        'import torch, torchvision, onnxruntime, ultralytics, insightface, easyocr, cv2, numpy; '
        'import sqlalchemy, alembic, psycopg, pgvector, fastapi, uvicorn, dotenv, httpx, yaml; '
        'import langchain_core, langgraph, langgraph.checkpoint.postgres, psycopg_pool, fastembed; '
        'import langchain_google_genai, langchain_openai; '
        'from src.ui.web_server import app; assert any(r.path == "/api/agent/chat" for r in app.routes); '
        'from src.tracker.bytetrack_tracker import PersonTracker; PersonTracker(); '
        'assert torch.cuda.is_available(); '
        'x=torch.arange(4,device="cuda"); assert (x*x).sum().item()==14; '
        'assert "CUDAExecutionProvider" in onnxruntime.get_available_providers()'],
        cwd=ROOT, capture_output=True, timeout=120)
    (logdir / 'imports.log').write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError('Critical imports/CUDA verification failed; inspect private imports log')
    (logdir / 'verified-versions.json').write_text(json.dumps(after, indent=2))
    return {'dependencies_reused': not changed, 'dependencies': 'PASS'}


if __name__ == '__main__':
    try:
        print(main())
    except RuntimeError as exc:
        print(str(exc))
        raise SystemExit(1)
