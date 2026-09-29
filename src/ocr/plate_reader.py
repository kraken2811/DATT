"""License Plate Localization and Optical Character Recognition (OCR).

Decoupled, modular OCR pipeline for vehicles:
1. Receives vehicle crop (never full frame).
2. Stage 0: Dedicated YOLO plate detector localizes plate bbox within vehicle crop.
3. Crops and enhances the tight plate region (contrast, denoising, adaptive thresholding).
4. Runs OCR (EasyOCR with fallback support) to extract plate text and confidence.
5. Emits structured PlateCandidate diagnostics and bounded visual proof in scratch/plate_debug/.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
import re
import threading
from typing import Any, Sequence

import cv2
import numpy as np

logger = logging.getLogger("datt.ocr.plate_reader")

# Lazy import – avoids circular imports at module load time
_plate_detector_module = None


def _get_plate_detector():
    """Return the global PlateDetector singleton (lazy import)."""
    global _plate_detector_module
    if _plate_detector_module is None:
        try:
            from src.ocr.plate_detector import PlateDetector  # noqa: PLC0415
            _plate_detector_module = PlateDetector.get_instance()
        except Exception as exc:
            logger.warning("[PLATE_MODEL] Could not load PlateDetector: %s", exc)
            _plate_detector_module = False  # sentinel – don't retry
    if _plate_detector_module is False:
        return None
    return _plate_detector_module


@dataclass
class PlateCandidate:
    """Structured license plate recognition result."""
    plate_text: str
    confidence: float
    # [x1, y1, x2, y2] relative to vehicle crop
    bbox_vehicle: tuple[int, int, int, int]
    # [x1, y1, x2, y2] in native full-frame coordinates
    bbox_native: tuple[int, int, int, int]
    raw_crop: np.ndarray
    preprocessed_crop: np.ndarray
    sharpness: float
    quality_score: float
    raw_text: str = ""
    normalized_text: str = ""

    def __post_init__(self):
        if not self.raw_text:
            self.raw_text = self.plate_text
        self.normalized_text = normalize_plate_text(self.plate_text)


LicensePlateCandidate = PlateCandidate


def clean_plate_text(raw_text: str) -> str:
    """Standardize and sanitize raw OCR license plate string.

    Converts to uppercase, normalizes delimiters (/ \n space) between plate parts to '-',
    retaining alphanumeric characters, hyphens, and dots.
    """
    if not raw_text:
        return ""
    # Uppercase
    cleaned = raw_text.strip().upper()
    # Normalize slash, newline, and spaces between plate segments to hyphen
    cleaned = re.sub(r"[\s/]+", "-", cleaned)
    # Remove all characters except alphanumeric, hyphen, dot
    cleaned = cleaned  # Preserve unknown characters so validation can reject noise.
    # Collapse multiple consecutive hyphens or dots
    cleaned = re.sub(r"[\-\.]{2,}", "-", cleaned)
    # Strip leading/trailing hyphens or dots
    cleaned = cleaned.strip("-.")

    return cleaned


def normalize_plate_text(raw_text: str) -> str:
    """Remove presentation separators only. Never guess O/0, I/1, B/8, etc."""
    return re.sub(r"[\s./-]", "", raw_text.upper())


def is_valid_plate_format(text: str) -> bool:
    """Conservative ordinary VN civilian plates, including legacy 4-digit plates.

    Special diplomatic/military/temporary formats are intentionally unsupported.
    Recognizes car series, legacy motorcycle letter+digit, and new two-letter series.
    """
    if not text or re.search(r"[^A-Za-z0-9\s./-]", text):
        return False
    compact = normalize_plate_text(text)
    provinces = {11, 12, *range(14, 30), *range(30, 42), 43, *range(47, 87),
                 88, 89, 90, 92, 93, 94, 95, 97, 98, 99}
    match = re.fullmatch(r"([0-9]{2})([ABCDEFGHKLMNPRSTUVXYZ](?:[ABCDEFGHKLMNPRSTUVXYZ]|[1-9])?)([0-9]{4,5})", compact)
    return bool(match and int(match[1]) in provinces and int(match[3]) != 0)


def order_quad_points(pts: np.ndarray) -> np.ndarray:
    """Sort 4 quad corner points in consistent order: [top-left, top-right, bottom-right, bottom-left]."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]

    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def fuse_plate_crops(crops: Sequence[np.ndarray]) -> np.ndarray | None:
    """Deterministic multi-frame real evidence fusion across real observed plate crops.

    Aligns crops using geometric registration (ECC / affine) to the sharpest reference
    and computes a temporal median stack. Zero generative AI hallucination.
    """
    if not crops:
        return None
    valid_crops = [c for c in crops if c is not None and isinstance(c, np.ndarray) and c.size > 0 and c.shape[0] >= 8 and c.shape[1] >= 15]
    if not valid_crops:
        return None
    if len(valid_crops) == 1:
        return valid_crops[0]

    def _sharpness(img: np.ndarray) -> float:
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        return float(cv2.Laplacian(g, cv2.CV_32F).var())

    sharpnesses = [_sharpness(c) for c in valid_crops]
    ref_idx = int(np.argmax(sharpnesses))
    ref_crop = valid_crops[ref_idx]
    ref_h, ref_w = ref_crop.shape[:2]
    ref_gray = cv2.cvtColor(ref_crop, cv2.COLOR_BGR2GRAY) if len(ref_crop.shape) == 3 else ref_crop

    aligned_stack = [ref_crop.astype(np.float32)]

    for i, c in enumerate(valid_crops):
        if i == ref_idx:
            continue
        c_h, c_w = c.shape[:2]
        if c_h != ref_h or c_w != ref_w:
            c_res = cv2.resize(c, (ref_w, ref_h), interpolation=cv2.INTER_CUBIC)
        else:
            c_res = c.copy()

        c_gray = cv2.cvtColor(c_res, cv2.COLOR_BGR2GRAY) if len(c_res.shape) == 3 else c_res

        try:
            warp_matrix = np.eye(2, 3, dtype=np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.01)
            _, warp_matrix = cv2.findTransformECC(ref_gray, c_gray, warp_matrix, cv2.MOTION_TRANSLATION, criteria, None, 5)
            aligned = cv2.warpAffine(c_res, warp_matrix, (ref_w, ref_h), flags=cv2.INTER_CUBIC + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
            aligned_stack.append(aligned.astype(np.float32))
        except Exception:
            aligned_stack.append(c_res.astype(np.float32))

    fused = np.median(aligned_stack, axis=0).astype(np.uint8)
    return fused


class LicensePlateReader:
    """Thread-safe singleton for localized vehicle license plate detection and OCR."""

    _instance: "LicensePlateReader | None" = None
    _lock = threading.Lock()

    def __init__(self, min_confidence: float = 0.35) -> None:
        self.min_confidence = min_confidence
        self._reader = None
        self._reader_initialized = False
        self._reader_error: str | None = None
        self._device: str = "CPU"
        self._infer_lock = threading.Lock()
        self._ocr_context = threading.local()

        # Bounded debug sample tracking in scratch/plate_debug/
        self._debug_dir = Path("scratch/plate_debug")
        self._debug_sample_count = 0
        self._max_debug_samples = 15

        # Stage 0: dedicated plate detector (loaded once at init)
        self._plate_detector = _get_plate_detector()
        if self._plate_detector is not None and self._plate_detector.is_available:
            logger.info(
                "[PLATE_MODEL] PlateDetector ready: model=%s",
                self._plate_detector.model_name,
            )
        else:
            logger.info("[PLATE_MODEL] PlateDetector unavailable – will use ROI heuristic fallback.")

    @property
    def device(self) -> str:
        """Current execution device for EasyOCR ('CUDA' or 'CPU')."""
        return self._device

    @classmethod
    def get_instance(cls) -> "LicensePlateReader":
        """Thread-safe singleton accessor."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def initialize(self) -> bool:
        """Initialize EasyOCR reader with GPU acceleration when CUDA is available, with safe CPU fallback."""
        with self._infer_lock:
            if self._reader_initialized:
                return True
            if self._reader_error is not None:
                return False

            try:
                import easyocr
            except ImportError as exc:
                self._reader_error = str(exc)
                logger.warning("[OCR] Could not import easyocr: %s. Using classical CV fallback.", exc)
                return False

            # Safe CUDA availability detection
            use_gpu = False
            try:
                import torch
                if torch.cuda.is_available():
                    use_gpu = True
            except Exception as torch_exc:
                logger.debug("[OCR] PyTorch CUDA check failed: %s", torch_exc)
                use_gpu = False

            if use_gpu:
                logger.info("[OCR] Initializing EasyOCR reader (GPU mode)...")
                try:
                    try:
                        self._reader = easyocr.Reader(["en"], gpu=True, download_enabled=False)
                    except Exception:
                        self._reader = easyocr.Reader(["en"], gpu=True, download_enabled=True)

                    self._device = "CUDA"
                    self._reader_initialized = True
                    logger.info("[OCR] EasyOCR device=CUDA")
                    logger.info("[OCR] EasyOCR reader successfully initialized.")
                    return True
                except Exception as gpu_exc:
                    logger.warning("[OCR] GPU initialization failed: %s", gpu_exc)
                    logger.warning("[OCR] GPU initialization failed, falling back to CPU...")
                    use_gpu = False

            # CPU mode (fallback or CUDA unavailable)
            logger.info("[OCR] Initializing EasyOCR reader (CPU mode)...")
            try:
                try:
                    self._reader = easyocr.Reader(["en"], gpu=False, download_enabled=False)
                except Exception:
                    self._reader = easyocr.Reader(["en"], gpu=False, download_enabled=True)

                self._device = "CPU"
                self._reader_initialized = True
                logger.info("[OCR] EasyOCR device=CPU")
                logger.info("[OCR] EasyOCR reader successfully initialized.")
                return True
            except Exception as exc:
                self._reader_error = str(exc)
                logger.warning("[OCR] Could not initialize EasyOCR reader: %s. Using classical CV fallback.", exc)
                return False

    def rectify_plate_perspective(
        self,
        vehicle_crop: np.ndarray,
        plate_bbox: tuple[int, int, int, int] | Sequence[int],
    ) -> tuple[np.ndarray, float]:
        """Detect plate orientation/corners and apply perspective rectification / deskew into a normalized crop."""
        if vehicle_crop is None or vehicle_crop.size == 0:
            return vehicle_crop, 0.0

        vh, vw = vehicle_crop.shape[:2]
        px1, py1, px2, py2 = [int(v) for v in plate_bbox[:4]]
        pw = max(0, px2 - px1)
        ph = max(0, py2 - py1)
        if pw < 10 or ph < 8:
            return vehicle_crop[py1:py2, px1:px2], 0.0

        pad_x = max(4, int(pw * 0.12))
        pad_y = max(4, int(ph * 0.15))
        rx1 = max(0, px1 - pad_x)
        ry1 = max(0, py1 - pad_y)
        rx2 = min(vw, px2 + pad_x)
        ry2 = min(vh, py2 + pad_y)

        roi = vehicle_crop[ry1:ry2, rx1:rx2]
        if roi.size == 0 or roi.shape[0] < 10 or roi.shape[1] < 15:
            return vehicle_crop[py1:py2, px1:px2], 0.0

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(thresh) > 127:
            thresh_inv = cv2.bitwise_not(thresh)
        else:
            thresh_inv = thresh

        contours, _ = cv2.findContours(thresh_inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_quad = None
        best_angle = 0.0
        roi_area = roi.shape[0] * roi.shape[1]

        valid_contours = []
        for cnt in contours:
            c_area = cv2.contourArea(cnt)
            if c_area < roi_area * 0.10:
                continue
            rect = cv2.minAreaRect(cnt)
            (cx, cy), (w, h), angle = rect
            if w < 10 or h < 8:
                continue
            aspect = max(w, h) / max(1.0, min(w, h))
            if 1.0 <= aspect <= 6.0:
                valid_contours.append((cnt, c_area, rect))

        if valid_contours:
            valid_contours.sort(key=lambda x: x[1], reverse=True)
            _, _, chosen_rect = valid_contours[0]
            (cx, cy), (rw, rh), angle = chosen_rect
            if rw < rh:
                angle = angle - 90.0
                rw, rh = rh, rw
            while angle < -45.0:
                angle += 90.0
            while angle > 45.0:
                angle -= 90.0
            best_angle = angle
            best_quad = cv2.boxPoints(chosen_rect)
        else:
            coords = np.column_stack(np.where(thresh_inv > 0))
            if len(coords) > 30:
                pts = np.fliplr(coords)
                rect = cv2.minAreaRect(pts)
                (cx, cy), (rw, rh), angle = rect
                if rw < rh:
                    angle = angle - 90.0
                    rw, rh = rh, rw
                while angle < -45.0:
                    angle += 90.0
                while angle > 45.0:
                    angle -= 90.0
                best_angle = angle
                best_quad = cv2.boxPoints(rect)

        if best_quad is not None and abs(best_angle) >= 1.5:
            src_pts = order_quad_points(best_quad)
            w_top = np.linalg.norm(src_pts[1] - src_pts[0])
            w_bot = np.linalg.norm(src_pts[2] - src_pts[3])
            dst_w = max(24, int(max(w_top, w_bot)))

            h_left = np.linalg.norm(src_pts[3] - src_pts[0])
            h_right = np.linalg.norm(src_pts[2] - src_pts[1])
            dst_h = max(12, int(max(h_left, h_right)))

            if dst_w < dst_h * 1.1:
                dst_w, dst_h = dst_h, dst_w

            dst_pts = np.array([
                [0, 0],
                [dst_w - 1, 0],
                [dst_w - 1, dst_h - 1],
                [0, dst_h - 1]
            ], dtype=np.float32)

            M = cv2.getPerspectiveTransform(src_pts, dst_pts)
            rectified = cv2.warpPerspective(roi, M, (dst_w, dst_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            return rectified, round(float(best_angle), 1)

        return vehicle_crop[py1:py2, px1:px2], 0.0

    def deskew_plate(self, crop: np.ndarray) -> tuple[np.ndarray, float]:
        """Detect tilt angle and apply perspective / affine deskew correction.

        Uses minAreaRect on segmented plate text and contours.
        Returns:
            rectified: Deskewed crop (or original if tilt is negligible).
            deskew_angle: Detected skew angle in degrees (0.0 if not deskewed).
        """
        if crop is None or crop.size == 0:
            return crop, 0.0

        h, w = crop.shape[:2]
        if h < 12 or w < 12:
            return crop, 0.0

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop.copy()
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        if np.mean(thresh) > 127:
            thresh = cv2.bitwise_not(thresh)

        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 30:
            return crop, 0.0

        pts = np.fliplr(coords)
        rect = cv2.minAreaRect(pts)
        angle = rect[-1]
        rw, rh = rect[1]

        if rw < rh:
            angle = angle - 90.0
        while angle < -45.0:
            angle += 90.0
        while angle > 45.0:
            angle -= 90.0

        # Ignore tiny tilt (< 1.2 deg) or extreme skew (> 35 deg)
        if abs(angle) < 1.2 or abs(angle) > 35.0:
            return crop, 0.0

        center = (w / 2.0, h / 2.0)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rectified = cv2.warpAffine(crop, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return rectified, round(float(angle), 1)

    def generate_preprocessing_variants(
        self,
        crop: np.ndarray,
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        """Generate 3 image variants for OCR and extract diagnostic metadata.

        Steps:
        1. Perspective / deskew correction if tilted.
        2. Adaptive aspect-ratio-preserving resize (standardizing height for small/large crops).
        3. Diagnostic metrics: brightness (mean) and contrast (std).
        4. Gamma correction for dark (<75) or overexposed/glaring (>180) images.
        5. CLAHE (Contrast Limited Adaptive Histogram Equalization).
        6. Bilateral filtering for denoising without losing character sharpness.
        7. Mild unsharp masking.
        8. Adaptive / Otsu binarization.

        Returns:
            variants:
                'ORIGINAL/RESIZED': Rectified, aspect-ratio-preserved color crop.
                'ENHANCED_GRAY': Grayscale, gamma-corrected, CLAHE, bilateral, sharpened crop.
                'BINARIZED': Clean 3-channel binarized crop.
            meta:
                'plate_size': (w, h) of raw crop.
                'deskew': deskew angle in degrees.
                'brightness': mean luminance before CLAHE.
                'contrast': luminance standard deviation.
                'scale': resize scaling factor.
                'rectified': rectified BGR crop.
                'enhanced': enhanced BGR crop.
                'binary': binary BGR crop.
        """
        if crop is None or crop.size == 0:
            empty = np.zeros((32, 32, 3), dtype=np.uint8)
            return {"ORIGINAL/RESIZED": empty, "ENHANCED_GRAY": empty, "BINARIZED": empty}, {
                "plate_size": (0, 0), "deskew": 0.0, "brightness": 0.0, "contrast": 0.0, "scale": 1.0,
                "rectified": empty, "enhanced": empty, "binary": empty
            }

        h0, w0 = crop.shape[:2]

        # 1. Perspective correction / deskew
        rectified, deskew_angle = self.deskew_plate(crop)

        # 2. Adaptive resize (preserving aspect ratio strictly)
        hr, wr = rectified.shape[:2]
        scale = 1.0
        if hr < 64 and hr > 0:
            scale = 64.0 / float(hr)
        elif hr > 240:
            scale = 240.0 / float(hr)

        if abs(scale - 1.0) > 0.01:
            new_w = max(32, int(round(wr * scale)))
            new_h = max(24, int(round(hr * scale)))
            interp = cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA
            resized = cv2.resize(rectified, (new_w, new_h), interpolation=interp)
        else:
            resized = rectified.copy()

        # Variant 1: ORIGINAL/RESIZED (BGR)
        orig_resized_bgr = resized if len(resized.shape) == 3 else cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)

        # 3. Brightness, Contrast & Grayscale conversion
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if len(resized.shape) == 3 else resized.copy()
        brightness = float(np.mean(gray))
        contrast = float(np.std(gray))

        # 4. Gamma correction
        if brightness < 75.0:
            gamma = 0.65
        elif brightness > 180.0:
            gamma = 1.45
        else:
            gamma = 1.0

        if abs(gamma - 1.0) > 0.01:
            lut = np.array([((i / 255.0) ** gamma) * 255.0 for i in range(256)]).astype(np.uint8)
            gamma_corrected = cv2.LUT(gray, lut)
        else:
            gamma_corrected = gray.copy()

        # 5. CLAHE contrast enhancement
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(4, 4))
        enhanced = clahe.apply(gamma_corrected)

        # 6. Bilateral filtering (noise suppression without character blur)
        denoised = cv2.bilateralFilter(enhanced, d=5, sigmaColor=35, sigmaSpace=35)

        # 7. Mild sharpening
        blurred = cv2.GaussianBlur(denoised, (0, 0), sigmaX=1.0)
        sharpened = cv2.addWeighted(denoised, 1.25, blurred, -0.25, 0)
        enhanced_bgr = cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)

        # 8. Adaptive / Otsu binarization
        _, binary = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary) < 127:
            binary = cv2.bitwise_not(binary)
        binary_bgr = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

        variants = {
            "ORIGINAL/RESIZED": orig_resized_bgr,
            "ENHANCED_GRAY": enhanced_bgr,
            "BINARIZED": binary_bgr,
        }
        meta = {
            "plate_size": (w0, h0),
            "deskew": deskew_angle,
            "brightness": round(brightness, 1),
            "contrast": round(contrast, 1),
            "scale": round(scale, 2),
            "rectified": rectified,
            "enhanced": enhanced_bgr,
            "binary": binary_bgr,
        }
        return variants, meta

    def preprocess_plate_crop(self, crop: np.ndarray) -> np.ndarray:
        """Enhance plate readability via deskew, adaptive resize, gamma, CLAHE, bilateral denoise, and sharpening."""
        if crop is None or crop.size == 0:
            return crop
        variants, _ = self.generate_preprocessing_variants(crop)
        return variants.get("ENHANCED_GRAY", crop)

    def _parse_plate_text_from_ocr_boxes(self, ocr_results: list[Any]) -> tuple[str, float]:
        """Extract plate text and confidence from EasyOCR bounding boxes on a plate crop.

        Handles both 1-line plates and stacked 2-tier plates.
        """
        self._ocr_context.parsed_raw = ""
        if not ocr_results:
            return "", 0.0

        boxes = []
        for poly, raw_text, conf in ocr_results:
            cleaned = clean_plate_text(raw_text)
            if not cleaned:
                continue
            cys = [pt[1] for pt in poly]
            cxs = [pt[0] for pt in poly]
            cy = sum(cys) / len(cys)
            cx = sum(cxs) / len(cxs)
            boxes.append({"raw": raw_text, "cleaned": cleaned, "conf": float(conf), "cx": cx, "cy": cy})

        if not boxes:
            return "", 0.0
        if len(boxes) == 1:
            self._ocr_context.parsed_raw = boxes[0]["raw"]
            return boxes[0]["cleaned"], boxes[0]["conf"]

        # Check vertical separation for 2-tier stacked plate
        by_y = sorted(boxes, key=lambda b: b["cy"])
        max_dy = by_y[-1]["cy"] - by_y[0]["cy"]
        if max_dy > 12:
            # 2-Tier plate (top line to bottom line)
            self._ocr_context.parsed_raw = "\n".join(b["raw"] for b in by_y)
            merged = clean_plate_text("-".join(b["cleaned"] for b in by_y))
            avg_conf = sum(b["conf"] for b in by_y) / len(by_y)
            return merged, round(avg_conf, 3)
        else:
            # Horizontal boxes
            by_x = sorted(boxes, key=lambda b: b["cx"])
            self._ocr_context.parsed_raw = " ".join(b["raw"] for b in by_x)
            merged = clean_plate_text("-".join(b["cleaned"] for b in by_x))
            avg_conf = sum(b["conf"] for b in by_x) / len(by_x)
            return merged, round(avg_conf, 3)

    def evaluate_variants(
        self,
        variants: dict[str, np.ndarray],
        baseline_text: str = "",
        baseline_conf: float = 0.0,
        track_id: int = -1,
        frame_id: int = -1,
    ) -> tuple[str, str, float, np.ndarray]:
        """Run EasyOCR on variants and select the best candidate.

        Selection criteria:
        1. OCR confidence
        2. Valid plate format
        3. Text completeness

        Returns:
            (selected_variant_name, best_text, best_conf, best_img)
        """
        default_vname = "ENHANCED_GRAY" if "ENHANCED_GRAY" in variants else list(variants.keys())[0]
        default_img = variants.get(default_vname, list(variants.values())[0])

        if self._reader is None:
            return default_vname, baseline_text, baseline_conf, default_img

        self._ocr_context.selected_raw = baseline_text
        candidates = []

        # Baseline evaluation (from initial vehicle detection pass)
        if baseline_text:
            cleaned_base = clean_plate_text(baseline_text)
            is_valid_base = is_valid_plate_format(cleaned_base)
            alnum_base = sum(1 for c in cleaned_base if c.isalnum())
            comp_base = min(alnum_base / 8.0, 1.0)
            bonus_base = 0.5 if (any(c.isalpha() for c in cleaned_base) and any(c.isdigit() for c in cleaned_base) and alnum_base >= 6) else 0.0
            base_score = (baseline_conf * 1.0) + (2.0 if is_valid_base else 0.0) + (comp_base * 0.8) + bonus_base
            candidates.append({
                "variant": "ENHANCED_GRAY",
                "text": cleaned_base,
                "raw": baseline_text,
                "conf": baseline_conf,
                "score": base_score,
                "img": default_img,
            })
            logger.info(
                "[PLATE_OCR] track_id=%d frame_id=%d baseline_text='%s' cleaned='%s' conf=%.3f valid=%s score=%.2f",
                track_id, frame_id, baseline_text, cleaned_base, baseline_conf, is_valid_base, base_score,
            )

        # Cascade OCR variants: ORIGINAL -> fail mới ENHANCED -> fail mới BINARY
        cascade_order = ["ORIGINAL/RESIZED", "ENHANCED_GRAY", "BINARIZED"]
        for vname in cascade_order:
            img = variants.get(vname)
            if img is None or img.size == 0:
                continue
            with self._infer_lock:
                try:
                    ocr_res = self._reader.readtext(img)
                except Exception as exc:
                    logger.debug("[OCR] Error reading variant %s: %s", vname, exc)
                    ocr_res = []

            text, conf = self._parse_plate_text_from_ocr_boxes(ocr_res)
            if not text:
                logger.info(
                    "[PLATE_OCR] track_id=%d frame_id=%d variant=%s raw_boxes=%d text='' (empty) -> try next in cascade",
                    track_id, frame_id, vname, len(ocr_res),
                )
                continue

            is_valid = is_valid_plate_format(text)
            raw = getattr(self._ocr_context, "parsed_raw", text)
            observation = {"raw_text": raw, "normalized_text": normalize_plate_text(text),
                           "confidence": conf, "valid": is_valid, "variant": vname}
            if hasattr(self._ocr_context, "observations"):
                self._ocr_context.observations.append(observation)
            logger.info("[PLATE_OCR_RAW] track=%s frame=%s observation=%s", track_id, frame_id, observation)
            alnum_cnt = sum(1 for c in text if c.isalnum())
            comp = min(alnum_cnt / 8.0, 1.0)
            bonus = 0.5 if (any(c.isalpha() for c in text) and any(c.isdigit() for c in text) and alnum_cnt >= 6) else 0.0
            score = (conf * 1.0) + (2.0 if is_valid else 0.0) + (comp * 0.8) + bonus

            logger.info(
                "[PLATE_OCR] track_id=%d frame_id=%d cascade_variant=%s raw_boxes=%d text='%s' conf=%.3f valid=%s score=%.2f",
                track_id, frame_id, vname, len(ocr_res), text, conf, is_valid, score,
            )

            cand = {
                "variant": vname,
                "text": text,
                "raw": getattr(self._ocr_context, "parsed_raw", text),
                "conf": conf,
                "score": score,
                "img": img,
            }
            candidates.append(cand)

            # Cascade early-exit: If valid complete plate format and acceptable confidence, STOP cascade!
            is_complete = (
                is_valid
                and alnum_cnt >= 5
                and any(c.isalpha() for c in text)
                and any(c.isdigit() for c in text)
            )
            if is_complete and conf >= self.min_confidence:
                logger.info(
                    "[PLATE_OCR] track_id=%d frame_id=%d CASCADE SUCCESS on variant=%s (text='%s', conf=%.3f) -> stopping cascade early",
                    track_id, frame_id, vname, text, conf,
                )
                self._ocr_context.selected_raw = cand["raw"]
                return vname, text, conf, img

        if not candidates:
            return default_vname, baseline_text, baseline_conf, default_img

        # Sort candidates by score descending
        candidates.sort(key=lambda c: c["score"], reverse=True)
        winner = candidates[0]
        logger.info(
            "[PLATE_OCR] track_id=%d frame_id=%d WINNER variant=%s text='%s' conf=%.3f score=%.2f",
            track_id, frame_id, winner["variant"], winner["text"], winner["conf"], winner["score"],
        )
        self._ocr_context.selected_raw = winner["raw"]
        return winner["variant"], winner["text"], winner["conf"], winner["img"]

    def _save_debug_sample(
        self,
        vehicle_crop: np.ndarray,
        plate_crop: np.ndarray,
        preprocessed_crop: np.ndarray,
        track_id: int,
        frame_id: int,
        plate_text: str,
        conf: float,
        rectified_crop: np.ndarray | None = None,
        binary_crop: np.ndarray | None = None,
    ) -> None:
        """Save bounded proof of plate acquisition in scratch/plate_debug/."""
        if self._debug_sample_count >= self._max_debug_samples:
            return

        try:
            self._debug_dir.mkdir(parents=True, exist_ok=True)
            self._debug_sample_count += 1
            prefix = f"f{frame_id}_v{track_id}"

            # Direct standard filenames requested
            if plate_crop is not None and plate_crop.size > 0:
                cv2.imwrite(str(self._debug_dir / "plate_original.jpg"), plate_crop)
                cv2.imwrite(str(self._debug_dir / f"{prefix}_plate_original.jpg"), plate_crop)
                cv2.imwrite(str(self._debug_dir / f"{prefix}_plate_{plate_text}.jpg"), plate_crop)

            rect_img = rectified_crop if (rectified_crop is not None and rectified_crop.size > 0) else plate_crop
            if rect_img is not None and rect_img.size > 0:
                cv2.imwrite(str(self._debug_dir / "plate_rectified.jpg"), rect_img)
                cv2.imwrite(str(self._debug_dir / f"{prefix}_plate_rectified.jpg"), rect_img)

            if preprocessed_crop is not None and preprocessed_crop.size > 0:
                cv2.imwrite(str(self._debug_dir / "plate_enhanced.jpg"), preprocessed_crop)
                cv2.imwrite(str(self._debug_dir / f"{prefix}_plate_enhanced.jpg"), preprocessed_crop)
                cv2.imwrite(str(self._debug_dir / f"{prefix}_preprocessed.jpg"), preprocessed_crop)

            bin_img = binary_crop
            if bin_img is None and preprocessed_crop is not None and preprocessed_crop.size > 0:
                gray = cv2.cvtColor(preprocessed_crop, cv2.COLOR_BGR2GRAY) if len(preprocessed_crop.shape) == 3 else preprocessed_crop
                _, bin_raw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                bin_img = cv2.cvtColor(bin_raw, cv2.COLOR_GRAY2BGR)

            if bin_img is not None and bin_img.size > 0:
                cv2.imwrite(str(self._debug_dir / "plate_binary.jpg"), bin_img)
                cv2.imwrite(str(self._debug_dir / f"{prefix}_plate_binary.jpg"), bin_img)

            if vehicle_crop is not None and vehicle_crop.size > 0:
                cv2.imwrite(str(self._debug_dir / f"{prefix}_vehicle.jpg"), vehicle_crop)

            logger.info(
                "[PLATE_DEBUG] Saved bounded plate debug sample %d/%d (text='%s', conf=%.2f) to %s",
                self._debug_sample_count, self._max_debug_samples, plate_text, conf, self._debug_dir
            )
        except Exception as exc:
            logger.warning("[PLATE_DEBUG] Failed to save plate debug sample: %s", exc)

    def _parse_plate_candidates(
        self,
        ocr_results: list[Any],
        vehicle_crop: np.ndarray,
        roi_y1: int,
        vx1: int,
        vy1: int,
        vw: int,
        vh: int,
        track_id: int = -1,
        frame_id: int = -1,
    ) -> list[PlateCandidate]:
        """Group and assemble OCR text boxes into 1-line or 2-tier plate candidates."""
        logger.info(
            "[PLATE_DET] track_id=%d frame_id=%d raw_boxes_count=%d in search_roi",
            track_id, frame_id, len(ocr_results) if ocr_results else 0,
        )
        parsed_boxes = []
        for poly, raw_text, conf in ocr_results:
            conf = float(conf)
            cleaned = clean_plate_text(raw_text)
            pxs = [pt[0] for pt in poly]
            pys = [pt[1] for pt in poly]
            x1 = max(0, int(min(pxs)))
            y1 = max(0, int(min(pys)))
            x2 = min(vw, int(max(pxs)))
            y2 = min(vh - roi_y1, int(max(pys)))
            pw = x2 - x1
            ph = y2 - y1

            passed_min_conf = (conf >= self.min_confidence)
            passed_size = (pw >= 8 and ph >= 6)
            logger.info(
                "[PLATE_DET] track_id=%d frame_id=%d raw_box: text='%s' cleaned='%s' conf=%.3f box=[%d,%d,%d,%d] size=%dx%d pass_conf=%s pass_size=%s",
                track_id, frame_id, raw_text, cleaned, conf, x1, y1, x2, y2, pw, ph, passed_min_conf, passed_size,
            )

            if not passed_min_conf or not cleaned or not passed_size:
                continue

            parsed_boxes.append({
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "cx": (x1 + x2) / 2.0, "cy": (y1 + y2) / 2.0,
                "w": pw, "h": ph,
                "raw_text": raw_text,
                "cleaned": cleaned,
                "conf": conf,
            })

        candidates: list[PlateCandidate] = []
        paired_indices = set()

        # 1. Check for 2-tier (square/stacked) plate pairs (Top line -> Bottom line)
        for i in range(len(parsed_boxes)):
            for j in range(len(parsed_boxes)):
                if i == j:
                    continue
                box_A = parsed_boxes[i]
                box_B = parsed_boxes[j]

                # Box A must be vertically above Box B
                if box_A["cy"] >= box_B["cy"]:
                    continue

                # Vertical distance check: B should be directly below A
                vert_gap = box_B["y1"] - box_A["y2"]
                max_h = max(box_A["h"], box_B["h"])
                if vert_gap > max_h * 1.5 or vert_gap < -max_h * 0.5:
                    continue

                # Horizontal alignment check: center X close, or horizontal overlap
                overlap_x = max(0, min(box_A["x2"], box_B["x2"]) - max(box_A["x1"], box_B["x1"]))
                cx_diff = abs(box_A["cx"] - box_B["cx"])
                max_w = max(box_A["w"], box_B["w"])
                if cx_diff > max_w * 0.8 and overlap_x == 0:
                    continue

                # Combine text: Top line + '-' + Bottom line (e.g. 29A-123.45 or 30G-567.89)
                merged_text = clean_plate_text(f"{box_A['cleaned']}-{box_B['cleaned']}")
                if not is_valid_plate_format(merged_text):
                    continue

                # Combined bounding box covering both lines with padding
                pad = 6
                bx1 = max(0, min(box_A["x1"], box_B["x1"]) - pad)
                by1 = max(0, box_A["y1"] - pad + roi_y1)
                bx2 = min(vw, max(box_A["x2"], box_B["x2"]) + pad)
                by2 = min(vh, box_B["y2"] + pad + roi_y1)

                pw = bx2 - bx1
                ph = by2 - by1
                if pw < 15 or ph < 15:
                    continue

                raw_crop = vehicle_crop[by1:by2, bx1:bx2]
                if raw_crop.size == 0:
                    continue

                preprocessed = self.preprocess_plate_crop(raw_crop)
                gray = cv2.cvtColor(raw_crop, cv2.COLOR_BGR2GRAY) if len(raw_crop.shape) == 3 else raw_crop
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

                comb_conf = (box_A["conf"] + box_B["conf"]) / 2.0
                quality = comb_conf * 50.0 + min(sharpness, 200.0) * 0.3 + min(pw, 150.0) * 0.2 + 25.0  # complete 2-tier bonus

                cand_bbox_native = (
                    int(round(vx1 + bx1)),
                    int(round(vy1 + by1)),
                    int(round(vx1 + bx2)),
                    int(round(vy1 + by2)),
                )

                candidates.append(PlateCandidate(
                    plate_text=merged_text,
                    raw_text=f"{box_A['raw_text']}\n{box_B['raw_text']}",
                    confidence=round(comb_conf, 3),
                    bbox_vehicle=(bx1, by1, bx2, by2),
                    bbox_native=cand_bbox_native,
                    raw_crop=raw_crop,
                    preprocessed_crop=preprocessed,
                    sharpness=round(sharpness, 1),
                    quality_score=round(quality, 2),
                ))
                paired_indices.add(i)
                paired_indices.add(j)

        # 2. Check for 1-line plate split into two boxes side-by-side
        for i in range(len(parsed_boxes)):
            if i in paired_indices:
                continue
            for j in range(len(parsed_boxes)):
                if i == j or j in paired_indices:
                    continue
                box_A = parsed_boxes[i]
                box_B = parsed_boxes[j]
                if box_A["cx"] >= box_B["cx"]:
                    continue

                if abs(box_A["cy"] - box_B["cy"]) > min(box_A["h"], box_B["h"]) * 0.6:
                    continue
                if (box_B["x1"] - box_A["x2"]) > max(box_A["h"], box_B["h"]) * 1.5:
                    continue

                merged_text = clean_plate_text(f"{box_A['cleaned']}-{box_B['cleaned']}")
                if not is_valid_plate_format(merged_text):
                    continue

                pad = 4
                bx1 = max(0, box_A["x1"] - pad)
                by1 = max(0, min(box_A["y1"], box_B["y1"]) - pad + roi_y1)
                bx2 = min(vw, box_B["x2"] + pad)
                by2 = min(vh, max(box_A["y2"], box_B["y2"]) + pad + roi_y1)

                raw_crop = vehicle_crop[by1:by2, bx1:bx2]
                if raw_crop.size == 0:
                    continue

                preprocessed = self.preprocess_plate_crop(raw_crop)
                gray = cv2.cvtColor(raw_crop, cv2.COLOR_BGR2GRAY) if len(raw_crop.shape) == 3 else raw_crop
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                comb_conf = (box_A["conf"] + box_B["conf"]) / 2.0
                quality = comb_conf * 50.0 + min(sharpness, 200.0) * 0.3 + min(bx2 - bx1, 150.0) * 0.2 + 20.0

                candidates.append(PlateCandidate(
                    plate_text=merged_text,
                    raw_text=f"{box_A['raw_text']}\n{box_B['raw_text']}",
                    confidence=round(comb_conf, 3),
                    bbox_vehicle=(bx1, by1, bx2, by2),
                    bbox_native=(int(round(vx1 + bx1)), int(round(vy1 + by1)), int(round(vx1 + bx2)), int(round(vy1 + by2))),
                    raw_crop=raw_crop,
                    preprocessed_crop=preprocessed,
                    sharpness=round(sharpness, 1),
                    quality_score=round(quality, 2),
                ))
                paired_indices.add(i)
                paired_indices.add(j)

        # 3. Single box candidates (standard 1-line plate)
        for i, box in enumerate(parsed_boxes):
            if i in paired_indices:
                continue
            if not is_valid_plate_format(box["cleaned"]):
                continue

            pad = 4
            bx1 = max(0, box["x1"] - pad)
            by1 = max(0, box["y1"] - pad + roi_y1)
            bx2 = min(vw, box["x2"] + pad)
            by2 = min(vh, box["y2"] + pad + roi_y1)

            raw_crop = vehicle_crop[by1:by2, bx1:bx2]
            if raw_crop.size == 0:
                continue

            preprocessed = self.preprocess_plate_crop(raw_crop)
            gray = cv2.cvtColor(raw_crop, cv2.COLOR_BGR2GRAY) if len(raw_crop.shape) == 3 else raw_crop
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

            has_alpha = any(c.isalpha() for c in box["cleaned"])
            has_digit = any(c.isdigit() for c in box["cleaned"])
            bonus = 15.0 if (has_alpha and has_digit and len(box["cleaned"].replace("-", "").replace(".", "")) >= 6) else 0.0

            quality = box["conf"] * 50.0 + min(sharpness, 200.0) * 0.3 + min(bx2 - bx1, 150.0) * 0.2 + bonus

            candidates.append(PlateCandidate(
                plate_text=box["cleaned"],
                raw_text=box["raw_text"],
                confidence=round(box["conf"], 3),
                bbox_vehicle=(bx1, by1, bx2, by2),
                bbox_native=(int(round(vx1 + bx1)), int(round(vy1 + by1)), int(round(vx1 + bx2)), int(round(vy1 + by2))),
                raw_crop=raw_crop,
                preprocessed_crop=preprocessed,
                sharpness=round(sharpness, 1),
                quality_score=round(quality, 2),
            ))

        logger.info(
            "[PLATE_DET] track_id=%d frame_id=%d assembled_candidates_count=%d",
            track_id, frame_id, len(candidates),
        )
        for c in candidates:
            logger.info(
                "[PLATE_DET] track_id=%d frame_id=%d candidate: text='%s' conf=%.3f bbox_veh=%s plate_size=%dx%d quality=%.2f",
                track_id, frame_id, c.plate_text, c.confidence, c.bbox_vehicle, c.raw_crop.shape[1], c.raw_crop.shape[0], c.quality_score,
            )

        return candidates

    # ------------------------------------------------------------------
    # Stage 0 helpers
    # ------------------------------------------------------------------

    def _detect_plate_bbox(
        self,
        vehicle_crop: np.ndarray,
        track_id: int = -1,
        frame_id: int = -1,
    ) -> "tuple[int, int, int, int, float] | None":
        """Run the dedicated YOLO plate detector on the vehicle crop.

        Returns (x1, y1, x2, y2, confidence) in vehicle-crop coordinates,
        or None if the detector is unavailable / finds nothing.
        """
        detector = self._plate_detector
        if detector is None or not detector.is_available:
            return None

        boxes = detector.detect(vehicle_crop)
        if not boxes:
            logger.info(
                "[PLATE_DET] track_id=%d frame_id=%d yolo_plate_boxes=0 confidence=0.000 bbox=[0,0,0,0] native_plate_WxH=0x0",
                track_id, frame_id,
            )
            return None

        best = boxes[0]  # sorted by conf desc
        pw = max(0, best.x2 - best.x1)
        ph = max(0, best.y2 - best.y1)
        logger.info(
            "[PLATE_DET] track_id=%d frame_id=%d yolo_plate_boxes=%d confidence=%.3f bbox=[%d,%d,%d,%d] native_plate_WxH=%dx%d",
            track_id, frame_id, len(boxes),
            best.confidence, best.x1, best.y1, best.x2, best.y2,
            pw, ph,
        )
        return (best.x1, best.y1, best.x2, best.y2, float(best.confidence))

    @staticmethod
    def _adaptive_upscale_plate(crop: np.ndarray) -> tuple[np.ndarray, float]:
        """Bounded adaptive upscale for tight plate crops (aspect-ratio preserved, INTER_CUBIC).

        Scale table (keyed on native height):
            h < 20   -> 4x
            20 <= h < 35  -> 3x
            35 <= h < 60  -> 2x
            60 <= h < 80  -> 1.5x
            h >= 80       -> 1x (no upscale)

        Returns:
            (upscaled_crop, scale_factor)
        """
        h, w = crop.shape[:2]
        if h < 20:
            scale = 4.0
        elif h < 35:
            scale = 3.0
        elif h < 60:
            scale = 2.0
        elif h < 80:
            scale = 1.5
        else:
            return crop, 1.0

        new_w = max(32, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        upscaled = cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
        return upscaled, scale

    # ------------------------------------------------------------------
    # Main extraction entry point
    # ------------------------------------------------------------------

    def extract_license_plate(
        self,
        vehicle_crop: np.ndarray,
        native_vehicle_bbox: Sequence[int],
        track_id: int = -1,
        frame_id: int = -1,
    ) -> PlateCandidate | None:
        """Localize and recognize license plate within vehicle crop.

        Pipeline:
          Stage 0  – Dedicated YOLO plate detector → tight plate crop.
          Stage 1  – Size gate check (<15px wide or <8px high skips OCR).
          Stage 2  – Bounded adaptive upscale (INTER_CUBIC).
          Stage 3  – Cascade OCR variants (ORIGINAL -> ENHANCED -> BINARY).
          Stage 4  – Multi-factor quality scoring & candidate emission.

        Args:
            vehicle_crop: BGR crop of the vehicle from native frame.
            native_vehicle_bbox: [vx1, vy1, vx2, vy2] on the native frame.
            track_id: Tracking ID of the vehicle.
            frame_id: Current sequence frame ID.

        Returns:
            PlateCandidate if a plausible plate is recognized, else None.
        """
        self._ocr_context.observations = []
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        vh, vw = vehicle_crop.shape[:2]
        if vh < 15 or vw < 15:
            return None

        # Lazy initialize EasyOCR reader
        if not self._reader_initialized:
            self.initialize()

        best_cand: PlateCandidate | None = None
        vx1, vy1, vx2, vy2 = native_vehicle_bbox[:4]
        best_meta: dict[str, Any] = {}
        variant_selected = "ORIGINAL/RESIZED"

        # ----------------------------------------------------------------
        # Stage 0: Dedicated YOLO plate detector
        # ----------------------------------------------------------------
        plate_det_res = self._detect_plate_bbox(vehicle_crop, track_id, frame_id)

        if plate_det_res is not None:
            px1, py1, px2, py2, det_conf = plate_det_res
            # Small padding to avoid cutting off plate edges
            pad = 4
            px1 = max(0, px1 - pad)
            py1 = max(0, py1 - pad)
            px2 = min(vw, px2 + pad)
            py2 = min(vh, py2 + pad)

            # Stage 0.5: Corner estimation & perspective rectification for angled plates
            rectified_crop, rect_angle = self.rectify_plate_perspective(vehicle_crop, (px1, py1, px2, py2))
            if abs(rect_angle) >= 1.5 and rectified_crop is not None and rectified_crop.size > 0:
                raw_tight_crop = rectified_crop
                logger.info(
                    "[PLATE_PERSPECTIVE] track_id=%d frame_id=%d perspective rectification applied: angle=%.1f deg size=%dx%d",
                    track_id, frame_id, rect_angle, raw_tight_crop.shape[1], raw_tight_crop.shape[0]
                )
            else:
                raw_tight_crop = vehicle_crop[py1:py2, px1:px2]

            if raw_tight_crop.size == 0:
                plate_det_res = None
            else:
                native_h, native_w = raw_tight_crop.shape[:2]

                # Size gate: If plate is too small (w < 15px or h < 8px), do not OCR; keep SEARCHING
                if native_w < 15 or native_h < 8:
                    logger.info(
                        "[PLATE_DET] track_id=%d frame_id=%d plate too small (native_plate_WxH=%dx%d < 15x8), skipping OCR, keep SEARCHING",
                        track_id, frame_id, native_w, native_h,
                    )
                    return None

                # Bounded adaptive upscale
                plate_upscaled, scale_factor = self._adaptive_upscale_plate(raw_tight_crop)
                out_h, out_w = plate_upscaled.shape[:2]

                logger.info(
                    "[PLATE_CROP] track_id=%d frame_id=%d native_size=%dx%d scale_factor=%.1fx output_size=%dx%d",
                    track_id, frame_id, native_w, native_h, scale_factor, out_w, out_h,
                )

                # Preprocessing variants on upscaled crop: ORIGINAL, ENHANCED, BINARY
                variants, meta = self.generate_preprocessing_variants(plate_upscaled)
                best_meta = meta

                enhanced_crop = variants.get("ENHANCED_GRAY", plate_upscaled)
                binary_crop = variants.get("BINARIZED", plate_upscaled)

                # Save debug crops: vehicle_crop, tight_plate_crop, plate_upscaled, enhanced, binary
                if self._debug_sample_count < self._max_debug_samples:
                    try:
                        self._debug_dir.mkdir(parents=True, exist_ok=True)
                        prefix = f"f{frame_id}_v{track_id}"
                        cv2.imwrite(str(self._debug_dir / "vehicle_crop.jpg"), vehicle_crop)
                        cv2.imwrite(str(self._debug_dir / f"{prefix}_vehicle_crop.jpg"), vehicle_crop)
                        cv2.imwrite(str(self._debug_dir / "tight_plate_crop.jpg"), raw_tight_crop)
                        cv2.imwrite(str(self._debug_dir / f"{prefix}_tight_plate_crop.jpg"), raw_tight_crop)
                        cv2.imwrite(str(self._debug_dir / "plate_upscaled.jpg"), plate_upscaled)
                        cv2.imwrite(str(self._debug_dir / f"{prefix}_plate_upscaled.jpg"), plate_upscaled)
                        cv2.imwrite(str(self._debug_dir / "enhanced.jpg"), enhanced_crop)
                        cv2.imwrite(str(self._debug_dir / f"{prefix}_enhanced.jpg"), enhanced_crop)
                        cv2.imwrite(str(self._debug_dir / "binary.jpg"), binary_crop)
                        cv2.imwrite(str(self._debug_dir / f"{prefix}_binary.jpg"), binary_crop)
                        self._debug_sample_count += 1
                        logger.info("[PLATE_DEBUG] Saved all 5 debug crops for track_id=%d frame_id=%d to %s", track_id, frame_id, self._debug_dir)
                    except Exception as e:
                        logger.warning("[PLATE_DEBUG] Failed saving debug crops: %s", e)

                # Cascade OCR: ORIGINAL -> fail mới ENHANCED -> fail mới BINARY
                v_name, v_text, v_conf, v_img = self.evaluate_variants(
                    variants=variants,
                    baseline_text="",
                    baseline_conf=0.0,
                    track_id=track_id,
                    frame_id=frame_id,
                )
                variant_selected = v_name

                if v_text and is_valid_plate_format(v_text) and v_conf >= self.min_confidence:
                    gray_crop = cv2.cvtColor(raw_tight_crop, cv2.COLOR_BGR2GRAY) if len(raw_tight_crop.shape) == 3 else raw_tight_crop
                    sharpness = float(cv2.Laplacian(gray_crop, cv2.CV_64F).var())
                    brightness = float(np.mean(gray_crop))
                    deskew_angle = meta.get("deskew", 0.0)

                    # Multi-factor quality score: detector conf, size, sharpness, brightness, perspective
                    q_conf = min(max(v_conf, 0.0), 1.0) * 35.0 + min(max(det_conf, 0.0), 1.0) * 15.0
                    q_size = min(native_w / 120.0, 1.0) * 25.0
                    q_sharp = min(sharpness / 150.0, 1.0) * 20.0
                    q_bright = 10.0 if (65.0 <= brightness <= 190.0) else max(0.0, 10.0 - abs(brightness - 128.0) * 0.1)
                    q_skew = max(-5.0, -abs(deskew_angle) * 0.3)
                    quality = round(max(0.0, q_conf + q_size + q_sharp + q_bright + q_skew + 5.0), 2)

                    best_cand = PlateCandidate(
                        plate_text=v_text,
                        raw_text=getattr(self._ocr_context, "selected_raw", v_text),
                        confidence=round(v_conf, 3),
                        bbox_vehicle=(px1, py1, px2, py2),
                        bbox_native=(
                            int(round(vx1 + px1)),
                            int(round(vy1 + py1)),
                            int(round(vx1 + px2)),
                            int(round(vy1 + py2)),
                        ),
                        raw_crop=raw_tight_crop,
                        preprocessed_crop=v_img,
                        sharpness=round(sharpness, 1),
                        quality_score=quality,
                    )
                    logger.info(
                        "[PLATE_DET] track_id=%d frame_id=%d YOLO+OCR SUCCESS: plate='%s' conf=%.3f scale=%.1fx quality=%.2f variant=%s",
                        track_id, frame_id, best_cand.plate_text, best_cand.confidence, scale_factor, best_cand.quality_score, variant_selected,
                    )

        # ----------------------------------------------------------------
        # Stage 1 (fallback): ROI heuristic + EasyOCR on vehicle crop
        # when YOLO detector is unavailable or found nothing useful
        # ----------------------------------------------------------------
        if best_cand is None and self._reader is not None:
            # Focus plate search: if already a tight plate crop or small vehicle crop, search full crop
            if vh < 180 or (vw / float(max(1, vh))) >= 2.0:
                roi_y1 = 0
                search_roi = vehicle_crop
            else:
                roi_y1 = int(vh * 0.25)
                search_roi = vehicle_crop[roi_y1:, :]
                if search_roi.size == 0:
                    search_roi = vehicle_crop
                    roi_y1 = 0

            logger.info(
                "[PLATE_DET] track_id=%d frame_id=%d fallback search_roi_size=%dx%d (vehicle_crop=%dx%d, roi_y1=%d)",
                track_id, frame_id, search_roi.shape[1], search_roi.shape[0], vw, vh, roi_y1,
            )
            with self._infer_lock:
                try:
                    ocr_results = self._reader.readtext(search_roi)
                except Exception as exc:
                    logger.debug("[OCR] Inference error on vehicle ROI: %s", exc)
                    ocr_results = []

            candidates = self._parse_plate_candidates(
                ocr_results=ocr_results,
                vehicle_crop=vehicle_crop,
                roi_y1=roi_y1,
                vx1=vx1,
                vy1=vy1,
                vw=vw,
                vh=vh,
                track_id=track_id,
                frame_id=frame_id,
            )

            for cand in candidates:
                if best_cand is None or cand.quality_score > best_cand.quality_score:
                    best_cand = cand

            # Stage 2: Multi-variant evaluation and refinement
            if best_cand is not None:
                logger.info(
                    "[PLATE_DET] track_id=%d frame_id=%d selected candidate for variant eval: text='%s' conf=%.3f size=%dx%d",
                    track_id, frame_id, best_cand.plate_text, best_cand.confidence, best_cand.raw_crop.shape[1], best_cand.raw_crop.shape[0],
                )
                variants, meta = self.generate_preprocessing_variants(best_cand.raw_crop)
                best_meta = meta
                v_name, v_text, v_conf, v_img = self.evaluate_variants(
                    variants=variants,
                    baseline_text=best_cand.plate_text,
                    baseline_conf=best_cand.confidence,
                    track_id=track_id,
                    frame_id=frame_id,
                )
                variant_selected = v_name
                if v_text:
                    best_cand.plate_text = v_text
                    best_cand.raw_text = getattr(self._ocr_context, "selected_raw", v_text)
                    best_cand.normalized_text = normalize_plate_text(v_text)
                    best_cand.confidence = round(v_conf, 3)
                    best_cand.preprocessed_crop = v_img
            else:
                # Direct crop fallback (for isolated plate crops or challenging tilt/lighting)
                logger.info(
                    "[PLATE_DET] track_id=%d frame_id=%d no ROI candidate -> running direct crop fallback on vehicle crop (%dx%d)",
                    track_id, frame_id, vw, vh,
                )
                variants, meta = self.generate_preprocessing_variants(vehicle_crop)
                best_meta = meta
                v_name, v_text, v_conf, v_img = self.evaluate_variants(
                    variants, track_id=track_id, frame_id=frame_id,
                )
                valid = is_valid_plate_format(v_text)
                logger.info(
                    "[PLATE_OCR] track_id=%d frame_id=%d direct_fallback result: text='%s' conf=%.3f valid=%s pass_conf=%s",
                    track_id, frame_id, v_text, v_conf, valid, (v_conf >= self.min_confidence),
                )
                if valid and v_conf >= self.min_confidence:
                    gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY) if len(vehicle_crop.shape) == 3 else vehicle_crop
                    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                    quality = v_conf * 50.0 + min(sharpness, 200.0) * 0.3 + 20.0
                    variant_selected = v_name
                    best_cand = PlateCandidate(
                        plate_text=v_text,
                        raw_text=getattr(self._ocr_context, "selected_raw", v_text),
                        confidence=round(v_conf, 3),
                        bbox_vehicle=(0, 0, vw, vh),
                        bbox_native=(int(round(vx1)), int(round(vy1)), int(round(vx2)), int(round(vy2))),
                        raw_crop=vehicle_crop,
                        preprocessed_crop=v_img,
                        sharpness=round(sharpness, 1),
                        quality_score=round(quality, 2),
                    )

            if best_cand is not None:
                logger.info(
                    "[PLATE_DET] track_id=%d frame_id=%d RESULT: FOUND plate='%s' conf=%.3f plate_bbox=%s quality=%.2f",
                    track_id, frame_id, best_cand.plate_text, best_cand.confidence, best_cand.bbox_vehicle, best_cand.quality_score,
                )
            else:
                logger.info(
                    "[PLATE_DET] track_id=%d frame_id=%d RESULT: NO_PLATE_DETECTED",
                    track_id, frame_id,
                )

        # 3. Emit structured diagnostic log and save bounded debug artifacts
        if best_cand is not None:
            raw_h, raw_w = best_cand.raw_crop.shape[:2]
            pw = best_meta.get("plate_size", (raw_w, raw_h))[0]
            ph = best_meta.get("plate_size", (raw_w, raw_h))[1]
            deskew = best_meta.get("deskew", 0.0)
            brightness = best_meta.get("brightness", 0.0)
            contrast = best_meta.get("contrast", 0.0)
            scale = best_meta.get("scale", 1.0)

            logger.info(
                "[PLATE_PREPROCESS] track_id=%s plate_size=%dx%d deskew=%.1f brightness=%.1f contrast=%.1f scale=%.2f variant_selected=%s ocr_conf=%.3f plate_text=%s",
                track_id, pw, ph, deskew, brightness, contrast, scale, variant_selected, best_cand.confidence, best_cand.plate_text
            )

            if track_id >= 0:
                self._save_debug_sample(
                    vehicle_crop=vehicle_crop,
                    plate_crop=best_cand.raw_crop,
                    preprocessed_crop=best_cand.preprocessed_crop,
                    track_id=track_id,
                    frame_id=frame_id,
                    plate_text=best_cand.plate_text,
                    conf=best_cand.confidence,
                    rectified_crop=best_meta.get("rectified"),
                    binary_crop=best_meta.get("binary"),
                )

        return best_cand


# Global singleton instance
plate_reader = LicensePlateReader()
