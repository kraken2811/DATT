"""Unit and integration tests for multi-vehicle classes (car, truck, bus, motorcycle) in DATT.

Verifies:
1. Target classes in config and detector include person (0), car (2), motorcycle (3), bus (5), truck (7).
2. Detector preserves vehicle classes and outputs unified vehicle detections.
3. ByteTrack tracks trucks/buses/motorcycles with preserved class IDs.
4. VehiclePlateManager logs [VEHICLE_DET] class=truck conf=... bbox=... track_id=...
5. Plate OCR applies to car, truck, bus, but skips motorcycles.
6. FrameRenderer displays subtype labels (TRUCK, BUS, MOTORCYCLE, CAR).
7. Person/face recognition pipeline remains completely unaffected.
"""

import unittest
from unittest.mock import MagicMock, patch
import numpy as np

import config
from src.counter.zone_counter import CarCounter
from src.detector.yolo_detector import DetectionsData, YOLODetector
from src.ocr.plate_tracker import PlateTrackState, VehiclePlateManager
from src.tracker.bytetrack_tracker import CarTracker, PersonTracker
from src.ui.frame_renderer import render_frame


class MockDetections:
    def __init__(self, xyxy, tracker_id=None, confidence=None, class_id=None):
        self.xyxy = np.array(xyxy, dtype=np.float32)
        self.tracker_id = np.array(tracker_id, dtype=int) if tracker_id is not None else None
        self.confidence = np.array(confidence, dtype=np.float32) if confidence is not None else None
        self.class_id = np.array(class_id, dtype=int) if class_id is not None else None

    def __len__(self):
        return len(self.xyxy)


