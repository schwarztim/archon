"""Unit tests for RoutingEngine decision logic, strategy selection, and scoring.

Tests cover:
- Strategy-based routing (cost_optimized, performance_optimized, balanced, sensitive)
- A/B-style strategy override distribution
- Capability filtering and data-classification gating
- Fallback chain construction
- Health penalties and degraded-model demotion
- Edge cases: no eligible models, unknown strategy, single model
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.models.router import ModelRegistryEntry, RoutingRule
from app.services.router import RoutingEngine, STRATEGIES

# ── Fixed UUIDs ─────────────────────────────────────────────────────

MODEL_CHEAP = UUID("00000001-0001-0001-0001-000000000001")
MODEL_FAST = UUID("00000002-0002-0002-0002-000000000002")
MODEL_CAPABLE = UUID("00000003-0003-0003-0003-000000000003")
MODEL_ON_PREM = UUID("00000004-0004-0004-0004-000000000004")
MODEL_DEGRADED = UUID("00000005-0005-0005-0005-000000000005")
RULE_ID = UUID("aaaa0001-0001-0001-0001-000000000001")
DEPT_ID = UUID("dddd0001-0001-0001-0001-000000000001")
AGENT_ID = UUID("eeee0001-0001-0001-0001-000000000001")
NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Factories ───────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _model(
    *,
    mid: UUID = MODEL_CHEAP,
    name: str = "cheap-model",
    provider: str = "openai",
    capabilities: list[str] | None = None,
    cost_in: float = 1.0,
    cost_out: float = 2.0,
    latency: float = 200.0,
    classification: str = "general",
    is_on_prem: bool = False,
    is_active: bool = True,
    health: str = "healthy",
) -> ModelRegistryEntry:
    """Build a ModelRegistryEntry with controllable fields."""
    return ModelRegistryEntry(
        id=mid,
        name=name,
        provider=provider,
        model_id=f"{provider}/{name}",
        capabilities=["chat"] if capabilities is None else capabilities,
        context_window=128_000,
        supports_streaming=True,
        cost_per_input_token=cost_in,
        cost_per_output_token=cost_out,
        speed_tier="fast",
        avg_latency_ms=latency,
        data_classification=classification,
        is_on_prem=is_on_prem,
        is_active=is_active,
        health_status=health,
        error_rate=0.0,
        config={},
        created_at=NOW,
        updated_at=NOW,
    )


def _rule(
    *,
    rid: UUID = RULE_ID,
    strategy: str = "balanced",
    priority: int = 10,
    department_id: UUID | None = None,
    agent_id: UUID | None = None,
    w_cost: float = 0.25,
    w_latency: float = 0.25,
    w_cap: float = 0.25,
    w_sens: float = 0.25,
    fallback_chain: list[str] | None = None,
    is_active: bool = True,
) -> RoutingRule:
    """Build a RoutingRule with controllable weights."""
    return RoutingRule(
        id=rid,
        name=f"rule-{strategy}",
        strategy=strategy,
        priority=priority,
        is_active=is_active,
        department_id=department_id,
        agent_id=agent_id,
        weight_cost=w_cost,
        weight_latency=w_latency,
        weight_capability=w_cap,
        weight_sensitivity=w_sens,
        conditions={},
        fallback_chain=fallback_chain or [],
        created_at=NOW,
        updated_at=NOW,
    )


def _setup_session(
    *,
    rules: list[RoutingRule] | None = None,
    models: list[ModelRegistryEntry] | None = None,
    fallback_gets: dict[str, ModelRegistryEntry | None] | None = None,
) -> AsyncMock:
    """Wire up a mock session for RoutingEngine.route.

    RoutingEngine calls session.exec twice (rules query, models query)
    and may call session.get for fallback chain entries.
    """
    session = _mock_session()

    rule_result = MagicMock()
    rule_result.all.return_value = rules or []

    model_result = MagicMock()
    model_result.all.return_value = models or []

    session.exec = AsyncMock(side_effect=[rule_result, model_result])

    # session.get is used for fallback_chain look-ups
    if fallback_gets:
        async def _get(cls: type, key: str | UUID) -> ModelRegistryEntry | None:
            return fallback_gets.get(str(key))
        session.get = AsyncMock(side_effect=_get)

    return session


# ═══════════════════════════════════════════════════════════════════
# Strategy constants
# ═══════════════════════════════════════════════════════════════════


def test_strategies_set_contains_expected() -> None:
    """STRATEGIES frozenset contains all known strategy names."""
    assert "cost_optimized" in STRATEGIES
    assert "performance_optimized" in STRATEGIES
    assert "balanced" in STRATEGIES
    assert "sensitive" in STRATEGIES
    assert "custom" in STRATEGIES


# ═══════════════════════════════════════════════════════════════════
# No eligible models
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_route_no_models_returns_none() -> None:
    """When no active models exist, route returns model=None."""
    session = _setup_session(rules=[], models=[])

    result = await RoutingEngine.route(session)

    assert result["model"] is None
    assert result["fallbacks"] == []
    assert result["strategy"] == "balanced"
    assert isinstance(result["decision_ms"], float)


# ═══════════════════════════════════════════════════════════════════
# Single model — always selected
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_route_single_model_is_primary() -> None:
    """With one eligible model, it becomes the primary with no fallbacks."""
    m = _model()
    session = _setup_session(models=[m])

    result = await RoutingEngine.route(session)

    assert result["model"]["id"] == str(MODEL_CHEAP)
    assert result["fallbacks"] == []
    assert str(MODEL_CHEAP) in result["scores"]


# ═══════════════════════════════════════════════════════════════════
# Cost-optimized strategy
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_cost_optimized_prefers_cheapest() -> None:
    """Cost-optimized strategy should rank the cheapest model first."""
    cheap = _model(mid=MODEL_CHEAP, name="cheap", cost_in=0.5, cost_out=1.0, latency=1000.0)
    expensive = _model(mid=MODEL_FAST, name="fast", cost_in=30.0, cost_out=60.0, latency=100.0)
    session = _setup_session(models=[cheap, expensive])

    result = await RoutingEngine.route(session, strategy_override="cost_optimized")

    assert result["model"]["id"] == str(MODEL_CHEAP)
    assert result["strategy"] == "cost_optimized"


# ═══════════════════════════════════════════════════════════════════
# Performance-optimized strategy
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_performance_optimized_prefers_fastest() -> None:
    """Performance-optimized strategy should rank the lowest-latency model first."""
    slow = _model(mid=MODEL_CHEAP, name="slow", cost_in=0.5, cost_out=1.0, latency=3000.0)
    fast = _model(mid=MODEL_FAST, name="fast", cost_in=30.0, cost_out=60.0, latency=50.0)
    session = _setup_session(models=[slow, fast])

    result = await RoutingEngine.route(session, strategy_override="performance_optimized")

    assert result["model"]["id"] == str(MODEL_FAST)
    assert result["strategy"] == "performance_optimized"


# ═══════════════════════════════════════════════════════════════════
# Sensitive strategy
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_sensitive_strategy_prefers_on_prem() -> None:
    """Sensitive strategy should strongly prefer on-prem models."""
    cloud = _model(mid=MODEL_CHEAP, name="cloud", cost_in=1.0, cost_out=2.0, latency=200.0)
    on_prem = _model(
        mid=MODEL_ON_PREM, name="on-prem", cost_in=5.0, cost_out=10.0,
        latency=500.0, is_on_prem=True,
    )
    session = _setup_session(models=[cloud, on_prem])

    result = await RoutingEngine.route(session, strategy_override="sensitive")

    assert result["model"]["id"] == str(MODEL_ON_PREM)


@pytest.mark.asyncio
async def test_sensitive_strategy_prefers_restricted_over_general() -> None:
    """Sensitive strategy ranks restricted-classified models above general."""
    general = _model(mid=MODEL_CHEAP, name="general", classification="general")
    restricted = _model(
        mid=MODEL_CAPABLE, name="restricted", classification="restricted",
        cost_in=5.0, cost_out=10.0,
    )
    session = _setup_session(models=[general, restricted])

    result = await RoutingEngine.route(session, strategy_override="sensitive")

    assert result["model"]["id"] == str(MODEL_CAPABLE)


# ═══════════════════════════════════════════════════════════════════
# Balanced strategy (default)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_balanced_strategy_is_default() -> None:
    """When no rule or override, strategy defaults to balanced."""
    m = _model()
    session = _setup_session(models=[m])

    result = await RoutingEngine.route(session)

    assert result["strategy"] == "balanced"


# ═══════════════════════════════════════════════════════════════════
# Capability-based filtering
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_required_capabilities_filter() -> None:
    """Models missing required capabilities are excluded."""
    chat_only = _model(mid=MODEL_CHEAP, name="chat-only", capabilities=["chat"])
    vision = _model(
        mid=MODEL_CAPABLE, name="vision-model",
        capabilities=["chat", "vision", "code"],
    )
    session = _setup_session(models=[chat_only, vision])

    result = await RoutingEngine.route(
        session, required_capabilities=["vision"],
    )

    # Only vision model qualifies
    assert result["model"]["id"] == str(MODEL_CAPABLE)
    assert len(result["fallbacks"]) == 0


@pytest.mark.asyncio
async def test_multiple_required_capabilities() -> None:
    """All required capabilities must be present."""
    partial = _model(mid=MODEL_CHEAP, name="partial", capabilities=["chat", "code"])
    full = _model(
        mid=MODEL_CAPABLE, name="full",
        capabilities=["chat", "code", "function_calling"],
    )
    session = _setup_session(models=[partial, full])

    result = await RoutingEngine.route(
        session, required_capabilities=["code", "function_calling"],
    )

    assert result["model"]["id"] == str(MODEL_CAPABLE)


@pytest.mark.asyncio
async def test_no_model_meets_capabilities() -> None:
    """When no model has the required capabilities, model is None."""
    m = _model(capabilities=["chat"])
    session = _setup_session(models=[m])

    result = await RoutingEngine.route(
        session, required_capabilities=["vision"],
    )

    assert result["model"] is None


# ═══════════════════════════════════════════════════════════════════
# Data classification gating
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_restricted_data_excludes_general_models() -> None:
    """Models with general classification cannot serve restricted data."""
    general_model = _model(mid=MODEL_CHEAP, name="general", classification="general")
    restricted_model = _model(
        mid=MODEL_ON_PREM, name="restricted", classification="restricted",
    )
    session = _setup_session(models=[general_model, restricted_model])

    result = await RoutingEngine.route(session, data_classification="restricted")

    assert result["model"]["id"] == str(MODEL_ON_PREM)


@pytest.mark.asyncio
async def test_internal_data_excludes_general_models() -> None:
    """Models with general classification cannot serve internal data."""
    general_model = _model(mid=MODEL_CHEAP, name="general", classification="general")
    internal_model = _model(
        mid=MODEL_FAST, name="internal", classification="internal",
    )
    session = _setup_session(models=[general_model, internal_model])

    result = await RoutingEngine.route(session, data_classification="internal")

    assert result["model"]["id"] == str(MODEL_FAST)


@pytest.mark.asyncio
async def test_general_data_allows_all_classifications() -> None:
    """General data classification allows all model classifications."""
    general_m = _model(mid=MODEL_CHEAP, name="gen", classification="general")
    restricted_m = _model(mid=MODEL_ON_PREM, name="restr", classification="restricted")
    session = _setup_session(models=[general_m, restricted_m])

    result = await RoutingEngine.route(session, data_classification="general")

    # Both models eligible — primary is whichever scores highest
    assert result["model"] is not None
    assert len(result["fallbacks"]) == 1


# ═══════════════════════════════════════════════════════════════════
# Health penalty — degraded models
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_degraded_model_penalised() -> None:
    """A degraded model scores lower than an equivalent healthy model."""
    healthy = _model(
        mid=MODEL_CHEAP, name="healthy", cost_in=2.0, cost_out=3.0, latency=300.0,
    )
    degraded = _model(
        mid=MODEL_DEGRADED, name="degraded", cost_in=2.0, cost_out=3.0,
        latency=300.0, health="degraded",
    )
    session = _setup_session(models=[healthy, degraded])

    result = await RoutingEngine.route(session)

    # Healthy model should win due to 0.7x penalty on degraded
    assert result["model"]["id"] == str(MODEL_CHEAP)
    assert result["scores"][str(MODEL_CHEAP)] > result["scores"][str(MODEL_DEGRADED)]


# ═══════════════════════════════════════════════════════════════════
# Unhealthy models excluded by query filter
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_unhealthy_models_excluded() -> None:
    """Unhealthy models are filtered at the DB level (not returned by _eligible_models)."""
    # In real code the WHERE clause excludes unhealthy. We simulate by
    # not including them in the result set — confirming engine handles it.
    healthy = _model(mid=MODEL_CHEAP, name="healthy")
    session = _setup_session(models=[healthy])

    result = await RoutingEngine.route(session)

    assert result["model"]["id"] == str(MODEL_CHEAP)


# ═══════════════════════════════════════════════════════════════════
# Fallback chain from scoring (top 3 runners-up)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_fallback_chain_contains_up_to_three_runners() -> None:
    """Fallback list includes up to 3 next-best models from scoring."""
    models = [
        _model(mid=uuid4(), name=f"m{i}", cost_in=float(i), cost_out=float(i))
        for i in range(5)
    ]
    session = _setup_session(models=models)

    result = await RoutingEngine.route(session)

    assert result["model"] is not None
    assert len(result["fallbacks"]) == 3


# ═══════════════════════════════════════════════════════════════════
# Fallback chain from rule definition
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rule_fallback_chain_appended() -> None:
    """Fallback IDs from the rule's fallback_chain are appended if not already present."""
    primary = _model(mid=MODEL_CHEAP, name="primary")
    extra_fb = _model(mid=MODEL_ON_PREM, name="extra-fallback", is_active=True)
    rule = _rule(fallback_chain=[str(MODEL_ON_PREM)])

    session = _setup_session(
        rules=[rule],
        models=[primary],
        fallback_gets={str(MODEL_ON_PREM): extra_fb},
    )

    result = await RoutingEngine.route(session)

    fb_ids = [f["id"] for f in result["fallbacks"]]
    assert str(MODEL_ON_PREM) in fb_ids


