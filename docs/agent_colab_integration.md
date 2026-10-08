# Agent / Colab integration repair

## Root causes and evidence

- `AgentPage` destructured and called `addToast`, while `ToastContext` only supplies `showToast(message, type, duration)`. Every error/reset call therefore invoked an undefined function; minification explains the reported `c is not a function`.
- Notebook Cell 2 reused `/content/DATT` without fetching `dev`. Cell 8 reused a healthy owned runner without checking its loaded revision or registered Agent routes. These are confirmed stale-deployment paths. Current source imports the Agent router unconditionally into `src.ui.web_server.app`.
- Neither `requirements-colab.txt` nor the staged installer supplied the complete Agent dependency set. A fresh deployment could fail application imports. FastEmbed also declares CPU ORT by distribution name; the installer now validates that dependency against the existing GPU ORT instead.
- The Agent header inherited camera telemetry, so its disconnected badge was not evidence of an Agent API failure. `Header` also discarded the supplied new-conversation action.
- Tests exposed an additional SQLite RAG defect: the fallback was attached to `try/else`, but the successful path always executed `break`. It never retrieved chunks. The fallback now runs inside the database transaction as the SQLite branch.

The live Colab notebook could not be inspected: browser security review denied access because permission was declined. Consequently the exact live 404 cause (old checkout, old process, wrong app, or saved API URL override) has not been measured. The corrected startup reports revision/module and checks the live schema instead of inferring readiness from HTTP health alone.

## Deployment behavior

Cell 2 fetches `origin/dev`, checks that HEAD can fast-forward, stops only the old CLI-owned service when the revision changes, switches to `dev`, and fast-forwards. Tracked edits or divergent history stop startup without discarding changes. Ignored models, databases, `.env`, media and caches remain intact. Unknown listeners are never killed.

Cell 3 installs missing Agent packages through the existing constrained wheel resolver, protects Torch/NumPy/GPU ORT, verifies Agent imports, and executes `python -m scripts.agent_smoke` in a separate interpreter. That smoke uses the actual web app, real LangGraph, MockChatModel and an isolated MemorySaver. It performs two chat turns, retrieves history, validates empty input, exercises provider-error serialization, creates an independent server-generated conversation and resets only its in-memory test thread. No paid provider or business tools are called.

The runner captures its Git revision when starting and reports `commit`, `application_module=src.ui.web_server` and `agent_llm_provider` in `/healthz`. Cell 8 restarts a verified owned runner whose revision/module or Agent schema is stale. Cell 12 verifies live revision/module, all Agent methods, empty history for a unique test identity/thread, and a 422 response for invalid chat. The live probe does not invoke an LLM or delete existing history. Final readiness requires both Agent checks to pass.

Required OpenAPI operations:

- `POST /api/agent/chat`
- `GET /api/agent/conversations/{thread_id}`
- `DELETE /api/agent/conversations/{thread_id}`

## API URL

Production requests default to the same origin as the UI, including Colab's HTTPS port-8501 proxy. Development Vite proxies `/api` to `127.0.0.1:8501`. There is no VITE API URL environment variable in this client. A saved `localStorage.datt_backend_url` overrides the origin. Ensure it refers to the DATT web app on port 8501, rather than the CV telemetry service on port 8000 or an old proxy URL. Clear just that override in Settings/DevTools if it is stale; keep session/auth/thread storage.

The Agent badge now describes API connectivity. A provider-unavailable response still means the API is reachable; its error is shown in chat and a toast.

## Restart / verify

