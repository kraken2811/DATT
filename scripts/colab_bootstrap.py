"""Fresh disposable Colab: python scripts/colab_bootstrap.py [--skip-install]."""
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    subprocess.run(args, cwd=ROOT, check=True)


def load_secrets():
    names = ("DATT_DATABASE_URL", "DATT_STORAGE_BACKEND", "DATT_STORAGE_URL",
             "DATT_STORAGE_OPTIONS", "DATT_STORAGE_CACHE", "SUPABASE_URL",
             "SUPABASE_SERVICE_ROLE_KEY", "DATT_STORAGE_BUCKET", "SUPABASE_STORAGE_BUCKET")
    try:
        from google.colab import userdata
    except ImportError:
        return
    for name in names:
        if not os.environ.get(name):
            try:
                value = userdata.get(name)
            except (userdata.SecretNotFoundError, userdata.NotebookAccessError):
                continue
            if value:
                os.environ[name] = value


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--skip-install", action="store_true")
    args = parser.parse_args()
    checkout = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=ROOT,
        check=True, capture_output=True, text=True,
    )
    if Path(checkout.stdout.strip()).resolve() != ROOT.resolve():
        raise RuntimeError("DATT must be the Git checkout root")
    for path in ("src/main.py", "src/db/alembic.ini", "requirements-colab.txt"):
        if not (ROOT / path).is_file():
            raise RuntimeError("DATT checkout is incomplete")
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    for port in (8000, 8501):
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError("DATT port occupied; stop the existing backend first")
    load_secrets()
    if not os.getenv("DATT_DATABASE_URL") or os.getenv("DATT_STORAGE_BACKEND") not in ("external", "supabase"):
        raise RuntimeError("Set DATT_DATABASE_URL and a remote DATT_STORAGE_BACKEND in environment/Colab Secrets")
    from src.storage import get_storage
    get_storage()  # Validate provider configuration without logging credentials.
    os.environ["DATT_REQUIRE_PERSISTENCE"] = "1"
    if not args.skip_install:
        import importlib.metadata as metadata
        constraints = ROOT / ".colab-persistence-constraints.txt"
        constraints.write_text("\n".join(name + "==" + metadata.version(name)
                                         for name in ("torch", "torchvision")) + "\n")
        run([sys.executable, "-m", "pip", "install", "-c", str(constraints), "-r", "requirements-colab.txt"])
        run([sys.executable, "-m", "pip", "uninstall", "-y", "onnxruntime", "onnxruntime-gpu"])
        run([sys.executable, "-m", "pip", "install", "--no-deps", "onnxruntime-gpu==1.26.0"])
    run([sys.executable, "-c", "import torch, onnxruntime as o; assert torch.cuda.is_available(), 'GPU required'; assert torch.version.cuda.startswith('12.'), 'CUDA 12 required'; assert 'CUDAExecutionProvider' in o.get_available_providers(); print('GPU:', torch.cuda.get_device_name(0))"])
    from src.db.database import Database
    from sqlalchemy import text
    db = Database()
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT version()"))
            available = conn.scalar(text("SELECT name FROM pg_available_extensions WHERE name='vector'"))
            if not available:
                raise RuntimeError("Server does not provide pgvector; ask the database administrator to install it")
    finally:
        db.dispose()
    # Use Alembic API so driver errors can be redacted by the outer handler.
    from alembic import command
    from alembic.config import Config
    command.upgrade(Config(str(ROOT / "src/db/alembic.ini")), "head")
    from src.persistence import audit, print_audit
    result, errors = audit(require_external=True)
    print_audit(result, errors)
    if errors:
        raise RuntimeError("External persistence preflight failed")
    # Existing notebook model download cell must have provisioned the models.
    for model in ("yolo11s.pt", "yolov8n-license-plate.pt"):
        if not (ROOT / "models" / model).is_file():
            raise RuntimeError("Required model missing; run the notebook model download cell")
    # Replace the helper, preserving the PID tracked by the notebook stop cell.
    os.execv(sys.executable, [sys.executable, "-u", "src/main.py", "--port", "8501", "--ai-port", "8000"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print provider/driver exceptions containing URLs or credentials.
        print("Bootstrap stopped (" + type(exc).__name__ + "). Check required configuration, provider driver, GPU, models and external connectivity.", file=sys.stderr)
        raise SystemExit(1)
