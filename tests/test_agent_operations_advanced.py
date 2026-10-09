"""Comprehensive test suite for DATT Advanced AI Operations Agent.

Covers:
1. Traffic Analytics (group by camera/hour/type, peak hours, comparisons, zero baseline, passage distinction).
2. Vehicle Observation Timeline (cross-camera sequence, chronological order, first/latest, sequence comparisons).
3. Alert Center Inspection (status breakdown, camera breakdown, match distinction).
4. Email Notification Delivery Status (delivery status, retry counts, errors, recipient masking).
5. Operational Report Generation (executive Vietnamese markdown, grounded metrics & recommendations).
6. Multi-Tool Reasoning & Follow-up Context Preservation (multi-turn thread context, entity continuity).
"""
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agent import graph, nodes
from src.agent.config import agent_config
from src.agent.tools.analytics import get_traffic_analytics
from src.agent.tools.alerts import get_alerts
from src.agent.tools.notifications import get_notifications_status, mask_recipient
from src.agent.tools.reports import generate_operational_report
from src.db.database import Database
from src.db.models import (
    Base,
    Camera,
    FaceEvent,
    Notification,
    PlateEvent,
    Target,
    VehicleEvent,
    VehiclePassage,
    VehicleWatchlist,
    VehicleWatchlistResult,
)

CAM1_ID = UUID("11111111-1111-4111-8111-111111111111")
CAM2_ID = UUID("22222222-2222-4222-8222-222222222222")
TARGET_LONG_ID = UUID("33333333-3333-4333-8333-333333333333")
WATCHLIST_CAR_ID = UUID("44444444-4444-4444-8444-444444444444")

NOW_UTC = datetime.now(timezone.utc)
TODAY_EARLIER = NOW_UTC - timedelta(hours=3)
TODAY_RECENT = NOW_UTC - timedelta(hours=1)
YESTERDAY = NOW_UTC - timedelta(days=1)
LAST_WEEK = NOW_UTC - timedelta(days=7)