1. Open the updated notebook from `dev`: https://colab.research.google.com/github/kraken2811/DATT/blob/dev/notebooks/DATT_Colab_GPU.ipynb . An already-open Drive copy retains its old cells unless updated.
2. Run Cells 1-13 in order in the existing runtime. Do not delete or factory-reset the runtime. The GPU probe reuses a working stack, and source/model/data updates retain the existing persistent files.
3. If Cell 2 reports tracked edits or divergence, preserve and resolve those changes first; do not use `git reset --hard` or `git clean`. If a port has an unknown owner, inspect it privately and stop the correct service through its existing controller.
4. Confirm the printed source commit matches `origin/dev`; require `agent_mock_api=PASS`, `agent_live_api=PASS` and `SYSTEM_READY=YES`. `/healthz` must report the same commit and intended module; `/openapi.json` must include the three operations above.
5. Reload the UI to load the new hashed production bundle. Check the saved API URL override, restore history, send a greeting, and create a new conversation. For quota-free interactive testing, select the existing mock provider setting before starting the service; restore your existing provider setting and restart only the DATT service when ready for a real-LLM check. Never paste credentials into notebook source.

No real-LLM request was executed during this repair. Existing configured credentials/providers are preserved by the deployment; MockChatModel is forced only inside isolated tests.

## Verification executed

- `venv/Scripts/python.exe -m scripts.agent_smoke`: PASS, real LLM calls = 0.
- `venv/Scripts/python.exe scripts/test_dev.py`: 247 passed, 1 skipped (POSIX socket-rebind test skipped on Windows), including CLI, camera, persistence, notification, streaming, and Colab regressions.
- `venv/Scripts/python.exe scripts/test_dev.py tests/test_agent_api.py tests/test_agent_graph.py tests/test_agent_e2e.py tests/test_agent_hardening_correctness.py tests/test_agent_grounding.py tests/test_agent_tools.py tests/test_agent_llm.py tests/test_agent_memory_isolation.py tests/test_colab_startup.py tests/test_colab_install.py tests/test_colab_runtime_cell.py tests/test_colab_source.py`: 92 passed after the SQLite fallback repair.
- `venv/Scripts/python.exe scripts/test_dev.py tests/test_cli.py`: 18 passed, 1 Windows-specific skip, with actual supervised Uvicorn HTTP Agent checks.
- `npm --prefix frontend run build`: PASS; production bundle rebuilt in `src/ui/static/react_dist`.
- `node frontend/scripts/test_agent_e2e.cjs`: PASS against that production bundle in headless Chrome, using mock HTTP responses. Covers history/reload, chat, HTTP and provider error toasts, new conversation/reset, API status independent of camera status, API base URL and session headers, with no uncaught JavaScript errors.
- `node --test frontend/test/camera-contract.test.js`: 4 passed.
- `git diff --check`: PASS.

## Changed files

- `frontend/src/pages/AgentPage.jsx`, `frontend/src/components/Header.jsx`: correct toast API, Agent connectivity and visible new-conversation action.
- `frontend/src/api/agent.js`: invalidate cached history after chat/reset operations.
- `frontend/package.json`, `frontend/scripts/test_agent_e2e.cjs`: repeatable browser regression command.
- `notebooks/DATT_Colab_GPU.ipynb`: safe dev update before startup.
- `requirements-agent.txt`, `requirements.txt`, `requirements-colab.txt`: shared Agent requirements.
- `scripts/colab_install.py`: install Agent dependency closure while retaining GPU ORT.
- `scripts/colab_startup.py`, `src/ops/runner.py`: loaded-revision/module diagnostics, stale-runner detection and startup API verification.
- `scripts/agent_smoke.py`: quota-free isolated Agent integration smoke.
- `scripts/test_dev.py`: disposable database/storage, mock provider and in-memory checkpoint isolation.
- `src/agent/rag/retrieval.py`: reachable SQLite fallback inside its transaction.
- `tests/test_agent_e2e.py`: self-contained mock RAG document fixture.
- `tests/test_cli.py`: actual supervised Uvicorn HTTP checks for revision/module, MockChatModel chat/history/new thread/reset and validation.
- `tests/test_colab_startup.py`, `tests/test_colab_install.py`, `tests/test_colab_source.py`: schema/process/dependency and local-Git preservation regressions.
- `src/ui/static/react_dist/index.html`, replaced hashed JavaScript asset: rebuilt production UI.
- `docs/agent_colab_integration.md`: root-cause evidence, verification and restart guide.
