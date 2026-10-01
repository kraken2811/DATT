# Backend integration: cameras, Event Center, vehicle email

Apply `python scripts/datt.py migrate` before starting this source. Revision 0010
follows 0009 without altering prior migrations. It extends the existing cameras,
FaceEvent camera metadata, and notifications tables; it creates no third source
registry and no duplicate event store. Uploaded files stay in video_sources and
Supabase Storage.

Camera API: GET/POST `/api/cameras`, GET/PATCH/PUT/DELETE `/api/cameras/{id}`, and
POST `/api/cameras/{id}/{enable,disable,test}`. Existing Camera Management aliases
under `/api/camera_management/cameras` and `/api/manage/cameras` are retained,
as is POST `/api/camera_management/test_connection`.
Both `camera_name/source_url/location` and FE `name/url/zone` fields are accepted.
`online` is observed from a live runtime lease, not claimed from user input;
`offline` means enabled but not currently active, `disabled` prevents activation.
File sources must reference a registered ready video_sources Storage key.

Existing `/cameras` selection includes DB entries; `switch_camera` resolves the
latest DB source. `select_source` accepts camera_id or resolves an existing exact
source URL, so disabled records cannot be bypassed by old client source payloads.
Source updates take effect on the next activation. CameraManager reuses existing
readers, records a 90-second lease and renews it outside the CV thread every 10
seconds. Stop clears the lease; lost renewal stops the reader. Delete or disable
of a live camera returns 409 CAMERA_ACTIVE_STOP_FIRST: stop it with the existing
stop-camera action first. Delete of referenced event history returns 409 and
preserves all history. No pipeline/model/threshold or EventManager logic changes.

Connection testing uses a separate, hard-bounded 10-second subprocess. It reads a
frame (or validates a CCTV snapshot image), rather than claiming a URL/port is a
working stream. Response includes success, code and measured latency_ms. TLS
verification remains enabled. YouTube uses the existing yt-dlp dependency.

Import existing JSON explicitly:
`python -m src.cameras.import_registry data/camera_registry.json --legacy-timezone Asia/Ho_Chi_Minh`.
Legacy non-UUID IDs are kept as registry_key aliases with deterministic UUIDs.
Import is transactional/idempotent and rejects conflicts without overwriting rows.
Original JSON is retained; the backend never reads it during runtime requests.
Existing YAML sources remain compatible; newly managed cameras live only in DB.

Event Center: GET `/api/event_center/events`,
GET `/api/event_center/events/{type}:{uuid}` and `/evidence` below that detail URL.
Types: face, plate, vehicle, passage, business. These identify the existing source
tables; watchlist matches are face/plate events with watchlist_match=true, not
extra duplicated events. Existing monitoring/history routes are unchanged.
Filters: camera/camera_id, event_type, target_id, exact normalized plate,
watchlist_match=true/false, from/to (timezone-aware ISO8601), notification_status.
Pagination: page>=1, page_size=1..200 (default 50); sort=asc/desc by timestamp with
stable type/ID tie-breakers. Events use namespaced IDs to avoid table collisions.
For multiple recipients notification_status summarizes failed > pending > sent >
suppressed; its filter matches any recipient's status. Recipients are not exposed.
Evidence is fetched only by event ID and its stored, validated Storage key; no
arbitrary URLs/paths are accepted. Only JPEG/PNG/WebP <=10 MiB are served with
nosniff and private/no-store. Legacy missing camera/evidence stays null; no
invented metadata. API inherits the existing backend access boundary.

Vehicle MATCH queues email in the same persistence transaction via a savepoint,
using the existing notifications table/worker/retry/cooldown. Face behavior is
preserved. Vehicle cooldown is separate from Face and scoped to watchlist ID,
camera, recipient. Only existing active exact matches qualify. Email includes
plate, display name, camera, UTC time, OCR confidence, PlateEvent ID and optional
plate evidence. Owner contact details are intentionally not copied into email.
`src.notifications.base.NotificationAdapter.send(notification)` is the shared
extension contract for future Telegram/Slack; fake-channel tests verify dispatch.
No live Telegram/Slack provider or credentials are introduced.

Camera previews are available at `/api/cameras/{id}/thumbnail` and supplied in
both thumbnail/thumbnail_url fields. They use bounded source probes, a small
90-second cache and the existing placeholder; disabled cameras are not probed.
Preview source URLs remain server-side. The FE `hls` value is retained in
source_type while runtime type remains direct_hls. The switch-camera proxy uses
30 seconds (previously 6) so Storage/DB-backed source initialization can finish;
this does not change CV timing or thresholds. Video sources referenced by cameras
return 409 on deletion; metadata and Storage files remain intact.

Deployment verification (2026-10-01): the existing Colab T4 runtime was preserved.
Supabase PostgreSQL 17.11, pgvector 0.8.2 and migration 0010 passed checks;
Storage upload/read/cleanup passed. Eight legacy cameras were imported, with
zero additional imports on rerun. Synthetic camera CRUD, disabled activation,
frame probing, Camera Selection, Monitoring, JPEG thumbnail and linked-video
deletion protection passed. Event Center verified all five types, filters,
pagination, detail, evidence and notification links.

The backend worker sent one synthetic Vehicle alert and one synthetic Face alert
per configured recipient, with retry_count=0 and SMTP acceptance. Both used
synthetic Storage evidence. SMTP acceptance does not guarantee inbox display.
After another CLI backend restart, camera/event/notification data and evidence
remained readable. Only this verification's DB rows and Storage objects were
cleaned up; final backend health was HTTP 200. No runtime reset or Git push ran.

Local validation: 129 focused tests passed, followed by the additional linked
video deletion regression test passing (130 unique tests, zero failures).
Frontend files were hash-checked unchanged during this task.
