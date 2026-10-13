"""End-to-End integration tests for automatic Gemini -> Groq failover in DATT AI Agent."""

import os
import time
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.agent.config import agent_config
from src.agent.llm import (
    LLMUnavailableException,
    ResilientChatModel,
    create_raw_model,
    get_active_provider_info,
)
from src.agent.tools import ALL_AGENT_TOOLS


# =============================================================================
# 1. Unit & Failure-Injection Tests using Test Doubles
# =============================================================================

def test_gemini_works_groq_not_called():
    """Scenario 1: Primary Gemini succeeds; Groq fallback is never invoked."""
    primary_mock = MagicMock()
    primary_mock.invoke.return_value = AIMessage(content="Gemini: Hệ thống camera hoạt động bình thường.")
    fallback_mock = MagicMock()

    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        primary_model_name="gemini-3.8-flash",
        fallback_model_name="openai/gpt-oss-120b",
        timeout_seconds=5.0,
        max_retries=1,
    )

    resp = model.invoke([HumanMessage(content="Kiểm tra camera")])
    assert resp.content == "Gemini: Hệ thống camera hoạt động bình thường."
    assert primary_mock.invoke.call_count == 1
    assert fallback_mock.invoke.call_count == 0
    assert resp.additional_kwargs["llm_provider"] == "google_genai"
    assert resp.additional_kwargs["llm_model"] == "gemini-3.8-flash"
    assert resp.additional_kwargs["failover_occurred"] is False


def test_gemini_returns_429_immediate_groq_failover():
    """Scenario 2: Primary Gemini returns 429 quota exhaustion; immediately routes to Groq without long sleep."""
    primary_mock = MagicMock()
    primary_mock.invoke.side_effect = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for metric: free_tier_requests")

    fallback_mock = MagicMock()
    fallback_mock.invoke.return_value = AIMessage(content="Groq: Đã tiếp nhận yêu cầu qua fallback model.")

    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        primary_model_name="gemini-3.8-flash",
        fallback_model_name="openai/gpt-oss-120b",
        timeout_seconds=5.0,
        max_retries=2,
        cooldown_seconds=60.0,
    )

    start = time.time()
    resp = model.invoke([HumanMessage(content="Tra cứu biển số xe 51F-12345")])
    elapsed = time.time() - start

    assert resp.content == "Groq: Đã tiếp nhận yêu cầu qua fallback model."
    assert primary_mock.invoke.call_count == 1  # Exactly 1 call, NO retries on 429 quota exhaustion!
    assert fallback_mock.invoke.call_count == 1
    assert elapsed < 1.0  # Fast failover without long sleep delay
    assert resp.additional_kwargs["llm_provider"] == "groq"
    assert resp.additional_kwargs["llm_model"] == "openai/gpt-oss-120b"
    assert resp.additional_kwargs["failover_occurred"] is True
    assert resp.additional_kwargs["failover_reason"] == "quota_exhausted_429"

    # Circuit breaker must be active
    status = model.get_status()
    assert status["in_cooldown"] is True
    assert status["cooldown_reason"] == "quota_exhausted_429"
    assert status["failover_count"] == 1


def test_gemini_timeout_bounded_retry_then_groq():
    """Scenario 3: Primary Gemini encounters transient timeout; retries bounded times then falls back to Groq."""
    primary_mock = MagicMock()
    primary_mock.invoke.side_effect = TimeoutError("HTTP 504 Gateway Timeout")

    fallback_mock = MagicMock()
    fallback_mock.invoke.return_value = AIMessage(content="Groq: Phản hồi sau khi Gemini timeout.")

    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        primary_model_name="gemini-3.8-flash",
        fallback_model_name="openai/gpt-oss-120b",
        timeout_seconds=5.0,
        max_retries=1,
        backoff_base_sec=0.01,  # Fast backoff for test speed
    )

    resp = model.invoke([HumanMessage(content="Thống kê lưu lượng 24h")])
    assert resp.content == "Groq: Phản hồi sau khi Gemini timeout."
    assert primary_mock.invoke.call_count == 2  # 1 initial + 1 retry
    assert fallback_mock.invoke.call_count == 1
    assert resp.additional_kwargs["llm_provider"] == "groq"
    assert resp.additional_kwargs["failover_occurred"] is True


