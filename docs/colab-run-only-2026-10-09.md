# Colab run-only notebook — 2026-10-09

Use `notebooks/DATT_Colab_Run.ipynb`. This is a new six-cell notebook, preserving the existing repository GPU and twelve-cell verification notebooks and their tests. The six run cells are source/model cache, dependencies/frontend build, configuration, mandatory preflight, GPU startup and application links. It contains no regression suites, source replacement archives, notebook outputs or secrets.

## Fixed behavior

The old upload cell unconditionally asserted that `/content/DATT/.env` must not exist. A second execution therefore failed even after a successful upload. The new loader reuses the existing file without opening the upload picker or overwriting it. It uploads only when absent, accepts Colab's already-written upload, uses exclusive creation if needed, rejects incorrect selections and preserves a concurrently created different file.

Strict authentication defaults to `1` when absent/empty. Explicit configuration is preserved and validated at preflight. No signing key is generated and the legacy production fallback remains forbidden. A legitimate private signing key must be configured by the user. `CONFIG=LOADED` only indicates that configuration was read; deployment requires `PREFLIGHT=PASS`.

Preflight verifies the reviewed source commit against latest origin/dev, clean checkout, authentication, real PostgreSQL/pgvector/schema revision, persistent conversation tables, Supabase bucket metadata and actual CUDA model initialization. It does not run migrations or paid LLM calls. Startup uses only the CLI-owned service, refuses unknown listeners, verifies the live revision and workers and rejects anonymous access to sensitive APIs. No account token is minted.

The approved source remains `ac1bc2a57c05e24a19623fc150628416d2f9e02b`, which previously passed actual Colab tests (347 Agent + 173 backend/deployment, zero failures/skips). A later remote revision requires review/verification before changing the approved pin.

## Browser edit status

The original 16-cell notebook's rendered source/output was saved for reference in `scratch/colab-before-clean-2026-10-09.json` before edits. A batch edit was interrupted when browser control timed out and disconnected. The number of successfully replaced cells could not be verified. No deletion of old cells has been confirmed. Do not claim that the live notebook has six cells yet; use the complete generated run-only notebook or finish direct UI cleanup when the browser is available.

## Run

1. Open/upload `notebooks/DATT_Colab_Run.ipynb` in Colab and select a GPU runtime.
2. Run cells 1–3 in order. Existing `.env` is reused. For a fresh runtime, select only your approved `.env` in the upload picker. Secrets and biometric media are never stored in the Drive model cache.
3. Personally configure `DATT_AGENT_AUTH_SECRET` using a private signing key of at least 32 characters in Colab Secrets, enabling this notebook's access, or supply the already configured key in your private `.env`. Never send it in chat. Rerun configuration after granting Secrets access.
4. Run cells 4–6. If schema/model/storage/auth checks fail, fix that named prerequisite and rerun; no migration, authentication bypass or unknown-process termination is automatic.
5. Open the displayed DATT/Agent link. Operational data and chat require a legitimate existing account token. Live authenticated chat and PostgreSQL restoration have not been executed by this new notebook yet.

## Local verification

Focused regression coverage includes repeated `.env` loads, upload-once behavior, Colab auto-saved uploads, concurrent-write preservation, invalid selections, credential nondisclosure, configuration failures, strict-auth defaults and the six-cell artifact contract. Existing Colab tests remain intact.

An initial attempt with the Windows system Python failed before collection because `pgvector` was not installed there. Verification was rerun using the project's `venv/Scripts/python.exe`; no dependency failure was hidden or test skipped. The final focused run passed **86 tests, zero failed, zero skipped**, with three existing deprecation warnings in 9.98 seconds. This includes 13 new cases. JUnit: `scratch/colab-run-only-tests.xml`. Six-cell syntax validation and whitespace checks passed. These are local results; the new notebook has not been executed end to end in Colab.

No push or production startup is claimed for this notebook cleanup.
