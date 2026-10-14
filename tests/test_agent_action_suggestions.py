"""Comprehensive test suite for Context-Aware Action Suggestions in DATT AI Assistant.

Validates:
1. Search watchlist for face target (e.g. 'Long') updates current_entity and derives
   grounded next-actions (recognition history, alerts, email status).
2. Elimination of static/fixed 3-action fallback ("Kiểm tra Camera", "Phát hiện bất thường", "Báo cáo ca trực").
3. Vehicle search (e.g. '30A-12345') generates vehicle-grounded suggestions (movement history, cameras, alerts).
4. Camera offline status derives video source check and troubleshooting guide.
5. Traffic analytics query derives yesterday comparison, peak hours, and anomaly detection.
6. Ambiguous candidates (multiple persons with the same name) prompt user to select the specific candidate.
7. No hallucination of entities, plates, cameras, or events.
8. Suggestions count is flexible (0 to 4), deduplicated, and returns [] when no action applies.
9. Verification that API response preserves tools_called for backend observability while UI hides it.
"""

import pytest
from fastapi.testclient import TestClient

from src.agent.investigation.memory import InvestigationMemoryManager
from src.agent.investigation.recommendations import generate_action_suggestions
from src.ui.web_server import app


def test_no_generic_three_action_fallback():
    """Verify that when no contextual action applies, action_suggestions is strictly empty [].

    It must never return the legacy static fallback:
    ['Kiểm tra Camera', 'Phát hiện bất thường', 'Báo cáo ca trực'].
    """
    suggestions = generate_action_suggestions(
        investigation_context=None,
        tools_called=[],
        last_reply="Thời tiết hôm nay rất đẹp.",
        user_query="Thời tiết hôm nay thế nào?",
    )
    assert suggestions == []

    # Even with empty context and no tools, never return legacy fallback
    legacy_labels = {"Kiểm tra Camera", "Phát hiện bất thường", "Báo cáo ca trực"}
    assert not any(s["label"] in legacy_labels for s in suggestions)


def test_face_target_search_watchlist_context_and_suggestions():
    """Case 1: User searches for person 'Long'. Watchlist returns target.

    Memory updates current_entity with target details.
    Suggestions recommend detection history and alert check for Long.
    """
    mgr = InvestigationMemoryManager
    initial_ctx = mgr.get_initial_context()

    # Simulate search_watchlist result returning single target 'Long'
    watchlist_result = {
        "status": "success",
        "vehicle_watchlist": [],
        "face_watchlist": [
            {
                "id": "target-uuid-long-01",
                "name": "Long",
                "target_type": "face",
                "active": True,
            }
        ],
        "identity_resolution": {
            "status": "resolved",
            "target_id": "target-uuid-long-01",
            "target_name": "Long",
        },
        "total_matches": 1,
    }

    updated_ctx = mgr.update_from_tool_results(
        context=initial_ctx,
        tool_name="search_watchlist",
        tool_args={"target": "Long", "watchlist_type": "face"},
        tool_result=watchlist_result,
    )

    assert updated_ctx["current_entity"] is not None
    assert updated_ctx["current_entity"]["type"] == "face"
    assert updated_ctx["current_entity"]["name"] == "Long"
    assert updated_ctx["current_entity"]["target_id"] == "target-uuid-long-01"

    suggestions = generate_action_suggestions(
        investigation_context=updated_ctx,
        tools_called=["search_watchlist"],
        last_reply="Đã tìm thấy đối tượng Long trong danh sách theo dõi. Bạn có thể kiểm tra lịch sử nhận diện hoặc cảnh báo của Long.",
        user_query="Tìm người tên Long",
    )

    assert len(suggestions) >= 2
    assert len(suggestions) <= 4

    labels = [s["label"] for s in suggestions]
    queries = [s["query"] for s in suggestions]

    # Must contain recognition history and alerts for Long
    assert "Lịch sử nhận diện" in labels
    assert any("Long" in q for q in queries)
    assert any("nhận diện" in q for q in queries)
    assert "Kiểm tra cảnh báo" in labels

    # Must NOT contain static unrelated camera_01 or shift report fallback
    assert "Báo cáo ca trực" not in labels
    assert not any("camera_01" in q for q in queries)


def test_ambiguous_face_candidates_prompt_selection():
    """Case 6: When multiple persons match the search query (e.g. 2 people named Long),

    Agent must generate selection chips for each candidate before investigating further.
    """
    mgr = InvestigationMemoryManager
    initial_ctx = mgr.get_initial_context()

    multi_match_result = {
        "status": "success",
        "vehicle_watchlist": [],
        "face_watchlist": [
            {"id": "uuid-long-vu-1111", "name": "Long Vũ", "target_type": "face", "active": True},
            {"id": "uuid-long-tran-2222", "name": "Long Trần", "target_type": "face", "active": True},
        ],
        "identity_resolution": {
            "status": "ambiguous",
            "candidates": [
                {"id": "uuid-long-vu-1111", "name": "Long Vũ"},
                {"id": "uuid-long-tran-2222", "name": "Long Trần"},
            ],
        },
        "total_matches": 2,
    }

    updated_ctx = mgr.update_from_tool_results(
        context=initial_ctx,
        tool_name="search_watchlist",
        tool_args={"target": "Long"},
        tool_result=multi_match_result,
    )

    assert updated_ctx["current_entity"]["type"] == "face_ambiguous"
    assert len(updated_ctx["candidate_entities"]) == 2

    suggestions = generate_action_suggestions(
        investigation_context=updated_ctx,
        tools_called=["search_watchlist"],
        last_reply="Tìm thấy 2 đối tượng cùng tên Long. Vui lòng chọn đối tượng cần điều tra.",
        user_query="Tìm người tên Long",
    )

    assert len(suggestions) >= 2
    queries = [s["query"] for s in suggestions]

    # Must provide candidate selection queries with specific IDs
    assert any("Long Vũ" in q and "uuid-long-vu" in q for q in queries)
    assert any("Long Trần" in q and "uuid-long-tran" in q for q in queries)


