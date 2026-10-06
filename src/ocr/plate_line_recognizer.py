"""Optional PP-OCRv4 English line recognition on detector-localized plates.

Uses existing ONNX Runtime. No downloads, model installation, DB or watchlist
access at inference time. Model provenance and installation: docs/plate_ocr.md.
"""
from dataclasses import dataclass
import hashlib
import logging
import math
from pathlib import Path
import re
import threading

import cv2
import numpy as np

MODEL_SHA256 = 'e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318'
MODEL_PATH = Path(__file__).resolve().parents[2] / 'models/ocr/en_PP-OCRv4_rec_mobile.onnx'
logger = logging.getLogger('datt.ocr.plate_line')


@dataclass(frozen=True)
class LinePlate:
    text: str
    confidence: float
    raw_text: str
    bbox: tuple[int, int, int, int]
    crop: np.ndarray


class PlateLineRecognizer:
    def __init__(self, path=MODEL_PATH):
        import onnxruntime as ort
        path = Path(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError('Plate line model checksum mismatch')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        providers = ['CPUExecutionProvider']
        if 'CUDAExecutionProvider' in ort.get_available_providers():
            providers.insert(0, 'CUDAExecutionProvider')
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
        chars = self.session.get_modelmeta().custom_metadata_map['character'].splitlines()
        self.characters = [''] + chars + [' ']
        if self.session.get_outputs()[0].shape[-1] != len(self.characters):
            raise ValueError('Plate line model dictionary mismatch')
        self.input_name = self.session.get_inputs()[0].name
        self._lock = threading.Lock()
        logger.info('[PLATE_LINE_MODEL] PP-OCRv4 English providers=%s', self.session.get_providers())

    @staticmethod
    def prepare(image):
        h, w = image.shape[:2]
        width = max(320, min(1024, math.ceil(48 * w / h)))
        resized_width = min(width, math.ceil(48 * w / h))
        pixels = cv2.resize(image, (resized_width, 48)).astype(np.float32)
        tensor = np.zeros((1, 3, 48, width), dtype=np.float32)
        tensor[0, :, :, :resized_width] = (pixels.transpose(2, 0, 1) / 255.0 - .5) / .5
        return tensor

    def read_line(self, image):
        with self._lock:
            probabilities = self.session.run(None, {self.input_name: self.prepare(image)})[0][0]
        if not np.isfinite(probabilities).all():
            return '', 0.0
        indices = probabilities.argmax(axis=1)
        selected = indices != 0
        selected[1:] &= indices[1:] != indices[:-1]
        if not selected.any():
            return '', 0.0
        text = ''.join(self.characters[i] for i in indices[selected])
        score = float(probabilities.max(axis=1)[selected].mean())
        return text, score

    @staticmethod
    def plate_regions(image, bbox):
        """Keep original detector ROI plus one bounded bright-background crop."""
        x1, y1, x2, y2 = map(int, bbox[:4])
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.shape[1], x2), min(image.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            return []
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return []
        regions = [((x1, y1, x2, y2), crop)]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            contour = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(contour)
            if (w >= 15 and h >= 12 and .8 <= w / h <= 6
                    and w * h >= .3 * crop.shape[0] * crop.shape[1]
                    and cv2.contourArea(contour) >= .45 * w * h
                    and (x, y, w, h) != (0, 0, crop.shape[1], crop.shape[0])):
                regions.append(((x1+x, y1+y, x1+x+w, y1+y+h), crop[y:y+h, x:x+w]))
        return regions

    def read_plate(self, image, bbox, validator):
        candidates = []
        for region_bbox, crop in self.plate_regions(image, bbox):
            h, w = crop.shape[:2]
            if h < 12 or w < 15:
                continue
            rows = [crop] if w / h > 2.1 else [crop[:h//2], crop[h//2:]]
            parts = [self.read_line(row) for row in rows]
            # Scores belong to this recognizer, not EasyOCR; both rows must pass.
            if any(not text.strip() or not math.isfinite(score) or score < .80 for text, score in parts):
                continue
            compact = [re.sub(r'[\s./-]', '', text.upper()) for text, _ in parts]
            if len(rows) == 2 and (not re.fullmatch(r'[0-9]{2}[A-Z][A-Z1-9]?', compact[0])
                                  or not re.fullmatch(r'[0-9]{4,5}', compact[1])):
                continue
            text = ''.join(compact)
            if not validator(text):
                continue
            candidates.append(LinePlate(text, min(score for _, score in parts),
                '\n'.join(text for text, _ in parts), region_bbox, crop.copy()))
        if not candidates or len({c.text for c in candidates}) != 1:
            return None
        return max(candidates, key=lambda c: c.confidence)
