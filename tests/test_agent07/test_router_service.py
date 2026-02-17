"""Tests for ModelRouterService — routing, auth filtering, circuit breaker, providers, Vault creds, policy."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.router import (
    DecisionFactor,
    ModelProvider,
    ModelRegistryEntry,
    RoutingDecision,
    RoutingPolicy,
    RoutingRequest,
)
from app.services.router_service import (
    ModelRouterService,
    _CircuitBreaker,
    _score_model,
)


# ── Fixtures ────────────────────────────────────────────────────────


TENANT_ID = "tenant-router-test"


def _admin_user(**overrides: Any) -> AuthenticatedUser:
    defaults = dict(
        id=str(uuid4()),
        email="admin@example.com",
        tenant_id=TENANT_ID,
        roles=["admin"],
        permissions=[],
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _viewer_user(**overrides: Any) -> AuthenticatedUser:
    defaults = dict(
        id=str(uuid4()),
        email="viewer@example.com",
        tenant_id=TENANT_ID,
        roles=["viewer"],
        permissions=[],
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _make_model_entry(
    name: str = "gpt-4o",
    provider: str = "openai",
    cost_in: float = 2.5,
    cost_out: float = 10.0,
    latency: float = 400.0,
    classification: str = "general",
    capabilities: list[str] | None = None,
    health: str = "healthy",
    geo: str = "us",
    error_rate: float = 0.0,
) -> ModelRegistryEntry:
    uid = uuid4()
    return ModelRegistryEntry(
        id=uid,
        name=name,
        provider=provider,
        model_id=name,
        capabilities=capabilities or ["chat", "code"],
        cost_per_input_token=cost_in,
        cost_per_output_token=cost_out,
        avg_latency_ms=latency,
        data_classification=classification,
        health_status=health,
        error_rate=error_rate,
        is_active=True,
        config={"geo_residency": geo, "tenant_id": TENANT_ID},
    )


def _mock_session_returning(models: list[ModelRegistryEntry]) -> AsyncMock:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.all.return_value = models
    session.exec.return_value = result_mock
    return session


def _mock_secrets() -> AsyncMock:
    return AsyncMock()


# ── Route: optimal model selection ──────────────────────────────────


class TestRouteSelectsOptimalModel:
    """route() selects optimal model based on cost/latency/capability."""

    @pytest.mark.asyncio
    async def test_selects_cheapest_when_cost_weighted(self) -> None:
        cheap = _make_model_entry(name="cheap-model", cost_in=0.1, cost_out=0.3)
        expensive = _make_model_entry(name="expensive-model", cost_in=50.0, cost_out=80.0)
        session = _mock_session_returning([cheap, expensive])
        policy = RoutingPolicy(cost_weight=0.9, latency_weight=0.03, quality_weight=0.03, data_residency_weight=0.04)
        request = RoutingRequest(task_type="chat")

        with patch("app.services.router_service._load_routing_policy", return_value=policy), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(), request,
            )

        assert decision.selected_model == "cheap-model"
        assert decision.data_classification_met is True

    @pytest.mark.asyncio
    async def test_selects_fastest_when_latency_weighted(self) -> None:
        fast = _make_model_entry(name="fast-model", latency=50.0)
        slow = _make_model_entry(name="slow-model", latency=9000.0)
        session = _mock_session_returning([fast, slow])
        policy = RoutingPolicy(cost_weight=0.0, latency_weight=0.9, quality_weight=0.05, data_residency_weight=0.05)
        request = RoutingRequest(task_type="chat", latency_requirement="fast")

        with patch("app.services.router_service._load_routing_policy", return_value=policy), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(), request,
            )

        assert decision.selected_model == "fast-model"

    @pytest.mark.asyncio
    async def test_selects_most_capable_model(self) -> None:
        capable = _make_model_entry(name="capable", capabilities=["chat", "code", "vision", "function_calling", "embedding"])
        basic = _make_model_entry(name="basic", capabilities=["chat"])
        session = _mock_session_returning([capable, basic])
        policy = RoutingPolicy(cost_weight=0.0, latency_weight=0.0, quality_weight=1.0, data_residency_weight=0.0)
        request = RoutingRequest(task_type="chat")

        with patch("app.services.router_service._load_routing_policy", return_value=policy), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(), request,
            )

        assert decision.selected_model == "capable"

    @pytest.mark.asyncio
    async def test_returns_fallback_chain(self) -> None:
        m1 = _make_model_entry(name="primary", cost_in=0.1)
        m2 = _make_model_entry(name="fallback1", cost_in=1.0)
        m3 = _make_model_entry(name="fallback2", cost_in=5.0)
        session = _mock_session_returning([m1, m2, m3])

        with patch("app.services.router_service._load_routing_policy", return_value=RoutingPolicy()), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(),
                RoutingRequest(task_type="chat"),
            )

        assert len(decision.fallback_chain) >= 1

    @pytest.mark.asyncio
    async def test_no_candidates_returns_none(self) -> None:
        session = _mock_session_returning([])

        with patch("app.services.router_service._load_routing_policy", return_value=RoutingPolicy()):
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(),
                RoutingRequest(task_type="chat", data_classification="restricted"),
            )

        assert decision.selected_model == "none"
        assert decision.data_classification_met is False


# ── Auth-aware filtering ────────────────────────────────────────────


class TestAuthAwareFiltering:
    """Auth filtering: data classification, tenant allowlist, role restrictions."""

    @pytest.mark.asyncio
    async def test_filters_by_data_classification(self) -> None:
        general = _make_model_entry(name="general-model", classification="general")
        restricted = _make_model_entry(name="restricted-model", classification="restricted")
        session = _mock_session_returning([general, restricted])

        with patch("app.services.router_service._load_routing_policy", return_value=RoutingPolicy()), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(),
                RoutingRequest(task_type="chat", data_classification="restricted"),
            )

        assert decision.selected_model == "restricted-model"

    @pytest.mark.asyncio
    async def test_filters_by_required_capabilities(self) -> None:
        vision = _make_model_entry(name="vision-model", capabilities=["chat", "vision"])
        no_vision = _make_model_entry(name="no-vision", capabilities=["chat"])
        session = _mock_session_returning([vision, no_vision])

        with patch("app.services.router_service._load_routing_policy", return_value=RoutingPolicy()), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(),
                RoutingRequest(task_type="vision", required_capabilities=["vision"]),
            )

        assert decision.selected_model == "vision-model"

    @pytest.mark.asyncio
    async def test_filters_by_geo_residency(self) -> None:
        eu = _make_model_entry(name="eu-model", geo="eu")
        us = _make_model_entry(name="us-model", geo="us")
        session = _mock_session_returning([eu, us])

        with patch("app.services.router_service._load_routing_policy", return_value=RoutingPolicy()), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(),
                RoutingRequest(task_type="chat", geo_residency="eu"),
            )

        assert decision.selected_model == "eu-model"

    @pytest.mark.asyncio
    async def test_budget_limit_filters_expensive_models(self) -> None:
        cheap = _make_model_entry(name="cheap", cost_in=0.1, cost_out=0.1)
        expensive = _make_model_entry(name="expensive", cost_in=100.0, cost_out=100.0)
        session = _mock_session_returning([cheap, expensive])

        with patch("app.services.router_service._load_routing_policy", return_value=RoutingPolicy()), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, _mock_secrets(), TENANT_ID, _admin_user(),
                RoutingRequest(task_type="chat", budget_limit=0.1, input_tokens_estimate=500),
            )

        assert decision.selected_model == "cheap"


# ── Circuit Breaker ─────────────────────────────────────────────────


class TestCircuitBreaker:
    """Circuit breaker: 3 failures → open, skip provider, auto-reset."""

    def test_starts_closed(self) -> None:
        cb = _CircuitBreaker()
        assert cb.is_open("prov-1") is False
        assert cb.get_status("prov-1") == "closed"

    def test_opens_after_threshold_failures(self) -> None:
        cb = _CircuitBreaker()
        for _ in range(3):
            cb.record_failure("prov-1")
        assert cb.is_open("prov-1") is True
        assert cb.get_consecutive_failures("prov-1") == 3

    def test_success_resets_circuit(self) -> None:
        cb = _CircuitBreaker()
        for _ in range(3):
            cb.record_failure("prov-1")
        assert cb.is_open("prov-1") is True
        cb.record_success("prov-1")
        assert cb.is_open("prov-1") is False
        assert cb.get_consecutive_failures("prov-1") == 0

    def test_half_open_after_timeout(self) -> None:
        cb = _CircuitBreaker()
        cb.RESET_TIMEOUT_S = 0.0  # instant timeout for test
        for _ in range(3):
            cb.record_failure("prov-1")
        # After timeout expires, should transition to half_open
        assert cb.is_open("prov-1") is False
        assert cb.get_status("prov-1") == "half_open"


# ── Provider Registration & Listing ─────────────────────────────────


class TestProviderRegistration:
    """Provider registration and list_providers."""

    @pytest.mark.asyncio
    async def test_register_provider(self) -> None:
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        provider = ModelProvider(
            name="test-openai",
            api_type="openai",
            model_ids=["gpt-4o"],
            capabilities=["chat", "code"],
            cost_per_1k_tokens=2.5,
        )

        with patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            result = await ModelRouterService.register_provider(
                session, _mock_secrets(), TENANT_ID, _admin_user(), provider,
            )

        assert result.name == "test-openai"
        assert result.id is not None
        session.add.assert_called_once()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_providers(self) -> None:
        entry = _make_model_entry(name="listed-provider")
        session = _mock_session_returning([entry])

        providers, total = await ModelRouterService.list_providers(
            session, TENANT_ID, _admin_user(),
        )

        assert total == 1
        assert providers[0].name == "listed-provider"

    @pytest.mark.asyncio
    async def test_list_providers_pagination(self) -> None:
        entries = [_make_model_entry(name=f"prov-{i}") for i in range(5)]
        session = _mock_session_returning(entries)

        providers, total = await ModelRouterService.list_providers(
            session, TENANT_ID, _admin_user(), limit=2, offset=0,
        )

        assert total == 5
        assert len(providers) == 2


# ── Vault Credential Retrieval ──────────────────────────────────────


class TestVaultCredentialRetrieval:
    """Vault credential retrieval for provider API keys."""

    @pytest.mark.asyncio
    async def test_secrets_manager_injected_in_route(self) -> None:
        model = _make_model_entry(name="vault-model")
        session = _mock_session_returning([model])
        secrets = AsyncMock()

        with patch("app.services.router_service._load_routing_policy", return_value=RoutingPolicy()), \
             patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            decision = await ModelRouterService.route(
                session, secrets, TENANT_ID, _admin_user(),
                RoutingRequest(task_type="chat"),
            )

        assert decision.selected_model == "vault-model"

    @pytest.mark.asyncio
    async def test_secrets_manager_injected_in_register(self) -> None:
        session = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        secrets = AsyncMock()
        provider = ModelProvider(name="vault-test", api_type="openai")

        with patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            result = await ModelRouterService.register_provider(
                session, secrets, TENANT_ID, _admin_user(), provider,
            )

        assert result.name == "vault-test"


# ── Routing Policy Update ──────────────────────────────────────────


class TestRoutingPolicyUpdate:
    """Routing policy update."""

    @pytest.mark.asyncio
    async def test_update_creates_new_policy(self) -> None:
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.exec.return_value = result_mock
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        policy = RoutingPolicy(cost_weight=0.5, latency_weight=0.2, quality_weight=0.2, data_residency_weight=0.1)

        with patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            result = await ModelRouterService.update_routing_policy(
                session, TENANT_ID, _admin_user(), policy,
            )

        assert result.cost_weight == 0.5
        session.add.assert_called()
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_modifies_existing_policy(self) -> None:
        existing_rule = MagicMock()
        existing_rule.conditions = {"tenant_id": TENANT_ID}
        existing_rule.id = uuid4()

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = [existing_rule]
        session.exec.return_value = result_mock
        session.commit = AsyncMock()

        policy = RoutingPolicy(cost_weight=0.8, latency_weight=0.1, quality_weight=0.05, data_residency_weight=0.05)

        with patch("app.services.router_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            result = await ModelRouterService.update_routing_policy(
                session, TENANT_ID, _admin_user(), policy,
            )

        assert result.cost_weight == 0.8
        assert existing_rule.weight_cost == 0.8


# ── Scoring helper ──────────────────────────────────────────────────


class TestScoreModel:
    """Unit tests for _score_model internal helper."""

    def test_score_returns_factors(self) -> None:
        model = _make_model_entry()
        request = RoutingRequest(task_type="chat")
        policy = RoutingPolicy()
        score, factors = _score_model(model, request, policy)
        assert isinstance(score, float)
        assert len(factors) == 4
        factor_names = {f.factor for f in factors}
        assert factor_names == {"cost", "latency", "quality", "data_residency"}

    def test_degraded_health_penalises_score(self) -> None:
        healthy = _make_model_entry(name="healthy", health="healthy")
        degraded = _make_model_entry(name="degraded", health="degraded")
        request = RoutingRequest(task_type="chat")
        policy = RoutingPolicy()
        h_score, _ = _score_model(healthy, request, policy)
        d_score, _ = _score_model(degraded, request, policy)
        assert d_score < h_score
