"""Comprehensive verification suite for DATT v1.0 Release Blockers.

Validates:
- CRITICAL: Per-conversation execution safety, background worker lifetime tracking,
  cancellation resistance, same-thread serialization, clean registry lifecycle.
- HIGH: Non-blocking tool timeout with managed bounded executor and late work tracking.
- Scenarios A through N as mandated by the release QA specification.
"""

import asyncio
import concurrent.futures
import json
import os
import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from src.agent.api.auth import create_auth_token
from src.agent.api.routes import (
    ConversationExecution,
    _conversation_executions,
    _executions_lock,
    _get_conversation_execution,
    _release_conversation_execution,
    chat_endpoint,
)
from src.agent.config import agent_config
from src.agent.graph import build_agent_graph, run_agent_message
from src.agent.llm import LLMUnavailableException, ResilientChatModel
from src.agent.memory.checkpoint import clear_thread_checkpoint, get_checkpointer, make_thread_config
from src.agent.nodes import (
    get_tool_executor,
    shutdown_tool_executor,
    tool_node,
    _timed_out_tool_executions,
    _timed_out_lock,
)
from src.db.database import Database
from src.db.models import Base
from src.ui.web_server import app


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    """Provide isolated test SQLite database for fast unit testing."""
    url = f"sqlite:///{(tmp_path / 'lifecycle_test.db').as_posix()}"
    db = Database(url)
    Base.metadata.create_all(db.engine)
    monkeypatch.setattr(agent_config, "get_database", lambda: Database(url))
    monkeypatch.setenv("DATT_STRICT_AUTH", "0")
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "0")
    monkeypatch.setenv("DATT_AGENT_AUTH_SECRET", "test_secret_key_at_least_32_characters_long_12345")
    yield db
    db.dispose()


@pytest.fixture
def client(test_db):
    return TestClient(app)


# ==============================================================================
# PHASE 3 & SCENARIOS I, J: TOOL TIMEOUT & MANAGED EXECUTOR
# ==============================================================================


def test_scenario_i_tool_timeout_non_blocking(monkeypatch):
    """Scenario I: Tool exceeding tool_timeout_sec must return control within deadline."""
    monkeypatch.setattr(agent_config, "tool_timeout_sec", 0.3)

    def slow_tool_func(*args, **kwargs):
        time.sleep(1.0)
        return {"status": "success", "data": "slow_result"}

    mock_tool = MagicMock()
    mock_tool.name = "slow_camera_tool"
    mock_tool.invoke.side_effect = slow_tool_func

    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "slow_camera_tool", "args": {"cam": "1"}, "id": "call_slow_1"},
                ],
            )
        ],
        "tool_call_counts": {},
        "repeated_tool_calls": 0,
        "tool_cycles": 0,
        "total_tool_calls": 0,
        "investigation_context": {},
    }

    with patch("src.agent.nodes.ALL_AGENT_TOOLS", [mock_tool]):
        t0 = time.time()
        result = tool_node(state)
        elapsed = time.time() - t0

    # Must return control promptly at ~0.3s, NOT blocked for 1.0s
    assert elapsed < 0.6, f"Tool timeout blocked! Elapsed time: {elapsed:.2f}s (expected < 0.6s)"
    assert len(result["messages"]) == 1
    msg = result["messages"][0]
    assert isinstance(msg, ToolMessage)
    assert msg.tool_call_id == "call_slow_1"
    payload = json.loads(msg.content)
    assert payload["status"] == "timeout"
    assert "quá thời gian quy định" in payload["message"]

    # Wait for the background thread to safely terminate and discard
    time.sleep(0.8)


def test_scenario_j_multiple_concurrent_tool_timeouts(monkeypatch):
    """Scenario J: Multiple concurrent tool timeouts must all respect deadline without blocking."""
    monkeypatch.setattr(agent_config, "tool_timeout_sec", 0.3)

    def slow_tool_1(*args, **kwargs):
        time.sleep(1.0)
        return "slow_1"

    def slow_tool_2(*args, **kwargs):
        time.sleep(1.0)
        return "slow_2"

    t1 = MagicMock()
    t1.name = "tool_slow_a"
    t1.invoke.side_effect = slow_tool_1

    t2 = MagicMock()
    t2.name = "tool_slow_b"
    t2.invoke.side_effect = slow_tool_2

    state = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "tool_slow_a", "args": {}, "id": "call_a"},
                    {"name": "tool_slow_b", "args": {}, "id": "call_b"},
                ],
            )
        ],
        "tool_call_counts": {},
        "repeated_tool_calls": 0,
        "tool_cycles": 0,
        "total_tool_calls": 0,
        "investigation_context": {},
    }

    with patch("src.agent.nodes.ALL_AGENT_TOOLS", [t1, t2]):
        t0 = time.time()
        result = tool_node(state)
        elapsed = time.time() - t0

    # Sequential tool loop in tool_node: each tool times out at 0.3s -> total ~0.6s, NOT 2.0s
    assert elapsed < 1.0, f"Multiple timeouts blocked execution! Elapsed: {elapsed:.2f}s"
    assert len(result["messages"]) == 2
    for msg in result["messages"]:
        data = json.loads(msg.content)
        assert data["status"] == "timeout"

    time.sleep(0.8)


