"""Integration tests for FastAPI Agent endpoints."""

import pytest
from fastapi.testclient import TestClient

from src.ui.web_server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_agent_chat_endpoint_success(client):
    response = client.post(
        "/api/agent/chat",
        json={
            "message": "Kiểm tra trạng thái camera_01",
            "thread_id": "api_test_thread_1",
            "user_id": "test_operator",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["thread_id"] == "api_test_thread_1"
    assert "reply" in data
    assert len(data["reply"]) > 0
    assert "tools_called" in data


def test_agent_chat_endpoint_validation_error(client):
    # Empty message should fail validation
    response = client.post(
        "/api/agent/chat",
        json={"message": ""},
    )
    assert response.status_code == 422


def test_agent_conversation_history_and_reset(client):
    thread_id = "api_test_history_thread"

    # 1. Send first message
    r1 = client.post(
        "/api/agent/chat",
        json={
            "message": "Tra cứu sự kiện",
            "thread_id": thread_id,
        },
    )
    assert r1.status_code == 200

    # 2. Get conversation
    r2 = client.get(f"/api/agent/conversations/{thread_id}")
    assert r2.status_code == 200
    data2 = r2.json()
    assert data2["status"] in ("success", "not_found")
    assert "messages" in data2

    # 3. Delete / reset conversation
    r3 = client.delete(f"/api/agent/conversations/{thread_id}")
    assert r3.status_code == 200
    assert r3.json()["status"] == "success"


def test_agent_privileged_spoofing_rejected(client):
    """Verify untrusted client cannot claim privileged admin identity."""
    response = client.post(
        "/api/agent/chat",
        json={
            "message": "Tra cứu sự kiện",
            "thread_id": "spoof_thread",
            "user_id": "admin",
        },
    )
    assert response.status_code == 403
    assert "Forbidden" in response.json().get("detail", "")
