# DATT CLI operations

Entry point: `python scripts/datt.py <command>`. Run from the checkout using its
virtual environment. No command commits, pushes, resets Git, resets PostgreSQL,
or restarts the Colab runtime.

## Audit and scope

Before this change, `scripts/colab_bootstrap.py`, `src.persistence`, `Database`,
Alembic and `get_storage()` already implemented configuration, schema and media
persistence. The notebook additionally owned installation, model downloads,
PID variables, readiness polling and stopping. `src/main.py` started CV and web
together. The CLI reuses these implementations and schema models; it adds process
ownership and an API-only supervisor, without changing CV or EventManager.

## Configuration

Explicit environment variables override `.env`; Colab Secrets fill missing values.
In Colab, call `load_secrets()` **in the notebook kernel** before starting CLI
subprocesses. CLI subprocesses inherit those values. Do not put credentials in
command arguments, URLs printed to a terminal, or source archives.

Existing names remain supported:

```dotenv
DATT_DATABASE_URL=
DATT_STORAGE_BACKEND=supabase
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
DATT_STORAGE_BUCKET=
DATT_REQUIRE_PERSISTENCE=1
```

`SUPABASE_STORAGE_BUCKET` is also accepted. `SUPABASE_URL` must be the actual HTTPS
project origin, not `<project-ref>`. No credential values are included here.
External fsspec options remain available through `DATT_STORAGE_URL` and
`DATT_STORAGE_OPTIONS`. Install the selected provider driver yourself.

Installation is explicit: bootstrap validates the environment but never upgrades
packages. `scripts/colab_install.py` checks the repository requirements first,
installs missing packages while constraining installed versions, and fails on
existing version conflicts. A CPU ORT overlap introduced by a new InsightFace
installation is repaired once with the repository's pinned GPU ORT 1.26.0.
Model provisioning is explicit through `models`, with the same download sources
as the legacy notebook. `cv-check` validates provisioning/provider availability;
it does not initialize every recognition model or claim inference accuracy.

The ordered startup notebook and its restart/failure rules are documented in
[`colab-startup.md`](colab-startup.md). Its separate disposable model probe calls
production YOLO, FaceEmbedder, AdaptiveFacePipeline, PlateDetector and OCR
initializers; it does not retain GPU models in the notebook kernel.

For isolated local development explicitly set a SQLite URL,
`DATT_STORAGE_BACKEND=local`, `DATT_STORAGE_ROOT` to a disposable directory, and
`DATT_REQUIRE_PERSISTENCE=0`. Missing DB configuration is reported, not silently
treated as a successful persistent deployment.

## Commands

| Command | Behavior |
| --- | --- |
| doctor | Environment, Git, GPU, DB/schema, Storage and owned backend status; GPU absence alone is not failure |
| bootstrap | Creates directories, validates dependencies/config, upgrades Alembic, verifies storage; repeatable |
| migrate | Existing Alembic upgrade to repository heads; no schema hardcoding |
| db-check | Connection/version, pgvector, repository revisions, model table names |
| storage-check | Unique random object upload, existence/read, byte equality, delete only that object |
| start | API-only by default; `--mode gpu` uses `src/main.py` |
| stop | Graceful shutdown of this CLI's verified process only |
| restart | Preserves running process mode and ports; never restarts notebook/runtime |
| status | PID, stale PID, mode, health and HTTP status |
| gpu-check | Torch CUDA detection isolated in a subprocess |
| cv-check | GPU, ORT CUDA provider and existing required model files; not a CV accuracy benchmark |
| models | Explicitly downloads the same two models as the old notebook; bounded by `--timeout` |
| test | Default CPU/schema/storage/API/CLI suite, isolated credentials/DB/storage; `--suite all` also includes existing YouTube/network/inference tests |
| e2e | External persistence by default; `--allow-local` explicitly labels SQLite/local validation |

`--timeout` bounds each worker, startup or shutdown (90 seconds default), not the
entire E2E. Test timeout applies to the whole pytest process. Workers suppress raw
provider errors and return their type; progress is flushed before each operation.
Worker/test timeouts reap owned descendants too, including Windows venv launcher
children. Locked disposable test directories may be retained after failure;
cleanup must not replace the original timeout with a filesystem exception.
Storage existence uses streamed Range GET because Supabase HEAD can return a
bodyless HTTP 400 for a missing object. It does not treat that as authentication
success. Timed-out writes may leave a unique test object; no broad deletion is used.

Runtime state lives in `.datt-runtime/`, configurable by `DATT_RUNTIME_DIR`.
An OS lock serializes lifecycle operations. PID creation time, runner command and
random instance token prevent signaling reused or foreign PIDs. Occupied ports
are refused. `/healthz` confirms the instance identity; GPU mode also requires
the existing AI `/telemetry` endpoint. Failed graceful shutdown leaves ownership
state for investigation, and never escalates automatically to killing a process.
Logs are written to `.datt-runtime/backend.log` through a credential redactor.
API-only binds loopback and serves existing metadata/media routes without starting
inference; CV-dependent endpoints are not promised in this mode.