def test_gemini_and_groq_both_fail_returns_llm_unavailable():
    """Scenario 4: Both Gemini and Groq fail; raises LLMUnavailableException."""
    primary_mock = MagicMock()
    primary_mock.invoke.side_effect = Exception("429 RESOURCE_EXHAUSTED")

    fallback_mock = MagicMock()
    fallback_mock.invoke.side_effect = Exception("503 Service Unavailable: Groq capacity full")

    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        primary_model_name="gemini-3.8-flash",
        fallback_model_name="openai/gpt-oss-120b",
        timeout_seconds=5.0,
        max_retries=0,
    )

    with pytest.raises(LLMUnavailableException) as exc_info:
        model.invoke([HumanMessage(content="Test fail")])

    assert exc_info.value.reason == "all_providers_failed"
    assert "All configured LLM providers failed" in str(exc_info.value)


def test_gemini_auth_error_reports_clearly_without_masking():
    """Scenario 5: Gemini authentication error is reported clearly without masquerading as failover."""
    primary_mock = MagicMock()
    primary_mock.invoke.side_effect = Exception("401 Unauthorized: Invalid API Key provided")

    fallback_mock = MagicMock()

    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        primary_model_name="gemini-3.8-flash",
        fallback_model_name="openai/gpt-oss-120b",
    )

    with pytest.raises(LLMUnavailableException) as exc_info:
        model.invoke([HumanMessage(content="Test auth")])

    assert exc_info.value.reason == "primary_auth_error"
    assert "authentication/configuration error" in str(exc_info.value).lower()
    assert fallback_mock.invoke.call_count == 0  # Do not mask auth errors


def test_circuit_breaker_bypasses_gemini_and_recovers_after_cooldown():
    """Scenario 6: Circuit-breaker routes directly to Groq during cooldown, then restores Gemini upon expiry."""
    primary_mock = MagicMock()
    primary_mock.invoke.side_effect = Exception("429 RESOURCE_EXHAUSTED")

    fallback_mock = MagicMock()
    fallback_mock.invoke.return_value = AIMessage(content="Groq answer")

    # Short cooldown for test speed: 0.15 seconds
    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        primary_model_name="gemini-3.8-flash",
        fallback_model_name="openai/gpt-oss-120b",
        cooldown_seconds=0.15,
        max_retries=0,
    )

    # Call 1: Gemini fails 429 -> Groq answers -> Cooldown starts
    resp1 = model.invoke([HumanMessage(content="Turn 1")])
    assert resp1.additional_kwargs["llm_provider"] == "groq"
    assert primary_mock.invoke.call_count == 1
    assert fallback_mock.invoke.call_count == 1
    assert model.get_status()["in_cooldown"] is True

    # Call 2: While cooldown active, Gemini is NOT touched at all
    resp2 = model.invoke([HumanMessage(content="Turn 2")])
    assert resp2.additional_kwargs["llm_provider"] == "groq"
    assert primary_mock.invoke.call_count == 1  # Unchanged! Zero doomed calls to Gemini
    assert fallback_mock.invoke.call_count == 2

    # Wait for cooldown to expire
    time.sleep(0.20)
    assert model.get_status()["in_cooldown"] is False

    # Simulate Gemini recovering!
    primary_mock.invoke.side_effect = None
    primary_mock.invoke.return_value = AIMessage(content="Gemini recovered!")

    # Call 3: Gemini is tried again and succeeds! Traffic is restored to Gemini
    resp3 = model.invoke([HumanMessage(content="Turn 3")])
    assert resp3.content == "Gemini recovered!"
    assert resp3.additional_kwargs["llm_provider"] == "google_genai"
    assert resp3.additional_kwargs["failover_occurred"] is False
    assert primary_mock.invoke.call_count == 2
    assert fallback_mock.invoke.call_count == 2  # Fallback was not called on turn 3


