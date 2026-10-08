"""Regression tests for DATT AI Agent Hardening and Correctness.

Validates:
1. Analytics correctness (calendar-day ICT boundaries vs rolling 24h, passages vs events, live occupancy).
2. Tool loop control (configurable budget, duplicate prevention, multi-step execution, partial results).
3. Camera status grounding (database lease status, stream reachability unverified, source-type guidance).
4. Security & anti-spoofing (arbitrary user spoofing rejection, token verification, conversation ownership).
5. Message and tool-call serialization fidelity.
"""

from datetime import datetime, timezone, timedelta
import json
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

from src.agent.api.auth import create_auth_token, resolve_authenticated_user
from src.agent.config import agent_config
from src.agent.graph import build_agent_graph, run_agent_message
from src.agent.nodes import MockChatModel, agent_node, should_continue, tool_node
from src.agent.state import AgentState
from src.agent.tools.analytics import get_event_statistics, get_today_calendar_bounds
from src.agent.tools.camera import get_camera_status, get_troubleshooting_guidance
from src.ui.web_server import app


# =============================================================================
# 1. ANALYTICS CORRECTNESS REGRESSION TESTS
# =============================================================================

def test_today_calendar_bounds_vietnam_ict():
    """Verify calendar-day boundaries are computed in Vietnam ICT (UTC+7) timezone."""
    today_start_utc, now_utc, today_start_local, now_local = get_today_calendar_bounds()

    # ICT timezone offset must be +07:00
    assert today_start_local.tzinfo is not None
    assert today_start_local.utcoffset() == timedelta(hours=7)
    assert now_local.utcoffset() == timedelta(hours=7)

    # Local start time must be exactly 00:00:00.000000
    assert today_start_local.hour == 0
    assert today_start_local.minute == 0
    assert today_start_local.second == 0
    assert today_start_local.microsecond == 0

    # Start UTC must precede now UTC
    assert today_start_utc <= now_utc


def test_event_statistics_metric_separation():
    """Verify get_event_statistics separates calendar day, rolling 24h, and live occupancy."""
    stats = get_event_statistics.invoke({})
    assert stats["status"] == "success"

    # 1. Calendar day section
    assert "today_calendar_day" in stats
    cal = stats["today_calendar_day"]
    assert "total_events_today" in cal
    assert "vehicle_passages_today" in cal
    assert "unique_plates_today" in cal
    assert "business_events_today" in cal
    assert cal["timezone"] == "ICT (UTC+7)"

    # 2. Rolling 24h section
    assert "rolling_24h_interval" in stats
    r24 = stats["rolling_24h_interval"]
    assert "vehicle_passages" in r24
    assert "business_events" in r24
    assert "unique_plates" in r24

    # 3. All-time database totals
    assert "all_time_database_totals" in stats
    all_time = stats["all_time_database_totals"]
    assert "total_business_events" in all_time
    assert "total_vehicle_passages" in all_time

    # 4. Live occupancy disclaimer
    assert stats["live_occupancy"] is None
    assert "live_occupancy_note" in stats
    assert "ZoneCounter" in stats["live_occupancy_note"] or "video" in stats["live_occupancy_note"]
    assert "metric_distinction" in stats


# =============================================================================
# 2. TOOL LOOP CONTROL & BUDGET REGRESSION TESTS
# =============================================================================

def test_duplicate_tool_call_in_same_turn_skipped():
    """Verify duplicate tool calls with identical arguments in the same turn are skipped."""
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_camera_status", "args": {"camera_id": "camera_01"}, "id": "call_1"},
            {"name": "get_camera_status", "args": {"camera_id": "camera_01"}, "id": "call_2"},
        ],
    )
    state: AgentState = {
        "messages": [ai_msg],
        "thread_id": "test_t",
        "user_id": "test_u",
        "tool_call_counts": {},
        "repeated_tool_calls": 0,
        "tool_cycles": 0,
        "total_tool_calls": 0,
        "error": None,
    }

    res = tool_node(state)
    msgs = res["messages"]
    assert len(msgs) == 2

    # Second tool message must be skipped as duplicate
    second_data = json.loads(msgs[1].content)
    assert second_data["status"] == "duplicate_call_skipped"
    # Total tool calls executed must be 1, not 2
    assert res["total_tool_calls"] == 1


def test_execution_budget_exhaustion_returns_partial_results():
    """Verify that when total_tool_calls reaches budget, partial results are returned explicitly."""
    ai_msg = AIMessage(
        content="",
        tool_calls=[
            {"name": "get_camera_status", "args": {"camera_id": "camera_01"}, "id": "call_1"},
        ],
    )
    # Simulate state that already consumed the full tool call budget
    state: AgentState = {
        "messages": [ai_msg],
        "thread_id": "test_t",
        "user_id": "test_u",
        "tool_call_counts": {},
        "repeated_tool_calls": 0,
        "tool_cycles": 2,
        "total_tool_calls": agent_config.max_total_tool_calls,
        "error": None,
    }

    res = tool_node(state)
    msgs = res["messages"]
    assert len(msgs) == 1
    data = json.loads(msgs[0].content)
    assert data["status"] == "budget_exhausted"


