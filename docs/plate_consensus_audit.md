# Plate consensus audit

The supplied confidence sequence explains the single vote without a state reset.
The previous consensus gate required confidence >=0.65 and quality >=55. Of
0.454, 0.614, 0.630, 0.693, 0.401, only 0.693 can vote. The reader accepts
confidence >=0.35. Format-valid reader results therefore entered history but
were excluded from the Counter. A regression reproduces five history entries,
one eligible entry, and CHECKING with the original gate settings. This explains
the provided excerpt; it does not prove no other resets occurred in Colab.

## Lifecycle trace

1. The reader evaluates preprocessing variants and returns one PlateCandidate.
2. The worker passes that candidate and the job's track/frame/generation to
   `_apply_ocr_result` under the manager lock.
3. The manager looks up the persistent state, rejecting missing states, mismatched
   generations, and frames <= the last applied result. It does not replace state.
4. Raw and normalized strings pass the unchanged Vietnamese validator. Finite
   confidence and quality and configured observation floors determine eligibility.
5. One history entry is appended; only entries beyond the bounded history size
   are trimmed. There is no frame-age expiration of the vote window.
6. The Counter counts eligible exact normalized strings. Previously the extra
   confidence gate excluded four of the five supplied readings.
7. Any votes produce CHECKING; >=3 exact votes and >=75% history agreement
   produce RECOGNIZED. Confirmed text is now retained for the track lifetime.

## Other lifecycle findings

- State creation occurs only when the track ID is absent; class jitter updates
  `vehicle_class`, not consensus history.
- Pending job replacement changes jobs, not plate state. In-flight jobs update
  the persistent dictionary entry only after checking generation and frame ID.
- Snapshot copies from `get_all_plate_states` are not written back by the worker.
- The application explicitly resets on camera activation/switch.
- A separate reuse bug refreshed last-seen before checking TTL. A returning ID
  after a long unobserved gap could inherit votes. Expiration now precedes refresh,
  assigning a new generation and rejecting old in-flight results.
- Explicit reset clears queued work and state under the same manager lock.
- TTL and explicit resets now log track_id, frame_id, and reason.

## Changes and validation

Observation defaults now match the reader's 0.35 acceptance floor, with crop
quality used for selection rather than a second default vote veto. Explicit
confidence/quality overrides remain supported. This changes which observations
can vote; the >=3 distinct-frame requirement and 75% agreement are unchanged.
Vietnamese validation, GPU initialization, detector/tracker implementations,
face recognition, and persistence are unchanged.

Tests cover the supplied sequence, original-gate reproduction, same-frame
variants, duplicate delivery, conflicts, bounded history, class jitter, TTL reuse,
reset during in-flight OCR, and retention after invalid/conflicting OCR.

For Colab, run the real video through the relevant interval (seeking changes track
IDs, so inspect equivalent tracks):

```sh
python scripts/validate_plate_runtime.py --video /path/to/video.mp4 --start-frame 9800 --frames 500 --output scratch/plate_consensus_runtime.json
```

Full-run reproduction can omit `--start-frame` and use `--frames 10500`.
Success requires real-video observations of 24C14058 with votes 1, 2, 3 and
RECOGNIZED. Unit replay alone does not establish this runtime success criterion.

Local validation completed: 55 tests passed across test_plate_consensus.py,
test_async_plate_scheduling.py, and test_plate_ocr.py (31 dependency warnings).
The local real-video run processed 500 frames after seeking to 9800, completing
59 OCR jobs on CPU. Track 6 accumulated two votes for 24H02156, but no track
reached RECOGNIZED and 24C14058 was not observed. Results are in
scratch/plate_consensus_runtime.json. This does not satisfy the requested Colab
L4 success criterion; that validation remains pending access to the Colab run.
