"""Unit tests for ``app.langgraph.embeddings`` — Phase 3 / WS9.

Covered:

1. Stub-mode determinism — same (text, model) → same vector across calls.
2. Stub-mode L2 normalisation — every synthesised vector has unit norm.
3. Stub-mode known-model dimensionality — vector length matches the table.
4. Stub-mode unknown-model dimensionality — falls back to 1536.
5. Real-mode dispatches to ``litellm.aembedding`` with the expected kwargs.
6. Real-mode propagates non-transient exceptions unchanged.
7. Real-mode retries on TimeoutError up to ``max_retries`` and ultimately
   returns on success.
8. Real-mode response includes cost + latency + token usage.
"""

from __future__ import annotations

import math
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Tests in this module flip stub mode on/off explicitly. We start clean.
@pytest.fixture(autouse=True)
def _isolate_stub_env(monkeypatch: pytest.MonkeyPatch):
    """Each test owns its LLM_STUB_MODE state."""
    monkeypatch.delenv("LLM_STUB_MODE", raising=False)
    yield


def _import_module():
    # Imported lazily so monkeypatched env vars apply to ``_is_stub_mode``.
    from app.langgraph import embeddings  # noqa: PLC0415

    return embeddings


# ---------------------------------------------------------------------------
# 1. Stub-mode determinism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_embedding_stub_mode_returns_deterministic_vector(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    mod = _import_module()

    r1 = await mod.call_embedding(text="hello", model="text-embedding-3-small")
    r2 = await mod.call_embedding(text="hello", model="text-embedding-3-small")

    assert r1.vector == r2.vector
    assert r1.dimensions == r2.dimensions
    assert r1.cost_usd == 0.0
    assert r1.model_used.endswith("-stub")


# ---------------------------------------------------------------------------
# 2. Stub-mode L2 normalisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_embedding_stub_mode_vector_is_l2_normalised(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    mod = _import_module()

    response = await mod.call_embedding(
        text="normalise me", model="text-embedding-3-small"
    )

    norm = math.sqrt(sum(x * x for x in response.vector))
    assert response.vector  # not empty
    assert norm == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 3. Stub-mode known-model dimensionality
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,expected_dims",
    [
        ("text-embedding-3-small", 1536),
        ("text-embedding-3-large", 3072),
        ("text-embedding-ada-002", 1536),
        ("voyage-3", 1024),
    ],
)
async def test_call_embedding_stub_mode_dimensions_match_known_model(
    monkeypatch: pytest.MonkeyPatch, model: str, expected_dims: int
):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    mod = _import_module()

    response = await mod.call_embedding(text="hi", model=model)

    assert response.dimensions == expected_dims
    assert len(response.vector) == expected_dims


# ---------------------------------------------------------------------------
# 4. Stub-mode unknown-model fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_embedding_stub_mode_dimensions_default_when_unknown_model(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LLM_STUB_MODE", "true")
    mod = _import_module()

    response = await mod.call_embedding(text="hi", model="some-future-model-xyz")

    assert response.dimensions == 1536
    assert len(response.vector) == 1536


# ---------------------------------------------------------------------------
# 5. Real-mode dispatches to litellm.aembedding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_embedding_real_mode_calls_litellm_aembedding(
    monkeypatch: pytest.MonkeyPatch,
):
    """Real path forwards model + input to ``litellm.aembedding``."""
    # LLM_STUB_MODE must NOT be 'true' so the real path runs.
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    mod = _import_module()

    # Build a litellm-shaped response object.
    fake_response = SimpleNamespace(
        data=[{"embedding": [0.1, 0.2, 0.3]}],
        usage=SimpleNamespace(prompt_tokens=2, total_tokens=2),
        model="text-embedding-3-small",
    )

    fake_aembedding = AsyncMock(return_value=fake_response)

    fake_litellm = MagicMock()
    fake_litellm.aembedding = fake_aembedding
    fake_litellm.completion_cost = MagicMock(return_value=0.000003)

    with patch.dict("sys.modules", {"litellm": fake_litellm}):
        result = await mod.call_embedding(
            text="hello",
            model="text-embedding-3-small",
            timeout_s=12.0,
            max_retries=0,
        )

    fake_aembedding.assert_awaited_once()
    kwargs = fake_aembedding.await_args.kwargs
    assert kwargs["model"] == "text-embedding-3-small"
    assert kwargs["input"] == ["hello"]
    assert kwargs["timeout"] == 12.0
    assert result.vector == [0.1, 0.2, 0.3]
    assert result.dimensions == 3
    assert result.prompt_tokens == 2
    assert result.total_tokens == 2
    assert result.cost_usd == pytest.approx(0.000003)


# ---------------------------------------------------------------------------
# 6. Real-mode propagates non-transient exceptions
# ---------------------------------------------------------------------------


class _PermanentEmbeddingError(Exception):
    """Stand-in for a non-transient provider error (e.g. auth failure)."""


@pytest.mark.asyncio
async def test_call_embedding_real_mode_propagates_litellm_exceptions(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    mod = _import_module()

    fake_litellm = MagicMock()
    fake_litellm.aembedding = AsyncMock(
        side_effect=_PermanentEmbeddingError("invalid api key")
    )

    with patch.dict("sys.modules", {"litellm": fake_litellm}):
        with pytest.raises(_PermanentEmbeddingError):
            await mod.call_embedding(
                text="hi",
                model="text-embedding-3-small",
                max_retries=2,
            )

    # No retry should fire for non-transient exceptions — exactly one call.
    fake_litellm.aembedding.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7. Real-mode retries on TimeoutError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_embedding_retries_on_timeout(monkeypatch: pytest.MonkeyPatch):
    """Two TimeoutErrors then success → final result returned, 3 attempts total."""
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    mod = _import_module()

    success_response = SimpleNamespace(
        data=[{"embedding": [0.0] * 4}],
        usage={"prompt_tokens": 1, "total_tokens": 1},
        model="text-embedding-3-small",
    )

    fake_aembedding = AsyncMock(
        side_effect=[
            TimeoutError("timed out"),
            TimeoutError("timed out again"),
            success_response,
        ]
    )

    fake_litellm = MagicMock()
    fake_litellm.aembedding = fake_aembedding
    fake_litellm.completion_cost = MagicMock(return_value=0.0)

    # Skip the actual sleep so the test stays fast.
    with patch.dict("sys.modules", {"litellm": fake_litellm}):
        with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
            result = await mod.call_embedding(
                text="hi",
                model="text-embedding-3-small",
                max_retries=2,
            )

    assert result.dimensions == 4
    assert fake_aembedding.await_count == 3


# ---------------------------------------------------------------------------
# 8. Real-mode response includes cost + latency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_embedding_response_includes_cost_and_latency(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LLM_STUB_MODE", "false")
    mod = _import_module()

    fake_response = SimpleNamespace(
        data=[{"embedding": [0.5, 0.5]}],
        usage={"prompt_tokens": 3, "total_tokens": 3},
        model="text-embedding-3-small",
    )
    fake_litellm = MagicMock()
    fake_litellm.aembedding = AsyncMock(return_value=fake_response)
    fake_litellm.completion_cost = MagicMock(return_value=0.0001)

    with patch.dict("sys.modules", {"litellm": fake_litellm}):
        result = await mod.call_embedding(text="hello", model="text-embedding-3-small")

    assert result.cost_usd == pytest.approx(0.0001)
    assert result.latency_ms >= 0.0
    assert result.prompt_tokens == 3
    assert result.total_tokens == 3
    assert result.model_used == "text-embedding-3-small"
