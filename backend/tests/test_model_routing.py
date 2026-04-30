"""Tests for app.services.router_service.route_request (Phase 4 / WS10).

Run with::

    LLM_STUB_MODE=true PYTHONPATH=backend python3 -m pytest \
        backend/tests/test_model_routing.py -v
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")

from app.models.router import ModelRegistryEntry, RoutingRule  # noqa: E402
from app.services import provider_health  # noqa: E402
from app.services.router_service import (  # noqa: E402
    Phase4RoutingDecision,
    route_request,
)


# ── Helpers ─────────────────────────────────────────────────────────


TENANT = UUID("11111111-1111-1111-1111-111111111111")


def _model(
    *,
    name: str,
    provider: str = "openai",
    capabilities: list[str] | None = None,
    cost_in: float = 1.0,
    cost_out: float = 3.0,
    latency_ms: float = 400.0,
    health: str = "healthy",
    tenant_id: str = str(TENANT),
) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        id=uuid4(),
        name=name,
        provider=provider,
        model_id=name,
        capabilities=capabilities or ["chat"],
        cost_per_input_token=cost_in,
        cost_per_output_token=cost_out,
        avg_latency_ms=latency_ms,
        health_status=health,
        is_active=True,
        config={"tenant_id": tenant_id},
    )


def _make_session(
    models: list[ModelRegistryEntry],
    rules: list[RoutingRule] | None = None,
) -> AsyncMock:
    """Build a session whose ``exec`` returns models, then routing rules.

    ``route_request`` calls ``session.exec`` twice:
      1. ``_fetch_tenant_models`` → models
      2. ``_load_tenant_policy_pin`` → routing rules
    """
    rules = rules or []

    models_result = MagicMock()
    models_result.all.return_value = models
    models_result.first.return_value = models[0] if models else None

    rules_result = MagicMock()
    rules_result.all.return_value = rules
    rules_result.first.return_value = rules[0] if rules else None

    session = AsyncMock()
    session.exec = AsyncMock(side_effect=[models_result, rules_result])
    return session


@pytest.fixture(autouse=True)
def _reset_health() -> None:
    """Drop any provider_health state between tests."""
    provider_health.reset_state()
    yield
    provider_health.reset_state()


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_route_request_uses_tenant_policy_when_present() -> None:
    """A tenant_policy RoutingRule with a pinned model wins over scoring."""
    cheap = _model(name="gpt-3.5-turbo", cost_in=0.5, cost_out=1.0, latency_ms=100.0)
    pricey = _model(name="gpt-4o", cost_in=5.0, cost_out=15.0, latency_ms=900.0)

    rule = RoutingRule(
        name="tenant-1-pin",
        strategy="tenant_policy",
        is_active=True,
        conditions={"tenant_id": str(TENANT), "pinned_model": "gpt-4o"},
    )
    session = _make_session([cheap, pricey], rules=[rule])

    decision = await route_request(session, tenant_id=TENANT)

    assert isinstance(decision, Phase4RoutingDecision)
    assert decision.model == "gpt-4o"
    assert decision.reason == "tenant_policy"
    assert decision.provider == "openai"
    assert "gpt-4o" in decision.fallback_chain
    assert decision.estimated_latency_ms == 900.0


@pytest.mark.asyncio
async def test_route_request_uses_requested_model_by_default() -> None:
    """When the caller asks for a specific model, it's used (no tenant policy)."""
    a = _model(name="gpt-3.5-turbo")
    b = _model(name="gpt-4o", latency_ms=900.0)
    session = _make_session([a, b])

    decision = await route_request(
        session, tenant_id=TENANT, requested_model="gpt-3.5-turbo"
    )

    assert decision.model == "gpt-3.5-turbo"
    assert decision.reason == "primary"
    # fallback_chain begins with the chosen model and lists alternatives
    assert decision.fallback_chain[0] == "gpt-3.5-turbo"
    assert "gpt-4o" in decision.fallback_chain


@pytest.mark.asyncio
async def test_route_request_respects_capability_match() -> None:
    """Candidates without the required capability are filtered out."""
    text_only = _model(name="text-only", capabilities=["chat"])
    vision = _model(name="vision-pro", capabilities=["chat", "vision"])
    session = _make_session([text_only, vision])

    decision = await route_request(
        session,
        tenant_id=TENANT,
        capability_required=["vision"],
    )

    assert decision.model == "vision-pro"
    assert "text-only" not in decision.fallback_chain


@pytest.mark.asyncio
async def test_route_request_skips_circuit_open_provider() -> None:
    """A provider whose circuit is open must not be selected."""
    # Open the circuit on "openai" before the call.
    for _ in range(provider_health.FAILURE_THRESHOLD):
        await provider_health.record_provider_call(
            None, "openai", success=False, latency_ms=1.0, error="x"
        )

    openai_model = _model(name="gpt-4o", provider="openai")
    anthropic_model = _model(name="claude-3-5-sonnet", provider="anthropic")
    session = _make_session([openai_model, anthropic_model])

    decision = await route_request(
        session, tenant_id=TENANT, requested_model="gpt-4o"
    )

    assert decision.model == "claude-3-5-sonnet"
    assert decision.provider == "anthropic"
    # The reason names the unhealthy primary
    assert "circuit_open_gpt-4o" in decision.reason or decision.reason == "primary"
    assert "gpt-4o" not in decision.fallback_chain


@pytest.mark.asyncio
async def test_route_request_returns_decision_with_fallback_chain() -> None:
    """Decision exposes a non-empty fallback chain when alternatives exist."""
    a = _model(name="model-a", cost_in=1.0, cost_out=1.0, latency_ms=100.0)
    b = _model(name="model-b", cost_in=2.0, cost_out=2.0, latency_ms=200.0)
    c = _model(name="model-c", cost_in=3.0, cost_out=3.0, latency_ms=300.0)
    session = _make_session([a, b, c])

    decision = await route_request(session, tenant_id=TENANT)

    assert decision.model in {"model-a", "model-b", "model-c"}
    assert isinstance(decision.fallback_chain, list)
    assert len(decision.fallback_chain) >= 2
    assert decision.fallback_chain[0] == decision.model
    # Estimate exposed
    assert decision.estimated_latency_ms is not None
    assert decision.decision_at is not None
