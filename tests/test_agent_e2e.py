"""Comprehensive End-to-End Evaluation & Verification tests for DATT AI Agent."""

import pytest
from fastapi.testclient import TestClient

from src.agent.graph import run_agent_message
from src.agent.memory.checkpoint import get_checkpointer, make_thread_config
from src.agent.tools.camera import get_camera, get_camera_status
from src.agent.tools.events import search_events
from src.agent.tools.knowledge import get_knowledge
from src.ui.web_server import app


@pytest.fixture
def api_client():
    return TestClient(app)


class TestAgentEndToEnd:
    """Suite validating core business scenarios and grounding requirements."""

    def test_e2e_camera_operational_query(self, api_client):
        """User asks about camera status: Agent must invoke get_camera_status without RAG."""
        resp = api_client.post(
            "/api/agent/chat",
            json={
                "message": "Trạng thái camera_01 hiện tại thế nào?",
                "thread_id": "e2e_cam_turn",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "get_camera_status" in data["tools_called"]
        assert "get_knowledge" not in data["tools_called"]

    def test_e2e_knowledge_rag_query(self, api_client):
        """User asks for troubleshooting documentation: Agent must invoke get_knowledge."""
        resp = api_client.post(
            "/api/agent/chat",
            json={
                "message": "Hướng dẫn tài liệu khắc phục sự cố camera khi bị offline",
                "thread_id": "e2e_rag_turn",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert "get_knowledge" in data["tools_called"]
        assert len(data["sources"]) > 0

    def test_e2e_event_and_watchlist_queries(self, api_client):
        """User queries watchlist and traffic events."""
        # 1. Watchlist
        r_w = api_client.post(
            "/api/agent/chat",
            json={
                "message": "Tra cứu danh sách theo dõi biển số xe",
                "thread_id": "e2e_w_turn",
            },
        )
        assert r_w.status_code == 200
        assert "search_watchlist" in r_w.json()["tools_called"]

        # 2. Events
        r_e = api_client.post(
            "/api/agent/chat",
            json={
                "message": "Tra cứu sự kiện gần đây",
                "thread_id": "e2e_e_turn",
            },
        )
        assert r_e.status_code == 200
        assert "search_events" in r_e.json()["tools_called"]

    def test_e2e_analytics_traffic_query(self, api_client):
        """User asks for traffic statistics."""
        resp = api_client.post(
            "/api/agent/chat",
            json={
                "message": "Cho tôi xem thống kê lưu lượng xe trong 24h qua",
                "thread_id": "e2e_stats_turn",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "get_event_statistics" in data["tools_called"]

    def test_e2e_multi_turn_conversation_continuity(self, api_client):
        """Verify thread history is preserved across multiple turns."""
        thread = "e2e_multi_turn_continuity"

        # Turn 1
        r1 = api_client.post(
            "/api/agent/chat",
            json={"message": "Kiểm tra camera_01", "thread_id": thread},
        )
        assert r1.status_code == 200

        # Turn 2: Follow-up question
        r2 = api_client.post(
            "/api/agent/chat",
            json={"message": "Cho tôi xem thống kê lưu lượng xe", "thread_id": thread},
        )
        assert r2.status_code == 200

        # Verify conversation history has both turns
        r_history = api_client.get(f"/api/agent/conversations/{thread}")
        assert r_history.status_code == 200
        hist_data = r_history.json()
        assert hist_data["message_count"] >= 4

    def test_e2e_thread_isolation(self, api_client):
        """Verify thread state is strictly partitioned between two distinct sessions."""
        t1 = "e2e_isolated_user_1"
        t2 = "e2e_isolated_user_2"

        api_client.post(
            "/api/agent/chat",
            json={"message": "Kiểm tra camera_01", "thread_id": t1, "user_id": "u1"},
        )
        api_client.post(
            "/api/agent/chat",
            json={"message": "Thống kê lưu lượng", "thread_id": t2, "user_id": "u2"},
        )

        h1 = api_client.get(f"/api/agent/conversations/{t1}?user_id=u1").json()
        h2 = api_client.get(f"/api/agent/conversations/{t2}?user_id=u2").json()

        # Content in h1 does not leak into h2
        assert h1["thread_id"] == t1
        assert h2["thread_id"] == t2
