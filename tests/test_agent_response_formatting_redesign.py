"""Tests for DATT AI Agent Redesigned Operational Response Formatting.

Verifies:
1. Single vehicle event concise formatting matching Section 3 specification.
2. Color mismatch notification with formatted percentage confidence.
3. Matching vehicle color does NOT trigger any warning.
4. Notification status semantics (SMTP acceptance, suppressed, etc.).
5. Missing camera metadata handling.
6. Detail levels: Concise, Explanation, Technical.
7. Explicit JSON formatting preservation.
8. Multi-event query summarization and pagination notices.
9. Contextual follow-up questions: event ID retention and 'Xem kỹ hơn'.
10. MockChatModel produces readable operational answers.
11. Security redaction of secrets and basic auth URLs.
"""
import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.agent import graph, nodes
from src.agent.response_formatting import (
    DETAIL_CONCISE,
    DETAIL_EXPLANATION,
    DETAIL_TECHNICAL,
    format_camera_info,
    format_event_list,
    format_notification_status,
    format_result,
    format_single_face_event,
    format_single_vehicle_event,
    format_tool_messages,
    get_detail_level,
    safe_result,
    utc_to_vietnam_time,
    wants_json,
)
from src.db.database import Database
from src.db.models import Base, Camera, DetectionEvent, PlateEvent, VehicleEvent, VehicleWatchlist, VehicleWatchlistResult


def test_section_3_single_vehicle_event_concise_spec():
    """Verify Section 3 example exact concise response contract."""
    input_event = {
        "plate": "24C14070",
        "event_type": "plate",
        "semantic_type": "VEHICLE_WATCHLIST_MATCH",
        "vehicle_type": "car",
        "detected_vehicle_color": "yellow",
        "watchlist_vehicle_color": "brown",
        "detected_vehicle_color_confidence": 0.618992,
        "plate_confidence": 0.644930,
        "timestamp": "2026-10-02T08:14:41.632246+00:00",
        "camera_id": "local_1790927843.5485723",
        "camera_location": "unavailable",
        "notification_status": "sent",
    }

    result = format_single_vehicle_event(input_event, detail_level=DETAIL_CONCISE)

    expected = (
        "Đã phát hiện ô tô biển số **24C14070** trùng Watchlist lúc **15:14 ngày 02/10/2026** (giờ Việt Nam).\n\n"
        "**Lưu ý:** Xe được nhận diện màu vàng, trong khi Watchlist đăng ký màu nâu. Độ tin cậy nhận diện màu khoảng 61,9%.\n\n"
        "**Email cảnh báo:** Đã được máy chủ SMTP chấp nhận.\n\n"
        "Camera: local_1790927843.5485723. Chưa có thông tin vị trí."
    )

    assert result == expected
    # Ensure no raw internal identifiers dumped
    assert "VEHICLE_WATCHLIST_MATCH" not in result
    assert "0.644930" not in result
    assert "2026-10-02T08:14:41" not in result


def test_matching_vehicle_color_no_invented_warning():
    """When detected color matches registered watchlist color, no warning is emitted."""
    event = {
        "plate": "30A12345",
        "event_type": "plate",
        "semantic_type": "VEHICLE_WATCHLIST_MATCH",
        "vehicle_type": "car",
        "detected_vehicle_color": "black",
        "watchlist_vehicle_color": "black",
        "detected_vehicle_color_confidence": 0.95,
        "timestamp": "2026-10-08T08:30:00+00:00",
        "camera_id": "CAM_01",
        "camera_name": "Cổng chính",
        "camera_location": "Cổng A, tầng 1",
        "notification_status": "sent",
    }
    result = format_single_vehicle_event(event, detail_level=DETAIL_CONCISE)
    assert "**Lưu ý:**" not in result
    assert "màu" not in result.lower() or "xe" in result.lower()
    assert "Đã phát hiện ô tô biển số **30A12345** trùng Watchlist lúc **15:30 ngày 08/10/2026** (giờ Việt Nam)." in result
    assert "Camera: Cổng chính (Cổng A, tầng 1)." in result


def test_missing_camera_metadata_handling():
    """Camera missing location is safely presented without inventing location."""
    # Location unavailable
    msg1 = format_camera_info("cam_test", None, "unavailable")
    assert msg1 == "Camera: cam_test. Chưa có thông tin vị trí."

    # Location missing None
    msg2 = format_camera_info("cam_test", None, None)
    assert msg2 == "Camera: cam_test. Chưa có thông tin vị trí."

    # Location present with camera name
    msg3 = format_camera_info("cam_uuid", "Cổng chính", "Tầng 1")
    assert msg3 == "Camera: Cổng chính (Tầng 1)."


