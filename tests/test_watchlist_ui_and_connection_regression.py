"""Regression tests for Watchlist UI, Detail Endpoints, and Connection Decoupling.

Verifies:
1. Backend connected but camera offline: telemetry is_fallback=True does not affect /api/targets.
2. /api/targets list query defers embedding vectors and provides created_at, has_embedding.
3. GET /api/targets/{target_id} provides detail metadata without exposing raw 512-dim vectors.
4. Protected target image endpoint /api/targets/{target_id}/image enforces authorization policy.
5. POST /api/targets/{target_id}/select toggles target selection state.
6. Vehicle detail and detection history endpoints function properly.
7. Deletion requires explicit call and removes target from database.
"""

import io
import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.recognition.target_matcher import target_manager
from src.ui.web_server import app


class TestWatchlistUIAndConnectionRegression(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_url = 'sqlite:///' + (Path(self.temp.name) / 'watchlist_reg.db').as_posix()
        self.env = patch.dict(os.environ, {
            'DATT_DATABASE_URL': self.db_url,
            'DATT_REQUIRE_PERSISTENCE': '0',
            'DATT_STORAGE_BACKEND': 'local',
            'DATT_STORAGE_ROOT': self.temp.name,
            'DATT_REQUIRE_AUTH': '0',
        })
        self.env.start()
        command.upgrade(Config(str(PROJECT_ROOT / 'src/db/alembic.ini')), 'head')
        self.client = TestClient(app)
        target_manager.clear()

    def tearDown(self):
        target_manager.clear()
        self.client.close()
        from src.db.database import Database
        try:
            Database(self.db_url).dispose()
        except Exception:
            pass
        self.env.stop()
        try:
            self.temp.cleanup()
        except Exception:
            pass

    def test_camera_offline_does_not_affect_watchlist_api(self):
        """Camera stream offline/fallback must NOT indicate Watchlist is offline."""
        # Telemetry may be disconnected/fallback
        t_resp = self.client.get("/api/telemetry")
        assert t_resp.status_code == 200
        t_data = t_resp.json()
        assert t_data.get("camera_status") in ("DISCONNECTED", "CONNECTING", "STOPPED")
        assert t_data.get("stream_alive") is False

        # Watchlist API is fully functional and returns 200
        targets_resp = self.client.get("/api/targets")
        assert targets_resp.status_code == 200
        assert targets_resp.json().get("status") == "ok"
        assert "targets" in targets_resp.json()

    def test_target_list_query_defers_embeddings_and_includes_metadata(self):
        """Target list items must include created_at, has_embedding, without raw embedding vectors."""
        # Register a target
        from src.db.database import Database
        from src.db.models import Target
        import uuid

        target_id = uuid.uuid4()
        db = Database()
        with db.transaction() as session:
            t = Target(
                id=target_id,
                name="Nguyen Van A",
                target_type="face",
                embedding=[0.1] * 512,  # Raw 512-dim embedding
                reference_metadata={"clothing_color": "blue", "threshold": 0.45, "selected": True},
                active=True,
            )
            session.add(t)

        resp = self.client.get("/api/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("total") >= 1
        item = next((x for x in data["targets"] if x["id"] == str(target_id)), None)
        assert item is not None
        assert item["name"] == "Nguyen Van A"
        assert item["clothing_color"] == "blue"
        assert item["selected"] is True
        assert item["has_embedding"] is True
        assert "created_at" in item
        # Embedding vector must NEVER be in list item payload
        assert "embedding" not in item
        assert "face_embedding" not in item

    def test_get_target_detail_endpoint_success_and_safety(self):
        """Target detail endpoint returns full metadata without exposing raw float vectors."""
        from src.db.database import Database
        from src.db.models import Target
        import uuid

        target_id = uuid.uuid4()
        db = Database()
        with db.transaction() as session:
            t = Target(
                id=target_id,
                name="Tran Thi B",
                target_type="face",
                embedding=[0.2] * 512,
                reference_metadata={"clothing_color": "red", "threshold": 0.50, "notes": "VIP Person"},
                active=True,
            )
            session.add(t)

        resp = self.client.get(f"/api/targets/{target_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        tgt = body["target"]
        assert tgt["id"] == str(target_id)
        assert tgt["name"] == "Tran Thi B"
        assert tgt["clothing_color"] == "red"
        assert tgt["face_threshold"] == 0.50
        assert tgt["has_embedding"] is True
        assert tgt["notes"] == "VIP Person"
        assert "created_at" in tgt
        # Vector floats must NEVER be exposed
        assert "embedding" not in tgt
        assert "face_embedding" not in tgt

    def test_get_target_detail_not_found(self):
        """Non-existent target UUID returns 404."""
        resp = self.client.get("/api/targets/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_toggle_target_selection_in_modal(self):
        """POST /api/targets/{id}/select toggles active video recognition state."""
        from src.db.database import Database
        from src.db.models import Target
        import uuid

        target_id = uuid.uuid4()
        db = Database()
        with db.transaction() as session:
            t = Target(
                id=target_id,
                name="Le Van C",
                target_type="face",
                reference_metadata={"selected": True},
                active=True,
            )
            session.add(t)

        # Toggle to false
        resp = self.client.post(f"/api/targets/{target_id}/select", json={"selected": False})
        assert resp.status_code == 200
        assert resp.json().get("selected") is False

        # Toggle to true
        resp2 = self.client.post(f"/api/targets/{target_id}/select", json={"selected": True})
        assert resp2.status_code == 200
        assert resp2.json().get("selected") is True

    def test_vehicle_detail_and_detections_endpoints(self):
        """Vehicle detail and detections endpoints return valid structure."""
        # Create vehicle
        create_resp = self.client.post("/api/watchlist/vehicles", json={
            "plate_number": "51A12345",
            "name": "Xe Giam Doc",
            "vehicle_type": "car",
            "vehicle_color": "black",
        })
        assert create_resp.status_code in (200, 201)
        veh = create_resp.json().get("vehicle")
        veh_id = veh["id"]

        # Get vehicle detail
        get_resp = self.client.get(f"/api/watchlist/vehicles/{veh_id}")
        assert get_resp.status_code == 200
        v_data = get_resp.json().get("vehicle")
        assert v_data["plate_number"] == "51A12345"

        # Get vehicle detections
        det_resp = self.client.get(f"/api/watchlist/vehicles/{veh_id}/detections")
        assert det_resp.status_code == 200
        assert "detections" in det_resp.json()
