"""Operational and RAG tools registered for DATT LangGraph AI Agent."""

from .camera import get_camera, get_camera_status
from .events import get_event, search_events
from .watchlist import search_watchlist
from .analytics import get_event_statistics
from .knowledge import get_knowledge

ALL_AGENT_TOOLS = [
    get_camera,
    get_camera_status,
    get_event,
    search_events,
    search_watchlist,
    get_event_statistics,
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
    "get_knowledge",
]
