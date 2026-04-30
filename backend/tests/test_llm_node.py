"""Tests for the LLM node and call_llm wrapper.

Run with::

    LLM_STUB_MODE=true PYTHONPATH=backend python3 -m pytest backend/tests/test_llm_node.py -v

All tests use LLM_STUB_MODE=true — no API keys required.
"""

from __future__ import annotations

import os

import pytest

# Ensure stub mode is active for all tests in this module
os.environ["LLM_STUB_MODE"] = "true"

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.langgraph.llm import LLMResponse, call_llm  # noqa: E402
from app.langgraph.nodes import process_node  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1 — call_llm in stub mode returns [STUB] content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_llm_stub_mode_content() -> None:
    """call_llm with LLM_STUB_MODE=true returns content starting with [STUB]."""
    resp = await call_llm("hello")
    assert isinstance(resp, LLMResponse)
    assert resp.content.startswith("[STUB]"), (
        f"Expected content to start with '[STUB]', got: {resp.content!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — process_node appends an AIMessage with [STUB] content
# ---------------------------------------------------------------------------


def test_process_node_appends_ai_message() -> None:
    """process_node with stub mode appends an AIMessage with [STUB] content."""
    state = {
        "messages": [HumanMessage(content="Say hi")],
        "agent_definition": {"system_prompt": "Test", "model": "gpt-3.5-turbo"},
        "input": "Say hi",
        "current_step": "process",
        "output": None,
        "error": None,
        "token_usage": {},
    }

    result = process_node(state)  # type: ignore[arg-type]

    new_messages = result.get("messages", [])
    assert len(new_messages) == 1, f"Expected 1 new message, got {len(new_messages)}"
    msg = new_messages[0]
    assert isinstance(msg, AIMessage), f"Expected AIMessage, got {type(msg)}"
    assert msg.content.startswith("[STUB]"), (
        f"Expected content to start with '[STUB]', got: {msg.content!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — process_node accumulates token_usage with total_tokens == 30
# ---------------------------------------------------------------------------


def test_process_node_token_usage() -> None:
    """process_node accumulates token_usage; total_tokens == 30 for stub."""
    state = {
        "messages": [HumanMessage(content="Say hi")],
        "agent_definition": {"system_prompt": "Test", "model": "gpt-3.5-turbo"},
        "input": "Say hi",
        "current_step": "process",
        "output": None,
        "error": None,
        "token_usage": {},
    }

    result = process_node(state)  # type: ignore[arg-type]

    token_usage = result.get("token_usage", {})
    assert token_usage.get("total_tokens") == 30, (
        f"Expected total_tokens=30, got: {token_usage.get('total_tokens')}"
    )
    assert token_usage.get("prompt_tokens") == 10
    assert token_usage.get("completion_tokens") == 20