@pytest.mark.asyncio
async def test_rule_fallback_chain_skips_inactive() -> None:
    """Inactive models in the rule fallback_chain are not included."""
    primary = _model(mid=MODEL_CHEAP, name="primary")
    inactive = _model(mid=MODEL_ON_PREM, name="inactive", is_active=False)
    rule = _rule(fallback_chain=[str(MODEL_ON_PREM)])

    session = _setup_session(
        rules=[rule],
        models=[primary],
        fallback_gets={str(MODEL_ON_PREM): inactive},
    )

    result = await RoutingEngine.route(session)

    fb_ids = [f["id"] for f in result["fallbacks"]]
    assert str(MODEL_ON_PREM) not in fb_ids


@pytest.mark.asyncio
async def test_rule_fallback_chain_skips_missing() -> None:
    """Fallback IDs that don't resolve to a model are silently skipped."""
    primary = _model(mid=MODEL_CHEAP, name="primary")
    rule = _rule(fallback_chain=[str(uuid4())])

    session = _setup_session(
        rules=[rule],
        models=[primary],
        fallback_gets={},
    )
    # Ensure session.get returns None for unknown IDs
    session.get = AsyncMock(return_value=None)

    result = await RoutingEngine.route(session)

    assert result["fallbacks"] == []


# ═══════════════════════════════════════════════════════════════════
# Rule resolution — specificity
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rule_matched_by_agent_id() -> None:
    """A rule scoped to a specific agent_id is selected when matching."""
    rule = _rule(
        strategy="cost_optimized",
        agent_id=AGENT_ID,
        w_cost=0.8, w_latency=0.05, w_cap=0.1, w_sens=0.05,
    )
    m = _model()
    session = _setup_session(rules=[rule], models=[m])

    result = await RoutingEngine.route(session, agent_id=AGENT_ID)

    assert result["strategy"] == "cost_optimized"


