"""Unit and integration test suite for Vehicle License Plate OCR module in DATT.

Verifies:
1. License plate text cleaning and format validation.
2. Plate localization and OCR extraction on vehicle crop (never full frame).
3. Cadence control: Does not OCR every frame; fast retry on >20% bbox growth.
4. BestPlateState retention: Keeps best plate crop per track; worse candidate does not overwrite.
5. Bounded debug sample saving in scratch/plate_debug/.
6. FrameRenderer overlays plate_text and plate bbox on vehicle.
7. Track lifecycle: Expiration on TTL and reset on camera switch.
"""

from collections import namedtuple
import logging
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ocr.plate_reader import (
    LicensePlateReader,
    PlateCandidate,
    clean_plate_text,
    is_valid_plate_format,
)
from src.ocr.plate_tracker import PlateTrackState, VehiclePlateManager
from src.ui.frame_renderer import render_frame

MockDetections = namedtuple("MockDetections", ["xyxy", "tracker_id", "confidence"])


class TestPlateOCR(unittest.TestCase):
    """Test suite covering decoupled license plate OCR detection, tracking, and rendering."""

    def setUp(self) -> None:
        self.reader = LicensePlateReader(min_confidence=0.30)
        self.manager = VehiclePlateManager(reader=self.reader, eval_interval=5, ttl_frames=15)
        self.debug_dir = Path("scratch/plate_debug")

    def tearDown(self) -> None:
        self.manager.reset_tracks()

    def test_text_cleaning_and_validation(self) -> None:
        """Test sanitization and validity check for diverse license plate strings."""
        # Standard alphanumeric plates
        self.assertEqual(clean_plate_text("  29a-123.45  "), "29A-123.45")
        self.assertEqual(clean_plate_text("51G -- 888.88"), "51G-888.88")
        self.assertEqual(clean_plate_text("XYZ 789"), "XYZ-789")

        # 2-Tier Vietnamese plates (delimiters: slash, newline, spaces)
        self.assertEqual(clean_plate_text("29A / 123.45"), "29A-123.45")
        self.assertEqual(clean_plate_text("30G / 567.89"), "30G-567.89")
        self.assertEqual(clean_plate_text("29A\n123.45"), "29A-123.45")
        self.assertEqual(clean_plate_text("30G 567.89"), "30G-567.89")
        self.assertEqual(clean_plate_text("3OG / 567.89"), "30G-567.89")

        # Validation
        self.assertTrue(is_valid_plate_format("29A-123.45"))
        self.assertTrue(is_valid_plate_format("30G-567.89"))
        self.assertTrue(is_valid_plate_format("51G-8888"))
        self.assertTrue(is_valid_plate_format("7XYZ890"))

        # Invalid noise strings
        self.assertFalse(is_valid_plate_format("A"))
        self.assertFalse(is_valid_plate_format("----"))
        self.assertFalse(is_valid_plate_format("THIS_IS_WAY_TOO_LONG_FOR_A_PLATE"))

    def test_plate_extraction_on_synthetic_vehicle(self) -> None:
        """Test plate candidate extraction on a vehicle crop with OCR mock."""
        vehicle_crop = np.full((180, 240, 3), 60, dtype=np.uint8)
        # Draw license plate in lower half
        cv2.rectangle(vehicle_crop, (70, 110), (170, 150), (240, 240, 240), -1)
        cv2.rectangle(vehicle_crop, (70, 110), (170, 150), (10, 10, 10), 2)
        cv2.putText(vehicle_crop, "30E-1234", (75, 138), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

        native_bbox = [200, 150, 440, 330]

        # Mock OCR output from reader
        mock_ocr = [
            ([[70, 20], [170, 20], [170, 60], [70, 60]], "30E-1234", 0.88),
        ]
        mock_reader_obj = MagicMock()
        mock_reader_obj.readtext.return_value = mock_ocr
        self.reader._reader = mock_reader_obj
        self.reader._reader_initialized = True

        cand = self.reader.extract_license_plate(
            vehicle_crop=vehicle_crop,
            native_vehicle_bbox=native_bbox,
            track_id=1,
            frame_id=1,
        )

        self.assertIsNotNone(cand)
        self.assertEqual(cand.plate_text, "30E-1234")
        self.assertAlmostEqual(cand.confidence, 0.88, places=2)
        self.assertTrue(cand.bbox_native[0] >= 200)
        self.assertTrue(cand.bbox_native[1] >= 150)
        self.assertEqual(cand.raw_crop.shape[0] > 0, True)

    def test_two_tier_plate_grouping_29A_12345(self) -> None:
        """Requirement: Assemble 2-tier plate: 29A / 123.45 -> 29A-123.45."""
        vehicle_crop = np.full((250, 300, 3), 60, dtype=np.uint8)
        native_bbox = [100, 100, 400, 350]

        # EasyOCR returns 2 stacked text boxes in search ROI
        mock_ocr = [
            ([[40, 20], [110, 20], [110, 55], [40, 55]], "29A", 0.96),
            ([[20, 75], [130, 75], [130, 110], [20, 110]], "123.45", 0.98),
        ]
        mock_reader_obj = MagicMock()
        mock_reader_obj.readtext.return_value = mock_ocr
        self.reader._reader = mock_reader_obj
        self.reader._reader_initialized = True

        cand = self.reader.extract_license_plate(
            vehicle_crop=vehicle_crop,
            native_vehicle_bbox=native_bbox,
            track_id=1,
            frame_id=1,
        )

        self.assertIsNotNone(cand)
        self.assertEqual(cand.plate_text, "29A-123.45")
        self.assertAlmostEqual(cand.confidence, 0.97, places=2)
        # Bbox covers both lines
        self.assertTrue(cand.bbox_vehicle[3] > cand.bbox_vehicle[1] + 50)

    def test_two_tier_plate_grouping_30G_56789(self) -> None:
        """Requirement: Assemble 2-tier plate: 30G / 567.89 -> 30G-567.89."""
        vehicle_crop = np.full((250, 300, 3), 60, dtype=np.uint8)
        native_bbox = [100, 100, 400, 350]

        mock_ocr = [
            ([[45, 18], [115, 18], [115, 52], [45, 52]], "30G", 0.94),
            ([[22, 70], [138, 70], [138, 108], [22, 108]], "567.89", 0.99),
        ]
        mock_reader_obj = MagicMock()
        mock_reader_obj.readtext.return_value = mock_ocr
        self.reader._reader = mock_reader_obj
        self.reader._reader_initialized = True

        cand = self.reader.extract_license_plate(
            vehicle_crop=vehicle_crop,
            native_vehicle_bbox=native_bbox,
            track_id=2,
            frame_id=1,
        )

        self.assertIsNotNone(cand)
        self.assertEqual(cand.plate_text, "30G-567.89")
        self.assertAlmostEqual(cand.confidence, 0.965, places=2)

    def test_cadence_control_does_not_ocr_every_frame(self) -> None:
        """Requirement: Does not run OCR every frame; fast retries when vehicle moves closer."""
        frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
        car_box_1 = np.array([[200.0, 200.0, 350.0, 350.0]], dtype=np.float32)  # area = 150*150 = 22500
        tracks_1 = MockDetections(xyxy=car_box_1, tracker_id=np.array([5]), confidence=np.array([0.9]))

        mock_candidate = PlateCandidate(
            plate_text="51H-5678",
            confidence=0.85,
            bbox_vehicle=(30, 80, 120, 110),
            bbox_native=(230, 280, 320, 310),
            raw_crop=np.full((30, 90, 3), 255, dtype=np.uint8),
            preprocessed_crop=np.full((30, 90), 200, dtype=np.uint8),
            sharpness=80.0,
            quality_score=95.0,
        )

        with patch.object(self.reader, "extract_license_plate", return_value=mock_candidate) as mock_extract:
            # Frame 1: Initial evaluation -> runs OCR
            res1 = self.manager.process_vehicle_tracks(frame, tracks_1, frame_id=1)
            self.assertEqual(mock_extract.call_count, 1)
            self.assertEqual(res1[5].plate_text, "51H-5678")
            self.assertEqual(res1[5].status, "RECOGNIZED")

            # Frame 2: Same size, cadence not due -> OCR MUST NOT BE CALLED
            res2 = self.manager.process_vehicle_tracks(frame, tracks_1, frame_id=2)
            self.assertEqual(mock_extract.call_count, 1, "Must NOT OCR every frame")
            self.assertEqual(res2[5].plate_text, "51H-5678")

            # Frame 3: Same size -> still not called
            self.manager.process_vehicle_tracks(frame, tracks_1, frame_id=3)
            self.assertEqual(mock_extract.call_count, 1)

            # Frame 4: Fast retry triggered! Vehicle box grew > 20% (car approached camera)
            car_box_grown = np.array([[180.0, 180.0, 380.0, 380.0]], dtype=np.float32)  # 200x200 = 40000 (> 70% growth)
            tracks_grown = MockDetections(xyxy=car_box_grown, tracker_id=np.array([5]), confidence=np.array([0.92]))
            self.manager.process_vehicle_tracks(frame, tracks_grown, frame_id=4)
            self.assertEqual(mock_extract.call_count, 2, "Fast retry must trigger upon >20% bbox area growth")

    def test_best_plate_retention_per_track(self) -> None:
        """Requirement: Keeps best plate crop per track; worse candidate does not overwrite."""
        frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
        car_box = np.array([[200.0, 200.0, 350.0, 350.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=car_box, tracker_id=np.array([8]), confidence=np.array([0.9]))

        crop_good = np.full((35, 100, 3), 255, dtype=np.uint8)
        cand_good = PlateCandidate(
            plate_text="29B-9999",
            confidence=0.92,
            bbox_vehicle=(20, 70, 120, 105),
            bbox_native=(220, 270, 320, 305),
            raw_crop=crop_good,
            preprocessed_crop=np.full((35, 100), 200, dtype=np.uint8),
            sharpness=90.0,
            quality_score=110.0,
        )

        crop_bad = np.full((25, 70, 3), 120, dtype=np.uint8)
        cand_bad = PlateCandidate(
            plate_text="29B-9",
            confidence=0.40,
            bbox_vehicle=(25, 75, 95, 100),
            bbox_native=(225, 275, 295, 300),
            raw_crop=crop_bad,
            preprocessed_crop=np.full((25, 70), 100, dtype=np.uint8),
            sharpness=20.0,
            quality_score=35.0,
        )

        with patch.object(self.reader, "extract_license_plate", side_effect=[cand_good, cand_bad]):
            # Frame 1: Receives good candidate
            self.manager.process_vehicle_tracks(frame, tracks, frame_id=1)
            st = self.manager.get_plate_state(8)
            self.assertEqual(st.plate_text, "29B-9999")
            self.assertIs(st.plate_crop, crop_good)
            self.assertEqual(st.confidence, 0.92)

            # Frame 70: Cadence due, receives blurry/bad candidate
            self.manager.process_vehicle_tracks(frame, tracks, frame_id=70)
            st_after = self.manager.get_plate_state(8)
            # Must PRESERVE best plate!
            self.assertEqual(st_after.plate_text, "29B-9999", "Best plate text must not be overwritten by worse candidate")
            self.assertIs(st_after.plate_crop, crop_good, "Best plate crop must be preserved")
            self.assertEqual(st_after.confidence, 0.92)

    def test_debug_sample_saving(self) -> None:
        """Requirement: Saves bounded debug samples into scratch/plate_debug/."""
        if self.debug_dir.exists():
            shutil.rmtree(self.debug_dir)

        vehicle_crop = np.full((150, 200, 3), 80, dtype=np.uint8)
        plate_crop = np.full((30, 80, 3), 255, dtype=np.uint8)
        preprocessed = np.full((30, 80), 200, dtype=np.uint8)

        self.reader._save_debug_sample(
            vehicle_crop=vehicle_crop,
            plate_crop=plate_crop,
            preprocessed_crop=preprocessed,
            track_id=12,
            frame_id=1,
            plate_text="43A-1234",
            conf=0.91,
        )

        self.assertTrue(self.debug_dir.exists())
        saved_files = list(self.debug_dir.glob("f1_v12_*"))
        self.assertTrue(len(saved_files) >= 2)

    def test_frame_renderer_overlay_with_plate(self) -> None:
        """Requirement: Render plate_text and plate box onto video frame."""
        frame = np.full((720, 1280, 3), 50, dtype=np.uint8)
        car_box = np.array([[200.0, 200.0, 450.0, 450.0]], dtype=np.float32)
        car_tracks = MockDetections(xyxy=car_box, tracker_id=np.array([21]), confidence=np.array([0.95]))

        plate_state = PlateTrackState(
            track_id=21,
            plate_text="51F-12345",
            confidence=0.89,
            plate_bbox_native=(280, 380, 370, 415),
            status="RECOGNIZED",
        )
        plate_results = {21: plate_state}

        rendered = render_frame(
            frame=frame,
            tracks=None,
            people_count=0,
            car_tracks=car_tracks,
            car_count=1,
            plate_results=plate_results,
        )

        self.assertIsNotNone(rendered)
        self.assertEqual(rendered.shape, frame.shape)
        # Frame was modified (plate bounding box and label drawn)
        self.assertFalse(np.array_equal(rendered, frame))

    def test_manager_ttl_expiration_and_reset(self) -> None:
        """Requirement: Expire disappeared vehicles and reset on camera switch."""
        frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
        car_box = np.array([[100.0, 100.0, 200.0, 200.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=car_box, tracker_id=np.array([99]), confidence=np.array([0.9]))

        # Track 99 seen at frame 1
        with patch.object(self.reader, "extract_license_plate", return_value=None):
            self.manager.process_vehicle_tracks(frame, tracks, frame_id=1)
            self.assertIn(99, self.manager.get_all_plate_states())

            # Track disappeared for 20 frames (> ttl_frames=15)
            tracks_empty = MockDetections(xyxy=np.empty((0, 4)), tracker_id=np.array([]), confidence=np.array([]))
            self.manager.process_vehicle_tracks(frame, tracks_empty, frame_id=25)
            self.assertNotIn(99, self.manager.get_all_plate_states(), "Track must expire after TTL frames")

            # Reset clears all
            self.manager.process_vehicle_tracks(frame, tracks, frame_id=26)
            self.manager.reset_tracks()
            self.assertEqual(len(self.manager.get_all_plate_states()), 0)

    def test_real_easyocr_end_to_end_on_vehicle(self) -> None:
        """End-to-end integration test: Real EasyOCR model on synthetic vehicle with plate."""
        # 720x1280 frame with a car at [300, 200, 600, 480]
        frame = np.full((720, 1280, 3), 90, dtype=np.uint8)
        # Car body
        cv2.rectangle(frame, (300, 200), (600, 480), (40, 40, 40), -1)
        # License plate on the car (in lower region)
        cv2.rectangle(frame, (400, 380), (520, 430), (250, 250, 250), -1)
        cv2.rectangle(frame, (400, 380), (520, 430), (10, 10, 10), 2)
        cv2.putText(frame, "29A-1234", (405, 418), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        car_box = np.array([[300.0, 200.0, 600.0, 480.0]], dtype=np.float32)
        tracks = MockDetections(xyxy=car_box, tracker_id=np.array([42]), confidence=np.array([0.95]))

        # Real manager with real EasyOCR reader
        real_reader = LicensePlateReader(min_confidence=0.30)
        real_manager = VehiclePlateManager(reader=real_reader, eval_interval=5)

        results = real_manager.process_vehicle_tracks(frame, tracks, frame_id=1)
        self.assertIn(42, results)
        st = results[42]
        self.assertEqual(st.track_id, 42)
        self.assertTrue(len(st.plate_text) >= 3, f"Expected recognized plate, got '{st.plate_text}'")
        self.assertIn("29", st.plate_text)
        self.assertGreater(st.confidence, 0.3)
        self.assertIsNotNone(st.plate_crop)

        # Test overlay rendering
        rendered = render_frame(
            frame=frame,
            tracks=None,
            people_count=0,
            car_tracks=tracks,
            car_count=1,
            plate_results=results,
        )
        self.assertIsNotNone(rendered)

    def test_real_easyocr_on_two_tier_plate_29A_12345(self) -> None:
        """End-to-end integration: Real EasyOCR model reading 2-tier plate '29A / 123.45'."""
        vehicle = np.full((250, 300, 3), 80, dtype=np.uint8)
        plate_roi = vehicle[100:220, 80:220]
        cv2.rectangle(plate_roi, (0, 0), (139, 119), (255, 255, 255), -1)
        cv2.rectangle(plate_roi, (0, 0), (139, 119), (0, 0, 0), 2)
        cv2.putText(plate_roi, "29A", (35, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(plate_roi, "123.45", (15, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)

        cand = self.reader.extract_license_plate(
            vehicle_crop=vehicle,
            native_vehicle_bbox=[100, 100, 400, 350],
            track_id=10,
            frame_id=1,
        )

        self.assertIsNotNone(cand)
        self.assertEqual(cand.plate_text, "29A-123.45")
        self.assertGreater(cand.confidence, 0.5)

    def test_real_easyocr_on_two_tier_plate_30G_56789(self) -> None:
        """End-to-end integration: Real EasyOCR model reading 2-tier plate '30G / 567.89'."""
        vehicle = np.full((250, 300, 3), 80, dtype=np.uint8)
        plate_roi = vehicle[100:220, 80:220]
        cv2.rectangle(plate_roi, (0, 0), (139, 119), (255, 255, 255), -1)
        cv2.rectangle(plate_roi, (0, 0), (139, 119), (0, 0, 0), 2)
        cv2.putText(plate_roi, "30G", (35, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(plate_roi, "567.89", (15, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)

        cand = self.reader.extract_license_plate(
            vehicle_crop=vehicle,
            native_vehicle_bbox=[100, 100, 400, 350],
            track_id=11,
            frame_id=1,
        )

        self.assertIsNotNone(cand)
        self.assertEqual(cand.plate_text, "30G-567.89")
        self.assertGreater(cand.confidence, 0.5)

    def test_small_plate_adaptation(self) -> None:
        """Requirement: Small distant plate adaptive resize (height >= 64px, aspect ratio preserved)."""
        # Small plate: 22px height, 70px width (aspect ratio ~ 3.18)
        small_plate = np.full((22, 70, 3), 255, dtype=np.uint8)
        cv2.putText(small_plate, "51G", (5, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

        variants, meta = self.reader.generate_preprocessing_variants(small_plate)

        # 1. Scale factor must be > 2.0 to bring 22px up to >= 64px
        self.assertGreater(meta["scale"], 2.0)
        resized_img = variants["ORIGINAL/RESIZED"]
        self.assertGreaterEqual(resized_img.shape[0], 64)

        # 2. Aspect ratio must be preserved without distortion
        orig_aspect = 70.0 / 22.0
        resized_aspect = float(resized_img.shape[1]) / float(resized_img.shape[0])
        self.assertAlmostEqual(orig_aspect, resized_aspect, delta=0.1)

        # 3. All variants must have matching dimensions
        self.assertEqual(variants["ENHANCED_GRAY"].shape[:2], resized_img.shape[:2])
        self.assertEqual(variants["BINARIZED"].shape[:2], resized_img.shape[:2])

    def test_tilted_plate_deskew(self) -> None:
        """Requirement: Perspective correction / deskew if plate is tilted."""
        flat = np.full((60, 180, 3), 255, dtype=np.uint8)
        cv2.putText(flat, "30G-567.89", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        # Rotate plate by 12 degrees
        M = cv2.getRotationMatrix2D((90, 30), 12.0, 1.0)
        tilted = cv2.warpAffine(flat, M, (180, 60), borderMode=cv2.BORDER_REPLICATE)

        variants, meta = self.reader.generate_preprocessing_variants(tilted)

        # Tilt angle must be detected (~ -12.0 deg rotation needed to level plate)
        self.assertGreaterEqual(abs(meta["deskew"]), 10.0)
        self.assertLessEqual(abs(meta["deskew"]), 15.0)

        # Rectified image exists and differs from tilted input
        self.assertIsNotNone(meta["rectified"])
        self.assertFalse(np.array_equal(meta["rectified"], tilted))

    def test_dark_plate_gamma_enhancement(self) -> None:
        """Requirement: Gamma correction for underexposed/dark plates."""
        # Mean luminance < 50
        dark_plate = np.full((60, 180, 3), 35, dtype=np.uint8)
        cv2.putText(dark_plate, "29A-8888", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

        variants, meta = self.reader.generate_preprocessing_variants(dark_plate)

        # Input brightness accurately detected as dark (< 75)
        self.assertLess(meta["brightness"], 75.0)

        # Enhanced variant must have significantly boosted luminance
        enhanced_mean = float(np.mean(variants["ENHANCED_GRAY"]))
        self.assertGreater(enhanced_mean, meta["brightness"] + 20.0)

    def test_glare_plate_enhancement(self) -> None:
        """Requirement: Contrast and gamma handling for washed-out/glaring plates."""
        # Overexposed plate with mean luminance > 200
        glare_plate = np.full((60, 180, 3), 240, dtype=np.uint8)
        cv2.putText(glare_plate, "43A-1234", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (190, 190, 190), 2)

        variants, meta = self.reader.generate_preprocessing_variants(glare_plate)

        # Glare brightness detected (> 180)
        self.assertGreater(meta["brightness"], 180.0)

        # Contrast is recovered in enhanced/binary variants
        enhanced_gray = cv2.cvtColor(variants["ENHANCED_GRAY"], cv2.COLOR_BGR2GRAY) if len(variants["ENHANCED_GRAY"].shape) == 3 else variants["ENHANCED_GRAY"]
        self.assertGreater(float(np.std(enhanced_gray)), 5.0)

    def test_one_line_plate_preprocessing_and_ocr(self) -> None:
        """Requirement: Support 1-line plate without aspect-ratio distortion."""
        plate = np.full((55, 220, 3), 255, dtype=np.uint8)
        cv2.putText(plate, "30E-1234", (15, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 0, 0), 2)

        variants, meta = self.reader.generate_preprocessing_variants(plate)

        # 1-line elongated ratio preserved
        orig_ratio = 220.0 / 55.0
        resized_h, resized_w = variants["ORIGINAL/RESIZED"].shape[:2]
        self.assertAlmostEqual(resized_w / resized_h, orig_ratio, delta=0.1)

        cand = self.reader.extract_license_plate(
            vehicle_crop=plate,
            native_vehicle_bbox=[100, 100, 320, 155],
            track_id=15,
            frame_id=1,
        )
        self.assertIsNotNone(cand)
        self.assertIn("30E", cand.plate_text)
        self.assertGreater(cand.confidence, 0.5)

    def test_vietnamese_two_tier_plate_preprocessing_and_ocr(self) -> None:
        """Requirement: Support Vietnamese 2-tier plate (aspect ratio ~1.0-1.4, no horizontal distortion)."""
        plate_2t = np.full((120, 150, 3), 255, dtype=np.uint8)
        cv2.rectangle(plate_2t, (0, 0), (149, 119), (0, 0, 0), 2)
        cv2.putText(plate_2t, "29A", (35, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(plate_2t, "123.45", (15, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)

        variants, meta = self.reader.generate_preprocessing_variants(plate_2t)

        # 2-Tier aspect ratio (~ 1.25) preserved, NOT stretched into 1-line ratio
        orig_ratio = 150.0 / 120.0
        resized_h, resized_w = variants["ORIGINAL/RESIZED"].shape[:2]
        self.assertAlmostEqual(resized_w / resized_h, orig_ratio, delta=0.15)
        self.assertLess(resized_w / resized_h, 2.0)

        cand = self.reader.extract_license_plate(
            vehicle_crop=plate_2t,
            native_vehicle_bbox=[100, 100, 250, 220],
            track_id=16,
            frame_id=1,
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand.plate_text, "29A-123.45")
        self.assertGreater(cand.confidence, 0.5)

    def test_multi_variant_ocr_selection(self) -> None:
        """Requirement: EasyOCR runs on 3 variants and picks best based on confidence, validity, completeness."""
        variants = {
            "ORIGINAL/RESIZED": np.full((64, 180, 3), 255, dtype=np.uint8),
            "ENHANCED_GRAY": np.full((64, 180, 3), 200, dtype=np.uint8),
            "BINARIZED": np.full((64, 180, 3), 0, dtype=np.uint8),
        }

        # Mock EasyOCR returning different results per variant
        # ORIGINAL/RESIZED gives partial text with low conf
        # ENHANCED_GRAY gives complete valid text with high conf
        # BINARIZED gives incomplete noise
        def mock_readtext_side_effect(img):
            mean_val = np.mean(img)
            if mean_val > 220: # ORIGINAL
                return [([[10, 10], [50, 10], [50, 40], [10, 40]], "29A", 0.45)]
            elif mean_val > 100: # ENHANCED_GRAY
                return [([[10, 10], [170, 10], [170, 40], [10, 40]], "29A-123.45", 0.95)]
            else: # BINARIZED
                return [([[10, 10], [60, 10], [60, 40], [10, 40]], "...", 0.10)]

        mock_reader = MagicMock()
        mock_reader.readtext.side_effect = mock_readtext_side_effect
        with patch.object(self.reader, "_reader", mock_reader):
            v_selected, best_text, best_conf, best_img = self.reader.evaluate_variants(variants)
            self.assertEqual(v_selected, "ENHANCED_GRAY")
            self.assertEqual(best_text, "29A-123.45")
            self.assertAlmostEqual(best_conf, 0.95, places=2)

    def test_plate_preprocess_logging_and_debug_files(self) -> None:
        """Requirement: Emits structured [PLATE_PREPROCESS] log and saves bounded debug files."""
        # Capture logger output
        log_records: list[str] = []

        class ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_records.append(self.format(record))

        ocr_logger = logging.getLogger("datt.ocr.plate_reader")
        handler = ListHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        ocr_logger.addHandler(handler)
        ocr_logger.setLevel(logging.INFO)

        try:
            plate = np.full((60, 180, 3), 255, dtype=np.uint8)
            cv2.putText(plate, "30G-567.89", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)

            cand = self.reader.extract_license_plate(
                vehicle_crop=plate,
                native_vehicle_bbox=[50, 50, 230, 110],
                track_id=88,
                frame_id=1,
            )
            self.assertIsNotNone(cand)

            # 1. Check structured log
            preprocess_logs = [r for r in log_records if "[PLATE_PREPROCESS]" in r]
            self.assertGreater(len(preprocess_logs), 0, "Must emit [PLATE_PREPROCESS] log")
            log_line = preprocess_logs[0]
            required_keys = [
                "track_id=",
                "plate_size=",
                "deskew=",
                "brightness=",
                "contrast=",
                "scale=",
                "variant_selected=",
                "ocr_conf=",
                "plate_text=",
            ]
            for key in required_keys:
                self.assertIn(key, log_line, f"Log missing required field: {key}")

            # 2. Check bounded debug files in scratch/plate_debug/
            self.assertTrue(self.debug_dir.exists())
            self.assertTrue((self.debug_dir / "plate_original.jpg").exists())
            self.assertTrue((self.debug_dir / "plate_rectified.jpg").exists())
            self.assertTrue((self.debug_dir / "plate_enhanced.jpg").exists())
            self.assertTrue((self.debug_dir / "plate_binary.jpg").exists())
        finally:
            ocr_logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()

