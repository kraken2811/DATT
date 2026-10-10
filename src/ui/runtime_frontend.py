"""Runtime-only React build support for Colab deployments.

The repository keeps a tracked fallback React bundle under src/ui/static/react_dist.
When source changes on Colab, building over that directory would dirty the Git
checkout and break the safe fast-forward workflow. This helper therefore builds
into .datt-runtime/react_dist and re-points only the static React mount.

No operational API, CV pipeline, database, Agent, or notification behavior lives
in this module.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
RUNTIME_DIST = PROJECT_ROOT / ".datt-runtime" / "react_dist"
RUNTIME_LOG_DIR = PROJECT_ROOT / ".datt-runtime" / "frontend"


def _is_colab_checkout() -> bool:
    """Return True for the supported /content/DATT-style Colab checkout."""
    return str(PROJECT_ROOT).startswith("/content/") or bool(os.getenv("COLAB_RELEASE_TAG"))


def prepare_runtime_frontend() -> Path | None:
    """Build current React source into an ignored runtime directory when required.

    Set DATT_BUILD_FRONTEND_RUNTIME=1 to force this behavior outside Colab, or 0
    to disable it explicitly. npm is invoked with package-lock writes disabled so
    the safe source update cell remains clean.
    """
    requested = os.getenv("DATT_BUILD_FRONTEND_RUNTIME", "").strip().lower()
    if requested in {"0", "false", "no", "off"}:
        return None
    if requested not in {"1", "true", "yes", "on"} and not _is_colab_checkout():
        return None

    package_json = FRONTEND_DIR / "package.json"
    if not package_json.is_file():
        raise RuntimeError("React frontend package.json is missing")

    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required to build the React frontend")

    RUNTIME_LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIST.parent.mkdir(parents=True, exist_ok=True)

    install_log = RUNTIME_LOG_DIR / "npm-install.log"
    with install_log.open("w", encoding="utf-8") as log:
        try:
            install = subprocess.run(
                [npm, "install", "--package-lock=false", "--no-audit", "--no-fund"],
                cwd=FRONTEND_DIR,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("React dependency installation timed out") from exc
    if install.returncode:
        raise RuntimeError("React dependency installation failed; inspect .datt-runtime/frontend/npm-install.log")

    build_log = RUNTIME_LOG_DIR / "npm-build.log"
    env = os.environ.copy()
    env["DATT_FRONTEND_OUT_DIR"] = str(RUNTIME_DIST)
    with build_log.open("w", encoding="utf-8") as log:
        try:
            build = subprocess.run(
                [npm, "run", "build"],
                cwd=FRONTEND_DIR,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=600,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("React frontend build timed out") from exc
    if build.returncode:
        raise RuntimeError("React frontend build failed; inspect .datt-runtime/frontend/npm-build.log")

    if not (RUNTIME_DIST / "index.html").is_file() or not (RUNTIME_DIST / "assets").is_dir():
        raise RuntimeError("React frontend build completed without the expected dist output")

    os.environ["DATT_REACT_DIST"] = str(RUNTIME_DIST)
    return RUNTIME_DIST


def configure_runtime_frontend(web_module: Any, runtime_dist: Path | None) -> None:
    """Point an already imported web_server module at the runtime React bundle."""
    if runtime_dist is None:
        return

    assets = runtime_dist / "assets"
    if not assets.is_dir():
        raise RuntimeError("Runtime React assets directory is missing")

    web_module.REACT_DIST = runtime_dist
    app = web_module.app

    # web_server mounts the tracked fallback /assets during import. Remove only
    # that mount and replace it with the newly built runtime assets directory.
    retained = []
    for route in app.router.routes:
        if getattr(route, "path", None) == "/assets" and getattr(route, "name", None) == "react_assets":
            continue
        retained.append(route)
    app.router.routes[:] = retained
    app.mount("/assets", StaticFiles(directory=str(assets)), name="react_assets")
