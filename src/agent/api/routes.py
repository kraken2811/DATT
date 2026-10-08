import asyncio
import logging
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.agent.api.auth import resolve_authenticated_user
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


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(payload: ChatRequest, request: Request) -> ChatResponse:
    """Send a message to the DATT AI Agent with conversation continuity.

    Offloaded to worker threadpool via asyncio.to_thread so that synchronous LLM calls,
    ONNX embeddings, and DB queries never block the asyncio loop or realtime CV streams.
    """
    thread_id = payload.thread_id or f"conv_{uuid.uuid4().hex[:12]}"
    verified_user, is_authenticated = resolve_authenticated_user(
        request,
        client_claimed_user=payload.user_id,
        client_claimed_session=payload.session_id,
    )

    # Offload blocking LangGraph execution to worker thread
    result = await asyncio.to_thread(
        run_agent_message,
        content=payload.message,
        thread_id=thread_id,
        user_id=verified_user,
        is_authenticated=is_authenticated,
    )

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


@router.get("/conversations/{thread_id}")
async def get_conversation(
    thread_id: str,
    request: Request,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve message history for a given conversation thread strictly isolated by verified user."""
    auth_user, _ = resolve_authenticated_user(request, client_claimed_user=user_id, client_claimed_session=session_id)
    checkpointer = get_checkpointer()
    config = make_thread_config(thread_id, user_id=auth_user)

    try:
        checkpoint_tuple = checkpointer.get_tuple(config)
        if not checkpoint_tuple or not checkpoint_tuple.checkpoint:
            return {"status": "not_found", "thread_id": thread_id, "user_id": auth_user, "message_count": 0, "messages": []}

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
            "message_count": len(serialized),
            "messages": serialized,
        }
    except Exception as exc:
        logger.error("Error retrieving conversation %s: %s", thread_id, exc)
        return {"status": "error", "message": str(exc), "messages": []}


@router.delete("/conversations/{thread_id}")
async def delete_conversation(
    thread_id: str,
    request: Request,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Reset / clear a conversation thread strictly isolated by verified user."""
    auth_user, _ = resolve_authenticated_user(request, client_claimed_user=user_id, client_claimed_session=session_id)
    cleared = clear_thread_checkpoint(thread_id, user_id=auth_user)
    return {
        "status": "success",
        "message": f"Conversation thread '{thread_id}' for user '{auth_user}' reset.",
        "thread_id": thread_id,
        "user_id": auth_user,
        "cleared": cleared,
    }
