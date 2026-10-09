# Colab UI authentication and repeated telemetry 401 — 2026-10-09

## Root causes and limits of the supplied evidence

The supplied browser log contains repeated `GET /api/telemetry` HTTP 401 responses from the Colab proxy. It does not include request headers or the response body, so it cannot prove whether the live request lacked a token, carried an invalid token, or was denied at the proxy. The existing strict-auth application middleware protects telemetry and other operational APIs. Its expected response to missing/invalid credentials is consistent with this log; removing that protection is not a fix.

The frontend read `datt_auth_token` from localStorage but offered no token-entry UI. Its telemetry wrapper converted authorization failures into disconnected fallback records with zero counts. AppContext then retried every second, producing the repeated console errors. API GET cache/deduplication keys also omitted the authenticated account/session, so changing credentials could reuse previous private data. Camera img URLs could not attach Bearer headers to protected video/snapshot routes.

## Changes

- Settings has a masked field for an existing authorized account's Bearer token. A read-only conversation-list request verifies the server-confirmed user before saving it. Invalid tokens, HTTP 403, registry/backend failures and HTTP 200 without a verified user do not produce successful login or overwrite the current token. No signing key or user token is minted.
- Tokens are bound to the selected backend. Legacy tokens remain usable on the same origin only. Remote HTTP token transmission is refused; local HTTP remains supported. Changing servers does not forward an old server's token.
- API cache/deduplication is partitioned by credential/session/backend revision. Stale responses cannot populate a new account's cache. Configuration changes clear displayed private state and remount page data loaders. Logout and failed token-storage writes fail closed.
- Telemetry preserves 401/403 as authentication errors and pauses sequential polling until connection/credentials change. The shared notice links to Settings. Unavailable counts are null/displayed as a dash; a recorded zero stays zero.
- Dashboard and camera view use authenticated fetch of the existing bounded frame_stream protocol instead of unauthenticated img URLs. The canvas retains the existing stream styling, releases decoded images, clears stopped/stale streams and rejects late paints after cleanup. Tokens never appear in frame URLs. CV processing and backend stream endpoints were not changed.
- The production React bundle was rebuilt, replacing the old JavaScript asset referenced by the supplied stack trace.

Backend authentication, tool authorization, database models/schema, PostgreSQL queries, checkpoint isolation, RAG retrieval and CV processing were not modified.

## Changed files for this patch

| Area | Files |
| --- | --- |
| API client and token handling | frontend/src/api/client.js, telemetry.js, connection.js, auth.js, frameStream.js |
| Shared UI | frontend/src/App.jsx, frontend/src/context/AppContext.jsx, frontend/src/components/Header.jsx, AuthenticationNotice.jsx, AuthenticatedVideo.jsx |
| Pages | frontend/src/pages/SettingsPage.jsx, DashboardPage.jsx, CameraViewPage.jsx |
| Tests and commands | frontend/test/auth-contract.test.js, frontend/scripts/test_auth_e2e.cjs, frontend/package.json |
| Agent responsive layout | frontend/src/index.css, frontend/scripts/test_layout_responsive.cjs |
| Generated build | src/ui/static/react_dist/index.html; assets/index-CttlZyBb.js and index-Bclhd4xA.css replace the previous JS/CSS assets |
| Evidence | docs/colab-ui-auth-validation-2026-10-09.md; screenshot/log/JUnit artifacts under scratch, not for committing |

The user authorized committing and pushing the current changes to dev. The run-only notebook and historical validation documents are included and preserved. The run-only notebook retains its previously reviewed source pin; before deploying a newer revision, explicitly review and update APPROVED_COMMIT in both notebook artifacts. Publication does not bypass the mandatory source, authentication or database gates.

## Verification actually executed locally

| Gate | Result |
| --- | --- |
| Python mock/SQLite Agent + web/backend + run-only notebook suites | 397 passed, 0 failed, 0 skipped; 3 deprecation warnings; 60.16 seconds |
| Complete Agent portion of that run | 347 passed |
| New frontend auth/telemetry/cache/stream contracts | 18 passed |
| Existing camera frontend contracts | 4 passed |
| Auth browser regression, disposable server and synthetic JPEG | PASS |
| Existing Agent browser regression, disposable server | PASS |
| Agent Markdown regression | PASS |
| Vite build at the initial auth verification | PASS, 1793 modules; asset index-Dhs98D8A.js |
| Lint | exit 0, 44 warnings; not a warning-free run |
| git diff --check | PASS |

