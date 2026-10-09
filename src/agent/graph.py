"""LangGraph StateGraph orchestration for DATT Single AI Agent."""

import logging
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from src.agent.config import agent_config
from src.agent.memory.checkpoint import get_checkpointer, make_thread_config
from src.agent.nodes import agent_node, should_continue, tool_node
from src.agent.state import AgentState

logger = logging.getLogger("datt.agent.graph")


def build_agent_graph(checkpointer: BaseCheckpointSaver | None = None) -> Any:
    """Construct and compile the LangGraph Single Agent StateGraph.

    Architecture:
        START -> agent_node -> should_continue -> (tools -> agent_node) | END
    """
    workflow = StateGraph(AgentState)

    # 1. Register nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tool_node)

    # 2. Add edges
    workflow.add_edge(START, "agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "__end__": END,
        },
    )

    workflow.add_edge("tools", "agent")

    # 3. Compile graph with checkpointer
    resolved_checkpointer = checkpointer if checkpointer is not None else get_checkpointer()
    return workflow.compile(checkpointer=resolved_checkpointer)


_compiled_graph = None


def get_agent_graph(checkpointer: BaseCheckpointSaver | None = None) -> Any:
    """Singleton getter for compiled agent graph."""
    global _compiled_graph
    if checkpointer is not None:
        return build_agent_graph(checkpointer=checkpointer)
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph(checkpointer=get_checkpointer())
    return _compiled_graph


def run_agent_message(
    content: str,
    thread_id: str,
    user_id: str = "default_user",
    is_authenticated: bool | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> dict[str, Any]:
    """Execute a single conversation turn through the compiled LangGraph Agent.

    Args:
        content: User prompt text.
        thread_id: Unique conversation identifier.
        user_id: User identifier for tenant isolation.
        is_authenticated: Whether the user was cryptographically verified.
        checkpointer: Optional checkpointer override.

    Returns:
        Structured response dictionary with reply content, tool executions, and sources.
    """
    graph = get_agent_graph(checkpointer=checkpointer)
    config = make_thread_config(thread_id, user_id=user_id)
    eff_auth = is_authenticated if is_authenticated is not None else (not user_id.startswith("unauth_"))

    user_message = HumanMessage(content=content, id=uuid.uuid4().hex)
    initial_input = {
        "messages": [user_message],
        "thread_id": thread_id,
        "user_id": user_id,
        "is_authenticated": eff_auth,
        "tool_call_counts": {},
        "repeated_tool_calls": 0,
        "tool_cycles": 0,
        "total_tool_calls": 0,
        "error": None,
    }

    try:
        final_state = graph.invoke(initial_input, config=config)
    except Exception as exc:
        logger.error("LangGraph execution error on thread %s: %s", thread_id, exc)
        return {
            "status": "error",
            "thread_id": thread_id,
            "reply": f"Hệ thống gặp sự cố khi xử lý yêu cầu: {exc}",
            "tools_called": [],
            "sources": [],
        }

    # Extract conversation outputs
    messages = final_state.get("messages", [])
    # Checkpoints retain prior turns; response metadata belongs to this input only.
    start = next((i + 1 for i, msg in enumerate(messages) if msg.id == user_message.id), len(messages))
    messages = messages[start:]
    reply_content = ""
    tools_called = []
    sources = []

    for msg in messages:
        if isinstance(msg, AIMessage) and msg.content:
            if isinstance(msg.content, list):
                text_parts = []
                for part in msg.content:
                    if isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                    elif isinstance(part, str):
                        text_parts.append(part)
                    else:
                        text_parts.append(str(part))
                reply_content = "\n".join(text_parts)
            else:
                reply_content = str(msg.content)
        elif isinstance(msg, ToolMessage):
            tool_name = getattr(msg, "name", "tool")
            if tool_name not in tools_called:
                tools_called.append(tool_name)
            if tool_name == "get_knowledge":
                try:
                    import json
                    k_data = json.loads(msg.content)
                    if isinstance(k_data, dict) and "results" in k_data:
                        for item in k_data["results"]:
                            sources.append({
                                "title": item.get("document_name", "Tài liệu"),
                                "section": item.get("section", "Chung"),
                                "score": item.get("score"),
                                "page": item.get("page"),
                            })
                except Exception:
                    pass

    if final_state.get("error") == "llm_unavailable":
        return {
            "status": "llm_unavailable",
            "thread_id": thread_id,
            "reply": reply_content or "Dịch vụ mô hình ngôn ngữ (LLM) hiện không khả dụng. Vui lòng thử lại sau.",
            "tools_called": tools_called,
            "sources": sources,
        }

    return {
        "status": "success",
        "thread_id": thread_id,
        "reply": reply_content or "Yêu cầu đã được thực thi thành công.",
        "tools_called": tools_called,
        "sources": sources,
    }
