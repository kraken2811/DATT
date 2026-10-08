"""Security and regression tests for User / Thread Memory Isolation in LangGraph."""

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.agent.graph import build_agent_graph, run_agent_message
from src.agent.memory.checkpoint import (
    clear_thread_checkpoint,
    get_checkpointer,
    make_thread_config,
)


def test_cross_user_secret_leak_prevention():
    """Verify that User B cannot read User A's secret on the exact same thread_id."""
    # Shared thread ID across two different users
    shared_thread = "shared-security-thread"

    # User A stores secret marker
    resp_a = run_agent_message(
        content="My secret marker is ALPHA-9381",
        thread_id=shared_thread,
        user_id="user_a",
    )
    assert resp_a["status"] == "success"

    # User B queries the same thread
    resp_b = run_agent_message(
        content="What secret marker did I tell you?",
        thread_id=shared_thread,
        user_id="user_b",
    )
    assert resp_b["status"] == "success"
    # User B MUST NOT receive ALPHA-9381
    assert "ALPHA-9381" not in resp_b["reply"]

    # User A returns to the same thread and asks for their secret marker
    resp_a_return = run_agent_message(
        content="What secret marker did I tell you?",
        thread_id=shared_thread,
        user_id="user_a",
    )
    assert resp_a_return["status"] == "success"
    # User A MUST retain their secret marker
    assert "ALPHA-9381" in resp_a_return["reply"]


def test_same_user_different_thread_isolation():
    """Verify that the same user has separate states across different threads."""
    user = "operator_alpha"

    # Store in thread 1
    run_agent_message(
        content="My secret marker is ALPHA-9381",
        thread_id="thread_01",
        user_id=user,
    )

    # Ask in thread 2
    resp_t2 = run_agent_message(
        content="What secret marker did I tell you?",
        thread_id="thread_02",
        user_id=user,
    )
    assert "ALPHA-9381" not in resp_t2["reply"]


def test_different_user_different_thread_isolation():
    """Verify different users on different threads are completely isolated."""
    resp_x = run_agent_message(
        content="My secret marker is ALPHA-1111",
        thread_id="thread_x",
        user_id="user_x",
    )
    assert resp_x["status"] == "success"

    resp_y = run_agent_message(
        content="What secret marker did I tell you?",
        thread_id="thread_y",
        user_id="user_y",
    )
    assert "ALPHA-1111" not in resp_y["reply"]


def test_persistence_after_backend_restart():
    """Simulate backend restart by reloading checkpointer from storage."""
    thread_id = "restart-test-thread"
    user_id = "admin_persisted"

    # 1. User records marker
    run_agent_message(
        content="My secret marker is ALPHA-9381",
        thread_id=thread_id,
        user_id=user_id,
    )

    # 2. Simulate server restart: verify state can be read back from checkpointer config
    checkpointer = get_checkpointer()
    config = make_thread_config(thread_id, user_id=user_id)
    tuple_state = checkpointer.get_tuple(config)
    assert tuple_state is not None
    assert tuple_state.checkpoint is not None

    # Verify channel values contain messages
    channel_vals = tuple_state.checkpoint.get("channel_values", {})
    msgs = channel_vals.get("messages", [])
    assert len(msgs) >= 1
    assert any("ALPHA-9381" in str(getattr(m, "content", "")) for m in msgs)


def test_thread_clearing_and_deletion():
    """Verify that clear_thread_checkpoint wipes saved conversation."""
    thread_id = "delete-test-thread"
    user_id = "user_delete_test"

    run_agent_message(
        content="My secret marker is ALPHA-9381",
        thread_id=thread_id,
        user_id=user_id,
    )

    # Clear checkpoint
    clear_thread_checkpoint(thread_id, user_id=user_id)

    # Query again
    resp_after = run_agent_message(
        content="What secret marker did I tell you?",
        thread_id=thread_id,
        user_id=user_id,
    )
    assert "ALPHA-9381" not in resp_after["reply"]