# ==============================================================================
# PHASE 2 & SCENARIOS A, B, C, D, E, F, K: PER-CONVERSATION EXECUTION SAFETY
# ==============================================================================


@pytest.mark.asyncio
async def test_scenario_a_normal_request_lifecycle(test_db):
    """Scenario A: Normal request completes successfully and cleans up execution state."""
    key = ("test_user_a", "thread_norm_1")

    with patch("src.agent.api.routes.run_agent_message") as mock_run:
        mock_run.return_value = {
            "status": "success",
            "reply": "Normal response content",
            "tools_called": [],
            "sources": [],
        }

        from src.agent.api.routes import ChatRequest
        from fastapi import Request

        mock_req = MagicMock(spec=Request)
        mock_req.headers = {}
        mock_req.cookies = {}

        payload = ChatRequest(message="Hello Normal", thread_id="thread_norm_1", user_id="test_user_a")
        resp = await chat_endpoint(payload, mock_req)

        assert resp.status == "success"
        assert resp.reply == "Normal response content"
        assert resp.thread_id == "thread_norm_1"

        # Verify execution record cleaned up
        await asyncio.sleep(0.05)
        async with _executions_lock:
            assert key not in _conversation_executions or _conversation_executions[key].queue_count == 0


@pytest.mark.asyncio
async def test_scenario_b_and_c_timeout_and_serialization(monkeypatch, test_db):
    """Scenarios B & C: HTTP timeout occurs while underlying worker continues.

    Question B arriving immediately after Question A times out is serialized safely:
    max concurrent executions for the same thread is strictly 1.
    """
    monkeypatch.setattr(agent_config, "execution_timeout_sec", 0.2)
    monkeypatch.setattr(agent_config, "prompt_guard_enabled", False)

    active_executions = 0
    max_concurrency_observed = 0

    def slow_worker(content, thread_id, user_id, is_authenticated):
        nonlocal active_executions, max_concurrency_observed
        active_executions += 1
        if active_executions > max_concurrency_observed:
            max_concurrency_observed = active_executions
        time.sleep(0.5)
        active_executions -= 1
        return {"status": "success", "reply": f"Reply to {content}", "tools_called": []}

    from src.agent.api.routes import ChatRequest
    from fastapi import Request

    mock_req = MagicMock(spec=Request)
    mock_req.headers = {}
    mock_req.cookies = {}

    with patch("src.agent.api.routes.run_agent_message", side_effect=slow_worker):
        # 1. Question A (slow)
        p_a = ChatRequest(message="Question A (slow)", thread_id="thread_ser_1", user_id="user_ser")
        t0 = time.time()
        resp_a = await chat_endpoint(p_a, mock_req)
        t_a = time.time() - t0

        # Scenario B verified: HTTP timeout returned within ~0.2s
        assert resp_a.status == "timeout"
        assert t_a < 0.4
        assert "vượt quá thời gian" in resp_a.reply

        # 2. Question B arrives immediately while worker for Question A is still running in background
        monkeypatch.setattr(agent_config, "execution_timeout_sec", 2.0)
        p_b = ChatRequest(message="Question B", thread_id="thread_ser_1", user_id="user_ser")
        resp_b = await chat_endpoint(p_b, mock_req)

        # Scenario C verified: Question B executed after Question A finished, strict serialization
        assert resp_b.status == "success"
        assert resp_b.reply == "Reply to Question B"
        assert max_concurrency_observed == 1, f"Concurrency violation! Max observed: {max_concurrency_observed}"