The auth browser test verifies that denied telemetry polling stops over 2.4 seconds, unavailable counts display a dash, invalid tokens are not saved, a legitimate fixture account resumes polling, valid zero remains zero and a synthetic JPEG is decoded/painted through a request with Authorization. Token input is empty after reload, and there are no uncaught JavaScript errors. No real credentials, recognized identities, video recordings or paid providers are used by these tests.

An intermediate addition to the browser test timed out while waiting for a painted JPEG because the test fixture immediately closed its stream; the component correctly cleared an ended stream. The fixture was corrected to stay open like the existing production streaming endpoint, keeping the pixel assertion unchanged. The rerun passed. The failed intermediate test is not hidden by the later Agent/Markdown successes.

JUnit: `scratch/auth-ui-backend-tests.xml`; lint log: `scratch/auth-ui-lint.log`; screenshot: `scratch/auth-settings-regression.png`. The screenshot is from the local fixture, not Google Colab.

## Final verification before the authorized dev push

The current checkout also includes the responsive Agent workspace changes. The final production build contains 1793 modules and references index-CttlZyBb.js / index-Bclhd4xA.css. Its auth, Agent, Markdown and responsive-layout browser checks all passed. Layout checks cover desktop 1920x1080 and 1366x768, tablet 768px, mobile 390px and collapsing/reopening conversation history. Auth/camera Node contracts: 22 passed, zero failed or skipped. Final lint exited 0 with 50 warnings; this is not a warning-free run.

The expanded Python selection passed 532 tests, failed zero and skipped one in 135.08 seconds, with three deprecation warnings. All 347 Agent tests passed without skips. The one skipped case is tests/test_cli.py::test_closed_stream_socket_does_not_block_restart, which already has a Windows skip marker for POSIX streaming socket rebind semantics. No test expectation or skip marker was changed. This run includes Agent, web/backend, CLI, alerts/notifications, migration/pool and Colab source/install/startup/cache/run-only contracts. JUnit: scratch/pre-push-2026-10-09.xml.

The candidate-file scan found no private credential literals from the local .env. The six-cell notebook has no saved outputs. .env, scratch artifacts, biometric data and model caches are excluded from the commit. These are local checks; publishing this patch does not imply Colab execution or live PostgreSQL/Gemini verification.

## Remaining security and deployment prerequisites

The existing HMAC Bearer-token contract has no expiry/revocation service; existing tokens remain bearer credentials. Browser localStorage is accessible to JavaScript on the application's origin, so this patch is not an HttpOnly-cookie/SSO migration. Credentials are scoped and never placed in URLs or logs, but those existing architecture limits remain. A server signing secret or Gemini API key must never be entered into the frontend's account-token field.

Direct browser access is still unavailable: the browser-control inventory returns no connected browser. This patch has therefore not been applied to the user's live Colab notebook, and no live authenticated Colab chat, real PostgreSQL restart/restoration or Gemini execution is claimed.

## Deploy the approved version

1. Review and commit the listed frontend patch and its generated production bundle. Push only when authorized. Record the resulting approved commit SHA; do not label the old ac1bc2a runtime as containing this UI fix.
2. After the new revision passes its required gates, update the notebook's approved-source pin to that reviewed SHA. Fetch origin/dev and fast-forward a clean Colab checkout while preserving .env/model cache. Do not run old ZIP/base64 source-replacement cells or automatically migrate production data.
3. Run the reviewed run-only notebook's dependency/build, configuration and mandatory preflight cells. Keep strict auth enabled and the real signing secret privately configured. Start/restart only the CLI-owned GPU service.
4. Open the fresh Colab proxy link and reload the browser so it loads the new production asset. In Settings, use that proxy origin as the backend and personally enter the existing account's Bearer token; click Xác thực. Never use DATT_AGENT_AUTH_SECRET or Gemini's key as the account token.
5. Verify telemetry and operational requests return 200 with the legitimate token and still return 401/403 without it. Verify real camera frames and authenticated Agent responses separately. Record live PostgreSQL restoration and Gemini checks only if genuinely executed.
