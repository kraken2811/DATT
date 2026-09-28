"""Integration tests for FastAPI Target Registration and Video Source Endpoints.

Verifies TEST 15:
- POST /api/set_video_source with valid/invalid payload
- GET /api/video_source
- POST /api/register_target (JSON and multipart form data)
- GET /api/targets
- DELETE /api/targets/{target_id}
"""

import io
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import numpy as np

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.recognition.target_matcher import target_manager
from src.ui.web_server import app


class TestTargetAPI(unittest.TestCase):
    """Test suite for Target & Video Source FastAPI endpoints."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        target_manager.clear()

    def tearDown(self) -> None:
        target_manager.clear()

    def test_get_targets_empty(self) -> None:
        """GET /api/targets returns empty list initially."""
        resp = self.client.get("/api/targets")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("targets"), [])

    def test_register_target_json_color_only(self) -> None:
        """POST /api/register_target via JSON with clothing color."""
        payload = {
            "name": "Detective Miller",
            "color": "blue",
            "threshold": 0.45,
        }
        resp = self.client.post("/api/register_target", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        target_info = data.get("target")
        self.assertEqual(target_info.get("name"), "Detective Miller")
        self.assertEqual(target_info.get("clothing_color"), "blue")
        self.assertFalse(target_info.get("has_face"))

        # Verify listed in GET /api/targets
        list_resp = self.client.get("/api/targets")
        self.assertEqual(list_resp.status_code, 200)
        self.assertEqual(len(list_resp.json().get("targets")), 1)

    def test_register_target_missing_name_fails(self) -> None:
        """POST /api/register_target with empty name returns HTTP 400."""
        payload = {"name": "", "color": "red"}
        resp = self.client.post("/api/register_target", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Target name is required", resp.json().get("message", ""))

    def test_register_target_missing_features_fails(self) -> None:
        """POST /api/register_target with no face and no color returns HTTP 400."""
        payload = {"name": "No Features"}
        resp = self.client.post("/api/register_target", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at least a valid face image or a clothing color", resp.json().get("message", ""))

    def test_register_target_multipart_form(self) -> None:
        """POST /api/register_target via multipart/form-data."""
        mock_embedding = np.random.randn(512).astype(np.float32)
        mock_embedding /= np.linalg.norm(mock_embedding)

        with patch("src.recognition.target_matcher.face_embedder.extract_face_embedding", return_value=mock_embedding):
            # Create a simple 1x1 BMP/JPEG byte stream
            import cv2
            img = np.ones((50, 50, 3), dtype=np.uint8) * 200
            _, img_encoded = cv2.imencode(".jpg", img)
            file_bytes = io.BytesIO(img_encoded.tobytes())

            files = {"face_image": ("face.jpg", file_bytes, "image/jpeg")}
            data = {"name": "Agent Carter", "color": "red", "threshold": "0.50"}

            resp = self.client.post("/api/register_target", data=data, files=files)
            self.assertEqual(resp.status_code, 200)
            res_json = resp.json()
            self.assertEqual(res_json.get("status"), "ok")
            target = res_json.get("target")
            self.assertEqual(target.get("name"), "Agent Carter")
            self.assertTrue(target.get("has_face"))
            self.assertEqual(target.get("clothing_color"), "red")

    def test_delete_target(self) -> None:
        """DELETE /api/targets/{target_id} deletes target."""
        target = target_manager.register_target(name="Target to Delete", clothing_color="green")
        tid = target.id

        del_resp = self.client.delete(f"/api/targets/{tid}")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json().get("status"), "ok")

        # Deleting non-existent target returns HTTP 404
        del_again = self.client.delete(f"/api/targets/{tid}")
        self.assertEqual(del_again.status_code, 404)

    def test_set_video_source_api_validation(self) -> None:
        """POST /api/set_video_source validates empty source."""
        resp = self.client.post("/api/set_video_source", json={"type": "local", "source": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cannot be empty", resp.json().get("message", ""))

    def test_get_video_source_api(self) -> None:
        """GET /api/video_source returns source status."""
        resp = self.client.get("/api/video_source")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("status"), "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
