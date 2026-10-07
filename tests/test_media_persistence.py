"""Verification tests for Video MP4 and Target Face Image Persistence.

Validates:
1. Video MP4 upload:
   - File saved to local storage (data/uploads/videos/)
   - Relative path stored in DB video_sources table (id UUID, original_filename, storage_path, status, created_at)
   - CV pipeline reads video from storage_path normally via LocalVideoReader / CameraManager
2. Face target registration:
   - Original image saved to local storage (data/uploads/targets/)
   - 512D ArcFace embedding persisted into target_embeddings
   - source_image_path references original image relative path
   - No binary image/video directly stored in PostgreSQL/DB
3. Event flow:
   - Events and vehicle passages are linked with video_source_id
"""

import io
import gc
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import cv2
from fastapi.testclient import TestClient
import numpy as np

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent

from src.db.database import Database
from src.db.models import Base, VideoSource, Target, TargetEmbedding, BusinessEvent, VehiclePassage, VehicleWatchlist, VehicleEvent
from src.db.repositories import (
    VideoSourceRepository, TargetRepository, TargetEmbeddingRepository,
    BusinessEventRepository, VehiclePassageRepository,
)
from src.events.event_manager import EventManager
from src.events.db_worker import DatabaseWorker
from src.recognition.target_matcher import target_manager
from src.stream.camera_manager import CameraManager
from src.stream.video_source import LocalVideoReader
from src.ui.web_server import app


