"""DATT - AI People Counter & Vision Monitoring System.

Phase 4.5: Single Unified Application Entry Point.
Starts both the AI processing pipeline and the FastAPI web dashboard
in a single command.

Usage:
    python src/main.py
    python src/main.py --camera camera_01
    python src/main.py --port 8501 --camera camera_02
"""

import argparse
from pathlib import Path
import sys

# Ensure repository root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime.runtime_manager import RuntimeManager


def parse_args() -> argparse.Namespace:
    """Parse command line options for unified DATT runtime."""
    parser = argparse.ArgumentParser(
        description="DATT - AI People Counter & Vision Monitor (Phase 4.5 Unified Runtime)"
    )
    parser.add_argument(
        "--camera",
        type=str,
        default=None,
        help="Initial camera ID from configs/cameras.yaml (default: primary camera)",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        default=True,
        help="Enable FastAPI web dashboard UI (default: True)",
    )
    parser.add_argument(
        "--no-ui",
        action="store_false",
        dest="ui",
        help="Disable web dashboard and run in headless AI mode only",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port for FastAPI web dashboard (default: 8501 for Google Colab)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host interface for web dashboard (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--ai-port",
        type=int,
        default=8000,
        help="Internal port for AI MJPEG stream server (default: 8000)",
    )
    parser.add_argument(
        "--ai-host",
        type=str,
        default="127.0.0.1",
        help="Internal host for AI stream server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Maximum frames to process (useful for automated benchmarks/tests)",
    )
    return parser.parse_args()


def main() -> None:
    """Unified application entry point."""
    args = parse_args()
    manager = RuntimeManager(
        camera_id=args.camera,
        web_host=args.host,
        web_port=args.port,
        ai_host=args.ai_host,
        ai_port=args.ai_port,
        ui_enabled=args.ui,
        max_frames=args.max_frames,
    )
    manager.run()


if __name__ == "__main__":
    main()
