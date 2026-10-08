"""Agent node and Tool node execution logic for LangGraph."""

import json
import logging
import os
from typing import Any
import uuid

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.language_models.chat_models import BaseChatModel

from src.agent.config import agent_config
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.response_formatting import current_turn, format_tool_messages
from src.agent.state import AgentState
from src.agent.tools import ALL_AGENT_TOOLS

logger = logging.getLogger("datt.agent.nodes")


class MockChatModel:
    """Deterministic rule-based mock chat model for tests and offline environments."""

    def __init__(self, tools: list[Any] | None = None) -> None:
        self.tools = {t.name: t for t in (tools or ALL_AGENT_TOOLS)}

    def bind_tools(self, tools: list[Any]) -> "MockChatModel":
        self.tools = {t.name: t for t in tools}
        return self

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        last_msg = messages[-1] if messages else HumanMessage(content="")
        content = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)

        # Check if tools are unbound / disabled
        tools_enabled = bool(self.tools)

        # 1. Check if prior message was a ToolMessage
        if isinstance(last_msg, ToolMessage) or (not tools_enabled and current_turn(messages)[1]):
            tool_name = getattr(last_msg, "name", "")
            # Hybrid check: If first tool was get_camera_status and user asked for documentation guide
            user_msg = current_turn(messages)[0]
            lower_user = str(user_msg).lower()
            if (
                tools_enabled
                and "get_knowledge" in self.tools
                and tool_name == "get_camera_status"
                and ("tài liệu" in lower_user or "hướng dẫn" in lower_user or "xử lý" in lower_user or "khắc phục" in lower_user)
            ):
                # Call get_knowledge as part of legitimate multi-step execution
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_knowledge",
                            "args": {"query": "Hướng dẫn khắc phục camera mất kết nối offline", "top_k": 3},
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                        }
                    ],
                )

            return AIMessage(content=format_tool_messages(messages))

        lower_q = content.lower()

        # 2. Prompt injection defense
        injection_patterns = [
            "ignore previous instructions", "dump all database", "dump database",
            "secrets", "system prompt", "drop table", "quên chỉ dẫn trước",
        ]
        if any(p in lower_q for p in injection_patterns):
            return AIMessage(
                content="Yêu cầu bị từ chối: Tôi không được phép tiết lộ cấu hình bảo mật hoặc trích xuất cơ sở dữ liệu hệ thống."
            )

        # 3. Creative requests (poems, jokes, chitchat) -> Direct response, NO tools
        if "bài thơ" in lower_q or "làm thơ" in lower_q or "poem" in lower_q:
            return AIMessage(
                content="Camera lặng lẽ bốn phương trời,\nGiám sát an ninh chẳng nghỉ ngơi.\nMỗi khung hình gửi niềm tin cậy,\nBình yên cuộc sống rạng nụ cười."
            )

        # 4. Short-term memory recall (e.g. secret markers or shift codes)
        if "marker" in lower_q or "secret" in lower_q or "bí mật" in lower_q or "mã ca trực" in lower_q or "mã trực" in lower_q or "mã của tôi" in lower_q:
            import re
            for m in messages[:-1]:
                m_txt = str(m.content)
                if "ALPHA-" in m_txt:
                    match = re.search(r"ALPHA-\d+", m_txt)
                    if match:
                        return AIMessage(content=f"Mã ca trực (secret marker) của bạn là: {match.group(0)}")
            return AIMessage(content="Tôi không có thông tin về secret marker hoặc mã ca trực nào trong phiên hội thoại này.")

        # If tools are disabled (budget exhausted or unbound), synthesize directly
        if not tools_enabled:
            return AIMessage(
                content="Dựa trên các thông tin đã thu thập được từ hệ thống, yêu cầu của bạn đã được ghi nhận."
            )

        # 5. Hybrid question: Camera status first, then documentation
        if ("đang offline" in lower_q or "mất kết nối" in lower_q) and ("tài liệu" in lower_q or "hướng dẫn" in lower_q):
            cam_id = "camera_01"
            for word in content.split():
                clean_w = word.strip(".,:;!?\"'")
                if clean_w.upper().startswith("CAM") or clean_w.lower().startswith("camera"):
                    cam_id = clean_w
                    break
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_camera_status",
                        "args": {"camera_id": cam_id},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # 6. Intent-based tool routing
        # A. Camera status query
        if ("camera" in lower_q or "cam" in lower_q) and ("online" in lower_q or "offline" in lower_q or "trạng thái" in lower_q or "status" in lower_q):
            cam_id = "camera_01"
            for word in content.split():
                clean_w = word.strip(".,:;!?\"'")
                if clean_w.upper().startswith("CAM") or clean_w.lower().startswith("camera"):
                    cam_id = clean_w
                    break
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_camera_status",
                        "args": {"camera_id": cam_id},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # B. Event counts today / Statistics / Busiest / most crowded camera
        if (
            "bao nhiêu sự kiện" in lower_q
            or "thống kê" in lower_q
            or "đông nhất" in lower_q
            or "busiest" in lower_q
            or "lưu lượng" in lower_q
            or ("hôm nay" in lower_q and ("sự kiện" in lower_q or "xe" in lower_q))
        ):
            group = "camera" if ("đông nhất" in lower_q or "busiest" in lower_q) else "type"
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_event_statistics",
                        "args": {"group_by": group},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # C. Watchlist search
        if "watchlist" in lower_q or "danh sách theo dõi" in lower_q:
            target = None
            if "biển số" in lower_q or "30a-" in lower_q:
                import re
                match = re.search(r"[0-9]{2}[A-Za-z]-[0-9]{4,5}", content)
                target = match.group(0) if match else "30A-12345"
            args = {"target": target, "limit": 10} if target else {"limit": 10}
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_watchlist",
                        "args": args,
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # D. Operational events search (person detection or target or specific events)
        if (
            "target_" in lower_q
            or "xuất hiện" in lower_q
            or ("người" in lower_q and "sự kiện" in lower_q)
            or ("sự kiện" in lower_q and ("gần đây" in lower_q or "tra cứu" in lower_q or "tìm" in lower_q or "danh sách" in lower_q))
        ):
            person_id = None
            for w in content.split():
                if w.lower().startswith("target_"):
                    person_id = w.strip(".,:;!?\"'")
            args = {"limit": 10}
            if person_id:
                args["person_id"] = person_id
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_events",
                        "args": args,
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # E & F. Documentation / How-to / Troubleshooting -> get_knowledge
        if (
            "tài liệu" in lower_q
            or "hướng dẫn" in lower_q
            or "khắc phục" in lower_q
            or "xử lý thế nào" in lower_q
            or "quy tắc" in lower_q
            or "chính sách" in lower_q
            or "cấu hình" in lower_q
            or "kiến trúc" in lower_q
            or "how to" in lower_q
            or "troubleshoot" in lower_q
            or "bytetrack" in lower_q
        ):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_knowledge",
                        "args": {"query": content, "top_k": 3},
                        "id": f"call_{uuid.uuid4().hex[:8]}",
                    }
                ],
            )

        # Default conversational greeting
        return AIMessage(
            content="Xin chào! Tôi là Trợ lý Vận hành Hệ thống DATT. Tôi có thể hỗ trợ bạn kiểm tra camera, tra cứu sự kiện, danh sách theo dõi, thống kê phương tiện hoặc tra cứu tài liệu hướng dẫn khắc phục sự cố."
        )


