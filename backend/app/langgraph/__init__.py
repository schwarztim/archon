"""LangGraph agent execution engine.

Usage::

    from app.langgraph import execute_agent

    result = await execute_agent(agent_id, definition, input_data)
"""

from app.langgraph.engine import execute_agent

__all__ = ["execute_agent"]