@pytest.mark.asyncio
async def test_rule_skipped_when_agent_id_mismatch() -> None:
    """A rule scoped to a different agent_id is not selected."""
    rule = _rule(strategy="cost_optimized", agent_id=uuid4())
    m = _model()
    session = _setup_session(rules=[rule], models=[m])

    result = await RoutingEngine.route(session, agent_id=AGENT_ID)

    # Falls back to default balanced
    assert result["strategy"] == "balanced"


@pytest.mark.asyncio
async def test_rule_matched_by_department_id() -> None:
    """A rule scoped to a department_id is selected when matching."""
    rule = _rule(strategy="sensitive", department_id=DEPT_ID)
    m = _model()
    session = _setup_session(rules=[rule], models=[m])

    result = await RoutingEngine.route(session, department_id=DEPT_ID)

    assert result["strategy"] == "sensitive"


@pytest.mark.asyncio
async def test_rule_skipped_when_department_id_mismatch() -> None:
    """A rule scoped to a different department_id is not selected."""
    rule = _rule(strategy="sensitive", department_id=uuid4())
    m = _model()
    session = _setup_session(rules=[rule], models=[m])

    result = await RoutingEngine.route(session, department_id=DEPT_ID)

    assert result["strategy"] == "balanced"


# ═══════════════════════════════════════════════════════════════════
# Strategy override
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_strategy_override_takes_precedence() -> None:
    """strategy_override param overrides both rule and default."""
    rule = _rule(strategy="balanced")
    m = _model()
    session = _setup_session(rules=[rule], models=[m])

    result = await RoutingEngine.route(
        session, strategy_override="performance_optimized",
    )

    # override is applied, but the rule won't match because rule.strategy != override
    assert result["strategy"] == "performance_optimized"


