"""YOLO11s ONNX Detector with Tiling and IoS NMS.

Executes ONNX Runtime inference (DirectML / CPU), decodes person bounding boxes,
and returns an engine-agnostic dictionary format {xyxy, confidence, class_id}.
"""

from pathlib import Path
import time
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort
import supervision as sv


class DetectionsData(dict):
    """Dictionary-based detections container providing attribute and dict access.

    Decouples detection output from ONNX or any specific framework.
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


def letterbox(image: np.ndarray, size: int = 640) -> tuple[np.ndarray, float, int, int]:
    """Resize image with constant aspect ratio and black padding."""
    h, w = image.shape[:2]
    scale = min(size / w, size / h)
    nw = int(w * scale)
    nh = int(h * scale)

    resized = cv2.resize(image, (nw, nh))
    canvas = np.zeros((size, size, 3), dtype=np.uint8)

    dx = (size - nw) // 2
    dy = (size - nh) // 2

    canvas[dy : dy + nh, dx : dx + nw] = resized
    return canvas, scale, dx, dy


def make_tiles(
    width: int,
    height: int,
    tile_mode: bool = True,
    tile_rows: int = 1,
    tile_cols: int = 1,
    tile_overlap: float = 0.15,
) -> list[tuple[int, int, int, int]]:
    """Compute bounding boxes for overlapping frame tiles."""
    if not tile_mode:
        return [(0, 0, width, height)]
    if tile_rows < 1 or tile_cols < 1 or not 0.0 <= tile_overlap < 0.9:
        raise ValueError("Invalid tile configuration")
    tile_w = width / tile_cols
    tile_h = height / tile_rows
    tiles = []
    for row in range(tile_rows):
        for col in range(tile_cols):
            x1 = max(0, int(col * tile_w - tile_w * tile_overlap / 2))
            y1 = max(0, int(row * tile_h - tile_h * tile_overlap / 2))
            x2 = min(width, int((col + 1) * tile_w + tile_w * tile_overlap / 2))
            y2 = min(height, int((row + 1) * tile_h + tile_h * tile_overlap / 2))
            tiles.append((x1, y1, x2, y2))
    return tiles


def decode_person_boxes(
    output: np.ndarray,
    scale: float,
    dx: int,
    dy: int,
    tx1: int,
    ty1: int,
    frame_w: int,
    frame_h: int,
    person_class_id: int = 0,
    conf_threshold: float = 0.35,
) -> tuple[np.ndarray, np.ndarray]:
    """Map YOLO xywh (letterboxed tile) to person xyxy in original frame coordinates."""
    # Ultralytics ONNX layout: (1, 4+C, N) -> (N, 4+C)
    preds = np.asarray(output)
    if preds.ndim == 3:
        preds = preds[0]
    preds = np.ascontiguousarray(preds.T)
    scores = np.max(preds[:, 4:], axis=1)
    class_ids = np.argmax(preds[:, 4:], axis=1)
    mask = (class_ids == person_class_id) & (scores > conf_threshold)
    if not np.any(mask):
        return np.empty((0, 4), dtype=np.float32), np.empty((0,), dtype=np.float32)

    boxes = preds[mask, :4]
    conf = scores[mask].astype(np.float32)
    xc, yc, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    x1 = tx1 + (xc - w / 2 - dx) / scale
    y1 = ty1 + (yc - h / 2 - dy) / scale
    x2 = tx1 + (xc + w / 2 - dx) / scale
    y2 = ty1 + (yc + h / 2 - dy) / scale
    xyxy = np.stack([x1, y1, x2, y2], axis=1)
    xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, frame_w)
    xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, frame_h)
    valid = (xyxy[:, 2] - xyxy[:, 0] >= 4) & (xyxy[:, 3] - xyxy[:, 1] >= 8)
    return xyxy[valid].astype(np.float32), conf[valid]


def keep_top_k(detections: sv.Detections, max_detections: int) -> sv.Detections:
    """Retain top-K detections with highest confidence."""
    if max_detections < 1 or len(detections) <= max_detections:
        return detections
    if detections.confidence is None:
        return detections.select(slice(0, max_detections))
    order = np.argsort(detections.confidence)[::-1][:max_detections]
    return detections.select(order)


class YOLODetector:
    """YOLO11s ONNX inference engine supporting tiled detection and IoS NMS."""

    def __init__(self, config: Any):
        self.config = config
        self.model_path = Path(config.MODEL_PATH)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Model ONNX khong ton tai: {self.model_path}")

        # Initialize ONNX session
        self.session = ort.InferenceSession(
            str(self.model_path), providers=config.PROVIDERS
        )
        model_inputs = self.session.get_inputs()
        self.input_name = model_inputs[0].name
        self.input_shape = model_inputs[0].shape

        # Validate input dimensions
        if len(self.input_shape) == 4:
            expected_h, expected_w = self.input_shape[2], self.input_shape[3]
            if (
                isinstance(expected_h, int)
                and isinstance(expected_w, int)
                and expected_h > 0
                and expected_w > 0
            ):
                if expected_h != config.IMG_SIZE or expected_w != config.IMG_SIZE:
                    raise ValueError(
                        f"Model expects {expected_h}x{expected_w}, but config IMG_SIZE={config.IMG_SIZE}"
                    )

        # Performance and detection telemetry
        self.last_yolo_ms: float = 0.0
        self.last_tile_count: int = 0
        self.last_before_nms: int = 0
        self.last_after_nms: int = 0

    def detect(self, frame: np.ndarray) -> DetectionsData:
        """Run tiled YOLO inference, IoS NMS, and return independent detection format."""
        frame_h, frame_w = frame.shape[:2]
        tiles = make_tiles(
            frame_w,
            frame_h,
            tile_mode=self.config.TILE_MODE,
            tile_rows=self.config.TILE_ROWS,
            tile_cols=self.config.TILE_COLS,
            tile_overlap=self.config.TILE_OVERLAP,
        )
        self.last_tile_count = len(tiles)

        tile_boxes: list[np.ndarray] = []
        tile_scores: list[np.ndarray] = []

        yolo_start = time.perf_counter()
        for tx1, ty1, tx2, ty2 in tiles:
            tile = frame[ty1:ty2, tx1:tx2]
            if tile.size == 0:
                continue
            img, scale, dx, dy = letterbox(tile, self.config.IMG_SIZE)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)
            tensor = np.ascontiguousarray(img.astype(np.float32) / 255.0)[None, ...]
            output = self.session.run(None, {self.input_name: tensor})[0]
            xyxy, conf = decode_person_boxes(
                output,
                scale,
                dx,
                dy,
                tx1,
                ty1,
                frame_w,
                frame_h,
                person_class_id=self.config.PERSON_CLASS_ID,
                conf_threshold=self.config.CONF_THRESHOLD,
            )
            if len(xyxy):
                tile_boxes.append(xyxy)
                tile_scores.append(conf)

        self.last_yolo_ms = (time.perf_counter() - yolo_start) * 1000

        if tile_boxes:
            boxes = np.concatenate(tile_boxes, axis=0)
            scores = np.concatenate(tile_scores, axis=0)
            detections = sv.Detections(
                xyxy=boxes,
                confidence=scores,
                class_id=np.full(len(boxes), self.config.PERSON_CLASS_ID, dtype=int),
            )
        else:
            detections = sv.Detections(
                xyxy=np.empty((0, 4), dtype=np.float32),
                confidence=np.empty((0,), dtype=np.float32),
                class_id=np.empty((0,), dtype=int),
            )

        self.last_before_nms = len(detections)
        if self.last_before_nms > 0:
            detections = detections.with_nms(
                threshold=self.config.NMS_THRESHOLD,
                class_agnostic=True,
                overlap_metric=sv.OverlapMetric.IOS,
            )
        detections = keep_top_k(detections, self.config.MAX_DETECTIONS)
        self.last_after_nms = len(detections)

        # Return decoupled dictionary format
        return DetectionsData(
            {
                "xyxy": detections.xyxy,
                "confidence": detections.confidence
                if detections.confidence is not None
                else np.empty((0,), dtype=np.float32),
                "class_id": detections.class_id
                if detections.class_id is not None
                else np.empty((0,), dtype=int),
            }
        )
