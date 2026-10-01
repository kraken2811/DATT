# Persistence audit (before implementation)

Inspected config.py, DB engine/session handling, models/repositories, migrations
0001–0007, web_server, video_stream, CameraManager, DatabaseWorker, EventStorage,
media tests, and requirements-colab.txt.

- Compose provides pgvector/pgvector:pg17 with a named Docker volume. This survives
  container restart on the same host, not deletion of a Colab VM.
- Database reads DATT_DATABASE_URL or .env, normalizes PostgreSQL to psycopg, and
  otherwise silently opens datt.db. Alembic has the same SQLite default.
- Existing schema already holds targets, 512D embeddings, video sources,
  detection/vehicle/plate/face events, passages, business events, cameras and zones.
  Revision 0003 creates vector; 0005 adds videos; HEAD is 0007. No schema redesign
  is needed. Repositories commit through transaction-scoped sessions.
- MP4 uploads go to data/uploads/videos; target originals to data/uploads/targets.
  DB rows store relative paths. Upload/target handlers previously swallowed DB
  failures. Video selection and image serving assumed those paths existed locally.
- DatabaseWorker writes vehicle, plate and face crops under data/events before
  persisting metadata. EventStorage also writes snapshots there.
- Legacy occupancy history and legacy passage copies use data/events.db directly.
  They are separate from Phase 6/7 PostgreSQL business events. Preserving that
  legacy history would require a separate migration; it is NOT durable here.
- OCR/face diagnostic dumps, downloaded videos/models, logs and caches are local
  runtime artifacts. They are not application evidence storage.
- Colab installs GPU dependencies and launches the app without migration or
  external DB/storage preflight. /content and all local media disappear on reset.

Implementation scope: retain the schema and CV algorithms; route media I/O through
one storage interface; add strict deployment preflight and reproducible bootstrap.
Cloud/reset durability cannot be asserted until external E2E validation passes.
