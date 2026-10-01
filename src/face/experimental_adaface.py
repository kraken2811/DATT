"""Experimental AdaFace Backend for DATT.

Isolated experimental interface for AdaFace (Quality Adaptive Margin for Face Recognition, CVPR 2022).
Backbone: IR-50 (MS1MV2) ONNX model (512D output).

Lifecycle:
- Isolated behind benchmark / experimental interface.
- Does NOT replace or modify ArcFace in production.
- CUDA Execution Provider prioritized when available; explicitly logs if falling back to CPU.
- Standard 5-point alignment (112x112) identical to SCRFD ArcFace pipeline.
- Input normalization: (x - 127.5) / 127.5 with BGR channel order.
- Output: 512D L2-normalized embedding.
"""

from __future__ import annotations

import logging
from pathlib import Path
import threading
from typing import Any, Sequence

import cv2
import numpy as np
import onnxruntime as ort

logger = logging.getLogger("datt.experimental_adaface")

MODEL_DEFAULT_PATH = Path("models/face/adaface_ir50_ms1mv2.onnx")


class AdaFaceEmbedder:
    """Experimental AdaFace embedding extractor."""

    _instance: "AdaFaceEmbedder | None" = None
    _lock = threading.Lock()

    def __init__(
        self,
        model_path: str | Path | None = None,
        prefer_gpu: bool = True,
    ) -> None:
        self.model_name = "adaface_ir50_ms1mv2"
        self.model_version = "cvpr2022_ir50_ms1mv2"
        self.model_path = Path(model_path or MODEL_DEFAULT_PATH)
        self.prefer_gpu = prefer_gpu
        self._session: ort.InferenceSession | None = None
        self._initialized = False
        self._init_error: str | None = None
        self._infer_lock = threading.Lock()
        self.execution_provider: str = "Uninitialized"
        self.input_name: str = "input"
        self.output_name: str = "embedding"
        self.embedding_dim: int = 512

    @classmethod
    def get_instance(cls, model_path: str | Path | None = None) -> "AdaFaceEmbedder":
        """Thread-safe access to singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(model_path=model_path)
            return cls._instance

    def initialize(self) -> bool:
        """Load AdaFace ONNX model on CUDA (GPU) or log fallback to CPU."""
        with self._infer_lock:
            if self._initialized:
                return True
            if self._init_error is not None:
                return False

            if not self.model_path.exists():
                self._init_error = f"AdaFace model file not found at {self.model_path}"
                logger.error("[ADAFACE] %s", self._init_error)
                return False

            try:
                available_providers = ort.get_available_providers()
                logger.info("[ADAFACE] Available ORT providers: %s", available_providers)

                target_gpu_id = 0
                try:
                    import config
                    dev = getattr(config, "DEVICE", "cuda:0")
                    if "cuda:" in str(dev).lower():
                        target_gpu_id = int(str(dev).split(":")[-1])
                except Exception:
                    target_gpu_id = 0

                providers: list[Any] = []
                if self.prefer_gpu and "CUDAExecutionProvider" in available_providers:
                    providers = [
                        ("CUDAExecutionProvider", {"device_id": target_gpu_id}),
                        "CPUExecutionProvider",
                    ]
                    logger.info("[ADAFACE] Configuring CUDAExecutionProvider (device_id=%d)", target_gpu_id)
                else:
                    if self.prefer_gpu:
                        logger.warning(
                            "[ADAFACE_PROVIDER_FALLBACK] CUDA requested but CUDAExecutionProvider not available in runtime; using CPUExecutionProvider"
                        )
                    providers = ["CPUExecutionProvider"]

                # Configure session options
                sess_options = ort.SessionOptions()
                sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

                self._session = ort.InferenceSession(
                    str(self.model_path),
                    sess_options=sess_options,
                    providers=providers,
                )

                active_providers = self._session.get_providers()
                self.execution_provider = active_providers[0] if active_providers else "Unknown"

                # Inspect I/O
                inputs = self._session.get_inputs()
                outputs = self._session.get_outputs()
                if inputs:
                    self.input_name = inputs[0].name
                if outputs:
                    self.output_name = outputs[0].name

                self._initialized = True
                logger.info(
                    "[ADAFACE] Initialized successfully. Model=%s, ActiveProvider=%s, InName=%s, OutName=%s",
                    self.model_name, self.execution_provider, self.input_name, self.output_name,
                )
                return True
            except Exception as exc:
                self._init_error = str(exc)
                logger.error("[ADAFACE] Initialization error: %s", exc, exc_info=True)
                return False

    def align_and_embed(
        self,
        native_frame: np.ndarray,
        kps: np.ndarray,
    ) -> np.ndarray | None:
        """Extract 512D AdaFace embedding from native frame using SCRFD 5-point landmarks.

        Pipeline:
        1. 5-point alignment via insightface.utils.face_align.norm_crop (112x112)
        2. AdaFace preprocessing: BGR channel format, (pixel - 127.5) / 127.5, shape (1, 3, 112, 112)
        3. Inference via ONNX Runtime
        4. L2 normalization: feat / ||feat||_2
        """
        if native_frame is None or kps is None or len(kps) < 5:
            return None

        if not self._initialized:
            if not self.initialize():
                return None

        try:
            from insightface.utils import face_align
            aligned = face_align.norm_crop(native_frame, landmark=kps, image_size=112)
        except Exception as exc:
            logger.warning("[ADAFACE_ALIGN] Alignment failed: %s", exc)
            return None

        if aligned is None or aligned.size == 0:
            return None

        return self.embed_aligned_face(aligned)

    def embed_aligned_face(self, aligned_bgr_112: np.ndarray) -> np.ndarray | None:
        """Extract L2-normalized 512D AdaFace embedding from already aligned 112x112 BGR face."""
        if aligned_bgr_112 is None or aligned_bgr_112.shape[:2] != (112, 112):
            return None

        if not self._initialized:
            if not self.initialize():
                return None

        with self._infer_lock:
            try:
                # Preprocessing for AdaFace: BGR format, (pixel - 127.5) / 127.5
                blob = (aligned_bgr_112.astype(np.float32) - 127.5) / 127.5
                blob = np.transpose(blob, (2, 0, 1))[np.newaxis, :]  # Shape: (1, 3, 112, 112)

                feat = self._session.run([self.output_name], {self.input_name: blob})[0][0]
                emb = np.asarray(feat, dtype=np.float32).flatten()

                norm = float(np.linalg.norm(emb))
                if norm < 1e-7 or np.isnan(norm) or np.isinf(norm):
                    return None

                return emb / norm
            except Exception as exc:
                logger.error("[ADAFACE_EMBED] Inference error: %s", exc)
                return None

    def extract_face_embedding(self, image: np.ndarray) -> tuple[np.ndarray | None, dict[str, Any]]:
        """Detect best face using SCRFD and return L2-normalized AdaFace embedding."""
        diag = {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "execution_provider": self.execution_provider,
            "faces_detected": 0,
            "confidence": 0.0,
            "face_size": 0.0,
            "landmarks_count": 0,
            "embedding_dims": 512,
            "embedding_norm": 0.0,
            "status": "FAIL",
            "reason": None,
        }

        if image is None or image.size == 0:
            diag["reason"] = "IMAGE_EMPTY"
            return None, diag

        from src.face.face_embedder import FaceEmbedder
        fe = FaceEmbedder.get_instance()
        if not fe._initialized:
            fe.initialize()

        with fe._infer_lock:
            faces = fe._app.get(image)

        if not faces:
            diag["reason"] = "NO_FACE_DETECTED"
            return None, diag

        # Select largest face
        best_face = max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
        )

        diag["faces_detected"] = len(faces)
        diag["confidence"] = float(getattr(best_face, "det_score", 0.0))
        bw = float(best_face.bbox[2] - best_face.bbox[0])
        bh = float(best_face.bbox[3] - best_face.bbox[1])
        diag["face_size"] = max(bw, bh)
        kps = getattr(best_face, "kps", None)
        diag["landmarks_count"] = len(kps) if kps is not None else 0

        emb = self.align_and_embed(image, kps)
        if emb is None:
            diag["reason"] = "EMBEDDING_FAILED"
            return None, diag

        diag["status"] = "SUCCESS"
        diag["embedding_norm"] = float(np.linalg.norm(emb))
        return emb, diag


def adaface_cosine_similarity(v1: np.ndarray | None, v2: np.ndarray | None) -> float:
    """Calculate cosine similarity with zero-norm and dimension guards."""
    if v1 is None or v2 is None:
        return 0.0
    v1 = np.asarray(v1, dtype=np.float32).flatten()
    v2 = np.asarray(v2, dtype=np.float32).flatten()
    if v1.size == 0 or v2.size == 0 or v1.size != v2.size:
        return 0.0
    n1 = float(np.linalg.norm(v1))
    n2 = float(np.linalg.norm(v2))
    if n1 < 1e-7 or n2 < 1e-7 or np.isnan(n1) or np.isnan(n2):
        return 0.0
    sim = float(np.dot(v1, v2) / (n1 * n2))
    return max(-1.0, min(1.0, sim))
