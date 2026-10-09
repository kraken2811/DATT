"""Notification delivery status inspection tools for DATT AI Agent."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from sqlalchemy import func, or_, select

from src.agent.config import agent_config
from src.agent.tools.analytics import parse_iso_time
from src.db.models import Camera, FaceEvent, Notification, PlateEvent, Target, VehicleWatchlist
from src.notifications.alerts import camera_aliases
from src.notifications.errors import safe_error


def mask_recipient(recipient: str | None) -> str:
    """Mask email recipient to protect sensitive addresses from prompt disclosure."""
    if not recipient:
        return "chưa có người nhận"
    if "@" not in recipient:
        return recipient[:3] + "***" if len(recipient) > 3 else "***"
    local, domain = recipient.split("@", 1)
    masked_local = (local[:2] + "***") if len(local) > 2 else (local[0] + "***" if local else "***")
    return f"{masked_local}@{domain}"


@tool
def get_notifications_status(
    event_id: str | None = None,
    plate_number: str | None = None,
    target_name: str | None = None,
    camera_id: str | None = None,
    status: str | None = None,
    start_time: str | None = None,
    from_time: str | None = None,
    end_time: str | None = None,
    to_time: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Inspect email notification delivery logs and retry statuses.

    Distinguishes:
    1. Delivery statuses: 'sent', 'failed', 'pending', 'suppressed' (cooldown).
    2. Retry counts and failure error reasons (from transactional outbox).
    3. Notice: 'sent' indicates outbox dispatched to SMTP relay; not proof recipient opened/read the email.

    Args:
        event_id: Optional event UUID (FaceEvent or PlateEvent ID).
        plate_number: Optional license plate number to check alerts for.
        target_name: Optional person target name or vehicle display name.
        camera_id: Optional camera identifier.
        status: Optional status filter: 'pending', 'sent', 'failed', 'suppressed', or 'all'.
        start_time: Optional start ISO timestamp / date.
        from_time: Optional alias for start_time.
        end_time: Optional end ISO timestamp / date.
        to_time: Optional alias for end_time.
        limit: Maximum number of notification records (1-100, default 20).

    Returns:
        Structured delivery status records, retry details, and status summary.
    """
    bounded_limit = max(1, min(100, limit))
    eff_start = start_time or from_time
    eff_end = end_time or to_time

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            q = (
                select(Notification, FaceEvent, PlateEvent, Target, VehicleWatchlist)
                .outerjoin(FaceEvent, Notification.event_id == FaceEvent.id)
                .outerjoin(PlateEvent, Notification.plate_event_id == PlateEvent.id)
                .outerjoin(Target, FaceEvent.target_id == Target.id)
                .outerjoin(VehicleWatchlist, Notification.vehicle_watchlist_id == VehicleWatchlist.id)
            )

            # Event ID filter
            if event_id and event_id.strip():
                clean_eid = event_id.strip()
                if ":" in clean_eid:
                    clean_eid = clean_eid.split(":")[-1]
                try:
                    uuid_eid = UUID(clean_eid)
                    q = q.where(or_(Notification.event_id == uuid_eid, Notification.plate_event_id == uuid_eid))
                except ValueError:
                    pass

            # Status filter
            if status and status.lower() != "all":
                st_clean = status.lower().strip()
                if st_clean in ("pending", "sent", "failed", "suppressed"):
                    q = q.where(Notification.status == st_clean)

            # Camera filter
            if camera_id and camera_id != "all":
                q = q.where(Notification.camera_id.in_(camera_aliases(camera_id.strip())))

            # Plate filter
            if plate_number and plate_number.strip():
                p_clean = f"%{plate_number.strip()}%"
                q = q.where(or_(PlateEvent.plate_text.ilike(p_clean), PlateEvent.normalized_plate.ilike(p_clean)))

            # Target filter
            if target_name and target_name.strip():
                t_clean = f"%{target_name.strip()}%"
                q = q.where(or_(Target.name.ilike(t_clean), VehicleWatchlist.display_name.ilike(t_clean)))

            # Time filters
            if eff_start:
                try:
                    start_dt = parse_iso_time(eff_start, datetime.min.replace(tzinfo=timezone.utc))
                    q = q.where(Notification.created_at >= start_dt)
                except Exception:
                    pass
            if eff_end:
                try:
                    end_dt = parse_iso_time(eff_end, datetime.max.replace(tzinfo=timezone.utc))
                    q = q.where(Notification.created_at <= end_dt)
                except Exception:
                    pass

            total = session.scalar(select(func.count()).select_from(q.subquery())) or 0
            rows = session.execute(q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(bounded_limit)).all()

            items = []
            for item, face, plate, target, vehicle in rows:
                is_face = item.event_id is not None
                linked_kind = "face" if is_face else "plate"
                linked_id = str(item.event_id if is_face else item.plate_event_id)
                target_str = target.name if target else (vehicle.display_name if vehicle else None)
                plate_str = (plate.normalized_plate or plate.plate_text) if plate else None

                items.append({
                    "id": str(item.id),
                    "channel": item.channel,
                    "status": item.status,
                    "linked_kind": linked_kind,
                    "linked_event_id": linked_id,
                    "target_name": target_str,
                    "plate_number": plate_str,
                    "camera_id": item.camera_id,
                    "recipient_masked": mask_recipient(item.recipient),
                    "retry_count": item.retry_count,
                    "error_reason": safe_error(item.error) if item.error else None,
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                    "sent_at": item.sent_at.isoformat() if item.sent_at else None,
                    "next_attempt_at": item.next_attempt_at.isoformat() if item.next_attempt_at else None,
                })

            # Calculate status totals
            summary_stmt = select(Notification.status, func.count(Notification.id)).group_by(Notification.status)
            status_summary = {str(r[0]): int(r[1]) for r in session.execute(summary_stmt).all()}

            return {
                "status": "success",
                "total_notifications": total,
                "count": len(items),
                "status_summary": {
                    "sent": status_summary.get("sent", 0),
                    "failed": status_summary.get("failed", 0),
                    "pending": status_summary.get("pending", 0),
                    "suppressed": status_summary.get("suppressed", 0),
                },
                "notifications": items,
                "delivery_disclaimer": (
                    "Trạng thái 'sent' thể hiện email đã được gửi thành công đến máy chủ chuyển tiếp SMTP / dịch vụ email outbox; "
                    "hệ thống không theo dõi và không khẳng định người nhận đã mở hoặc đọc email."
                ),
            }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to retrieve notifications: {exc}"}
    finally:
        db.dispose()
