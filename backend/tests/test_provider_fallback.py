"""Tests for app.langgraph.llm.call_llm_routed (Phase 4 / WS10).

Run with::

    LLM_STUB_MODE=true PYTHONPATH=backend python3 -m pytest \
        backend/tests/test_provider_fallback.py -v
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# Stub mode is forced off for fallback tests so we exercise the real
# routed path; individual tests opt back into stub mode where appropriate.

from app.langgraph.llm import LLMResponse  # noqa: E402
from app.models.router import ModelRegistryEntry  # noqa: E402
from app.services import provider_health  # noqa: E402
from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from app.services.router_service import Phase4RoutingDecision  # noqa: E402

from tests.test_node_executors import make_ctx  # noqa: E402


# ── Helpers ─────────────────────────────────────────────────────────


TENANT = UUID("22222222-2222-2222-2222-222222222222")


def _llm_response(content: str = "ok", model: str = "gpt-3.5-turbo") -> LLMResponse:
    return LLMResponse(
        content=content,
        prompt_tokens=10,
        completion_tokens=20,
        total_tokens=30,
        cost_usd=0.001,
        model_used=model,
        latency_ms=12.0,
    )


def _model(
    *,
    name: str,
    provider: str,
    capabilities: list[str] | None = None,
    tenant_id: str = str(TENANT),
) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        id=uuid4(),
        name=name,
        provider=provider,
        model_id=name,
        capabilities=capabilities or ["chat"],
        cost_per_input_token=1.0,
        cost_per_output_token=3.0,
        avg_latency_ms=400.0,
        health_status="healthy",
        is_active=True,
        config={"tenant_id": tenant_id},
    )


def _make_session(models: list[ModelRegistryEntry]) -> AsyncMock:
    """Mock session: first exec → models, second exec → no rules."""
    models_result = MagicMock()
    models_result.all.return_value = models
    rules_result = MagicMock()
    rules_result.all.return_value = []
    session = AsyncMock()
    session.exec = AsyncMock(side_effect=[models_result, rules_result])
    return session


@pytest.fixture(autouse=True)
def _reset_health() -> None:
    provider_health.reset_state()
    # Force non-stub mode for tests in this file unless explicitly overridden.
    prev = os.environ.get("LLM_STUB_MODE")
    os.environ["LLM_STUB_MODE"] = "false"
    yield
    provider_health.reset_state()
    if prev is None:
        os.environ.pop("LLM_STUB_MODE", None)
    else:
        os.environ["LLM_STUB_MODE"] = prev


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_routed_falls_back_when_primary_provider_fails() -> None:
    """Primary provider raises → fallback provider is invoked, decision reason updated."""
    from app.langgraph.llm import call_llm_routed  # noqa: PLC0415

    primary = _model(name="gpt-4o", provider="openai")
    fallback = _model(name="claude-3-5-sonnet", provider="anthropic")
    session = _make_session([primary, fallback])

    calls: list[str] = []

    async def _fake_call_llm(messages, model="", **kw):  # noqa: ANN001
        calls.append(model)
        if model == "gpt-4o":
            raise RuntimeError("upstream 503")
        return _llm_response("recovered", model=model)

    with patch("app.langgraph.llm.call_llm", new=_fake_call_llm):
        response, decision = await call_llm_routed(
            tenant_id=TENANT,
            messages=[{"role": "user", "content": "hi"}],
            requested_model="gpt-4o",
            session=session,
        )

    assert response.content == "recovered"
    assert calls == ["gpt-4o", "claude-3-5-sonnet"]
    assert decision.model == "claude-3-5-sonnet"
    assert decision.provider == "anthropic"
    assert decision.reason.startswith("fallback_after_")
    assert "openai" in decision.reason


@pytest.mark.asyncio
async def test_call_llm_routed_records_provider_health_on_failure() -> None:
    """A failed provider call is recorded into provider_health."""
    from app.langgraph.llm import call_llm_routed  # noqa: PLC0415

    primary = _model(name="gpt-4o", provider="openai")
    fallback = _model(name="claude-3-5-sonnet", provider="anthropic")
    session = _make_session([primary, fallback])

    async def _fake_call_llm(messages, model="", **kw):  # noqa: ANN001
        if model == "gpt-4o":
            raise RuntimeError("rate limit")
        return _llm_response("ok", model=model)

    with patch("app.langgraph.llm.call_llm", new=_fake_call_llm):
        await call_llm_routed(
            tenant_id=TENANT,
            messages=[{"role": "user", "content": "x"}],
            requested_model="gpt-4o",
            session=session,
        )

    openai_health = await provider_health.check_provider(None, "openai")
    anthropic_health = await provider_health.check_provider(None, "anthropic")

    # openai had a failure recorded (error_rate > 0)
    assert openai_health.error_rate > 0.0
    assert openai_health.last_error is not None and "rate limit" in openai_health.last_error
    # anthropic had a successful call recorded (no failures)
    assert anthropic_health.error_rate == 0.0


@pytest.mark.asyncio
async def test_call_llm_routed_returns_routing_decision_in_response() -> None:
    """The routed call returns a Phase4RoutingDecision alongside the LLMResponse."""
    from app.langgraph.llm import call_llm_routed  # noqa: PLC0415

    only = _model(name="gpt-4o", provider="openai")
    session = _make_session([only])

    async def _fake_call_llm(messages, model="", **kw):  # noqa: ANN001
        return _llm_response("hi", model=model)

    with patch("app.langgraph.llm.call_llm", new=_fake_call_llm):
        response, decision = await call_llm_routed(
            tenant_id=TENANT,
            messages=[{"role": "user", "content": "yo"}],
            requested_model="gpt-4o",
            session=session,
        )

    assert isinstance(decision, Phase4RoutingDecision)
    assert decision.model == "gpt-4o"
    assert decision.provider == "openai"
    assert decision.reason == "primary"
    assert decision.fallback_chain[0] == "gpt-4o"
    assert response.model_used == "gpt-4o"


@pytest.mark.asyncio
async def test_llm_node_output_includes_routing_metadata() -> None:
    """llmNode output dict carries the routing metadata when tenant_id is a UUID."""
    from app.langgraph import llm as llm_mod  # noqa: PLC0415

    only = _model(name="gpt-4o", provider="openai")
    session = _make_session([only])

    async def _fake_call_llm(messages, model="", **kw):  # noqa: ANN001
        return _llm_response("hello", model=model)

    ctx = make_ctx(
        "llmNode",
        config={"prompt": "Hi", "model": "gpt-4o"},
        tenant_id=str(TENANT),
        db_session=session,
    )

    with patch.object(llm_mod, "call_llm", new=_fake_call_llm):
        result = await NODE_EXECUTORS["llmNode"].execute(ctx)

    assert result.status == "completed"
    assert "routing" in result.output
    routing = result.output["routing"]
    assert routing["model"] == "gpt-4o"
    assert routing["provider"] == "openai"
    assert routing["reason"] == "primary"
    assert "gpt-4o" in routing["fallback_chain"]


@pytest.mark.asyncio
async def test_call_llm_stub_mode_returns_synthetic_routing_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM_STUB_MODE=true bypasses providers; decision.reason == 'stub_mode'."""
    from app.langgraph.llm import call_llm_routed  # noqa: PLC0415

    monkeypatch.setenv("LLM_STUB_MODE", "true")

    response, decision = await call_llm_routed(
        tenant_id=TENANT,
        messages=[{"role": "user", "content": "hello"}],
        requested_model="gpt-3.5-turbo",
        session=None,                 # no DB needed in stub mode
    )

    assert response.content.startswith("[STUB]")
    assert decision.reason == "stub_mode"
    assert decision.provider == "stub"
    assert decision.model == "gpt-3.5-turbo"
    assert decision.fallback_chain == ["gpt-3.5-turbo"]
    assert decision.estimated_cost_usd == 0.0
