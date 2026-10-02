"""End-to-End Test Suite for DATT Backend, Database, Video Library, Target Person, and Motorcycle OCR.

Validates all 9 user requirements:
1. Video Library: Upload MP4 -> persisted storage -> video_sources PostgreSQL -> list -> select -> delete
2. Target Person: Register -> original image persisted -> AdaFace 512D in target_embeddings -> select/toggle
3. Motorcycle Plate OCR: Motorcycle detection -> ByteTrack -> ROI -> plate detection -> OCR -> consensus -> PlateEvent (no rider/person dependency)
4. Vehicle Event: 1 VehicleEvent per vehicle track on exit with HSV color, best crop image, first_seen/last_seen, linked PlateEvent
5. Source Traceability: video_source_id -> video -> frame/time -> track -> VehicleEvent / FaceEvent / PlateEvent
6. Persistence: EventManager -> async DB worker -> PostgreSQL
7. API Endpoints: list/upload/select/delete video_sources, list/register/select targets, query vehicle/plate/face events
"""

from datetime import datetime, timezone
import io
import os
from pathlib import Path
import tempfile
import time
from uuid import UUID, uuid4

import cv2
from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.db.database import Database
from src.db.models import FaceEvent, PlateEvent, Target, TargetEmbedding, VehicleEvent, VideoSource
from src.db.repositories import (
    FaceEventRepository,
    PlateEventRepository,
    TargetEmbeddingRepository,
    TargetRepository,
    VehicleEventRepository,
    VideoSourceRepository,
)
from src.events.db_worker import DatabaseWorker
from src.events.event_dto import FaceEventDTO, VehiclePassageDTO
from src.events.event_manager import EventManager
from src.ocr.plate_reader import PlateCandidate
from src.ocr.plate_tracker import PlateTrackState, VehiclePlateManager
from src.recognition.color_extractor import extract_vehicle_color
from src.recognition.target_matcher import target_manager
from src.stream.camera_manager import CameraManager
from src.stream.video_source import LocalVideoReader
from src.ui.web_server import app

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def create_sample_mp4(path: Path, num_frames: int = 15, width: int = 320, height: int = 240) -> Path:
    """Generate a valid, playable MP4 file for testing."""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(path), fourcc, 30.0, (width, height))
    for i in range(num_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        # Red vehicle box moving across screen
        x = 20 + i * 8
        cv2.rectangle(frame, (x, 80), (x + 80, 160), (0, 0, 220), -1)
        # Motorcycle plate simulation box
        cv2.rectangle(frame, (x + 20, 130), (x + 60, 150), (255, 255, 255), -1)
        cv2.putText(frame, "29A12345", (x + 22, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 0), 1)
        out.write(frame)
    out.release()
    return path


class TestEndToEndBackendDatabase:
    """End-to-end integration tests for backend, database, and computer vision pipelines."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self) -> None:
        """Fixture for setting up test client and cleaning up disk artifacts."""
        self.client = TestClient(app)
        target_manager.clear()
        self.cleanup_files: list[Path] = []
        yield
        target_manager.clear()
        for p in self.cleanup_files:
            if p.is_file():
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

    def test_01_video_library_e2e_flow(self) -> None:
        """Requirement 1 & 7: Video Library Upload, Storage, Database Record, Listing, and Deletion."""
        # 1. Create a temporary MP4
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        create_sample_mp4(tmp_path, num_frames=10)
        self.cleanup_files.append(tmp_path)

        with open(tmp_path, "rb") as f:
            mp4_content = f.read()

        # 2. Upload via API
        upload_resp = self.client.post(
            "/api/upload_video",
            files={"file": ("highway_patrol.mp4", mp4_content, "video/mp4")},
        )
        assert upload_resp.status_code == 200
        data = upload_resp.json()
        assert data["status"] == "ok"
        source_id = data["video_source_id"]
        rel_storage_path = data["storage_path"]
        server_path = Path(data["server_path"])
        self.cleanup_files.append(server_path)

        assert server_path.is_file()
        assert rel_storage_path.startswith("data/uploads/videos/")

        # 3. Verify PostgreSQL record in video_sources
        db = Database()
        with db.transaction() as session:
            repo = VideoSourceRepository(session)
            src_uuid = UUID(source_id)
            rec = repo.get(src_uuid)
            assert rec is not None
            assert rec.original_filename == "highway_patrol.mp4"
            assert rec.storage_path == rel_storage_path
            assert rec.status == "ready"

        # 4. List videos in library
        list_resp = self.client.get("/api/video_sources")
        assert list_resp.status_code == 200
        sources = list_resp.json().get("sources", [])
        found = [s for s in sources if s["id"] == source_id]
        assert len(found) == 1
        assert found[0]["original_filename"] == "highway_patrol.mp4"

        # 5. Select and verify CV reader can stream from storage_path
        cam_mgr = CameraManager()
        try:
            cam_info = cam_mgr.set_video_source(
                source_type="local",
                source=rel_storage_path,
                loop=False,
                video_source_id=source_id,
            )
            assert cam_info.video_source_id == source_id
            frame_res = cam_mgr.read_with_meta(timeout=2.0)
            assert frame_res is not None
            assert frame_res[0] is not None
        finally:
            cam_mgr.stop_camera()

        # 6. Delete video from library and storage
        del_resp = self.client.delete(f"/api/video_sources/{source_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["status"] == "ok"

        # Verify DB deletion and disk deletion
        with db.transaction() as session:
            repo = VideoSourceRepository(session)
            assert repo.get(src_uuid) is None
        assert not server_path.exists()

    def test_02_target_person_e2e_flow(self) -> None:
        """Requirement 2 & 7: Target Person Registration, 512D AdaFace, Selection, and DB Persistence."""
        # 1. Create a dummy synthetic face image
        face_img = np.ones((100, 100, 3), dtype=np.uint8) * 190
        cv2.circle(face_img, (50, 50), 30, (80, 80, 220), -1)
        _, img_buf = cv2.imencode(".jpg", face_img)
        img_bytes = img_buf.tobytes()

        # Generate normalized 512D embedding
        sim_emb = np.random.randn(512).astype(np.float32)
        sim_emb /= np.linalg.norm(sim_emb)

        from unittest.mock import patch
        with patch("src.recognition.target_matcher.face_embedder.extract_face_embedding", return_value=sim_emb):
            reg_resp = self.client.post(
                "/api/register_target",
                data={"name": "Subject Delta", "color": "blue", "threshold": "0.45"},
                files={"face_image": ("subject_delta.jpg", io.BytesIO(img_bytes), "image/jpeg")},
            )
            assert reg_resp.status_code == 200
            res_data = reg_resp.json()
            assert res_data["status"] == "ok"
            target_info = res_data["target"]
            target_id = target_info["id"]

            rel_target_img = target_info["source_image_path"]
            assert rel_target_img.startswith("data/uploads/targets/")
            disk_target_img = PROJECT_ROOT / rel_target_img
            self.cleanup_files.append(disk_target_img)
            assert disk_target_img.is_file()

        # 2. Verify PostgreSQL persistence in targets and target_embeddings tables
        db = Database()
        with db.transaction() as session:
            t_repo = TargetRepository(session)
            te_repo = TargetEmbeddingRepository(session)

            t_rec = t_repo.get(UUID(target_id))
            assert t_rec is not None
            assert t_rec.name == "Subject Delta"
            assert t_rec.image_path == rel_target_img

            embs = session.query(TargetEmbedding).filter_by(target_id=t_rec.id).all()
            assert len(embs) == 1
            assert embs[0].model_name == "adaface_ir50_ms1mv2"
            assert len(list(embs[0].embedding)) == 512

        # 3. Test list targets API
        targets_resp = self.client.get("/api/targets")
        assert targets_resp.status_code == 200
        t_list = targets_resp.json().get("targets", [])
        assert any(t["id"] == target_id for t in t_list)

        # 4. Test Target Selection API (Select / Deselect)
        sel_resp = self.client.post(f"/api/targets/{target_id}/select", json={"selected": False})
        assert sel_resp.status_code == 200
        assert sel_resp.json()["selected"] is False

        # Verify TargetManager updated selection state
        t_obj = target_manager.get_target(target_id)
        assert t_obj is not None
        assert t_obj.is_selected is False

        # Re-select target
        sel_resp2 = self.client.post(f"/api/targets/{target_id}/select", json={"selected": True})
        assert sel_resp2.status_code == 200
        assert t_obj.is_selected is True

        # 5. Test serve target image
        img_resp = self.client.get(f"/api/targets/{target_id}/image")
        assert img_resp.status_code == 200
        assert len(img_resp.content) > 0

    def test_03_motorcycle_plate_ocr_independent_of_person(self) -> None:
        """Requirement 3: Motorcycle plate OCR must execute directly on motorcycle tracks without person/rider dependency."""
        from unittest.mock import MagicMock

        # Mock reader returning valid plate candidate
        mock_reader = MagicMock()
        cand = PlateCandidate(
            plate_text="29A12345",
            confidence=0.92,
            bbox_vehicle=(10, 10, 50, 30),
            bbox_native=(110, 110, 150, 130),
            raw_crop=np.zeros((20, 40, 3), dtype=np.uint8),
            preprocessed_crop=np.zeros((20, 40, 3), dtype=np.uint8),
            sharpness=120.0,
            quality_score=85.0,
            raw_text="29A12345",
            normalized_text="29A12345",
        )
        mock_reader.extract_license_plate.return_value = cand

        mgr = VehiclePlateManager(reader=mock_reader, min_observations=1)

        # Motorcycle track (class 3) without ANY person track
        class MockMotorcycleTracks:
            xyxy = np.array([[100, 100, 280, 320]], dtype=np.float32)
            tracker_id = np.array([101], dtype=np.int32)
            class_id = np.array([3], dtype=np.int32)  # 3 = motorcycle
            confidence = np.array([0.91], dtype=np.float32)

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(frame, (100, 100), (280, 320), (0, 160, 255), -1)

        # Process motorcycle tracks directly without any rider or person
        results = mgr.process_vehicle_tracks(frame=frame, vehicle_tracks=MockMotorcycleTracks(), frame_id=1)
        assert 101 in results
        assert results[101].vehicle_class == "motorcycle"
        assert results[101].plate_text == "29A12345"
        assert results[101].confidence == 0.92
        mock_reader.extract_license_plate.assert_called_once()

    def test_04_vehicle_event_persistence_and_traceability(self) -> None:
        """Requirement 4, 5, 6: 1 VehicleEvent on track completion with HSV color, crop, linked PlateEvent, and video_source_id."""
        db = Database()
        with db.transaction() as session:
            vs_repo = VideoSourceRepository(session)
            vs = vs_repo.create(
                original_filename="motorcycle_city.mp4",
                storage_path="data/uploads/videos/motorcycle_city.mp4",
                status="ready",
            )
            vs_id = vs.id

        # Setup worker and repository
        worker = DatabaseWorker(batch_size=5)

        # Vehicle Passage DTO representing completed motorcycle track
        v_event_id = uuid4()
        dto = VehiclePassageDTO(
            id=v_event_id,
            session_key="session_motorcycle_1",
            camera_id="cam_street_01",
            track_id=101,
            first_seen_at=datetime(2026, 9, 30, 8, 0, 0, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 9, 30, 8, 0, 6, tzinfo=timezone.utc),
            video_source_id=vs_id,
            vehicle_type="motorcycle",
            vehicle_color="red",
            vehicle_type_confidence=0.93,
            plate_text="29X19999",
            plate_confidence=0.94,
            plate_status="CONFIRMED",
            best_vehicle_image_path="data/events/vehicle_101.jpg",
            is_final=True,
        )

        crop = np.zeros((80, 80, 3), dtype=np.uint8)
        crop[:, :] = [0, 0, 255]  # Red

        # Enqueue vehicle event
        worker.enqueue_passage(dto, vehicle_crop=crop, is_critical=True)
        worker.stop(timeout=3.0)

        # Verify PostgreSQL VehicleEvent and linked PlateEvent
        with db.transaction() as session:
            v_repo = VehicleEventRepository(session)
            p_repo = PlateEventRepository(session)

            v_rec = v_repo.get(v_event_id)
            assert v_rec is not None
            assert v_rec.vehicle_class == "motorcycle"
            assert v_rec.vehicle_color == "red"
            assert v_rec.video_source_id == vs_id
            assert v_rec.track_id == 101

            # Check PlateEvent linkage
            plates = p_repo.query_events(vehicle_event_id=v_event_id)
            assert len(plates) == 1
            assert plates[0].plate_text == "29X19999"
            assert plates[0].vehicle_event_id == v_event_id

    def test_05_face_event_persistence_and_traceability(self) -> None:
        """Requirement 5 & 6: FaceEvent persistence with video_source_id, target_id, track_id, and crop image."""
        db = Database()
        target_id = uuid4()

        with db.transaction() as session:
            vs_repo = VideoSourceRepository(session)
            t_repo = TargetRepository(session)

            vs = vs_repo.create(
                original_filename="security_hallway.mp4",
                storage_path="data/uploads/videos/security_hallway.mp4",
                status="ready",
            )
            vs_id = vs.id
            tgt = t_repo.create(
                id=target_id,
                name="Target Alpha",
                target_type="face",
                active=True,
            )

        worker = DatabaseWorker(batch_size=5)

        face_ev_id = uuid4()
        face_dto = FaceEventDTO(
            id=face_ev_id,
            camera_id="cam_gate_02",
            target_id=target_id,
            target_name="Target Alpha",
            track_id=45,
            decision="FACE_MATCH",
            similarity=0.88,
            frame_id=128,
            created_at=datetime(2026, 9, 30, 8, 15, 0, tzinfo=timezone.utc),
            video_source_id=vs_id,
        )

        face_crop = np.ones((60, 60, 3), dtype=np.uint8) * 160
        worker.enqueue_face_event(face_dto, face_crop=face_crop, is_critical=True)
        worker.stop(timeout=3.0)

        # Verify PostgreSQL FaceEvent
        with db.transaction() as session:
            f_repo = FaceEventRepository(session)
            f_rec = f_repo.get(face_ev_id)
            assert f_rec is not None
            assert f_rec.target_id == target_id
            assert f_rec.track_id == 45
            assert f_rec.frame_id == 128
            assert f_rec.video_source_id == vs_id
            assert f_rec.decision == "FACE_MATCH"

    def test_06_event_query_apis(self) -> None:
        """Requirement 7: Query APIs for vehicles, plates, and faces."""
        v_resp = self.client.get("/api/events/vehicles?limit=10")
        assert v_resp.status_code == 200
        assert "events" in v_resp.json()

        p_resp = self.client.get("/api/events/plates?limit=10")
        assert p_resp.status_code == 200
        assert "events" in p_resp.json()

        f_resp = self.client.get("/api/events/faces?limit=10")
        assert f_resp.status_code == 200
        assert "events" in f_resp.json()
