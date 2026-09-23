"""Tests for FastAPI Web UI Server (Phase 4.4).

Verifies:
1. GET / returns index.html
2. Static assets load (/static/style.css, /static/app.js)
3. Telemetry endpoint: backend online/offline handling
4. Events endpoint
5. Camera endpoint & camera switching
"""

from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import httpx

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ui.web_server import app


class TestWebServer(unittest.TestCase):
    """Test suite for DATT FastAPI monitoring web server."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    # -------------------------------------------------------------------------
    # 1. Root & Static File Delivery
    # -------------------------------------------------------------------------

    def test_root_returns_index_html(self) -> None:
        """GET / must return HTTP 200 and serve static/index.html content."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn("DATT", response.text)
        self.assertIn("Camera Management", response.text)
        self.assertIn("Live Camera Stream", response.text)
        self.assertIn("Realtime AI Telemetry", response.text)
        self.assertIn("Recent Occupancy Events", response.text)

    def test_static_assets_load(self) -> None:
        """Static assets /static/style.css and /static/app.js must be served."""
        css_resp = self.client.get("/static/style.css")
        self.assertEqual(css_resp.status_code, 200)
        self.assertIn("text/css", css_resp.headers.get("content-type", ""))
        self.assertIn("#0e1117", css_resp.text)
        self.assertIn("--accent-cyan", css_resp.text)

        js_resp = self.client.get("/static/app.js")
        self.assertEqual(js_resp.status_code, 200)
        self.assertIn("javascript", js_resp.headers.get("content-type", "").lower())
        self.assertIn("pollTelemetry", js_resp.text)
        self.assertIn("pollEvents", js_resp.text)
        self.assertIn("setupVideoStream", js_resp.text)

    # -------------------------------------------------------------------------
    # 2. Telemetry Endpoint (Backend Online / Offline Handling)
    # -------------------------------------------------------------------------

    def test_telemetry_offline_handling(self) -> None:
        """GET /telemetry when backend is unreachable must return DISCONNECTED schema."""
        # Query with non-existent backend port to simulate offline server
        response = self.client.get("/telemetry?backend_url=http://127.0.0.1:59999")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data.get("status"), "DISCONNECTED")
        self.assertIn("error_message", data)
        self.assertEqual(data.get("people_count"), 0)
        self.assertEqual(data.get("detection_count"), 0)
        self.assertEqual(data.get("track_count"), 0)
        self.assertEqual(data.get("stream_fps"), 0.0)
        self.assertEqual(data.get("processing_fps"), 0.0)
        self.assertIn("device", data)
        self.assertIn("gpu_name", data)
        self.assertIn("vram_mb", data)
        self.assertIn("model_name", data)
        self.assertIn("input_size", data)

    def test_telemetry_online_handling(self) -> None:
        """GET /telemetry when backend is online must forward live AI metrics."""
        mock_payload = {
            "status": "RUNNING",
            "error_message": "",
            "people_count": 5,
            "detection_count": 5,
            "track_count": 5,
            "stream_fps": 30.0,
            "processing_fps": 28.5,
            "yolo_latency_ms": 12.3,
            "pipeline_latency_ms": 15.6,
            "device": "CUDA",
            "gpu_name": "NVIDIA GeForce RTX 4090",
            "vram_mb": 1450.0,
            "model_name": "YOLO11s",
            "input_size": "640x640",
            "camera_id": "camera_01",
            "camera_name": "Tokyo Street Live",
            "last_event": "COUNT_CHANGED",
            "event_count_today": 12,
            "filtered_event_count": 2,
            "last_event_time": "2026-09-23 09:15:20",
            "last_saved_people_count": 5,
        }

        mock_resp = httpx.Response(200, json=mock_payload)
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            response = self.client.get("/telemetry")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get("status"), "RUNNING")
            self.assertEqual(data.get("people_count"), 5)
            self.assertEqual(data.get("camera_name"), "Tokyo Street Live")
            self.assertAlmostEqual(data.get("processing_fps"), 28.5)

    # -------------------------------------------------------------------------
    # 3. Events Endpoint
    # -------------------------------------------------------------------------

    def test_events_endpoint_returns_latest_five_normalized(self) -> None:
        """GET /events must return at most 5 events with standardized fields."""
        raw_events = [
            {"id": i, "timestamp": f"2026-09-23 09:00:{i:02d}", "camera_id": "camera_01", "old_value": i, "new_value": i + 2, "snapshot_path": f"data/events/snap_{i}.jpg"}
            for i in range(1, 8)
        ]
        mock_resp = httpx.Response(200, json={"status": "ok", "events": raw_events, "event_count_today": 7})

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            response = self.client.get("/events?limit=5")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data.get("status"), "ok")
            events = data.get("events", [])
            # Must strictly limit to at most 5 latest events
            self.assertLessEqual(len(events), 5)
            if events:
                ev = events[0]
                self.assertIn("timestamp", ev)
                self.assertIn("camera_id", ev)
                self.assertIn("old_count", ev)
                self.assertIn("new_count", ev)
                self.assertIn("snapshot_id", ev)

    # -------------------------------------------------------------------------
    # 4. Camera Endpoint & Switching
    # -------------------------------------------------------------------------

    def test_camera_list_endpoint(self) -> None:
        """GET /cameras must return camera list and active camera ID."""
        response = self.client.get("/cameras")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("cameras", data)
        self.assertIn("active_camera_id", data)
        self.assertIsInstance(data.get("cameras"), list)

    def test_switch_camera_missing_param_returns_400(self) -> None:
        """GET /switch_camera without camera_id must return HTTP 400 Bad Request."""
        response = self.client.get("/switch_camera")
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data.get("status"), "error")

    def test_switch_camera_success(self) -> None:
        """GET and POST /switch_camera with id must forward switch command."""
        mock_resp = httpx.Response(200, json={"status": "ok", "camera_id": "camera_02", "message": "Switched"})
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_resp
            # GET test
            resp_get = self.client.get("/switch_camera?id=camera_02")
            self.assertEqual(resp_get.status_code, 200)
            self.assertEqual(resp_get.json().get("status"), "ok")

            # POST test
            resp_post = self.client.post("/switch_camera", json={"camera_id": "camera_02"})
            self.assertEqual(resp_post.status_code, 200)
            self.assertEqual(resp_post.json().get("status"), "ok")

    # -------------------------------------------------------------------------
    # 5. Snapshot API
    # -------------------------------------------------------------------------

    def test_event_snapshot_missing_params(self) -> None:
        """GET /event_snapshot without path or id must return HTTP 400."""
        response = self.client.get("/event_snapshot")
        self.assertEqual(response.status_code, 400)


def run_tests():
    """CLI runner for tests."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestWebServer)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    run_tests()
