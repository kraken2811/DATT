"""Face Embedding & Recognition Module for DATT.

Reuses InsightFace ('buffalo_s' with MobileFaceNet 512-dim embedding)
using CPUExecutionProvider via ONNX Runtime.

Lifecycle:
- Singleton pattern: Model weights are loaded once in RAM on startup / lazy init.
- Never instantiates models per-frame.
- Thread-safe inference.
"""

from dataclasses import asdict, dataclass, field
import io
import logging
import math
import os
from pathlib import Path
import threading
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("datt.face")


@dataclass
class FaceDiagInfo:
    """Diagnostic details for face detection and embedding extraction."""

    model_name: str = "buffalo_s"
    model_path: str = ""
    model_loaded: bool = False
    execution_provider: str = "CPUExecutionProvider"
    det_size: tuple[int, int] = (320, 320)
    faces_detected: int = 0
    confidences: list[float] = field(default_factory=list)
    bounding_boxes: list[list[float]] = field(default_factory=list)
    landmarks_count: int = 0
    rejection_reason: str | None = None
    user_message: str = ""
    embedding_norm: float | None = None
    embedding_dims: int | None = None
    has_nan: bool = False
    has_inf: bool = False
    is_zero: bool = False
    rotation_applied: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decode_face_image_bytes(content: bytes) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Decode raw image bytes to BGR numpy array with EXIF orientation handling.

    Args:
        content: Uploaded image file bytes (JPEG, PNG, WEBP, etc.)

    Returns:
        tuple[np.ndarray | None, dict[str, Any]]:
            Decoded BGR image (or None on failure) and metadata dictionary.
    """
    meta: dict[str, Any] = {
        "success": False,
        "width": 0,
        "height": 0,
        "channels": 0,
        "dtype": "unknown",
        "orientation_tag": None,
        "error": None,
    }

    if not content or len(content) == 0:
        meta["error"] = "IMAGE_DECODE_FAILED: Empty image payload"
        return None, meta

    # Strategy A: Use PIL with ImageOps.exif_transpose for authoritative EXIF orientation handling
    try:
        from PIL import Image, ImageOps

        pil_img = Image.open(io.BytesIO(content))
        exif = pil_img.getexif() if hasattr(pil_img, "getexif") else None
        meta["orientation_tag"] = exif.get(0x0112) if exif else None

        # Transpose/rotate image according to EXIF orientation tag
        try:
            pil_img = ImageOps.exif_transpose(pil_img)
        except Exception as exc:
            logger.debug("[FACE_DECODE] EXIF transpose ignored: %s", exc)

        # Convert to RGB mode if needed (handles RGBA, grayscale, CMYK, etc.)
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")

        rgb_arr = np.array(pil_img)
        bgr_arr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2BGR)

        h, w = bgr_arr.shape[:2]
        c = bgr_arr.shape[2] if len(bgr_arr.shape) > 2 else 1
        meta.update({
            "success": True,
            "width": w,
            "height": h,
            "channels": c,
            "dtype": str(bgr_arr.dtype),
        })

        # Save diagnostic copy for development inspection (Phase A2)
        try:
            debug_dir = Path("scratch")
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = debug_dir / "datt_face_registration_debug.jpg"
            cv2.imwrite(str(debug_path), bgr_arr)
            meta["debug_path"] = str(debug_path)
        except Exception:
            pass

        logger.info(
            "[FACE_DECODE_SUCCESS] w=%d h=%d c=%d dtype=%s exif_orientation=%s",
            w, h, c, meta["dtype"], meta["orientation_tag"],
        )
        return bgr_arr, meta

    except Exception as exc:
        logger.warning("[FACE_DECODE] PIL decode failed (%s), falling back to OpenCV imdecode", exc)

    # Strategy B: Fallback to cv2.imdecode
    try:
        nparr = np.frombuffer(content, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is not None and img.size > 0:
            h, w = img.shape[:2]
            c = img.shape[2] if len(img.shape) > 2 else 1
            meta.update({
                "success": True,
                "width": w,
                "height": h,
                "channels": c,
                "dtype": str(img.dtype),
            })
            return img, meta
    except Exception as exc:
        meta["error"] = f"IMAGE_DECODE_FAILED: {exc}"

    meta["error"] = "IMAGE_DECODE_FAILED: Could not decode image bytes into valid pixel array"
    return None, meta


def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Calculate cosine similarity between two feature vectors with zero-norm guard."""
    if v1 is None or v2 is None:
        return 0.0

    v1 = np.asarray(v1, dtype=np.float32).flatten()
    v2 = np.asarray(v2, dtype=np.float32).flatten()

    if v1.size == 0 or v2.size == 0 or v1.size != v2.size:
        return 0.0

    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)

    if norm1 < 1e-7 or norm2 < 1e-7 or np.isnan(norm1) or np.isnan(norm2):
        return 0.0

    sim = float(np.dot(v1, v2) / (norm1 * norm2))
    if np.isnan(sim):
        return 0.0

    # Clip to valid cosine range [-1.0, 1.0]
    return max(-1.0, min(1.0, sim))


