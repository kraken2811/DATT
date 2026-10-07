"""Comprehensive test suite for VehicleEvent persistence, HSV color extraction, and PlateEvent linkage."""

from datetime import datetime, timezone
import os
from pathlib import Path
import time
import tempfile
from unittest.mock import patch
from uuid import UUID, uuid4
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.db.database import Database
from src.db.models import PlateEvent, VehicleEvent, VehiclePassage
from src.db.repositories import (
    DetectionEventRepository,
    PlateEventRepository,
    VehicleEventRepository,
    VehiclePassageRepository,
)
from src.events.db_worker import DatabaseWorker
from src.events.event_dto import VehiclePassageDTO
from src.events.event_manager import EventManager
from src.recognition.color_extractor import extract_vehicle_color, VEHICLE_COLOR_NAMES

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestVehicleColorExtraction:
    """Unit tests for HSV lightweight vehicle color extraction."""

    def test_color_names_specification(self) -> None:
        """Verify all 8 required colors are supported."""
        expected = {
            "white",
            "black",
            "gray/silver",
            "red",
            "blue",
            "green",
            "yellow",
            "other/unknown",
        }
        assert set(VEHICLE_COLOR_NAMES) == expected

    def test_white_vehicle_crop(self) -> None:
        crop = np.ones((100, 100, 3), dtype=np.uint8) * 245
        assert extract_vehicle_color(crop) == "white"

    def test_black_vehicle_crop(self) -> None:
        crop = np.ones((100, 100, 3), dtype=np.uint8) * 20
        assert extract_vehicle_color(crop) == "black"

    def test_gray_silver_vehicle_crop(self) -> None:
        crop = np.ones((100, 100, 3), dtype=np.uint8) * 130
        assert extract_vehicle_color(crop) == "gray/silver"

    def test_red_vehicle_crop(self) -> None:
        # BGR: Red is [0, 0, 255]
        crop = np.zeros((100, 100, 3), dtype=np.uint8)
        crop[:, :] = [0, 0, 220]
        assert extract_vehicle_color(crop) == "red"

    def test_blue_vehicle_crop(self) -> None:
        # BGR: Blue is [255, 0, 0]
        crop = np.zeros((100, 100, 3), dtype=np.uint8)
        crop[:, :] = [220, 0, 0]
        assert extract_vehicle_color(crop) == "blue"

    def test_green_vehicle_crop(self) -> None:
        # BGR: Green is [0, 255, 0]
        crop = np.zeros((100, 100, 3), dtype=np.uint8)
        crop[:, :] = [0, 200, 0]
        assert extract_vehicle_color(crop) == "green"

    def test_yellow_vehicle_crop(self) -> None:
        # BGR: Yellow is [0, 255, 255]
        crop = np.zeros((100, 100, 3), dtype=np.uint8)
        crop[:, :] = [0, 220, 220]
        assert extract_vehicle_color(crop) == "yellow"

    def test_invalid_or_empty_crop(self) -> None:
        assert extract_vehicle_color(None) == "other/unknown"
        assert extract_vehicle_color(np.zeros((0, 0, 3), dtype=np.uint8)) == "other/unknown"
        assert extract_vehicle_color(np.zeros((5, 5, 3), dtype=np.uint8)) == "other/unknown"


