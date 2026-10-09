"""Automated tests for persistent multi-conversation management and LangGraph checkpoint restoration."""
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.agent import graph, nodes
from src.agent.api.auth import create_auth_token
from src.agent.config import agent_config
from src.agent.conversations import (
    create_conversation,
    derive_conversation_title,
    get_conversation,
    list_conversations,
    rename_conversation,
    touch_conversation,
)
from src.agent.memory.checkpoint import clear_thread_checkpoint, get_checkpointer, make_thread_config
from src.db.database import Database
from src.db.models import (
    AgentConversation,
    Base,
    Camera,
    PlateEvent,
    Target,
    VehicleEvent,
    VehicleWatchlist,
    VehicleWatchlistResult,
)
from src.ui.web_server import app


@pytest.fixture
def persistence_db(tmp_path, monkeypatch):
    url = 'sqlite:///' + (tmp_path / 'persistence.db').as_posix()
    db = Database(url)
    Base.metadata.create_all(db.engine)
    monkeypatch.setattr(agent_config, 'get_database', lambda: Database(url))
    monkeypatch.setattr(nodes, 'get_llm', lambda: nodes.MockChatModel())
    monkeypatch.setenv('DATT_STRICT_AUTH', '0')
    monkeypatch.setenv('DATT_REQUIRE_OPERATIONAL_AUTH', '0')
    monkeypatch.setenv('DATT_AGENT_AUTH_SECRET', 'test_secret_key_at_least_32_characters_long_12345')
    yield db
    db.dispose()


@pytest.fixture
def api_client(persistence_db):
    return TestClient(app)


# 1, 2, 3, 4, 5, 6, 7: Create A, message A, create B, switch back to A, restore checkpoint, continue context, verify B independent
def test_conversation_lifecycle_and_checkpoint_continuity(persistence_db):
    saver = InMemorySaver()
    user_id = "operator_alpha"

    # Step 1: Create Conv A
    with persistence_db.transaction() as session:
        conv_a = create_conversation(session, user_id=user_id, title="Hội thoại A", thread_id="thread_A")
        assert conv_a.thread_id == "thread_A"

    # Step 2: Send multiple messages in A
    r_a1 = graph.run_agent_message("Kiểm tra trạng thái camera_01", thread_id="thread_A", user_id=user_id, checkpointer=saver)
    assert r_a1["status"] == "success"
    r_a2 = graph.run_agent_message("Secret marker của tôi là ALPHA-777", thread_id="thread_A", user_id=user_id, checkpointer=saver)
    assert r_a2["status"] == "success"

    # Step 3: Create Conv B without deleting A
    with persistence_db.transaction() as session:
        conv_b = create_conversation(session, user_id=user_id, title="Hội thoại B", thread_id="thread_B")
        assert conv_b.thread_id == "thread_B"

    r_b1 = graph.run_agent_message("Camera nào hiện đang đông nhất?", thread_id="thread_B", user_id=user_id, checkpointer=saver)
    assert r_b1["status"] == "success"

    # Verify both exist in registry
    with persistence_db.transaction() as session:
        items, count = list_conversations(session, user_id=user_id)
        assert count == 2
        tids = [i.thread_id for i in items]
        assert "thread_A" in tids and "thread_B" in tids

    # Step 4, 5, 6: Switch back to A, restore checkpoint, continue using previous context
    r_a3 = graph.run_agent_message("Mã ca trực bí mật của tôi là gì?", thread_id="thread_A", user_id=user_id, checkpointer=saver)
    assert "ALPHA-777" in r_a3["reply"]

    # Step 7: Verify Conv B remains independent
    r_b2 = graph.run_agent_message("Mã ca trực bí mật của tôi là gì?", thread_id="thread_B", user_id=user_id, checkpointer=saver)
    assert "ALPHA-777" not in r_b2["reply"]
    assert "không có thông tin" in r_b2["reply"]


