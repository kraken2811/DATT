# Current persistence verification ? 2026-10-01

Branch `main`, commit `549226811392b379dd337578f0c7c5376705b16d`. The existing dirty working tree was retained. No commit or push.

## Verified implementation

- `Database` loads an explicit URL, environment, then `.env`; PostgreSQL URLs use psycopg and pool pre-ping. Transaction-scoped sessions commit or roll back. Strict deployment refuses missing configuration and SQLite; a failed PostgreSQL connection does not switch databases.
- `config.py` contains CV/runtime configuration, not persistence credentials. It was not changed.
- Migrations form one chain: 0001 initial event/target/camera tables; 0002 zones; 0003 pgvector and 512D target embeddings; 0004 passages/business events; 0005 video sources and links; 0006 vehicle image/color; 0007 source traceability. Repository HEAD is 0007; deployed revision and extension version are unknown.
- Video upload writes the StorageBackend object before committing VideoSource metadata. `/api/video_sources` reads the database. CameraManager resolves VideoSource.storage_path through materialize before LocalVideoReader opens it. External mode refuses a local fallback on failed ID resolution.
- Target upload routes original images through storage and commits target/embedding metadata; image retrieval can reload the key from the DB and materialize it. Face algorithms are unchanged.
- DatabaseWorker saves vehicle, plate and face crops through save_image before DB metadata commits; storage failures fail the batch for existing retry handling. Legacy snapshots also use the adapter. DB/object writes are not atomic: failed commits can leave orphan objects.
- ExternalStorageBackend uses the already implemented fsspec provider driver, rejects local/memory/HTTP protocols, supports write/read/exists/delete, and treats its cache as disposable. No provider was selected or invented.

## Confirmed preflight fixes in this continuation

Bootstrap checked sentinel files but did not verify Git. It now checks that the checkout root is the DATT root. The audit omitted business_events, vehicle_passages, cameras and zones from its required tables; these are now checked. Four regression cases migrate an isolated SQLite test DB, remove each required table and verify audit rejection despite revision 0007. These are local preflight tests, not external persistence tests.

Bootstrap checks configuration, dependencies (unless --skip-install), CUDA 12 GPU/ORT, PostgreSQL and vector availability, runs upgrade head, audits revision/extension/tables and external object write/read/delete, checks model files, then execs the backend. The notebook loads Colab Secrets in the kernel and passes them to this helper. The helper was executed with --skip-install and exited 1 at missing configuration; backend startup did not occur. Later checks cannot be claimed to have passed here.

## External validation blocked

DATT_DATABASE_URL, DATT_STORAGE_BACKEND, DATT_STORAGE_URL and DATT_STORAGE_OPTIONS are unset in this process. The repository .env contains a loopback PostgreSQL URL, not external service configuration. Colab Secrets cannot be inspected from this Windows runtime. No actual credentials were printed.

POSTGRESQL_EXTERNAL_SETUP_REQUIRED

Environment / Colab Secret: `DATT_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB?sslmode=require`. URL-encode credentials. Supply an external PostgreSQL server with pgvector available and migration/extension privileges.

EXTERNAL_STORAGE_SETUP_REQUIRED

Environment / same-named Colab Secrets: `DATT_STORAGE_BACKEND=external`, `DATT_STORAGE_URL=<provider-protocol>://<bucket-or-container>/<dedicated-prefix>`, `DATT_STORAGE_OPTIONS=<JSON object of selected driver options/credentials>` (or ambient provider credentials; default `{}`). Install that provider's fsspec driver. Optional `DATT_STORAGE_CACHE` is disposable. Bootstrap sets `DATT_REQUIRE_PERSISTENCE=1`.

The strict diagnostic returned database_connected=false and storage_connected=false. No external migration, object probe, real API E2E or backend/cache-reset test was performed. No video_source_id or storage_key is fabricated. After configuration, run bootstrap and the requested real MP4, target-image and event-image flows, stop backend, discard only disposable cache/staging, restart through bootstrap and re-read those same PostgreSQL IDs and remote objects.

## Occupancy history (separate from main fixes)

Read-only inspection of data/events.db found:

- `events`: 17 legacy records; integer ID, timestamp, camera_id, event_type, old_value, new_value, snapshot_path.
- `vehicle_passages`: 0 records; track/camera/zone, type/color, plate text/status/confidence, direction, first/last seen, duration, vehicle/plate image paths and created_at.
- `sqlite_sequence`: autoincrement bookkeeping.

