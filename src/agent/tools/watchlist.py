"""Watchlist search and inspection tools for DATT AI Agent."""

from typing import Any
from uuid import UUID
from langchain_core.tools import tool
from sqlalchemy import select

from src.agent.config import agent_config
from src.db.database import Database
from src.db.models import Target, VehicleWatchlist
from src.watchlists.vehicles import normalize_plate, serialize_item


@tool
def search_watchlist(
    target_id: str | None = None,
    target: str | None = None,
    plate_number: str | None = None,
    plate: str | None = None,
    query: str | None = None,
    watchlist_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search registered watchlists for monitored persons of interest (face) and vehicles (license plate).

    Args:
        target_id: Optional person target UUID or name substring.
        target: Optional alias for target_id or plate.
        plate_number: Optional license plate number (exact or partial) to look up.
        plate: Optional alias for plate_number.
        query: Optional search keyword or identifier.
        watchlist_type: Optional filter: 'vehicle' (for license plates) or 'face' / 'person' (for facial recognition).
        status: Optional filter: 'active' or 'disabled'.
        limit: Maximum results to return (1-50, default: 20).

    Returns:
        Structured matches for vehicle and/or person watchlists.
    """
    effective_plate = plate_number or plate
    effective_target = target_id or target
    if query:
        if any(c.isdigit() for c in query):
            effective_plate = effective_plate or query
        effective_target = effective_target or query

    w_type = (watchlist_type or "").strip().lower()
    bounded_limit = max(1, min(50, limit))
    results: dict[str, Any] = {
        "status": "success",
        "vehicle_watchlist": [],
        "face_watchlist": [],
    }

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            # 1. Search vehicle watchlist if relevant
            if w_type in ("vehicle", "plate", "") or effective_plate:
                stmt = select(VehicleWatchlist)
                if effective_plate:
                    clean_norm = normalize_plate(effective_plate)
                    stmt = stmt.where(VehicleWatchlist.plate_number.ilike(f"%{clean_norm}%"))
                if status:
                    stmt = stmt.where(VehicleWatchlist.status == status.lower())
                stmt = stmt.order_by(VehicleWatchlist.created_at.desc()).limit(bounded_limit)
                v_rows = session.scalars(stmt).all()
                results["vehicle_watchlist"] = [serialize_item(v) for v in v_rows]

            # 2. Search face target watchlist if relevant
            if w_type in ("face", "person", "") or target_id:
                stmt_f = select(Target)
                if target_id:
                    clean_target = target_id.strip()
                    try:
                        u_id = UUID(clean_target)
                        stmt_f = stmt_f.where(Target.id == u_id)
                    except ValueError:
                        stmt_f = stmt_f.where(Target.name.ilike(f"%{clean_target}%"))
                if status:
                    stmt_f = stmt_f.where(Target.active == (status.lower() == "active"))
                stmt_f = stmt_f.order_by(Target.created_at.desc()).limit(bounded_limit)
                f_rows = session.scalars(stmt_f).all()
                results["face_watchlist"] = [
                    {
                        "id": str(t.id),
                        "name": t.name,
                        "target_type": t.target_type,
                        "active": t.active,
                        "created_at": t.created_at.isoformat() if t.created_at else None,
                        "has_embedding": t.embedding is not None,
                        "image_path": t.image_path,
                    }
                    for t in f_rows
                ]

        total_found = len(results["vehicle_watchlist"]) + len(results["face_watchlist"])
        results["total_matches"] = total_found
        return results
    except Exception as exc:
        return {"status": "error", "message": f"Watchlist search failed: {exc}"}
    finally:
        db.dispose()