@pytest.fixture
def ops_db(tmp_path, monkeypatch):
    """Create isolated SQLite database populated with multi-camera passages, alerts and notifications."""
    db_file = tmp_path / "agent_operations.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    db = Database(db_url)
    Base.metadata.create_all(db.engine)

    with db.transaction() as session:
        # Cameras
        c1 = Camera(
            id=CAM1_ID,
            registry_key="camera_01",
            name="Cổng chính",
            location="Cổng A",
            source_type="local",
            source="cam1.mp4",
            enabled=True,
            last_active=NOW_UTC,
        )
        c2 = Camera(
            id=CAM2_ID,
            registry_key="camera_02",
            name="Cổng sau",
            location="Cổng B",
            source_type="rtsp",
            source="rtsp://192.168.1.100:554/live",
            enabled=True,
            last_active=NOW_UTC,
        )
        session.add_all([c1, c2])

        # Watchlists
        target_long = Target(
            id=TARGET_LONG_ID,
            name="Nguyễn Văn Long",
            target_type="face",
            active=True,
        )
        wl_vehicle = VehicleWatchlist(
            id=WATCHLIST_CAR_ID,
            plate_number="30A-12345",
            vehicle_type="car",
            vehicle_color="black",
            display_name="Xe của Long",
            owner_info="Nguyễn Văn Long",
            status="active",
        )
        session.add_all([target_long, wl_vehicle])
        session.flush()

        # Vehicle Passages (Today & Yesterday across both cameras)
        p1 = VehiclePassage(
            id=uuid4(),
            camera_id="camera_01",
            track_id=1,
            session_key="cam1_sess1",
            plate_text="30A-12345",
            vehicle_type="car",
            first_seen_at=TODAY_EARLIER,
            last_seen_at=TODAY_EARLIER + timedelta(seconds=10),
            duration_ms=10000.0,
        )
        p2 = VehiclePassage(
            id=uuid4(),
            camera_id="camera_02",
            track_id=2,
            session_key="cam2_sess2",
            plate_text="30A-12345",
            vehicle_type="car",
            first_seen_at=TODAY_RECENT,
            last_seen_at=TODAY_RECENT + timedelta(seconds=8),
            duration_ms=8000.0,
        )
        p3 = VehiclePassage(
            id=uuid4(),
            camera_id="camera_01",
            track_id=3,
            session_key="cam1_sess3",
            plate_text="29B-99999",
            vehicle_type="motorbike",
            first_seen_at=TODAY_RECENT,
            last_seen_at=TODAY_RECENT + timedelta(seconds=5),
            duration_ms=5000.0,
        )
        p4 = VehiclePassage(
            id=uuid4(),
            camera_id="camera_01",
            track_id=4,
            session_key="cam1_sess4",
            plate_text="51C-77777",
            vehicle_type="truck",
            first_seen_at=YESTERDAY,
            last_seen_at=YESTERDAY + timedelta(seconds=15),
            duration_ms=15000.0,
        )
        session.add_all([p1, p2, p3, p4])

        # Recognition Events (Plate & Face)
        ve1 = VehicleEvent(id=uuid4(), detection_event_id=None, vehicle_class="car", track_id=1, last_seen=TODAY_EARLIER)
        session.add(ve1)
        session.flush()

        pe1 = PlateEvent(
            id=uuid4(),
            vehicle_event_id=ve1.id,
            plate_text="30A-12345",
            normalized_plate="30A12345",
            confidence=0.96,
            created_at=TODAY_EARLIER,
        )
        pe2 = PlateEvent(
            id=uuid4(),
            vehicle_event_id=ve1.id,
            plate_text="30A-12345",
            normalized_plate="30A12345",
            confidence=0.94,
            created_at=TODAY_RECENT,
        )
        session.add_all([pe1, pe2])

        fe1 = FaceEvent(
            id=uuid4(),
            target_id=TARGET_LONG_ID,
            camera_id="camera_01",
            similarity=0.92,
            decision="MATCH",
            created_at=TODAY_EARLIER,
        )
        session.add(fe1)
        session.flush()

        wr1 = VehicleWatchlistResult(
            id=uuid4(),
            plate_event_id=pe1.id,
            watchlist_id=WATCHLIST_CAR_ID,
            normalized_plate="30A12345",
            decision="MATCH",
            display_name="Xe của Long",
            camera_id="camera_01",
            created_at=TODAY_EARLIER,
        )
        wr2 = VehicleWatchlistResult(
            id=uuid4(),
            plate_event_id=pe2.id,
            watchlist_id=WATCHLIST_CAR_ID,
            normalized_plate="30A12345",
            decision="MATCH",
            display_name="Xe của Long",
            camera_id="camera_02",
            created_at=TODAY_RECENT,
        )
        session.add_all([wr1, wr2])
        session.flush()

        # Notifications / Alerts (Email delivery logs)
        notif1 = Notification(
            id=uuid4(),
            camera_id="camera_01",
            event_id=fe1.id,
            target_id=TARGET_LONG_ID,
            recipient="security_lead@datt.vn",
            status="sent",
            retry_count=0,
            error=None,
            payload={"subject": "Cảnh báo khuôn mặt VIP"},
            created_at=TODAY_EARLIER,
            sent_at=TODAY_EARLIER + timedelta(seconds=2),
        )
        notif2 = Notification(
            id=uuid4(),
            camera_id="camera_01",
            plate_event_id=pe1.id,
            vehicle_watchlist_id=WATCHLIST_CAR_ID,
            recipient="ops_manager@datt.vn",
            status="failed",
            retry_count=3,
            error="SMTP connection timed out on port 587",
            payload={"subject": "Cảnh báo biển số"},
            created_at=TODAY_EARLIER,
        )
        notif3 = Notification(
            id=uuid4(),
            camera_id="camera_02",
            plate_event_id=pe2.id,
            vehicle_watchlist_id=WATCHLIST_CAR_ID,
            recipient="admin@datt.vn",
            status="pending",
            retry_count=1,
            error=None,
            payload={"subject": "Cảnh báo biển số"},
            created_at=TODAY_RECENT,
        )
        session.add_all([notif1, notif2, notif3])

    monkeypatch.setattr(agent_config, "get_database", lambda: Database(db_url))
    monkeypatch.setattr(nodes, "get_llm", lambda: nodes.MockChatModel())
    monkeypatch.setenv("DATT_STRICT_AUTH", "0")
    monkeypatch.setenv("DATT_REQUIRE_OPERATIONAL_AUTH", "0")
    saver = InMemorySaver()

    def ask(question, thread="ops-test-thread", user="fixture-operator", authenticated=True):
        return graph.run_agent_message(question, thread, user, authenticated, saver)

    yield db, ask, saver
    db.dispose()


# =========================================================================
# 1. Traffic Analytics Tests
# =========================================================================

