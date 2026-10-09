# Actual Colab runtime verification — 2026-10-09

Notebook: https://colab.research.google.com/drive/1-5MzpmDfPwdzIRy5_5QewbOleZLFWgQt?hl=vi

The existing GPU notebook was operated directly. The user explicitly authorized uploading the local `.env` to this runtime. Configuration loaded successfully; the five required database/storage variables are SET. Secret values were not printed, committed or cached on Drive.

## Source and actual results

The runtime fetched `origin/dev` and verified both HEAD and the remote branch equal `ac1bc2a57c05e24a19623fc150628416d2f9e02b`. The checkout was clean before testing.

| Actual Colab check | Result |
| --- | --- |
| Complete Agent suite, mock provider and disposable SQLite | 347 passed, 0 failed, 0 skipped, exit 0 |
| Selected backend and Colab deployment suites, disposable SQLite | 173 passed, 0 failed, 0 skipped, exit 0 |
| React Markdown regression | exit 0 |
| Camera frontend contracts | 4 passed, 0 failed, 0 skipped |
| npm ci / production build / lint | all exit 0 |
| Real PostgreSQL connection | PASS; PostgreSQL 17.11 |
| pgvector | PASS; 0.8.2 |
| Database migration revision / repository head | both 0014; no migration executed |
| Required application and checkpoint tables | no missing tables |
| Supabase bucket metadata GET | HTTP 200; upload/read/delete probe not executed |
| GPU | Tesla T4; torch 2.11.0+cu130; CUDA 13.0 available |
| ONNX providers | CUDAExecutionProvider available |
| Production model subprocess initialization | PASS; YOLO cuda:0, SCRFD/AdaFace CUDAExecutionProvider, plate OCR PASS; exit 0 |

The backend/Colab test selection comprises test_backend_completion, test_colab_startup, test_colab_source, test_colab_install, test_colab_drive_cache, test_migration_head, test_database_pool_lifecycle, test_web_server, test_alerts, test_notifications, test_cli and test_colab_latest_dev_verification.

Runtime logs and JUnit reports remain under `/content/DATT/.datt-runtime/colab-verify-*`. Test subprocesses use temporary SQLite, mock LLM/embeddings and blank external credentials. These results do not represent live PostgreSQL checkpoint restoration or paid model verification. The Colab React browser regression was not executed.

## Remaining startup blocker

Active configuration: LLM provider `mock`, model name `gemini-3.5-flash`, embedding provider `fastembed`, persistent history required and operational authentication required. The model name does not activate Gemini.

Fresh-process authentication validation fails with `Agent authentication signing key is not configured`. Repeated `userdata.get` checks return `SecretNotFoundError` for both `DATT_AGENT_AUTH_SECRET` and `DATT_STRICT_AUTH`. Inspection of the Secrets panel shows only four existing email secrets. User confirmations that the two variables were added did not change this observed runtime state.

The service status was STOPPED. A new startup cell validates authentication before invoking the CLI; no unsigned token, development fallback or disabled-auth workaround was used. No authenticated live chat, PostgreSQL restart/restoration test, Gemini call or email smoke test is claimed.

## Resume safely

1. In this notebook's left Secrets panel, the user must personally add `DATT_AGENT_AUTH_SECRET` using their private signing key of at least 32 characters and `DATT_STRICT_AUTH` with value `1`. Enable notebook access for both. Do not send the key in chat.
2. Run the new cell beginning `# Start only verified dev with strict authentication`. It checks the exact source commit, test gates, database revision, storage metadata, model results and fresh-process auth configuration before starting the GPU service. It does not run migrations or mint user tokens.
3. Verify `START_RESULT`, `/healthz`, worker status, rejection of anonymous sensitive requests and the resulting Colab proxy URL. A legitimate existing account token is still needed to verify authenticated operational chat and live checkpoint restoration.
4. Do not run the older base64/ZIP replacement cells, which can overwrite the verified source with older patches. Do not use the old automatic startup loop, which runs migrations and outdated unauthenticated checks.

Screenshot: `scratch/colab-auth-blocker-2026-10-09.png`. This report and screenshot are local artifacts; no source change or push was performed in this runtime-verification turn.