E2E creates one uniquely tagged `VideoSource` and binary object, restarts only the
owned backend, reopens metadata and downloads bytes in a fresh worker, checks the
real API before and after restart, then deletes only its fixture. This verifies
the persistence plumbing, not MP4 encoding, face recognition or all media classes;
the separate Supabase media tests cover those flows. On cleanup failure it prints
the fixture UUID for targeted recovery. Existing user data is not deleted.

## Local

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-cli.txt
.\venv\Scripts\python.exe scripts/datt.py doctor
.\venv\Scripts\python.exe scripts/datt.py bootstrap
.\venv\Scripts\python.exe scripts/datt.py start --mode api
.\venv\Scripts\python.exe scripts/datt.py status
.\venv\Scripts\python.exe scripts/datt.py test --timeout 180
.\venv\Scripts\python.exe scripts/package_runtime.py
```

Configure `.env` first. Running the CLI locally manages a local process, **not a
remote Colab process**. This task does not introduce a remote shell, public admin
endpoint or browser-independent authentication channel into Colab.

## Fresh Colab (no commit/push needed)

Upload `.datt-runtime/datt-source.zip` produced above once. Run this in a Colab cell:

```python
from google.colab import files
from pathlib import Path
import os, subprocess, sys, zipfile, io
root = Path('/content/DATT')
if not root.exists():
    subprocess.run(['git', 'clone', '--branch', 'main', 'https://github.com/kraken2811/DATT.git', str(root)], check=True, timeout=180)
uploaded = files.upload()  # select only datt-source.zip; never upload .env
with zipfile.ZipFile(io.BytesIO(uploaded['datt-source.zip'])) as archive:
    for item in archive.infolist():
        target = (root / item.filename).resolve()
        assert target.is_relative_to(root.resolve()), 'Unsafe archive path'
    archive.extractall(root)
os.chdir(root)
subprocess.run([sys.executable, 'scripts/colab_install.py'], check=True, timeout=3700)
from scripts.colab_bootstrap import load_secrets
load_secrets()
os.environ['DATT_REQUIRE_PERSISTENCE'] = '1'
def datt(*args, timeout=180):
    subprocess.run([sys.executable, '-u', 'scripts/datt.py', *args], check=True, timeout=timeout)
datt('models', '--timeout', '600', timeout=650)
datt('bootstrap', '--mode', 'gpu', timeout=400)
datt('doctor', timeout=400)
datt('start', '--mode', 'gpu')
from google.colab.output import serve_kernel_port_as_window
serve_kernel_port_as_window(8501)
```

Use the overlay on a **fresh checkout**; preserve/review any edits before applying
it to an existing runtime. Source archives also support testing local changes before publication.
For already running notebook-owned processes, use that notebook's existing stop
cell once; the CLI intentionally refuses to adopt or kill unknown processes.
The legacy bootstrap entrypoint remains available during migration.

## Whole-system verification

```bash
python scripts/datt.py doctor --timeout 60
python scripts/datt.py db-check --timeout 60
python scripts/datt.py storage-check --timeout 60
python scripts/datt.py e2e --mode api --timeout 120
python scripts/datt.py status
```

On Colab run the same commands through `datt(...)`; use `--mode gpu` for E2E if
the owned backend runs GPU mode. Local absence of CUDA is explicitly skipped,
not interpreted as lost persistence. Colab reset/reprovision still needs source,
dependencies, model weights and Secrets restored; persistent data remains remote.

## Validation in this checkout

- `python scripts/datt.py test --timeout 120`: **63 passed**, four existing
  deprecation warnings. Includes a real HTTP API backend, repeated start,
  restart, fresh worker DB/media reads, stale PID protection, environment
  precedence and timeout cleanup of a real subprocess tree.
- Standalone bootstrap/doctor/E2E with disposable SQLite + local storage:
  **PASS**, schema revision 0007, HTTP 200, fixture cleanup PASS, no GPU needed.
  Evidence: `.datt-runtime/cli-validation.txt` (generated, ignored by Git).
- Full repository suite: **not passed**. A 240-second run timed out with failures;
  a repeat after resolving FFmpeg before subprocess mocks reached a 600-second
  cutoff and Windows temporary-directory cleanup raised PermissionError.
  The CLI now bounds descendant processes and tolerates locked temporary cleanup;
  the full suite was not repeated after that final fix. Existing stream/CV tests
  still need separate investigation; no algorithm was changed here.
- Cloud CLI verification on the existing Colab T4 runtime: **PASS** with
  PostgreSQL 17.11, pgvector 0.8.2 and repository Alembic head 0007; all 11
  application tables were verified. Real Storage upload/read/byte comparison
  and deletion passed. GPU backend startup initialized YOLO and the plate model
  on CUDA 12.8. Health, video-source API and web returned HTTP 200.
- Cloud E2E restarted only the CLI-owned backend, verified the fixture's DB
  metadata and remote bytes in a fresh worker, and cleaned up its test artifacts.
  No Colab runtime reset or CV algorithm change was required. This does not
  claim that the separate opt-in all-media live test passed.
- Use the actual project origin in the `SUPABASE_URL` Secret. The verified
  runtime used an environment correction for a placeholder Secret; that
  correction is not embedded in source and must be configured for fresh runtimes.
