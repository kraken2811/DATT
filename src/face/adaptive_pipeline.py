"""Validated adaptive face geometry and unique-frame F2 fusion.

Geometry/warp/safety functions copied from
scratch/run_final_homography_production_validation.py.
Normal-path arithmetic is preserved. Additional defensive checks reject invalid
transforms before warping. Selection never receives an enrollment or target score.
"""
from __future__ import annotations
import math
import time
from collections import Counter
from typing import Any
import cv2
import numpy as np

CANONICAL_ASPECT = 1.1544
TOP_K = 3
HOMOGRAPHY_ALPHA = 0.50

def compute_geometry_and_overhead_score(
    kps: np.ndarray,
    bbox: list[float] | tuple[float, float, float, float],
    roi_h: int,
    roi_w: int,
) -> dict[str, float]:
    lx, ly = float(kps[0][0]), float(kps[0][1])
    rx, ry = float(kps[1][0]), float(kps[1][1])
    nx, ny = float(kps[2][0]), float(kps[2][1])
    lmx, lmy = float(kps[3][0]), float(kps[3][1])
    rmx, rmy = float(kps[4][0]), float(kps[4][1])

    fw = max(1.0, float(bbox[2] - bbox[0]))
    fh = max(1.0, float(bbox[3] - bbox[1]))

    eye_dx = rx - lx
    eye_dy = ry - ly
    eye_dist = max(1.0, math.hypot(eye_dx, eye_dy))
    roll_deg = math.degrees(math.atan2(eye_dy, eye_dx))

    eye_cx, eye_cy = (lx + rx) / 2.0, (ly + ry) / 2.0
    mouth_cx, mouth_cy = (lmx + rmx) / 2.0, (lmy + rmy) / 2.0
    face_cx, face_cy = (eye_cx + mouth_cx) / 2.0, (eye_cy + mouth_cy) / 2.0

    d_en = ny - eye_cy
    d_nm = mouth_cy - ny
    d_em = max(1.0, mouth_cy - eye_cy)

    aspect = d_em / eye_dist
    eye_ratio = eye_dist / fw
    forehead_dist = eye_cy - float(bbox[1])
    forehead_ratio = forehead_dist / fh

    roi_cx, roi_cy = roi_w / 2.0, roi_h / 2.0
    center_shift = math.hypot(face_cx - roi_cx, face_cy - roi_cy) / max(1.0, math.hypot(roi_cx, roi_cy))

    d_left = abs(nx - lx)
    d_right = abs(rx - nx)
    yaw_asym = (d_left - d_right) / max(1.0, eye_dist)
    yaw_deg = yaw_asym * 45.0

    nose_ratio = d_en / d_em
    pitch_deg = (nose_ratio - 0.50) * 80.0

    aspect_deficit = max(0.0, (CANONICAL_ASPECT - aspect) / 0.25)
    eye_deficit = max(0.0, (0.46 - eye_ratio) / 0.08)
    forehead_surplus = max(0.0, (forehead_ratio - 0.35) / 0.15)

    distortion_raw = (0.40 * aspect_deficit + 0.35 * eye_deficit + 0.25 * forehead_surplus)
    overhead_distortion_score = float(min(100.0, max(0.0, distortion_raw * 100.0)))

    return {
        "face_width": fw, "face_height": fh, "eye_dist": eye_dist,
        "eye_ratio": eye_ratio, "aspect": aspect, "d_en": d_en, "d_nm": d_nm,
        "forehead_ratio": forehead_ratio, "center_shift": center_shift,
        "yaw_deg": yaw_deg, "pitch_deg": pitch_deg, "roll_deg": roll_deg,
        "overhead_distortion_score": overhead_distortion_score,
    }


