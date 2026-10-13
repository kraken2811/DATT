"""LangGraph Investigation tools for DATT AI Assistant."""

from typing import Any
from langchain_core.tools import tool

from src.agent.config import agent_config
from src.agent.investigation.entity_investigation import (
    investigate_vehicle_entity,
    investigate_face_entity,
)


@tool
def investigate_vehicle(
    plate_number: str,
    from_time: str | None = None,
    to_time: str | None = None,
    camera_ids: list[str] | None = None,
    include_watchlist: bool = True,
    include_alerts: bool = True,
    include_notifications: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Perform a comprehensive operational investigation on a vehicle / license plate.

    Chronologically reconstructs camera observations, inspects OCR confidence,
    resolves camera locations, checks Watchlist registration, retrieves related
    security alerts, and checks notification dispatch status in a single unified operation.

    Args:
        plate_number: License plate string (e.g. '30A-12345', '29B-9999').
        from_time: Optional start time filter (ISO timestamp or preset: 'today', 'yesterday', '24h', '7_days').
        to_time: Optional end time filter (ISO timestamp).
        camera_ids: Optional list of camera identifiers to filter the investigation.
        include_watchlist: Whether to check vehicle watchlist status (default: True).
        include_alerts: Whether to inspect related security alerts (default: True).
        include_notifications: Whether to check email delivery outbox logs (default: True).
        limit: Maximum number of raw observations to evaluate (default: 50).

    Returns:
        Structured investigation result containing chronological timeline, observation summary,
        watchlist record, alerts, notification status, provenance notes, and evidence record IDs.
    """
    db = agent_config.get_database()
    try:
        return investigate_vehicle_entity(
            db=db,
            plate_number=plate_number,
            from_time=from_time,
            to_time=to_time,
            camera_ids=camera_ids,
            include_watchlist=include_watchlist,
            include_alerts=include_alerts,
            include_notifications=include_notifications,
            limit=limit,
        )
    finally:
        db.dispose()


@tool
def investigate_face(
    target_id: str | None = None,
    name: str | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    camera_ids: list[str] | None = None,
    include_watchlist: bool = True,
    include_alerts: bool = True,
    include_notifications: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    """Perform a comprehensive operational investigation on a face target or watchlist person.

    Resolves target identity (with disambiguation if multiple names match),
    reconstructs chronological camera observations with face similarity scores,
    resolves camera names and locations, checks Watchlist status,
    retrieves security alerts, and inspects notification outbox status.

    Args:
        target_id: Optional target UUID (must be valid UUID, not a person name).
        name: Optional person name to search and resolve against the watchlist.
        from_time: Optional start time filter (ISO timestamp or preset: 'today', 'yesterday', '24h', '7_days').
        to_time: Optional end time filter (ISO timestamp).
        camera_ids: Optional list of camera identifiers to scope the investigation.
        include_watchlist: Whether to inspect target watchlist status (default: True).
        include_alerts: Whether to inspect related security alerts (default: True).
        include_notifications: Whether to check email delivery outbox logs (default: True).
        limit: Maximum observations to retrieve (default: 50).

    Returns:
        Structured result with candidate targets (if disambiguation needed), chronological timeline,
        similarity metrics, alerts, notifications, and evidence record IDs.
    """
    db = agent_config.get_database()
    try:
        return investigate_face_entity(
            db=db,
            target_id=target_id,
            name=name,
            from_time=from_time,
            to_time=to_time,
            camera_ids=camera_ids,
            include_watchlist=include_watchlist,
            include_alerts=include_alerts,
            include_notifications=include_notifications,
            limit=limit,
        )
    finally:
        db.dispose()
