# Supabase media persistence

The existing PostgreSQL schema (Alembic 0007) keeps relative media keys. The
Supabase adapter stores binary data in a private bucket under those same keys.
No signed URLs or credentials are saved in application metadata. OpenCV receives
a disposable materialized cache; a fresh process can download the original again.

## Configuration

Set these environment variables or same-named Colab Secrets:

- `DATT_DATABASE_URL`: existing PostgreSQL connection.
- `DATT_STORAGE_BACKEND`: `supabase`.
- `SUPABASE_URL`: HTTPS project origin.
- `SUPABASE_SERVICE_ROLE_KEY`: server-only legacy service-role JWT or modern
  Supabase secret API key. Modern keys use the `apikey` header without a JWT bearer.
- `DATT_STORAGE_BUCKET`: existing private bucket name, case-sensitive;
  `SUPABASE_STORAGE_BUCKET` is also accepted.
- `DATT_STORAGE_CACHE`: optional disposable cache directory.

Do not paste credentials into notebook code/output, source files or chat. The
notebook bootstrap loads Secrets and refuses local storage in persistent mode.
Set the bucket file-size/MIME limits to accommodate the intended MP4 uploads.
The adapter uses authenticated REST requests, bounded timeouts, streamed upload
and download, and redacted errors. It does not require a new Supabase SDK.
Existence checks use a streamed one-byte GET: Supabase may return HTTP 400 for
missing objects, with `NoSuchKey` / statusCode 404 in the JSON body. HEAD omits
that body and cannot safely distinguish a missing object from other HTTP 400s.

## Existing media

Before changing a running backend, stop its tracked process to avoid concurrent
local writes. Run `python scripts/migrate_media_to_storage.py` with remote storage
configured. It copies videos, target originals and event images, verifies SHA256,
retains all local originals and DB keys, and stops on a conflicting remote object.
It cannot recover files already lost in a previous Colab reset. Local legacy
`events.db` metadata is not migrated by this binary-copy command; historical
numeric event IDs still need their existing metadata or a separate import.

## Validation

`python -m pytest tests/test_supabase_storage.py tests/test_persistent_storage.py -q`
tests the adapter and existing media paths locally with simulated remote transport.
This is not evidence of cloud durability.

With real PostgreSQL and Storage configured, set
`DATT_RUN_SUPABASE_MEDIA_TEST=1` and run
`python -m pytest tests/test_supabase_media_live.py -q`.
The opt-in test uploads a synthetic MP4 and target image through actual handlers,
writes vehicle/plate/face images through DatabaseWorker, and launches a fresh
interpreter with a new empty cache to read DB keys, decode media and serve image
endpoints. Only face embedding extraction is mocked. Synthetic fixtures are
uniquely named and retained; no existing records or objects are deleted.

Current implementation does not make PostgreSQL and Storage a single atomic
transaction: failed metadata commits may leave orphan objects. Storage failures
must not produce successful uploads. Existing worker retry behavior is retained.

REST reference: https://supabase.com/docs/reference/self-hosting-storage/retrieve-an-object
