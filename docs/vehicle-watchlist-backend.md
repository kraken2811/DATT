# Vehicle Watchlist backend

## Current confirmed-plate and color contract

Revision **0011** adds nullable `vehicle_watchlists.vehicle_color`. Accepted
values are `black`, `white`, `gray`, `silver`, `red`, `blue`, `green`, `yellow`,
`orange`, `brown`, `other`; null means not declared. Create/update/list/detail
use the existing API. Name/owner columns remain for compatibility but are
removed from the Vehicle UI. The migration is included in source and tested
on isolated SQLite; it has **not** been applied to production by this change.
Deploying this backend against schema 0010 requires the normal migration first.

OCR engine, preprocessing, normalization and confidence thresholds are retained.
Bounded distinct-frame observations use exact-string, confidence/quality-weighted
voting, the configured minimum observation count and agreement ratio. Only
`CONFIRMED` plus `confirmed_plate` enters persistence/watchlist matching.
Watchlist data is never an input to OCR consensus. Normal/unconfirmed vehicles
do not create new persisted watchlist events.

Matching remains **PLATE ONLY**. The existing DB worker first checks an active
exact normalized plate match, then enriches the same logical event using the
best sampled vehicle crop. Color never decides the match. Metadata snapshots
`watchlist_vehicle_color`, `detected_vehicle_color` and
`detected_vehicle_color_confidence`; later edits to the Watchlist do not rewrite
event history. Confidence is the existing HSV classified-pixel fraction, not
a calibrated probability. Gray/silver remains ambiguous in this extractor;
unavailable evidence yields `unknown` and 0. No PP-Vehicle model is introduced.

Existing VehicleEvent/PlateEvent/BusinessEvent linkage, Event Center projection
and notification outbox are reused. There is no separate color event, Alert
store, or new notification policy. Alert Center now provides a read-only view
of Notification delivery history through `/api/alerts`; see
[the Email/Alert contract](alert-center.md). There is no separate Alert entity
or acknowledge/resolve workflow.

Run `python scripts/test_dev.py` for isolated regressions. Actual video accuracy
and full Event-to-Alert acceptance are not established by these tests.

## Original backend implementation and historical verification

`/api/watchlist/vehicles` and `/watchlist/vehicles` now use the deployment
`Database`, including Supabase PostgreSQL. The existing UI contract keeps `name`
as an alias for DB `display_name`, plus `normalized_plate`, detection counts,
last-seen time, and the existing detail/history routes. No UI files are changed.

Apply `python scripts/datt.py migrate` before starting the new backend. Revision
0009 follows 0008; it creates `vehicle_watchlists` and `vehicle_watchlist_results`,
and backfills an indexed `plate_events.normalized_plate` without changing OCR
text or deleting existing events. Normalization removes ASCII punctuation and
whitespace and uppercases ASCII letters; lookup is exact, never substring-based.
A unique DB constraint rejects duplicate normalized plates across workers.

The existing DatabaseWorker records the lookup in the same transaction as the
finalized passage's PlateEvent. Only active entries match. Every lookup has a
MATCH/NO_MATCH result linked to its PlateEvent. A snapshot of the display name
survives watchlist deletion; disabling an entry affects future matches only.
History remains sourced from PlateEvent, including pre-migration detections.
No historical MATCH is invented for old detections. History returns the latest
100 matching events and the full matching count, with actual camera information
when available (otherwise null).

No runtime API reads/writes `data/vehicle_watchlist.json`. Preserve an existing
JSON file and import it once, explicitly:

```
python -m src.watchlists.import_vehicles data/vehicle_watchlist.json
```

Imports preserve IDs and fields, are transactional and idempotent, and refuse
conflicts rather than overwriting existing DB entries. Legacy naive timestamps
are interpreted as UTC (Colab); for local Vietnam exports pass
`--legacy-timezone Asia/Ho_Chi_Minh`. The original JSON is never deleted.

Validation: `python -m pytest tests/test_vehicle_watchlists.py tests/test_notifications.py tests/test_target_api.py -q`.
Tests use temporary migrated SQLite and fake email transports; cloud checks use
unique synthetic records only. No OCR/model/threshold or EventManager changes.

Cloud verification (2026-10-01): Supabase revision 0009 applied; live API CRUD,
duplicate rejection, active/disabled lookup, and DatabaseWorker PlateEvent
integration passed. A separate backend process reloaded both the watchlist and
MATCH/NO_MATCH history from PostgreSQL. Synthetic fixture rows were cleaned up;
Colab kernel PID was unchanged. One immediate CLI restart encountered a released
listener whose port was temporarily unavailable (errno 98); starting again after
port release succeeded without changing CLI or resetting Colab. Local focused
regression suite: 90 passed (vehicle, notification, Face API, storage and CLI).

Two existing local JSON entries were imported to Supabase with their original IDs
and Asia/Ho_Chi_Minh legacy timestamps. A second import inserted zero rows; both
IDs were verified through the live API. Original JSON files remain intact.
