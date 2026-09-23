"""DATT Runtime Manager - Unified Application Orchestrator.

Phase 4.5: Unified Runtime Integration.
Coordinates the simultaneous execution and graceful lifecycle of:
1. AI processing pipeline (YOLO11s CUDA, ByteTrack, ZoneCounter, CameraManager, EventManager, MJPEG stream)
2. FastAPI monitoring dashboard (HTML/JS UI, Telemetry API, Camera API, Event API)

Architecture:
    src/main.py -> RuntimeManager
                     ├── AI Pipeline Thread (dedicated daemon)
                     └── FastAPI Server Thread (dedicated daemon)
"""

import logging
import os
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Any

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uvicorn
from src.runtime.shared_state import shared_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("datt.runtime")


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a network port is available for binding.

    Prevents 'OSError: [Errno 98] Address already in use'.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            bind_host = "127.0.0.1" if host in ("0.0.0.0", "", "*") else host
            sock.bind((bind_host, port))
            return True
        except OSError:
            return False


class RuntimeManager:
    """Unified runtime manager orchestrating AI pipeline and Web dashboard."""

    def __init__(
        self,
        camera_id: str | None = None,
        web_host: str = "0.0.0.0",
        web_port: int = 8501,
        ai_host: str = "127.0.0.1",
        ai_port: int = 8000,
        ui_enabled: bool = True,
        max_frames: int | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.web_host = web_host
        self.web_port = web_port
        self.ai_host = ai_host
        self.ai_port = ai_port
        self.ui_enabled = ui_enabled
        self.max_frames = max_frames

        # Lifecycle threads & flags
        self._stop_event = threading.Event()
        self._ai_thread: threading.Thread | None = None
        self._web_thread: threading.Thread | None = None
        self._uvicorn_server: uvicorn.Server | None = None
        self._is_shutting_down = False
        self._lock = threading.Lock()

    def validate_ports(self) -> None:
        """Validate network ports before launching services to prevent binding errors."""
        # 1. Check AI streaming port if UI mode enabled
        if self.ui_enabled and not is_port_available(self.ai_port, self.ai_host):
            raise RuntimeError(
                f"[DATT-RUNTIME] AI stream port {self.ai_port} is already in use. "
                f"Please free the port or specify an alternative with --ai-port."
            )

        # 2. Check Web dashboard port if UI mode enabled
        if self.ui_enabled and not is_port_available(self.web_port, self.web_host):
            raise RuntimeError(
                f"[DATT-RUNTIME] Web dashboard port {self.web_port} is already in use. "
                f"Please free the port or specify an alternative with --port."
            )

    def start_ai_pipeline(self) -> None:
        """Start the AI detection and tracking pipeline in a dedicated worker thread."""
        logger.info("[DATT-RUNTIME] Starting...")

        def _ai_worker() -> None:
            try:
                from app import run_pipeline
                # Pass stop_event to run_pipeline for coordinated cancellation
                run_pipeline(
                    max_frames=self.max_frames,
                    ui_mode=self.ui_enabled,
                    host=self.ai_host,
                    port=self.ai_port,
                    camera_id=self.camera_id,
                    stop_event=self._stop_event,
                )
            except TypeError:
                # Fallback if run_pipeline doesn't yet take stop_event
                from app import run_pipeline
                run_pipeline(
                    max_frames=self.max_frames,
                    ui_mode=self.ui_enabled,
                    host=self.ai_host,
                    port=self.ai_port,
                    camera_id=self.camera_id,
                )
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.error("[DATT-AI] AI Pipeline crashed: %s", exc, exc_info=True)

        self._ai_thread = threading.Thread(
            target=_ai_worker,
            name="DATT-AIPipelineThread",
            daemon=True,
        )
        self._ai_thread.start()

        # Wait for AI pipeline and camera to initialize
        t0 = time.time()
        while time.time() - t0 < 8.0:
            if self._stop_event.is_set():
                return
            if shared_state.status in ("RUNNING", "ERROR"):
                break
            time.sleep(0.1)

        logger.info("[DATT-AI] Pipeline started")

    def start_web_server(self) -> None:
        """Start FastAPI dashboard in a dedicated daemon thread."""
        if not self.ui_enabled:
            return

        from src.ui.web_server import app as web_app
        web_app.state.backend_url = f"http://{self.ai_host}:{self.ai_port}"

        config = uvicorn.Config(
            web_app,
            host=self.web_host,
            port=self.web_port,
            log_level="warning",
            access_log=False,
        )
        self._uvicorn_server = uvicorn.Server(config)

        def _web_worker() -> None:
            try:
                self._uvicorn_server.run()
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.error("[DATT-WEB] Web server error: %s", exc, exc_info=True)

        self._web_thread = threading.Thread(
            target=_web_worker,
            name="DATT-WebServerThread",
            daemon=True,
        )
        self._web_thread.start()

        # Wait briefly for Uvicorn server to bind
        t0 = time.time()
        while time.time() - t0 < 3.0:
            if self._stop_event.is_set() or (self._uvicorn_server and self._uvicorn_server.started):
                break
            time.sleep(0.05)

        display_host = "localhost" if self.web_host in ("0.0.0.0", "127.0.0.1", "") else self.web_host
        logger.info("[DATT-WEB] Dashboard available: http://%s:%d", display_host, self.web_port)

    def start(self) -> None:
        """Start both the AI pipeline and the web server."""
        self.validate_ports()
        self.start_ai_pipeline()
        self.start_web_server()

    def run(self) -> None:
        """Run runtime manager synchronously, blocking until interrupted."""
        self.start()
        try:
            while not self._stop_event.is_set():
                # If running max_frames test, check if AI thread has concluded
                if self.max_frames is not None and self._ai_thread and not self._ai_thread.is_alive():
                    break
                time.sleep(0.2)
        except KeyboardInterrupt:
            logger.info("Interrupt received by user.")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Coordinate graceful shutdown of all threads and release resources."""
        with self._lock:
            if self._is_shutting_down:
                return
            self._is_shutting_down = True

        logger.info("Initiating graceful DATT shutdown...")
        self._stop_event.set()

        # 1. Stop FastAPI / Uvicorn server
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True

        if self._web_thread is not None and self._web_thread.is_alive():
            self._web_thread.join(timeout=2.0)

        # 2. Stop AI pipeline thread
        if self._ai_thread is not None and self._ai_thread.is_alive():
            self._ai_thread.join(timeout=3.0)

        logger.info("[DATT] Shutdown complete")
