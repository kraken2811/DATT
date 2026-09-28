"""Unit and verification tests for the updated vehicle tracking overlay format.

Tests the requirement:
When a vehicle plate is CONFIRMED/RECOGNIZED:
Format: CLASS-ID | PLATE
Examples:
  - CAR-46 | 29K-104.25
  - MOTORCYCLE-12 | 24X1-124.42
  - TRUCK-8 | 29K-404.35

Rules:
- Use vehicle class + track_id + confirmed plate.
- Only display confirmed_plate / RECOGNIZED result.
- Do NOT display raw OCR candidates.
- Do NOT display unconfirmed CHECKING text as a real plate.
- If plate is not confirmed yet, keep the current tracking label without plate text.
- Preserve current bbox style, colors, confidence rendering, zone rendering, and tracking behavior.
"""

from pathlib import Path
import unittest

import cv2
import numpy as np

import config
from src.ocr.plate_tracker import PlateTrackState
from src.ui.frame_renderer import (
    format_plate_display,
    get_vehicle_track_label,
    render_frame,
)


class MockDetections:
    """Mock supervision.Detections container for testing."""

    def __init__(
        self,
        xyxy: np.ndarray,
        tracker_id: np.ndarray | None = None,
        confidence: np.ndarray | None = None,
        class_id: np.ndarray | None = None,
    ) -> None:
        self.xyxy = xyxy
        self.tracker_id = tracker_id
        self.confidence = confidence
        self.class_id = class_id

    def __len__(self) -> int:
        return len(self.xyxy)


class TestVehicleTrackingOverlayFormat(unittest.TestCase):
    """Test suite for vehicle tracking overlay format and presentation rules."""

    def test_format_plate_display_standard_vietnamese_plates(self) -> None:
        """Test standard 5-digit and 4-digit Vietnamese license plate display formatting."""
        # 5-digit civilian car plate
        self.assertEqual(format_plate_display("29K10425"), "29K-104.25")
        self.assertEqual(format_plate_display("29K-104.25"), "29K-104.25")
        self.assertEqual(format_plate_display("29k10425"), "29K-104.25")
        self.assertEqual(format_plate_display("29K 104.25"), "29K-104.25")

        # 5-digit motorcycle plate
        self.assertEqual(format_plate_display("24X112442"), "24X1-124.42")
        self.assertEqual(format_plate_display("24X1-124.42"), "24X1-124.42")
        self.assertEqual(format_plate_display("24X1\n12442"), "24X1-124.42")

        # 5-digit truck plate
        self.assertEqual(format_plate_display("29K40435"), "29K-404.35")
        self.assertEqual(format_plate_display("29K-404.35"), "29K-404.35")

        # 4-digit legacy civilian plate
        self.assertEqual(format_plate_display("29A1234"), "29A-1234")
        self.assertEqual(format_plate_display("29A-1234"), "29A-1234")

        # Empty / None
        self.assertEqual(format_plate_display(""), "")

    def test_get_vehicle_track_label_confirmed_car_motorcycle_truck(self) -> None:
        """Verify the required formats:
        CAR-46 | 29K-104.25
        MOTORCYCLE-12 | 24X1-124.42
        TRUCK-8 | 29K-404.35
        """
        # 1. Car track 46 with recognized plate
        label, is_conf = get_vehicle_track_label(
            v_type_str="CAR",
            track_id=46,
            conf=0.92,
            plate_text="29K10425",
            plate_status="RECOGNIZED",
        )
        self.assertTrue(is_conf)
        self.assertEqual(label, "CAR-46 | 29K-104.25")

        # 2. Motorcycle track 12 with recognized plate
        label, is_conf = get_vehicle_track_label(
            v_type_str="MOTORCYCLE",
            track_id=12,
            conf=0.88,
            plate_text="24X112442",
            plate_status="RECOGNIZED",
        )
        self.assertTrue(is_conf)
        self.assertEqual(label, "MOTORCYCLE-12 | 24X1-124.42")

        # 3. Truck track 8 with recognized plate
        label, is_conf = get_vehicle_track_label(
            v_type_str="TRUCK",
            track_id=8,
            conf=0.95,
            plate_text="29K40435",
            plate_status="RECOGNIZED",
        )
        self.assertTrue(is_conf)
        self.assertEqual(label, "TRUCK-8 | 29K-404.35")

    def test_unconfirmed_checking_plate_not_displayed(self) -> None:
        """Rule: Do NOT display raw OCR candidates or unconfirmed CHECKING text as a real plate.
        If plate is not confirmed yet, keep the current tracking label without plate text.
        """
        # Track 46 is currently in CHECKING state with a candidate
        label, is_conf = get_vehicle_track_label(
            v_type_str="CAR",
            track_id=46,
            conf=0.91,
            plate_text="29K10425",  # candidate or unconfirmed
            plate_status="CHECKING",
        )
        self.assertFalse(is_conf)
        self.assertNotIn("29K", label)
        self.assertNotIn("104.25", label)
        self.assertEqual(label, "CAR | C-46 | 0.91")

    def test_unconfirmed_searching_plate_not_displayed(self) -> None:
        """Rule: SEARCHING state keeps current tracking label without plate text."""
        label, is_conf = get_vehicle_track_label(
            v_type_str="MOTORCYCLE",
            track_id=12,
            conf=0.85,
            plate_text="",
            plate_status="SEARCHING",
        )
        self.assertFalse(is_conf)
        self.assertEqual(label, "MOTORCYCLE | C-12 | 0.85")

    def test_zone_prefix_preservation(self) -> None:
        """Rule: Preserve zone rendering when counting zone is enabled."""
        label, is_conf = get_vehicle_track_label(
            v_type_str="CAR",
            track_id=46,
            conf=0.92,
            plate_text="29K10425",
            plate_status="RECOGNIZED",
            zone_prefix="[ZONE] ",
        )
        self.assertTrue(is_conf)
        self.assertEqual(label, "[ZONE] CAR-46 | 29K-104.25")

        # Outside zone with confirmed plate
        label_out, is_conf_out = get_vehicle_track_label(
            v_type_str="CAR",
            track_id=46,
            conf=0.92,
            plate_text="29K10425",
            plate_status="RECOGNIZED",
            zone_prefix="[OUT] ",
        )
        self.assertTrue(is_conf_out)
        self.assertEqual(label_out, "[OUT] CAR-46 | 29K-104.25")

    def test_render_frame_with_confirmed_plate_draws_label_and_bbox(self) -> None:
        """Verify render_frame integration with PlateTrackState."""
        frame = np.full((720, 1280, 3), 40, dtype=np.uint8)
        car_box = np.array([[200.0, 200.0, 500.0, 500.0]], dtype=np.float32)
        car_tracks = MockDetections(
            xyxy=car_box,
            tracker_id=np.array([46]),
            confidence=np.array([0.94]),
            class_id=np.array([config.CAR_CLASS_ID]),
        )

        plate_state = PlateTrackState(
            track_id=46,
            vehicle_class="car",
            plate_text="29K10425",
            confidence=0.88,
            plate_bbox_native=(300, 420, 420, 460),
            status="RECOGNIZED",
        )

        rendered = render_frame(
            frame=frame,
            tracks=None,
            people_count=0,
            car_tracks=car_tracks,
            car_count=1,
            plate_results={46: plate_state},
        )

        self.assertIsNotNone(rendered)
        self.assertEqual(rendered.shape, frame.shape)
        # Frame was modified (plate box and overlay label rendered)
        self.assertFalse(np.array_equal(rendered, frame))


if __name__ == "__main__":
    unittest.main(verbosity=2)
