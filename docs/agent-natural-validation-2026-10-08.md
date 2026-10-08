# Agent natural-response validation — 2026-10-08

Scope: deterministic Vietnamese presentation for MockChatModel; grounded conversational SYSTEM_PROMPT for Gemini/OpenAI; scoped React Markdown rendering. Tool payloads remain JSON. No additional LLM calls; mock tests require no API key. CV processing, production schema, memory isolation, tool authorization and RAG retrieval are unchanged.

## Verification

- Local: python scripts/validate_agent_responses.py — **98 passed**, including all 60 existing Agent tests and 38 new natural-response regressions; 3 upstream deprecation warnings.
- Colab T4: same isolated Agent suite — **98 passed**, 1 warning, 5.13 seconds. Disposable SQLite fixtures; no live provider calls in this suite.
- Colab: npm install --ignore-scripts --no-audit --no-fund — exit 0.
- Colab: npm run test:agent-markdown — PASS for paragraphs, lists, emphasis, exact identifiers, citations, explicit JSON code, safe HTML/links/images, literal user text.
- Colab: npm run build — PASS, 9.01 seconds. Verified package lock and production bundle restored to local workspace.
- Colab existing CLI-owned service restarted in GPU mode on UI port 8501 / AI port 8000. Post-restart health: notification_worker=RUNNING; persistence_worker=RUNNING; verified React bundle served at /agent.
- Local: git diff --check — PASS. Windows renderer initially blocked by sandbox esbuild directory access; rerun with approved normal filesystem access — PASS. Colab renderer test and production build passed.

## Regression coverage

Camera status and connection uncertainty; events and pagination; statistics and distinct time windows; face/vehicle watchlists; RAG exact document/section/page citations; zero versus missing data; errors and authorization denial; hybrid results; partial budgets; current-turn JSON preference and history; unchanged internal messages; credential redaction; keyless mock and existing invocation count.

## Limits

Gemini/OpenAI conversational behavior is governed by the updated system prompt; no paid live-provider evaluation was performed. Existing stored replies are preserved and may contain legacy JSON. Existing startup/dependency edits present before this task are excluded from the Agent change.

Live UI verification: camera_01 returned a Vietnamese paragraph and Markdown facts, preserving the source type/local-file guidance, and explicitly distinguishing configured offline status from unverified network reachability. No new raw JSON response. Screenshot: screenshots/agent-natural-colab-2026-10-08.png.