# 8 & 9: Checkpoint survives new graph instance (reopening / simulated backend restart)
def test_conversation_restoration_across_agent_restart(persistence_db):
    saver = InMemorySaver()
    user_id = "op_restart_test"
    thread_id = "thread_restart_1"

    # First session
    graph.run_agent_message("Mã ca trực là ALPHA-999", thread_id=thread_id, user_id=user_id, checkpointer=saver)

    # Simulated restart: Build brand new graph instance with same saver/checkpointer
    new_graph = graph.build_agent_graph(checkpointer=saver)
    config = graph.make_thread_config(thread_id, user_id=user_id)
    state = new_graph.get_state(config)
    assert state is not None and len(state.values.get("messages", [])) > 0

    # Query with new graph
    res = graph.run_agent_message("Mã ca trực của tôi là gì?", thread_id=thread_id, user_id=user_id, checkpointer=saver)
    assert "ALPHA-999" in res["reply"]


# 10: List conversations sorted by recent activity
def test_list_conversations_sorted_by_activity(persistence_db):
    user_id = "user_activity_test"
    with persistence_db.transaction() as session:
        c1 = create_conversation(session, user_id, title="C1", thread_id="t1")
        c2 = create_conversation(session, user_id, title="C2", thread_id="t2")
        session.flush()
        # Touch c1 later with future timestamp
        c1.last_message_at = c2.last_message_at + timedelta(seconds=10)

    with persistence_db.transaction() as session:
        items, _ = list_conversations(session, user_id)
        assert len(items) == 2
        # Most recently touched should be first
        assert items[0].thread_id == "t1"


