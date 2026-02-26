"""LangGraph node functions for agent execution.

Stub implementations for the vertical slice. Each node receives the current
AgentState and returns a partial update dict that LangGraph merges back.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from app.langgraph.state import AgentState


def process_node(state: AgentState) -> dict[str, Any]:
    """Process input data and produce an intermediate result.

    For the vertical slice this is a pass-through: it echoes the last
    human message back as an AI message and advances the step counter.
    """
    last_message = state["messages"][-1] if state["messages"] else None
    content = last_message.content if last_message else ""

    return {
        "messages": [AIMessage(content=f"Processed: {content}")],
        "current_step": "respond",
    }


def respond_node(state: AgentState) -> dict[str, Any]:
    """Format the final output for the caller.

    Collects all AI-generated messages and packages them into the
    ``output`` field so ``execute_agent`` can return a clean result.
    """
    ai_messages = [
        m.content for m in state["messages"] if isinstance(m, AIMessage)
    ]
    return {
        "output": {"result": ai_messages[-1] if ai_messages else None},
        "current_step": "done",
    }
