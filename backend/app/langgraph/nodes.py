"""LangGraph node functions for agent execution.

``process_node`` calls an LLM via ``call_llm`` (LiteLLM wrapper).
``respond_node`` finalises the result and packages token usage.

Set ``LLM_STUB_MODE=true`` in the environment to get deterministic stub
responses without any API key — required for unit tests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from app.langgraph.llm import LLMResponse, call_llm
from app.langgraph.state import AgentState

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM = "You are a helpful AI assistant."
_DEFAULT_MODEL = "gpt-3.5-turbo"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _last_human_content(state: AgentState) -> str:
    """Return the content of the most recent HumanMessage, or empty string."""
    for msg in reversed(state.get("messages", [])):  # type: ignore[arg-type]
        if isinstance(msg, HumanMessage):
            return str(msg.content)
    return ""


def _run_async(coro: Any) -> Any:
    """Run a coroutine from a sync context.

    LangGraph may call node functions synchronously.  This helper runs the
    coroutine in the current event loop if one is running, or creates a new
    one otherwise.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context — use run_coroutine_threadsafe
            # or, more commonly, the caller is already in async context and
            # LangGraph's ainvoke path will just await the coroutine.
            # Fallback: nest via asyncio.ensure_future is not possible here;
            # use a new event loop in a thread.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def process_node(state: AgentState) -> dict[str, Any]:
    """Call the LLM and append the response to the message list.

    Reads from state:
    - ``agent_definition`` (optional dict): may contain ``system_prompt`` and
      ``model``. When absent, defaults are used.
    - ``input`` (optional str): raw text input. Falls back to the last
      HumanMessage content when absent.

    Returns a partial state update dict with:
    - ``messages``: list containing the new ``AIMessage``
    - ``current_step``: ``"respond"``
    - ``token_usage``: cumulative token counts dict
    """
    agent_def: dict[str, Any] = state.get("agent_definition", {}) or {}  # type: ignore[assignment]
    system_prompt: str = agent_def.get("system_prompt") or _DEFAULT_SYSTEM
    model: str = agent_def.get("model") or _DEFAULT_MODEL

    # Determine prompt: prefer explicit ``input`` key, fall back to messages
    input_text: str = state.get("input") or _last_human_content(state)  # type: ignore[arg-type]

    logger.info(
        "process_node.start",
        extra={"model": model, "input_len": len(input_text)},
    )

    try:
        llm_resp: LLMResponse = _run_async(
            call_llm(
                prompt=input_text,
                model=model,
                system=system_prompt,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("process_node.llm_error", extra={"error": str(exc)})
        return {
            "messages": [AIMessage(content=f"Error: {exc}")],
            "current_step": "respond",
            "error": f"{type(exc).__name__}: {exc}",
            "token_usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    # Accumulate token usage (merge with any prior usage in state)
    prior: dict[str, Any] = state.get("token_usage", {}) or {}  # type: ignore[assignment]
    token_usage = {
        "prompt_tokens": prior.get("prompt_tokens", 0) + llm_resp.prompt_tokens,
        "completion_tokens": (
            prior.get("completion_tokens", 0) + llm_resp.completion_tokens
        ),
        "total_tokens": prior.get("total_tokens", 0) + llm_resp.total_tokens,
        "cost_usd": (prior.get("cost_usd") or 0.0) + (llm_resp.cost_usd or 0.0),
        "model_used": llm_resp.model_used,
        "latency_ms": llm_resp.latency_ms,
    }

    logger.info(
        "process_node.complete",
        extra={
            "total_tokens": llm_resp.total_tokens,
            "model_used": llm_resp.model_used,
        },
    )

    return {
        "messages": [AIMessage(content=llm_resp.content)],
        "current_step": "respond",
        "token_usage": token_usage,
    }


def respond_node(state: AgentState) -> dict[str, Any]:
    """Finalise the workflow output.

    Collects all AI-generated messages and packages them into ``output``
    alongside the accumulated ``token_usage``.
    """
    ai_messages = [
        m.content for m in state["messages"] if isinstance(m, AIMessage)
    ]
    token_usage: dict[str, Any] = state.get("token_usage", {}) or {}  # type: ignore[assignment]

    return {
        "output": {
            "result": ai_messages[-1] if ai_messages else None,
            "token_usage": token_usage,
        },
        "current_step": "done",
        "status": "completed",
    }
