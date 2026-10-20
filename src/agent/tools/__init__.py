"""Operational, Analytics, Alert, Investigation, and RAG tools registered for DATT LangGraph AI Agent."""

from .alerts import get_alerts
from .analytics import (
    get_event_statistics,
    get_traffic_analytics,
    get_historical_analytics,
    get_peak_traffic_hours,
    get_tomorrow_forecast,
    get_predictive_alerts,
)
from .anomalies import detect_traffic_anomalies
from .camera import get_camera, get_camera_status, list_cameras
from .events import get_event, search_events
from .investigation import investigate_vehicle, investigate_face
from .knowledge import get_knowledge
from .notifications import get_notifications_status
from .reports import generate_operational_report
from .shift_reports import generate_shift_handover_report
from .watchlist import search_watchlist

ALL_AGENT_TOOLS = [
    get_camera,
    get_camera_status,
    list_cameras,
    get_event,
    search_events,
    search_watchlist,
    get_event_statistics,
    get_traffic_analytics,
    get_historical_analytics,
    get_peak_traffic_hours,
    get_tomorrow_forecast,
    get_predictive_alerts,
    get_alerts,
    get_notifications_status,
    generate_operational_report,
    get_knowledge,
    # Phase 1, 2, 3 investigation tools:
    investigate_vehicle,
    investigate_face,
    detect_traffic_anomalies,
    generate_shift_handover_report,
]

__all__ = [
    "ALL_AGENT_TOOLS",
    "get_camera",
    "get_camera_status",
    "list_cameras",
    "get_event",
    "search_events",
    "search_watchlist",
    "get_event_statistics",
    "get_traffic_analytics",
    "get_historical_analytics",
    "get_peak_traffic_hours",
    "get_tomorrow_forecast",
    "get_predictive_alerts",
    "get_alerts",
    "get_notifications_status",
    "generate_operational_report",
    "get_knowledge",
    "investigate_vehicle",
    "investigate_face",
    "detect_traffic_anomalies",
    "generate_shift_handover_report",
]
