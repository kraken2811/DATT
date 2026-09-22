"""Configuration file for DATT - AI People Counter.

All hyperparameters and runtime settings are centralized here.
No other module should hard-code these values.
"""

from pathlib import Path
from typing import Any

# ==============================================================================
# 1. STREAM & VIDEO CONFIGURATION
# ==============================================================================
YOUTUBE_LINK: str = "https://youtu.be/Cp4RRAEgpeU"
WIDTH: int = 1280
HEIGHT: int = 720

# ==============================================================================
# 2. MODEL & INFERENCE RUNTIME
# ==============================================================================
PROJECT_ROOT: Path = Path(__file__).resolve().parent
MODEL_PATH: str = str(PROJECT_ROOT / "models" / "yolo11s_640.onnx")
IMG_SIZE: int = 640

# Execution providers for ONNX Runtime (DirectML prioritized on Windows, CPU fallback)
PROVIDERS: list[Any] = [
    ("DmlExecutionProvider", {"device_id": 0}),
    "CPUExecutionProvider",
]

# ==============================================================================
# 3. DETECTION & TILING CONFIGURATION
# ==============================================================================
PERSON_CLASS_ID: int = 0
CONF_THRESHOLD: float = 0.35
NMS_THRESHOLD: float = 0.45
MAX_DETECTIONS: int = 100

# Tiling parameters (Test A: 1x1 full-frame; Test B: 1x2 split-frame)
TILE_MODE: bool = True
TILE_ROWS: int = 1
TILE_COLS: int = 1
TILE_OVERLAP: float = 0.15

# ==============================================================================
# 4. TRACKING CONFIGURATION (ByteTrack)
# ==============================================================================
TRACK_ACTIVATION_THRESHOLD: float = 0.40
LOST_TRACK_BUFFER: int = 30
MINIMUM_MATCHING_THRESHOLD: float = 0.80
MINIMUM_CONSECUTIVE_FRAMES: int = 2
TRACKER_FRAME_RATE: float = 30.0

# ==============================================================================
# 5. COUNTING & ZONE CONFIGURATION
# ==============================================================================
# Default zone is full frame [0, 0, WIDTH, HEIGHT] if None.
# Can be defined as a list of (x, y) tuples for ROI polygon.
ZONE_POLYGON: list[tuple[int, int]] | None = None

# ==============================================================================
# 6. DISPLAY & DEBUG CONFIGURATION
# ==============================================================================
SHOW_RAW_DETECTIONS: bool = False
