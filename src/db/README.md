# DATT database layer

Independent SQLAlchemy 2 layer. No runtime/OCR imports, background threads,
automatic migrations, or database writes on import. Repository calls are
synchronous: invoke them from a dedicated persistence worker, never the AI loop.

## Setup and migrations

Run from the project root using the project virtualenv:

```powershell
.\venv\Scripts\python.exe -m pip install -r src/db/requirements.txt

# Preferred deployment: PostgreSQL, database already provisioned.
$env:DATT_DATABASE_URL = 'postgresql+psycopg://user:password@localhost:5432/datt'

# Local/demo alternative (parent directory must exist).
$env:DATT_DATABASE_URL = 'sqlite:///data/datt.db'

.\venv\Scripts\python.exe -m alembic -c src/db/alembic.ini upgrade head
.\venv\Scripts\python.exe -m alembic -c src/db/alembic.ini current
.\venv\Scripts\python.exe -m unittest discover -s tests -p test_db.py -v
```

Choose one URL assignment. Without a URL, `Database()` and Alembic default to
`sqlite:///datt.db`, relative to the working directory. `postgresql://` URLs are
normalized to the psycopg 3 driver. Credentials belong in the environment.
No changes to the application's config.py or shared requirements are needed.

Revision `0001` creates all six tables, foreign keys, and indexes. It is a frozen
schema definition independent of application models. For a future schema change:

```powershell
.\venv\Scripts\python.exe -m alembic -c src/db/alembic.ini revision --autogenerate -m describe_change
.\venv\Scripts\python.exe -m alembic -c src/db/alembic.ini upgrade head
.\venv\Scripts\python.exe -m alembic -c src/db/alembic.ini check
```

Review generated migrations before applying. `downgrade base` removes these
tables and their data; tests exercise this only against disposable databases.

## Schema

All primary keys are application-generated UUIDs. All timestamps are aware UTC
datetimes; naive input raises an error. SQLite reads regain the UTC timezone.
Defaults (UUID, timestamps, booleans, status, empty metadata) are supplied by
SQLAlchemy, so raw SQL writers must supply those values explicitly.

| Table | Columns besides id |
| --- | --- |
| cameras | name, source_type, source, location?, enabled, created_at, updated_at |
| zones | camera_id, name, polygon, enabled, created_at, updated_at |
| targets | name, target_type, embedding?, reference_metadata, image_path?, active, created_at |
| detection_events | camera_id, event_type, frame_id, timestamp, track_id?, class_name?, confidence?, bbox?, snapshot_path?, metadata |
| vehicle_events | detection_event_id, vehicle_class, track_id, zone_id?, first_seen, last_seen |
| plate_events | vehicle_event_id, plate_text, confidence?, plate_bbox?, plate_crop_path?, status, created_at |
| face_events | detection_event_id, target_id?, track_id?, similarity?, decision, face_crop_path?, created_at |

`?` means nullable. `vehicle_events.zone_id` remains an external string identifier for compatibility;
it is not yet a foreign key. New writers may store the string form of a zones UUID.
The new `zones.camera_id` foreign key references cameras with RESTRICT deletion. Track IDs and frame IDs are integers. Track IDs are not globally
unique; queries should also scope detection events by camera and time/session.
Use detection metadata to record a source-session identifier where needed.
Type/status/decision strings are intentionally extensible, not database enums.

JSON uses JSONB on PostgreSQL and JSON on SQLite. `embedding` stores a list of
floats, not a vector-search index. Reference metadata can include model/version
and external embedding references. Bboxes use `[x1, y1, x2, y2]`; callers should
record image dimensions/coordinate conventions in metadata. Images remain in
external storage, with only paths stored here.

SQL column `metadata` is exposed as `DetectionEvent.event_metadata` because
`metadata` is reserved by SQLAlchemy. Replace the complete JSON value through
`repository.update(...)`; in-place nested dictionary/list changes are not tracked.

## Relationships and deletion

```mermaid
erDiagram
    cameras ||--o{ zones : defines
    cameras ||--o{ detection_events : captures
    detection_events ||--o{ vehicle_events : describes
    vehicle_events ||--o{ plate_events : reads
    detection_events ||--o{ face_events : recognizes
    targets o|--o{ face_events : matches
```

Relationships are enforced with database foreign keys; ORM lazy-loading
relationships are deliberately absent. Multiple vehicle/face details and plate
readings per parent are permitted.

