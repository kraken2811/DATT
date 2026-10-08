"""Unit tests for LangGraph agent orchestration and short-term memory."""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.agent.graph import build_agent_graph, run_agent_message


@pytest.fixture
def memory_checkpointer():
    return MemorySaver()


def test_agent_graph_compilation(memory_checkpointer):
    graph = build_agent_graph(checkpointer=memory_checkpointer)
    assert graph is not None


def test_agent_camera_status_turn(memory_checkpointer):
    # Single turn querying camera status
    res = run_agent_message(
        content="Kiểm tra trạng thái camera_01",
        thread_id="test_thread_001",
        user_id="operator_1",
        checkpointer=memory_checkpointer,
    )
    assert res["status"] == "success"
    assert "reply" in res
    assert "get_camera_status" in res["tools_called"]


def test_agent_memory_continuity(memory_checkpointer):
    # Turn 1
    res1 = run_agent_message(
        content="Kiểm tra trạng thái camera_01",
        thread_id="thread_continuity_test",
        user_id="user_a",
        checkpointer=memory_checkpointer,
    )
    assert res1["status"] == "success"

    # Turn 2: Follow-up question in the same thread
    res2 = run_agent_message(
        content="Cho tôi xem thống kê lưu lượng xe trong 24h qua",
        thread_id="thread_continuity_test",
        user_id="user_a",
        checkpointer=memory_checkpointer,
    )
    assert res2["status"] == "success"
    assert "get_event_statistics" in res2["tools_called"]


def test_agent_thread_isolation(memory_checkpointer):
    # Thread A
    res_a = run_agent_message(
        content="Kiểm tra trạng thái camera_01",
        thread_id="thread_isolated_A",
        user_id="user_a",
        checkpointer=memory_checkpointer,
    )
    assert res_a["status"] == "success"

    # Thread B has completely separate state
    res_b = run_agent_message(
        content="Tra cứu danh sách theo dõi biển số",
        thread_id="thread_isolated_B",
        user_id="user_b",
        checkpointer=memory_checkpointer,
    )
    assert res_b["status"] == "success"
    assert "search_watchlist" in res_b["tools_called"]


def test_agent_knowledge_rag_turn(memory_checkpointer):
    # Turn querying troubleshooting documentation
    res = run_agent_message(
        content="Hướng dẫn tài liệu khắc phục sự cố camera offline",
        thread_id="thread_rag_test",
        user_id="operator_1",
        checkpointer=memory_checkpointer,
    )
    assert res["status"] == "success"
    assert "get_knowledge" in res["tools_called"]
