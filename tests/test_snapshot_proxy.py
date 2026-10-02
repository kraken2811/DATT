"""A missing snapshot and an unavailable backend are different failures."""
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from src.ui.web_server import app


@pytest.mark.parametrize("result,expected", [
    (httpx.ConnectError("offline"), 503),
    (httpx.ReadTimeout(""), 504),
    (httpx.Response(404), 404),
    (httpx.Response(500), 500),
    (httpx.Response(200, content=b"jpeg"), 200),
])
def test_snapshot_proxy_status(result, expected):
    storage = Mock()
    storage.materialize.side_effect = FileNotFoundError
    upstream = AsyncMock()
    if isinstance(result, Exception):
        upstream.side_effect = result
    else:
        upstream.return_value = result
    with patch("src.ui.web_server.get_storage", return_value=storage), patch(
        "httpx.AsyncClient.get", upstream
    ):
        response = TestClient(app).get("/event_snapshot?path=data/events/missing.jpg")
    assert response.status_code == expected
    if expected == 200:
        assert response.content == b"jpeg"


def test_unknown_legacy_event_does_not_proxy_empty_path():
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as upstream:
        response = TestClient(app).get("/event_snapshot?id=-999999")
    assert response.status_code == 404
    upstream.assert_not_called()