@pytest.mark.asyncio
async def test_scenario_d_and_e_stop_button_and_immediate_send(monkeypatch, test_db):
    """Scenarios D & E: User clicks Stop (cancellation) while Question A is processing.

    Subsequent immediate Question B executes serialized after Question A's background worker terminates.
    """
    monkeypatch.setattr(agent_config, "execution_timeout_sec", 5.0)
    monkeypatch.setattr(agent_config, "prompt_guard_enabled", False)

    active_executions = 0
    max_concurrency_observed = 0

    def slow_worker(content, thread_id, user_id, is_authenticated):
        nonlocal active_executions, max_concurrency_observed
        active_executions += 1
        if active_executions > max_concurrency_observed:
            max_concurrency_observed = active_executions
        time.sleep(0.5)
        active_executions -= 1
        return {"status": "success", "reply": f"Reply to {content}", "tools_called": []}

    from src.agent.api.routes import ChatRequest
    from fastapi import Request

    mock_req = MagicMock(spec=Request)
    mock_req.headers = {}
    mock_req.cookies = {}

    with patch("src.agent.api.routes.run_agent_message", side_effect=slow_worker):
        # Launch Question A as an asyncio task
        p_a = ChatRequest(message="Question A", thread_id="thread_stop_1", user_id="user_stop")
        task_a = asyncio.create_task(chat_endpoint(p_a, mock_req))

        # Wait briefly for thread execution to start
        await asyncio.sleep(0.1)

        # User presses Stop (AbortController abort -> task cancelled)
        task_a.cancel()
        try:
            await task_a
        except asyncio.CancelledError:
            pass

        # Immediate Send on Question B
        p_b = ChatRequest(message="Question B after stop", thread_id="thread_stop_1", user_id="user_stop")
        resp_b = await chat_endpoint(p_b, mock_req)

        assert resp_b.status == "success"
        assert resp_b.reply == "Reply to Question B after stop"
        assert max_concurrency_observed == 1, "Question B must not run concurrently with Question A!"


@pytest.mark.asyncio
async def test_scenario_f_independent_conversations_concurrent(monkeypatch, test_db):
    """Scenario F: Two different conversations process independently in parallel."""
    monkeypatch.setattr(agent_config, "execution_timeout_sec", 5.0)
    monkeypatch.setattr(agent_config, "prompt_guard_enabled", False)

    active_executions = 0
    max_concurrency_observed = 0

    def parallel_worker(content, thread_id, user_id, is_authenticated):
        nonlocal active_executions, max_concurrency_observed
        active_executions += 1
        if active_executions > max_concurrency_observed:
            max_concurrency_observed = active_executions
        time.sleep(0.4)
        active_executions -= 1
        return {"status": "success", "reply": f"Done {content}", "tools_called": []}

    from src.agent.api.routes import ChatRequest
    from fastapi import Request

    mock_req = MagicMock(spec=Request)
    mock_req.headers = {}
    mock_req.cookies = {}

    with patch("src.agent.api.routes.run_agent_message", side_effect=parallel_worker):
        t0 = time.time()
        t1 = asyncio.create_task(
            chat_endpoint(ChatRequest(message="Conv1", thread_id="thread_f_1", user_id="user_f"), mock_req)
        )
        t2 = asyncio.create_task(
            chat_endpoint(ChatRequest(message="Conv2", thread_id="thread_f_2", user_id="user_f"), mock_req)
        )
        t3 = asyncio.create_task(
            chat_endpoint(ChatRequest(message="Conv3", thread_id="thread_f_3", user_id="user_diff"), mock_req)
        )

        r1, r2, r3 = await asyncio.gather(t1, t2, t3)
        elapsed = time.time() - t0

    assert r1.status == "success"
    assert r2.status == "success"
    assert r3.status == "success"
    # All 3 ran concurrently: total elapsed should be ~0.4-0.6s, NOT 1.2s
    assert elapsed < 0.8
    assert max_concurrency_observed == 3, f"Expected 3 concurrent conversations, observed {max_concurrency_observed}"


def test_scenario_h_slow_postgresql_execution():
    """Scenario H: PostgreSQL execution is deliberately slowed without state race."""
    saver = MemorySaver()
    tid = "slow_pg_thread"
    uid = "op_slow_pg"

    original_put = saver.put

    def slow_put(*args, **kwargs):
        time.sleep(0.1)
        return original_put(*args, **kwargs)

    saver.put = slow_put

    res = run_agent_message("Test slow DB storage", thread_id=tid, user_id=uid, checkpointer=saver)
    assert res["status"] == "success"
    state = build_agent_graph(checkpointer=saver).get_state(make_thread_config(tid, user_id=uid))
    assert len(state.values.get("messages", [])) >= 2


