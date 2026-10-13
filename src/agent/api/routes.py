"""API routes for DATT LangGraph Single AI Agent and persistent conversation management."""
import asyncio
import logging
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
import uuid

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
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
from src.agent.guard import check_prompt_safety
from src.agent.memory.checkpoint import clear_thread_checkpoint, get_checkpointer, make_thread_config

logger = logging.getLogger("datt.agent.api")

router = APIRouter(prefix="/api/agent", tags=["Agent"])


def registry_unavailable(exc):
    logger.error('Conversation registry unavailable (%s)', type(exc).__name__)
    return HTTPException(status_code=503, detail='Conversation registry is unavailable; retry later.')


def database():
    try:
        return agent_config.get_database()
    except Exception as exc:
        raise registry_unavailable(exc) from None


def missing_conversation(thread_id, user_id):
    return {'status': 'not_found', 'thread_id': thread_id, 'user_id': user_id,
            'title': 'Cuộc trò chuyện mới', 'created_at': None, 'updated_at': None,
            'message_count': 0, 'messages': []}


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
    provider: str | None = Field(default=None, description="Active LLM provider used")
    model: str | None = Field(default=None, description="Active LLM model name")
    failover_occurred: bool = Field(default=False, description="Whether failover from primary to fallback occurred")
    failover_level: int = Field(default=0, description="Failover tier: 0=Primary, 1=Level 1 (GPT-OSS), 2=Level 2 (Qwen)")
    action_suggestions: list[dict[str, Any]] = Field(default_factory=list, description="Recommended next-best investigation actions")
    investigation_context: dict[str, Any] | None = Field(default=None, description="Active structured investigation memory")


