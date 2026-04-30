"""embeddingNode contract tests — Phase 3 / WS9 (Executor Workstream 1).

Coverage dimensions (mirrors test_llm_node_contract.py):

1. input schema       — missing text → ``status="failed"`` (ValueError-shaped).
2. config defaults    — model defaults to ``text-embedding-3-small`` when omitted.
3. config override    — ``config["model"]`` is honoured when present.
4. output schema      — embedding vector + dimensions; token_usage + cost_usd
                        populated; latency reported.
5. stub determinism   — same (text, model) yields the same vector across calls.
6. stub variability   — different text under same model yields different vector.
7. retry classification — ``call_embedding`` raises → status="failed", error
                          string names the exception class so the dispatcher's
                          ``RetryPolicy`` can classify by class name.
8. token usage        — populated on the success path.
9. cost_usd           — populated on the success path.
10. tenant isolation  — N/A: embeddings have no DB writes; tenant_id is not
                        forwarded into the embedding payload.
11. registry          — embeddingNode is classified BETA in NODE_STATUS.
12. production gate   — assert_node_runnable does not raise after promotion.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

# Tests run in stub mode by default so they are deterministic regardless of
# whether the host has provider credentials. The package conftest also sets
# this; the duplicate ``setdefault`` is defensive when the file is run alone.
os.environ.setdefault("LLM_STUB_MODE", "true")

from app.langgraph.embeddings import EmbeddingResponse  # noqa: E402
from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from app.services.node_executors._stub_block import assert_node_runnable  # noqa: E402
from app.services.node_executors.status_registry import (  # noqa: E402
    NODE_STATUS,
    NodeStatus,
)
from tests.test_node_executors import make_ctx  # noqa: E402


def _fake_embedding_response(
    *,
    dimensions: int = 1536,
    cost: float = 0.00002,
    model: str = "text-embedding-3-small",
) -> EmbeddingResponse:
    return EmbeddingResponse(
        vector=[0.1] * dimensions,
        dimensions=dimensions,
        prompt_tokens=4,
        total_tokens=4,
        cost_usd=cost,
        model_used=model,
        latency_ms=2.5,
    )


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_input_schema_missing_text_returns_failed():
    """No text in config or inputs → status=failed with a ValueError-shaped error."""
    ctx = make_ctx("embeddingNode", config={"model": "text-embedding-3-small"})
    result = await NODE_EXECUTORS["embeddingNode"].execute(ctx)
    assert result.status == "failed"
    assert result.error is not None
    assert "ValueError" in result.error
    assert "text" in result.error.lower()


# ---------------------------------------------------------------------------
# 2. config defaults
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_model_used_when_config_omits():
    """When config has no ``model``, the default is text-embedding-3-small."""
    captured: dict = {}

    async def _capture(*, text, model, timeout_s, max_retries, metadata=None):
        captured["model"] = model
        captured["text"] = text
        return _fake_embedding_response(model=model)

    ctx = make_ctx("embeddingNode", config={"text": "hello"})
    with patch("app.langgraph.embeddings.call_embedding", new=_capture):
        result = await NODE_EXECUTORS["embeddingNode"].execute(ctx)

    assert result.status == "completed"
    assert captured["model"] == "text-embedding-3-small"
    assert captured["text"] == "hello"


# ---------------------------------------------------------------------------
# 3. config override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_model_override_used_when_present():
    """``config['model']`` is honoured by the executor."""
    captured: dict = {}

    async def _capture(*, text, model, timeout_s, max_retries, metadata=None):
        captured["model"] = model
        return _fake_embedding_response(model=model)

    ctx = make_ctx(
        "embeddingNode",
        config={"text": "hi", "model": "voyage-3"},
    )
    with patch("app.langgraph.embeddings.call_embedding", new=_capture):
        result = await NODE_EXECUTORS["embeddingNode"].execute(ctx)

    assert result.status == "completed"
    assert captured["model"] == "voyage-3"


# ---------------------------------------------------------------------------
# 4. output schema (success path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_returns_vector_with_correct_dimensions():
    """LLM_STUB_MODE=true → status=completed; embedding has the expected shape."""
    ctx = make_ctx(
        "embeddingNode",
        config={"text": "hello world", "model": "text-embedding-3-small"},
    )
    result = await NODE_EXECUTORS["embeddingNode"].execute(ctx)

    assert result.status == "completed"
    assert isinstance(result.output["embedding"], list)
    assert len(result.output["embedding"]) == 1536
    assert result.output["dimensions"] == 1536
    assert result.output["model"].endswith("-stub")
    assert "token_usage" in result.output
    assert {"prompt", "total"} <= set(result.output["token_usage"].keys())
    assert "cost_usd" in result.output
    assert "latency_ms" in result.output
    assert result.output.get("_stub") is True
    assert isinstance(result.token_usage, dict)
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(
        result.token_usage.keys()
    )


# ---------------------------------------------------------------------------
# 5. stub determinism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_mode_returns_deterministic_vector_for_same_input():
    """Two calls with identical (text, model) produce identical vectors."""
    ctx = make_ctx(
        "embeddingNode",
        config={"text": "deterministic", "model": "text-embedding-3-small"},
    )
    r1 = await NODE_EXECUTORS["embeddingNode"].execute(ctx)
    r2 = await NODE_EXECUTORS["embeddingNode"].execute(ctx)

    assert r1.status == "completed"
    assert r2.status == "completed"
    assert r1.output["embedding"] == r2.output["embedding"]


# ---------------------------------------------------------------------------
# 6. stub variability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stub_mode_returns_different_vector_for_different_text():
    """Different text under the same model produces a different vector."""
    ctx_a = make_ctx(
        "embeddingNode",
        config={"text": "alpha", "model": "text-embedding-3-small"},
    )
    ctx_b = make_ctx(
        "embeddingNode",
        config={"text": "beta", "model": "text-embedding-3-small"},
    )
    ra = await NODE_EXECUTORS["embeddingNode"].execute(ctx_a)
    rb = await NODE_EXECUTORS["embeddingNode"].execute(ctx_b)

    assert ra.status == "completed"
    assert rb.status == "completed"
    assert ra.output["embedding"] != rb.output["embedding"]


# ---------------------------------------------------------------------------
# 7. retry classification
# ---------------------------------------------------------------------------


class _TransientEmbeddingError(Exception):
    """Stand-in for the dispatcher's transient marker on the embedding path."""