- Camera deletion is restricted while detections exist; use `enabled=False`.
- Deleting a detection cascades to its vehicles, plates, and face events.
- Deleting a vehicle cascades to plate readings.
- Deleting a target sets face-event target_id to NULL, retaining event history.

Indexes cover camera_id, timestamp, event_type, every track_id, plate_text,
target_id, and all child-event foreign keys. SQLite foreign-key enforcement is
enabled for every connection.

## Repository and transaction API

Each entity has a repository exported from `src.db.repositories`:
CameraRepository, ZoneRepository, TargetRepository, DetectionEventRepository,
VehicleEventRepository, PlateEventRepository, FaceEventRepository.

All support `create(**fields)`, `get(id)`, `list(limit=100, offset=0, **filters)`,
`update(id, **fields)`, and `delete(id)`. Missing get/update returns None; delete
returns a boolean. Lists accept equality filters and stable UUID ordering.
DetectionEventRepository.query additionally supports camera_id, event_type,
track_id, since inclusive, until exclusive, and newest-first pagination.
Page size is capped at 1000. Invalid fields are rejected; IDs and creation/update
timestamps cannot be manually mutated through repository methods.

```python
from src.db import Database
from src.db.repositories import (
    CameraRepository, DetectionEventRepository,
    VehicleEventRepository, PlateEventRepository,
)

db = Database()  # Reads DATT_DATABASE_URL; migrations run separately.
try:
    with db.transaction() as session:
        camera = CameraRepository(session).create(
            name="Gate", source_type="file", source="demo.mp4")
        detection = DetectionEventRepository(session).create(
            camera_id=camera.id, event_type="vehicle", frame_id=42,
            track_id=7, event_metadata={"source_session": "demo-session"})
        vehicle = VehicleEventRepository(session).create(
            detection_event_id=detection.id, vehicle_class="car", track_id=7)
        PlateEventRepository(session).create(
            vehicle_event_id=vehicle.id, plate_text="30A12345", status="confirmed")
    # All four inserts commit together. Exceptions roll back all four.
finally:
    db.dispose()
```

Repositories flush to obtain IDs and validate constraints but never commit.
Let database exceptions leave the transaction context; do not catch them and
continue using a failed session. Each thread/batch owns a separate session.
The engine may be shared across threads; create a new engine after a process fork.
For threaded SQLite workers, use a file database, not `:memory:` (which is
connection-scoped). SQLite has a 5-second busy timeout; it can block a worker.

## Future Observation/Event integration (not implemented here)

1. Map finalized Observation/Event data to a small immutable DTO: camera ID,
   source session, captured UTC time, track/frame IDs, result fields, image paths.
   Do not enqueue frames, ORM objects, or sessions.
2. The AI loop calls `put_nowait` on a bounded queue. On full queue, apply an
   explicit drop/coalesce policy and increment a metric; never wait for DB I/O.
3. A dedicated worker maps DTOs to repositories and writes small batches inside
   `db.transaction()`. Create parent and child events within the same transaction.
4. Retry transient database errors with bounded backoff in the worker. Add a
   stable observation/event idempotency key plus a unique constraint in a future
   migration before enabling retries after uncertain commits. Current inserts
   are not idempotent across repeated calls.
5. Monitor queue depth, dropped events, write latency, retry count, and failures.
   Shut down with a bounded drain deadline. If losing queued events is unacceptable,
   use a durable broker/spool outside the AI thread; an in-memory queue is not durable.

## Validation

`tests/test_db.py` runs eleven tests against databases created by the real migration:
CRUD, event graph insert/query/update, UTC/JSON round-trip, paging, whole-graph
rollback, failed-FK rollback and recovery, delete policies, naive timestamp
rejection, required indexes, schema drift, and upgrade/downgrade/upgrade.
It also generates PostgreSQL migration SQL and checks UUID/JSONB/timestamptz.
Real PostgreSQL tests are in `tests/test_db_postgres.py`; see the Docker workflow below.

Transaction boundaries follow the [SQLAlchemy session documentation](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).
Migration setup follows the [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).


## Docker + real PostgreSQL

Services: `postgres` (`postgres:17-bookworm`) and opt-in `db-tools` (Python 3.11,
SQLAlchemy/Alembic/pytest only, no AI packages). PostgreSQL binds to loopback only.
The named volume is exactly `datt_postgres_data`, mounted at
`/var/lib/postgresql/data`. The healthcheck uses `pg_isready`; db-tools waits for
`service_healthy`. Docker startup does not run migrations automatically.

On this workstation `.env` uses host port **64646**, because 5432 and 55432 are
occupied by other applications. The example keeps 5432 as a configurable default.