class TestVehicleEventPersistence:
    """Integration tests for VehicleEvent and PlateEvent PostgreSQL persistence."""

    def setup_method(self) -> None:
        self._db_temp = tempfile.TemporaryDirectory()
        self.db_url = "sqlite:///" + (Path(self._db_temp.name) / "vehicle.db").as_posix()
        self._database_env = patch.dict(os.environ, {"DATT_DATABASE_URL": self.db_url})
        self._database_env.start()
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("src/db/alembic.ini"), "head")
        self.db = Database(self.db_url)
        self.created_files: list[Path] = []

    def teardown_method(self) -> None:
        for f in self.created_files:
            if f.is_file():
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
        self.db.dispose()
        self._database_env.stop()
        self._db_temp.cleanup()

    def test_single_vehicle_event_per_track_and_plate_linkage(self) -> None:
        """Requirement:

        - Only ONE VehicleEvent per completed track (not every frame).
        - Saves best vehicle crop to storage and vehicle_image_path in DB.
        - Extracts vehicle_color in HSV.
        - PlateEvent linked to VehicleEvent without plate_text duplicate in VehicleEvent.
        - first_seen and last_seen recorded.
        """
        # Create dedicated worker with temp snapshot dir
        test_snapshot_dir = PROJECT_ROOT / "data" / "events" / "test_tmp"
        test_snapshot_dir.mkdir(parents=True, exist_ok=True)

        worker = DatabaseWorker(
            db_url=self.db_url,
            max_queue_size=100,
            batch_size=10,
            snapshot_dir=test_snapshot_dir,
        )
        with self.db.transaction() as session:
            from src.db.models import VehicleWatchlist
            session.add(VehicleWatchlist(plate_number="51F99999", vehicle_type="car",
                display_name="Test", owner_info="", notes="", status="active"))

        test_passage_id = uuid4()
        track_id = 992
        camera_id = str(uuid4())
        session_key = f"{camera_id}:{track_id}:1000"

        # 1. In-progress frame 1: vehicle detected, small box
        t_first = datetime(2026, 9, 30, 10, 0, 0, tzinfo=timezone.utc)
        dto_f1 = VehiclePassageDTO(
            id=test_passage_id,
            session_key=session_key,
            camera_id=camera_id,
            track_id=track_id,
            first_seen_at=t_first,
            last_seen_at=t_first,
            vehicle_type="car",
            is_final=False,
        )
        small_veh_crop = np.zeros((40, 40, 3), dtype=np.uint8)
        worker.enqueue_passage(dto_f1, vehicle_crop=small_veh_crop, is_critical=False)
        time.sleep(0.15)

        # Confirm: In-progress frame must NOT create VehicleEvent
        with self.db.transaction() as session:
            ve_repo = VehicleEventRepository(session)
            ve_in_progress = ve_repo.get(test_passage_id)
            assert ve_in_progress is None, "VehicleEvent must NOT be created during in-progress frames"

        # 2. In-progress frame 2: better vehicle crop (e.g. bright blue car) & plate detected
        t_mid = datetime(2026, 9, 30, 10, 0, 2, tzinfo=timezone.utc)
        # Create a synthetic blue car crop
        best_veh_crop = np.zeros((120, 140, 3), dtype=np.uint8)
        best_veh_crop[:, :] = [210, 20, 20]  # Blue in BGR

        # Create a synthetic plate crop
        best_plate_crop = np.ones((30, 80, 3), dtype=np.uint8) * 255
        cv2.putText(best_plate_crop, "51F99999", (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        dto_f2 = VehiclePassageDTO(
            id=test_passage_id,
            session_key=session_key,
            camera_id=camera_id,
            track_id=track_id,
            first_seen_at=t_first,
            last_seen_at=t_mid,
            vehicle_type="car",
            plate_text="51F-999.99",
            plate_status="CONFIRMED",
            plate_confidence=0.94,
            is_final=False,
        )
        worker.enqueue_passage(dto_f2, vehicle_crop=best_veh_crop, plate_crop=best_plate_crop, is_critical=False)
        time.sleep(0.15)

        with self.db.transaction() as session:
            ve_repo = VehicleEventRepository(session)
            assert ve_repo.get(test_passage_id) is None, "VehicleEvent still must NOT exist before finalization"

        # 3. Track finalization: Track exits camera / timeout reached
        t_last = datetime(2026, 9, 30, 10, 0, 5, tzinfo=timezone.utc)
        dto_final = VehiclePassageDTO(
            id=test_passage_id,
            session_key=session_key,
            camera_id=camera_id,
            track_id=track_id,
            first_seen_at=t_first,
            last_seen_at=t_last,
            vehicle_type="car",
            plate_text="51F-999.99",
            plate_status="CONFIRMED",
            plate_confidence=0.94,
            is_final=True,
        )
        worker.enqueue_passage(dto_final, vehicle_crop=best_veh_crop, plate_crop=best_plate_crop, is_critical=True)

        # Stop worker cleanly and drain queue
        worker.stop(timeout=3.0)

        # 4. Verify PostgreSQL persistence:
        with self.db.transaction() as session:
            ve_repo = VehicleEventRepository(session)
            pe_repo = PlateEventRepository(session)

            # Query VehicleEvent
            ve = ve_repo.get(test_passage_id)
            assert ve is not None, "Exactly ONE VehicleEvent must be created upon track completion"
            assert ve.id == test_passage_id
            assert ve.track_id == track_id
            assert ve.vehicle_class == "car"
            assert ve.vehicle_color == "blue"
            assert ve.first_seen == t_first
            assert ve.last_seen == t_last
            assert ve.vehicle_image_path is not None
            assert ve.vehicle_image_path.startswith("data/events/")

            # Ensure vehicle_events does NOT duplicate plate_text column
            assert not hasattr(ve, "plate_text")

            # Check that the vehicle image exists on disk
            img_disk_path = PROJECT_ROOT / ve.vehicle_image_path
            self.created_files.append(img_disk_path)
            assert img_disk_path.is_file(), f"Vehicle crop image must exist at {img_disk_path}"
            assert img_disk_path.stat().st_size > 0

            # Check PlateEvent linked to vehicle_event_id
            plate_events = pe_repo.get_by_vehicle_event(ve.id)
            assert len(plate_events) == 1, "Exactly one PlateEvent must link to this VehicleEvent"
            pe = plate_events[0]
            assert pe.vehicle_event_id == ve.id
            assert pe.plate_text == "51F-999.99"
            assert pe.confidence == pytest.approx(0.94, rel=1e-2)
            assert pe.plate_crop_path is not None
            assert pe.plate_crop_path.startswith("data/events/")

            plate_disk_path = PROJECT_ROOT / pe.plate_crop_path
            self.created_files.append(plate_disk_path)
            assert plate_disk_path.is_file()

            # Ensure query_events works with color and class filter
            filtered = ve_repo.query_events(vehicle_color="blue", vehicle_class="car")
            assert any(item.id == ve.id for item in filtered)

    def test_event_manager_e2e_track_lifecycle_vehicle_event(self) -> None:
        """End-to-end test with EventManager:

        - YOLO/ByteTrack frames -> active passages -> timeout -> ONE VehicleEvent created.
        """
        worker = DatabaseWorker(db_url=self.db_url)
        with worker.db.transaction() as session:
            from src.db.models import VehicleWatchlist
            session.add(VehicleWatchlist(plate_number="51F99999", vehicle_type="car",
                display_name="Test", owner_info="", notes="", status="active"))
        em = EventManager(db_worker=worker)
        camera_id = str(uuid4())

        # Frame 1: Vehicle track 55 appears with red vehicle crop
        red_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        red_frame[100:300, 150:400] = [0, 0, 220]  # Red vehicle

        from unittest.mock import MagicMock
        mock_tracks = MagicMock()
        mock_tracks.xyxy = np.array([[150, 100, 400, 300]], dtype=np.float32)
        mock_tracks.tracker_id = np.array([55], dtype=np.int32)
        mock_tracks.class_id = np.array([2], dtype=np.int32)
        mock_tracks.confidence = np.array([0.88], dtype=np.float32)

        em.process_vehicle_frame(
            camera_id=camera_id,
            vehicle_tracks=mock_tracks,
            plate_results={55: SimpleNamespace(status="CONFIRMED", confirmed_plate="51F99999",
                plate_text="51F99999", confidence=0.94, plate_crop=np.ones((30,80,3), dtype=np.uint8))},
            frame=red_frame,
        )

        # In-progress: check no vehicle event yet
        passage_55 = em._active_passages.get((camera_id, 55))
        assert passage_55 is not None
        p_id = passage_55.id

        with self.db.transaction() as session:
            assert VehicleEventRepository(session).get(p_id) is None

        # Reset / Finalize track
        em.reset()
        em.stop()

        # Verify ONE VehicleEvent was created
        with self.db.transaction() as session:
            ve = VehicleEventRepository(session).get(p_id)
            assert ve is not None, "VehicleEvent must be created upon track finalization"
            assert ve.track_id == 55
            assert ve.vehicle_class == "car"
            assert ve.vehicle_color == "red"
            assert ve.vehicle_image_path is not None
            img_file = PROJECT_ROOT / ve.vehicle_image_path
            self.created_files.append(img_file)
            assert img_file.is_file()
