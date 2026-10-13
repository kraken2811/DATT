"""Unit tests for Structured Investigation Memory and Multi-turn Context Tracking."""

from uuid import uuid4
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.investigation.memory import (
    InvestigationMemoryManager,
    extract_plate_from_text,
    parse_time_intent,
)


def test_plate_extraction_and_time_intent():
    """Verify regex plate extraction and Vietnamese time intent parsing."""
    assert extract_plate_from_text("Xe 30A-12345 xuất hiện ở đâu?") == "30A-12345"
    assert extract_plate_from_text("Tìm xe 51F99999 hôm nay") == "51F99999"
    assert extract_plate_from_text("Không có biển số nào ở đây") is None

    t_today = parse_time_intent("Xe này hôm nay đi đâu?")
    assert t_today is not None
    assert t_today["preset"] == "today"

    t_yesterday = parse_time_intent("Thế hôm qua thì sao?")
    assert t_yesterday is not None
    assert t_yesterday["preset"] == "yesterday"

    t_7d = parse_time_intent("Trong 7 ngày qua có xuất hiện không?")
    assert t_7d is not None
    assert t_7d["preset"] == "7_days"


def test_multi_turn_investigation_continuity():
    """Verify that structured context correctly updates and retains entity across multi-turn queries."""
    mgr = InvestigationMemoryManager

    # Turn 1: "Xe 30A-12345 hôm nay xuất hiện ở đâu?"
    ctx_1 = mgr.resolve_context(
        existing_context=None,
        messages=[],
        current_question="Xe 30A-12345 hôm nay xuất hiện ở đâu?",
    )
    assert ctx_1["current_entity"] is not None
    assert ctx_1["current_entity"]["type"] == "vehicle"
    assert ctx_1["current_entity"]["plate"] == "30A-12345"
    assert ctx_1["current_entity"]["normalized_plate"] == "30A12345"
    assert ctx_1["time_range"]["preset"] == "today"

    # Simulate tool execution updating context with event & alert IDs
    sample_tool_result = {
        "status": "success",
        "target_plate": "30A-12345",
        "normalized_plate": "30A12345",
        "timeline": [
            {"event_id": "evt-101", "camera_name": "Cổng 1"},
            {"event_id": "evt-102", "camera_name": "Cổng 2"},
        ],
        "alerts": [
            {"alert_id": "alt-501", "status": "sent"},
        ],
    }
    ctx_1 = mgr.update_from_tool_results(
        context=ctx_1,
        tool_name="investigate_vehicle",
        tool_args={"plate_number": "30A-12345"},
        tool_result=sample_tool_result,
    )
    assert ctx_1["last_event_id"] == "evt-102"
    assert ctx_1["last_alert_id"] == "alt-501"

    # Turn 2: "Có cảnh báo không?" -> retains plate and time_range, sets goal to check_alerts
    ctx_2 = mgr.resolve_context(
        existing_context=ctx_1,
        messages=[
            HumanMessage(content="Xe 30A-12345 hôm nay xuất hiện ở đâu?"),
            AIMessage(content="Đã tìm thấy 2 lần xuất hiện.", additional_kwargs={"investigation_context": ctx_1}),
        ],
        current_question="Có cảnh báo không?",
    )
    assert ctx_2["current_entity"]["plate"] == "30A-12345"
    assert ctx_2["time_range"]["preset"] == "today"
    assert ctx_2["investigation_goal"] == "check_alerts"
    assert ctx_2["last_event_id"] == "evt-102"
    assert ctx_2["last_alert_id"] == "alt-501"

    # Turn 3: "Thế hôm qua thì sao?" -> retains plate, shifts time_range to yesterday
    ctx_3 = mgr.resolve_context(
        existing_context=ctx_2,
        messages=[
            HumanMessage(content="Có cảnh báo không?"),
            AIMessage(content="Có 1 cảnh báo an ninh.", additional_kwargs={"investigation_context": ctx_2}),
        ],
        current_question="Thế hôm qua thì sao?",
    )
    assert ctx_3["current_entity"]["plate"] == "30A-12345"
    assert ctx_3["time_range"]["preset"] == "yesterday"

    # Turn 4: "Vậy email đã gửi chưa?" -> retains plate, sets goal to check_notifications
    ctx_4 = mgr.resolve_context(
        existing_context=ctx_3,
        messages=[
            HumanMessage(content="Thế hôm qua thì sao?"),
            AIMessage(content="Hôm qua không ghi nhận xe này.", additional_kwargs={"investigation_context": ctx_3}),
        ],
        current_question="Vậy email đã gửi chưa?",
    )
    assert ctx_4["current_entity"]["plate"] == "30A-12345"
    assert ctx_4["investigation_goal"] == "check_notifications"
    assert ctx_4["last_alert_id"] == "alt-501"

    # Turn 5: "Xóa ngữ cảnh" -> resets context back to initial clean state
    ctx_5 = mgr.resolve_context(
        existing_context=ctx_4,
        messages=[],
        current_question="Xóa ngữ cảnh để bắt đầu điều tra mới",
    )
    assert ctx_5["current_entity"] is None
    assert ctx_5["last_event_id"] is None
    assert ctx_5["last_alert_id"] is None


def test_entity_replacement():
    """Verify that mentioning a new vehicle replaces the previous entity."""
    mgr = InvestigationMemoryManager

    ctx_old = mgr.resolve_context(
        existing_context=None,
        messages=[],
        current_question="Kiểm tra xe 30A-11111",
    )
    assert ctx_old["current_entity"]["plate"] == "30A-11111"

    ctx_new = mgr.resolve_context(
        existing_context=ctx_old,
        messages=[],
        current_question="Thế còn xe 51F-22222 thì sao?",
    )
    assert ctx_new["current_entity"]["plate"] == "51F-22222"
    assert ctx_new["current_entity"]["normalized_plate"] == "51F22222"


def test_fallback_context_from_message_history():
    """When existing_context is None (e.g. state reload), retrieve entity from message history."""
    mgr = InvestigationMemoryManager

    history = [
        HumanMessage(content="Xe 29B-88888 xuất hiện lúc nào?"),
        AIMessage(
            content="Ghi nhận lúc 10:00 tại Cổng Đông.",
            additional_kwargs={
                "investigation_context": {
                    "current_entity": {
                        "type": "vehicle",
                        "plate": "29B-88888",
                        "normalized_plate": "29B88888",
                        "target_id": None,
                        "name": "Xe Khách Tuyến 1",
                    },
                    "time_range": {"preset": "today", "label": "Hôm nay"},
                    "last_event_id": "evt-999",
                }
            },
        ),
    ]

    # New turn without existing_context: "Có cảnh báo không?"
    recovered_ctx = mgr.resolve_context(
        existing_context=None,
        messages=history,
        current_question="Có cảnh báo không?",
    )

    assert recovered_ctx["current_entity"] is not None
    assert recovered_ctx["current_entity"]["plate"] == "29B-88888"
    assert recovered_ctx["current_entity"]["name"] == "Xe Khách Tuyến 1"
    assert recovered_ctx["last_event_id"] == "evt-999"
    assert recovered_ctx["investigation_goal"] == "check_alerts"
