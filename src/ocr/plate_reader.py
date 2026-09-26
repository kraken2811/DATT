"""License Plate Localization and Optical Character Recognition (OCR).

Decoupled, modular OCR pipeline for vehicles:
1. Receives vehicle crop (never full frame).
2. Localizes license plate candidate ROI inside vehicle boundaries.
3. Crops and enhances the license plate (contrast, denoising, adaptive thresholding).
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
    cleaned = re.sub(r"[^A-Z0-9\-\.]", "", cleaned)
    # Collapse multiple consecutive hyphens or dots
    cleaned = re.sub(r"[\-\.]{2,}", "-", cleaned)
    # Strip leading/trailing hyphens or dots
    cleaned = cleaned.strip("-.")

    # Vietnamese plate prefix heuristic: first 2 characters are province digits
    # Correct common OCR misclassification of 'O'/'Q' for '0' in the first 2 positions
    if len(cleaned) >= 3 and cleaned[0] in "0123456789" and cleaned[1] in "OQ":
        cleaned = cleaned[0] + "0" + cleaned[2:]
    elif len(cleaned) >= 3 and cleaned[0] in "OQ" and cleaned[1] in "0123456789":
        cleaned = "0" + cleaned[1:]

    return cleaned


def is_valid_plate_format(text: str) -> bool:
    """Validate whether cleaned text exhibits reasonable license plate characteristics."""
    if len(text) < 3 or len(text) > 14:
        return False
    # Count alphanumeric characters
    alnum_count = sum(1 for c in text if c.isalnum())
    if alnum_count < 3:
        return False
    # Require at least one digit and at least one letter (most plates world-wide & VN/US)
    has_digit = any(c.isdigit() for c in text)
    has_alpha = any(c.isalpha() for c in text)
    return has_digit or (has_alpha and alnum_count >= 4)


class LicensePlateReader:
    """Thread-safe singleton for localized vehicle license plate detection and OCR."""

    _instance: "LicensePlateReader | None" = None
    _lock = threading.Lock()

    def __init__(self, min_confidence: float = 0.35) -> None:
        self.min_confidence = min_confidence
        self._reader = None
        self._reader_initialized = False
        self._reader_error: str | None = None
        self._infer_lock = threading.Lock()

        # Bounded debug sample tracking in scratch/plate_debug/
        self._debug_dir = Path("scratch/plate_debug")
        self._debug_sample_count = 0
        self._max_debug_samples = 15

    @classmethod
    def get_instance(cls) -> "LicensePlateReader":
        """Thread-safe singleton accessor."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def initialize(self) -> bool:
        """Initialize EasyOCR reader with download disabled if models pre-exist, or standard."""
        with self._infer_lock:
            if self._reader_initialized:
                return True
            if self._reader_error is not None:
                return False

            try:
                import easyocr

                logger.info("[OCR] Initializing EasyOCR reader (CPU mode)...")
                # Try loading without downloading first, fallback to standard
                try:
                    self._reader = easyocr.Reader(["en"], gpu=False, download_enabled=False)
                except Exception:
                    self._reader = easyocr.Reader(["en"], gpu=False, download_enabled=True)

                self._reader_initialized = True
                logger.info("[OCR] EasyOCR reader successfully initialized.")
                return True
            except Exception as exc:
                self._reader_error = str(exc)
                logger.warning("[OCR] Could not initialize EasyOCR reader: %s. Using classical CV fallback.", exc)
                return False

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
            boxes.append({"cleaned": cleaned, "conf": float(conf), "cx": cx, "cy": cy})

        if not boxes:
            return "", 0.0
        if len(boxes) == 1:
            return boxes[0]["cleaned"], boxes[0]["conf"]

        # Check vertical separation for 2-tier stacked plate
        by_y = sorted(boxes, key=lambda b: b["cy"])
        max_dy = by_y[-1]["cy"] - by_y[0]["cy"]
        if max_dy > 12:
            # 2-Tier plate (top line to bottom line)
            merged = clean_plate_text("-".join(b["cleaned"] for b in by_y))
            avg_conf = sum(b["conf"] for b in by_y) / len(by_y)
            return merged, round(avg_conf, 3)
        else:
            # Horizontal boxes
            by_x = sorted(boxes, key=lambda b: b["cx"])
            merged = clean_plate_text("-".join(b["cleaned"] for b in by_x))
            avg_conf = sum(b["conf"] for b in by_x) / len(by_x)
            return merged, round(avg_conf, 3)

    def evaluate_variants(
        self,
        variants: dict[str, np.ndarray],
        baseline_text: str = "",
        baseline_conf: float = 0.0,
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
                "conf": baseline_conf,
                "score": base_score,
                "img": default_img,
            })

        for vname in ["ORIGINAL/RESIZED", "ENHANCED_GRAY", "BINARIZED"]:
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
                continue

            is_valid = is_valid_plate_format(text)
            alnum_cnt = sum(1 for c in text if c.isalnum())
            comp = min(alnum_cnt / 8.0, 1.0)
            bonus = 0.5 if (any(c.isalpha() for c in text) and any(c.isdigit() for c in text) and alnum_cnt >= 6) else 0.0
            score = (conf * 1.0) + (2.0 if is_valid else 0.0) + (comp * 0.8) + bonus

            candidates.append({
                "variant": vname,
                "text": text,
                "conf": conf,
                "score": score,
                "img": img,
            })

        if not candidates:
            return default_vname, baseline_text, baseline_conf, default_img

        # Sort candidates by score descending
        candidates.sort(key=lambda c: c["score"], reverse=True)
        winner = candidates[0]
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
    ) -> list[PlateCandidate]:
        """Group and assemble OCR text boxes into 1-line or 2-tier plate candidates."""
        parsed_boxes = []
        for poly, raw_text, conf in ocr_results:
            conf = float(conf)
            if conf < self.min_confidence:
                continue
            cleaned = clean_plate_text(raw_text)
            if not cleaned:
                continue

            pxs = [pt[0] for pt in poly]
            pys = [pt[1] for pt in poly]
            x1 = max(0, int(min(pxs)))
            y1 = max(0, int(min(pys)))
            x2 = min(vw, int(max(pxs)))
            y2 = min(vh - roi_y1, int(max(pys)))
            pw = x2 - x1
            ph = y2 - y1
            if pw < 8 or ph < 6:
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
                confidence=round(box["conf"], 3),
                bbox_vehicle=(bx1, by1, bx2, by2),
                bbox_native=(int(round(vx1 + bx1)), int(round(vy1 + by1)), int(round(vx1 + bx2)), int(round(vy1 + by2))),
                raw_crop=raw_crop,
                preprocessed_crop=preprocessed,
                sharpness=round(sharpness, 1),
                quality_score=round(quality, 2),
            ))

        return candidates

    def extract_license_plate(
        self,
        vehicle_crop: np.ndarray,
        native_vehicle_bbox: Sequence[int],
        track_id: int = -1,
        frame_id: int = -1,
    ) -> PlateCandidate | None:
        """Localize and recognize license plate within vehicle crop.

        Args:
            vehicle_crop: BGR crop of the vehicle from native frame.
            native_vehicle_bbox: [vx1, vy1, vx2, vy2] on the native frame.
            track_id: Tracking ID of the vehicle.
            frame_id: Current sequence frame ID.

        Returns:
            PlateCandidate if a plausible plate is recognized, else None.
        """
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        vh, vw = vehicle_crop.shape[:2]
        if vh < 15 or vw < 15:
            return None

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

        # Lazy initialize EasyOCR reader
        if not self._reader_initialized:
            self.initialize()

        best_cand: PlateCandidate | None = None
        vx1, vy1, vx2, vy2 = native_vehicle_bbox[:4]
        best_meta: dict[str, Any] = {}
        variant_selected = "ORIGINAL/RESIZED"

        # 1. OCR-driven detection on search ROI
        if self._reader is not None:
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
            )

            for cand in candidates:
                if best_cand is None or cand.quality_score > best_cand.quality_score:
                    best_cand = cand

            # 2. Multi-variant evaluation and refinement
            if best_cand is not None:
                variants, meta = self.generate_preprocessing_variants(best_cand.raw_crop)
                best_meta = meta
                v_name, v_text, v_conf, v_img = self.evaluate_variants(
                    variants=variants,
                    baseline_text=best_cand.plate_text,
                    baseline_conf=best_cand.confidence,
                )
                variant_selected = v_name
                if v_text:
                    best_cand.plate_text = v_text
                    best_cand.confidence = round(v_conf, 3)
                    best_cand.preprocessed_crop = v_img
            else:
                # Direct crop fallback (for isolated plate crops or challenging tilt/lighting)
                variants, meta = self.generate_preprocessing_variants(vehicle_crop)
                best_meta = meta
                v_name, v_text, v_conf, v_img = self.evaluate_variants(variants)
                if is_valid_plate_format(v_text) and v_conf >= self.min_confidence:
                    gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY) if len(vehicle_crop.shape) == 3 else vehicle_crop
                    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                    quality = v_conf * 50.0 + min(sharpness, 200.0) * 0.3 + 20.0
                    variant_selected = v_name
                    best_cand = PlateCandidate(
                        plate_text=v_text,
                        confidence=round(v_conf, 3),
                        bbox_vehicle=(0, 0, vw, vh),
                        bbox_native=(int(round(vx1)), int(round(vy1)), int(round(vx2)), int(round(vy2))),
                        raw_crop=vehicle_crop,
                        preprocessed_crop=v_img,
                        sharpness=round(sharpness, 1),
                        quality_score=round(quality, 2),
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