def test_notification_status_semantics():
    """Preserve accurate SMTP acceptance vs suppressed vs failed semantics."""
    assert format_notification_status("sent") == "**Email cảnh báo:** Đã được máy chủ SMTP chấp nhận."
    assert "chặn" in format_notification_status("suppressed")
    assert "thất bại" in format_notification_status("failed")
    assert "chờ" in format_notification_status("pending")

    # Explanation level notes SMTP acceptance limitation
    exp_sent = format_notification_status("sent", detail_level=DETAIL_EXPLANATION)
    assert "SMTP" in exp_sent
    assert "không theo dõi việc người nhận đã mở hoặc đọc email" in exp_sent


def test_three_detail_levels_vehicle_event():
    """Test concise, explanation, and technical detail levels."""
    event = {
        "event_id": "plate:11111111-2222-3333-4444-555555555555",
        "plate": "51F88888",
        "vehicle_type": "truck",
        "timestamp": "2026-10-05T03:00:00+00:00",
        "camera_id": "CAM_02",
        "camera_location": "Bãi xe",
        "plate_confidence": 0.887,
        "notification_status": "sent",
    }

    # Concise: no technical evidence or raw event ID
    concise = format_single_vehicle_event(event, detail_level=DETAIL_CONCISE)
    assert "plate:11111111" not in concise
    assert "Độ tin cậy" not in concise
    assert "51F88888" in concise
    assert "10:00 ngày 05/10/2026" in concise
    assert "(giờ Việt Nam)" in concise

    # Explanation: includes OCR confidence and limitations
    explanation = format_single_vehicle_event(event, detail_level=DETAIL_EXPLANATION)
    assert "Bằng chứng kỹ thuật & Giới hạn:" in explanation
    assert "Độ tin cậy nhận diện biển số (OCR): 88,7%." in explanation
    assert "Giới hạn dữ liệu:" in explanation

    # Technical: includes event ID, UTC time, raw camera details
    technical = format_single_vehicle_event(event, detail_level=DETAIL_TECHNICAL)
    assert "Thông tin kỹ thuật đầy đủ:" in technical
    assert "ID sự kiện: plate:11111111-2222-3333-4444-555555555555" in technical
    assert "Thời điểm (UTC): 2026-10-05T03:00:00+00:00" in technical
    assert "Thời điểm (ICT): 10:00 ngày 05/10/2026 (giờ Việt Nam)" in technical


def test_detail_level_intent_resolution():
    """Verify user query intent triggers the appropriate detail level."""
    assert get_detail_level("Xe 30A-12345 xuất hiện ở đâu?") == DETAIL_CONCISE
    assert get_detail_level("Tại sao hệ thống nhận diện xe này?") == DETAIL_EXPLANATION
    assert get_detail_level("Giải thích nguyên nhân và bằng chứng") == DETAIL_EXPLANATION
    assert get_detail_level("Căn cứ nào xác định biển số này?") == DETAIL_EXPLANATION
    assert get_detail_level("Cho tôi toàn bộ dữ liệu sự kiện") == DETAIL_TECHNICAL
    assert get_detail_level("Thông tin kỹ thuật") == DETAIL_TECHNICAL
    assert get_detail_level("Debug sự kiện") == DETAIL_TECHNICAL
    assert get_detail_level("Xem kỹ hơn") == DETAIL_TECHNICAL

    # 'Chi tiết' alone should not trigger technical dump
    assert get_detail_level("Cho tôi biết chi tiết về xe này") == DETAIL_CONCISE


def test_explicit_json_contract():
    """Explicit JSON queries produce valid ```json ``` markdown code blocks."""
    assert wants_json("Xuất kết quả dạng JSON") is True
    assert wants_json("Cho tôi json") is True
    assert wants_json("Tìm xe 30A-12345 hiển thị json") is True
    assert wants_json("Không dùng json nhé") is False

    mock_msg = ToolMessage(
        content=json.dumps({"status": "success", "plate": "30A12345", "vehicle_type": "car"}),
        tool_call_id="call_1",
        name="search_events",
    )
    user_msg = HumanMessage(content="Tìm xe 30A-12345 hiển thị JSON")
    ai_msg = AIMessage(content="", tool_calls=[{"name": "search_events", "args": {}, "id": "call_1"}])

    res = format_tool_messages([user_msg, ai_msg, mock_msg])
    assert res.startswith("```json")
    assert res.strip().endswith("```")
    payload = json.loads(res.strip()[7:-3])
    assert payload["plate"] == "30A12345"


def test_multi_event_query_summarization():
    """Multiple event query summarizes total results and displays recent items first."""
    events = [
        {
            "plate": f"30A{i:05d}",
            "vehicle_type": "car",
            "timestamp": f"2026-10-08T0{i}:00:00+00:00",
            "camera_name": f"Camera {i}",
        }
        for i in range(1, 8)
    ]

    res = format_event_list(events, total=15, detail_level=DETAIL_CONCISE)
    assert "Hệ thống ghi nhận tổng cộng **15** sự kiện phù hợp" in res
    assert "hiển thị 5 sự kiện gần nhất" in res
    assert "Trang hiện tại hiển thị 7/15 sự kiện" in res


