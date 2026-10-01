# Persistent infrastructure implementation report

## Current architecture / already implemented

See [pre-change audit](persistence-audit.md). Phase 6/7 already provides PostgreSQL
repositories, transaction-scoped sessions, pgvector embeddings, and media-path
columns. Alembic HEAD is 0007. Compose's named volume only protects data on the
same Docker host. The Colab notebook previously started without DB migrations or
external storage validation.

## Missing pieces addressed

- Added one storage interface with local and provider-neutral fsspec adapters.
- Preserved existing DB keys and schema; remote objects materialize to a disposable
  cache for the existing video reader and image-serving endpoints.
- Routed uploaded videos, target originals, vehicle/plate/face evidence, and
  legacy event snapshots through the interface.
- Added strict PostgreSQL/external-storage startup validation and explicit local
  development warnings. DB failures do not trigger a PostgreSQL-to-SQLite fallback.
- Uploads now return 503 when storage/metadata persistence fails instead of false
  success. Evidence storage failures enter the existing worker retry behavior.
- Added Colab Secrets loading, migration/bootstrap and a redacted diagnostic.

## Files changed

| File | Change |
| --- | --- |
| `.env.example`, `.gitignore` | Configuration examples; ignore disposable media cache/constraints |
| `requirements-colab.txt` | Include DB/storage and API dependencies |
| `notebooks/DATT_Colab_GPU.ipynb` | Load Secrets and launch strict bootstrap before backend |
| `src/db/database.py` | Missing-URL warning; strict PostgreSQL requirement |
| `src/main.py` | Preflight before runtime imports/start |
| `src/stream/camera_manager.py` | Resolve persisted video keys through storage for existing LocalVideoReader |
| `src/ui/web_server.py` | Persist uploads/images; retrieve/delete through storage; report failed writes |
| `src/ui/video_stream.py` | Backend target image storage and event image reads |
| `src/events/db_worker.py` | Evidence image storage adapter; retry failed storage operations |
| `src/events/event_storage.py` | Route legacy snapshot image writes through storage |

## Files added

`src/storage.py`, `src/persistence.py`, `scripts/colab_bootstrap.py`,
`requirements-persistence.txt`, `tests/test_persistent_storage.py`,
`docs/persistence-audit.md`, `docs/persistent-colab.md`, and this report.

The pre-existing untracked `src/face/experimental_adaface.py` was not touched.
No YOLO, ByteTrack, InsightFace, ArcFace, OCR, thresholds, EventManager logic,
Agent/RAG, HTML, CSS or JavaScript changes. No commit or push.

## Database, storage and API changes

No migration, table or relationship changes. Bootstrap runs existing Alembic
upgrade to HEAD. Deployment expects external PostgreSQL with pgvector installed
or available for the existing extension migration. Binary files remain outside DB.

Storage configuration selects a filesystem driver without binding to a vendor.
Paths in existing DB columns remain relative media keys. Local mode remains
available for explicit development/tests. Production preflight requires external
storage. Existing files require an operator-controlled copy to the chosen storage
under identical keys; this implementation does not claim to have migrated them.

API paths and successful response shapes are preserved. Persistence failures now
return errors. Target/event images are retrieved from storage as needed; selection
by video ID downloads its persisted object instead of assuming a Colab-local file.
Strict deployments also persist color-only target metadata without inventing an
embedding. Local color-only target behavior is unchanged.

## Configuration and bootstrap

Required: `DATT_DATABASE_URL`, `DATT_STORAGE_BACKEND=external`,
`DATT_STORAGE_URL`; supply `DATT_STORAGE_OPTIONS` or provider ambient credentials.
Bootstrap sets `DATT_REQUIRE_PERSISTENCE=1`. Optional: `DATT_STORAGE_CACHE`.
Local development optionally uses `DATT_STORAGE_ROOT`.

Provision external PostgreSQL/pgvector, private media storage, its fsspec driver,
and the existing model assets, then use the notebook startup cell or:

```python
%run /content/DATT/scripts/colab_bootstrap.py
```

Use `%run` for Colab Secrets access. For a shell with exported configuration:

```sh
python scripts/colab_bootstrap.py
python -m src.persistence --require-external
```

See [deployment instructions](persistent-colab.md) for configuration, startup
order, cache semantics and failure limitations. Keep secrets out of tracked files.

## Validation results

- **16 new tests passed**: local storage contract; path traversal rejection;
  missing/strict configuration; error redaction; simulated remote cache loss;
  deletion/stale-cache behavior; real MP4 bytes generated locally, API metadata,
  fresh-process DB/file access and CameraManager frame read; real DatabaseWorker
  vehicle/plate image keys; target image retrieval with a fresh cache; storage
  failure responses. Explicit SQLite tests validate local compatibility only.
- Existing DB/media/API/video suite: **35 passed, 7 skipped, 6 failed**.
  The 7 opt-in PostgreSQL tests lack `DATT_TEST_POSTGRES_URL`.
  Four media/target failures are unavailable configured local PostgreSQL
  (`127.0.0.1`); rerun outside sandbox still produced those four failures
  (**7 passed, 4 failed** in that subset). No SQLite substitution was used.
  The frontend test expects `pollTelemetry`, absent even in HEAD's unchanged JS.
  The YouTube source-switch test fails to receive a frame and attempts network
  access for a mocked URL; this unresolved test is outside media persistence scope.
- All notebook Python cells and changed Python modules compile. `git diff --check`
  passes (Git emits existing Windows line-ending conversion notices).

## External connectivity / E2E result

**BLOCKED, NOT PASSED.** No external PostgreSQL/storage configuration is available.
The configured `.env` DB is local. Strict diagnostic exits unsuccessfully with:

```text
[DATT_PERSISTENCE_AUDIT]
database_type=unconfigured
database_connected=false
database_host=unconfigured
alembic_revision=unknown
pgvector_version=unknown
storage_backend=local
storage_connected=false
video_sources_count=unknown
targets_count=unknown
local_runtime_is_disposable=true
check_error=database_check_failed:RuntimeError
check_error=storage_check_failed:RuntimeError
```

This reflects missing exported external configuration; it does not describe a
successful database migration. No live cloud upload, backend restart or Colab
reset-persistence test has passed. Mock remote tests are not cloud evidence.

## Remaining setup / limitations

1. Supply external service configuration and install the selected storage driver.
2. Run bootstrap with schema/extension privileges and perform the documented real
   MP4 + target + vehicle/plate event upload/restart/cache-loss acceptance test.
3. Move pre-existing media under the exact stored keys before switching providers.
4. Legacy occupancy history in `data/events.db` remains local. Its numeric-ID
   snapshot lookup does not survive a reset. Migrating it requires a separately
   scoped legacy-data change; EventManager logic was deliberately preserved.
5. DB/object-store writes are not distributed transactions. Failed DB writes may
   leave orphan objects; failed deletion may require cleanup. Cache eviction,
   external backups, object retention and access policies are operational setup.

The provider-neutral implementation is ready for external validation, but a claim
that every application feature is reset-persistent would be inaccurate.
