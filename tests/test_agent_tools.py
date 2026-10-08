"""Unit tests for DATT Agent operational tools and RAG tool."""

import pytest

from src.agent.tools.camera import get_camera, get_camera_status
from src.agent.tools.events import get_event, search_events
from src.agent.tools.watchlist import search_watchlist
from src.agent.tools.analytics import get_event_statistics
from src.agent.tools.knowledge import get_knowledge


def test_get_camera_and_status():
    # 1. Non-existent camera
    res_not_found = get_camera.invoke({"camera_id": "non_existent_cam_999"})
    assert res_not_found["status"] == "not_found"

    # 2. Existing camera in YAML (camera_01 or similar)
    res_status = get_camera_status.invoke({"camera_id": "camera_01"})
    assert res_status["status"] in ("success", "not_found")
    if res_status["status"] == "success":
        assert "operational_status" in res_status
        assert res_status["operational_status"] in ("online", "offline", "disabled")


def test_get_event_and_search_events():
    # 1. Non-existent event
    res_single = get_event.invoke({"event_id": "plate:00000000-0000-0000-0000-000000000000"})
    assert res_single["status"] == "not_found"

    # 2. Search events query
    res_search = search_events.invoke({"limit": 5})
    assert res_search["status"] == "success"
    assert "events" in res_search
    assert isinstance(res_search["events"], list)


def test_search_watchlist():
    # Search vehicle and face watchlists
    res = search_watchlist.invoke({"plate_number": "30A", "limit": 5})
    assert res["status"] == "success"
    assert "vehicle_watchlist" in res
    assert "face_watchlist" in res
    assert isinstance(res["vehicle_watchlist"], list)


def test_get_event_statistics():
    res = get_event_statistics.invoke({"group_by": "type"})
    assert res["status"] == "success"
    assert "total_vehicle_passages" in res
    assert "vehicle_type_breakdown" in res
    assert "security_matches" in res


def test_get_knowledge_seeded():
    # Query knowledge base for camera troubleshooting (seeded from docs/)
    res = get_knowledge.invoke({"query": "camera offline troubleshooting", "top_k": 3})
    assert res["status"] in ("success", "insufficient_context")
    if res["status"] == "success":
        assert len(res["results"]) > 0
        assert "content" in res["results"][0]
        assert "document_name" in res["results"][0]
        assert "score" in res["results"][0]
