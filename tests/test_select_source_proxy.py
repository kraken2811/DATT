"""Source-selection proxy failures must be actionable and distinguishable."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.ui.web_server import app


@pytest.mark.parametrize("error,status,code", [
    (httpx.ConnectError("offline"), 503, "BACKEND_UNAVAILABLE"),
    (httpx.ReadTimeout(""), 504, "BACKEND_TIMEOUT"),
])
def test_transport_failure(error, status, code):
    with patch("src.ui.web_server.preview_manager.stop_preview"), patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=error
    ):
        response = TestClient(app).post("/api/select_source", json={"camera_id": "test"})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["message"]


@pytest.mark.parametrize("upstream,status,code", [
    (httpx.Response(200, text="<html>tunnel</html>"), 502, "BACKEND_INVALID_RESPONSE"),
    (httpx.Response(409, json={"code": "CAMERA_DISABLED"}), 409, "CAMERA_DISABLED"),
    (httpx.Response(503, json={"code": "MANAGER_UNAVAILABLE"}), 503, "MANAGER_UNAVAILABLE"),
    (httpx.Response(200, json={"code": "OK"}), 200, "OK"),
])
def test_upstream_response(upstream, status, code):
    with patch("src.ui.web_server.preview_manager.stop_preview"), patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=upstream
    ) as post:
        response = TestClient(app).post("/api/select_source", json={"camera_id": "test"})
    assert response.status_code == status
    assert response.json()["code"] == code
    assert post.call_args.kwargs["json"] == {"camera_id": "test"}