@pytest.mark.asyncio
async def test_failure_propagates_error_class_name_for_retry_classification():
    """``call_embedding`` raises → status=failed; error names the exc class."""
    ctx = make_ctx(
        "embeddingNode",
        config={"text": "hi", "model": "text-embedding-3-small"},
    )
    with patch(
        "app.langgraph.embeddings.call_embedding",
        new=AsyncMock(side_effect=_TransientEmbeddingError("rate limited")),
    ):
        result = await NODE_EXECUTORS["embeddingNode"].execute(ctx)

    assert result.status == "failed"
    assert result.error is not None
    assert "_TransientEmbeddingError" in result.error or (
        "TransientEmbeddingError" in result.error
    )


# ---------------------------------------------------------------------------
# 8. token usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_usage_populated_in_output():
    """token_usage dict + NodeResult.token_usage carry the prompt/total counts."""
    fake = _fake_embedding_response()

    with patch(
        "app.langgraph.embeddings.call_embedding",
        new=AsyncMock(return_value=fake),
    ):
        ctx = make_ctx("embeddingNode", config={"text": "hi"})
        result = await NODE_EXECUTORS["embeddingNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["token_usage"]["prompt"] == fake.prompt_tokens
    assert result.output["token_usage"]["total"] == fake.total_tokens
    assert result.token_usage is not None
    assert result.token_usage["prompt_tokens"] == fake.prompt_tokens
    assert result.token_usage["total_tokens"] == fake.total_tokens


# ---------------------------------------------------------------------------
# 9. cost_usd
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_usd_populated_in_output():
    """cost_usd is forwarded from EmbeddingResponse onto the NodeResult."""
    fake = _fake_embedding_response(cost=0.000123)

    with patch(
        "app.langgraph.embeddings.call_embedding",
        new=AsyncMock(return_value=fake),
    ):
        ctx = make_ctx("embeddingNode", config={"text": "hi"})
        result = await NODE_EXECUTORS["embeddingNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["cost_usd"] == 0.000123
    assert result.cost_usd == 0.000123


# ---------------------------------------------------------------------------
# 10. tenant isolation (N/A — embeddings have no DB writes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_isolation_no_cross_call():
    """Embeddings have no per-tenant routing today; tenant_id is not leaked.

    Documented as an explicit assertion rather than a skip so the contract
    stays visible even if isolation semantics change later.
    """
    captured: dict = {}

    async def _capture(*, text, model, timeout_s, max_retries, metadata=None):
        captured["text"] = text
        captured["metadata"] = dict(metadata or {})
        return _fake_embedding_response()

    ctx = make_ctx(
        "embeddingNode",
        config={"text": "no leak"},
        tenant_id="tenant-alpha",
    )
    with patch("app.langgraph.embeddings.call_embedding", new=_capture):
        result = await NODE_EXECUTORS["embeddingNode"].execute(ctx)

    assert result.status == "completed"
    # tenant_id is not part of the embedding input or surfaced metadata.
    assert "tenant-alpha" not in captured["text"]
    assert "tenant-alpha" not in str(captured["metadata"])


# ---------------------------------------------------------------------------
# 11. registry classification
# ---------------------------------------------------------------------------


def test_executor_registered_with_beta_status():
    """embeddingNode is registered AND classified BETA — production-runnable."""
    assert "embeddingNode" in NODE_EXECUTORS
    assert NODE_STATUS["embeddingNode"] is NodeStatus.BETA


# ---------------------------------------------------------------------------
# 12. production gate
# ---------------------------------------------------------------------------


def test_executor_runs_in_production_env_after_promotion():
    """assert_node_runnable does not raise for embeddingNode in ARCHON_ENV=production."""
    # No need to actually mutate the environment — pass env explicitly so the
    # check is hermetic.
    assert_node_runnable("embeddingNode", env="production")
    assert_node_runnable("embeddingNode", env="staging")
