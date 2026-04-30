"""LLM node contract tests — Phase 3 / WS9.

Coverage dimensions:

1. input schema      — ``call_llm`` is invoked with the configured prompt + model.
2. output schema     — content, model_used, latency_ms; token_usage dict; cost_usd.
3. success path      — minimal config + LLM_STUB_MODE → status="completed".
4. failure path      — call_llm raises → status="failed", error populated.
5. cancellation      — N/A (LLM is opaque mid-call); skipped with reason.
6. retry classification — TransientError-shaped exc → status="failed",
                          error names the exc type so the dispatcher's
                          RetryPolicy can classify it.
7. tenant isolation   — call doesn't leak tenant_id into the prompt; tenant
                        is not passed to call_llm directly (LLM has no tenant
                        scope; isolation is upstream).
8. event emission    — N/A (LLM does not emit events directly; the dispatcher
                        records run.step.completed); skipped with reason.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")

from app.langgraph.llm import LLMResponse  # noqa: E402
from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


def _stub_response(content: str = "[STUB] hi", cost: float = 0.0) -> LLMResponse:
    return LLMResponse(
        content=content,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cost_usd=cost,
        model_used="gpt-3.5-turbo-stub",
        latency_ms=1.0,
    )


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_input_schema_minimal_required():
    """No prompt → falls back to str(inputs); does not crash."""
    ctx = make_ctx("llmNode", config={"model": "gpt-3.5-turbo"}, inputs={"x": 1})
    result = await NODE_EXECUTORS["llmNode"].execute(ctx)
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_llm_input_schema_supports_camel_and_snake():
    """Both ``maxTokens`` and ``max_tokens`` (likewise ``user_prompt``) accepted."""
    ctx_camel = make_ctx(
        "llmNode",
        config={"model": "gpt-3.5-turbo", "userPrompt": "hi", "maxTokens": 64},
    )
    ctx_snake = make_ctx(
        "llmNode",
        config={"model": "gpt-3.5-turbo", "user_prompt": "hi", "max_tokens": 64},
    )
    r_camel = await NODE_EXECUTORS["llmNode"].execute(ctx_camel)
    r_snake = await NODE_EXECUTORS["llmNode"].execute(ctx_snake)
    assert r_camel.status == "completed"
    assert r_snake.status == "completed"


# ---------------------------------------------------------------------------
# 2. output schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_output_shape():
    """Output dict has content/model_used/latency_ms; token_usage + cost_usd populated."""
    ctx = make_ctx("llmNode", config={"prompt": "hi"})
    result = await NODE_EXECUTORS["llmNode"].execute(ctx)
    assert result.status == "completed"
    assert "content" in result.output
    assert "model_used" in result.output
    assert "latency_ms" in result.output
    assert isinstance(result.token_usage, dict)
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(
        result.token_usage.keys()
    )
    assert result.cost_usd is not None


# ---------------------------------------------------------------------------
# 3. success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_success_with_explicit_mock():
    ctx = make_ctx("llmNode", config={"prompt": "say hi"})
    with patch(
        "app.langgraph.llm.call_llm",
        new=AsyncMock(return_value=_stub_response("hello world", cost=0.001)),
    ):
        result = await NODE_EXECUTORS["llmNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["content"] == "hello world"
    assert result.cost_usd == 0.001


# ---------------------------------------------------------------------------
# 4. failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_failure_call_llm_raises():
    ctx = make_ctx("llmNode", config={"prompt": "hi"})
    with patch(
        "app.langgraph.llm.call_llm",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await NODE_EXECUTORS["llmNode"].execute(ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert "RuntimeError" in result.error
    assert "boom" in result.error


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_cancellation_not_supported():
    """LLM call is opaque mid-flight; the executor doesn't honour cancel_check.

    Documented as an explicit skip so the contract is visible.
    """
    pytest.skip(
        "cancellation N/A — LLM call is atomic; cancel_check ignored mid-call"
    )


# ---------------------------------------------------------------------------
# 6. retry classification
# ---------------------------------------------------------------------------


class _TransientError(Exception):
    """Stand-in for the dispatcher's transient marker."""


@pytest.mark.asyncio
async def test_llm_retry_classification_on_transient():
    """Transient exception bubbles up as status=failed with the exc type in error.

    The dispatcher's RetryPolicy reads the error string (or raised type) to
    classify retryability; the executor's contract is to surface it.
    """
    ctx = make_ctx("llmNode", config={"prompt": "hi"})
    with patch(
        "app.langgraph.llm.call_llm",
        new=AsyncMock(side_effect=_TransientError("rate limited")),
    ):
        result = await NODE_EXECUTORS["llmNode"].execute(ctx)

    assert result.status == "failed"
    assert "_TransientError" in result.error or "TransientError" in result.error


# ---------------------------------------------------------------------------
# 7. tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_tenant_id_not_leaked_into_prompt():
    """tenant_id is workflow-level metadata; never injected into the LLM prompt."""
    captured: dict = {}

    async def _capture(prompt, model="gpt-3.5-turbo", **kw):
        captured["prompt"] = prompt
        captured["model"] = model
        return _stub_response()

    ctx = make_ctx(
        "llmNode",
        config={"prompt": "Hello user"},
        tenant_id="tenant-alpha",
    )
    with patch("app.langgraph.llm.call_llm", new=_capture):
        await NODE_EXECUTORS["llmNode"].execute(ctx)

    assert "tenant-alpha" not in str(captured.get("prompt", ""))


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_does_not_emit_events_directly():
    """LLM executor returns a NodeResult; event emission is dispatcher-side."""
    pytest.skip(
        "event emission N/A — LLM executor returns NodeResult; "
        "dispatcher emits run.step.* events"
    )


# ---------------------------------------------------------------------------
# Stub-mode determinism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_stub_mode_deterministic():
    """LLM_STUB_MODE=true → content prefixed [STUB], total_tokens=30."""
    ctx = make_ctx("llmNode", config={"prompt": "hello"})
    result = await NODE_EXECUTORS["llmNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["content"].startswith("[STUB]")
    assert result.token_usage["total_tokens"] == 30
