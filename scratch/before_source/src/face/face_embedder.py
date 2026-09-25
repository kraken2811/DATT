"""Face Embedding & Recognition Module for DATT.

Reuses InsightFace ('buffalo_s' with MobileFaceNet 512-dim embedding)
using CPUExecutionProvider via ONNX Runtime.

Lifecycle:
- Singleton pattern: Model weights are loaded once in RAM on startup / lazy init.
- Never instantiates models per-frame.
- Thread-safe inference.
"""

import logging
import threading
from typing import Any

import numpy as np

logger = logging.getLogger("datt.face")


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

    def __init__(self, model_name: str = "buffalo_s", det_size: tuple[int, int] = (320, 320)) -> None:
        self.model_name = model_name
        self.det_size = det_size
        self._app = None
        self._initialized = False
        self._init_error: str | None = None
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

                logger.info("[FACE] Initializing InsightFace '%s' models...", self.model_name)
                app = FaceAnalysis(
                    name=self.model_name,
                    providers=["CPUExecutionProvider"],
                )
                app.prepare(ctx_id=0, det_size=self.det_size)
                self._app = app
                self._initialized = True
                logger.info("[FACE] InsightFace '%s' initialized successfully.", self.model_name)
                return True
            except Exception as exc:
                self._init_error = str(exc)
                logger.error("[FACE] Failed to initialize InsightFace: %s", exc, exc_info=True)
                return False

    def extract_face_embedding(self, image: np.ndarray) -> np.ndarray | None:
        """Detect the largest face in image and return normalized 512-dim embedding.

        Args:
            image: BGR numpy image (full frame, user upload, or person crop).

        Returns:
            np.ndarray | None: 512-dim float32 L2-normalized embedding, or None if no face found.
        """
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return None

        h, w = image.shape[:2]
        if h < 20 or w < 20:
            return None

        if not self._initialized:
            if not self.initialize():
                return None

        with self._infer_lock:
            try:
                assert self._app is not None
                faces = self._app.get(image)
                if not faces:
                    return None

                # Pick face with largest bounding box area
                best_face = None
                max_area = 0.0
                for face in faces:
                    bbox = getattr(face, "bbox", None)
                    if bbox is not None and len(bbox) == 4:
                        area = max(0.0, float((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])))
                        if area > max_area:
                            max_area = area
                            best_face = face

                if best_face is None:
                    best_face = faces[0]

                # Extract normalized embedding (512-dim)
                embedding = getattr(best_face, "normed_embedding", None)
                if embedding is None:
                    raw_emb = getattr(best_face, "embedding", None)
                    if raw_emb is not None:
                        norm = np.linalg.norm(raw_emb)
                        if norm > 1e-7:
                            embedding = raw_emb / norm

                if embedding is not None and len(embedding) > 0:
                    emb_arr = np.asarray(embedding, dtype=np.float32).flatten()
                    if not np.isnan(emb_arr).any():
                        return emb_arr

                return None

            except Exception as exc:
                logger.warning("[FACE] Face embedding extraction error: %s", exc)
                return None


# Module-level convenience singleton
face_embedder = FaceEmbedder.get_instance()
