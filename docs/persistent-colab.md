# Disposable Colab deployment

The implementation keeps Phase 6/7 schema HEAD 0007 and existing CV algorithms.
GitHub holds code; external PostgreSQL holds metadata; external storage holds
media. Colab contains only processes, models and disposable file copies.

## Configuration

Set these environment variables or same-named Colab Secrets (grant notebook access):

| Variable | Value |
| --- | --- |
| DATT_DATABASE_URL | `postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB?sslmode=require` (URL-encode credentials) |
| DATT_STORAGE_BACKEND | `external` |
| DATT_STORAGE_URL | Provider-qualified bucket/container/prefix; no embedded credentials |
| DATT_STORAGE_OPTIONS | JSON object of provider driver options/credentials; default `{}` for ambient credentials |
| DATT_STORAGE_CACHE | Optional disposable cache directory |
| DATT_REQUIRE_PERSISTENCE | `1`; bootstrap sets this automatically |

Local development uses `DATT_STORAGE_BACKEND=local` and optionally
`DATT_STORAGE_ROOT` (defaults to checkout root). Explicit SQLite test databases
remain supported outside strict deployment mode. PostgreSQL errors never switch
to SQLite. Do not put secrets in notebooks, command-line arguments or tracked files.

The adapter uses [fsspec filesystem drivers](https://filesystem-spec.readthedocs.io/en/latest/api.html).
Install the selected provider's driver separately (for example s3fs, gcsfs or
adlfs). No provider is selected by this repository. Provision a private writable
storage prefix and external PostgreSQL with pgvector available; the migration
role needs extension/schema privileges. Configure provider timeouts/retries in
the driver options and database TLS/connect_timeout in the DB URL.

## Bootstrap

Clone/upload this checkout to `/content/DATT`, select an L4 CUDA 12 runtime, install
your provider driver, and provision models using the existing model download cell.
Do not run the old backend startup cell for a persistent deployment.

```python
# Notebook cell: secrets are read inside the helper; never printed.
%run /content/DATT/scripts/colab_bootstrap.py
```

This runs in the foreground. Stop it before restarting. `--skip-install` reuses
already installed dependencies. Use `%run` when reading Colab Secrets so the
helper runs in the notebook kernel; a shell command requires exported environment
variables. The repository notebook startup cell loads Secrets in the kernel and
passes the environment to its background bootstrap process.

The helper checks required configuration, installs
requirements with Colab Torch versions preserved, checks GPU, tests PostgreSQL,
checks extension availability, upgrades Alembic, verifies revision/tables/pgvector
and storage write/read/delete, then starts the existing application. It deliberately
stops on missing credentials/models/provider drivers; it does not create a cloud
account, download private data or silently fall back to local storage.

For a separate diagnostic after exporting configuration:

```sh
python -m src.persistence --require-external
```

## Media and failure behavior

DB paths remain keys such as `data/uploads/videos/<uuid>_name.mp4`.
Uploads persist objects before metadata; the library reads existing DB rows.
Selection by VideoSource ID materializes the stored key for LocalVideoReader.
Targets, vehicle/plate/face crops and legacy snapshots share the same adapter.
Evidence I/O remains in the existing DB worker. Failed crop writes retry the
existing batch instead of committing a missing image reference.

The cache can be discarded on restart; it is not the source of truth. Objects
must use immutable keys. DB and object storage do not share a transaction: failed
DB commits may leave orphan objects, and failed object deletion after DB deletion
requires operator cleanup. Existing local objects are not automatically migrated;
copy them with their exact keys before switching providers. Protect backups and
retention at the external services. Uploaded binary data never enters PostgreSQL.

## Known boundary and validation status

Legacy occupancy history still lives in `data/events.db`; legacy IDs/snapshot
lookup by those IDs will not survive a VM reset. The Phase 6/7 PostgreSQL events
and images referenced by their keys are the durable path. Diagnostic OCR/face
dumps, logs, stream downloads and models remain disposable. EventManager and
recognition algorithms are unchanged. This is not a claim that every legacy
application feature is reset-persistent.

External credentials are required to validate actual durability. Local adapter
and restart tests do not prove cloud persistence. Before accepting deployment:
upload a real MP4 and reference image through the API, generate a vehicle/plate
event, verify each DB key and remote object, stop DATT, discard only the disposable
cache, restart with the same external configuration, and verify old library rows,
video selection/frame decoding, target images and event images. Do not delete the
cloud data or claim a successful reset test until this sequence passes.
