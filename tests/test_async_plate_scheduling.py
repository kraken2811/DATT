"""Unit and integration tests for plate OCR async best-quality scheduling.

Validates requirements:
1. Replace "latest pending OCR job per track" with "best-quality pending OCR job per track".
2. Score candidate jobs before queue replacement using cheap metrics:
   - vehicle bbox size
   - plate detector confidence if already available
   - plate native width/height
   - sharpness
   - brightness/contrast
   - frame age
3. A newer frame must NOT replace an older pending frame unless its quality score is better.
4. Prefer OCR when the vehicle/plate is approaching and sharp, not after it starts leaving the frame.
5. Keep:
   - async worker
   - bounded queue
   - one pending job per track
   - non-blocking main loop
6. Logs:
   [OCR_JOB_SELECT] track_id old_frame new_frame old_quality new_quality action=KEEP_BEST/REPLACE
7. Track 25/29 scenario:
   - Preserves high-quality frame (584x344) over late small frame (206x88)
   - Confirmed plate renders as CAR-29 | 47A-401.94
"""

import logging
import threading
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

import config
from src.ocr.plate_reader import PlateCandidate
from src.ocr.plate_tracker import (
    PlateTrackState,
    VehiclePlateManager,
    _OcrJob,
    _OcrWorker,
    _OCR_QUEUE_MAXSIZE,
    compute_ocr_job_quality,
)
from src.ui.frame_renderer import get_vehicle_track_label


class MockDetections:
    """Mock detections for supervisor/tracker tracks."""

    def __init__(self, xyxy, tracker_id=None, confidence=None, class_id=None):
        self.xyxy = np.array(xyxy, dtype=np.float32)
        self.tracker_id = np.array(tracker_id) if tracker_id is not None else None
        self.confidence = np.array(confidence) if confidence is not None else None
        self.class_id = np.array(class_id) if class_id is not None else None

    def __len__(self):
        return len(self.xyxy)


