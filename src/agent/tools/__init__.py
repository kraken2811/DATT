"""Operational, Analytics, Alert, and RAG tools registered for DATT LangGraph AI Agent."""

from .alerts import get_alerts
from .analytics import get_event_statistics, get_traffic_analytics
from .camera import get_camera, get_camera_status
from .events import get_event, search_events
from .knowledge import get_knowledge
from .notifications import get_notifications_status
from .reports import generate_operational_report
from .watchlist import search_watchlist

ALL_AGENT_TOOLS = [
    get_camera,
    get_camera_status,
    get_event,
    search_events,
    search_watchlist,
    get_event_statistics,
    get_traffic_analytics,
    get_alerts,
    get_notifications_status,
    generate_operational_report,
    get_knowledge,
]

__all__ = [
    "ALL_AGENT_TOOLS",
    "get_camera",
    "get_camera_status",
    "get_event",
    "search_events",
    "search_watchlist",
    "get_event_statistics",
    "get_traffic_analytics",
    "get_alerts",
    "get_notifications_status",
    "generate_operational_report",
    "get_knowledge",
]