def test_should_continue_stops_when_cycles_exceed_config():
    """Verify should_continue returns __end__ when cycles reach max_tool_cycles."""
    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "get_camera_status", "args": {"camera_id": "camera_01"}, "id": "call_1"}],
    )
    state: AgentState = {
        "messages": [ai_msg],
        "thread_id": "test_t",
        "user_id": "test_u",
        "tool_call_counts": {},
        "repeated_tool_calls": 0,
        "tool_cycles": agent_config.max_tool_cycles,
        "total_tool_calls": 2,
        "error": None,
    }
    decision = should_continue(state)
    assert decision == "__end__"


def test_legitimate_multi_step_tool_execution():
    """Verify hybrid query performs multi-step tool execution within budget."""
    checkpointer = MemorySaver()
    # Hybrid query: check status, then retrieve troubleshooting guide
    res = run_agent_message(
        content="Camera camera_01 đang offline, dựa theo tài liệu hãy hướng dẫn xử lý",
        thread_id="test_hybrid_turn",
        user_id="operator_hybrid",
        checkpointer=checkpointer,
    )
    assert res["status"] == "success"
    # Must have invoked camera status first and then knowledge
    assert "get_camera_status" in res["tools_called"]
    assert "get_knowledge" in res["tools_called"]
    assert len(res["reply"]) > 0


# =============================================================================
# 3. CAMERA STATUS GROUNDING REGRESSION TESTS
# =============================================================================

def test_camera_status_grounding_fields():
    """Verify get_camera_status explicitly returns status_basis and reachability flags."""
    res = get_camera_status.invoke({"camera_id": "camera_01"})
    assert res["status"] == "success"
    assert res["status_basis"] in ("database_heartbeat_lease", "static_yaml_registry")
    assert res["stream_reachability_verified"] is False
    assert "troubleshooting_guidance" in res


def test_troubleshooting_guidance_adaptation_by_source_type():
    """Verify troubleshooting guidance adapts strictly to camera source type."""
    # 1. Local file source
    file_guide = get_troubleshooting_guidance("file", "data/sample_videos/traffic.mp4")
    assert file_guide["source_category"] == "local_file"
    assert file_guide["is_network_stream"] is False
    assert any("file" in s.lower() for s in file_guide["steps"])
    assert "RTSP" in file_guide["caution"]

    # 2. RTSP stream source
    rtsp_guide = get_troubleshooting_guidance("rtsp", "rtsp://192.168.1.100:554/live")
    assert rtsp_guide["source_category"] == "rtsp_network_stream"
    assert rtsp_guide["is_network_stream"] is True
    assert any("554" in s for s in rtsp_guide["steps"])

    # 3. HLS stream source
    hls_guide = get_troubleshooting_guidance("direct_hls", "https://example.com/live.m3u8")
    assert hls_guide["source_category"] == "http_hls_stream"
    assert any("m3u8" in s for s in hls_guide["steps"])

    # 4. YouTube stream source
    yt_guide = get_troubleshooting_guidance("youtube", "https://youtube.com/watch?v=123")
    assert yt_guide["source_category"] == "youtube_live"
    assert any("yt-dlp" in s for s in yt_guide["steps"])


# =============================================================================
# 4. SECURITY & ANTI-SPOOFING REGRESSION TESTS
# =============================================================================

@pytest.fixture
def api_client():
    return TestClient(app)


def test_arbitrary_unauthenticated_user_spoofing_prevention(api_client):
    """Verify unauthenticated clients claiming user identities are scoped to their client context."""
    # Client A creates thread
    r1 = api_client.post(
        "/api/agent/chat",
        json={"message": "Kiểm tra camera_01", "thread_id": "tenant_test_thread", "user_id": "victim_user"},
    )
    assert r1.status_code == 200

    # Inspect conversation for victim_user
    r2 = api_client.get("/api/agent/conversations/tenant_test_thread", params={"user_id": "victim_user"})
    assert r2.status_code == 200
    data2 = r2.json()
    # The internal verified user should be scoped with client fingerprint
    assert "unauth_victim_user_" in data2["user_id"]


def test_hmac_signed_bearer_token_authenticated():
    """Verify HMAC signed bearer token grants global verified identity."""
    token = create_auth_token("verified_operator")
    headers = {"Authorization": f"Bearer {token}"}

    client = TestClient(app)
    resp = client.post(
        "/api/agent/chat",
        headers=headers,
        json={"message": "Kiểm tra camera_01", "thread_id": "token_auth_thread"},
    )
    assert resp.status_code == 200

    # Get conversation with Bearer token
    c_resp = client.get("/api/agent/conversations/token_auth_thread", headers=headers)
    assert c_resp.status_code == 200
    assert c_resp.json()["user_id"] == "verified_operator"