@pytest.mark.asyncio
async def test_unknown_strategy_falls_back_to_balanced_weights() -> None:
    """An unknown strategy name gets balanced preset weights."""
    m = _model()
    session = _setup_session(models=[m])

    result = await RoutingEngine.route(session, strategy_override="unknown_strategy")

    assert result["strategy"] == "unknown_strategy"
    assert result["model"] is not None  # still routes with balanced weights


# ═══════════════════════════════════════════════════════════════════
# A/B testing simulation — strategy_override as treatment arm
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_ab_test_different_strategies_produce_different_rankings() -> None:
    """Simulates A/B testing: two strategy arms can pick different primary models."""
    cheap = _model(mid=MODEL_CHEAP, name="cheap", cost_in=0.5, cost_out=1.0, latency=2000.0)
    fast = _model(mid=MODEL_FAST, name="fast", cost_in=50.0, cost_out=80.0, latency=50.0)

    session_a = _setup_session(models=[cheap, fast])
    result_a = await RoutingEngine.route(session_a, strategy_override="cost_optimized")

    session_b = _setup_session(models=[cheap, fast])
    result_b = await RoutingEngine.route(session_b, strategy_override="performance_optimized")

    assert result_a["model"]["id"] == str(MODEL_CHEAP), "Cost arm picks cheap"
    assert result_b["model"]["id"] == str(MODEL_FAST), "Performance arm picks fast"
    assert result_a["strategy"] != result_b["strategy"]