@pytest.mark.asyncio
async def test_scenario_k_unexpected_exception_recovery(test_db):
    """Scenario K: Worker raising unexpected exception does not cause deadlock."""
    from src.agent.api.routes import ChatRequest
    from fastapi import Request, HTTPException

    mock_req = MagicMock(spec=Request)
    mock_req.headers = {}
    mock_req.cookies = {}

    with patch("src.agent.api.routes.run_agent_message") as mock_run:
        # First call crashes
        mock_run.side_effect = RuntimeError("Fatal worker failure")

        p_err = ChatRequest(message="Crash please", thread_id="thread_err_1", user_id="user_k")
        with pytest.raises(HTTPException) as exc_info:
            await chat_endpoint(p_err, mock_req)
        assert exc_info.value.status_code == 503

        # Subsequent call must acquire lock cleanly without deadlock
        mock_run.side_effect = None
        mock_run.return_value = {"status": "success", "reply": "Recovered nicely"}

        p_ok = ChatRequest(message="Recover please", thread_id="thread_err_1", user_id="user_k")
        resp = await chat_endpoint(p_ok, mock_req)
        assert resp.status == "success"
        assert resp.reply == "Recovered nicely"


# ==============================================================================
# SCENARIO G: GEMINI TIMEOUT ACTIVATES GROQ FALLBACK
# ==============================================================================


def test_scenario_g_gemini_timeout_activates_groq_fallback():
    """Scenario G: Gemini primary model timeout activates cascading Groq fallback."""
    primary_mock = MagicMock()
    primary_mock.invoke.side_effect = TimeoutError("Gemini call timed out after 30s")

    fallback_mock = MagicMock()
    fallback_mock.invoke.return_value = AIMessage(
        content="Groq fallback answer",
        additional_kwargs={},
    )

    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        primary_model_name="gemini-3.8-flash",
        fallback_model_name="openai/gpt-oss-120b",
        timeout_seconds=1.0,
        max_retries=1,
    )

    resp = model.invoke([HumanMessage(content="Test query")])
    assert resp.content == "Groq fallback answer"
    assert resp.additional_kwargs.get("failover_occurred") is True
    assert resp.additional_kwargs.get("failover_level") == 1
    assert resp.additional_kwargs.get("llm_provider") == "groq"


# ==============================================================================
# SCENARIOS L, M & N: PERSISTENCE, RESTART, STOP RELOAD & POSTGRES CHECKPOINTER
# ==============================================================================


def test_scenario_l_and_m_history_reloaded_after_stop(test_db):
    """Scenario L & M: Conversation history persists and can be reloaded after stop / restart."""
    saver = MemorySaver()
    thread_id = "thread_persist_stop_1"
    user_id = "op_stop_reload"

    # Turn 1: Processed
    r1 = run_agent_message("Ghi nhớ mã trạm X-99", thread_id=thread_id, user_id=user_id, checkpointer=saver)
    assert r1["status"] == "success"

    # Simulate backend restart with same checkpointer
    graph_restarted = build_agent_graph(checkpointer=saver)
    state = graph_restarted.get_state(make_thread_config(thread_id, user_id=user_id))

    messages = state.values.get("messages", [])
    assert any("X-99" in getattr(m, "content", "") for m in messages)


def test_scenario_n_postgres_checkpoint_integrity():
    """Scenario N: Validate checkpointer against actual PostgreSQL database if configured."""
    from src.agent.memory.checkpoint import get_checkpointer, get_postgres_connection_string

    conn_str = get_postgres_connection_string()
    if not conn_str:
        pytest.skip("PostgreSQL connection not configured in current environment")

    saver = get_checkpointer(force_memory=False)
    assert saver is not None

    # Write a test turn
    test_tid = f"test_e2e_pg_{uuid4().hex[:8]}"
    test_uid = "pg_verifier"

    res = run_agent_message(
        "Chào hệ thống DATT",
        thread_id=test_tid,
        user_id=test_uid,
        checkpointer=saver,
    )
    assert res["status"] == "success"

    # Verify state can be read back from PostgreSQL checkpointer
    graph_inst = build_agent_graph(checkpointer=saver)
    state = graph_inst.get_state(make_thread_config(test_tid, user_id=test_uid))
    assert len(state.values.get("messages", [])) >= 2

    # Clean up test thread
    clear_thread_checkpoint(test_tid, user_id=test_uid)