Create `.env` from `.env.example` if absent and supply POSTGRES_PASSWORD. This
workspace has an ignored `.env` with a randomly generated password. Do not replace
an existing password after initializing the volume: changing environment values
alone does not change the database role's stored password.

The optional DATT_DATABASE_URL in `.env` is a **container** override (host
`postgres`, port `5432`). Leave it empty to construct the URL from POSTGRES_*
without password-escaping mistakes. Host commands use `127.0.0.1` and the mapped
POSTGRES_PORT instead. Never print or commit connection URLs containing passwords.

### Host workflow (PowerShell)

```powershell
. ./venv/Scripts/Activate.ps1
python -m pip install -r src/db/requirements-dev.txt
. ./src/db/activate.ps1

docker compose up -d
docker compose ps
# Wait for postgres to report healthy, or use: docker compose up -d --wait
alembic upgrade head
alembic current
pytest tests/test_db.py

$env:DATT_TEST_POSTGRES_URL = $env:DATT_DATABASE_URL
pytest tests/test_db_postgres.py -v

# Host-only opt-in: restarts the Compose postgres service.
$env:DATT_TEST_POSTGRES_RESTART = '1'
pytest tests/test_db_postgres.py -v
Remove-Item Env:DATT_TEST_POSTGRES_RESTART
```

`activate.ps1` sets ALEMBIC_CONFIG so bare `alembic` commands find the DB migration
configuration. It reads simple KEY=VALUE entries (optional surrounding quotes),
not multiline values, interpolation, or inline comments. For this workflow use a
random hex password to avoid shell/.env interpolation differences.

### Container workflow

```powershell
docker compose up -d --wait
docker compose build db-tools
docker compose run --rm db-tools alembic upgrade head
docker compose run --rm db-tools alembic current
docker compose run --rm db-tools python -m pytest tests/test_db.py -q
```

The DB tools image contains only src/db, src/__init__.py and DB tests. It runs as
an unprivileged user and has no Docker socket access. Run the restart test from
the host, not this image. Ordinary `docker compose up -d` starts only PostgreSQL.

### Migration and integration coverage

Head revision: **0002**, following **0001**. Revision 0002 adds zones (UUID, camera
FK, name, polygon JSONB/JSON, enabled, UTC created_at/updated_at, camera_id index).
Polygon convention: a list of at least three `[x, y]` vertices in source-image
coordinates; the DB stores JSON without geometric validation. Existing cameras
and events survive upgrade and downgrade of revision 0002. The vehicle zone_id
column is intentionally unchanged to preserve existing string identifiers.

SQLite tests cover zone CRUD, FK enforcement, index/schema parity, and migration
preservation. Real PostgreSQL tests require DATT_TEST_POSTGRES_URL; absent that
variable they explicitly skip. Each test creates a random isolated schema,
upgrades it to head, and removes only that schema afterward. The test role needs
CREATE SCHEMA privilege. No existing application tables are downgraded or cleared.

Real tests cover connection, migration, JSONB, schema parity, camera/zone insert,
detection -> vehicle -> plate, target/face, UTC, queries, transaction rollback,
FK errors and session recovery. The persistence test is separately opt-in: it
checks the selected container's published port and named-volume mount, commits
an event graph, restarts postgres, waits for healthy status, and reloads the same
UUIDs through a fresh connection. Restart briefly interrupts all clients of this
local PostgreSQL service; use it during development. Tests are not parallelized.

### Start, stop, backup, restore

```powershell
# Start / stop (preserves named volume)
docker compose up -d --wait
docker compose stop
# Remove containers/network, retaining data volume
docker compose down
# Start again using the same volume
docker compose up -d --wait

# Backup: binary custom format via file/copy, safe in Windows PowerShell.
New-Item -ItemType Directory -Force backups | Out-Null
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/datt.dump'
docker compose cp postgres:/tmp/datt.dump backups/datt.dump

# Restore into a NEW database; does not overwrite datt.
docker compose cp backups/datt.dump postgres:/tmp/datt-restore.dump
docker compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" datt_restored'
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d datt_restored --no-owner --exit-on-error /tmp/datt-restore.dump'
```

Use a unique new database name for each restore. Do not use `docker compose down
-v` when retaining data: it deletes the named volume. A restart test checks local
persistence, not backup durability; retain backups outside Docker's storage.

Configuration follows [Docker Compose health dependencies](https://docs.docker.com/compose/how-tos/startup-order/)
and the [official PostgreSQL image](https://hub.docker.com/_/postgres).
