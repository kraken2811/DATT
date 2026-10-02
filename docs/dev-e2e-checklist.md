# Dev final-flow verification

This branch prepares the final production test. It is not a claim of complete
E2E acceptance. The archived vehicle-intelligence candidate remains rolled
back; no candidate modules, model binaries, runtime data or credentials belong
in this change.

## Supported behavior

- Manual camera capture saves a fresh raw JPEG to configured Storage and
  displays its returned URL without creating an Event Center record.
- Person detection status follows current people-count telemetry. It does not
  imply that a face-watchlist identity has been confirmed.
- Normal person/vehicle detections do not create new persisted events.
- Active face and exact normalized plate-watchlist matches use existing
  recognition decisions and notification cooldowns. Linked new event rows
  appear as one logical Event Center record; history remains accessible.
- Crowd: more than 40 people continuously for 180 seconds, once per episode.
  Vehicle congestion: more than 40 cars plus motorcycles, immediately once
  per episode. Counts are per camera and selected location/zone.
- Oversized Storage uploads return HTTP 413; backend unavailability and source
  selection timeouts remain explicit errors rather than false success.

## Remaining acceptance decisions

1. Vehicle Watchlist currently supports plate rules only. Color-only and
   combined plate/color matching require an agreed contract/schema extension.
2. The last live audit found the selected target threshold at 0.10, while a
   prior acceptance request specified 0.40; the code default is 0.45. No stored
   threshold or recognition logic was changed. Agree the intended value before
   scoring face acceptance.
3. Live event writes, Storage evidence and actual email delivery must be tested
   together in a designated test environment. Prior audit video runs suppressed
   writes and used isolated transaction/Storage and mocked transport tests.
4. Windows Application Control blocks local Torch DLL loading (WinError 4551).
   Run real model/video regression in the already working Colab GPU runtime.
   Do not interpret isolated test passes as model accuracy or GPU acceptance.

## Final-flow checks

Run `python scripts/test_dev.py` with the existing environment for the focused
regression suite. It creates a disposable SQLite schema and local Storage and
suppresses background event writes; individual persistence tests use their own
fixtures. It does not run the legacy full suite or real GPU/video acceptance.
On 2026-10-02 this command completed with **143 passed**, zero failed and four
dependency deprecation warnings. Python compilation, JavaScript syntax and
Git whitespace checks also passed. Protected face/OCR/tracker/config source
hashes matched the preceding audit snapshot.

Use the existing configured runtime and `START DATT` cell described in
[Colab startup](colab-startup.md). Confirm that the deployed checkout matches
the intended dev commit; pushing Git alone does not update a running process.

1. Check `/healthz`, `/startup-health`, all production screens and workers.
   Open the frontend on port 8501, not the monitor on port 8000.
2. Upload/select a test video, confirm fresh telemetry and person status,
   capture an image, reopen its URL and confirm Storage persistence. Exercise
   an oversized upload and verify a clear HTTP 413 without a partial library row.
3. In a designated test database/bucket, exercise active and inactive watchlist
   targets, normal detections, crowd duration/reset and congestion reset.
4. Check event deduplication, evidence URLs, outbox state, notification cooldown
   and delivery using a designated recipient. Do not use historical production
   data for cleanup or run destructive test fixtures against it.
5. While inference is active, inspect `/api/runtime_devices` for the live YOLO,
   SCRFD, AdaFace and OCR instances. AdaFace uses ONNX CUDA with NumPy host
   inputs; an idle/lazy model can legitimately be uninitialized.
6. Restart only the owned DATT service and verify health, history, media URLs
   and workers again. Record failures and untested checks explicitly.