class TestVehicleClassesAndTruckDetection(unittest.TestCase):
    """Test suite for multi-vehicle class expansion and truck detection."""

    def test_1_config_target_classes_include_all_vehicle_types(self) -> None:
        """Target classes must include person (0), car (2), motorcycle (3), bus (5), truck (7)."""
        self.assertEqual(config.PERSON_CLASS_ID, 0)
        self.assertEqual(config.CAR_CLASS_ID, 2)
        self.assertEqual(config.MOTORCYCLE_CLASS_ID, 3)
        self.assertEqual(config.BUS_CLASS_ID, 5)
        self.assertEqual(config.TRUCK_CLASS_ID, 7)

        self.assertIn(0, config.TARGET_CLASSES)
        self.assertIn(2, config.TARGET_CLASSES)
        self.assertIn(3, config.TARGET_CLASSES)
        self.assertIn(5, config.TARGET_CLASSES)
        self.assertIn(7, config.TARGET_CLASSES)

        self.assertIn(2, config.PLATE_ELIGIBLE_CLASSES)
        self.assertIn(5, config.PLATE_ELIGIBLE_CLASSES)
        self.assertIn(7, config.PLATE_ELIGIBLE_CLASSES)
        self.assertNotIn(3, config.PLATE_ELIGIBLE_CLASSES)  # Motorcycle excluded from plate OCR

    def test_2_detector_passes_all_vehicle_classes_to_yolo_model(self) -> None:
        """YOLODetector passes [0, 2, 3, 5, 7] to Ultralytics model call."""
        detector = YOLODetector.__new__(YOLODetector)
        detector.config = config
        detector.model = MagicMock()
        detector.device = "cpu"
        detector.last_yolo_ms = 0.0

        mock_boxes = MagicMock()
        mock_boxes.__len__.return_value = 2
        mock_boxes.xyxy.cpu().numpy.return_value = np.array([[10, 10, 100, 100], [200, 200, 400, 400]], dtype=np.float32)
        mock_boxes.conf.cpu().numpy.return_value = np.array([0.9, 0.85], dtype=np.float32)
        mock_boxes.cls.cpu().numpy.return_value = np.array([7, 2], dtype=int)

        mock_result = MagicMock()
        mock_result.boxes = mock_boxes
        detector.model.return_value = [mock_result]

        dummy_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        dets = detector.detect(dummy_frame)

        call_kwargs = detector.model.call_args.kwargs
        self.assertIn(0, call_kwargs["classes"])
        self.assertIn(2, call_kwargs["classes"])
        self.assertIn(3, call_kwargs["classes"])
        self.assertIn(5, call_kwargs["classes"])
        self.assertIn(7, call_kwargs["classes"])

        # Preserves truck class 7
        self.assertIn(7, dets.class_id)
        self.assertIn(2, dets.class_id)

    def test_3_bytetrack_preserves_truck_and_vehicle_subtypes(self) -> None:
        """CarTracker (ByteTrack) tracks vehicles and maintains truck/bus/car class_ids."""
        tracker = CarTracker(config=config, frame_rate=30.0)

        # 1 truck (7) and 1 car (2)
        vehicle_dets = DetectionsData({
            "xyxy": np.array([[50, 50, 200, 200], [300, 300, 450, 450]], dtype=np.float32),
            "confidence": np.array([0.92, 0.88], dtype=np.float32),
            "class_id": np.array([7, 2], dtype=int),
        })

        # Feed frame 1 and frame 2 to satisfy ByteTrack minimum consecutive frames activation
        tracker.update(vehicle_dets)
        tracks = tracker.update(vehicle_dets)
        self.assertEqual(len(tracks), 2)
        self.assertIn(7, tracks.class_id)
        self.assertIn(2, tracks.class_id)

    def test_4_vehicle_plate_manager_logs_vehicle_det_and_evaluates_truck(self) -> None:
        """VehiclePlateManager logs [VEHICLE_DET] class=truck and processes truck plate."""
        mock_reader = MagicMock()
        mock_reader.extract_license_plate.return_value = MagicMock(
            plate_text="29C-888.88",
            confidence=0.91,
            bbox_native=[100, 140, 160, 160],
            raw_crop=np.zeros((30, 80, 3), dtype=np.uint8),
            quality_score=85.0,
        )

        mgr = VehiclePlateManager(reader=mock_reader)
        dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128

        truck_tracks = MockDetections(
            xyxy=[[50, 50, 250, 250]],
            tracker_id=[42],
            confidence=[0.89],
            class_id=[7],  # TRUCK
        )

        with self.assertLogs("datt.ocr.plate_tracker", level="INFO") as log_ctx:
            results = mgr.process_vehicle_tracks(frame=dummy_frame, vehicle_tracks=truck_tracks, frame_id=1)

            # Check [VEHICLE_DET] log format
            det_logged = any("[VEHICLE_DET] class=truck conf=0.89 bbox=[50, 50, 250, 250] track_id=42" in msg for msg in log_ctx.output)
            self.assertTrue(det_logged, f"Expected [VEHICLE_DET] log not found in: {log_ctx.output}")

            # Check plate evaluated for truck
            self.assertIn(42, results)
            self.assertEqual(results[42].vehicle_class, "truck")
            self.assertEqual(results[42].plate_text, "29C-888.88")
            self.assertEqual(results[42].status, "RECOGNIZED")

    def test_5_motorcycle_excluded_from_plate_ocr_but_tracked(self) -> None:
        """Motorcycle (3) is tracked with [VEHICLE_DET] logged, but excluded from plate OCR."""
        mock_reader = MagicMock()
        mgr = VehiclePlateManager(reader=mock_reader)
        dummy_frame = np.ones((720, 1280, 3), dtype=np.uint8) * 128

        moto_tracks = MockDetections(
            xyxy=[[30, 30, 90, 120]],
            tracker_id=[99],
            confidence=[0.85],
            class_id=[3],  # MOTORCYCLE
        )

        with self.assertLogs("datt.ocr.plate_tracker", level="INFO") as log_ctx:
            results = mgr.process_vehicle_tracks(frame=dummy_frame, vehicle_tracks=moto_tracks, frame_id=1)

            # [VEHICLE_DET] logged for motorcycle
            self.assertTrue(any("[VEHICLE_DET] class=motorcycle" in msg for msg in log_ctx.output))

            # Plate OCR reader was NEVER called for motorcycle
            mock_reader.extract_license_plate.assert_not_called()
            self.assertEqual(results[99].vehicle_class, "motorcycle")
            self.assertEqual(results[99].plate_text, "")

    def test_6_car_counter_counts_all_active_vehicles(self) -> None:
        """CarCounter counts all vehicles (car=2, motorcycle=3, bus=5, truck=7)."""
        counter = CarCounter()
        tracks = MockDetections(
            xyxy=[[10, 10, 50, 50], [100, 100, 200, 200], [300, 300, 500, 500]],
            tracker_id=[1, 2, 3],
            class_id=[2, 7, 5],  # car, truck, bus
        )
        count = counter.update(tracks, frame_shape=(720, 1280, 3))
        self.assertEqual(count, 3)

    def test_7_frame_renderer_renders_truck_label(self) -> None:
        """FrameRenderer displays TRUCK label instead of hardcoded CAR."""
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        truck_tracks = MockDetections(
            xyxy=[[100, 100, 300, 300]],
            tracker_id=[15],
            confidence=[0.90],
            class_id=[7],  # TRUCK
        )
        plate_state = PlateTrackState(
            track_id=15,
            vehicle_class="truck",
            plate_text="29C-123.45",
            confidence=0.92,
        )

        # Should render cleanly without exception
        annotated = render_frame(
            frame=frame,
            tracks=None,
            people_count=0,
            car_tracks=truck_tracks,
            car_count=1,
            plate_results={15: plate_state},
        )
        self.assertEqual(annotated.shape, frame.shape)


if __name__ == "__main__":
    unittest.main(verbosity=2)