def test_face_event_concise_and_explanation():
    """Face event formatting respects concise and explanation levels."""
    face_event = {
        "event_id": "face:99999999-9999-4999-8999-999999999999",
        "target_name": "Nguyễn Văn Long",
        "similarity": 0.9425,
        "timestamp": "2026-10-08T09:30:00+00:00",
        "camera_name": "Sảnh lễ tân",
        "camera_location": "Tòa B",
        "notification_status": "sent",
    }

    concise = format_single_face_event(face_event, detail_level=DETAIL_CONCISE)
    assert "Đã ghi nhận nhận diện khuôn mặt của **Nguyễn Văn Long** lúc **16:30 ngày 08/10/2026** (giờ Việt Nam)." in concise
    assert "Email cảnh báo" in concise
    assert "Camera: Sảnh lễ tân (Tòa B)." in concise
    assert "0.9425" not in concise

    explanation = format_single_face_event(face_event, detail_level=DETAIL_EXPLANATION)
    assert "Độ tương đồng khuôn mặt: 94,2%." in explanation
    assert "Giới hạn dữ liệu:" in explanation


def test_security_redaction_preserves_safety():
    """Sensitive passwords, tokens, API keys, and basic-auth credentials are redacted."""
    raw = {
        "camera_url": "rtsp://admin:super_secret_password@192.168.1.50:554/live",
        "api_key": "sk-secret-12345",
        "password": "my_password",
        "plate": "30A12345",
    }
    redacted = safe_result(raw)
    assert redacted["api_key"] == "đã ẩn"
    assert redacted["password"] == "đã ẩn"
    assert "super_secret_password" not in redacted["camera_url"]
    assert "rtsp://***@" in redacted["camera_url"]
    assert redacted["plate"] == "30A12345"


@pytest.fixture
def mock_agent_app(tmp_path, monkeypatch):
    """Set up database and agent for multi-turn conversational follow-up tests."""
    url = "sqlite:///" + (tmp_path / "format_test.db").as_posix()
    db = Database(url)
    Base.metadata.create_all(db.engine)

    cam_id = uuid4()
    with db.transaction() as session:
        session.add(
            Camera(
                id=cam_id,
                registry_key="CAM_TEST",
                name="Cổng Tây",
                location="Khu vực cổng phụ",
                source_type="local",
                source="test.mp4",
            )
        )
        wl = VehicleWatchlist(
            id=uuid4(),
            plate_number="24C-14070",
            vehicle_type="car",
            vehicle_color="brown",
            display_name="Xe tải chở hàng",
            status="active",
        )
        session.add(wl)
        ve = VehicleEvent(
            id=uuid4(),
            detection_event_id=None,
            vehicle_class="car",
            track_id=1,
            last_seen=datetime(2026, 10, 2, 8, 14, 41, tzinfo=timezone.utc),
            vehicle_color="yellow",
        )
        session.add(ve)
        session.flush()

        pe = PlateEvent(
            id=uuid4(),
            vehicle_event_id=ve.id,
            plate_text="24C14070",
            normalized_plate="24C14070",
            confidence=0.85,
            created_at=datetime(2026, 10, 2, 8, 14, 41, tzinfo=timezone.utc),
        )
        session.add(pe)
        session.flush()

        wr = VehicleWatchlistResult(
            id=uuid4(),
            plate_event_id=pe.id,
            watchlist_id=wl.id,
            normalized_plate="24C14070",
            decision="MATCH",
            display_name="Xe tải chở hàng",
            camera_id="CAM_TEST",
            created_at=datetime(2026, 10, 2, 8, 14, 41, tzinfo=timezone.utc),
        )
        session.add(wr)

    monkeypatch.setattr("src.agent.config.agent_config.get_database", lambda: Database(url))
    monkeypatch.setattr(nodes, "get_llm", lambda: nodes.MockChatModel())
    monkeypatch.setenv("DATT_STRICT_AUTH", "0")
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "0")

    saver = InMemorySaver()

    def ask(question, thread="test-thread"):
        return graph.run_agent_message(question, thread, "operator", True, saver)

    yield ask, db
    db.dispose()


def test_conversational_follow_up_retains_event_id(mock_agent_app):
    """Verify follow-up questions 'Cho tôi ID sự kiện đó' and 'Xem kỹ hơn' retain event context."""
    ask, _ = mock_agent_app

    # Turn 1: Search event
    t1 = ask("Tìm xe 24C14070", thread="test-followup-id")
    assert "search_events" in t1["tools_called"]
    assert "24C14070" in t1["reply"]

    # Turn 2: Ask for event ID
    t2 = ask("Cho tôi ID sự kiện đó", thread="test-followup-id")
    assert "ID sự kiện vừa tra cứu là:" in t2["reply"]
    assert "plate:" in t2["reply"]

    # Turn 3: Ask to inspect more closely
    t3 = ask("Xem kỹ hơn", thread="test-followup-id")
    assert "Thông tin kỹ thuật đầy đủ:" in t3["reply"]
    assert "24C14070" in t3["reply"]
