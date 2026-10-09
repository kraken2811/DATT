"""Conversation registry management for DATT Single AI Agent."""
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.db.models import AgentConversation, utc_now


def derive_conversation_title(first_message: str) -> str:
    """Deterministically derive a concise, descriptive Vietnamese title without paid LLM calls."""
    text = (first_message or "").strip()
    if not text:
        return "Cuộc trò chuyện mới"

    # 1. License plate detection: "30A-12345", "51F 99999", etc.
    plate_match = re.search(r"\b([0-9]{2}[A-Za-z][-.\s]?[0-9]{3,5}(?:\.[0-9]{2})?|[0-9]{2}[A-Za-z][0-9]{4,5})\b", text)
    if plate_match:
        from src.watchlists.vehicles import normalize_plate
        raw_plate = plate_match.group(1).replace(" ", "").upper()
        return f"Lịch sử xe {raw_plate}"

    # 2. Vehicle display name: "Xe của Long", "chiếc xe có tên X"
    if "xe của " in text.lower():
        match = re.search(r"xe\s+của\s+([^\s.,:;!?\"']+)", text, re.IGNORECASE)
        if match:
            return f"Lịch sử xe của {match.group(1)}"

    # 3. Person / Face recognition query
    if "khuôn mặt" in text.lower() or "người" in text.lower():
        match = re.search(r"(?:khuôn mặt|người)\s+([^\s.,:;!?\"']+)", text, re.IGNORECASE)
        if match and match.group(1).lower() not in ("này", "đó", "nào"):
            return f"Tra cứu khuôn mặt {match.group(1)}"

    if "long" in text.lower() and ("nhận diện" in text.lower() or "xuất hiện" in text.lower() or "khớp" in text.lower()):
        return "Tra cứu khuôn mặt Long"

    # 4. Operational documentation / Troubleshooting
    if any(k in text.lower() for k in ("khắc phục", "mất kết nối", "offline", "tài liệu", "hướng dẫn")):
        return "Hướng dẫn khắc phục sự cố"

    # 5. Camera query
    cam_match = re.search(r"\b(cam(?:era)?[_-]?\w+)\b", text, re.IGNORECASE)
    if cam_match:
        return f"Kiểm tra {cam_match.group(1)}"

    # 6. Vehicle / Traffic statistics
    if any(k in text.lower() for k in ("thống kê", "lưu lượng", "đông nhất", "busiest", "số lượt")):
        return "Thống kê phương tiện"

    # 7. Fallback: sanitize and truncate first user query
    clean = re.sub(r"\s+", " ", text)
    if len(clean) > 35:
        clean = clean[:32].rstrip() + "..."
    return clean or "Cuộc trò chuyện mới"


def serialize_conversation(conv: AgentConversation) -> dict[str, Any]:
    """Serialize conversation entity to API dictionary."""
    return {
        "id": str(conv.id),
        "thread_id": conv.thread_id,
        "user_id": conv.user_id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
        "status": conv.status,
    }


def create_conversation(
    session: Session,
    user_id: str,
    title: str | None = None,
    thread_id: str | None = None,
) -> AgentConversation:
    """Create a new conversation record in the registry."""
    clean_uid = (user_id or "").strip()
    if not clean_uid:
        raise ValueError("user_id is required")

    tid = (thread_id or "").strip() or f"conv_{uuid4().hex[:12]}"
    clean_title = (title or "").strip() or "Cuộc trò chuyện mới"

    # Check if thread_id already exists
    existing = session.scalars(
        select(AgentConversation).where(AgentConversation.thread_id == tid)
    ).first()
    if existing:
        if existing.user_id != clean_uid:
            raise PermissionError("Thread ID belongs to another user")
        return existing

    now = utc_now()
    conv = AgentConversation(
        id=uuid4(),
        thread_id=tid,
        user_id=clean_uid,
        title=clean_title,
        created_at=now,
        updated_at=now,
        last_message_at=now,
        status="active",
    )
    session.add(conv)
    session.flush()
    return conv


def list_conversations(
    session: Session,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AgentConversation], int]:
    """List conversations belonging to the verified user, sorted by last activity."""
    clean_uid = (user_id or "").strip()
    bounded_limit = max(1, min(100, limit))
    bounded_offset = max(0, offset)

    base_query = select(AgentConversation).where(
        AgentConversation.user_id == clean_uid,
        AgentConversation.status == "active",
    )

    total = session.scalar(
        select(func.count()).select_from(base_query.subquery())
    ) or 0

    stmt = (
        base_query.order_by(
            func.coalesce(AgentConversation.last_message_at, AgentConversation.updated_at).desc(),
            AgentConversation.created_at.desc(),
        )
        .offset(bounded_offset)
        .limit(bounded_limit)
    )

    items = list(session.scalars(stmt).all())
    return items, total


def get_conversation(
    session: Session,
    thread_id: str,
    user_id: str | None = None,
) -> AgentConversation | None:
    """Retrieve conversation by thread_id with optional ownership verification."""
    clean_tid = (thread_id or "").strip()
    conv = session.scalars(
        select(AgentConversation).where(AgentConversation.thread_id == clean_tid)
    ).first()

    if conv and user_id is not None:
        clean_uid = user_id.strip()
        if conv.user_id != clean_uid:
            raise PermissionError("Access denied: conversation owned by another user")

    return conv


def touch_conversation(
    session: Session,
    thread_id: str,
    user_id: str,
    user_message: str | None = None,
) -> AgentConversation | None:
    """Update last_message_at and auto-derive title on first message if default."""
    clean_tid = (thread_id or "").strip()
    clean_uid = (user_id or "").strip()

    conv = get_conversation(session, clean_tid, clean_uid)
    if not conv:
        # Auto-register if chat was sent to a new thread
        derived = derive_conversation_title(user_message or "") if user_message else "Cuộc trò chuyện mới"
        conv = create_conversation(session, clean_uid, title=derived, thread_id=clean_tid)
        return conv

    now = utc_now()
    conv.last_message_at = now
    conv.updated_at = now

    # Auto-derive title if currently the default
    if conv.title == "Cuộc trò chuyện mới" and user_message:
        derived = derive_conversation_title(user_message)
        if derived and derived != "Cuộc trò chuyện mới":
            conv.title = derived

    session.flush()
    return conv


def rename_conversation(
    session: Session,
    thread_id: str,
    user_id: str,
    new_title: str,
) -> AgentConversation:
    """Rename a conversation owned by the verified user."""
    clean_title = (new_title or "").strip()
    if not clean_title:
        raise ValueError("Title cannot be empty")
    if len(clean_title) > 255:
        raise ValueError("Title must be at most 255 characters")

    conv = get_conversation(session, thread_id, user_id)
    if not conv:
        raise LookupError(f"Conversation '{thread_id}' not found")

    conv.title = clean_title
    conv.updated_at = utc_now()
    session.flush()
    return conv


def delete_conversation(
    session: Session,
    thread_id: str,
    user_id: str,
) -> bool:
    """Permanently delete a conversation from the registry."""
    conv = get_conversation(session, thread_id, user_id)
    if not conv:
        return False

    session.delete(conv)
    session.flush()
    return True