def apply_r2_homography(head_roi: np.ndarray, kps: np.ndarray, alpha: float = 0.50) -> tuple[np.ndarray, np.ndarray]:
    """R2 — Perspective / Homography Rectification (outer 4 landmarks to canonical proportions)."""
    h, w = head_roi.shape[:2]
    src_4 = np.array([kps[0], kps[1], kps[4], kps[3]], dtype=np.float32)

    center = np.mean(src_4, axis=0)
    eye_dist = max(1.0, float(np.hypot(src_4[1][0] - src_4[0][0], src_4[1][1] - src_4[0][1])))
    target_em = eye_dist * CANONICAL_ASPECT

    dst_4 = np.array([
        [center[0] - eye_dist / 2.0, center[1] - target_em / 2.0],
        [center[0] + eye_dist / 2.0, center[1] - target_em / 2.0],
        [center[0] + eye_dist * 0.40, center[1] + target_em / 2.0],
        [center[0] - eye_dist * 0.40, center[1] + target_em / 2.0],
    ], dtype=np.float32)

    H_full = cv2.getPerspectiveTransform(src_4, dst_4)
    H_alpha = np.eye(3, dtype=np.float32) * (1.0 - alpha) + H_full * alpha

    # Reject unstable/singular transforms; do not clamp a flipped denominator.
    if (not np.isfinite(H_alpha).all() or abs(np.linalg.det(H_alpha)) < 1e-8
            or np.linalg.cond(H_alpha) > 1e8):
        raise ValueError("UNSTABLE_TRANSFORM")
    homogeneous = np.hstack([kps, np.ones((len(kps), 1), dtype=np.float32)])
    denominators = (H_alpha @ homogeneous.T).T[:, 2]
    if not np.isfinite(denominators).all() or np.any(denominators <= 1e-6):
        raise ValueError("INVALID_PROJECTIVE_DENOMINATOR")

    warped_roi = cv2.warpPerspective(head_roi, H_alpha, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)

    kps_homo = np.hstack([kps, np.ones((len(kps), 1), dtype=np.float32)])
    kps_w = (H_alpha @ kps_homo.T).T
    kps_w = kps_w[:, :2] / np.maximum(1e-6, kps_w[:, 2:3])
    return warped_roi, kps_w


def validate_homography_safety(
    head_roi: np.ndarray,
    warped_roi: np.ndarray,
    kps: np.ndarray,
    kps_w: np.ndarray,
) -> tuple[bool, str]:
    h, w = head_roi.shape[:2]
    if (warped_roi is None or warped_roi.shape != head_roi.shape
            or warped_roi.size == 0 or not np.isfinite(warped_roi).all()):
        return False, "INVALID_WARPED_IMAGE"
    if h < 10 or w < 10 or kps is None or len(kps) < 5:
        return False, "INVALID_INPUT_DIMENSIONS"

    if not np.all(np.isfinite(kps)) or not np.all(np.isfinite(kps_w)):
        return False, "LANDMARKS_NON_FINITE"

    margin = 15.0
    if np.any(kps_w[:, 0] < -margin) or np.any(kps_w[:, 0] > w + margin) or \
       np.any(kps_w[:, 1] < -margin) or np.any(kps_w[:, 1] > h + margin):
        return False, "MAPPED_LANDMARKS_OUT_OF_BOUNDS"

    if kps_w[0, 0] >= kps_w[1, 0]:
        return False, "MAPPED_EYE_ORDERING_INVERTED"

    return True, "SAFE"


def apply_homography_with_safety(
    head_roi: np.ndarray,
    kps: np.ndarray,
    alpha: float = 0.50,
) -> tuple[np.ndarray, np.ndarray, bool, str]:
    if head_roi is None or head_roi.ndim != 3 or head_roi.size == 0:
        return head_roi, kps, False, "INVALID_INPUT_DIMENSIONS"
    h, w = head_roi.shape[:2]
    if h < 10 or w < 10 or kps is None or len(kps) < 5:
        return head_roi, kps, False, "INVALID_INPUT_DIMENSIONS"
    if not np.all(np.isfinite(kps)):
        return head_roi, kps, False, "LANDMARKS_NON_FINITE"
    if np.asarray(kps).shape != (5, 2):
        return head_roi, kps, False, "INVALID_LANDMARK_SHAPE"
    polygon = np.float32([kps[0], kps[1], kps[4], kps[3]])
    if abs(cv2.contourArea(polygon)) < 1.0 or not cv2.isContourConvex(polygon):
        return head_roi, kps, False, "DEGENERATE_GEOMETRY"
    eye_dist = float(np.hypot(kps[1][0] - kps[0][0], kps[1][1] - kps[0][1]))
    if eye_dist < 4.0:
        return head_roi, kps, False, "EYE_DIST_TOO_SMALL"
    if kps[0][0] >= kps[1][0]:
        return head_roi, kps, False, "MAPPED_EYE_ORDERING_INVERTED"

    try:
        warped_roi, kps_w = apply_r2_homography(head_roi, kps, alpha)
    except Exception as e:
        return head_roi, kps, False, f"WARP_FAILED: {e}"

    is_safe, reason = validate_homography_safety(head_roi, warped_roi, kps, kps_w)
    if not is_safe:
        return head_roi, kps, False, reason
    return warped_roi, kps_w, True, "SAFE"


