# Face recognition history and Agent grounding — 2026-10-09

## Provider

Local configured LLM provider: `mock`. Configured model name: `gemini-3.5-flash`; the name does not activate Gemini. All verification below forces mock LLM/embeddings, blank API keys and disposable SQLite fixtures. No real Gemini/OpenAI call or production PostgreSQL verification is claimed.

## Exact causes and changes

1. MockChatModel had no face-history intent or identity-resolution workflow. The reported Vietnamese requests reached the welcome fallback. It now resolves the name/UUID in Face Watchlist first, asks for selection when ambiguous, then queries `search_events` with the resolved UUID, `event_type=face`, and `watchlist_match=True`. Unsupported operational requests ask for missing details instead of greeting.
2. search_watchlist calculated target/query aliases but applied only target_id to Target filters. Aliases now filter face/person records; literal SQL wildcard escaping and a separate unpaginated face count prevent unrelated matches and hidden ambiguity. Explicit face searches do not query vehicles.
3. Event tool results exposed recorded camera IDs but omitted configured names and locations. Agent tools now add display metadata from a batched Camera query or static camera registry. Missing metadata remains null. Existing event-center PostgreSQL queries, event timestamps and IDs are unchanged. Locations are labeled current configuration, not historical location evidence.
4. graph.py scanned the whole checkpoint when building tools_called and sources. It now scopes output to the input HumanMessage ID and deduplicates tool names in order. React also deduplicates badges. Checkpoint thread/user isolation and authorization are unchanged.
5. Natural Vietnamese presentation preserves exact recorded facts, distinguishes absent history from unavailable/error data, and returns JSON only on the current user's explicit request. No formatting-only LLM call was added. The system prompt gives real providers the same identity/history grounding instructions.

The deterministic workflow honors today/yesterday and explicit YYYY-MM-DD or DD/MM/YYYY dates in ICT, keeps the requested date through identity selection, and accepts explicit CAM_/camera_ IDs or camera UUID filters. It reports at most 20 historical matches and preserves the backend total.

CV processing, DB models/migrations, event-center SQL, authorization, checkpoint configuration and RAG retrieval were not modified.

## Verification

| Check | Result |
| --- | --- |
| Final local Agent suite | 138 passed, 3 existing deprecation warnings, 14.89 seconds, exit 0 |
| Local Agent + DB/vehicle-watchlist/target-selection/camera-selection contracts | 180 passed, 3 warnings, 61.45 seconds |
| New face-history regressions | 40 cases; included in the Agent suite |
| React Markdown regression | PASS |
| Vite production build | PASS, 1788 modules |
| git diff --check | PASS |
| Colab earlier patch | 128 passed, 1 warning, 17.41 seconds; COLAB_AGENT_FACE_HISTORY_EXIT=0 |
| Colab final patch | Pending; final source package prepared, browser review blocked further notebook access |

The 180-case local run preceded the final tightening of camera-token parsing; the complete 138-case Agent suite was rerun afterward and passed. Coverage includes real isolated SQL/tools, target aliases and UUIDs, Unicode names, inactive identities, ambiguity and selection, checkpoint tenant isolation, matched-only history, exact timestamps, registration-time separation, configured camera names/locations, missing timestamps/metadata, empty history, backend errors, authorization denial, date/camera filters, pagination, explicit JSON, natural text, current-turn sources and unique tool metadata.

Colab uses the existing notebook at https://colab.research.google.com/drive/1-5MzpmDfPwdzIRy5_5QewbOleZLFWgQt?hl=vi . The completed 128-test result is in the face-history verification cell. A later final source package was uploaded, but the cell was not updated/executed because automatic approval review rejected browser access (usage-limit failure followed by a policy block). Screenshot capture also timed out; no screenshot proof is claimed.

## Complete the final Colab check

1. Upload the latest local `scratch/agent-face-history-colab-final.zip` through Colab's Files pane. An earlier file with the same name is stale; replace it with the latest local package.
2. Paste `notebooks/colab_face_history_validation_cell.py` into a code cell and run it after the source/dependency cells. The cell verifies SHA-256 and its nine-file allowlist, preserves original source backups and runs the credential-free isolated test runner.
3. Expected output: `138 passed` and `COLAB_AGENT_FACE_HISTORY_EXIT=0`. The isolated log is `/content/DATT/.datt-runtime/face-history-tests.log`.

Final ZIP SHA-256: `da8ced8749152d7d191809626972cf376accb3d1447fb5b115418309f6d52c5b`.

No local .env, credentials, biometric media or real recognition records were uploaded. No push has been performed for this patch; final Colab verification remains the outstanding pre-push step.
