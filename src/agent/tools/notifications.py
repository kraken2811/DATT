"""Notification delivery status inspection tools for DATT AI Agent."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langchain_core.tools import tool
from sqlalchemy import func, or_, select

from src.agent.config import agent_config
from src.agent.tools.notification_queries import filtered_notifications, status_totals
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
    event_type: str | None = None,
    target_id: str | None = None,
    search: str | None = None,
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

    db = None
    try:
        db = agent_config.get_database()
        with db.transaction() as session:
            q = filtered_notifications(session, camera_id=camera_id, status=status, event_type=event_type,
                event_id=event_id, target_id=target_id, target_name=target_name, plate_number=plate_number,
                search=search, start_time=eff_start, end_time=eff_end)
            filtered = q.subquery()

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

            status_summary = status_totals(session, filtered)

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
        return {"status": "error", "message": "Không thể truy xuất thông báo hoặc bộ lọc không hợp lệ; chưa xác minh được số lượng."}
    finally:
        if db is not None:
            db.dispose()
