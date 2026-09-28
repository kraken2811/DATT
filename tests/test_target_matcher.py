"""Unit tests for Target Registration, Color Extraction, and ByteTrack Target Association.

Tests:
- TEST 6: Register target with clothing color only.
- TEST 7: Register target with face image only.
- TEST 8: Register target with both face image and clothing color.
- TEST 9: Upload image without face is rejected with ValueError.
- TEST 10: Matcher handles invalid person crops, out-of-bounds bboxes, empty frames without crash.
- TEST 11: Target is associated with ByteTrack track_id and maintained across frames.
- TEST 12: Association is cleaned up when track expires (TTL exceeded).
- Torso Color Extraction test: verifies basic color classification in HSV space.
- Combined Matching Logic: when both face and color are required, color alone must NOT match.
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.face.face_embedder import cosine_similarity
from src.recognition.color_extractor import ClothingColorExtractor
from src.recognition.target_matcher import (
    Target,
    TargetManager,
    TargetMatcher,
)


class MockDetections:
    """Mock for supervision.Detections."""
    def __init__(self, xyxy: np.ndarray, tracker_id: np.ndarray, confidence: np.ndarray | None = None) -> None:
        self.xyxy = xyxy
        self.tracker_id = tracker_id
        self.confidence = confidence if confidence is not None else np.ones(len(xyxy), dtype=np.float32)


class TestTargetMatcher(unittest.TestCase):
    """Test suite for TargetManager, TargetMatcher, and ColorExtractor."""

    def setUp(self) -> None:
        self.manager = TargetManager()
        self.matcher = TargetMatcher(manager=self.manager, re_eval_interval=5, ttl_frames=10)

    def test_register_target_color_only(self) -> None:
        """TEST 6: Register target with clothing color only."""
        target = self.manager.register_target(name="Bob Red", clothing_color="red")
        self.assertEqual(target.name, "Bob Red")
        self.assertEqual(target.clothing_color, "red")
        self.assertFalse(target.has_face)
        self.assertIsNone(target.face_embedding)

    def test_register_target_face_only(self) -> None:
        """TEST 7: Register target with face image only."""
        mock_embedding = np.random.randn(512).astype(np.float32)
        mock_embedding /= np.linalg.norm(mock_embedding)

        with patch("src.recognition.target_matcher.face_embedder.extract_face_embedding", return_value=mock_embedding):
            dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 128
            target = self.manager.register_target(name="Alice Face", face_image=dummy_img)

            self.assertEqual(target.name, "Alice Face")
            self.assertTrue(target.has_face)
            self.assertIsNotNone(target.face_embedding)
            self.assertIsNone(target.clothing_color)

    def test_register_target_face_and_color(self) -> None:
        """TEST 8: Register target with both face image and clothing color."""
        mock_embedding = np.random.randn(512).astype(np.float32)
        mock_embedding /= np.linalg.norm(mock_embedding)

        with patch("src.recognition.target_matcher.face_embedder.extract_face_embedding", return_value=mock_embedding):
            dummy_img = np.ones((100, 100, 3), dtype=np.uint8) * 128
            target = self.manager.register_target(
                name="Charlie Both",
                face_image=dummy_img,
                clothing_color="blue",
                face_threshold=0.5,
            )

            self.assertEqual(target.name, "Charlie Both")
            self.assertTrue(target.has_face)
            self.assertEqual(target.clothing_color, "blue")
            self.assertEqual(target.face_threshold, 0.5)

    def test_register_target_no_attributes_rejected(self) -> None:
        """TEST 9: Registering target without face and without color raises ValueError."""
        with self.assertRaises(ValueError):
            self.manager.register_target(name="No Feature")

        # Also when uploaded image has no detectable face
        with patch("src.recognition.target_matcher.face_embedder.extract_face_embedding", return_value=None):
            blank_img = np.zeros((100, 100, 3), dtype=np.uint8)
            with self.assertRaises(ValueError) as ctx:
                self.manager.register_target(name="Blank Face", face_image=blank_img)
            self.assertIn("Could not detect a valid human face", str(ctx.exception))

    def test_clothing_color_extraction_hsv(self) -> None:
        """Verify clothing color extraction on synthetic colored person crop."""
        extractor = ClothingColorExtractor(min_valid_pixels=20)
        # Create a 200x100 frame with a BLUE person box
        frame = np.zeros((200, 100, 3), dtype=np.uint8)
        # Fill person area with pure Blue in BGR: (255, 0, 0)
        frame[20:180, 20:80] = (255, 0, 0)

        res = extractor.extract_clothing_color(frame, (20, 20, 80, 180))
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.dominant_color, "blue")
        self.assertGreater(res.confidence, 0.8)

        # Test RED person box in BGR: (0, 0, 255)
        frame_red = np.zeros((200, 100, 3), dtype=np.uint8)
        frame_red[20:180, 20:80] = (0, 0, 255)
        res_red = extractor.extract_clothing_color(frame_red, (20, 20, 80, 180))
        self.assertIsNotNone(res_red)
        assert res_red is not None
        self.assertEqual(res_red.dominant_color, "red")

    def test_matcher_robust_to_invalid_crops(self) -> None:
        """TEST 10: Matcher does not crash on empty crops or out-of-bound bboxes."""
        self.manager.register_target(name="Test Target", clothing_color="red")
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        # 1. Negative / out-of-bounds coordinates
        tracks_oob = MockDetections(
            xyxy=np.array([[-50, -50, -10, -10], [200, 200, 300, 300]]),
            tracker_id=np.array([1, 2]),
        )
        matches = self.matcher.match_tracks(frame, tracks_oob, frame_id=1)
        self.assertEqual(len(matches), 0)

        # 2. Inverted coordinates
        tracks_inv = MockDetections(
            xyxy=np.array([[50, 50, 20, 20]]),
            tracker_id=np.array([3]),
        )
        matches = self.matcher.match_tracks(frame, tracks_inv, frame_id=2)
        self.assertEqual(len(matches), 0)

        # 3. None / empty frame
        matches = self.matcher.match_tracks(None, tracks_inv, frame_id=3)
        self.assertEqual(len(matches), 0)

    def test_target_association_with_bytetrack_id(self) -> None:
        """TEST 11: Target is associated with track_id and maintained across frames."""
        self.manager.register_target(name="Agent Smith", clothing_color="black")
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        # Black person box
        frame[50:250, 50:150] = (10, 10, 10)

        tracks = MockDetections(
            xyxy=np.array([[50, 50, 150, 250]]),
            tracker_id=np.array([42]),
        )

        # Frame 1: Initial evaluation
        matches1 = self.matcher.match_tracks(frame, tracks, frame_id=1)
        self.assertIn(42, matches1)
        self.assertEqual(matches1[42].target_name, "Agent Smith")
        self.assertEqual(matches1[42].match_type, "COLOR_MATCH")

        # Frame 2: Cache hit (before re_eval_interval)
        matches2 = self.matcher.match_tracks(frame, tracks, frame_id=2)
        self.assertIn(42, matches2)
        self.assertEqual(matches2[42].target_name, "Agent Smith")

    def test_track_association_cleanup_on_ttl(self) -> None:
        """TEST 12: Association is cleaned up when track exceeds TTL."""
        self.manager.register_target(name="Ghost", clothing_color="black")
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        frame[50:250, 50:150] = (10, 10, 10)

        tracks = MockDetections(
            xyxy=np.array([[50, 50, 150, 250]]),
            tracker_id=np.array([99]),
        )

        # Track 99 seen at frame 1
        matches = self.matcher.match_tracks(frame, tracks, frame_id=1)
        self.assertIn(99, matches)

        # Track 99 disappears. Later, another track appears at frame 20 (> ttl_frames=10)
        tracks_new = MockDetections(
            xyxy=np.array([[10, 10, 40, 80]]),
            tracker_id=np.array([101]),
        )
        self.matcher.match_tracks(frame, tracks_new, frame_id=20)

        # Track 99 must be evicted from internal cache
        with self.matcher._lock:
            self.assertNotIn(99, self.matcher._matched_tracks)
            self.assertNotIn(99, self.matcher._track_last_seen)

    def test_combined_rule_no_false_match_when_face_missing(self) -> None:
        """Crucial Rule: If target has FACE + COLOR, but person crop has NO FACE, it must NOT match!"""
        mock_embedding = np.random.randn(512).astype(np.float32)
        mock_embedding /= np.linalg.norm(mock_embedding)

        # Register target with Face + Blue color
        with patch("src.recognition.target_matcher.face_embedder.extract_face_embedding", return_value=mock_embedding):
            self.manager.register_target(name="VIP", face_image=np.ones((50, 50, 3), dtype=np.uint8), clothing_color="blue")

        # Frame has BLUE clothing, but face extractor returns None (person facing away / no face)
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        frame[50:250, 50:150] = (255, 0, 0)  # Blue

        tracks = MockDetections(
            xyxy=np.array([[50, 50, 150, 250]]),
            tracker_id=np.array([7]),
        )

        with patch("src.recognition.target_matcher.face_embedder.extract_face_embedding", return_value=None):
            matches = self.matcher.match_tracks(frame, tracks, frame_id=1)
            # MUST NOT MATCH just because clothing is blue!
            self.assertNotIn(7, matches)

    def test_cosine_similarity_edge_cases(self) -> None:
        """Verify cosine_similarity handles zero norms, NaNs, and negative vectors safely."""
        # Exact match
        v = np.array([1.0, 0.0, 0.0])
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0, places=5)

        # Orthogonal
        v2 = np.array([0.0, 1.0, 0.0])
        self.assertAlmostEqual(cosine_similarity(v, v2), 0.0, places=5)

        # Zero norm
        zeros = np.zeros(3)
        self.assertEqual(cosine_similarity(v, zeros), 0.0)

        # NaN guard
        with_nan = np.array([np.nan, 1.0, 0.0])
        self.assertEqual(cosine_similarity(v, with_nan), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