def select_candidates(candidates: list[dict], top_k: int = TOP_K) -> list[dict]:
    """Benchmark ranking, with mandatory gates/spacing even for small pools."""
    unique = {}
    for c in candidates:
        if not (32.0 <= c['face_width'] <= 44.0 and c['overhead_distortion_score'] <= 40.0):
            continue
        # First representation wins. A source frame cannot be re-submitted.
        unique.setdefault(c['frame_id'], c)
    ranked = sorted(unique.values(), key=lambda c: c['composite_quality'], reverse=True)
    spaced = []
    for c in ranked:
        if all(abs(c['frame_id'] - s['frame_id']) >= 2 for s in spaced):
            spaced.append(c)
        if len(spaced) >= top_k:
            break
    return spaced


def fuse_candidates(candidates: list[dict]) -> np.ndarray | None:
    """Exact benchmark F2 weights (image quality), followed by L2 normalization."""
    if not candidates:
        return None
    if len({c['frame_id'] for c in candidates}) != len(candidates):
        raise ValueError('DUPLICATE_SOURCE_FRAME')
    if len({(c['camera_id'], c['track_id']) for c in candidates}) != 1:
        raise ValueError('MIXED_SOURCE_TRACK')
    weights = [c['quality_score'] for c in candidates]
    w_sum = sum(weights) if sum(weights) > 0 else 1.0
    vec = np.sum([c['embedding'] * (w / w_sum) for c, w in zip(candidates, weights)], axis=0)
    norm = float(np.linalg.norm(vec))
    if not np.isfinite(vec).all() or not np.isfinite(norm) or norm < 1e-6:
        return None
    return np.asarray(vec / norm, dtype=np.float32)


class CandidateBuffer:
    """Bounded per-camera/per-track history; first representation per frame wins."""
    def __init__(self, camera_id: str, track_id: int, capacity: int = 64):
        self.key = (camera_id, track_id)
        self.capacity = capacity
        self.candidates: list[dict] = []
        self.last_frame_id = -1

    def add(self, candidate: dict) -> bool:
        if (candidate['camera_id'], candidate['track_id']) != self.key:
            raise ValueError('MIXED_SOURCE_TRACK')
        if candidate['frame_id'] <= self.last_frame_id:
            return False
        self.last_frame_id = candidate['frame_id']
        self.candidates.append(candidate)
        self.candidates[:] = self.candidates[-self.capacity:]
        return True

    def selected(self) -> list[dict]:
        return select_candidates(self.candidates)