def get_llm():
    """Resolve configured resilient Chat Model."""
    from src.agent.llm import get_configured_llm
    return get_configured_llm()


def trim_messages(messages: list[BaseMessage], max_count: int = 20) -> list[BaseMessage]:
    """Preserve system message and keep most recent conversation turns starting with HumanMessage."""
    sys_msg = [m for m in messages if isinstance(m, SystemMessage)]
    non_sys = [m for m in messages if not isinstance(m, SystemMessage)]

    if len(non_sys) > max_count:
        non_sys = non_sys[-max_count:]

    # Ensure the non-system sequence always starts with a HumanMessage
    # to avoid orphan ToolMessages breaking strict provider APIs (like Google Gemini)
    first_human_idx = None
    for idx, m in enumerate(non_sys):
        if isinstance(m, HumanMessage):
            first_human_idx = idx
            break

    if first_human_idx is not None and first_human_idx > 0:
        non_sys = non_sys[first_human_idx:]

    return sys_msg + non_sys


def agent_node(state: AgentState) -> dict[str, Any]:
    """LangGraph Agent node: processes messages, injects system prompt, and calls LLM."""
    from src.agent.llm import LLMUnavailableException
    raw_messages = list(state.get("messages", []))

    # 1. Ensure system prompt is first message
    has_system = any(isinstance(m, SystemMessage) for m in raw_messages)
    if not has_system:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + raw_messages
    else:
        messages = raw_messages

    # 2. Context trimming
    trimmed = trim_messages(messages, max_count=agent_config.max_history_messages)

    # 3. Check execution budget
    cycles = state.get("tool_cycles", 0)
    total_calls = state.get("total_tool_calls", 0)
    budget_exhausted = (cycles >= agent_config.max_tool_cycles) or (total_calls >= agent_config.max_total_tool_calls)

    llm = get_llm()
    if not budget_exhausted and hasattr(llm, "bind_tools"):
        llm = llm.bind_tools(ALL_AGENT_TOOLS)
    elif hasattr(llm, "bind_tools"):
        llm = llm.bind_tools([])

    # If budget exhausted, instruct LLM to synthesize partial results
    if budget_exhausted:
        trimmed.append(
            HumanMessage(
                content=(
                    "[Hệ thống: Hạn mức gọi công cụ đã kết thúc "
                    f"({cycles}/{agent_config.max_tool_cycles} chu kỳ, "
                    f"{total_calls}/{agent_config.max_total_tool_calls} lượt gọi). "
                    "Hãy tổng hợp câu trả lời cuối cùng từ các dữ liệu và kết quả một phần đã thu thập được ở trên, "
                    "nêu rõ những thông tin đã xác minh được và lưu ý hạn chế dữ liệu nếu có.]"
                )
            )
        )

    try:
        response = llm.invoke(trimmed)
        return {"messages": [response]}
    except LLMUnavailableException as exc:
        logger.error("LLM unavailable: %s", exc)
        return {
            "messages": [
                AIMessage(
                    content="Dịch vụ mô hình ngôn ngữ (LLM) hiện không khả dụng. Vui lòng thử lại sau.",
                    additional_kwargs={"status": "llm_unavailable", "reason": getattr(exc, "reason", "error")},
                )
            ],
            "error": "llm_unavailable",
        }


