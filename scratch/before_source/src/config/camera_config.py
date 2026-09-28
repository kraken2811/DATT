"""Camera Configuration Loader and Validator for DATT.

Phase 4 Version 3: Camera Management & Event Logging.
Replaces hardcoded stream links with centralized YAML camera definitions.
"""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

# Default configuration path relative to repository root
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "cameras.yaml"


@dataclass(frozen=True)
class CameraInfo:
    """Immutable representation of a configured camera source."""

    id: str
    name: str
    type: str  # "youtube", "rtsp", "file", "http"
    url: str
    width: int = 1280
    height: int = 720
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize camera metadata to dictionary."""
        return asdict(self)


def load_cameras(config_path: Path | str | None = None) -> dict[str, CameraInfo]:
    """Load and validate all cameras defined in cameras.yaml.

    Args:
        config_path: Path to cameras.yaml. Defaults to configs/cameras.yaml.

    Returns:
        dict[str, CameraInfo]: Map of camera_id -> CameraInfo.

    Raises:
        FileNotFoundError: If the configuration file cannot be found.
        ValueError: If configuration syntax or camera fields are invalid.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Camera configuration file not found at: {path}")

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(f"Failed to parse cameras YAML config: {exc}") from exc

    if not isinstance(data, dict) or "cameras" not in data:
        raise ValueError("Invalid cameras.yaml structure: root key 'cameras' missing.")

    raw_cameras = data.get("cameras", {})
    if not isinstance(raw_cameras, dict) or len(raw_cameras) == 0:
        raise ValueError("No camera configurations found in cameras.yaml.")

    cameras: dict[str, CameraInfo] = {}
    for cam_id, cam_data in raw_cameras.items():
        if not isinstance(cam_data, dict):
            continue

        name = cam_data.get("name", cam_id)
        cam_type = str(cam_data.get("type", "youtube")).lower()
        url = str(cam_data.get("url", "")).strip()
        width = int(cam_data.get("width", 1280))
        height = int(cam_data.get("height", 720))
        desc = str(cam_data.get("description", ""))

        if not url:
            raise ValueError(f"Camera '{cam_id}' is missing a valid 'url' parameter.")

        valid_types = {"youtube", "rtsp", "file", "http", "https"}
        if cam_type not in valid_types:
            raise ValueError(
                f"Camera '{cam_id}' has unsupported type '{cam_type}'. Valid: {valid_types}"
            )

        cameras[cam_id] = CameraInfo(
            id=cam_id,
            name=name,
            type=cam_type,
            url=url,
            width=width,
            height=height,
            description=desc,
        )

    return cameras


def get_camera(camera_id: str, config_path: Path | str | None = None) -> CameraInfo:
    """Retrieve a single camera by ID."""
    cameras = load_cameras(config_path)
    if camera_id not in cameras:
        available = list(cameras.keys())
        raise KeyError(f"Camera '{camera_id}' not found. Available cameras: {available}")
    return cameras[camera_id]


def list_cameras(config_path: Path | str | None = None) -> list[CameraInfo]:
    """Return all configured cameras as an ordered list."""
    return list(load_cameras(config_path).values())


def get_default_camera(config_path: Path | str | None = None) -> CameraInfo:
    """Return the first configured camera as the primary default."""
    cams = list_cameras(config_path)
    if not cams:
        raise RuntimeError("No cameras available in configuration.")
    return cams[0]