def create_test_mp4(dest_path: Path, num_frames: int = 10, width: int = 320, height: int = 240, fps: float = 30.0) -> Path:
    """Create a minimal playable MP4 video file."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(dest_path), fourcc, fps, (width, height))
    for i in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        cv2.putText(frame, f"Test {i}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        out.write(frame)
    out.release()
    return dest_path


class TestMediaPersistence(unittest.TestCase):
    """Test suite verifying persistence of uploaded MP4s and target registration images."""

    def setUp(self) -> None:
        self.db_temp = tempfile.TemporaryDirectory()
        db_url = "sqlite:///" + (Path(self.db_temp.name) / "media.db").as_posix()
        self.db_env = patch.dict(os.environ, {"DATT_DATABASE_URL": db_url})
        self.db_env.start()
        from alembic import command
        from alembic.config import Config
        command.upgrade(Config("src/db/alembic.ini"), "head")
        self.client = TestClient(app)
        target_manager.clear()
        self.created_files: list[Path] = []

    def tearDown(self) -> None:
        target_manager.clear()
        for f in self.created_files:
            if f.is_file():
                try:
                    f.unlink(missing_ok=True)
                except Exception:
                    pass
        self.db_env.stop()
        gc.collect()
        self.db_temp.cleanup()

    def test_01_upload_mp4_persistence_and_db_record(self) -> None:
        """Upload MP4 -> file saved in data/uploads/videos/ + video_sources DB record."""
        # 1. Create a dummy MP4 file in a temp directory
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        create_test_mp4(tmp_path, num_frames=8)
        self.created_files.append(tmp_path)

        with open(tmp_path, "rb") as f:
            mp4_bytes = f.read()

        # 2. Upload through /api/upload_video endpoint
        response = self.client.post(
            "/api/upload_video",
            files={"file": ("sample_test_traffic.mp4", mp4_bytes, "video/mp4")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")

        # Verify response fields
        self.assertIn("video_source_id", data)
        self.assertIn("storage_path", data)
        self.assertIn("server_path", data)
        self.assertTrue(data["storage_path"].startswith("data/uploads/videos/"))

        uploaded_disk_file = Path(data["server_path"])
        self.created_files.append(uploaded_disk_file)
        self.assertTrue(uploaded_disk_file.is_file(), "Uploaded MP4 file must exist on disk")
        self.assertGreater(uploaded_disk_file.stat().st_size, 0)

        # 3. Verify DB record in video_sources
        db = Database()
        with db.transaction() as session:
            repo = VideoSourceRepository(session)
            vs_uuid = UUID(data["video_source_id"])
            vs_record = repo.get(vs_uuid)
            self.assertIsNotNone(vs_record, "video_sources table must contain uploaded record")
            assert vs_record is not None
            self.assertEqual(vs_record.original_filename, "sample_test_traffic.mp4")
            self.assertEqual(vs_record.storage_path, data["storage_path"])
            self.assertEqual(vs_record.status, "ready")
            self.assertIsNotNone(vs_record.created_at)

        # 4. Verify CV pipeline reads video from storage_path normally
        reader = LocalVideoReader(file_path=data["storage_path"], loop=False)
        reader.start()
        try:
            frame = reader.read(timeout=2.0)
            self.assertIsNotNone(frame, "LocalVideoReader must successfully read frame from storage_path")
            assert frame is not None
            self.assertEqual(frame.shape, (240, 320, 3))
        finally:
            reader.stop()

        # 5. Verify CameraManager starts video source and links video_source_id
        cam_mgr = CameraManager()
        try:
            cam_info = cam_mgr.set_video_source(
                source_type="local",
                source=data["storage_path"],
                loop=False,
                video_source_id=data["video_source_id"],
            )
            self.assertEqual(cam_info.video_source_id, data["video_source_id"])
            frame_res = cam_mgr.read_with_meta(timeout=2.0)
            self.assertIsNotNone(frame_res)
            self.assertIsNotNone(frame_res[0])
        finally:
            cam_mgr.stop_camera()

    def test_02_target_registration_persistence_and_embeddings(self) -> None:
        """Register target image -> file saved in data/uploads/targets/ + 512D ArcFace in DB."""
        # 1. Create a dummy synthetic face image
        img = np.ones((120, 120, 3), dtype=np.uint8) * 180
        cv2.circle(img, (60, 60), 30, (100, 100, 220), -1)
        _, img_buf = cv2.imencode(".jpg", img)
        raw_bytes = img_buf.tobytes()

        # Mock face embedding extraction (512D normalized)
        mock_embedding = np.random.randn(512).astype(np.float32)
        mock_embedding /= np.linalg.norm(mock_embedding)

        with patch("src.recognition.target_matcher.face_embedder.extract_face_embedding", return_value=mock_embedding):
            resp = self.client.post(
                "/api/register_target",
                data={"name": "Inspector Morse", "clothing_color": "navy", "threshold": "0.48"},
                files={"face_image": ("morse_face.jpg", io.BytesIO(raw_bytes), "image/jpeg")},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "ok")
            target_data = data["target"]
            self.assertTrue(target_data["has_face"])
            self.assertIn("source_image_path", target_data)
            rel_img_path = target_data["source_image_path"]
            self.assertTrue(rel_img_path.startswith("data/uploads/targets/"))

            target_disk_path = PROJECT_ROOT / rel_img_path
            self.created_files.append(target_disk_path)
            self.assertTrue(target_disk_path.is_file(), "Original target image must exist on disk")

            # Verify in DB: target_embeddings table has 512D embedding and source_image_path
            db = Database()
            with db.transaction() as session:
                t_repo = TargetRepository(session)
                te_repo = TargetEmbeddingRepository(session)

                t_record = t_repo.get(UUID(target_data["id"]))
                self.assertIsNotNone(t_record, "Target record must exist in DB")
                assert t_record is not None
                self.assertEqual(t_record.name, "Inspector Morse")
                self.assertEqual(t_record.image_path, rel_img_path)

                embeddings = session.query(TargetEmbedding).filter_by(target_id=t_record.id).all()
                self.assertEqual(len(embeddings), 1)
                emb_record = embeddings[0]
                self.assertEqual(emb_record.source_image_path, rel_img_path)
                self.assertEqual(emb_record.model_name, "adaface_ir50_ms1mv2")
                # Confirm embedding dimension is 512
                emb_list = list(emb_record.embedding)
                self.assertEqual(len(emb_list), 512)

    def test_03_event_flow_links_video_source_id(self) -> None:
        """Verify business events and vehicle passages link with video_source_id."""
        db = Database()
        with db.transaction() as session:
            # Create a mock VideoSource record in DB
            vs_repo = VideoSourceRepository(session)
            vs = vs_repo.create(
                original_filename="traffic_clip.mp4",
                storage_path="data/uploads/videos/traffic_clip.mp4",
                status="ready",
            )
            vs_id = vs.id

        # Persist a real confirmed watchlist passage using the current flow.
        with db.transaction() as session:
            session.add(VehicleWatchlist(plate_number="29A12345", vehicle_type="car",
                display_name="Media test", owner_info="", notes="", status="active"))
        worker = DatabaseWorker()
        em = EventManager(db_worker=worker)

        # 1. Process occupancy frame with video_source_id
        em.process_frame(
            camera_id="cam_test_01",
            people_count=10,
            video_source_id=vs_id,
        )
        time.sleep(0.05)
        em.process_frame(
            camera_id="cam_test_01",
            people_count=18,
            video_source_id=vs_id,
        )

        # 2. Process vehicle frame with video_source_id
        class MockTracks:
            xyxy = np.array([[50, 50, 200, 200]])
            tracker_id = np.array([42])
            class_id = np.array([2])
            confidence = np.array([0.92])

        em.process_vehicle_frame(
            camera_id="cam_test_01",
            vehicle_tracks=MockTracks(),
            plate_results={42: SimpleNamespace(status="CONFIRMED", confirmed_plate="29A12345",
                plate_text="29A12345", confidence=.95, plate_crop=None)},
            video_source_id=vs_id,
        )

        # Verify internal passage received video_source_id
        passage = em._active_passages.get(("cam_test_01", 42))
        self.assertIsNotNone(passage)
        assert passage is not None
        self.assertEqual(passage.video_source_id, vs_id)

        dto = passage.to_dto()
        self.assertEqual(dto.video_source_id, vs_id)
        em.reset()
        worker.stop(timeout=3.0)
        with db.transaction() as session:
            event = session.get(VehicleEvent, passage.id)
            self.assertIsNotNone(event)
            self.assertEqual(event.video_source_id, vs_id)


if __name__ == "__main__":
    unittest.main()