class AdaptiveFacePipeline:
    """Post-SCRFD processing. No detector or identity/gallery input is accepted."""
    def __init__(self, embedder=None):
        if embedder is None:
            from src.face.experimental_adaface import AdaFaceEmbedder
            embedder = AdaFaceEmbedder.get_instance()
        self.embedder = embedder
        self.counters = Counter()
        self.last_observation: dict = {}

    def enroll_original(self, image):
        """One original-only enrollment vector; no synthetic gallery or live regeneration."""
        from src.face.face_embedder import face_embedder
        from insightface.utils import face_align
        self.last_enrollment_reason = 'NO_FACE_DETECTED'
        faces = face_embedder.detect_faces_in_roi(image, single_pass=True)
        if not faces:
            return None
        face = faces[0]
        valid, _ = face_embedder.validate_landmarks(face['kps'], face['bbox'])
        if not valid:
            self.last_enrollment_reason = 'INVALID_LANDMARKS'
            return None
        aligned = face_align.norm_crop(image, landmark=face['kps'], image_size=112)
        vector = self.embedder.embed_aligned_face(aligned)
        self.last_enrollment_reason = '' if self.valid_embedding(vector) else 'EMBEDDING_FAILED'
        return vector if self.valid_embedding(vector) else None

    def process(self, roi, bbox, score, kps, *, camera_id, track_id, frame_id, timestamp):
        from insightface.utils import face_align
        from src.recognition.target_matcher import calculate_face_frontality
        start = time.perf_counter()
        timings = dict(geometry=0.0, homography=0.0, alignment=0.0, adaface=0.0)
        record = dict(camera_id=camera_id, track_id=track_id, frame_id=frame_id,
                      timestamp=timestamp, representation_type='RAW', fallback_reason='',
                      accepted=False, timings=timings)
        self.last_observation = record
        self.counters['scrfd_valid_faces'] += 1
        try:
            t = time.perf_counter()
            if (roi is None or roi.ndim != 3 or min(roi.shape[:2]) < 10
                    or kps is None or np.asarray(kps).shape != (5, 2)
                    or not np.isfinite(kps).all() or not np.isfinite(bbox).all()
                    or not np.isfinite(roi).all()):
                record.update(representation_type='RAW_FALLBACK', fallback_reason='INVALID_INPUT')
                self.counters['homography_fallback'] += 1
                return None
            from src.face.face_embedder import FaceEmbedder
            valid, reason = FaceEmbedder.validate_landmarks(kps, bbox)
            if not valid:
                record.update(representation_type='RAW_FALLBACK', fallback_reason=reason)
                self.counters['candidate_rejected_geometry'] += 1
                return None
            geo = compute_geometry_and_overhead_score(kps, bbox, *roi.shape[:2])
            record.update(geometry=geo, face_width=float(bbox[2]-bbox[0]), scrfd_confidence=score,
                          overhead_distortion_score=geo['overhead_distortion_score'])
            if not all(np.isfinite(v) for v in geo.values()):
                self.counters['candidate_rejected_geometry'] += 1
                return None
            timings['geometry'] = (time.perf_counter()-t)*1000
            overhead = ((geo['overhead_distortion_score'] >= 8.0 or geo['aspect'] < 1.14)
                        and record['face_width'] >= 32.0 and score >= 0.50)
            chosen_roi, chosen_kps = roi, kps
            if overhead:
                self.counters['homography_attempts'] += 1
                t = time.perf_counter()
                chosen_roi, chosen_kps, safe, reason = apply_homography_with_safety(roi, kps, HOMOGRAPHY_ALPHA)
                timings['homography'] = (time.perf_counter()-t)*1000
                record['representation_type'] = 'RECTIFIED' if safe else 'RAW_FALLBACK'
                if safe:
                    self.counters['homography_success'] += 1
                else:
                    record['fallback_reason'] = reason
                    self.counters['homography_fallback'] += 1
            t = time.perf_counter()
            try:
                raw_aligned = face_align.norm_crop(roi, landmark=kps, image_size=112)
                if raw_aligned is None or not np.isfinite(raw_aligned).all():
                    raise ValueError('INVALID_RAW_ALIGNMENT')
            except Exception:
                record.update(representation_type='RAW_FALLBACK', fallback_reason='RAW_ALIGNMENT_FAILED')
                self.counters['candidate_rejected_quality'] += 1
                return None
            aligned = raw_aligned
            if record['representation_type'] == 'RECTIFIED':
                try:
                    aligned = face_align.norm_crop(chosen_roi, landmark=chosen_kps, image_size=112)
                    if aligned is None or aligned.shape != (112, 112, 3) or not np.isfinite(aligned).all():
                        raise ValueError('INVALID_RECTIFIED_ALIGNMENT')
                except Exception:
                    aligned = raw_aligned
                    record.update(representation_type='RAW_FALLBACK', fallback_reason='RECTIFIED_ALIGNMENT_FAILED')
                    self.counters['homography_fallback'] += 1
            timings['alignment'] = (time.perf_counter()-t)*1000
            # Exact benchmark quality: always measured on RAW alignment, before identity comparison.
            gray = cv2.cvtColor(raw_aligned, cv2.COLOR_BGR2GRAY)
            sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            frontality = calculate_face_frontality(kps)
            quality = float((score*0.35 + min(1.0, sharp/100.0)*0.35 + frontality*0.30)*100.0)
            record.update(sharpness=sharp, frontality=round(frontality, 3), image_quality=quality,
                          quality_score=round(quality, 2), composite_quality=round(quality*max(0.2, frontality), 2))
            if not (32.0 <= record['face_width'] <= 44.0 and geo['overhead_distortion_score'] <= 40.0):
                self.counters['candidate_rejected_geometry'] += 1
                return None
            t = time.perf_counter()
            embedding = self.embedder.embed_aligned_face(aligned)
            if not self.valid_embedding(embedding) and record['representation_type'] == 'RECTIFIED':
                record.update(representation_type='RAW_FALLBACK', fallback_reason='RECTIFIED_EMBEDDING_FAILED')
                self.counters['homography_fallback'] += 1
                embedding = self.embedder.embed_aligned_face(raw_aligned)
            timings['adaface'] = (time.perf_counter()-t)*1000
            if not self.valid_embedding(embedding):
                self.counters['candidate_rejected_quality'] += 1
                return None
            record.update(embedding=np.asarray(embedding, dtype=np.float32)/np.linalg.norm(embedding), accepted=True)
            self.counters['face_candidates_rectified' if record['representation_type']=='RECTIFIED' else 'face_candidates_raw'] += 1
            return record
        except Exception as exc:
            self.counters['exceptions'] += 1
            record['error_type'] = type(exc).__name__
            return None
        finally:
            timings['face_processing'] = (time.perf_counter()-start)*1000

    @staticmethod
    def valid_embedding(embedding):
        return (embedding is not None and np.asarray(embedding).shape == (512,)
                and np.isfinite(embedding).all() and np.linalg.norm(embedding) > 1e-6)