def test_tool_binding_preserves_shared_state_across_copies():
    """Scenario 7: Calling bind_tools() shares circuit breaker status and wraps clean raw models."""
    primary_raw = MagicMock()
    fallback_raw = MagicMock()

    model = ResilientChatModel(
        primary_model=primary_raw,
        fallback_model=fallback_raw,
        cooldown_seconds=60.0,
    )
    # Engage cooldown on model 1
    model._shared_state["cooldown_until"] = time.time() + 30.0
    model._shared_state["cooldown_reason"] = "quota_exhausted_429"

    # Clone via bind_tools
    bound = model.bind_tools(ALL_AGENT_TOOLS)
    assert bound.get_status()["in_cooldown"] is True
    assert bound.get_status()["cooldown_reason"] == "quota_exhausted_429"


def test_mock_chat_model_forbidden_in_production():
    """Scenario 8: MockChatModel cannot be loaded in production runtime."""
    with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "", "DATT_ALLOW_TEST_MOCK": "0", "CI": ""}, clear=False):
        with pytest.raises(LLMUnavailableException) as exc_info:
            create_raw_model(provider="mock", model_name="mock", temperature=0.0)
        assert exc_info.value.reason == "mock_disallowed_in_production"


def test_active_provider_info_structure():
    """Scenario 9: Diagnostics information safely reports providers and keys status."""
    info = get_active_provider_info()
    assert "configured_provider" in info
    assert "actual_runtime" in info
    assert "fallback_provider" in info
    assert "has_groq_key" in info
    # Ensure no actual key value leaked
    for k, v in info.items():
        assert not str(v).startswith("gsk_")
        assert not str(v).startswith("AIza")


# =============================================================================
# 2. REAL Groq API End-to-End Tests (Live Network Execution)
# =============================================================================