def test_traffic_analytics_by_camera(ops_db):
    """Test grouping passages by camera, ranking busiest cameras."""
    res = get_traffic_analytics.invoke({"time_range": "today", "group_by": "camera"})
    assert res["status"] == "success"
    assert res["total_vehicle_passages"] >= 3
    assert len(res["grouped_analytics"]) > 0
    top_cam = res["grouped_analytics"][0]
    assert top_cam["camera_id"] == "camera_01"
    assert top_cam["passage_count"] >= 2


def test_traffic_analytics_by_hour_and_peak(ops_db):
    """Test grouping by hour and identifying the peak hour slot."""
    res = get_traffic_analytics.invoke({"time_range": "today", "group_by": "hour"})
    assert res["status"] == "success"
    assert res["busiest_period"] is not None
    assert res["busiest_period"]["dimension"] == "hour"
    assert "peak_hour" in res["busiest_period"]


def test_traffic_analytics_by_vehicle_type(ops_db):
    """Test classification breakdown across car, motorbike, truck."""
    res = get_traffic_analytics.invoke({"time_range": "7_days", "group_by": "type"})
    assert res["status"] == "success"
    assert res["vehicle_type_breakdown"]["car"] >= 2
    assert res["vehicle_type_breakdown"]["motorbike"] >= 1
    assert res["vehicle_type_breakdown"]["truck"] >= 1


def test_traffic_analytics_today_vs_yesterday_comparison(ops_db):
    """Test period comparison with trend calculation."""
    res = get_traffic_analytics.invoke({"time_range": "today", "compare_with": "yesterday"})
    assert res["status"] == "success"
    comp = res["comparison"]
    assert comp is not None
    assert comp["baseline_total_passages"] >= 1
    assert comp["current_total_passages"] >= 3
    assert comp["difference"] == comp["current_total_passages"] - comp["baseline_total_passages"]
    assert comp["percent_change"] > 0
    assert comp["trend_description"] == "tăng"


def test_traffic_analytics_zero_baseline_safety(ops_db):
    """Test baseline comparison when comparison period has 0 records (safe zero baseline)."""
    res = get_traffic_analytics.invoke({"camera_id": "camera_02", "time_range": "today", "compare_with": "yesterday"})
    assert res["status"] == "success"
    comp = res["comparison"]
    assert comp is not None
    assert comp["baseline_total_passages"] == 0
    assert comp["zero_baseline"] is True
    assert comp["percent_change"] is None
    assert "baseline = 0" in comp["trend_description"]


# =========================================================================
# 2. Alert Center History Tests
# =========================================================================

def test_get_alerts_status_filtering(ops_db):
    """Test alert lookup filtering by status (sent, failed, pending)."""
    res_all = get_alerts.invoke({"status": "all"})
    assert res_all["status"] == "success"
    assert res_all["total_alerts"] == 3
    assert res_all["status_breakdown"]["sent"] == 1
    assert res_all["status_breakdown"]["failed"] == 1
    assert res_all["status_breakdown"]["pending"] == 1

    res_failed = get_alerts.invoke({"status": "failed"})
    assert res_failed["status"] == "success"
    assert len(res_failed["alerts"]) == 1
    assert res_failed["alerts"][0]["status"] == "failed"
    assert "delivery failed" in res_failed["alerts"][0]["error"].lower()


def test_get_alerts_by_camera(ops_db):
    """Test alert grouping and filtering by camera."""
    res = get_alerts.invoke({"camera_id": "camera_01"})
    assert res["status"] == "success"
    assert res["total_alerts"] == 2
    for a in res["alerts"]:
        assert a["camera_id"] == "camera_01"


# =========================================================================
# 3. Email Notification Delivery Status Tests
# =========================================================================

def test_notification_delivery_inspection_and_masking(ops_db):
    """Test notification outbox inspection, retry counts, and email address privacy masking."""
    res = get_notifications_status.invoke({"plate_number": "30A-12345"})
    assert res["status"] == "success"
    assert res["total_notifications"] == 2

    # Verify recipient masking
    for n in res["notifications"]:
        masked = n["recipient_masked"]
        assert "@datt.vn" in masked
        assert not masked.startswith("ops_manager@")
        assert not masked.startswith("admin@")

    # Verify retry count reported accurately
    failed_notif = next(n for n in res["notifications"] if n["status"] == "failed")
    assert failed_notif["retry_count"] == 3
    assert "delivery failed" in failed_notif["error_reason"].lower()


