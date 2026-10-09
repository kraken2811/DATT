# Colab resume — 2026-10-09

The current fresh T4 runtime stopped at a SIGBUS signal from git fetch against the mirror in /content/drive/MyDrive/DATT-Colab-cache/dev.git. The repaired bootstrap runs clone/fetch/fast-forward on /content/DATT instead; Drive still supplies pip and model caches. Existing Drive mirror is left intact. Dirty or divergent checkouts are refused; .env/models/data are preserved; source changes stop only a verified CLI-owned service.

Live source bootstrap: direct clone of dev commit b1242616c26cd6d4237d0204cfdbd8419e193af4 succeeded in 14.4 seconds; 4 cached model files restored. All 10 dependency stages, critical imports and CUDA checks passed (DEPENDENCY_INSTALL_EXIT=0).

Local regressions: 71 passed, 1 skipped for source refresh, installer, startup, CLI and runtime management; all 98 Agent tests passed separately. git diff --check passed.

The fresh runtime has previously granted email Secrets but lacks DATT_DATABASE_URL, DATT_STORAGE_BACKEND, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and DATT_STORAGE_BUCKET. Full production startup remains pending project configuration; no local credential was transferred without user approval.

Colab regressions: 170 passed, 1 warning in 26.78 seconds; COLAB_REGRESSION_EXIT=0. The combined suite covers all 98 Agent tests and 72 source/installer/startup/CLI/runtime tests.
