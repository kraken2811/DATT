"""YOLO11s PyTorch Detector via Ultralytics on CUDA / CPU.

Phase 3 Target:
- Ultralytics YOLO11s (.pt)
- CUDA GPU acceleration (Google Colab / Server)
- Standardized output format {xyxy, confidence, class_id} completely decoupled
  from downstream modules (ByteTrack, ZoneCounter, App).
"""

from pathlib import Path
import time
from typing import Any

import numpy as np
import torch
from ultralytics import YOLO


class DetectionsData(dict):
    """Dictionary-based detections container providing attribute and dict access.

    Decouples detection output from Ultralytics or any specific framework.
    Keys: 'xyxy', 'confidence', 'class_id'
    """

    @property
    def xyxy(self) -> np.ndarray:
        return self["xyxy"]

    @property
    def confidence(self) -> np.ndarray:
        return self["confidence"]

    @property
    def class_id(self) -> np.ndarray:
        return self["class_id"]

    def __len__(self) -> int:
        return len(self["xyxy"])


class YOLODetector:
    """YOLO11s PyTorch detector powered by Ultralytics.

    Maintains identical interface to Phase 2:
        detector = YOLODetector(config)
        detections = detector.detect(frame)
    """

    def __init__(self, config: Any):
        self.config = config

        # 1. Resolve model path (.pt)
        raw_path = getattr(config, "MODEL_PATH", "models/yolo11s.pt")
        model_path = Path(raw_path)
        if not model_path.is_absolute():
            project_root = getattr(config, "PROJECT_ROOT", Path(__file__).resolve().parent.parent.parent)
            model_path = project_root / model_path

        # If .onnx was given in config, seamlessly resolve to .pt
        if model_path.suffix == ".onnx":
            pt_candidate = model_path.with_suffix(".pt")
            if pt_candidate.is_file():
                model_path = pt_candidate
            else:
                alt_pt = model_path.parent / "yolo11s.pt"
                if alt_pt.is_file():
                    model_path = alt_pt

        if not model_path.is_file():
            raise FileNotFoundError(f"Khong tim thay model PyTorch YOLO: {model_path}")

        self.model_path = model_path

        # 2. Configure Device (CUDA if available, else CPU)
        configured_device = getattr(config, "DEVICE", "cuda:0")
        if "cuda" in str(configured_device).lower() and not torch.cuda.is_available():
            self.device = "cpu"
        else:
            self.device = configured_device

        # 3. Load Ultralytics Model
        self.model = YOLO(str(self.model_path))

        # 4. Telemetry and Metadata
        self.device_type: str = "CUDA" if "cuda" in str(self.device).lower() else "CPU"
        self.device_name: str = (
            torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
        )
        self.last_yolo_ms: float = 0.0
        self.last_tile_count: int = 1
        self.last_before_nms: int = 0
        self.last_after_nms: int = 0
        self.vram_allocated_mb: float = 0.0

    def detect(self, frame: np.ndarray) -> DetectionsData:
        """Run YOLO11s inference on frame and return decoupled {xyxy, confidence, class_id}."""
        t0 = time.perf_counter()

        img_size = getattr(self.config, "IMG_SIZE", 640)
        conf_threshold = getattr(self.config, "CONF_THRESHOLD", 0.35)
        nms_threshold = getattr(self.config, "NMS_THRESHOLD", 0.45)
        person_class_id = getattr(self.config, "PERSON_CLASS_ID", 0)
        max_detections = getattr(self.config, "MAX_DETECTIONS", 100)

        # Ultralytics natively handles BGR numpy frames, letterbox resize to imgsz,
        # normalization, inference, and IoU NMS.
        results = self.model(
            frame,
            imgsz=img_size,
            conf=conf_threshold,
            iou=nms_threshold,
            classes=[person_class_id],
            device=self.device,
            verbose=False,
        )

        self.last_yolo_ms = (time.perf_counter() - t0) * 1000

        if torch.cuda.is_available():
            self.vram_allocated_mb = torch.cuda.memory_allocated(0) / (1024 ** 2)
        else:
            self.vram_allocated_mb = 0.0

        # Extract predictions for person class only
        res = results[0]
        if res.boxes is not None and len(res.boxes) > 0:
            boxes = res.boxes
            xyxy = boxes.xyxy.cpu().numpy().astype(np.float32)
            confidence = boxes.conf.cpu().numpy().astype(np.float32)
            class_id = boxes.cls.cpu().numpy().astype(int)
        else:
            xyxy = np.empty((0, 4), dtype=np.float32)
            confidence = np.empty((0,), dtype=np.float32)
            class_id = np.empty((0,), dtype=int)

        self.last_before_nms = len(xyxy)

        # Retain top-K
        if len(xyxy) > max_detections:
            order = np.argsort(confidence)[::-1][:max_detections]
            xyxy = xyxy[order]
            confidence = confidence[order]
            class_id = class_id[order]

        self.last_after_nms = len(xyxy)

        return DetectionsData(
            {
                "xyxy": xyxy,
                "confidence": confidence,
                "class_id": class_id,
            }
        )