def test_mask_recipient_helper():
    """Unit test for mask_recipient privacy logic."""
    assert mask_recipient("long@gmail.com") == "lo***@gmail.com"
    assert mask_recipient("a@domain.com") == "a***@domain.com"
    assert mask_recipient(None) == "chưa có người nhận"


# =========================================================================
# 4. Operational Report Generation Tests
# =========================================================================

def test_generate_operational_report_structure(ops_db):
    """Test automated executive operational report generation in Vietnamese markdown."""
    res = generate_operational_report.invoke({"period": "today"})
    assert res["status"] == "success"
    metrics = res["metrics"]
    assert metrics["cameras"]["total"] == 2
    assert metrics["traffic"]["total_passages"] >= 3
    assert metrics["security"]["total_matches"] >= 2
    assert metrics["alerts_and_notifications"]["total_alerts"] == 3

    report_md = res["report_markdown"]
    assert "BÁO CÁO VẬN HÀNH HỆ THỐNG DATT" in report_md
    assert "Trạng Thái Hạ Tầng Camera" in report_md
    assert "Lưu Lượng & Phân Loại Phương Tiện" in report_md
    assert "Khuyến Nghị Vận Hành" in report_md
    assert "camera_01" in report_md


# =========================================================================
# 5. LangGraph & Multi-Tool Reasoning Integration Tests
# =========================================================================

def test_agent_operational_report_query(ops_db):
    """Agent answers 'Tổng hợp hoạt động hệ thống hôm nay' by invoking operational report."""
    _, ask, _ = ops_db
    result = ask("Tổng hợp hoạt động hệ thống hôm nay")
    assert "generate_operational_report" in result["tools_called"]
    assert "BÁO CÁO VẬN HÀNH" in result["reply"]
    assert "Cổng chính" in result["reply"] or "camera_01" in result["reply"]


def test_agent_multi_tool_reasoning_query(ops_db):
    """Agent answers a complex operational question requiring traffic, alerts, and notification status."""
    _, ask, _ = ops_db
    query = "Camera 01 hôm nay có bao nhiêu lượt xe, có cảnh báo nào bất thường không, và email cảnh báo đã gửi thành công chưa?"
    result = ask(query)

    # Verify tool calls executed in the turn
    assert "get_traffic_analytics" in result["tools_called"] or "get_event_statistics" in result["tools_called"]
    assert "get_alerts" in result["tools_called"]
    assert "get_notifications_status" in result["tools_called"]

    # Verify unified synthesized response covers all 3 aspects
    content = result["reply"]
    assert "lưu lượng" in content.lower() or "lượt xe" in content.lower()
    assert "cảnh báo" in content.lower()
    assert "thông báo" in content.lower() or "email" in content.lower()


def test_agent_observation_timeline_cross_camera(ops_db):
    """Agent answers observation timeline question comparing which camera saw vehicle 30A-12345 first."""
    _, ask, _ = ops_db
    query = "Xe 30A-12345 được nhìn thấy tại Camera 01 trước hay Camera 02?"
    result = ask(query)
    assert "search_events" in result["tools_called"]
    assert "30A-12345" in result["reply"] or "30A12345" in result["reply"]
    assert "trước" in result["reply"].lower()


def test_agent_contextual_follow_up_workflow(ops_db):
    """Test contextual thread follow-up continuity:
    Turn 1: 'Tìm lịch sử xe 30A-12345'
    Turn 2: 'Hôm qua thì sao?' (updates date filter, preserves plate)
    Turn 3: 'Vậy có gửi cảnh báo không?' (preserves vehicle context, queries alerts)
    """
    _, ask, _ = ops_db

    # Turn 1
    t1 = ask("Tìm lịch sử xe 30A-12345", thread="follow-up-1")
    assert "30A-12345" in t1["reply"] or "30A12345" in t1["reply"]
    assert "search_events" in t1["tools_called"]

    # Turn 2
    t2 = ask("Hôm qua thì sao?", thread="follow-up-1")
    assert "30A-12345" in t2["reply"] or "30A12345" in t2["reply"]

    # Turn 3
    t3 = ask("Vậy có gửi cảnh báo không?", thread="follow-up-1")
    assert "get_alerts" in t3["tools_called"] or "get_notifications_status" in t3["tools_called"]
    assert "cảnh báo" in t3["reply"].lower()