@pytest.mark.asyncio
async def test_ab_test_scores_differ_across_strategies() -> None:
    """Different strategies produce different composite scores for the same model set."""
    models = [
        _model(mid=MODEL_CHEAP, name="cheap", cost_in=1.0, cost_out=2.0, latency=500.0),
        _model(mid=MODEL_FAST, name="fast", cost_in=20.0, cost_out=30.0, latency=100.0),
    ]

    session_cost = _setup_session(models=models)
    result_cost = await RoutingEngine.route(session_cost, strategy_override="cost_optimized")

    session_perf = _setup_session(models=models)
    result_perf = await RoutingEngine.route(session_perf, strategy_override="performance_optimized")

    # Scores should differ — same models, different weights
    assert result_cost["scores"] != result_perf["scores"]


# ═══════════════════════════════════════════════════════════════════
# Scoring internals — _weights
# ═══════════════════════════════════════════════════════════════════


def test_weights_from_rule_uses_rule_values() -> None:
    """_weights returns the rule's weight fields when a rule is provided."""
    rule = _rule(w_cost=0.5, w_latency=0.2, w_cap=0.2, w_sens=0.1)

    weights = RoutingEngine._weights(rule, "balanced")

    assert weights == {
        "cost": 0.5,
        "latency": 0.2,
        "capability": 0.2,
        "sensitivity": 0.1,
    }


