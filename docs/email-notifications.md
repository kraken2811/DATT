# Email notification backend

## Existing hook

`EventManager.process_face_matches` builds `FaceEventDTO` and calls
`DatabaseWorker.enqueue_face_event`. Recognition and EventManager are unchanged.
The DB worker now adds an outbox/history row in a savepoint after creating the
FaceEvent, in the same outer transaction. Only `decision == FACE_MATCH` with a
registered target ID qualifies. No threshold or similarity is recomputed.
The email worker sees committed rows only. Missing notification schema is logged
without rolling back FaceEvent persistence; notifications from that interval are
not automatically backfilled. Apply migration before enabling email.

## Configuration

Run the existing migration command (`python scripts/datt.py migrate`) to apply
new revision `0008` on the deployment database. No existing migration is modified.
Only USERNAME, PASSWORD and TO use Colab Secrets. Load them in the notebook
kernel before launching the backend. Other settings are optional environment
variables; Gmail defaults require no additional Secrets:

- `DATT_EMAIL_HOST` (default smtp.gmail.com), `DATT_EMAIL_PORT` (default 587)
- `DATT_EMAIL_USERNAME`, `DATT_EMAIL_PASSWORD` (Gmail SMTP app password)
- `DATT_EMAIL_FROM` (defaults to DATT_EMAIL_USERNAME), `DATT_EMAIL_TO` (comma-separated recipients)
- `DATT_EMAIL_TLS`: `starttls` (default) or `ssl`; plaintext disabled
- `DATT_NOTIFICATION_COOLDOWN_SECONDS`: default 300, nonnegative
- `DATT_NOTIFICATION_MAX_RETRIES`: default 3, allowed 0 through 10
- `DATT_NOTIFICATION_RETRY_SECONDS`: default 30, positive; exponential delay capped at 3600 seconds

For Colab, before starting the existing CLI:

```python
from src.notifications.config import load_colab_secrets
load_colab_secrets()
```

The CLI/persistence launcher is unchanged. Environment is inherited by backend
children. Startup logs only `[NOTIFICATIONS] CONFIGURED=true/false`; credentials
are never logged. Missing/invalid configuration disables the email worker without
crashing CV; qualifying events get `failed` history with `CONFIGURED=false`.
Those disabled-period events are not retroactively sent after configuration.
No API/frontend or recipient management interface is introduced.

## Delivery and history

Revision `0010` extends this same outbox to Vehicle Watchlist matches through
`plate_event_id` and `vehicle_watchlist_id`; each row references either a FaceEvent
or a PlateEvent. The worker, SMTP adapter and retry behavior are shared. See
[backend integration](backend-completion.md) for vehicle cooldown and cloud checks.

`notifications` stores event/target IDs, camera, channel, recipient, status,
retry_count, safe error code, timestamps and a payload snapshot. Payload stores
an evidence object key, never a temporary URL. Target and camera identify the
cooldown scope (per email recipient); pending/sent rows reserve the cooldown.
Suppressed events have their own history, do not extend the cooldown, and are
never sent. PostgreSQL target-row locks serialize concurrent reservations.

`NotificationService` dispatches through a channel adapter; only SMTP Email is
implemented. A dedicated daemon worker polls the durable DB queue, downloads
optional evidence through existing Storage, and sends TLS-protected SMTP email.
The message includes target name/ID, camera ID, UTC event time, similarity when
present and FaceEvent ID. Evidence is attached if readable and <=5 MiB; otherwise
a text alert notes that evidence is unavailable. Existing face crops are JPEG.
No provider calls occur on the CV or persistence worker thread.

Pending jobs survive process restarts. PostgreSQL `FOR UPDATE SKIP LOCKED`
prevents concurrent workers sending the same row while a delivery is in progress.
A row lock is held during transport; SMTP sockets have a 15-second timeout.
Initial attempt plus at most `MAX_RETRIES` retries are made for normal delivery
failures. Raw SMTP/Storage exception text is neither persisted nor logged.
Delivery is **at least once**: a crash after SMTP accepts a message but before the
DB commits can resend it. A stable Message-ID helps correlation but is not an
exactly-once guarantee. SQLite is for single-worker tests/development only.

## Validation

`python -m pytest tests/test_notifications.py -q` uses migrated temporary SQLite,
fake adapters and synthetic evidence. It never sends a real email. Production
PostgreSQL locking and SMTP delivery require deployment verification with an
explicitly configured provider and recipient. Cloud verification on 2026-10-01 used the existing Colab T4 runtime and
Supabase PostgreSQL/Storage. All three email Secrets were configured. After a
CLI backend restart, a synthetic FaceEvent was queued through NotificationService;
the backend worker delivered it with status `sent`, retry_count `0`, and SMTP
acceptance. Synthetic JPEG attachment construction was verified against Storage.
Only that test's DB rows and Storage object were cleaned up. SMTP acceptance is
not a guarantee that the recipient's inbox has displayed the message.