@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not configured")
def test_real_groq_api_direct_invocation():
    """Scenario 10: Live Groq API invocation with model openai/gpt-oss-120b."""
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model_name="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        request_timeout=30.0,
    )
    resp = llm.invoke([HumanMessage(content="Respond with the single word: DATT_VERIFIED")])
    assert "DATT_VERIFIED" in resp.content.upper()


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not configured")
def test_real_groq_api_tool_calling():
    """Scenario 11: Live Groq API tool-binding and tool-calling with DATT operational tools."""
    from langchain_groq import ChatGroq

    raw_llm = ChatGroq(
        model_name="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        request_timeout=30.0,
    )
    bound_llm = raw_llm.bind_tools(ALL_AGENT_TOOLS)

    # 1. Camera Status Tool Calling
    resp = bound_llm.invoke([HumanMessage(content="Kiểm tra trạng thái hoạt động của camera_01 giúp tôi")])
    assert hasattr(resp, "tool_calls")
    assert len(resp.tool_calls) > 0
    call = resp.tool_calls[0]
    assert call["name"] in ("get_camera_status", "get_cameras")
    assert "camera_01" in str(call["args"]) or "01" in str(call["args"])


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not configured")
def test_real_groq_synthesis_from_tool_messages():
    """Scenario 12: Live Groq API synthesizes a user response from simulated tool output."""
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model_name="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        request_timeout=30.0,
    ).bind_tools(ALL_AGENT_TOOLS)

    msgs = [
        SystemMessage(content="Bạn là Trợ lý AI Vận hành Hệ thống DATT."),
        HumanMessage(content="Kiểm tra trạng thái camera Cổng chính"),
        AIMessage(
            content="",
            tool_calls=[{"name": "get_camera_status", "args": {"camera_id": "cam_main"}, "id": "call_cam_1"}],
        ),
        ToolMessage(
            content='{"status": "RUNNING", "camera_name": "Cổng chính", "fps": 24.5, "stream_alive": true}',
            tool_call_id="call_cam_1",
            name="get_camera_status",
        ),
    ]

    resp = llm.invoke(msgs)
    assert len(resp.content) > 10
    # Must synthesize the tool output into Vietnamese
    assert any(w in resp.content.lower() for w in ("cổng chính", "hoạt động", "running", "24", "fps", "bình thường"))


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not configured")
def test_real_groq_watchlist_lookup_tool_calling():
    """Scenario 13: Live Groq API calls get_watchlist or lookup_target for plate query."""
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model_name="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        request_timeout=30.0,
    ).bind_tools(ALL_AGENT_TOOLS)

    resp = llm.invoke([HumanMessage(content="Tra cứu danh sách theo dõi biển số xe 51F-99999 xem có vi phạm không")])
    assert hasattr(resp, "tool_calls")
    assert len(resp.tool_calls) > 0
    names = [c["name"] for c in resp.tool_calls]
    assert any(n in names for n in ("search_watchlist", "get_watchlist", "lookup_target", "get_vehicle_history"))


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not configured")
def test_real_groq_forecast_and_analytics_tool_calling():
    """Scenario 14: Live Groq API calls get_tomorrow_forecast_tool for tomorrow traffic inquiry."""
    import time
    time.sleep(2.0)
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model_name="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        request_timeout=30.0,
        max_retries=3,
    ).bind_tools(ALL_AGENT_TOOLS)

    resp = llm.invoke([HumanMessage(content="Dự báo lưu lượng giao thông ngày mai của camera_01 như thế nào?")])
    assert hasattr(resp, "tool_calls")
    assert len(resp.tool_calls) > 0
    names = [c["name"] for c in resp.tool_calls]
    assert any(n in names for n in ("get_tomorrow_forecast", "get_predictive_alerts", "get_historical_analytics"))


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="GROQ_API_KEY not configured")
def test_real_groq_rag_documentation_tool_calling():
    """Scenario 15: Live Groq API calls get_knowledge tool for operational documentation questions."""
    import time
    time.sleep(2.0)
    from langchain_groq import ChatGroq

    llm = ChatGroq(
        model_name="openai/gpt-oss-120b",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        request_timeout=30.0,
        max_retries=3,
    ).bind_tools(ALL_AGENT_TOOLS)

    resp = llm.invoke([HumanMessage(content="Theo tài liệu hướng dẫn vận hành, quy trình xử lý khi camera bị mất tín hiệu là gì?")])
    assert hasattr(resp, "tool_calls")
    assert len(resp.tool_calls) > 0
    names = [c["name"] for c in resp.tool_calls]
    assert any(n in names for n in ("get_knowledge", "get_camera_status"))


def test_langgraph_full_turn_failover_preserves_context(monkeypatch):
    """Scenario 16: Full LangGraph execution preserves conversation state across model failover."""
    monkeypatch.setenv("DATT_REQUIRE_PERSISTENCE", "0")
    from langgraph.checkpoint.memory import MemorySaver
    from src.agent.graph import run_agent_message

    primary_mock = MagicMock()
    primary_mock.bind_tools.return_value = primary_mock
    primary_mock.invoke.side_effect = Exception("429 RESOURCE_EXHAUSTED: quota exceeded")

    fallback_mock = MagicMock()
    fallback_mock.bind_tools.return_value = fallback_mock
    fallback_mock.invoke.side_effect = lambda *a, **k: AIMessage(content="Groq đã phản hồi thành công qua LangGraph.")

    resilient = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        primary_model_name="gemini-3.8-flash",
        fallback_model_name="openai/gpt-oss-120b",
        timeout_seconds=5.0,
        max_retries=0,
    )

    checkpointer = MemorySaver()
    thread_id = "test_memory_thread_1"

    with patch("src.agent.nodes.get_llm", return_value=resilient):
        # Turn 1
        res1 = run_agent_message(
            content="Xin chào",
            thread_id=thread_id,
            is_authenticated=True,
            checkpointer=checkpointer,
        )
        assert res1["status"] == "success"
        assert res1["provider"] == "groq"
        assert res1["failover_occurred"] is True
        assert "Groq đã phản hồi" in res1["reply"]

        # Turn 2 on same thread retains conversation state
        res2 = run_agent_message(
            content="Tiếp tục hỗ trợ tôi",
            thread_id=thread_id,
            is_authenticated=True,
            checkpointer=checkpointer,
        )
        assert res2["status"] == "success"
        assert res2["provider"] == "groq"
        assert fallback_mock.invoke.call_count >= 2