class TranscribeResponse(BaseModel):
    status: str
    text: str
    duration: float | None = None
    duration_sec: float | None = None
    language: str = "vi"
    latency_sec: float = 0.0
    model: str = "whisper-large-v3-turbo"


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

    # Verify conversation ownership and update/register registry in background thread
    def _verify_and_create() -> str:
        db = database()
        try:
            with db.transaction() as session:
                existing = get_conversation_record(session, thread_id)
                if existing and existing.user_id != verified_user:
                    return "forbidden"
                if not existing:
                    create_conversation(session, verified_user, thread_id=thread_id)
                return "ok"
        finally:
            db.dispose()

    try:
        check_status = await asyncio.to_thread(_verify_and_create)
        if check_status == "forbidden":
            raise HTTPException(
                status_code=403,
                detail="Forbidden: Cannot send messages to another user's conversation thread.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise registry_unavailable(exc) from None

    # Security check: Prompt Guard evaluation before LLM execution
    if agent_config.prompt_guard_enabled:
        guard_res = await asyncio.to_thread(check_prompt_safety, payload.message)
        if guard_res.get("is_injection") and agent_config.prompt_guard_block:
            logger.warning(
                "Prompt Guard flagged untrusted input in thread %s (score=%.4f)",
                thread_id,
                guard_res.get("score", 0.0),
            )
            return ChatResponse(
                status="flagged",
                thread_id=thread_id,
                reply="Yêu cầu bị từ chối: Hệ thống phát hiện câu lệnh có dấu hiệu vi phạm an toàn thông tin hoặc can thiệp chỉ dẫn hệ thống (Prompt Injection).",
                tools_called=[],
                sources=[],
                provider="prompt_guard",
                model=agent_config.prompt_guard_model,
                failover_occurred=False,
                failover_level=0,
            )

    # Offload blocking LangGraph execution to worker thread
    try:
        result = await asyncio.to_thread(
            run_agent_message, content=payload.message, thread_id=thread_id,
            user_id=verified_user, is_authenticated=is_authenticated,
        )
    except Exception as exc:
        logger.error('Agent unavailable (%s)', type(exc).__name__)
        raise HTTPException(status_code=503, detail='Agent/history service is unavailable.') from None

    if result.get('status') == 'error':
        raise HTTPException(status_code=503, detail='Agent/history service is unavailable.')

    # Update conversation activity & title in background thread
    def _touch_record() -> None:
        db = database()
        try:
            with db.transaction() as session:
                touch_conversation(session, thread_id, verified_user, user_message=payload.message)
        finally:
            db.dispose()

    try:
        await asyncio.to_thread(_touch_record)
    except Exception as exc:
        raise registry_unavailable(exc) from None

    status = result.get("status", "success")
    if status in ("error", "llm_unavailable"):
        return ChatResponse(
            status=status,
            thread_id=thread_id,
            reply=result.get("reply", "Dịch vụ mô hình ngôn ngữ (LLM) hiện không khả dụng. Vui lòng thử lại sau."),
            tools_called=[],
            sources=[],
            provider=result.get("provider"),
            model=result.get("model"),
            failover_occurred=result.get("failover_occurred", False),
            failover_level=result.get("failover_level", 0),
            action_suggestions=result.get("action_suggestions", []),
            investigation_context=result.get("investigation_context"),
        )

    return ChatResponse(
        status="success",
        thread_id=thread_id,
        reply=result.get("reply", ""),
        tools_called=result.get("tools_called", []),
        sources=result.get("sources", []),
        provider=result.get("provider"),
        model=result.get("model"),
        failover_occurred=result.get("failover_occurred", False),
        failover_level=result.get("failover_level", 0),
        action_suggestions=result.get("action_suggestions", []),
        investigation_context=result.get("investigation_context"),
    )


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_endpoint(
    request: Request,
    file: UploadFile = File(...),
) -> TranscribeResponse:
    """Transcribe audio recording to Vietnamese text using Groq Whisper Large V3 Turbo."""
    resolve_authenticated_user(request)

    if not agent_config.voice_enabled:
        raise HTTPException(status_code=403, detail="Voice features are currently disabled by configuration.")

    key = agent_config.groq_api_key or os.getenv("GROQ_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="Voice service unavailable: GROQ_API_KEY is not configured.")

    allowed_exts = {".webm", ".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".flac"}
    suffix = Path(file.filename or "audio.webm").suffix.lower() or ".webm"
    if suffix not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio format '{suffix}'. Supported: {', '.join(sorted(allowed_exts))}",
        )

    start_t = time.time()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with open(tmp_path, "wb") as f_out:
            shutil.copyfileobj(file.file, f_out)

        file_size = tmp_path.stat().st_size
        if file_size == 0:
            raise HTTPException(status_code=400, detail="Empty audio file provided.")
        if file_size > 25 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"Audio file size ({file_size} bytes) exceeds 25MB limit.")

        from groq import Groq
        groq_client = Groq(api_key=key, timeout=30.0)

        with open(tmp_path, "rb") as audio_file:
            transcription = await asyncio.to_thread(
                groq_client.audio.transcriptions.create,
                model=agent_config.whisper_model,
                file=audio_file,
                language="vi",
                response_format="verbose_json",
            )

        duration = getattr(transcription, "duration", None)
        text = getattr(transcription, "text", "") or ""
        latency = round(time.time() - start_t, 3)

        return TranscribeResponse(
            status="success",
            text=text.strip(),
            duration=duration,
            duration_sec=duration,
            language="vi",
            latency_sec=latency,
            model=agent_config.whisper_model,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Audio transcription error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Whisper transcription failed: {exc}") from exc
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


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

    db = database()
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
        raise registry_unavailable(exc) from None
    finally:
        db.dispose()


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

    def _fetch_list():
        db = database()
        try:
            with db.transaction() as session:
                return list_conversations(session, user_id=auth_user, limit=limit, offset=offset)
        finally:
            db.dispose()

    try:
        items, total = await asyncio.to_thread(_fetch_list)
        return {
            "status": "success",
            "user_id": auth_user,
            "total": total,
            "count": len(items),
            "conversations": [serialize_conversation(c) for c in items],
        }
    except Exception as exc:
        raise registry_unavailable(exc) from None


@router.get("/conversations/{thread_id}")
async def get_conversation(
    thread_id: str,
    request: Request,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve message history and metadata for a conversation thread strictly isolated by verified user."""
    auth_user, authenticated = resolve_authenticated_user(request, client_claimed_user=user_id, client_claimed_session=session_id)

    # 1. Check registry and verify ownership in background thread
    def _fetch_conv_record():
        db = database()
        try:
            with db.transaction() as session:
                conv = get_conversation_record(session, thread_id)
                if not conv:
                    return None, "Cuộc trò chuyện mới", None, None
                if conv.user_id != auth_user:
                    if not authenticated and conv.user_id.startswith('unauth_'):
                        return "unauth_conceal", "Cuộc trò chuyện mới", None, None
                    return "forbidden", "Cuộc trò chuyện mới", None, None
                t = conv.title
                c_at = conv.created_at.isoformat() if conv.created_at else None
                u_at = conv.updated_at.isoformat() if conv.updated_at else None
                return "found", t, c_at, u_at
        finally:
            db.dispose()

    try:
        conv_status, title, created_at, updated_at = await asyncio.to_thread(_fetch_conv_record)
        if conv_status == "forbidden":
            raise HTTPException(
                status_code=403,
                detail="Forbidden: Cannot access another user's conversation thread.",
            )
        if conv_status == "unauth_conceal" or conv_status is None:
            return missing_conversation(thread_id, auth_user)
    except HTTPException:
        raise
    except Exception as exc:
        raise registry_unavailable(exc) from None

    # 2. Retrieve LangGraph checkpoint state in background thread
    def _fetch_checkpoint_msgs():
        config = make_thread_config(thread_id, user_id=auth_user)
        checkpointer = get_checkpointer()
        checkpoint_tuple = checkpointer.get_tuple(config)
        if not checkpoint_tuple or not checkpoint_tuple.checkpoint:
            return []
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
        return serialized

    try:
        serialized = await asyncio.to_thread(_fetch_checkpoint_msgs)
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
        logger.error('Conversation checkpoint unavailable (%s)', type(exc).__name__)
        raise HTTPException(status_code=503, detail='Conversation history is unavailable; retry later.') from None


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

    db = database()
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
        raise registry_unavailable(exc) from None
    finally:
        db.dispose()


@router.delete("/conversations/{thread_id}")
async def delete_conversation(
    thread_id: str,
    request: Request,
    user_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Permanently delete a conversation thread and its checkpoints strictly isolated by verified user."""
    auth_user, _ = resolve_authenticated_user(request, client_claimed_user=user_id, client_claimed_session=session_id)
    db = database()

    # 1. Delete from conversation registry (with ownership check)
    try:
        with db.transaction() as session:
            conv = get_conversation_record(session, thread_id, auth_user)
            if conv is None:
                raise HTTPException(status_code=404, detail='Conversation not found.')
            cleared = clear_thread_checkpoint(thread_id, user_id=auth_user, session=session)
            if not cleared:
                raise HTTPException(status_code=503, detail='Conversation history deletion failed; retry later.')
            delete_conversation_record(session, thread_id, auth_user)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        raise registry_unavailable(exc) from None
    finally:
        db.dispose()

    return {
        "status": "success",
        "message": f"Conversation thread '{thread_id}' for user '{auth_user}' deleted.",
        "thread_id": thread_id,
        "user_id": auth_user,
        "cleared": cleared,
    }

