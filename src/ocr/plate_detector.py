"""Dedicated YOLO-based License Plate Detector.

Wraps a lightweight YOLO model to localize license plate bounding boxes
within a vehicle crop before OCR. Loaded once at process startup.

Supported model sources (in priority order):
1. PLATE_MODEL_PATH from config (explicit .pt/.onnx file).
2. Auto-download from Ultralytics Hub via model slug.
3. Graceful fallback: returns None bboxes (pipeline uses legacy ROI heuristic).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import NamedTuple

import numpy as np

logger = logging.getLogger("datt.ocr.plate_detector")

# Public HuggingFace / Ultralytics Hub model slug for license plate detection.
# keremberke/yolov8n-license-plate-detection covers VN, EU, US plates.
_DEFAULT_HUB_MODEL = "keremberke/yolov8n-license-plate-detection"


class PlateBox(NamedTuple):
    """Single detected license plate region."""

    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float


class PlateDetector:
    """Lightweight YOLO-based license plate localization.

    Usage:
        detector = PlateDetector.get_instance()
        boxes = detector.detect(vehicle_crop)   # list[PlateBox] or []
    """

    _instance: "PlateDetector | None" = None

    def __init__(
        self,
        model_path: str | None = None,
        conf_threshold: float = 0.25,
        device: str = "cpu",
    ) -> None:
        self._model_path = model_path
        self._conf_threshold = conf_threshold
        self._device = device
        self._model = None
        self._initialized = False
        self._error: str | None = None

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "PlateDetector":
        """Return the process-level singleton, initializing on first call."""
        if cls._instance is None:
            try:
                import config as cfg  # type: ignore

                model_path = getattr(cfg, "PLATE_MODEL_PATH", None)
                conf = float(getattr(cfg, "PLATE_DET_CONF", 0.25))
                device = str(getattr(cfg, "DEVICE", "cpu"))
                # Plate detector always runs on CPU to avoid VRAM contention
                if "cuda" in device.lower():
                    import torch
                    device = "cuda:0" if torch.cuda.is_available() else "cpu"
            except ImportError:
                model_path = None
                conf = 0.25
                device = "cpu"

            cls._instance = cls(model_path=model_path, conf_threshold=conf, device=device)
            cls._instance.initialize()
        return cls._instance

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Load the plate detection model.  Returns True on success."""
        if self._initialized:
            return True

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            self._error = f"ultralytics not installed: {exc}"
            logger.warning("[PLATE_MODEL] ultralytics unavailable – plate detector disabled. %s", exc)
            return False

        # 1. Try explicit model path from config
        if self._model_path:
            p = Path(self._model_path)
            if not p.is_absolute():
                try:
                    import config as cfg  # type: ignore
                    p = Path(getattr(cfg, "PROJECT_ROOT", Path(__file__).resolve().parent.parent.parent)) / p
                except ImportError:
                    p = Path(__file__).resolve().parent.parent.parent / p

            if p.is_file():
                try:
                    self._model = YOLO(str(p))
                    logger.info("[PLATE_MODEL] Loaded plate model from %s device=%s conf_thr=%.2f", p, self._device, self._conf_threshold)
                    self._initialized = True
                    return True
                except Exception as exc:
                    logger.warning("[PLATE_MODEL] Failed to load explicit model %s: %s", p, exc)
            else:
                logger.warning("[PLATE_MODEL] PLATE_MODEL_PATH set to '%s' but file not found – trying hub.", self._model_path)

        # 2. Auto-download lightweight hub model
        try:
            logger.info("[PLATE_MODEL] Downloading plate model from hub: %s", _DEFAULT_HUB_MODEL)
            from ultralyticsplus import YOLO as HubYOLO, render_result  # type: ignore  # noqa: F401
            self._model = HubYOLO(_DEFAULT_HUB_MODEL)
            self._model.overrides["conf"] = self._conf_threshold
            self._model.overrides["iou"] = 0.45
            self._model.overrides["agnostic_nms"] = True
            self._model.overrides["max_det"] = 10
            logger.info("[PLATE_MODEL] Hub model loaded: %s", _DEFAULT_HUB_MODEL)
            self._initialized = True
            return True
        except Exception as exc_hub:
            logger.warning("[PLATE_MODEL] ultralyticsplus hub load failed: %s. Trying vanilla ultralytics download.", exc_hub)

        # 3. Vanilla ultralytics auto-download (for models that support hub slug)
        try:
            self._model = YOLO(_DEFAULT_HUB_MODEL)
            logger.info("[PLATE_MODEL] Loaded via vanilla YOLO hub: %s", _DEFAULT_HUB_MODEL)
            self._initialized = True
            return True
        except Exception as exc2:
            logger.warning("[PLATE_MODEL] All plate model load attempts failed: %s. Plate detector disabled.", exc2)
            self._error = str(exc2)
            return False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def detect(self, vehicle_crop: np.ndarray) -> list[PlateBox]:
        """Detect license plate regions within a vehicle crop.

        Args:
            vehicle_crop: BGR numpy array cropped to single vehicle.

        Returns:
            Sorted list of PlateBox detections (highest confidence first).
            Empty list if model unavailable or no plates detected.
        """
        if not self._initialized or self._model is None:
            return []
        if vehicle_crop is None or vehicle_crop.size == 0:
            return []

        h, w = vehicle_crop.shape[:2]
        if h < 15 or w < 15:
            return []

        try:
            results = self._model(
                vehicle_crop,
                conf=self._conf_threshold,
                device=self._device,
                verbose=False,
            )
        except Exception as exc:
            logger.debug("[PLATE_DET] Inference error: %s", exc)
            return []

        boxes: list[PlateBox] = []
        res = results[0] if results else None
        if res is None or res.boxes is None or len(res.boxes) == 0:
            return []

        xyxy = res.boxes.xyxy.cpu().numpy()
        confs = res.boxes.conf.cpu().numpy()

        for (x1, y1, x2, y2), conf in zip(xyxy, confs):
            x1i = max(0, int(round(x1)))
            y1i = max(0, int(round(y1)))
            x2i = min(w, int(round(x2)))
            y2i = min(h, int(round(y2)))
            pw = x2i - x1i
            ph = y2i - y1i
            if pw < 10 or ph < 5:
                continue
            boxes.append(PlateBox(x1=x1i, y1=y1i, x2=x2i, y2=y2i, confidence=float(conf)))

        boxes.sort(key=lambda b: b.confidence, reverse=True)
        return boxes

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if model loaded successfully."""
        return self._initialized and self._model is not None

    @property
    def model_name(self) -> str:
        """Human-readable model identifier."""
        if self._model_path:
            return Path(self._model_path).name
        return _DEFAULT_HUB_MODEL