# 11: Rename a conversation
def test_rename_conversation_endpoint(api_client, persistence_db):
    user_id = "test_rename_user"
    token = create_auth_token(user_id)
    with persistence_db.transaction() as session:
        create_conversation(session, user_id=user_id, title="Tên cũ", thread_id="t_rename")

    resp = api_client.patch(
        "/api/agent/conversations/t_rename",
        json={"title": "Tên mới cập nhật"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["conversation"]["title"] == "Tên mới cập nhật"

    # Verify in DB
    with persistence_db.transaction() as session:
        conv = get_conversation(session, "t_rename", user_id)
        assert conv.title == "Tên mới cập nhật"


# 12: Delete only the selected conversation
def test_delete_only_selected_conversation(api_client, persistence_db):
    user_id = "test_del_user"
    token = create_auth_token(user_id)
    with persistence_db.transaction() as session:
        create_conversation(session, user_id=user_id, title="Giữ lại", thread_id="t_keep")
        create_conversation(session, user_id=user_id, title="Xóa bỏ", thread_id="t_delete")

    resp = api_client.delete(
        "/api/agent/conversations/t_delete",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    # Verify t_delete gone, t_keep retained
    with persistence_db.transaction() as session:
        items, total = list_conversations(session, user_id)
        assert total == 1
        assert items[0].thread_id == "t_keep"


# 13: Creating new conversation via API NEVER deletes previous conversations
def test_create_conversation_does_not_delete_previous(api_client, persistence_db):
    user_id = "test_nodelete_user"

    # Create Conv 1
    r1 = api_client.post("/api/agent/conversations", json={"title": "Hội thoại 1", "user_id": user_id})
    assert r1.status_code == 200
    t1 = r1.json()["conversation"]["thread_id"]

    # Create Conv 2
    r2 = api_client.post("/api/agent/conversations", json={"title": "Hội thoại 2", "user_id": user_id})
    assert r2.status_code == 200
    t2 = r2.json()["conversation"]["thread_id"]

    assert t1 != t2

    # Verify both exist
    r_list = api_client.get(f"/api/agent/conversations?user_id={user_id}")
    assert r_list.status_code == 200
    tids = [c["thread_id"] for c in r_list.json()["conversations"]]
    assert t1 in tids and t2 in tids


# 14: Cross-user access denial
def test_cross_user_access_denial(api_client, persistence_db):
    with persistence_db.transaction() as session:
        create_conversation(session, user_id="user_alice", title="Alice Private", thread_id="alice_thread")

    # Bob attempts to get Alice's conversation
    resp_get = api_client.get("/api/agent/conversations/alice_thread?user_id=user_bob")
    assert resp_get.status_code == 403

    # Bob attempts to rename Alice's conversation
    resp_patch = api_client.patch(
        "/api/agent/conversations/alice_thread",
        json={"title": "Hacked", "user_id": "user_bob"},
    )
    assert resp_patch.status_code == 403

    # Bob attempts to delete Alice's conversation
    resp_del = api_client.delete("/api/agent/conversations/alice_thread?user_id=user_bob")
    assert resp_del.status_code == 403

    # Bob attempts to post message to Alice's conversation
    resp_chat = api_client.post(
        "/api/agent/chat",
        json={"message": "Infiltration", "thread_id": "alice_thread", "user_id": "user_bob"},
    )
    assert resp_chat.status_code == 403


# 15: Auto-derive conversation title from first user message
def test_deterministic_conversation_title_derivation():
    assert derive_conversation_title("Tìm xe biển số 30A-12345") == "Lịch sử xe 30A-12345"
    assert derive_conversation_title("Tìm lịch sử chiếc xe có tên Xe của Long") == "Lịch sử xe của Long"
    assert derive_conversation_title("Khuôn mặt Long khớp lúc nào?") == "Tra cứu khuôn mặt Long"
    assert derive_conversation_title("Kiểm tra camera_01 đang online không") == "Kiểm tra camera_01"
    assert derive_conversation_title("Cho tôi xem thống kê phương tiện") == "Thống kê phương tiện"
    assert derive_conversation_title("Hướng dẫn khắc phục camera mất kết nối") == "Hướng dẫn khắc phục sự cố"


# 16: Restored Face History follow-up across turns in active thread
def test_restored_face_history_follow_up(persistence_db):
    saver = InMemorySaver()
    user_id = "op_face_followup"
    thread_id = "thread_face_followup"
    LONG_ID = UUID('11111111-1111-4111-8111-111111111111')

    with persistence_db.transaction() as session:
        session.add(Target(id=LONG_ID, name='Long', target_type='face', active=True))
        session.add(Camera(id=UUID('33333333-3333-4333-8333-333333333333'), registry_key='CAM_GATE', name='Cổng chính', source_type='local', source='cam.mp4'))

    # Turn 1: Discuss person Long
    r1 = graph.run_agent_message("Long đã được nhận diện ở camera nào?", thread_id=thread_id, user_id=user_id, checkpointer=saver)
    assert "search_watchlist" in r1["tools_called"]

    # Turn 2: Follow-up question referencing 'người này'
    r2 = graph.run_agent_message("Lần gần nhất người này xuất hiện là khi nào?", thread_id=thread_id, user_id=user_id, checkpointer=saver)
    assert str(LONG_ID) in r2["reply"] or "Long" in r2["reply"]


# 17: Restored Vehicle History follow-up across turns in active thread
def test_restored_vehicle_history_follow_up(persistence_db):
    saver = InMemorySaver()
    user_id = "op_veh_followup"
    thread_id = "thread_veh_followup"

    # Turn 1: Discuss vehicle 30A-12345
    r1 = graph.run_agent_message("Tìm xe biển số 30A-12345.", thread_id=thread_id, user_id=user_id, checkpointer=saver)
    assert "30A12345" in r1["reply"]

    # Turn 2: Follow-up referencing 'xe này'
    r2 = graph.run_agent_message("Hôm qua xe này có xuất hiện không?", thread_id=thread_id, user_id=user_id, checkpointer=saver)
    assert "30A12345" in r2["reply"]