def tool_node(state: AgentState) -> dict[str, Any]:
    """Safe execution of tool calls with argument validation, error handling, duplicate prevention, and execution budget."""
    messages = state.get("messages", [])
    if not messages:
        return {"messages": []}

    last_ai_message = messages[-1]
    tool_calls = getattr(last_ai_message, "tool_calls", None)
    if not tool_calls:
        return {"messages": []}

    tool_map = {t.name: t for t in ALL_AGENT_TOOLS}
    tool_counts = dict(state.get("tool_call_counts", {}))
    repeated_count = state.get("repeated_tool_calls", 0)
    total_calls = state.get("total_tool_calls", 0)

    tool_results: list[ToolMessage] = []
    seen_in_batch: set[str] = set()

    for call in tool_calls:
        call_name = call.get("name")
        call_args = call.get("args", {})
        call_id = call.get("id", f"call_{uuid.uuid4().hex[:8]}")
        call_signature = f"{call_name}:{json.dumps(call_args, sort_keys=True)}"

        # A. Execution Budget Check
        if total_calls >= agent_config.max_total_tool_calls:
            logger.info("Total tool call budget reached (%s); skipping further calls", total_calls)
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "budget_exhausted",
                            "message": f"Hạn mức tổng số lượt gọi công cụ ({agent_config.max_total_tool_calls}) đã đạt. Trả về kết quả một phần.",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        # B. Duplicate call in same batch/turn check
        if call_signature in seen_in_batch:
            logger.info("Duplicate tool call in same batch detected for %s; skipping duplicate execution", call_signature)
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "duplicate_call_skipped",
                            "message": f"Công cụ '{call_name}' đã được gọi trong cùng lượt xử lý với đối số tương tự. Tránh gọi trùng lặp.",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue
        seen_in_batch.add(call_signature)

        # C. Repeated calls across turns check
        count = tool_counts.get(call_signature, 0) + 1
        tool_counts[call_signature] = count

        if count > agent_config.max_tool_repeats:
            repeated_count += 1
            logger.warning("Repeated tool call loop detected for %s; breaking loop", call_signature)
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "loop_prevention",
                            "message": f"Công cụ '{call_name}' đã được gọi {count} lần với cùng đối số. Vui lòng tổng hợp câu trả lời từ dữ liệu đã có.",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        target_tool = tool_map.get(call_name)
        if not target_tool:
            tool_results.append(
                ToolMessage(
                    content=json.dumps({"status": "error", "message": f"Unknown tool '{call_name}'"}),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        # Authorization check for sensitive operational tools
        is_authenticated = state.get("is_authenticated", False)
        sensitive_tools = {"search_watchlist"}
        require_auth = os.getenv("DATT_STRICT_AUTH") == "1" or os.getenv("DATT_REQUIRE_OPERATIONAL_AUTH") == "1"
        if require_auth and call_name in sensitive_tools and not is_authenticated:
            logger.warning(
                "Unauthorized attempt to access sensitive tool %s by unauthenticated user %s",
                call_name,
                state.get("user_id"),
            )
            tool_results.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "unauthorized",
                            "message": f"Truy cập bị từ chối: Công cụ '{call_name}' yêu cầu thông tin xác thực phiên làm việc hợp lệ (Authorization Bearer token).",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
            continue

        # Execute tool safely
        total_calls += 1
        try:
            res = target_tool.invoke(call_args)
            content_str = json.dumps(res, ensure_ascii=False) if isinstance(res, (dict, list)) else str(res)
            tool_results.append(
                ToolMessage(
                    content=content_str,
                    tool_call_id=call_id,
                    name=call_name,
                )
            )
        except Exception as exc:
            logger.error("Error executing tool %s: %s", call_name, exc)
            tool_results.append(
                ToolMessage(
                    content=json.dumps({"status": "error", "message": f"Execution failed: {exc}"}),
                    tool_call_id=call_id,
                    name=call_name,
                )
            )

    return {
        "messages": tool_results,
        "tool_call_counts": tool_counts,
        "repeated_tool_calls": repeated_count,
        "tool_cycles": state.get("tool_cycles", 0) + 1,
        "total_tool_calls": total_calls,
    }


def should_continue(state: AgentState) -> str:
    """Conditional edge router: determines if graph should call tools or finish."""
    if state.get("error") == "llm_unavailable":
        return "__end__"

    messages = state.get("messages", [])
    if not messages:
        return "__end__"

    last_message = messages[-1]
    tool_calls = getattr(last_message, "tool_calls", None)
    if tool_calls and len(tool_calls) > 0:
        cycles = state.get("tool_cycles", 0)
        total_calls = state.get("total_tool_calls", 0)
        repeated = state.get("repeated_tool_calls", 0)
        if (
            cycles >= agent_config.max_tool_cycles
            or total_calls >= agent_config.max_total_tool_calls
            or repeated >= 3
        ):
            logger.info("Ending tool loop due to budget or repeat threshold")
            return "__end__"
        return "tools"

    return "__end__"
