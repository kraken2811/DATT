"""Regression tests for compound Face Recognition History + Email Notification multi-tool workflow."""

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from src.agent import graph, nodes
from src.agent.config import agent_config
from src.agent.face_history import history_subject, asks_notifications
from src.agent.tools.alerts import get_alerts
from src.agent.tools.events import search_events
from src.agent.tools.notifications import get_notifications_status
from src.agent.tools.watchlist import search_watchlist
from src.db.database import Database
from src.db.models import Base, Camera, FaceEvent, Notification, Target
from src.event_center.service import query as query_events


LONG_ID = UUID("11111111-1111-4111-8111-111111111111")
ANOTHER_LONG_ID = UUID("22222222-2222-4222-8222-222222222222")
MAI_ID = UUID("33333333-3333-4333-8333-333333333333")
NO_NOTIF_PERSON_ID = UUID("44444444-4444-4444-8444-444444444444")

CAM_GATE_ID = UUID("55555555-5555-4555-8555-555555555555")
CAM_LOBBY_ID = UUID("66666666-6666-4666-8666-666666666666")

EVENT_OLD_ID = UUID("77777777-7777-4777-8777-777777777777")
EVENT_NEW_ID = UUID("88888888-8888-4888-8888-888888888888")
EVENT_MAI_ID = UUID("99999999-9999-4999-8999-999999999999")
EVENT_NO_NOTIF_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

NOTIF_OLD_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
NOTIF_NEW_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NOTIF_MAI_ID = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")

TS_OLD = datetime(2026, 10, 8, 8, 0, 0, tzinfo=timezone.utc)
TS_NEW = datetime(2026, 10, 8, 9, 30, 0, tzinfo=timezone.utc)
TS_MAI = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def regression_db(tmp_path, monkeypatch):
    """Database fixture matching required regression scenario."""
    url = "sqlite:///" + (tmp_path / "regression_face_notif.db").as_posix()
    db = Database(url)
    Base.metadata.create_all(db.engine)

    with db.transaction() as session:
        # Targets
        session.add_all([
            Target(id=LONG_ID, name="Long", target_type="face", active=True),
            Target(id=MAI_ID, name="Mai", target_type="person", active=True),
            Target(id=NO_NOTIF_PERSON_ID, name="Hoang", target_type="face", active=True),
        ])
        session.flush()

        # Cameras
        session.add_all([
            Camera(
                id=CAM_GATE_ID,
                registry_key="CAM_GATE",
                name="Cổng chính",
                location="Cổng A, tầng 1",
                source_type="local",
                source="gate.mp4",
            ),
            Camera(
                id=CAM_LOBBY_ID,
                registry_key="CAM_LOBBY",
                name="Sảnh lễ tân",
                location="Tòa B, sảnh chính",
                source_type="local",
                source="lobby.mp4",
            ),
        ])
        session.flush()

        # Face Recognition Events
        # 1. Older event for Long (CAM_GATE, 08:00 UTC)
        session.add(
            FaceEvent(
                id=EVENT_OLD_ID,
                camera_id="CAM_GATE",
                target_id=LONG_ID,
                decision="FACE_MATCH",
                similarity=0.9123,
                created_at=TS_OLD,
            )
        )
        # 2. Newer event for Long (CAM_LOBBY, 09:30 UTC)
        session.add(
            FaceEvent(
                id=EVENT_NEW_ID,
                camera_id="CAM_LOBBY",
                target_id=LONG_ID,
                decision="FACE_MATCH",
                similarity=0.8456,
                created_at=TS_NEW,
            )
        )
        # 3. Another person's event (Mai, CAM_GATE, 10:00 UTC)
        session.add(
            FaceEvent(
                id=EVENT_MAI_ID,
                camera_id="CAM_GATE",
                target_id=MAI_ID,
                decision="FACE_MATCH",
                similarity=0.9500,
                created_at=TS_MAI,
            )
        )
        # 4. Event for Hoang without any notification
        session.add(
            FaceEvent(
                id=EVENT_NO_NOTIF_ID,
                camera_id="CAM_GATE",
                target_id=NO_NOTIF_PERSON_ID,
                decision="FACE_MATCH",
                similarity=0.8900,
                created_at=TS_OLD,
            )
        )
        session.flush()

        # Notifications
        # Linked to older event -> sent
        session.add(
            Notification(
                id=NOTIF_OLD_ID,
                event_id=EVENT_OLD_ID,
                target_id=LONG_ID,
                camera_id="CAM_GATE",
                channel="email",
                status="sent",
                recipient="admin@datt.vn",
                payload={"subject": "Cảnh báo khuôn mặt"},
                sent_at=datetime(2026, 10, 8, 8, 0, 5, tzinfo=timezone.utc),
                created_at=datetime(2026, 10, 8, 8, 0, 1, tzinfo=timezone.utc),
            )
        )
        # Linked to newer event -> suppressed
        session.add(
            Notification(
                id=NOTIF_NEW_ID,
                event_id=EVENT_NEW_ID,
                target_id=LONG_ID,
                camera_id="CAM_LOBBY",
                channel="email",
                status="suppressed",
                recipient="security@datt.vn",
                payload={"subject": "Cảnh báo khuôn mặt"},
                created_at=datetime(2026, 10, 8, 9, 30, 2, tzinfo=timezone.utc),
            )
        )
        # Linked to Mai's event -> sent
        session.add(
            Notification(
                id=NOTIF_MAI_ID,
                event_id=EVENT_MAI_ID,
                target_id=MAI_ID,
                camera_id="CAM_GATE",
                channel="email",
                status="sent",
                recipient="hr@datt.vn",
                payload={"subject": "Cảnh báo khuôn mặt"},
                sent_at=datetime(2026, 10, 8, 10, 0, 4, tzinfo=timezone.utc),
                created_at=datetime(2026, 10, 8, 10, 0, 1, tzinfo=timezone.utc),
            )
        )

    monkeypatch.setattr(agent_config, "get_database", lambda: Database(url))
    monkeypatch.setattr(nodes, "get_llm", lambda: nodes.MockChatModel())
    monkeypatch.setenv("DATT_STRICT_AUTH", "0")
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "0")

    saver = InMemorySaver()

    def ask(question, thread="test-face-notif", user="operator", authenticated=True):
        return graph.run_agent_message(question, thread, user, authenticated, saver)

    yield db, ask, saver, url
    db.dispose()