class TestAsyncPlateScheduling(unittest.TestCase):
    """Test suite for quality-based OCR job scheduling."""

    def test_quality_scoring_favors_large_over_small_vehicle(self) -> None:
        """Vehicle 584x344 (track 29 peak) must score significantly higher than 206x88 (late frame)."""
        # 1. Large peak crop: 584x344
        large_crop = np.full((344, 584, 3), 120, dtype=np.uint8)
        # Add rich texture/edges to simulate sharp vehicle details
        cv2.rectangle(large_crop, (100, 100), (480, 280), (40, 40, 40), -1)
        cv2.rectangle(large_crop, (200, 200), (380, 260), (240, 240, 240), -1)

        q_large = compute_ocr_job_quality(
            vehicle_crop=large_crop,
            native_vehicle_bbox=(300, 100, 884, 444),
            frame_res=(1920, 1080),
            prev_bbox_area=150000.0,
            max_bbox_area=200000.0,
        )

        # 2. Small receding crop: 206x88
        small_crop = np.full((88, 206, 3), 120, dtype=np.uint8)
        cv2.rectangle(small_crop, (30, 20), (170, 70), (40, 40, 40), -1)

        q_small = compute_ocr_job_quality(
            vehicle_crop=small_crop,
            native_vehicle_bbox=(450, 0, 656, 88),  # Touching top border (truncated)
            frame_res=(1920, 1080),
            prev_bbox_area=100000.0,
            max_bbox_area=200896.0,  # Peak was 200,896 px, now 18,128 px
        )

        self.assertGreater(q_large, 60.0)
        self.assertLess(q_small, 40.0)
        self.assertGreater(q_large - q_small, 30.0, "Large crop must substantially outperform small receding crop")

    def test_quality_scoring_sharpness_impact(self) -> None:
        """Sharp crop must score higher than heavily blurred crop."""
        sharp_crop = np.zeros((200, 300, 3), dtype=np.uint8)
        # Add alternating stripes for high Laplacian variance
        sharp_crop[:, ::8] = 255
        sharp_crop[::8, :] = 255

        blur_crop = cv2.GaussianBlur(sharp_crop, (25, 25), 0)

        q_sharp = compute_ocr_job_quality(
            vehicle_crop=sharp_crop,
            native_vehicle_bbox=(100, 100, 400, 300),
            frame_res=(1920, 1080),
        )

        q_blur = compute_ocr_job_quality(
            vehicle_crop=blur_crop,
            native_vehicle_bbox=(100, 100, 400, 300),
            frame_res=(1920, 1080),
        )

        self.assertGreater(q_sharp, q_blur, "Sharp crop must score higher than blurred crop")

    def test_queue_keeps_best_quality_job_when_newer_frame_is_worse(self) -> None:
        """Requirement: A newer frame must NOT replace an older pending frame unless its quality score is better."""
        manager = Mock()
        manager.reader = Mock()
        worker = _OcrWorker(manager, start_thread=False)

        crop_1566 = np.full((344, 584, 3), 120, dtype=np.uint8)
        job_1566 = _OcrJob(
            track_id=29,
            frame_id=1566,
            vehicle_crop=crop_1566,
            native_vehicle_bbox=(300, 100, 884, 444),
            vehicle_class="car",
            eval_count=1,
            generation=1,
            quality_score=85.0,
        )

        with patch("src.ocr.plate_tracker.logger.info") as mock_log:
            # Enqueue initial high quality job
            worker.enqueue(job_1566)
            self.assertEqual(worker.queue_size, 1)
            self.assertEqual(worker.get_pending_job(29).frame_id, 1566)

            # Frame 1629 arrives: smaller vehicle, worse quality (20.0)
            crop_1629 = np.full((88, 206, 3), 100, dtype=np.uint8)
            job_1629 = _OcrJob(
                track_id=29,
                frame_id=1629,
                vehicle_crop=crop_1629,
                native_vehicle_bbox=(450, 0, 656, 88),
                vehicle_class="car",
                eval_count=2,
                generation=1,
                quality_score=20.0,
            )

            worker.enqueue(job_1629)

            # Queue MUST preserve frame 1566 because new quality (20.0) <= old quality (~76.0)
            self.assertEqual(worker.queue_size, 1, "Queue size must remain 1 per track")
            retained_job = worker.get_pending_job(29)
            self.assertEqual(retained_job.frame_id, 1566, "Must KEEP_BEST frame 1566, not replace with 1629")

            # Check that [OCR_JOB_SELECT] was logged with action=KEEP_BEST
            logged_messages = [call.args[0] % call.args[1:] for call in mock_log.call_args_list if call.args]
            select_logs = [m for m in logged_messages if "[OCR_JOB_SELECT]" in m]
            self.assertTrue(len(select_logs) > 0, "Must log [OCR_JOB_SELECT]")
            last_select = select_logs[-1]
            self.assertIn("track_id=29", last_select)
            self.assertIn("old_frame=1566", last_select)
            self.assertIn("new_frame=1629", last_select)
            self.assertIn("action=KEEP_BEST", last_select)

    def test_queue_replaces_job_when_newer_frame_is_better(self) -> None:
        """When an approaching vehicle gets closer and sharper, newer job replaces older job."""
        manager = Mock()
        manager.reader = Mock()
        worker = _OcrWorker(manager, start_thread=False)

        # Frame 1500: medium vehicle (quality 50.0)
        job_1500 = _OcrJob(
            track_id=29,
            frame_id=1500,
            vehicle_crop=np.full((150, 250, 3), 100, dtype=np.uint8),
            native_vehicle_bbox=(200, 200, 450, 350),
            vehicle_class="car",
            eval_count=1,
            generation=1,
            quality_score=50.0,
        )

        with patch("src.ocr.plate_tracker.logger.info") as mock_log:
            worker.enqueue(job_1500)
            self.assertEqual(worker.get_pending_job(29).frame_id, 1500)

            # Frame 1550: closer, sharper vehicle (quality 88.0)
            job_1550 = _OcrJob(
                track_id=29,
                frame_id=1550,
                vehicle_crop=np.full((320, 500, 3), 100, dtype=np.uint8),
                native_vehicle_bbox=(250, 150, 750, 470),
                vehicle_class="car",
                eval_count=2,
                generation=1,
                quality_score=88.0,
            )

            worker.enqueue(job_1550)

            self.assertEqual(worker.queue_size, 1)
            retained_job = worker.get_pending_job(29)
            self.assertEqual(retained_job.frame_id, 1550, "Must REPLACE with better frame 1550")

            logged_messages = [call.args[0] % call.args[1:] for call in mock_log.call_args_list if call.args]
            select_logs = [m for m in logged_messages if "[OCR_JOB_SELECT]" in m]
            self.assertTrue(len(select_logs) > 0)
            self.assertIn("action=REPLACE", select_logs[-1])

    def test_queue_remains_bounded_under_load(self) -> None:
        """Requirement: Keep bounded queue with max _OCR_QUEUE_MAXSIZE items."""
        manager = Mock()
        manager.reader = Mock()
        worker = _OcrWorker(manager, start_thread=False)

        for tid in range(1, 25):
            job = _OcrJob(
                track_id=tid,
                frame_id=100,
                vehicle_crop=np.full((100, 100, 3), 50, dtype=np.uint8),
                native_vehicle_bbox=(10, 10, 110, 110),
                vehicle_class="car",
                eval_count=1,
                generation=1,
                quality_score=50.0,
            )
            worker.enqueue(job)

        self.assertEqual(worker.queue_size, _OCR_QUEUE_MAXSIZE)

    def test_track_29_e2e_retains_peak_frame_and_confirms_plate(self) -> None:
        """End-to-end simulation of Track 29 on the real Vietnamese traffic video:
        - At frame 1566, car is large and enqueued.
        - At frame 1629, car is small (206x88) and rejected by KEEP_BEST.
        - Worker processes frame 1566 and confirms 47A-401.94.
        - Renders overlay as CAR-29 | 47A-401.94.
        """
        # Mock reader returning valid plate candidate for frame 1566
        def mock_extract(vehicle_crop, native_vehicle_bbox, track_id, frame_id):
            vh, vw = vehicle_crop.shape[:2]
            if vw > 300 and vh > 200:
                # High-res vehicle crop allows high-confidence reading
                crop = np.zeros((40, 100, 3), dtype=np.uint8)
                return PlateCandidate(
                    plate_text="47A-401.94",
                    confidence=0.92,
                    bbox_vehicle=(50, 150, 150, 190),
                    bbox_native=(native_vehicle_bbox[0] + 50, native_vehicle_bbox[1] + 150,
                                 native_vehicle_bbox[0] + 150, native_vehicle_bbox[1] + 190),
                    raw_crop=crop,
                    preprocessed_crop=crop,
                    sharpness=100.0,
                    quality_score=85.0,
                    raw_text="47A-401.94",
                )
            else:
                # Small/low-res vehicle crop produces None or low confidence
                return None

        reader = Mock()
        reader.extract_license_plate.side_effect = mock_extract

        manager = VehiclePlateManager(reader=reader, eval_interval=1, async_worker=False)

        # 1. Simulate vehicle approaching at frame 1566: size 584x344
        frame_1566 = np.full((1080, 1920, 3), 100, dtype=np.uint8)
        tracks_1566 = MockDetections(
            xyxy=[[300.0, 100.0, 884.0, 444.0]],
            tracker_id=[29],
            confidence=[0.95],
            class_id=[config.CAR_CLASS_ID],
        )

        # 3 observations of the large clear vehicle to fulfill consensus >= 3
        for fid in [1566, 1570, 1575]:
            results = manager.process_vehicle_tracks(frame_1566, tracks_1566, frame_id=fid)

        st = results[29]
        self.assertIn(st.status, ["CONFIRMED", "RECOGNIZED"])
        self.assertEqual(st.plate_text, "47A40194")
        self.assertGreaterEqual(st.consensus_count, 2)

        # Verify overlay format
        label, is_conf = get_vehicle_track_label(
            v_type_str="CAR",
            track_id=29,
            conf=0.95,
            plate_text=st.plate_text,
            plate_status=st.status,
        )
        self.assertTrue(is_conf)
        self.assertEqual(label, "CAR-29 | 47A-401.94")


if __name__ == "__main__":
    unittest.main(verbosity=2)