def test_weights_no_rule_uses_preset() -> None:
    """_weights returns preset weights when no rule is provided."""
    weights = RoutingEngine._weights(None, "cost_optimized")

    assert weights["cost"] == 0.6
    assert weights["latency"] == 0.1


def test_weights_unknown_strategy_uses_balanced() -> None:
    """_weights returns balanced preset for unknown strategy names."""
    weights = RoutingEngine._weights(None, "nonexistent")

    assert weights == {"cost": 0.25, "latency": 0.25, "capability": 0.25, "sensitivity": 0.25}


# ═══════════════════════════════════════════════════════════════════
# Scoring internals — _score
# ═══════════════════════════════════════════════════════════════════


def test_score_healthy_model() -> None:
    """_score returns a positive float for a healthy model."""
    m = _model(cost_in=5.0, cost_out=10.0, latency=500.0, capabilities=["chat", "code"])
    weights = {"cost": 0.25, "latency": 0.25, "capability": 0.25, "sensitivity": 0.25}

    score = RoutingEngine._score(m, weights, "balanced")

    assert 0.0 < score <= 1.0


def test_score_degraded_model_lower() -> None:
    """_score applies 0.7x health penalty for degraded models."""
    healthy = _model(health="healthy")
    degraded = _model(health="degraded")
    weights = {"cost": 0.25, "latency": 0.25, "capability": 0.25, "sensitivity": 0.25}

    s_healthy = RoutingEngine._score(healthy, weights, "balanced")
    s_degraded = RoutingEngine._score(degraded, weights, "balanced")

    assert s_degraded == pytest.approx(s_healthy * 0.7, rel=1e-6)


def test_score_on_prem_gets_full_sensitivity() -> None:
    """On-prem model gets sensitivity_score=1.0."""
    on_prem = _model(is_on_prem=True)
    cloud = _model(is_on_prem=False, classification="general")
    weights = {"cost": 0.0, "latency": 0.0, "capability": 0.0, "sensitivity": 1.0}

    s_prem = RoutingEngine._score(on_prem, weights, "sensitive")
    s_cloud = RoutingEngine._score(cloud, weights, "sensitive")

    assert s_prem > s_cloud


def test_score_zero_cost_gets_perfect_cost_score() -> None:
    """A free model (cost=0) gets cost_score=1.0."""
    free = _model(cost_in=0.0, cost_out=0.0)
    weights = {"cost": 1.0, "latency": 0.0, "capability": 0.0, "sensitivity": 0.0}

    score = RoutingEngine._score(free, weights, "cost_optimized")

    assert score == pytest.approx(1.0, rel=1e-6)


