"""Shared agent state schema used across the LangGraph execution engine."""

from __future__ import annotations

from typing import Annotated, Any, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Typed state that flows through every node in an agent graph.

    Attributes:
        messages: Conversation history. Uses the ``add_messages`` reducer so
            each node can *append* messages rather than replacing the list.
        current_step: Name of the step the agent is currently executing.
        output: Arbitrary output payload populated by the final node.
        error: Optional error description set when execution fails.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    current_step: str
    output: Any
    error: Optional[str]
    token_usage: dict[str, int]
