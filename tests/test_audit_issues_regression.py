"""Comprehensive regression tests covering audit issues 1 through 7:
1. Vehicle vs Face popup alert label separation
2. Camera status list query tool (list_cameras, get_camera_status without camera_id)
3. Alert availability independent from notification email outbox
4. RAG cache TTL, max capacity eviction, and invalidation
5. Prompt Guard multi-chunk sampling (start, middle, end) and fail-open/closed config
6. Tool timeout handling, executor bounds, backpressure shedding, and metrics
7. Plate recognition latency: immediate confirmation emission and milestone timestamps
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.db.database import Database
from src.db.models import (
    Base,
    Camera,
    FaceEvent,
    Target,
    Notification,
    PlateEvent,
    VehicleEvent,
    VehicleWatchlist,
    VehicleWatchlistResult,
    utc_now,
)
from src.notifications.alerts import query as query_alerts
from src.agent.tools.alerts import get_alerts
from src.agent.tools.camera import get_camera_status, list_cameras
from src.agent.tools.knowledge import KnowledgeCache, invalidate_knowledge_cache
from src.agent.guard import check_prompt_safety, _sample_chunks
from src.agent.nodes import tool_node, get_timed_out_task_count, _timed_out_tool_executions, _timed_out_lock
from src.agent.config import agent_config
from src.events.event_manager import EventManager, VehiclePassage
from src.events.event_dto import VehiclePassageDTO
from src.ocr.plate_tracker import PlateTrackState


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    """Create a temporary SQLite database initialized with Alembic migrations."""
    url = "sqlite:///" + (tmp_path / "audit_regression.db").as_posix()
    monkeypatch.setenv("DATT_DATABASE_URL", url)
    monkeypatch.setenv("DATT_REQUIRE_PERSISTENCE", "0")
    monkeypatch.delenv("DATT_EMAIL_HOST", raising=False)
    command.upgrade(Config("src/db/alembic.ini"), "head")
    db = Database(url)
    yield db
    db.dispose()


# ============================================================================
# Issue 1: Vehicle vs Face Popup Alert Separation
# ============================================================================
def test_vehicle_alert_strictly_separates_plate_from_display_name(audit_db):
    """Ensure get_alerts and query_alerts strictly separate vehicle plate from target_name."""
    cam_id = "cam_test_01"
    vw_id = uuid4()
    ve_id = uuid4()
    pe_id = uuid4()

    with audit_db.transaction() as s:
        vw = VehicleWatchlist(
            id=vw_id,
            plate_number="30A10010",
            display_name="Chủ xe Nguyễn Văn A",
            status="active",
        )
        ve = VehicleEvent(
            id=ve_id,
            vehicle_class="car",
            track_id=1,
            first_seen=utc_now(),
            last_seen=utc_now(),
        )
        s.add(vw)
        s.add(ve)
        s.flush()

        pe = PlateEvent(
            id=pe_id,
            vehicle_event_id=ve.id,
            plate_text="30A10010",
            confidence=0.95,
            status="confirmed",
        )
        s.add(pe)
        s.flush()

        notif = Notification(
            id=uuid4(),
            plate_event_id=pe.id,
            vehicle_watchlist_id=vw.id,
            camera_id=cam_id,
            channel="email",
            recipient="security@example.com",
            status="sent",
            payload={
                "alert_type": "VEHICLE_WATCHLIST_MATCH",
                "event_id": str(pe.id),
                "plate_number": "30A10010",
                "display_name": "Chủ xe Nguyễn Văn A",
                "camera_id": cam_id,
            },
            created_at=utc_now(),
            sent_at=utc_now(),
        )
        s.add(notif)

    with audit_db.transaction() as s:
        alerts_res = query_alerts(s, {"limit": 10})
        alerts = alerts_res["alerts"]
        assert len(alerts) >= 1
        alert = next((a for a in alerts if a.get("plate_number") == "30A10010"), None)
        assert alert is not None
        assert alert["event_type"] == "VEHICLE_WATCHLIST_MATCH"
        assert alert["plate_number"] == "30A10010"
        assert alert.get("vehicle_display_name") == "Chủ xe Nguyễn Văn A"

    # Check agent tool get_alerts
    with patch("src.agent.tools.alerts.agent_config.get_database", return_value=audit_db):
        tool_res = get_alerts.invoke({"plate_number": "30A10010"})
        assert tool_res["status"] == "success"
        t_alert = next((a for a in tool_res["alerts"] if a.get("plate_number") == "30A10010"), None)
        assert t_alert is not None
        assert t_alert["plate_number"] == "30A10010"
        assert t_alert.get("vehicle_display_name") == "Chủ xe Nguyễn Văn A"
        assert t_alert.get("target_name") is None


# ============================================================================
# Issue 2: Agent Query Cameras by Status
# ============================================================================
def test_list_cameras_and_get_camera_status_without_id(audit_db):
    """Ensure get_camera_status and list_cameras can query cameras by status without camera_id."""
    now = utc_now()
    with audit_db.transaction() as s:
        cam_online = Camera(
            id=uuid4(),
            name="Cổng chính",
            source="rtsp://10.0.0.1/live",
            source_type="rtsp",
            location="Cổng 1",
            enabled=True,
            active_until=now + timedelta(seconds=60),  # Lease active -> online
        )
        cam_offline = Camera(
            id=uuid4(),
            name="Bãi xe B",
            source="rtsp://10.0.0.2/live",
            source_type="rtsp",
            location="Bãi đỗ",
            enabled=True,
            active_until=now - timedelta(seconds=120),  # Expired lease -> offline
        )
        cam_disabled = Camera(
            id=uuid4(),
            name="Kho hàng C",
            source="rtsp://10.0.0.3/live",
            source_type="rtsp",
            location="Kho C",
            enabled=False,
            active_until=None,
        )
        s.add_all([cam_online, cam_offline, cam_disabled])

    with patch("src.agent.tools.camera.database") as mock_db_ctx:
        mock_db_ctx.return_value.__enter__.return_value = audit_db

        # 1. Query offline cameras
        res_offline = get_camera_status.invoke({"status": "offline"})
        assert res_offline["status"] == "success"
        assert res_offline["filter"] == "offline"
        assert any(c["name"] == "Bãi xe B" and c["operational_status"] == "offline" for c in res_offline["cameras"])

        # 2. Query online cameras via list_cameras
        res_online = list_cameras.invoke({"status": "online"})
        assert res_online["status"] == "success"
        assert res_online["filter"] == "online"
        assert any(c["name"] == "Cổng chính" and c["operational_status"] == "online" for c in res_online["cameras"])

        # 3. Query all cameras
        res_all = list_cameras.invoke({"status": "all"})
        assert res_all["status"] == "success"
        assert res_all["count"] >= 3


# ============================================================================
# Issue 3: Alert Availability Independent of Notification Email Outbox
# ============================================================================
def test_alert_fallback_projection_without_notification_row(audit_db):
    """Ensure confirmed watchlist events appear in query_alerts even if Notification row was not created."""
    now = utc_now()
    fe_id = uuid4()
    with audit_db.transaction() as s:
        ft = Target(id=uuid4(), name="Trần Thị B", target_type="face", active=True)
        s.add(ft)
        s.flush()

        fe = FaceEvent(
            id=fe_id,
            track_id=10,
            camera_id="cam_01",
            target_id=ft.id,
            similarity=0.88,
            decision="FACE_MATCH",
            created_at=now,
        )
        s.add(fe)

    with audit_db.transaction() as s:
        # Query alerts when no Notification row exists
        alerts_res = query_alerts(s, {"limit": 10})
        alerts = alerts_res["alerts"]
        assert len(alerts) >= 1
        match_alert = next((a for a in alerts if a.get("event_id") == str(fe_id)), None)
        assert match_alert is not None
        assert match_alert["target_name"] == "Trần Thị B"
        assert match_alert["event_type"] == "FACE_WATCHLIST_MATCH"
        assert match_alert["status"] == "PENDING"


# ============================================================================
# Issue 4: RAG Cache TTL and Invalidation
# ============================================================================
def test_knowledge_cache_ttl_and_invalidation():
    """Verify KnowledgeCache adheres to TTL, max capacity eviction, and explicit invalidation."""
    cache = KnowledgeCache(ttl_seconds=0.1, max_size=2)
    key1 = ("query1", 3, None)
    key2 = ("query2", 3, None)
    key3 = ("query3", 3, None)

    # 1. Set key1
    cache.set(key1, {"status": "success", "results": ["doc1"]})
    assert cache.get(key1) == {"status": "success", "results": ["doc1"]}

    # 2. Query within TTL -> hit
    assert cache.get(key1) is not None

    # 3. Wait past TTL -> expired
    time.sleep(0.15)
    assert cache.get(key1) is None

    # 4. Max capacity eviction (max_size=2)
    cache.set(key1, {"status": "success", "results": ["doc1"]})
    cache.set(key2, {"status": "success", "results": ["doc2"]})
    assert cache.size() == 2
    cache.set(key3, {"status": "success", "results": ["doc3"]})
    assert cache.size() == 2
    # key1 was oldest and should be evicted
    assert cache.get(key1) is None
    assert cache.get(key2) is not None
    assert cache.get(key3) is not None

    # 5. Invalidation
    cache.clear()
    assert cache.size() == 0


# ============================================================================
# Issue 5: Prompt Guard Sampling and Fail-Open/Closed Configuration
# ============================================================================
def test_prompt_guard_sampling_and_fail_modes():
    """Verify Prompt Guard scans beginning, middle, and end chunks, and respects fail-open/closed config."""
    # Test multi-chunk sampling helper
    chunks = [f"chunk_{i}" for i in range(10)]
    sampled = _sample_chunks(chunks, max_samples=3)
    assert len(sampled) == 3
    assert sampled[0] == "chunk_0"
    assert sampled[1] in ("chunk_4", "chunk_5")
    assert sampled[2] == "chunk_9"

    # Test fail-open vs fail-closed when guard service fails
    bad_client = MagicMock()
    bad_client.chat.completions.create.side_effect = Exception("API Connection Refused")
    with patch.object(agent_config, "prompt_guard_enabled", True):
        with patch.object(agent_config, "groq_api_key", "mock_key"):
            # Fail-open = True -> allowed
            res_open = check_prompt_safety("hello", client=bad_client, fail_open=True)
            assert res_open["safe"] is True
            assert res_open["status"] == "fail_open"

            # Fail-open = False -> rejected (fail-closed)
            res_closed = check_prompt_safety("hello", client=bad_client, fail_open=False)
            assert res_closed["safe"] is False
            assert res_closed["is_injection"] is True
            assert res_closed["status"] == "fail_closed"


# ============================================================================
# Issue 6: Tool Timeout & Backpressure Load Shedding
# ============================================================================
def test_tool_timeout_and_backpressure():
    """Verify tool timeout produces ToolMessage timeout and backpressure sheds load when saturated."""
    slow_tool = MagicMock()
    slow_tool.name = "get_camera"
    slow_tool.invoke.side_effect = lambda args: time.sleep(0.5)

    with patch("src.agent.nodes.ALL_AGENT_TOOLS", [slow_tool]):
        with patch.object(agent_config, "tool_timeout_sec", 0.05):
            state = {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[{"name": "get_camera", "args": {}, "id": "call_slow_1"}],
                    )
                ],
                "total_tool_calls": 0,
            }
            res = tool_node(state)
            messages = res["messages"]
            assert len(messages) == 1
            assert "timeout" in messages[0].content

        # Test backpressure shedding when pool saturated
        with patch.dict("os.environ", {"DATT_AGENT_TOOL_MAX_WORKERS": "2"}):
            dummy_future = MagicMock()
            with _timed_out_lock:
                _timed_out_tool_executions.add(dummy_future)
                _timed_out_tool_executions.add(MagicMock())
            try:
                state = {
                    "messages": [
                        AIMessage(
                            content="",
                            tool_calls=[{"name": "get_camera", "args": {}, "id": "call_shed_1"}],
                        )
                    ],
                    "total_tool_calls": 0,
                }
                res = tool_node(state)
                assert "tool_executor_busy" in res["messages"][0].content
            finally:
                with _timed_out_lock:
                    _timed_out_tool_executions.clear()


# ============================================================================
# Issue 7: Plate Recognition Latency & Milestone Metrics
# ============================================================================
def test_plate_immediate_confirmation_and_milestones():
    """Verify EventManager immediately enqueues confirmed plates and captures latency timestamps."""
    mock_db_worker = MagicMock()
    em = EventManager(db_worker=mock_db_worker)

    cam_id = "cam_gate_01"
    track_id = 99
    key = (cam_id, track_id)
    passage = VehiclePassage(camera_id=cam_id, track_id=track_id)
    em._active_passages[key] = passage

    state = PlateTrackState(
        track_id=track_id,
        status="CONFIRMED",
        confirmed_plate="29A12345",
        confidence=0.92,
        plate_detected_at=datetime.now(timezone.utc),
        ocr_first_candidate_at=datetime.now(timezone.utc),
        plate_confirmed_at=datetime.now(timezone.utc),
    )
    passage.plate_state = state

    # Trigger plate collection
    em._collect_confirmed_plate(passage)

    # Must be emitted immediately to db_worker without waiting 3 seconds
    assert passage.plate_confirmed_emitted is True
    assert mock_db_worker.enqueue_passage.call_count == 1
    call_args = mock_db_worker.enqueue_passage.call_args[0]
    dto: VehiclePassageDTO = call_args[0]
    assert dto.plate_text == "29A12345"
    assert dto.plate_status == "CONFIRMED"
    assert dto.plate_confirmed_at is not None
    assert dto.is_final is True


def test_confirmed_plate_duplicate_protection():
    """Case E: Immediate plate enqueueing does not generate duplicate events on subsequent frames or finalization."""
    mock_db_worker = MagicMock()
    em = EventManager(db_worker=mock_db_worker)

    cam_id = "cam_gate_02"
    track_id = 101
    key = (cam_id, track_id)
    passage = VehiclePassage(camera_id=cam_id, track_id=track_id)
    em._active_passages[key] = passage

    state = PlateTrackState(
        track_id=track_id,
        status="CONFIRMED",
        confirmed_plate="51H99999",
        confidence=0.98,
        plate_detected_at=datetime.now(timezone.utc),
        ocr_first_candidate_at=datetime.now(timezone.utc),
        plate_confirmed_at=datetime.now(timezone.utc),
    )
    passage.plate_state = state

    # Frame 1: Immediate confirmation
    em._collect_confirmed_plate(passage)
    assert mock_db_worker.enqueue_passage.call_count == 1

    # Frame 2: Same vehicle track continues in frame
    em._collect_confirmed_plate(passage)
    assert mock_db_worker.enqueue_passage.call_count == 1  # No duplicate enqueue

    # Frame N: Vehicle leaves frame and is finalized after timeout
    em._finalize_vehicle(passage)
    assert mock_db_worker.enqueue_passage.call_count == 1  # Still exactly 1 enqueue


def test_latency_milestones_chronological_ordering(audit_db):
    """Case F: Latency milestones are strictly chronological: detected <= first OCR <= confirmed <= persisted <= alert available."""
    cam_id = "cam_milestone_01"
    vw_id = uuid4()
    ve_id = uuid4()
    pe_id = uuid4()

    t_base = utc_now() - timedelta(seconds=2)
    t_detect = t_base
    t_ocr1 = t_base + timedelta(milliseconds=120)
    t_confirm = t_base + timedelta(milliseconds=250)
    t_persist = t_base + timedelta(milliseconds=400)
    t_alert = t_base + timedelta(milliseconds=450)

    with audit_db.transaction() as s:
        vw = VehicleWatchlist(
            id=vw_id,
            plate_number="51A55555",
            display_name="Xe VIP",
            status="active",
        )
        ve = VehicleEvent(
            id=ve_id,
            vehicle_class="car",
            track_id=77,
            first_seen=t_detect,
            last_seen=t_confirm,
        )
        s.add(vw)
        s.add(ve)
        s.flush()

        pe = PlateEvent(
            id=pe_id,
            vehicle_event_id=ve.id,
            plate_text="51A55555",
            confidence=0.96,
            status="confirmed",
            created_at=t_confirm,
        )
        s.add(pe)
        s.flush()

        notif = Notification(
            id=uuid4(),
            plate_event_id=pe.id,
            vehicle_watchlist_id=vw.id,
            camera_id=cam_id,
            channel="email",
            recipient="security@example.com",
            status="pending",
            created_at=t_persist,
            next_attempt_at=t_persist,
            payload={
                "plate_detected_at": t_detect.isoformat(),
                "ocr_first_candidate_at": t_ocr1.isoformat(),
                "plate_confirmed_at": t_confirm.isoformat(),
                "event_persisted_at": t_persist.isoformat(),
                "alert_available_at": t_alert.isoformat(),
            },
        )
        s.add(notif)
        s.flush()

        res = query_alerts(s, {"camera_id": cam_id})
        assert len(res["alerts"]) == 1
        a = res["alerts"][0]

        d_dt = datetime.fromisoformat(a["plate_detected_at"])
        o_dt = datetime.fromisoformat(a["ocr_first_candidate_at"])
        c_dt = datetime.fromisoformat(a["plate_confirmed_at"])
        p_dt = datetime.fromisoformat(a["event_persisted_at"])
        av_dt = datetime.fromisoformat(a["alert_available_at"])

        assert d_dt <= o_dt
        assert o_dt <= c_dt
        assert c_dt <= p_dt
        assert p_dt <= av_dt
