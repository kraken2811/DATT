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
MODEL_PATH: str = str(PROJECT_ROOT / "models" / "yolo11s.pt")
IMG_SIZE: int = 960

# Target device: "cuda:0" on Google Colab GPU runtime, fallback to "cpu" if CUDA unavailable
DEVICE: str = "cuda:0"

# Execution providers for ONNX Runtime compatibility
PROVIDERS: list[Any] = [
    ("DmlExecutionProvider", {"device_id": 0}),
    "CPUExecutionProvider",
]

# ==============================================================================
# 3. DETECTION & TILING CONFIGURATION
# ==============================================================================
PERSON_CLASS_ID: int = 0
CAR_CLASS_ID: int = 2
TARGET_CLASSES: list[int] = [0, 2]
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

# ==============================================================================
# 7. YOUTUBE & STREAM RESOLVER CONFIGURATION
# ==============================================================================
YOUTUBE_MAX_RESOLVE_RETRIES: int = 3
YOUTUBE_RESOLVE_MIN_INTERVAL: float = 3.0    # Minimum interval in seconds between yt-dlp extractions
YOUTUBE_BACKOFF_BASE: float = 10.0           # Base delay in seconds for HTTP 429 exponential backoff
YOUTUBE_BACKOFF_MAX: float = 120.0           # Maximum delay in seconds for HTTP 429
YOUTUBE_BACKOFF_JITTER: float = 5.0          # Random jitter in seconds to prevent thundering herd
YOUTUBE_MAX_CONCURRENT_RESOLVE: int = 1      # Global concurrency limit for yt-dlp extractions
YOUTUBE_URL_TTL_SECONDS: float = 14400.0     # Stream cache TTL in seconds (4 hours default)
STREAM_READ_FAILURE_THRESHOLD: int = 10      # Consecutive frame read failures before reconnecting
STREAM_DIRECT_RECONNECT_RETRIES: int = 3     # Attempts to reconnect using current direct URL before re-resolving
CAMERA_STARTUP_STAGGER: float = 2.0          # Startup delay between initializing multiple cameras