def test_intent_detection_vietnamese_phrases():
    """Verify intent detection matches all required Vietnamese variants."""
    assert history_subject("Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?") == "Long"
    assert asks_notifications("Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?") is True

    # Variations from specification
    assert history_subject("Tìm thấy khuôn mặt Long gần nhất ở đâu?") == "Long"
    assert history_subject("Khuôn mặt Long lần cuối xuất hiện ở đâu?") == "Long"
    assert history_subject("Khuôn mặt Long lần gần đây nhất xuất hiện lúc nào?") == "Long"
    assert history_subject("Khuôn mặt Long xuất hiện ở đâu?") == "Long"
    assert history_subject("Khuôn mặt Long xuất hiện lúc nào?") == "Long"
    assert history_subject("Khuôn mặt Long đã nhận diện ở camera nào?") == "Long"
    assert history_subject("Long được tìm thấy gần nhất ở đâu và khi nào?") == "Long"

    assert asks_notifications("đã gửi email cảnh báo chưa?") is True
    assert asks_notifications("đã gửi mail cảnh báo chưa?") is True
    assert asks_notifications("có gửi cảnh báo không?") is True
    assert asks_notifications("Khuôn mặt Long xuất hiện lúc nào?") is False


def test_reproduced_question_latest_recognition_and_suppressed_notification(regression_db):
    """Reproduce exact question:
    'Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?'
    Verify:
    1. Tool sequence: search_watchlist -> search_events -> get_notifications_status
    2. Correct latest event chosen (CAM_LOBBY at 09:30, NOT older CAM_GATE at 08:00)
    3. Correct linked notification status reported (suppressed, NOT sent from older event)
    4. Identity Long resolved, Mai's event excluded
    5. Recipient masked
    """
    _, ask, saver, _ = regression_db
    question = "Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?"
    result = ask(question, thread="reproduce-1")

    # 1. Exact tool call sequence
    assert result["tools_called"] == ["search_watchlist", "search_events", "get_notifications_status"]

    # 2. Check tool calls and arguments in LangGraph state
    config = graph.make_thread_config("reproduce-1", user_id="operator")
    state = graph.build_agent_graph(saver).get_state(config)
    ai_messages = [m for m in state.values["messages"] if isinstance(m, AIMessage) and m.tool_calls]

    assert len(ai_messages) == 3
    # Step 1: search_watchlist
    call1 = ai_messages[0].tool_calls[0]
    assert call1["name"] == "search_watchlist"
    assert call1["args"]["query"] == "Long"
    assert call1["args"]["watchlist_type"] == "face"

    # Step 2: search_events with resolved target_id
    call2 = ai_messages[1].tool_calls[0]
    assert call2["name"] == "search_events"
    assert call2["args"]["target_id"] == str(LONG_ID)
    assert call2["args"]["event_type"] == "face"
    assert call2["args"]["watchlist_match"] is True

    # Step 3: get_notifications_status with exact event_id
    call3 = ai_messages[2].tool_calls[0]
    assert call3["name"] == "get_notifications_status"
    assert str(EVENT_NEW_ID) in call3["args"]["event_id"]
    assert call3["args"]["target_id"] == str(LONG_ID)

    # 3. Grounded reply verification
    reply = result["reply"]
    # Includes identity Long
    assert "Long" in reply and str(LONG_ID) in reply
    # Mai must NOT be in reply
    assert "Mai" not in reply and str(MAI_ID) not in reply

    # Latest event details (CAM_LOBBY, 09:30:00)
    assert "CAM_LOBBY" in reply
    assert "Sảnh lễ tân" in reply
    assert "Tòa B, sảnh chính" in reply
    assert TS_NEW.isoformat() in reply

    # Must NOT report older event as the latest
    assert "0.8456" in reply

    # Linked notification status for latest event is suppressed
    assert "suppressed" in reply.lower() or "chặn" in reply.lower()
    # Must NOT claim sent for this latest event
    assert "se***@datt.vn" in reply or "security" not in reply  # email is masked
    assert "security@datt.vn" not in reply  # never expose raw unmasked email


