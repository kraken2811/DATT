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
    ) -> None:
        self.model_name = model_name
        self.det_size = det_size
        self._app = None
        self._initialized = False
        self._init_error: str | None = None
        self._model_path: str = ""
        self._infer_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "FaceEmbedder":
        """Thread-safe access to singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def initialize(self) -> bool:
        """Load InsightFace models into memory."""
        with self._infer_lock:
            if self._initialized:
                return True
            if self._init_error is not None:
                return False

            try:
                from insightface.app import FaceAnalysis

                model_root = Path.home() / ".insightface" / "models" / self.model_name
                self._model_path = str(model_root)

                logger.info("[FACE] Initializing InsightFace '%s' models from %s...", self.model_name, self._model_path)
                app = FaceAnalysis(
                    name=self.model_name,
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(ctx_id=0, det_size=self.det_size, det_thresh=0.40)
                self._app = app
                self._det_model = app.models.get("detection")
                self._rec_model = app.models.get("recognition")
                self._initialized = True
                logger.info(
                    "[FACE] InsightFace '%s' initialized successfully (provider=CPUExecutionProvider, det_size=%s).",
                    self.model_name, self.det_size,
                )
                return True
            except Exception as exc:
                self._init_error = str(exc)
                logger.error("[FACE] Failed to initialize InsightFace: %s", exc, exc_info=True)
                return False

    @staticmethod
    def check_illumination(roi: np.ndarray) -> tuple[str, str, np.ndarray]:
        """Check illumination of head/face ROI using LAB-L space.

        Returns:
            tuple[str, str, np.ndarray]:
                - illumination: "NORMAL", "DARK", or "BACKLIT"
                - enhancement_applied: "NONE", "CLAHE", "CLAHE+GAMMA"
                - enhanced_roi: Enhanced BGR image if dark/backlit, else original roi
        """
        if roi is None or roi.size == 0:
            return "NORMAL", "NONE", roi

        lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
        L = lab[:, :, 0]

        mean_L = float(np.mean(L))
        rh, rw = L.shape[:2]
        center = L[
            int(rh * 0.2):max(int(rh * 0.2) + 1, int(rh * 0.8)),
            int(rw * 0.2):max(int(rw * 0.2) + 1, int(rw * 0.8)),
        ]
        center_mean = float(np.mean(center)) if center.size > 0 else mean_L
        p90 = float(np.percentile(L, 90))

        # Backlit check: high background brightness while face center is dark or contrast gap > 85
        if (p90 >= 170.0 and center_mean < 85.0) or (p90 - center_mean > 90.0):
            illumination = "BACKLIT"
        elif mean_L < 75.0 or center_mean < 70.0:
            illumination = "DARK"
        else:
            illumination = "NORMAL"

        if illumination == "NORMAL":
            return "NORMAL", "NONE", roi

        # Gentle enhancement for DARK or BACKLIT
        enhancements = []
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        L_enhanced = clahe.apply(L)
        enhancements.append("CLAHE")

        if center_mean < 65.0:
            inv_gamma = 1.0 / 0.85
            table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)]).astype("uint8")
            L_enhanced = cv2.LUT(L_enhanced, table)
            enhancements.append("GAMMA")

        lab_enhanced = lab.copy()
        lab_enhanced[:, :, 0] = L_enhanced
        enhanced_roi = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
        enhancement_applied = "+".join(enhancements)

        return illumination, enhancement_applied, enhanced_roi

    def detect_faces_in_roi(
        self,
        roi: np.ndarray,
        illumination: str,
        enhanced_roi: np.ndarray | None = None,
    ) -> list[dict[str, Any]]:
        """Detect faces within upper-body/head ROI using SCRFD.

        Supports upscaling for small ROIs (2x-4x) and enhancement fallback for backlit/dark scenes.

        Returns:
            list[dict[str, Any]]: List of dicts with 'bbox' [x1, y1, x2, y2], 'score', 'kps' in unscaled ROI coords.
        """
        if roi is None or roi.size == 0:
            return []

        if not self._initialized:
            if not self.initialize():
                return []

        det_model = getattr(self, "_det_model", None)
        if det_model is None and self._app is not None:
            det_model = self._app.models.get("detection")
        if det_model is None:
            return []

        rh, rw = roi.shape[:2]
        min_dim = min(rh, rw)

        # Upscaling factor to aid detection on small ROIs
        scale_factor = 1.0
        if min_dim < 64:
            scale_factor = 4.0
        elif min_dim < 160:
            scale_factor = 2.0

        if scale_factor > 1.0:
            eval_roi = cv2.resize(roi, (0, 0), fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
        else:
            eval_roi = roi

        with self._infer_lock:
            bboxes, kpss = det_model.detect(eval_roi, max_num=0, det_thresh=0.35)

            # Fallback to enhanced ROI if no face found and scene is dark or backlit
            if (bboxes is None or len(bboxes) == 0) and illumination in ("DARK", "BACKLIT") and enhanced_roi is not None:
                if scale_factor > 1.0:
                    eval_enhanced = cv2.resize(
                        enhanced_roi, (0, 0), fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC
                    )
                else:
                    eval_enhanced = enhanced_roi
                bboxes, kpss = det_model.detect(eval_enhanced, max_num=0, det_thresh=0.30)

        if bboxes is None or len(bboxes) == 0:
            return []

        results = []
        for i in range(len(bboxes)):
            b = bboxes[i].copy()
            k = kpss[i].copy() if kpss is not None and i < len(kpss) else None

            if scale_factor > 1.0:
                b[:4] /= scale_factor
                if k is not None:
                    k /= scale_factor

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
        return results

    def calculate_face_quality(
        self,
        native_frame: np.ndarray,
        face_bbox: Any,
        conf: float,
        illumination: str,
    ) -> tuple[float, float, float, str]:
        """Evaluate face quality against quality gates.

        Returns:
            tuple[float, float, float, str]:
                - face_size: min(face_w, face_h) in native pixels
                - sharpness: variance of Laplacian
                - quality_score: composite quality score
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
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # Quality Gate (Point 5):
        # <32 px  -> FACE_TOO_SMALL
        # 32–48px -> WAIT_FOR_BETTER_FACE
        # >=48px  -> can embedding
        # >=64px  -> ưu tiên
        if face_size < 32.0:
            gate_decision = "FACE_TOO_SMALL"
        elif face_size < 48.0:
            gate_decision = "WAIT_FOR_BETTER_FACE"
        else:
            if conf < 0.40 or sharpness < 20.0:
                gate_decision = "WAIT_FOR_BETTER_FACE"
            else:
                gate_decision = "CAN_EMBED"

        # Composite quality score for BestFace replacement
        # Rewards larger face size, higher sharpness, good confidence, and normal lighting
        quality_score = (
            face_size * 1.0
            + min(sharpness, 200.0) * 0.3
            + conf * 40.0
            + (10.0 if illumination == "NORMAL" else 0.0)
        )

        return face_size, sharpness, quality_score, gate_decision

    def align_and_embed(
        self,
        native_frame: np.ndarray,
        kps: np.ndarray,
        illumination: str = "NORMAL",
    ) -> np.ndarray | None:
        """Preprocess face with landmark alignment and extract ArcFace embedding.

        Pipeline:
            Landmark alignment (112x112) -> light lighting balancing if backlit -> ArcFace embedding -> normalize.
            No generative face restoration.
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

        # Mild lighting balancing if backlit or dark
        if illumination in ("BACKLIT", "DARK"):
            lab = cv2.cvtColor(aligned, cv2.COLOR_BGR2LAB)
            clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(4, 4))
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

