"""Tests for ModelRouterService — routing, circuit breaker, tenant isolation."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.router import (
    ModelRegistryEntry,
    ModelProvider,
    RoutingPolicy,
    RoutingRequest,
    RoutingRule,
    FallbackChainConfig,
)
from app.services.router_service import (
    ModelRouterService,
    _CircuitBreaker,
    _score_model,
    _match_visual_conditions,
    _eval_operator,
    _find_model_by_id,
    _build_alternatives,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _admin_user(tenant_id: str = "tenant-1") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=str(uuid4()),
        email="admin@test.com",
        tenant_id=tenant_id,
        roles=["admin"],
    )


def _make_model(
    *,
    tenant_id: str = "tenant-1",
    name: str = "gpt-4o",
    provider: str = "openai",
    capabilities: list[str] | None = None,
    data_classification: str = "general",
    cost_per_input_token: float = 2.5,
    cost_per_output_token: float = 10.0,
    avg_latency_ms: float = 500.0,
    health_status: str = "healthy",
    is_active: bool = True,
    geo_residency: str = "us",
) -> ModelRegistryEntry:
    return ModelRegistryEntry(
        id=uuid4(),
        name=name,
        provider=provider,
        model_id=name,
        capabilities=capabilities or ["chat", "completion"],
        data_classification=data_classification,
        cost_per_input_token=cost_per_input_token,
        cost_per_output_token=cost_per_output_token,
        avg_latency_ms=avg_latency_ms,
        health_status=health_status,
        is_active=is_active,
        config={"geo_residency": geo_residency, "tenant_id": tenant_id},
    )


def _make_request(
    task_type: str = "chat",
    data_classification: str = "general",
    latency_requirement: str = "medium",
    required_capabilities: list[str] | None = None,
    geo_residency: str | None = None,
    budget_limit: float | None = None,
    input_tokens_estimate: int = 1000,
) -> RoutingRequest:
    return RoutingRequest(
        task_type=task_type,
        data_classification=data_classification,
        latency_requirement=latency_requirement,
        required_capabilities=required_capabilities or [],
        geo_residency=geo_residency,
        budget_limit=budget_limit,
        input_tokens_estimate=input_tokens_estimate,
    )


# ── Circuit Breaker Tests ────────────────────────────────────────────────────


class TestCircuitBreaker:
    """Test the _CircuitBreaker in-memory state machine."""

    def test_initial_state_is_closed(self):
        cb = _CircuitBreaker()
        assert cb.get_status("p1") == "closed"
        assert cb.is_open("p1") is False

    def test_opens_after_failure_threshold(self):
        cb = _CircuitBreaker()
        for _ in range(_CircuitBreaker.FAILURE_THRESHOLD):
            cb.record_failure("p1")
        assert cb.is_open("p1") is True
        assert cb.get_status("p1") == "open"

    def test_stays_closed_below_threshold(self):
        cb = _CircuitBreaker()
        for _ in range(_CircuitBreaker.FAILURE_THRESHOLD - 1):
            cb.record_failure("p1")
        assert cb.is_open("p1") is False
        assert cb.get_status("p1") == "closed"

    def test_success_resets_circuit_breaker(self):
        cb = _CircuitBreaker()
        for _ in range(_CircuitBreaker.FAILURE_THRESHOLD):
            cb.record_failure("p1")
        assert cb.is_open("p1") is True
        cb.record_success("p1")
        assert cb.is_open("p1") is False
        assert cb.get_consecutive_failures("p1") == 0

    def test_half_open_after_reset_timeout(self):
        cb = _CircuitBreaker()
        for _ in range(_CircuitBreaker.FAILURE_THRESHOLD):
            cb.record_failure("p1")
        # Fake last failure far in the past
        cb._last_failure["p1"] = time.monotonic() - (
            _CircuitBreaker.RESET_TIMEOUT_S + 5
        )
        assert cb.is_open("p1") is False
        assert cb.get_status("p1") == "half_open"

    def test_consecutive_failure_count(self):
        cb = _CircuitBreaker()
        cb.record_failure("p1")
        cb.record_failure("p1")
        assert cb.get_consecutive_failures("p1") == 2


# ── Score Model Tests ────────────────────────────────────────────────────────


class TestScoreModel:
    """Test the _score_model scoring function."""

    def test_score_returns_tuple_of_float_and_factors(self):
        model = _make_model()
        request = _make_request()
        policy = RoutingPolicy()
        score, factors = _score_model(model, request, policy)
        assert isinstance(score, float)
        assert len(factors) == 4  # cost, latency, quality, data_residency

    def test_cheaper_model_scores_higher_on_cost(self):
        cheap = _make_model(
            name="cheap", cost_per_input_token=0.1, cost_per_output_token=0.2
        )
        expensive = _make_model(
            name="exp", cost_per_input_token=30.0, cost_per_output_token=60.0
        )
        request = _make_request()
        policy = RoutingPolicy(
            cost_weight=1.0,
            latency_weight=0.0,
            quality_weight=0.0,
            data_residency_weight=0.0,
        )
        cheap_score, _ = _score_model(cheap, request, policy)
        expensive_score, _ = _score_model(expensive, request, policy)
        assert cheap_score > expensive_score

    def test_degraded_health_reduces_score(self):
        healthy = _make_model(health_status="healthy")
        degraded = _make_model(health_status="degraded")
        request = _make_request()
        policy = RoutingPolicy()
        healthy_score, _ = _score_model(healthy, request, policy)
        degraded_score, _ = _score_model(degraded, request, policy)
        assert healthy_score > degraded_score

    def test_geo_residency_match_bonus(self):
        match = _make_model(geo_residency="eu")
        mismatch = _make_model(geo_residency="us")
        request = _make_request(geo_residency="eu")
        policy = RoutingPolicy(
            data_residency_weight=1.0,
            cost_weight=0.0,
            latency_weight=0.0,
            quality_weight=0.0,
        )
        match_score, _ = _score_model(match, request, policy)
        mismatch_score, _ = _score_model(mismatch, request, policy)
        assert match_score > mismatch_score


# ── Route Method Tests ───────────────────────────────────────────────────────


class TestModelRouterServiceRoute:
    """Test ModelRouterService.route with mocked DB."""

    def _make_session(self, models: list[ModelRegistryEntry]) -> AsyncMock:
        """Build a mock session that returns *models* from exec calls."""
        mock_result = MagicMock()
        mock_result.all.return_value = models
        mock_result.first.return_value = None

        session = AsyncMock()
        session.exec = AsyncMock(return_value=mock_result)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.get = AsyncMock(return_value=None)
        return session

    @pytest.mark.asyncio
    async def test_happy_path_returns_selected_model(self):
        model = _make_model(name="gpt-4o", tenant_id="t1")
        session = self._make_session([model])
        secrets = AsyncMock()
        user = _admin_user("t1")
        request = _make_request()

        with patch(
            "app.services.router_service.AuditLogService.create", new=AsyncMock()
        ):
            decision = await ModelRouterService.route(
                session, secrets, "t1", user, request
            )

        assert decision.selected_model == "gpt-4o"
        assert decision.score > 0.0
        assert decision.data_classification_met is True

    @pytest.mark.asyncio
    async def test_no_candidates_returns_none_decision(self):
        session = self._make_session([])
        secrets = AsyncMock()
        user = _admin_user("t1")
        request = _make_request()

        decision = await ModelRouterService.route(session, secrets, "t1", user, request)

        assert decision.selected_model == "none"
        assert decision.data_classification_met is False

    @pytest.mark.asyncio
    async def test_tenant_isolation_filters_other_tenant_models(self):
        """Models belonging to tenant-2 must not appear in tenant-1 decisions."""
        model_t2 = _make_model(name="gpt-4o", tenant_id="tenant-2")
        session = self._make_session([model_t2])
        secrets = AsyncMock()
        user = _admin_user("tenant-1")
        request = _make_request()

        decision = await ModelRouterService.route(
            session, secrets, "tenant-1", user, request
        )

        assert decision.selected_model == "none"

    @pytest.mark.asyncio
    async def test_capability_filter_removes_incapable_models(self):
        capable = _make_model(
            name="capable", capabilities=["chat", "code"], tenant_id="t1"
        )
        incapable = _make_model(name="incapable", capabilities=["chat"], tenant_id="t1")
        session = self._make_session([capable, incapable])
        secrets = AsyncMock()
        user = _admin_user("t1")
        request = _make_request(required_capabilities=["code"])

        with patch(
            "app.services.router_service.AuditLogService.create", new=AsyncMock()
        ):
            decision = await ModelRouterService.route(
                session, secrets, "t1", user, request
            )

        assert decision.selected_model == "capable"

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_skips_provider(self):
        model = _make_model(name="broken", tenant_id="t1")
        session = self._make_session([model])
        secrets = AsyncMock()
        user = _admin_user("t1")
        request = _make_request()

        # Force circuit open for that model
        import app.services.router_service as rs

        original_is_open = rs._circuit_breaker.is_open
        rs._circuit_breaker.is_open = lambda pid: True

        try:
            decision = await ModelRouterService.route(
                session, secrets, "t1", user, request
            )
            assert decision.selected_model == "none"
        finally:
            rs._circuit_breaker.is_open = original_is_open

    @pytest.mark.asyncio
    async def test_cost_routing_budget_limit_filters_expensive_model(self):
        cheap = _make_model(
            name="cheap",
            cost_per_input_token=0.01,
            cost_per_output_token=0.02,
            tenant_id="t1",
        )
        expensive = _make_model(
            name="expensive",
            cost_per_input_token=50.0,
            cost_per_output_token=100.0,
            tenant_id="t1",
        )
        session = self._make_session([cheap, expensive])
        secrets = AsyncMock()
        user = _admin_user("t1")
        # Very tight budget: only cheap qualifies
        request = _make_request(budget_limit=0.001, input_tokens_estimate=100)

        with patch(
            "app.services.router_service.AuditLogService.create", new=AsyncMock()
        ):
            decision = await ModelRouterService.route(
                session, secrets, "t1", user, request
            )

        assert decision.selected_model == "cheap"


# ── Visual Condition Matching ────────────────────────────────────────────────


class TestMatchVisualConditions:
    """Test _match_visual_conditions and _eval_operator helpers."""

    def test_empty_conditions_returns_false(self):
        assert _match_visual_conditions([], {"capability": "code"}) is False

    def test_equals_operator_matches(self):
        cond = [{"field": "capability", "operator": "equals", "value": "code"}]
        assert _match_visual_conditions(cond, {"capability": "code"}) is True

    def test_equals_operator_no_match(self):
        cond = [{"field": "capability", "operator": "equals", "value": "code"}]
        assert _match_visual_conditions(cond, {"capability": "chat"}) is False

    def test_greater_than_operator(self):
        assert _eval_operator("100", "greater_than", "50") is True
        assert _eval_operator("30", "greater_than", "50") is False

    def test_less_than_operator(self):
        assert _eval_operator("10", "less_than", "50") is True

    def test_in_operator(self):
        assert _eval_operator("eu", "in", ["eu", "us"]) is True
        assert _eval_operator("ap", "in", ["eu", "us"]) is False

    def test_missing_context_field_returns_false(self):
        cond = [{"field": "missing_field", "operator": "equals", "value": "x"}]
        assert _match_visual_conditions(cond, {"other": "x"}) is False


# ── Helper Utilities ─────────────────────────────────────────────────────────


class TestHelpers:
    def test_find_model_by_id_found(self):
        model = _make_model()
        result = _find_model_by_id([model], str(model.id))
        assert result is model

    def test_find_model_by_id_not_found(self):
        model = _make_model()
        result = _find_model_by_id([model], str(uuid4()))
        assert result is None

    def test_build_alternatives_excludes_selected(self):
        m1 = _make_model(name="m1")
        m2 = _make_model(name="m2")
        m3 = _make_model(name="m3")
        alts = _build_alternatives([m1, m2, m3], str(m1.id))
        names = [a["model_name"] for a in alts]
        assert "m1" not in names
        assert "m2" in names
        assert len(alts) <= 3