def test_score_expensive_model_lower_cost_score() -> None:
    """An expensive model ($100/M token total) gets cost_score approaching 0."""
    expensive = _model(cost_in=50.0, cost_out=50.0)
    weights = {"cost": 1.0, "latency": 0.0, "capability": 0.0, "sensitivity": 0.0}

    score = RoutingEngine._score(expensive, weights, "cost_optimized")

    assert score == pytest.approx(0.0, abs=0.01)


def test_score_zero_latency_gets_perfect_latency_score() -> None:
    """A model with 0ms latency gets latency_score=1.0."""
    fast = _model(latency=0.0)
    weights = {"cost": 0.0, "latency": 1.0, "capability": 0.0, "sensitivity": 0.0}

    score = RoutingEngine._score(fast, weights, "performance_optimized")

    assert score == pytest.approx(1.0, rel=1e-6)


def test_score_many_capabilities_caps_at_one() -> None:
    """Capability score caps at 1.0 for >=5 capabilities."""
    many_caps = _model(capabilities=["a", "b", "c", "d", "e", "f", "g"])
    weights = {"cost": 0.0, "latency": 0.0, "capability": 1.0, "sensitivity": 0.0}

    score = RoutingEngine._score(many_caps, weights, "balanced")

    assert score == pytest.approx(1.0, rel=1e-6)


def test_score_no_capabilities() -> None:
    """Model with empty capabilities list gets only sensitivity contribution."""
    no_caps = _model(capabilities=[])
    weights = {"cost": 0.0, "latency": 0.0, "capability": 1.0, "sensitivity": 0.0}

    score = RoutingEngine._score(no_caps, weights, "balanced")

    # capability_score = 0/5 = 0.0; but sensitivity defaults to 0.5
    # with sensitivity weight=0, only capability matters → 0.0
    assert score == pytest.approx(0.0, abs=1e-6)


def test_score_empty_capabilities_list() -> None:
    """Model with empty capabilities has lower score than model with capabilities."""
    no_caps = _model(capabilities=[])
    has_caps = _model(capabilities=["chat", "code", "vision"])
    weights = {"cost": 0.0, "latency": 0.0, "capability": 1.0, "sensitivity": 0.0}

    s_none = RoutingEngine._score(no_caps, weights, "balanced")
    s_has = RoutingEngine._score(has_caps, weights, "balanced")

    assert s_has > s_none


# ═══════════════════════════════════════════════════════════════════
# Decision latency tracking
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_decision_ms_is_non_negative() -> None:
    """decision_ms field is always a non-negative float."""
    m = _model()
    session = _setup_session(models=[m])

    result = await RoutingEngine.route(session)

    assert result["decision_ms"] >= 0.0


# ═══════════════════════════════════════════════════════════════════
# Rule uses custom weights to swing selection
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_rule_weights_override_default_strategy() -> None:
    """A rule with custom weights can swing selection away from default."""
    cheap = _model(mid=MODEL_CHEAP, name="cheap", cost_in=0.5, cost_out=1.0, latency=3000.0)
    fast = _model(mid=MODEL_FAST, name="fast", cost_in=50.0, cost_out=50.0, latency=50.0)

    # Rule heavily weights latency
    rule = _rule(strategy="balanced", w_cost=0.0, w_latency=0.9, w_cap=0.05, w_sens=0.05)
    session = _setup_session(rules=[rule], models=[cheap, fast])

    result = await RoutingEngine.route(session)

    assert result["model"]["id"] == str(MODEL_FAST)


# ═══════════════════════════════════════════════════════════════════
# Scores dict structure
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_scores_dict_contains_all_models() -> None:
    """The scores dict has an entry for every eligible model."""
    models = [
        _model(mid=MODEL_CHEAP, name="m1"),
        _model(mid=MODEL_FAST, name="m2"),
        _model(mid=MODEL_CAPABLE, name="m3"),
    ]
    session = _setup_session(models=models)

    result = await RoutingEngine.route(session)

    assert len(result["scores"]) == 3
    for m in models:
        assert str(m.id) in result["scores"]
