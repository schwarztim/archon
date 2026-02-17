"""Tests for CostService — ledger, summary, budgets, chargeback, forecast, optimization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.cost import (
    Budget,
    BudgetCheckResult,
    BudgetConfig,
    BudgetPeriod,
    BudgetResponse,
    BudgetScope,
    ChargebackReport,
    CostForecast,
    CostSummary,
    Recommendation,
    TokenLedger,
    TokenLedgerEntry,
    UsageEvent,
)
from app.services.cost_service import CostService


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "tenant-cost-test"


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


def _finance_user(**overrides: Any) -> AuthenticatedUser:
    defaults = dict(
        id=str(uuid4()),
        email="finance@example.com",
        tenant_id=TENANT_ID,
        roles=["finance_admin"],
        permissions=[],
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _dev_user(**overrides: Any) -> AuthenticatedUser:
    defaults = dict(
        id=str(uuid4()),
        email="dev@example.com",
        tenant_id=TENANT_ID,
        roles=["agent_creator"],
        permissions=[],
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _make_ledger_entry(
    tenant_id: str = TENANT_ID,
    provider: str = "openai",
    model_id: str = "gpt-4o",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    total_cost: float = 0.015,
    user_id: UUID | None = None,
    department_id: UUID | None = None,
    days_ago: int = 0,
) -> TokenLedger:
    now = datetime.now(timezone.utc) - timedelta(days=days_ago)
    entry = MagicMock(spec=TokenLedger)
    entry.id = uuid4()
    entry.tenant_id = tenant_id
    entry.provider = provider
    entry.model_id = model_id
    entry.input_tokens = input_tokens
    entry.output_tokens = output_tokens
    entry.total_cost = total_cost
    entry.input_cost = total_cost * 0.3
    entry.output_cost = total_cost * 0.7
    entry.total_tokens = input_tokens + output_tokens
    entry.user_id = user_id
    entry.department_id = department_id
    entry.workspace_id = None
    entry.execution_id = None
    entry.agent_id = None
    entry.latency_ms = 150.0
    entry.attribution_chain = {"tenant_id": tenant_id, "provider": provider}
    entry.extra_metadata = {}
    entry.created_at = now
    return entry


def _make_budget(
    tenant_id: str = TENANT_ID,
    limit: float = 100.0,
    spent: float = 0.0,
    hard_limit: bool = False,
    scope: str = "tenant",
    user_id: UUID | None = None,
    alert_threshold_pct: float = 80.0,
    name: str = "test-budget",
) -> MagicMock:
    b = MagicMock(spec=Budget)
    b.id = uuid4()
    b.tenant_id = tenant_id
    b.name = name
    b.scope = scope
    b.limit_amount = limit
    b.spent_amount = spent
    b.hard_limit = hard_limit
    b.is_active = True
    b.user_id = user_id
    b.alert_threshold_pct = alert_threshold_pct
    b.alert_thresholds = [50.0, 75.0, 90.0, 100.0]
    b.updated_at = datetime.now(timezone.utc)
    return b


def _mock_session_exec(entries: list[Any]) -> AsyncMock:
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.all.return_value = entries
    result_mock.first.return_value = None
    session.exec.return_value = result_mock
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


# ── Record Usage (Immutable Ledger) ─────────────────────────────────


class TestRecordUsage:
    """record_usage creates immutable ledger entries."""

    @pytest.mark.asyncio
    async def test_record_creates_entry(self) -> None:
        session = _mock_session_exec([])
        event = UsageEvent(
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
        )

        with patch.object(CostService, "_update_budget_spend", new_callable=AsyncMock):
            entry = await CostService.record_usage(session, TENANT_ID, event)

        session.add.assert_called_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_with_explicit_cost(self) -> None:
        session = _mock_session_exec([])
        event = UsageEvent(
            provider="anthropic",
            model="claude-3-5-sonnet",
            input_tokens=2000,
            output_tokens=1000,
            cost_usd=0.05,
        )

        with patch.object(CostService, "_update_budget_spend", new_callable=AsyncMock):
            entry = await CostService.record_usage(session, TENANT_ID, event)

        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert added.total_cost == 0.05

    @pytest.mark.asyncio
    async def test_record_includes_attribution_chain(self) -> None:
        session = _mock_session_exec([])
        user_id = uuid4()
        dept_id = uuid4()
        event = UsageEvent(
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            user_id=user_id,
            department_id=dept_id,
        )

        with patch.object(CostService, "_update_budget_spend", new_callable=AsyncMock):
            await CostService.record_usage(session, TENANT_ID, event)

        added = session.add.call_args[0][0]
        assert added.attribution_chain["user_id"] == str(user_id)
        assert added.attribution_chain["department_id"] == str(dept_id)


# ── Cost Summary with RBAC ──────────────────────────────────────────


class TestCostSummary:
    """Cost summary with RBAC filtering."""

    @pytest.mark.asyncio
    async def test_admin_sees_all_costs(self) -> None:
        entries = [
            _make_ledger_entry(provider="openai", total_cost=1.0),
            _make_ledger_entry(provider="anthropic", total_cost=2.0),
        ]
        session = _mock_session_exec(entries)

        result = await CostService.get_cost_summary(
            session, TENANT_ID, _admin_user(),
        )

        assert isinstance(result, CostSummary)
        assert result.total_cost == 3.0
        assert result.call_count == 2

    @pytest.mark.asyncio
    async def test_summary_groups_by_provider(self) -> None:
        entries = [
            _make_ledger_entry(provider="openai", total_cost=5.0),
            _make_ledger_entry(provider="openai", total_cost=3.0),
            _make_ledger_entry(provider="anthropic", total_cost=2.0),
        ]
        session = _mock_session_exec(entries)

        result = await CostService.get_cost_summary(
            session, TENANT_ID, _admin_user(),
        )

        assert result.by_provider["openai"] == 8.0
        assert result.by_provider["anthropic"] == 2.0

    @pytest.mark.asyncio
    async def test_summary_includes_period(self) -> None:
        session = _mock_session_exec([])
        result = await CostService.get_cost_summary(
            session, TENANT_ID, _admin_user(),
        )
        assert "since" in result.period
        assert "until" in result.period


# ── Budget Set and Check ────────────────────────────────────────────


class TestBudgetSetAndCheck:
    """Budget set and check: allowed, soft_limit, hard_limit."""

    @pytest.mark.asyncio
    async def test_set_budget(self) -> None:
        session = _mock_session_exec([])
        config = BudgetConfig(
            name="team-budget",
            scope=BudgetScope.DEPARTMENT,
            limit_usd=500.0,
            period=BudgetPeriod.MONTHLY,
        )

        with patch("app.services.cost_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            result = await CostService.set_budget(
                session, TENANT_ID, _admin_user(), config,
            )

        assert isinstance(result, BudgetResponse)
        assert result.status == "active"
        session.add.assert_called()
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_check_budget_allowed(self) -> None:
        budget = _make_budget(limit=100.0, spent=10.0, hard_limit=False, alert_threshold_pct=80.0)
        session = _mock_session_exec([budget])

        result = await CostService.check_budget(
            session, TENANT_ID, _admin_user(), estimated_cost=5.0,
        )

        assert result.allowed is True
        assert result.status == "allowed"

    @pytest.mark.asyncio
    async def test_check_budget_soft_limit_warning(self) -> None:
        budget = _make_budget(limit=100.0, spent=75.0, hard_limit=False, alert_threshold_pct=80.0)
        session = _mock_session_exec([budget])

        result = await CostService.check_budget(
            session, TENANT_ID, _admin_user(), estimated_cost=10.0,
        )

        assert result.allowed is True
        assert result.status == "soft_limit_warning"

    @pytest.mark.asyncio
    async def test_check_budget_hard_limit_blocked(self) -> None:
        budget = _make_budget(limit=100.0, spent=98.0, hard_limit=True)
        session = _mock_session_exec([budget])

        result = await CostService.check_budget(
            session, TENANT_ID, _admin_user(), estimated_cost=5.0,
        )

        assert result.allowed is False
        assert result.status == "hard_limit_blocked"

    @pytest.mark.asyncio
    async def test_check_budget_no_budgets_allows(self) -> None:
        session = _mock_session_exec([])
        result = await CostService.check_budget(
            session, TENANT_ID, _admin_user(), estimated_cost=1000.0,
        )
        assert result.allowed is True
        assert result.status == "allowed"


# ── Chargeback Report ───────────────────────────────────────────────


class TestChargebackReport:
    """Chargeback report generation."""

    @pytest.mark.asyncio
    async def test_generates_report(self) -> None:
        entries = [
            _make_ledger_entry(provider="openai", model_id="gpt-4o", total_cost=10.0),
            _make_ledger_entry(provider="openai", model_id="gpt-4o", total_cost=5.0),
            _make_ledger_entry(provider="anthropic", model_id="claude-3-5-sonnet", total_cost=8.0),
        ]
        session = _mock_session_exec(entries)

        with patch("app.services.cost_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            report = await CostService.generate_chargeback_report(
                session, TENANT_ID, _admin_user(),
            )

        assert isinstance(report, ChargebackReport)
        assert report.total == 23.0
        assert len(report.line_items) == 2

    @pytest.mark.asyncio
    async def test_report_with_department_filter(self) -> None:
        dept_id = uuid4()
        entries = [_make_ledger_entry(total_cost=7.0, department_id=dept_id)]
        session = _mock_session_exec(entries)

        with patch("app.services.cost_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            report = await CostService.generate_chargeback_report(
                session, TENANT_ID, _admin_user(), department_id=dept_id,
            )

        assert report.total == 7.0
        assert report.department_id == dept_id

    @pytest.mark.asyncio
    async def test_empty_report(self) -> None:
        session = _mock_session_exec([])

        with patch("app.services.cost_service.AuditLogService") as audit:
            audit.create = AsyncMock()
            report = await CostService.generate_chargeback_report(
                session, TENANT_ID, _admin_user(),
            )

        assert report.total == 0.0
        assert report.line_items == []


# ── Forecast ────────────────────────────────────────────────────────


class TestForecast:
    """Cost forecasting with basic trend detection."""

    @pytest.mark.asyncio
    async def test_forecast_empty_returns_stable(self) -> None:
        session = _mock_session_exec([])

        result = await CostService.forecast_costs(
            session, TENANT_ID, _admin_user(), horizon_days=7,
        )

        assert isinstance(result, CostForecast)
        assert result.trend == "stable"
        assert result.daily_avg == 0.0
        assert result.projected_total == 0.0

    @pytest.mark.asyncio
    async def test_forecast_with_data(self) -> None:
        entries = []
        for i in range(10):
            e = _make_ledger_entry(total_cost=5.0, days_ago=i)
            entries.append(e)
        session = _mock_session_exec(entries)

        result = await CostService.forecast_costs(
            session, TENANT_ID, _admin_user(), horizon_days=30,
        )

        assert result.daily_avg > 0
        assert result.projected_total > 0
        assert len(result.daily_projections) == 30

    @pytest.mark.asyncio
    async def test_forecast_trend_detection(self) -> None:
        entries = []
        # Increasing trend: older entries cheap, newer ones expensive
        for i in range(14):
            cost = 1.0 if i >= 7 else 10.0  # days_ago high = older = cheap
            e = _make_ledger_entry(total_cost=cost, days_ago=i)
            entries.append(e)
        session = _mock_session_exec(entries)

        result = await CostService.forecast_costs(
            session, TENANT_ID, _admin_user(), horizon_days=30,
        )

        assert result.trend in ("increasing", "decreasing", "stable")


# ── Optimization Recommendations ────────────────────────────────────


class TestOptimizationRecommendations:
    """Optimization recommendations based on usage patterns."""

    @pytest.mark.asyncio
    async def test_empty_usage_returns_no_recommendations(self) -> None:
        session = _mock_session_exec([])

        # Need two exec calls: one for ledger entries, one for budgets
        recs = await CostService.get_optimization_recommendations(session, TENANT_ID)

        assert recs == []

    @pytest.mark.asyncio
    async def test_expensive_model_recommendation(self) -> None:
        entries = [_make_ledger_entry(model_id="gpt-4o", total_cost=100.0)]
        # Two exec() calls: entries + budgets
        session = AsyncMock()
        result1 = MagicMock()
        result1.all.return_value = entries
        result2 = MagicMock()
        result2.all.return_value = []
        session.exec = AsyncMock(side_effect=[result1, result2])

        recs = await CostService.get_optimization_recommendations(session, TENANT_ID)

        model_switch = [r for r in recs if r.type == "model_switch"]
        assert len(model_switch) >= 1
        assert model_switch[0].estimated_savings > 0

    @pytest.mark.asyncio
    async def test_high_volume_cache_recommendation(self) -> None:
        entries = [_make_ledger_entry(model_id="gpt-4o-mini", total_cost=0.01) for _ in range(150)]
        session = AsyncMock()
        result1 = MagicMock()
        result1.all.return_value = entries
        result2 = MagicMock()
        result2.all.return_value = []
        session.exec = AsyncMock(side_effect=[result1, result2])

        recs = await CostService.get_optimization_recommendations(session, TENANT_ID)

        cache_recs = [r for r in recs if r.type == "cache_usage"]
        assert len(cache_recs) >= 1

    @pytest.mark.asyncio
    async def test_budget_utilization_recommendation(self) -> None:
        entries = [_make_ledger_entry(total_cost=1.0)]
        budget = _make_budget(limit=100.0, spent=95.0, name="high-usage-budget")
        session = AsyncMock()
        result1 = MagicMock()
        result1.all.return_value = entries
        result2 = MagicMock()
        result2.all.return_value = [budget]
        session.exec = AsyncMock(side_effect=[result1, result2])

        recs = await CostService.get_optimization_recommendations(session, TENANT_ID)

        budget_recs = [r for r in recs if r.type == "budget_adjustment"]
        assert len(budget_recs) >= 1

    @pytest.mark.asyncio
    async def test_recommendations_sorted_by_priority(self) -> None:
        entries = [_make_ledger_entry(model_id="gpt-4o-mini", total_cost=0.01) for _ in range(150)]
        session = AsyncMock()
        result1 = MagicMock()
        result1.all.return_value = entries
        result2 = MagicMock()
        result2.all.return_value = []
        session.exec = AsyncMock(side_effect=[result1, result2])

        recs = await CostService.get_optimization_recommendations(session, TENANT_ID)

        if len(recs) > 1:
            priorities = [r.priority for r in recs]
            assert priorities == sorted(priorities)