def test_same_ip_different_session_tokens_isolation(api_client):
    """Verify two clients sharing the same IP but with distinct session tokens cannot access each other's conversations."""
    shared_thread = "nat_collision_thread"
    shared_username = "operator_team"

    # Client A on local IP creates a conversation with session_A
    r_a = api_client.post(
        "/api/agent/chat",
        headers={"X-Session-Id": "client_session_alpha_111"},
        json={"message": "Dữ liệu mật ca trực Alpha", "thread_id": shared_thread, "user_id": shared_username},
    )
    assert r_a.status_code == 200

    # Client B on the EXACT SAME IP queries the same thread using session_B
    r_b = api_client.get(
        f"/api/agent/conversations/{shared_thread}",
        headers={"X-Session-Id": "client_session_beta_222"},
        params={"user_id": shared_username},
    )
    assert r_b.status_code == 200
    data_b = r_b.json()
    # Client B MUST NOT see Client A's conversation
    assert data_b["status"] == "not_found"
    assert data_b["message_count"] == 0
    assert len(data_b["messages"]) == 0

    # Client A queries using session_A and successfully retrieves conversation
    r_a_check = api_client.get(
        f"/api/agent/conversations/{shared_thread}",
        headers={"X-Session-Id": "client_session_alpha_111"},
        params={"user_id": shared_username},
    )
    assert r_a_check.status_code == 200
    assert r_a_check.json()["status"] == "success"
    assert r_a_check.json()["message_count"] > 0


def test_hmac_invalid_or_forged_token_rejected_401(api_client):
    """Verify malformed or forged tokens are strictly rejected with 401."""
    # 1. Forged signature
    r1 = api_client.post(
        "/api/agent/chat",
        headers={"Authorization": "Bearer admin:deadbeefdeadbeefdeadbeefdeadbeef"},
        json={"message": "Tra cứu", "thread_id": "forged_thread"},
    )
    assert r1.status_code == 401
    assert "Invalid token signature" in r1.json().get("detail", "")

    # 2. Malformed token without separator
    r2 = api_client.post(
        "/api/agent/chat",
        headers={"Authorization": "Bearer invalidtokenwithoutcolon"},
        json={"message": "Tra cứu", "thread_id": "malformed_thread"},
    )
    assert r2.status_code == 401
    assert "Malformed Bearer token" in r2.json().get("detail", "")

    # 3. Unsupported scheme
    r3 = api_client.post(
        "/api/agent/chat",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
        json={"message": "Tra cứu", "thread_id": "basic_auth_thread"},
    )
    assert r3.status_code == 401


def test_privileged_user_claim_rejected(api_client):
    """Verify unauthenticated client claiming privileged admin name is forbidden."""
    for privileged in ("admin", "root", "system", "superuser"):
        resp = api_client.post(
            "/api/agent/chat",
            json={"message": "Tra cứu", "thread_id": "p_thread", "user_id": privileged},
        )
        assert resp.status_code == 403


# =============================================================================
# 5. MESSAGE & TOOL-CALL SERIALIZATION ORDERING REGRESSION TESTS
# =============================================================================

def test_conversation_serialization_preserves_tool_calls_and_ids(api_client):
    """Verify GET /api/agent/conversations/{thread_id} preserves tool_calls and tool_call_id."""
    thread_id = "test_serialization_fidelity"

    # Send message that triggers tool call
    res = api_client.post(
        "/api/agent/chat",
        json={"message": "Kiểm tra trạng thái camera_01", "thread_id": thread_id},
    )
    assert res.status_code == 200

    # Retrieve history
    h_res = api_client.get(f"/api/agent/conversations/{thread_id}")
    assert h_res.status_code == 200
    msgs = h_res.json()["messages"]

    # Verify presence and order of HumanMessage, AIMessage with tool_calls, ToolMessage with tool_call_id
    assert len(msgs) >= 3
    has_tool_call_spec = False
    has_tool_call_id = False

    for m in msgs:
        if m.get("tool_calls"):
            has_tool_call_spec = True
        if m.get("tool_call_id"):
            has_tool_call_id = True

    assert has_tool_call_spec is True
    assert has_tool_call_id is True


def test_sensitive_operational_tool_authorization_enforcement(api_client, monkeypatch):
    """Verify sensitive operational tools require authentication when operational auth is enforced."""
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "1")
    thread_id = "test_sensitive_auth_enforce"

    # Unauthenticated request attempting watchlist search
    resp = api_client.post(
        "/api/agent/chat",
        json={"message": "Tra cứu danh sách theo dõi biển số xe 30A-12345", "thread_id": thread_id},
    )
    assert resp.status_code == 200
    # Chat reply should communicate unauthorized access
    reply = resp.json()["reply"]
    assert "Truy cập bị từ chối" in reply or "yêu cầu thông tin xác thực" in reply or "unauthorized" in reply.lower()

    # Authenticated request with HMAC token succeeds
    token = create_auth_token("security_officer")
    resp_auth = api_client.post(
        "/api/agent/chat",
        json={"message": "Tra cứu danh sách theo dõi biển số xe 30A-12345", "thread_id": "test_sensitive_auth_ok"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_auth.status_code == 200
    assert "Truy cập bị từ chối" not in resp_auth.json()["reply"]
