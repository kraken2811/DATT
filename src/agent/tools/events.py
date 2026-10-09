"""Event search and inspection tools for DATT AI Agent."""

from typing import Any
from uuid import UUID
from langchain_core.tools import tool
from sqlalchemy import or_, select
import yaml

from src.agent.config import agent_config
from src.config.camera_config import DEFAULT_CONFIG_PATH
from src.db.models import Camera
from src.event_center.service import query as query_events


def _camera_details(session, events):
    """Add current camera configuration without changing recorded event facts."""
    identifiers = {str(e["camera_id"]) for e in events if e.get("camera_id")}
    uuids = []
    for ident in identifiers:
        try:
            uuids.append(UUID(ident))
        except ValueError:
            pass
    cameras = session.scalars(select(Camera).where(or_(Camera.id.in_(uuids), Camera.registry_key.in_(identifiers)))).all() if identifiers else []
    lookup = {}
    for camera in cameras:
        for key in (str(camera.id), camera.id.hex, camera.registry_key):
            if key:
                lookup[key] = camera
    # Static registry entries can predate database-managed cameras. Read only
    # display metadata; never expose stream URLs or infer location from a name.
    configured = {}
    if identifiers - lookup.keys():
        try:
            data = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("cameras"), dict):
                configured = data["cameras"]
        except (OSError, yaml.YAMLError):
            pass
    for event in events:
        ident = str(event.get("camera_id"))
        camera = lookup.get(ident)
        if camera is None:
            try:
                camera = lookup.get(str(UUID(ident)))
            except ValueError:
                pass
        static = configured.get(ident)
        static = static if isinstance(static, dict) else {}
        event["camera_name"] = camera.name if camera else static.get("name")
        event["camera_location"] = camera.location if camera else static.get("location")
        event["camera_metadata_basis"] = "current_camera_configuration" if camera or static else "unavailable"
    return events


@tool
def get_event(event_id: str) -> dict[str, Any]:
    """Retrieve detailed information about a single event by its ID.

    Args:
        event_id: Unified event identifier (e.g. 'plate:<uuid>', 'face:<uuid>', 'passage:<uuid>', 'business:<uuid>').

    Returns:
        Structured event details including timestamp, camera, classification, confidence, and evidence key.
    """
    clean_id = (event_id or "").strip()
    if not clean_id:
        return {"status": "error", "message": "event_id is required"}

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            # If plain UUID was passed without prefix, try common kinds
            if ":" not in clean_id:
                for prefix in ("plate", "face", "passage", "business", "vehicle"):
                    try:
                        res = query_events(session, {}, ident=f"{prefix}:{clean_id}")
                        if res:
                            return {"status": "success", "event": _camera_details(session, [res])[0]}
                    except Exception:
                        continue
                return {"status": "not_found", "message": f"Event '{clean_id}' not found"}

            res = query_events(session, {}, ident=clean_id)
            return {"status": "success", "event": _camera_details(session, [res])[0]}
    except LookupError:
        return {"status": "not_found", "message": f"Event '{clean_id}' not found"}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to retrieve event: {exc}"}
    finally:
        db.dispose()


@tool
def search_events(
    camera_id: str | None = None,
    target_id: str | None = None,
    person_id: str | None = None,
    event_type: str | None = None,
    plate: str | None = None,
    plate_number: str | None = None,
    watchlist_match: bool | None = None,
    from_time: str | None = None,
    to_time: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Query computer vision events (faces, license plates, vehicles, passages, business events).

    Args:
        camera_id: Optional camera identifier or UUID to filter by.
        target_id: Optional person watchlist target UUID.
        person_id: Optional alias for target_id.
        event_type: Optional filter: 'face', 'plate', 'vehicle', 'passage', or 'business'.
        plate: Optional license plate number (exact or partial).
        plate_number: Optional alias for plate.
        watchlist_match: Optional boolean filter for watchlist matches only.
        from_time: Optional ISO timestamp start of interval (e.g. '2026-10-01T00:00:00Z').
        to_time: Optional ISO timestamp end of interval.
        start_time: Optional alias for from_time.
        end_time: Optional alias for to_time.
        limit: Maximum number of events to return (1-100, default: 20).

    Returns:
        Structured list of matching events, total count, and pagination info.
    """
    bounded_limit = max(1, min(100, limit))
    params: dict[str, Any] = {"page": 1, "limit": bounded_limit}

    eff_camera = camera_id
    eff_target = target_id or person_id
    eff_plate = plate or plate_number
    eff_from = from_time or start_time
    eff_to = to_time or end_time

    if eff_camera:
        params["camera_id"] = eff_camera.strip()
    if eff_target:
        params["target_id"] = eff_target.strip()
    if event_type:
        params["event_type"] = event_type.strip().lower()
    if eff_plate:
        params["plate"] = eff_plate.strip()
    if watchlist_match is not None:
        params["watchlist_match"] = "true" if watchlist_match else "false"
    if eff_from:
        params["from"] = eff_from.strip()
    if eff_to:
        params["to"] = eff_to.strip()

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            result = query_events(session, params)
            events = _camera_details(session, result.get("events", []))
            return {
                "status": "success",
                "total": result.get("total", len(result.get("events", []))),
                "count": len(events),
                "events": events,
            }
    except Exception as exc:
        return {"status": "error", "message": f"Event search failed: {exc}"}
    finally:
        db.dispose()