def test_cascade_failover_gemini_fails_gpt_fails_qwen_succeeds():
    """Scenario 17: Multi-Level Fallback: Gemini (Primary) fails, Groq GPT-OSS (L1) fails, Groq Qwen (L2) succeeds."""
    primary_mock = MagicMock()
    primary_mock.invoke.side_effect = Exception("429 RESOURCE_EXHAUSTED: Gemini quota exceeded")

    fallback_1_mock = MagicMock()
    fallback_1_mock.invoke.side_effect = Exception("429 Too Many Requests: Groq GPT-OSS model rate limit")

    fallback_2_mock = MagicMock()
    fallback_2_mock.invoke.return_value = AIMessage(content="Qwen: Phản hồi thành công từ Fallback Level 2.")

    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_1_mock,
        fallback_2_model=fallback_2_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        fallback_2_provider="groq",
        primary_model_name="gemini-2.5-flash",
        fallback_model_name="openai/gpt-oss-120b",
        fallback_2_model_name="qwen/qwen3.8-27b",
        timeout_seconds=5.0,
        max_retries=0,
    )

    resp = model.invoke([HumanMessage(content="Dự báo lưu lượng ngày mai")])
    assert resp.content == "Qwen: Phản hồi thành công từ Fallback Level 2."
    assert primary_mock.invoke.call_count == 1
    assert fallback_1_mock.invoke.call_count == 1
    assert fallback_2_mock.invoke.call_count == 1
    assert resp.additional_kwargs["llm_provider"] == "groq"
    assert resp.additional_kwargs["llm_model"] == "qwen/qwen3.8-27b"
    assert resp.additional_kwargs["failover_occurred"] is True
    assert resp.additional_kwargs["failover_level"] == 2


def test_all_three_tiers_fail_returns_llm_unavailable():
    """Scenario 18: All three tiers (Gemini, Groq GPT-OSS, Groq Qwen) fail; raises LLMUnavailableException."""
    primary_mock = MagicMock()
    primary_mock.invoke.side_effect = Exception("429 RESOURCE_EXHAUSTED")

    fallback_1_mock = MagicMock()
    fallback_1_mock.invoke.side_effect = Exception("503 Service Unavailable")

    fallback_2_mock = MagicMock()
    fallback_2_mock.invoke.side_effect = Exception("500 Internal Server Error")

    model = ResilientChatModel(
        primary_model=primary_mock,
        fallback_model=fallback_1_mock,
        fallback_2_model=fallback_2_mock,
        primary_provider="google_genai",
        fallback_provider="groq",
        fallback_2_provider="groq",
        primary_model_name="gemini-2.5-flash",
        fallback_model_name="openai/gpt-oss-120b",
        fallback_2_model_name="qwen/qwen3.8-27b",
        timeout_seconds=5.0,
        max_retries=0,
    )

    with pytest.raises(LLMUnavailableException) as exc_info:
        model.invoke([HumanMessage(content="Tra cứu camera")])

    assert exc_info.value.reason == "all_providers_failed"
    assert "all configured llm providers failed" in str(exc_info.value).lower()