def test_face_event_without_notification(regression_db):
    """Person with face events but zero notification records:
    Agent reports recognition facts and states no email notification was found.
    Never claims 0 recognitions just because no notification was found.
    """
    _, ask, _, _ = regression_db
    question = "Khuôn mặt Hoang được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?"
    result = ask(question, thread="no-notif-thread")

    assert result["tools_called"] == ["search_watchlist", "search_events", "get_notifications_status"]
    reply = result["reply"]
    # Recognizes Hoang
    assert "Hoang" in reply and str(NO_NOTIF_PERSON_ID) in reply
    assert "CAM_GATE" in reply
    # Explicitly reports no notification record found
    assert "chưa có bản ghi thông báo" in reply.lower() or "không có thông báo" in reply.lower()
    # Must not claim 0 detections
    assert "Tổng số kết quả phù hợp: 1" in reply


def test_no_matching_identity(regression_db):
    """When person is not in Face Watchlist, agent stops and does not query events."""
    _, ask, _, _ = regression_db
    question = "Khuôn mặt NgườiLạ được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?"
    result = ask(question, thread="not-found-thread")

    assert result["tools_called"] == ["search_watchlist"]
    assert "Không tìm thấy người phù hợp" in result["reply"]
    assert "NgườiLạ" in result["reply"]


def test_multiple_matching_identities(regression_db, tmp_path):
    """When multiple people match query name, agent asks operator to choose ID."""
    db, ask, _, url = regression_db
    # Add second Long
    with db.transaction() as session:
        session.add(Target(id=ANOTHER_LONG_ID, name="Long", target_type="face", active=True))

    result = ask("Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?", thread="disambiguate-thread")
    assert result["tools_called"] == ["search_watchlist"]
    assert "Có nhiều người phù hợp" in result["reply"]
    assert str(LONG_ID) in result["reply"]
    assert str(ANOTHER_LONG_ID) in result["reply"]