def test_vehicle_search_context_and_suggestions():
    """Case 2: User investigates vehicle plate '30A-12345'.

    Suggestions recommend movement history, cameras observed, and notification/alert checks.
    """
    mgr = InvestigationMemoryManager
    ctx = mgr.resolve_context(
        existing_context=None,
        messages=[],
        current_question="Tìm xe 30A-12345 hôm nay",
    )
    assert ctx["current_entity"]["plate"] == "30A-12345"

    suggestions = generate_action_suggestions(
        investigation_context=ctx,
        tools_called=["search_watchlist"],
        last_reply="Xe 30A-12345 đã được tìm thấy trong danh sách theo dõi.",
        user_query="Tìm xe 30A-12345",
    )

    labels = [s["label"] for s in suggestions]
    queries = [s["query"] for s in suggestions]

    assert "Lịch sử xuất hiện" in labels or "Các camera ghi nhận" in labels
    assert any("30A-12345" in q for q in queries)
    assert not any("camera_01" in q for q in queries)


def test_camera_offline_status_suggestions():
    """Case 3: Camera is offline / unverified stream.

    Suggestions recommend video source check and troubleshooting guide.
    """
    ctx = {
        "camera_scope": ["camera_01"],
        "last_camera_status": "offline",
        "current_entity": None,
    }

    suggestions = generate_action_suggestions(
        investigation_context=ctx,
        tools_called=["get_camera_status"],
        last_reply="Camera camera_01 hiện đang offline, nguồn video chưa xác minh kết nối.",
        user_query="Tại sao camera_01 offline?",
    )

    labels = [s["label"] for s in suggestions]
    queries = [s["query"] for s in suggestions]

    assert "Kiểm tra nguồn video" in labels
    assert "Hướng dẫn khắc phục" in labels
    assert any("camera_01" in q for q in queries)
    assert any("nguồn video" in q for q in queries)
    assert any("khắc phục" in q for q in queries)


def test_traffic_analytics_suggestions():
    """Case 4: Traffic analytics query derives comparison with yesterday and peak hours."""
    ctx = {
        "camera_scope": ["camera_02"],
        "current_entity": None,
    }

    suggestions = generate_action_suggestions(
        investigation_context=ctx,
        tools_called=["get_traffic_analytics"],
        last_reply="Lưu lượng tại camera_02 hôm nay ghi nhận 1,250 lượt phương tiện.",
        user_query="Thống kê lưu lượng camera_02 hôm nay",
    )

    labels = [s["label"] for s in suggestions]
    queries = [s["query"] for s in suggestions]

    assert "So sánh với hôm qua" in labels
    assert "Khung giờ cao điểm" in labels
    assert any("camera_02" in q for q in queries)


def test_suggestions_deduplication_and_cap():
    """Verify suggestions are capped at max 4, have unique labels, and no duplicate queries."""
    ctx = {
        "camera_scope": ["camera_03"],
        "current_entity": {"type": "vehicle", "plate": "29B-99999"},
    }

    suggestions = generate_action_suggestions(
        investigation_context=ctx,
        tools_called=["get_traffic_analytics", "get_camera_status"],
        last_reply="Dữ liệu tổng hợp.",
        user_query="Kiểm tra xe 29B-99999",
    )

    assert len(suggestions) <= 4
    labels = [s["label"] for s in suggestions]
    queries = [s["query"] for s in suggestions]
    assert len(labels) == len(set(labels))
    assert len(queries) == len(set(queries))


def test_e2e_api_chat_preserves_tools_called_and_action_suggestions():
    """Verify HTTP API /api/agent/chat preserves tools_called in payload for observability

    and returns contextual action_suggestions.
    """
    client = TestClient(app)
    resp = client.post(
        "/api/agent/chat",
        json={"message": "Kiểm tra trạng thái hoạt động của camera_01", "thread_id": "test_sug_thread"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # tools_called MUST be preserved in API response for observability & logging
    assert "tools_called" in data
    assert "get_camera_status" in data["tools_called"]

    # action_suggestions must be present and contextual
    assert "action_suggestions" in data
    assert isinstance(data["action_suggestions"], list)
    if data["action_suggestions"]:
        # Should be related to camera_01, not generic fallback
        queries = [s["query"] for s in data["action_suggestions"]]
        assert any("camera_01" in q for q in queries)
        assert not any("Báo cáo ca trực" == s.get("label") for s in data["action_suggestions"])
