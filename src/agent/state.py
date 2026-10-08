"""Agent State definition for LangGraph orchestrator."""

from typing import Annotated, Any
from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages


class AgentState(MessagesState):
    """Conversation and execution state for DATT Single Agent."""

    # Thread and user scoping
    thread_id: str
    user_id: str
    is_authenticated: bool

    # Execution telemetry and loop prevention
    tool_call_counts: dict[str, int]
    repeated_tool_calls: int
    tool_cycles: int
    total_tool_calls: int
    error: str | None