def test_contextual_follow_up_face_notification(regression_db):
    """Contextual multi-turn conversation:
    Turn 1: 'Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào?'
    Turn 2: 'Đã gửi mail cảnh báo chưa?'
    """
    _, ask, _, _ = regression_db
    t1 = ask("Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào?", thread="followup-face")
    assert "search_watchlist" in t1["tools_called"]
    assert "search_events" in t1["tools_called"]
    assert "Long" in t1["reply"]

    t2 = ask("Đã gửi mail cảnh báo chưa?", thread="followup-face")
    assert "get_notifications_status" in t2["tools_called"]
    assert "suppressed" in t2["reply"].lower() or "chặn" in t2["reply"].lower()


def test_database_error_handling(regression_db, monkeypatch):
    """Database query failure during notifications lookup reports error gracefully."""
    _, ask, _, _ = regression_db

    # Force database query in get_notifications_status to raise
    def fail_query(*args, **kwargs):
        raise RuntimeError("Database connection timed out")

    monkeypatch.setattr("src.agent.tools.notifications.filtered_notifications", fail_query)

    result = ask("Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?", thread="err-thread")
    assert "Long" in result["reply"]
    # Recognizes face event
    assert "CAM_LOBBY" in result["reply"]
    # Notes notification status could not be verified
    assert "chưa thể xác minh" in result["reply"].lower() or "lỗi" in result["reply"].lower()


def test_unauthorized_access_handling(regression_db, monkeypatch):
    """Strict authorization blocks sensitive operational tools for unauthenticated calls."""
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "1")
    monkeypatch.setenv("DATT_STRICT_AUTH", "1")

    _, ask, _, _ = regression_db
    result = ask("Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?", thread="unauth-thread", authenticated=False)

    # Result should inform unauthorized access
    assert "truy cập bị từ chối" in result["reply"].lower() or "xác thực" in result["reply"].lower() or "unauthorized" in result["reply"].lower()


def test_compare_with_event_center_and_alert_center(regression_db):
    """Compare Agent findings with underlying Event Center and Alert Center SQL queries."""
    db, _, _, _ = regression_db

    with db.transaction() as session:
        # Event Center query for Long
        ec_result = query_events(session, {"target_id": str(LONG_ID), "event_type": "face"})
        assert ec_result["total"] == 2
        events = ec_result["events"]
        # Newest first
        assert events[0]["source_event_id"] == str(EVENT_NEW_ID)
        assert events[0]["camera_id"] == "CAM_LOBBY"
        assert events[0]["notification_status"] == "suppressed"
        # Face similarity is exposed
        assert events[0]["similarity"] == 0.8456
        assert events[0]["confidence"] == 0.8456  # mapped projection column

        # Older event
        assert events[1]["source_event_id"] == str(EVENT_OLD_ID)
        assert events[1]["camera_id"] == "CAM_GATE"
        assert events[1]["notification_status"] == "sent"
        assert events[1]["similarity"] == 0.9123

    # Alert Center query for Long
    alerts_result = get_alerts.invoke({"target_id": str(LONG_ID), "limit": 10})
    assert alerts_result["status"] == "success"
    assert alerts_result["total_alerts"] == 2
    # Verify latest alert in Alert Center is the suppressed one
    assert alerts_result["alerts"][0]["status"] == "suppressed"
    assert alerts_result["alerts"][0]["camera_id"] == "CAM_LOBBY"
    assert alerts_result["alerts"][1]["status"] == "sent"
    assert alerts_result["alerts"][1]["camera_id"] == "CAM_GATE"


def test_notification_without_usable_timestamp(regression_db, monkeypatch):
    """Notification record with null timestamps formats cleanly without crashing."""
    _, ask, _, _ = regression_db

    from src.agent.tools import notifications
    real_status = notifications.get_notifications_status.func

    def mock_status(*args, **kwargs):
        res = real_status(*args, **kwargs)
        if res.get("status") == "success" and res.get("notifications"):
            # Set all timestamps to None to verify formatting resilience
            for item in res["notifications"]:
                item["sent_at"] = None
                item["created_at"] = None
        return res

    monkeypatch.setattr(notifications.get_notifications_status, "func", mock_status)

    result = ask("Khuôn mặt Long được tìm thấy gần nhất ở đâu và khi nào, đã gửi mail cảnh báo chưa?", thread="no-ts-thread")
    assert result["tools_called"] == ["search_watchlist", "search_events", "get_notifications_status"]
    assert "suppressed" in result["reply"].lower() or "chặn" in result["reply"].lower()
    assert "Long" in result["reply"]
