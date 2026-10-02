# Repeatable Colab startup

Use `notebooks/DATT_Colab_GPU.ipynb`, which contains 13 ordered executable cells.
Deploy this source version to `/content/DATT` before running it. The notebook
never clones, pulls, resets, replaces source files, commits, or pushes.

1. Runtime preflight provisions the exact Torch/vision/audio cu126 stack from
   the official PyTorch wheel index when the installed versions differ (including
   fresh Colab cu130 runtimes). Matching versions are reused. It refuses package
   replacement while native modules are loaded in the kernel or application ports
   are occupied. If requested, restart the session (not delete the runtime), then
   rerun Cell 1. The GPU tensor probe and version checks run in a fresh subprocess.
   Provisioning logs are in `/content/datt-torch-install.log`; GPU probe errors
   are in `/content/datt-gpu-probe.log`. The standalone source for Cell 1 is
   `notebooks/colab_runtime_cell.py`, embedded in the notebook for fresh runtimes.
2. Source setup reuses the deployment and reports Git HEAD when available.
3. Dependencies resolve bounded wheel-only stages and verify native imports in
   a subprocess. The installer preserves Torch 2.11.0+cu126, torchvision
   0.26.0+cu126 and torchaudio 2.11.0+cu126 exactly. Constraints use active
   metadata rather than shadowed system distributions. Each dry-run plan is
   audited before installing its exact missing packages without a second
   dependency resolution. InsightFace uses GPU ORT instead of installing the
   overlapping CPU distribution; the full dependency closure is validated.
   Stage logs and resolution reports stay in `.datt-runtime/install/`.
4. Configuration prefers `/content/DATT/.env` (no interpolation), then existing
   environment and granted Colab Secrets for missing names. Only presence flags
   are printed. Email settings are also loaded; full readiness requires a running
   notification worker. No test email is sent.
5. Existing CLI DB/storage checks verify PostgreSQL, pgvector and temporary
   upload/read/delete. Current and expected migration revisions are displayed.
   A behind-head database may proceed to Cell 7; connection/extension/storage
   failures may not. The existing storage adapter is the Supabase REST client.
6. CLI model provisioning reuses existing weights. A disposable model probe
   initializes existing production classes, including the AdaFace embedder,
   and requires actual CUDA providers. No recognition algorithm is reimplemented.
   If the AdaFace asset is absent, deploy the existing production model; the
   notebook does not select a substitute or change model paths/thresholds.
7. The existing CLI `migrate` upgrades to the dynamically discovered head.
8. Healthy CLI-owned backends are preserved. Only an unhealthy verified owner
   is gracefully stopped by the CLI. Unknown port owners block startup.
9. The CLI starts GPU mode only when necessary. It owns all runtime services.
10. Health checks verify owner identity, one runner/listener, HTTP, DB/storage,
    CUDA and live persistence/notification threads via `/startup-health`.
11. URLs show the local UI and existing Colab proxy, without a new tunnel provider.
12. GET-only smoke checks cover cameras, video selection listings, source state,
    face targets, vehicle watchlist, Event Center and AI telemetry. They do not
    activate cameras, create events, send emails or prove recognition accuracy.
13. Readiness rechecks health and prints the requested compact report.

After any failed cell, resolve the named blocker and rerun from Cell 1. A failure
latches the startup helper so subsequent cells cannot launch services blindly.
A reconnect reuses source, packages, caches and healthy CLI ownership records.
A dead backend is restarted through CLI; a complete reset requires redeployment.
An older healthy backend without `/startup-health` must be explicitly restarted
through the CLI after deploying this source; the notebook does not restart a
healthy owner automatically just to load a diagnostic endpoint.

Raw driver/pip/model output and `.env` contents are withheld. Model probes run in
bounded child processes; storage probes retain the existing CLI's `finally`
cleanup. An externally killed/timed-out storage operation can still require
manual inspection for its uniquely named probe; full readiness is never reported
when the check or cleanup fails.

## Existing configured runtime

For an already provisioned `/content/DATT`, use the standalone
`notebooks/start_datt_cell.py` as the final Colab cell named **START DATT**.
It loads the existing environment, uses the canonical GPU CLI startup,
checks production frontend/API routes and workers, then displays **OPEN DATT**
on port **8501**. Port 8000 is the internal AI stream and legacy monitor.
This cell does not install dependencies or run migrations. It only stops an
unhealthy CLI-owned process or a verified standalone legacy DATT process;
unknown port owners block startup.

The latest event/GPU audit reached production HTTP 200 with persistence and
notification workers running and live CUDA inference. Its final service was
restored with audit-only mode disabled and the test video stopped. The same
61 isolated policy/capture/watchlist/notification tests passed locally and on
Colab. These results do not prove the complete production write/email flow.
See [the remaining dev acceptance checks](dev-e2e-checklist.md).

## Earlier provisioning validation (2026-10-02)

The following records describe earlier sessions, before the successful
configured-runtime audit above; they are not the current readiness status.

Fresh-runtime follow-up: Python 3.13.15 / Tesla T4 initially supplied Torch
2.11.0+cu130. The revised Cell 1 installed the official cu126 stack and passed
the GPU tensor probe without a kernel reset. Source was absent in this new
runtime and was deployed from the local working tree. Cells 2 and 3 then passed,
including all eight dependency stages. Cell 4 requested DATT_DATABASE_URL;
application startup remains unverified pending persistence configuration.
The local YOLO/plate/AdaFace model assets were uploaded to the new runtime;
the standalone production model probe passed YOLO, face, plate/OCR and ONNX
CUDA initialization. This does not bypass Cell 4 or establish backend readiness.
Local runtime/installer/startup regressions: 19 passed.

Earlier session evidence (not the fresh runtime):

The preserved Colab kernel (PID 2253) uses Python 3.13.15, Tesla T4 and Torch
2.11.0+cu126 / CUDA 12.6. Cells 1?3 passed. The original Cell 3 timeout was
caused by last-entry-wins distribution enumeration pinning shadowed NumPy
1.26.4 instead of active 2.1.3 (and other stale system versions). Unbounded
ONNX selection also backtracked against the installed protobuf 5.29.6.
The staged installer selects ONNX 1.20.1, whose ABI3 wheel supports Python
3.13 and whose protobuf constraint accepts the existing runtime.

Cell 4 is blocked on absent persistence configuration. No production database,
Storage, application E2E or Real Camera Acceptance success is claimed.
Provision the five required persistence variables and SMTP configuration
securely in `/content/DATT/.env` or authorized Colab Secrets, then rerun from
Cell 1. Never paste secret values into notebook cells or reports.

GPU model verification also passed using the existing model assets: YOLO/plate
and OCR initialized on CUDA; SCRFD and AdaFace profiled 132 and 152 CUDA node
executions respectively. Supervision is pinned to 0.30.3, matching the local
workspace and passing synthetic tracking/source-switch tests.

The credential-isolated regression run currently has 456 unique passes,
17 failures, and 12 skips. Remaining failures cover legacy downgrade safety
expectations, face fixtures/expectations, and repository-root Storage path
assumptions. These are not production E2E acceptance. Full PostgreSQL/Storage,
SMTP, frontend/backend and restart checks still require configured access.