class FaceEmbedder:
    """Singleton face analysis and embedding extraction wrapper."""

    _instance: "FaceEmbedder | None" = None
    _lock = threading.Lock()

    def __init__(
        self,
        model_name: str = "buffalo_s",
        det_size: list[tuple[int, int]] | tuple[int, int] = [(320, 320), (640, 640)],
        prefer_gpu: bool = True,
    ) -> None:
        self.model_name = model_name
        self.det_size = det_size
        self.prefer_gpu = prefer_gpu
        self._app = None
        self._initialized = False
        self._init_error: str | None = None
        self._model_path: str = ""
        self._infer_lock = threading.Lock()
        self.execution_provider: str = "CUDAExecutionProvider" if prefer_gpu else "CPUExecutionProvider"

    @classmethod
    def get_instance(cls) -> "FaceEmbedder":
        """Thread-safe access to singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def initialize(self) -> bool:
        """Load InsightFace models into memory on GPU (CUDA) or fallback to CPU."""
        with self._infer_lock:
            if self._initialized:
                return True
            if self._init_error is not None:
                return False

            try:
                from insightface.app import FaceAnalysis
                import onnxruntime as ort

                model_root = Path.home() / ".insightface" / "models" / self.model_name
                self._model_path = str(model_root)

                logger.info("[FACE] Initializing InsightFace '%s' models from %s...", self.model_name, self._model_path)

                # Determine GPU device ID from config if available
                target_gpu_id = 0
                try:
                    import config
                    dev = getattr(config, "DEVICE", "cuda:0")
                    if "cuda:" in str(dev).lower():
                        target_gpu_id = int(str(dev).split(":")[-1])
                except Exception:
                    target_gpu_id = 0

                # Prioritize CUDA GPU, with graceful fallback to CPU
                available_providers = ort.get_available_providers()
                if self.prefer_gpu and "CUDAExecutionProvider" in available_providers:
                    providers: list[Any] = [
                        ("CUDAExecutionProvider", {"device_id": target_gpu_id}),
                        "CPUExecutionProvider",
                    ]
                    ctx_id = target_gpu_id
                elif self.prefer_gpu and "DmlExecutionProvider" in available_providers:
                    providers = [("DmlExecutionProvider", {"device_id": target_gpu_id}), "CPUExecutionProvider"]
                    ctx_id = target_gpu_id
                elif self.prefer_gpu:
                    # Request CUDA with CPU fallback if onnxruntime-gpu is configured
                    providers = [
                        ("CUDAExecutionProvider", {"device_id": target_gpu_id}),
                        "CPUExecutionProvider",
                    ]
                    ctx_id = target_gpu_id
                else:
                    providers = ["CPUExecutionProvider"]
                    ctx_id = -1

                app = FaceAnalysis(
                    name=self.model_name,
                    providers=providers,
                )
                app.prepare(ctx_id=ctx_id, det_size=self.det_size, det_thresh=0.40)
                self._app = app
                self._det_model = app.models.get("detection")
                self._rec_model = app.models.get("recognition")

                # Detect actual active provider from session
                active_provider = "CPUExecutionProvider"
                if self._det_model and hasattr(self._det_model, "session"):
                    sess_providers = self._det_model.session.get_providers()
                    if sess_providers:
                        active_provider = sess_providers[0]
                self.execution_provider = active_provider

                self._initialized = True
                logger.info(
                    "[FACE] InsightFace '%s' initialized successfully (provider=%s, det_size=%s).",
                    self.model_name, self.execution_provider, self.det_size,
                )
                return True
            except Exception as exc:
                self._init_error = str(exc)
                logger.error("[FACE] Failed to initialize InsightFace: %s", exc, exc_info=True)
                return False

    @staticmethod
    def analyze_illumination(roi: np.ndarray) -> dict[str, Any]:
        """Analyze local illumination statistics on head/face ROI using luminance.

        Returns:
            dict[str, Any] with state ("NORMAL", "DARK", "OVEREXPOSED", "LOW_CONTRAST", "BACKLIT")
            and luminance metrics (median, mean, p05, p95, dynamic_range, ratios).
        """
        if roi is None or roi.size == 0:
            return {
                "state": "NORMAL", "median": 128.0, "mean": 128.0,
                "p05": 60.0, "p95": 200.0, "dynamic_range": 140.0,
                "overexposed_ratio": 0.0, "underexposed_ratio": 0.0, "local_contrast": 0.5,
                "center_median": 128.0,
            }

        ycbcr = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
        Y = ycbcr[:, :, 0]
        median = float(np.median(Y))
        mean = float(np.mean(Y))
        p05 = float(np.percentile(Y, 5))
        p95 = float(np.percentile(Y, 95))
        dynamic_range = p95 - p05
        overexposed_ratio = float(np.mean(Y >= 245))
        underexposed_ratio = float(np.mean(Y <= 15))
        std_y = float(np.std(Y))
        local_contrast = std_y / max(1.0, mean)

        rh, rw = Y.shape[:2]
        center_Y = Y[
            int(rh * 0.15):max(int(rh * 0.15) + 1, int(rh * 0.75)),
            int(rw * 0.20):max(int(rw * 0.20) + 1, int(rw * 0.80)),
        ]
        center_median = float(np.median(center_Y)) if center_Y.size > 0 else median

        if overexposed_ratio > 0.18 or p05 > 190.0 or median > 210.0:
            state = "OVEREXPOSED"
        elif median < 45.0 or p95 < 65.0:
            state = "DARK"
        elif (p95 >= 175.0 and center_median < 80.0) or (p95 - center_median > 90.0 and p95 > 165.0):
            state = "BACKLIT"
        elif dynamic_range < 40.0:
            state = "LOW_CONTRAST"
        else:
            state = "NORMAL"

        return {
            "state": state,
            "median": round(median, 1),
            "mean": round(mean, 1),
            "p05": round(p05, 1),
            "p95": round(p95, 1),
            "dynamic_range": round(dynamic_range, 1),
            "overexposed_ratio": round(overexposed_ratio, 3),
            "underexposed_ratio": round(underexposed_ratio, 3),
            "local_contrast": round(local_contrast, 3),
            "center_median": round(center_median, 1),
        }

    @classmethod
    def check_illumination(cls, roi: np.ndarray) -> tuple[str, str, np.ndarray]:
        """Check illumination of head/face ROI using luminance statistics.

        Returns:
            tuple[str, str, np.ndarray]:
                - illumination: "NORMAL", "DARK", "BACKLIT", "OVEREXPOSED", or "LOW_CONTRAST"
                - enhancement_applied: "NONE", "CLAHE", "CLAHE+GAMMA", etc.
                - enhanced_roi: Enhanced BGR image if needed for detector ROI, else original roi
        """
        if roi is None or roi.size == 0:
            return "NORMAL", "NONE", roi

        info = cls.analyze_illumination(roi)
        illumination = info["state"]

        if illumination == "NORMAL":
            return "NORMAL", "NONE", roi

        # Gentle enhancement on luminance channel for detector ROI
        enhancements = []
        ycbcr = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
        Y = ycbcr[:, :, 0]

        if illumination in ("BACKLIT", "LOW_CONTRAST"):
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4))
            ycbcr[:, :, 0] = clahe.apply(Y)
            enhancements.append("CLAHE")
        elif illumination == "DARK":
            if info["median"] < 50.0:
                inv_gamma = 1.0 / 0.85
                table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")
                ycbcr[:, :, 0] = cv2.LUT(Y, table)
                enhancements.append("GAMMA")
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4))
            ycbcr[:, :, 0] = clahe.apply(ycbcr[:, :, 0])
            enhancements.append("CLAHE")

        enhanced_roi = cv2.cvtColor(ycbcr, cv2.COLOR_YCrCb2BGR)
        enhancement_applied = "+".join(enhancements) if enhancements else "NONE"
        return illumination, enhancement_applied, enhanced_roi

    @staticmethod
    def validate_landmarks(kps: np.ndarray, face_bbox: list | tuple) -> tuple[bool, str]:
        """Validate 5-point facial landmark geometry before embedding.

        Checks:
        1. Left/right eye ordering
        2. Eye-line roll angle (within ~38 degrees of horizontal)
        3. Eye distance relative to face size
        4. Nose location relative to eyes
        5. Mouth location below nose and mouth ordering
        6. Landmarks within bounding box margins
        7. Reasonable facial triangle proportion

        Returns:
            tuple[bool, str]: (is_valid, reason)
        """
        if kps is None or len(kps) < 5 or not np.isfinite(kps).all():
            return False, "INVALID_LANDMARKS"

        lx, ly = float(kps[0][0]), float(kps[0][1])
        rx, ry = float(kps[1][0]), float(kps[1][1])
        nx, ny = float(kps[2][0]), float(kps[2][1])
        lmx, lmy = float(kps[3][0]), float(kps[3][1])
        rmx, rmy = float(kps[4][0]), float(kps[4][1])

        # 1. Left/Right Eye Ordering
        if rx <= lx + 2.0:
            return False, "EYE_ORDERING_INVERTED"

        # 2. Eye-line roll angle
        eye_dx = rx - lx
        eye_dy = ry - ly
        angle_rad = abs(math.atan2(eye_dy, eye_dx))
        if angle_rad > 0.66:
            return False, "EXCESSIVE_ROLL_ANGLE"

        # 3. Eye distance
        eye_dist = math.hypot(eye_dx, eye_dy)
        if eye_dist < 3.0:
            return False, "EYE_DISTANCE_TOO_SMALL"

        fb_w = max(1.0, float(face_bbox[2] - face_bbox[0]))
        eye_ratio = eye_dist / fb_w
        if eye_ratio < 0.10 or eye_ratio > 0.85:
            return False, "ABNORMAL_EYE_RATIO"

        # 4. Nose location relative to eyes
        if nx < (lx - 0.25 * eye_dist) or nx > (rx + 0.25 * eye_dist):
            return False, "NOSE_OUTSIDE_EYES"
        if ny <= min(ly, ry) + 1.0:
            return False, "NOSE_ABOVE_EYES"

        # 5. Mouth below nose & mouth ordering
        mouth_y = (lmy + rmy) / 2.0
        if mouth_y <= ny + 1.5:
            return False, "MOUTH_ABOVE_NOSE"
        if rmx <= lmx + 1.0:
            return False, "MOUTH_ORDERING_INVERTED"

        # 6. Landmarks inside/near bbox (margin 18%)
        margin_x = fb_w * 0.18
        fb_h = max(1.0, float(face_bbox[3] - face_bbox[1]))
        margin_y = fb_h * 0.18
        for pt in kps:
            px, py = float(pt[0]), float(pt[1])
            if px < (face_bbox[0] - margin_x) or px > (face_bbox[2] + margin_x):
                return False, "LANDMARKS_OUTSIDE_BBOX"
            if py < (face_bbox[1] - margin_y) or py > (face_bbox[3] + margin_y):
                return False, "LANDMARKS_OUTSIDE_BBOX"

        # 7. Vertical facial triangle proportion
        eye_mid_y = (ly + ry) / 2.0
        nose_dist = ny - eye_mid_y
        mouth_dist = mouth_y - eye_mid_y
        if mouth_dist > 2.0:
            v_ratio = nose_dist / mouth_dist
            if v_ratio < 0.20 or v_ratio > 0.88:
                return False, "ABNORMAL_TRIANGLE_RATIO"

        return True, "VALID"

    def detect_faces_in_roi(
        self,
        roi: np.ndarray,
        illumination: str = "NORMAL",
        enhanced_roi: np.ndarray | None = None,
        return_diag: bool = False,
        single_pass: bool = False,
    ) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], dict[str, Any]]:
        """Detect faces within upper-body/head ROI using SCRFD.

        Two-pass detection architecture:
        - Pass 1: Original ROI (1.0x) with det_thresh=0.35.
        - Pass 2: Fallback small-face adaptive upscale (2x-4x) with det_thresh=0.30/0.26.
          Illumination enhancement and geometric upscale are independent.
          NORMAL lighting never prevents the upscaled pass.

        Returns:
            list[dict[str, Any]] or tuple[list[dict[str, Any]], dict[str, Any]]:
                List of dicts with 'bbox' [x1, y1, x2, y2], 'score', 'kps' in unscaled ROI coords.
        """
        empty_diag = {
            "upper_roi_size": (0, 0),
            "upscale_factor": 1.0,
            "detector_input_size": (0, 0),
            "illumination_state": illumination,
            "original_face_count": 0,
            "enhanced_face_count": 0,
            "best_face_confidence": 0.0,
            "best_face_bbox": None,
            "eval_roi": None,
        }
        if roi is None or roi.size == 0:
            return ([], empty_diag) if return_diag else []

        if not self._initialized:
            if not self.initialize():
                return ([], empty_diag) if return_diag else []

        det_model = getattr(self, "_det_model", None)
        if det_model is None and self._app is not None:
            det_model = self._app.models.get("detection")
        if det_model is None:
            return ([], empty_diag) if return_diag else []

        rh, rw = roi.shape[:2]
        if single_pass:
            # Production adaptive path: one SCRFD invocation, existing native threshold.
            with self._infer_lock:
                boxes, landmarks = det_model.detect(roi, max_num=0, det_thresh=0.35)
            results = []
            for i, box in enumerate(boxes if boxes is not None else []):
                results.append(dict(bbox=box[:4].copy(), score=float(box[4]),
                                    kps=landmarks[i].copy() if landmarks is not None else None))
            results.sort(key=lambda f: (f['bbox'][2]-f['bbox'][0])*(f['bbox'][3]-f['bbox'][1]), reverse=True)
            diag = {**empty_diag, 'upper_roi_size': (rw, rh), 'detector_input_size': (rw, rh),
                    'original_face_count': len(results), 'eval_roi': roi,
                    'best_face_confidence': results[0]['score'] if results else 0.0,
                    'best_face_bbox': results[0]['bbox'] if results else None}
            self.last_detection_diag = diag
            return (results, diag) if return_diag else results
        min_dim = min(rh, rw)

        # Adaptive 2x-4x enlargement for small ROIs (Point 3)
        if min_dim <= 80:
            scale_factor = 4.0
        elif min_dim <= 125:  # e.g. 109x175 -> 3.0x -> 327x525
            scale_factor = 3.0
        elif min_dim <= 220:  # e.g. 159x193 -> 2.0x -> 318x386
            scale_factor = 2.0
        elif min_dim <= 320:
            scale_factor = 1.5
        else:
            scale_factor = 1.0

        # Always record original ROI detection count at 1.0x with det_thresh=0.35 (Point 1)
        with self._infer_lock:
            bboxes_orig, kpss_orig = det_model.detect(roi, max_num=0, det_thresh=0.35)

        orig_count = len(bboxes_orig) if bboxes_orig is not None else 0
        enh_count = 0

        # Point 3 & 6: Adaptive upscale executes for small ROIs (around 109x175 or 159x193)
        # Illumination enhancement and geometric upscale are independent.
        # NORMAL lighting never prevents upscale.
        if illumination in ("DARK", "BACKLIT") and enhanced_roi is not None:
            source_img = enhanced_roi
        else:
            source_img = roi

        if scale_factor > 1.0:
            eval_roi = cv2.resize(source_img, (0, 0), fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
            logger.info(
                "[FACE_UPSCALE] roi_original=%dx%d upscale=%.1f detector_input=%dx%d",
                rw, rh, scale_factor, eval_roi.shape[1], eval_roi.shape[0]
            )

            with self._infer_lock:
                # Sensitive detection on upscaled ROI (0.30 threshold for small CCTV faces)
                bboxes_fallback, kpss_fallback = det_model.detect(eval_roi, max_num=0, det_thresh=0.30)
                # If still 0 faces and upscaled, sensitive retry at 0.26
                if (bboxes_fallback is None or len(bboxes_fallback) == 0):
                    bboxes_fallback, kpss_fallback = det_model.detect(eval_roi, max_num=0, det_thresh=0.26)

            enh_count = len(bboxes_fallback) if bboxes_fallback is not None else 0
            used_scale = scale_factor
            if enh_count > 0:
                bboxes = bboxes_fallback
                kpss = kpss_fallback
            else:
                bboxes = bboxes_orig
                kpss = kpss_orig
                if orig_count > 0:
                    used_scale = 1.0
                    eval_roi = roi
        else:
            eval_roi = source_img
            used_scale = 1.0
            bboxes = bboxes_orig
            kpss = kpss_orig
            if orig_count == 0 and illumination in ("DARK", "BACKLIT") and enhanced_roi is not None:
                with self._infer_lock:
                    bboxes_enh, kpss_enh = det_model.detect(eval_roi, max_num=0, det_thresh=0.30)
                enh_count = len(bboxes_enh) if bboxes_enh is not None else 0
                if enh_count > 0:
                    bboxes = bboxes_enh
                    kpss = kpss_enh

        results = []
        if bboxes is not None and len(bboxes) > 0:
            for i in range(len(bboxes)):
                b = bboxes[i].copy()
                k = kpss[i].copy() if kpss is not None and i < len(kpss) else None

                if used_scale > 1.0:
                    b[:4] /= used_scale
                    if k is not None:
                        k /= used_scale

                results.append({
                    "bbox": b[:4],
                    "score": float(b[4]),
                    "kps": k,
                })

            # Sort by bounding box area descending
            results.sort(
                key=lambda item: (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1]),
                reverse=True,
            )

        best_conf = float(results[0]["score"]) if results else 0.0
        best_box = [round(float(v), 1) for v in results[0]["bbox"][:4]] if results else None
        diag = {
            "upper_roi_size": (rw, rh),
            "upscale_factor": used_scale,
            "detector_input_size": (eval_roi.shape[1], eval_roi.shape[0]),
            "illumination_state": illumination,
            "original_face_count": orig_count,
            "enhanced_face_count": enh_count,
            "best_face_confidence": best_conf,
            "best_face_bbox": best_box,
            "eval_roi": eval_roi,
        }
        self.last_detection_diag = diag

        if return_diag:
            return results, diag
        return results

    def calculate_face_quality(
        self,
        native_frame: np.ndarray,
        face_bbox: Any,
        conf: float,
        illumination: str,
        kps: np.ndarray | None = None,
    ) -> tuple[float, float, float, str]:
        """Evaluate face quality against quality gates from native face pixels.

        Returns:
            tuple[float, float, float, str]:
                - face_size: min(face_w, face_h) in native pixels
                - sharpness: scale-robust sharpness (Tenengrad / Laplacian)
                - quality_score: composite quality score with clipping penalty
                - gate_decision: 'FACE_TOO_SMALL', 'WAIT_FOR_BETTER_FACE', or 'CAN_EMBED'
        """
        x1, y1, x2, y2 = [int(round(float(v))) for v in face_bbox[:4]]
        h, w = native_frame.shape[:2]
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(0, min(x2, w))
        y2 = max(0, min(y2, h))

        fw = max(0, x2 - x1)
        fh = max(0, y2 - y1)
        face_size = float(min(fw, fh))

        if fw < 5 or fh < 5:
            return face_size, 0.0, 0.0, "FACE_TOO_SMALL"

        face_crop = native_frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

        # Native sharpness metrics computed BEFORE upscale
        sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        tenengrad = float(np.mean(sobelx**2 + sobely**2))
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        # Blend Tenengrad & Laplacian var for robustness across small/large faces
        sharpness = max(lap_var, min(300.0, tenengrad * 0.05))

        # Clipping penalty
        over_ratio = float(np.mean(gray >= 245))
        under_ratio = float(np.mean(gray <= 15))
        clipping_penalty = max(0.25, min(1.0, 1.0 - (over_ratio * 2.0 + under_ratio * 1.5)))

        # Quality Gate:
        # <28 px  -> FACE_TOO_SMALL (protects against noise/blobs)
        # >=28 px -> CAN_EMBED if confidence and sharpness satisfy quality floor
        if face_size < 28.0:
            gate_decision = "FACE_TOO_SMALL"
        else:
            if conf < 0.30 or (lap_var < 12.0 and tenengrad < 150.0):
                gate_decision = "WAIT_FOR_BETTER_FACE"
            else:
                gate_decision = "CAN_EMBED"

        frontality = 0.5
        if kps is not None:
            try:
                from src.recognition.target_matcher import calculate_face_frontality
                frontality = calculate_face_frontality(kps)
            except Exception:
                frontality = 0.5

        # Composite quality score for BestFace replacement
        # Rewards larger face size, higher sharpness, good confidence, frontality, and normal lighting
        quality_score = (
            min(face_size, 120.0) * 0.8
            + min(sharpness, 200.0) * 0.3
            + conf * 40.0
            + frontality * 10.0
            + (10.0 if illumination == "NORMAL" else 0.0)
        ) * clipping_penalty

        return face_size, sharpness, quality_score, gate_decision

    def align_and_embed(
        self,
        native_frame: np.ndarray,
        kps: np.ndarray,
        illumination: str = "NORMAL",
        variant: str = "RAW",
    ) -> np.ndarray | None:
        """Preprocess face with landmark alignment and extract ArcFace embedding.

        Pipeline:
            Landmark alignment (112x112) from native frame pixels ->
            conditional enhancement variant (RAW / EXPOSURE_CORRECTED / LOCAL_CONTRAST / MILD_SHARPEN) ->
            ArcFace embedding -> L2 normalize.
            RAW is the primary reference. No generative face restoration.
        """
        if kps is None or len(kps) < 5:
            return None

        if not self._initialized:
            if not self.initialize():
                return None

        try:
            from insightface.utils import face_align
            aligned = face_align.norm_crop(native_frame, landmark=kps, image_size=112)
        except Exception as exc:
            logger.warning("[FACE_ALIGN] norm_crop failed: %s", exc)
            return None

        if aligned is None or aligned.size == 0:
            return None

        # Resolve variant
        eff_variant = variant
        if eff_variant == "RAW":
            # Keep raw native pixels for ArcFace
            pass
        elif eff_variant == "EXPOSURE_CORRECTED" or (eff_variant == "AUTO" and illumination in ("DARK", "UNDEREXPOSED")):
            ycbcr = cv2.cvtColor(aligned, cv2.COLOR_BGR2YCrCb)
            Y = ycbcr[:, :, 0]
            med = float(np.median(Y))
            gamma = np.clip(np.log(100.0 / 255.0) / np.log(max(15.0, med) / 255.0), 0.70, 1.0)
            inv_gamma = 1.0 / gamma
            table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")
            ycbcr[:, :, 0] = cv2.LUT(Y, table)
            aligned = cv2.cvtColor(ycbcr, cv2.COLOR_YCrCb2BGR)
        elif eff_variant == "LOCAL_CONTRAST" or (eff_variant == "AUTO" and illumination in ("BACKLIT", "LOW_CONTRAST")):
            ycbcr = cv2.cvtColor(aligned, cv2.COLOR_BGR2YCrCb)
            clahe = cv2.createCLAHE(clipLimit=1.2, tileGridSize=(4, 4))
            ycbcr[:, :, 0] = clahe.apply(ycbcr[:, :, 0])
            aligned = cv2.cvtColor(ycbcr, cv2.COLOR_YCrCb2BGR)
        elif eff_variant == "MILD_SHARPEN":
            blurred = cv2.GaussianBlur(aligned, (0, 0), 1.0)
            aligned = cv2.addWeighted(aligned, 1.35, blurred, -0.35, 0)
        elif illumination in ("BACKLIT", "DARK") and eff_variant not in ("RAW",):
            # Backward-compatible fallback
            lab = cv2.cvtColor(aligned, cv2.COLOR_BGR2LAB)
            clahe = cv2.createCLAHE(clipLimit=1.2, tileGridSize=(4, 4))
            lab[:, :, 0] = clahe.apply(lab[:, :, 0])
            aligned = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

        rec_model = getattr(self, "_rec_model", None)
        if rec_model is None and self._app is not None:
            rec_model = self._app.models.get("recognition")
        if rec_model is None:
            return None

        with self._infer_lock:
            try:
                feat = rec_model.get_feat(aligned)
                if feat is None:
                    return None
                emb = np.asarray(feat, dtype=np.float32).flatten()
                norm = np.linalg.norm(emb)
                if norm < 1e-7 or np.isnan(norm) or np.isinf(norm):
                    return None
                return emb / norm
            except Exception as exc:
                logger.error("[ARCFACE_EMBED] Error during embedding: %s", exc)
                return None

    def extract_face_embedding_detailed(
        self,
        image: np.ndarray,
        is_registration: bool = False,
        min_confidence: float = 0.35,
    ) -> tuple[np.ndarray | None, FaceDiagInfo]:
        """Detect the best face in BGR image and return normalized embedding with full diagnostics.

        Args:
            image: BGR numpy image (full frame, user upload, or person crop).
            is_registration: If True, applies extra checks and multi-orientation search.
            min_confidence: Minimum detection confidence score.

        Returns:
            tuple[np.ndarray | None, FaceDiagInfo]:
                512-dim embedding (or None) and diagnostic information.
        """
        diag = FaceDiagInfo(
            model_name=self.model_name,
            model_path=self._model_path,
            model_loaded=self._initialized,
            execution_provider=self.execution_provider,
            det_size=self.det_size,
        )

        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            diag.rejection_reason = "IMAGE_DECODE_FAILED"
            diag.user_message = "Không thể giải mã hình ảnh hoặc hình ảnh rỗng"
            return None, diag

        h, w = image.shape[:2]
        if h < 20 or w < 20:
            diag.rejection_reason = "FACE_TOO_SMALL"
            diag.user_message = f"Kích thước ảnh quá nhỏ ({w}x{h} px)"
            return None, diag

        if not self._initialized:
            if not self.initialize():
                diag.rejection_reason = "FACE_MODEL_NOT_LOADED"
                diag.user_message = f"Không thể tải mô hình nhận diện khuôn mặt: {self._init_error}"
                return None, diag

        diag.model_loaded = True

        with self._infer_lock:
            try:
                assert self._app is not None

                # Step 1: Detect faces on the input image
                faces = self._app.get(image)
                rotation_applied = 0

                # Step 2: Multi-orientation fallback for target registration if 0 faces found
                if is_registration and (not faces or len(faces) == 0):
                    # Try 90 CW, 180, 270 CW (90 CCW)
                    rotations = [
                        (90, cv2.ROTATE_90_CLOCKWISE),
                        (180, cv2.ROTATE_180),
                        (270, cv2.ROTATE_90_COUNTERCLOCKWISE),
                    ]
                    for deg, rot_code in rotations:
                        rotated_img = cv2.rotate(image, rot_code)
                        rot_faces = self._app.get(rotated_img)
                        if rot_faces and len(rot_faces) > 0:
                            faces = rot_faces
                            rotation_applied = deg
                            logger.info("[FACE_ROTATION_RECOVERY] Found %d face(s) at %d deg rotation", len(faces), deg)
                            break

                diag.rotation_applied = rotation_applied
                diag.faces_detected = len(faces) if faces else 0

                if not faces or len(faces) == 0:
                    diag.rejection_reason = "NO_FACE_DETECTED"
                    diag.user_message = "Không tìm thấy khuôn mặt người trong ảnh tải lên"
                    logger.info("[FACE_REJECTED] reason=NO_FACE_DETECTED shape=(%d,%d)", h, w)
                    return None, diag

                # Collect detection confidences and bounding boxes
                scores = []
                boxes = []
                for face in faces:
                    score = float(getattr(face, "det_score", 0.0))
                    scores.append(round(score, 3))
                    bbox = getattr(face, "bbox", None)
                    if bbox is not None:
                        boxes.append([round(float(v), 1) for v in bbox[:4]])

                diag.confidences = scores
                diag.bounding_boxes = boxes

                # Pick face with largest bounding box area
                best_face = None
                max_area = 0.0
                all_areas = []

                for face in faces:
                    bbox = getattr(face, "bbox", None)
                    if bbox is not None and len(bbox) >= 4:
                        area = max(0.0, float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
                        all_areas.append(area)
                        if area > max_area:
                            max_area = area
                            best_face = face

                if best_face is None:
                    best_face = faces[0]

                # Step 3: Validate best face
                best_score = float(getattr(best_face, "det_score", 0.0))
                best_bbox = getattr(best_face, "bbox", None)
                bw = (best_bbox[2] - best_bbox[0]) if best_bbox is not None and len(best_bbox) >= 4 else 0
                bh = (best_bbox[3] - best_bbox[1]) if best_bbox is not None and len(best_bbox) >= 4 else 0

                kps = getattr(best_face, "kps", None)
                diag.landmarks_count = len(kps) if kps is not None else 0

                if best_score < min_confidence:
                    diag.rejection_reason = "FACE_CONFIDENCE_TOO_LOW"
                    diag.user_message = f"Độ tin cậy phát hiện khuôn mặt quá thấp ({best_score:.2f} < {min_confidence:.2f})"
                    logger.info("[FACE_REJECTED] reason=FACE_CONFIDENCE_TOO_LOW score=%.3f min=%.3f", best_score, min_confidence)
                    return None, diag

                if bw < 20 or bh < 20:
                    diag.rejection_reason = "FACE_TOO_SMALL"
                    diag.user_message = f"Vùng khuôn mặt quá nhỏ ({bw:.0f}x{bh:.0f} px)"
                    logger.info("[FACE_REJECTED] reason=FACE_TOO_SMALL bw=%.1f bh=%.1f", bw, bh)
                    return None, diag

                # Check multiple faces ambiguity in registration mode
                if is_registration and len(faces) > 1:
                    all_areas.sort(reverse=True)
                    if len(all_areas) >= 2 and all_areas[0] > 0:
                        ratio = all_areas[1] / all_areas[0]
                        if ratio > 0.85 and scores[0] > 0.6 and scores[1] > 0.6:
                            # Two similarly sized prominent faces: log diagnostic
                            logger.warning(
                                "[FACE_MULTIPLE_AMBIGUOUS] Multiple prominent faces detected (area ratio=%.2f). Selected largest.",
                                ratio,
                            )

                # Step 4: Extract and validate embedding
                embedding = getattr(best_face, "normed_embedding", None)
                if embedding is None:
                    raw_emb = getattr(best_face, "embedding", None)
                    if raw_emb is not None:
                        norm = np.linalg.norm(raw_emb)
                        if norm > 1e-7:
                            embedding = raw_emb / norm

                if embedding is None or len(embedding) == 0:
                    diag.rejection_reason = "EMBEDDING_FAILED"
                    diag.user_message = "Không thể trích xuất vector đặc trưng khuôn mặt"
                    logger.warning("[FACE_REJECTED] reason=EMBEDDING_FAILED")
                    return None, diag

                emb_arr = np.asarray(embedding, dtype=np.float32).flatten()
                norm_val = float(np.linalg.norm(emb_arr))
                diag.embedding_dims = int(len(emb_arr))
                diag.embedding_norm = round(norm_val, 4)
                diag.has_nan = bool(np.isnan(emb_arr).any())
                diag.has_inf = bool(np.isinf(emb_arr).any())
                diag.is_zero = bool(norm_val < 1e-7)

                if diag.has_nan or diag.has_inf or diag.is_zero or diag.embedding_dims != 512:
                    diag.rejection_reason = "EMBEDDING_FAILED"
                    diag.user_message = "Vector đặc trưng không hợp lệ (NaN/Inf hoặc kích thước sai)"
                    logger.warning(
                        "[FACE_REJECTED] reason=EMBEDDING_FAILED dims=%d norm=%.4f nan=%s inf=%s zero=%s",
                        diag.embedding_dims, norm_val, diag.has_nan, diag.has_inf, diag.is_zero,
                    )
                    return None, diag

                logger.info(
                    "[FACE_ACCEPTED] faces=%d best_score=%.3f bbox=[%.1f,%.1f,%.1f,%.1f] dims=%d norm=%.4f rot=%d",
                    len(faces), best_score, best_bbox[0], best_bbox[1], best_bbox[2], best_bbox[3],
                    diag.embedding_dims, norm_val, rotation_applied,
                )
                return emb_arr, diag

            except Exception as exc:
                diag.rejection_reason = "FACE_MODEL_RUNTIME_ERROR"
                diag.user_message = f"Lỗi trong quá trình xử lý khuôn mặt: {exc}"
                logger.error("[FACE] Face embedding extraction error: %s", exc, exc_info=True)
                return None, diag

    def extract_face_embedding(self, image: np.ndarray) -> np.ndarray | None:
        """Detect the largest face in image and return normalized 512-dim embedding.

        Maintains backward compatibility with callers expecting np.ndarray | None.
        """
        emb, _ = self.extract_face_embedding_detailed(image, is_registration=False)
        return emb


# Module-level convenience singleton
face_embedder = FaceEmbedder.get_instance()