EventStorage initializes the schema; save_event and save_passage are the legacy writers. Repository search found no production call sites for these writers outside their definitions. Current EventManager.process_frame enqueues BusinessEventDTO with old_count/new_count metadata through DatabaseWorker into PostgreSQL. Thus the previous report overstated ongoing SQLite dependence: current occupancy writes already use PostgreSQL.

EventStorage.get_recent_events/get_event_count_today prefer PostgreSQL business events but fall back to local SQLite on failure. web_server `/api/events` and video_stream `/events` consume these readers. web_server snapshot lookup by uncached legacy ID directly queries SQLite. Losing this file loses 17 historical rows and their numeric-ID-to-image mapping, even if image objects survive remotely. It does not erase current PostgreSQL business-event rows. PostgreSQL display mapping currently substitutes track_id/1 for legacy old/new values; that pre-existing behavior is not changed here.

Minimal separate migration: back up SQLite read-only; import each legacy event into business_events preserving timestamp, camera, counts, snapshot key and a deterministic legacy-ID idempotency key; maintain legacy-ID lookup mapping; copy existing local images under identical keys; reconcile counts and readable objects before switching legacy reads. Import legacy passage records similarly if present. No data migration or EventManager change was made. Preservation of all pre-existing legacy history remains a blocker to a claim that *all* application data survives reset.

## Tests

The system Python lacks dependencies (including Alembic), causing six collection errors; the repository venv was used instead. The updated persistence suite passed 20 tests. These include local SQLite and simulated remote contract tests only.

Previous six failures classified individually:

| Test | Classification | Evidence |
| --- | --- | --- |
| TestMediaPersistence.test_01_upload_mp4_persistence_and_db_record | Missing external service | Requires live configured PostgreSQL; upload now correctly reports failure if DB commit fails. |
| TestMediaPersistence.test_02_target_registration_persistence_and_embeddings | Missing external service | Mocked embedding does not mock PostgreSQL metadata commit. |
| TestMediaPersistence.test_03_event_flow_links_video_source_id | Missing external service | Direct Database transaction needs PostgreSQL. |
| TestTargetAPI.test_register_target_multipart_form | Missing external service | Mocks face extraction, not the database write. |
| TestWebServer.test_static_assets_load | Obsolete test expectation | Expects pollTelemetry, absent in unchanged HEAD JavaScript. |
| TestVideoSources.test_runtime_video_source_switch_and_release | Environment-specific | Asynchronous FFmpeg frame required within one second; mocked resolve scope can expire while background retries continue against mock_switch. Persistence diff affects local-file resolution only, not the YouTube branch. |

Seven PostgreSQL tests require DATT_TEST_POSTGRES_URL (unset). No tests were weakened and no SQLite replacement was used for real E2E. The YouTube failure is outside persistence scope; its precise FFmpeg/timing cause is not proven by static inspection alone.


Completed rerun: the original 48-test selection returned **36 passed, 5 failed, 7 skipped** in 47.77 seconds. The same loopback PostgreSQL URL was retained, adding only connect_timeout=2 in the test process to bound waits. The YouTube switch test passed on this run, supporting the environment/timing classification. Combined with the final 20 persistence tests: **56 passed, 5 failed, 7 skipped** (68 distinct tests). The first unbounded combined attempt was interrupted without completed totals and is not counted. Syntax validation and git diff --check passed.

```text
[DATT_PERSISTENCE_FINAL_AUDIT]
git_branch=main
git_commit=549226811392b379dd337578f0c7c5376705b16d
database_type=postgresql_expected_external_unconfigured
database_connected=false
alembic_revision=unknown_deployed_repository_head_0007
pgvector_version=unknown
storage_backend=local_default_external_unconfigured
storage_connected=false
video_upload_status=NOT_RUN_EXTERNAL_CONFIG_MISSING
video_source_db_status=NOT_VERIFIED_EXTERNAL
video_reload_status=NOT_RUN_EXTERNAL_CONFIG_MISSING
image_persistence_status=NOT_RUN_EXTERNAL_CONFIG_MISSING
event_persistence_status=NOT_RUN_EXTERNAL_CONFIG_MISSING
restart_test_status=NOT_RUN_EXTERNAL_CONFIG_MISSING
occupancy_sqlite_remaining=true_17_legacy_events_0_legacy_passages
tests_passed=56
tests_failed=5
tests_skipped=7
PERSISTENCE_STATUS=BLOCKED
```

Remaining blockers: provision external PostgreSQL/pgvector and the existing fsspec storage configuration above; execute the real external E2E and bootstrap restart acceptance sequence in the configured Colab GPU runtime; preserve/import the 17 legacy SQLite records and any pre-existing local media before a reset if all historical data must survive. Legacy migration remains separately scoped and was not performed.
