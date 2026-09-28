"""Database integration tests use real SQLite and the actual Alembic revision."""
import io
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, StatementError

from src.db import Database
from src.db.repositories import (
    CameraRepository, TargetRepository, DetectionEventRepository,
    VehicleEventRepository, PlateEventRepository, FaceEventRepository, ZoneRepository,
)

ROOT = Path(__file__).resolve().parents[1]


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.url = "sqlite:///" + (Path(self.temp.name) / "test.db").as_posix()
        self.env = patch.dict(os.environ, {"DATT_DATABASE_URL": self.url})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = Config(str(ROOT / "src/db/alembic.ini"))
        command.upgrade(self.config, "head")
        self.db = Database(self.url)
        self.addCleanup(self.db.dispose)

    def camera(self, session):
        return CameraRepository(session).create(name="Gate", source_type="file", source="demo.mp4")

    def graph(self, session):
        camera = self.camera(session)
        target = TargetRepository(session).create(name="Person", target_type="face", embedding=[0.1, 0.2],
                                                   reference_metadata={"model": "demo"})
        detection = DetectionEventRepository(session).create(
            camera_id=camera.id, event_type="vehicle", frame_id=10, track_id=0,
            timestamp=datetime(2026, 1, 1, 7, tzinfo=timezone(timedelta(hours=7))),
            bbox=[1, 2, 3, 4], event_metadata={"nested": {"labels": ["car"]}})
        vehicle = VehicleEventRepository(session).create(detection_event_id=detection.id,
                                                          vehicle_class="car", track_id=0)
        plate = PlateEventRepository(session).create(vehicle_event_id=vehicle.id, plate_text="30A12345")
        face = FaceEventRepository(session).create(detection_event_id=detection.id, target_id=target.id,
                                                    track_id=0, similarity=0.9, decision="matched")
        return camera, target, detection, vehicle, plate, face

    def test_camera_target_crud(self):
        with self.db.transaction() as session:
            camera = self.camera(session)
            target = TargetRepository(session).create(name="A", target_type="face")
        with self.db.transaction() as session:
            cameras = CameraRepository(session)
            self.assertEqual(cameras.get(camera.id).source, "demo.mp4")
            updated = cameras.update(camera.id, name="Gate 2", enabled=False)
            self.assertGreaterEqual(updated.updated_at, camera.updated_at)
            TargetRepository(session).update(target.id, active=False, reference_metadata={"version": 2})
        with self.db.transaction() as session:
            self.assertEqual(CameraRepository(session).list(enabled=False)[0].name, "Gate 2")
            self.assertEqual(TargetRepository(session).get(target.id).reference_metadata, {"version": 2})
            self.assertTrue(TargetRepository(session).delete(target.id))
            self.assertTrue(CameraRepository(session).delete(camera.id))
            self.assertFalse(CameraRepository(session).delete(camera.id))

    def test_zone_crud_and_foreign_key(self):
        polygon = [[0, 0], [100, 0], [100, 100]]
        with self.db.transaction() as session:
            camera = self.camera(session)
            zone = ZoneRepository(session).create(camera_id=camera.id, name="Entry", polygon=polygon)
        with self.db.transaction() as session:
            repo = ZoneRepository(session)
            self.assertEqual(repo.list(camera_id=camera.id)[0].polygon, polygon)
            updated = repo.update(zone.id, name="Exit", enabled=False)
            self.assertGreaterEqual(updated.updated_at, zone.updated_at)
        with self.assertRaises(IntegrityError):
            with self.db.transaction() as session:
                CameraRepository(session).delete(camera.id)
        with self.db.transaction() as session:
            self.assertFalse(ZoneRepository(session).get(zone.id).enabled)
            ZoneRepository(session).delete(zone.id)
            CameraRepository(session).delete(camera.id)
        with self.assertRaises(IntegrityError):
            with self.db.transaction() as session:
                ZoneRepository(session).create(camera_id=uuid4(), name="Invalid", polygon=polygon)

    def test_zone_migration_preserves_existing_data(self):
        self.db.dispose()
        command.downgrade(self.config, "0001")
        with self.db.transaction() as session:
            camera = self.camera(session)
        command.upgrade(self.config, "head")
        with self.db.transaction() as session:
            self.assertEqual(CameraRepository(session).get(camera.id).name, "Gate")
            ZoneRepository(session).create(camera_id=camera.id, name="Entry", polygon=[[0, 0], [1, 0], [1, 1]])
        self.db.dispose()
        command.downgrade(self.config, "0001")
        with self.db.transaction() as session:
            self.assertIsNotNone(CameraRepository(session).get(camera.id))

    def test_event_insert_query_and_utc_json_roundtrip(self):
        with self.db.transaction() as session:
            camera, target, detection, vehicle, plate, face = self.graph(session)
        with self.db.transaction() as session:
            events = DetectionEventRepository(session)
            rows = events.query(camera_id=camera.id, event_type="vehicle", track_id=0,
                                since=datetime(2026, 1, 1, tzinfo=timezone.utc),
                                until=datetime(2026, 1, 2, tzinfo=timezone.utc))
            self.assertEqual([row.id for row in rows], [detection.id])
            self.assertEqual(rows[0].timestamp, datetime(2026, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(rows[0].timestamp.tzinfo, timezone.utc)
            self.assertEqual(rows[0].event_metadata, {"nested": {"labels": ["car"]}})
            self.assertEqual(events.query(until=rows[0].timestamp), [])
            self.assertEqual(events.query(camera_id=uuid4()), [])
            self.assertEqual(PlateEventRepository(session).list(plate_text="30A12345")[0].id, plate.id)
            self.assertEqual(FaceEventRepository(session).list(target_id=target.id)[0].id, face.id)
            self.assertEqual(VehicleEventRepository(session).list(track_id=0)[0].id, vehicle.id)
            PlateEventRepository(session).update(plate.id, status="confirmed", confidence=0.95)
        with self.db.transaction() as session:
            self.assertEqual(PlateEventRepository(session).get(plate.id).status, "confirmed")

    def test_exception_rolls_back_whole_event_graph(self):
        with self.assertRaises(RuntimeError):
            with self.db.transaction() as session:
                self.graph(session)
                raise RuntimeError("writer failed")
        with self.db.transaction() as session:
            for repository in (CameraRepository, TargetRepository, DetectionEventRepository,
                               VehicleEventRepository, PlateEventRepository, FaceEventRepository):
                self.assertEqual(repository(session).list(), [])

    def test_fk_failure_rolls_back_and_next_transaction_works(self):
        with self.assertRaises(IntegrityError):
            with self.db.transaction() as session:
                self.camera(session)
                DetectionEventRepository(session).create(camera_id=uuid4(), event_type="face", frame_id=1)
        with self.db.transaction() as session:
            self.assertEqual(CameraRepository(session).list(), [])
            self.camera(session)

    def test_delete_policies(self):
        with self.db.transaction() as session:
            camera, target, detection, vehicle, plate, face = self.graph(session)
        with self.assertRaises(IntegrityError):
            with self.db.transaction() as session:
                CameraRepository(session).delete(camera.id)
        with self.db.transaction() as session:
            TargetRepository(session).delete(target.id)
        with self.db.transaction() as session:
            self.assertIsNone(FaceEventRepository(session).get(face.id).target_id)
            DetectionEventRepository(session).delete(detection.id)
        with self.db.transaction() as session:
            for repository in (VehicleEventRepository, PlateEventRepository, FaceEventRepository):
                self.assertEqual(repository(session).list(), [])
            CameraRepository(session).delete(camera.id)

    def test_naive_time_rejected(self):
        with self.assertRaises(StatementError):
            with self.db.transaction() as session:
                camera = self.camera(session)
                DetectionEventRepository(session).create(camera_id=camera.id, event_type="face",
                                                         frame_id=1, timestamp=datetime(2026, 1, 1))

    def test_query_pagination_and_validation(self):
        with self.db.transaction() as session:
            camera = self.camera(session)
            repo = DetectionEventRepository(session)
            start = datetime(2026, 1, 1, tzinfo=timezone.utc)
            for number in range(3):
                repo.create(camera_id=camera.id, event_type="vehicle", frame_id=number,
                            timestamp=start + timedelta(seconds=number))
            self.assertEqual([r.frame_id for r in repo.query(limit=1, offset=1)], [1])
            with self.assertRaises(ValueError):
                repo.query(limit=0)
            with self.assertRaises(ValueError):
                repo.list(unknown="value")
            with self.assertRaises(ValueError):
                repo.update(uuid4(), id=uuid4())

    def test_migration_indexes_schema_drift_and_roundtrip(self):
        inspector = inspect(self.db.engine)
        expected = {
            "zones": {"camera_id"},
            "detection_events": {"camera_id", "timestamp", "track_id", "event_type"},
            "vehicle_events": {"track_id"}, "plate_events": {"plate_text"},
            "face_events": {"track_id", "target_id"},
        }
        for table, columns in expected.items():
            indexed = {column for idx in inspector.get_indexes(table) for column in idx["column_names"]}
            self.assertTrue(columns <= indexed)
        command.check(self.config)
        self.db.dispose()
        command.downgrade(self.config, "base")
        self.assertEqual(set(inspect(self.db.engine).get_table_names()), {"alembic_version"})
        command.upgrade(self.config, "head")
        with self.db.transaction() as session:
            self.graph(session)

    def test_postgresql_migration_sql(self):
        buffer = io.StringIO()
        self.config.output_buffer = buffer
        with patch.dict(os.environ, {"DATT_DATABASE_URL": "postgresql://user:pass@localhost/datt"}):
            command.upgrade(self.config, "head", sql=True)
        sql = buffer.getvalue()
        self.assertIn("JSONB", sql)
        self.assertIn("TIMESTAMP WITH TIME ZONE", sql)
        self.assertIn("UUID", sql)
        self.assertIn("ON DELETE SET NULL", sql)


if __name__ == "__main__":
    unittest.main()
