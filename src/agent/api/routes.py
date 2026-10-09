"""API routes for DATT LangGraph Single AI Agent and persistent conversation management."""
import asyncio
import logging
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.agent.api.auth import resolve_authenticated_user
from src.agent.config import agent_config
from src.agent.conversations import (
    create_conversation,
    delete_conversation as delete_conversation_record,
    get_conversation as get_conversation_record,
    list_conversations,
    rename_conversation,
    serialize_conversation,
    touch_conversation,
)
from src.agent.graph import run_agent_message
from src.agent.memory.checkpoint import clear_thread_checkpoint, get_checkpointer, make_thread_config

logger = logging.getLogger("datt.agent.api")

router = APIRouter(prefix="/api/agent", tags=["Agent"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User prompt or query")
    thread_id: str | None = Field(default=None, description="Conversation session identifier")
    user_id: str | None = Field(default=None, description="Optional client user ID claim")
    session_id: str | None = Field(default=None, description="Optional client session identifier")


class ChatResponse(BaseModel):
    status: str
    thread_id: str
    reply: str
    tools_called: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255, description="Initial conversation title")
    thread_id: str | None = Field(default=None, max_length=128, description="Optional pre-allocated thread ID")
    user_id: str | None = Field(default=None, description="Optional client user ID claim")
    session_id: str | None = Field(default=None, description="Optional client session identifier")


class RenameConversationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="New conversation title")
    user_id: str | None = Field(default=None, description="Optional client user ID claim")
    session_id: str | None = Field(default=None, description="Optional client session identifier")


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest, request: Request) -> ChatResponse:
    """Send a message to the DATT AI Agent with persistent conversation continuity."""
    verified_user, is_authenticated = resolve_authenticated_user(
        request,
        client_claimed_user=payload.user_id,
        client_claimed_session=payload.session_id,
    )

    thread_id = (payload.thread_id or "").strip() or f"thread_{uuid.uuid4().hex[:12]}"
    db = agent_config.get_database()

    # Verify conversation ownership and update/register registry
    try:
        with db.transaction() as session:
            existing = get_conversation_record(session, thread_id)
            if existing and existing.user_id != verified_user:
                raise HTTPException(
                    status_code=403,
                    detail="Forbidden: Cannot send messages to another user's conversation thread.",
                )
            if not existing:
                create_conversation(session, verified_user, thread_id=thread_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Conversation registry check failed (%s); proceeding with chat", exc)

    # Offload blocking LangGraph execution to worker thread
    result = await asyncio.to_thread(
        run_agent_message,
        content=payload.message,
        thread_id=thread_id,
        user_id=verified_user,
        is_authenticated=is_authenticated,
    )

    # Update conversation activity & title
    try:
        with db.transaction() as session:
            touch_conversation(session, thread_id, verified_user, user_message=payload.message)
    except Exception as exc:
        logger.warning("Failed to update conversation activity (%s)", exc)

    status = result.get("status", "success")
    if status in ("error", "llm_unavailable"):
        return ChatResponse(
            status=status,
            thread_id=thread_id,
            reply=result.get("reply", "Dịch vụ mô hình ngôn ngữ (LLM) hiện không khả dụng. Vui lòng thử lại sau."),
            tools_called=[],
            sources=[],
        )

    return ChatResponse(
        status="success",
        thread_id=thread_id,
        reply=result.get("reply", ""),
        tools_called=result.get("tools_called", []),
        sources=result.get("sources", []),
    )


@router.post("/conversations")
async def create_conversation_endpoint(
    payload: CreateConversationRequest | None = None,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Create a new persistent conversation for the verified user without deleting previous threads."""
    payload = payload or CreateConversationRequest()
    auth_user, _ = resolve_authenticated_user(
        request,
        client_claimed_user=payload.user_id,
        client_claimed_session=payload.session_id,
    )

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            conv = create_conversation(
                session,
                user_id=auth_user,
                title=payload.title,
                thread_id=payload.thread_id,
            )
            return {
                "status": "success",
                "conversation": serialize_conversation(conv),
            }
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to create conversation: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to create conversation: {exc}")


@router.get("/conversations")
async def list_conversations_endpoint(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """List persistent conversations owned by the verified user, sorted by latest activity."""
    auth_user, _ = resolve_authenticated_user(
        request,
        client_claimed_user=user_id,
        client_claimed_session=session_id,
    )

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            items, total = list_conversations(session, user_id=auth_user, limit=limit, offset=offset)
            return {
                "status": "success",
                "user_id": auth_user,
                "total": total,
                "count": len(items),
                "conversations": [serialize_conversation(c) for c in items],
            }
    except Exception as exc:
        logger.error("Failed to list conversations: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to list conversations: {exc}")


@router.get("/conversations/{thread_id}")
async def get_conversation(
    thread_id: str,
    request: Request,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve message history and metadata for a conversation thread strictly isolated by verified user."""
    auth_user, _ = resolve_authenticated_user(request, client_claimed_user=user_id, client_claimed_session=session_id)
    db = agent_config.get_database()

    # 1. Check registry and verify ownership
    title = "Cuộc trò chuyện mới"
    created_at = None
    updated_at = None
    try:
        with db.transaction() as session:
            conv = get_conversation_record(session, thread_id)
            if conv:
                if conv.user_id != auth_user:
                    raise HTTPException(
                        status_code=403,
                        detail="Forbidden: Cannot access another user's conversation thread.",
                    )
                title = conv.title
                created_at = conv.created_at.isoformat() if conv.created_at else None
                updated_at = conv.updated_at.isoformat() if conv.updated_at else None
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Could not read conversation registry record: %s", exc)

    # 2. Retrieve LangGraph checkpoint state
    checkpointer = get_checkpointer()
    config = make_thread_config(thread_id, user_id=auth_user)

    try:
        checkpoint_tuple = checkpointer.get_tuple(config)
        if not checkpoint_tuple or not checkpoint_tuple.checkpoint:
            return {
                "status": "success" if conv else "not_found",
                "thread_id": thread_id,
                "user_id": auth_user,
                "title": title,
                "created_at": created_at,
                "updated_at": updated_at,
                "message_count": 0,
                "messages": [],
            }

        channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
        raw_msgs = channel_values.get("messages", [])

        serialized = []
        for m in raw_msgs:
            m_type = getattr(m, "type", m.__class__.__name__)
            content = getattr(m, "content", "")
            msg_obj: dict[str, Any] = {
                "type": m_type,
                "content": content,
                "name": getattr(m, "name", None),
            }
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                msg_obj["tool_calls"] = tool_calls
            tool_call_id = getattr(m, "tool_call_id", None)
            if tool_call_id:
                msg_obj["tool_call_id"] = tool_call_id
            msg_id = getattr(m, "id", None)
            if msg_id:
                msg_obj["id"] = msg_id
            serialized.append(msg_obj)

        return {
            "status": "success",
            "thread_id": thread_id,
            "user_id": auth_user,
            "title": title,
            "created_at": created_at,
            "updated_at": updated_at,
            "message_count": len(serialized),
            "messages": serialized,
        }
    except Exception as exc:
        logger.error("Error retrieving conversation %s: %s", thread_id, exc)
        return {"status": "error", "message": str(exc), "messages": []}


@router.patch("/conversations/{thread_id}")
async def rename_conversation_endpoint(
    thread_id: str,
    payload: RenameConversationRequest,
    request: Request,
) -> dict[str, Any]:
    """Rename a conversation owned by the verified user."""
    auth_user, _ = resolve_authenticated_user(
        request,
        client_claimed_user=payload.user_id,
        client_claimed_session=payload.session_id,
    )

    db = agent_config.get_database()
    try:
        with db.transaction() as session:
            conv = rename_conversation(session, thread_id, auth_user, payload.title)
            return {
                "status": "success",
                "conversation": serialize_conversation(conv),
            }
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to rename conversation: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to rename conversation: {exc}")


@router.delete("/conversations/{thread_id}")
async def delete_conversation(
    thread_id: str,
    request: Request,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Permanently delete a conversation thread and its checkpoints strictly isolated by verified user."""
    auth_user, _ = resolve_authenticated_user(request, client_claimed_user=user_id, client_claimed_session=session_id)
    db = agent_config.get_database()

    # 1. Delete from conversation registry (with ownership check)
    try:
        with db.transaction() as session:
            delete_conversation_record(session, thread_id, auth_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        logger.warning("Failed to delete conversation record (%s)", exc)

    # 2. Clear checkpoint state in PostgresSaver/MemorySaver
    cleared = clear_thread_checkpoint(thread_id, user_id=auth_user)

    return {
        "status": "success",
        "message": f"Conversation thread '{thread_id}' for user '{auth_user}' deleted.",
        "thread_id": thread_id,
        "user_id": auth_user,
        "cleared": cleared,
    }
