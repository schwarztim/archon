"""Tests for Agent 11 — Cost Engine: routes, service, budget enforcement, export."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
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
    ChargebackLineItem,
    ChargebackReport,
    CostAlert,
    CostForecast,
    CostSummary,
    DailyProjection,
    ProviderPricing,
    Recommendation,
    TokenLedger,
    TokenLedgerEntry,
    UsageEvent,
)
from app.services.cost import CostEngine
from app.services.cost_service import CostService


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "tenant-cost-engine-test"


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
        roles=["developer"],
        permissions=[],
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _make_ledger_entry(
    *,
    provider: str = "openai",
    model_id: str = "gpt-4o",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    total_cost: float = 0.0075,
    tenant_id: str = TENANT_ID,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    department_id: UUID | None = None,
    created_at: datetime | None = None,
) -> TokenLedger:
    return TokenLedger(
        id=uuid4(),
        tenant_id=tenant_id,
        provider=provider,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_cost=total_cost * 0.4,
        output_cost=total_cost * 0.6,
        total_cost=total_cost,
        user_id=user_id,
        agent_id=agent_id,
        department_id=department_id,
        attribution_chain={
            "tenant_id": tenant_id,
            "provider": provider,
            "model": model_id,
        },
        extra_metadata={},
        created_at=created_at or datetime.now(timezone.utc),
    )


def _make_budget(
    *,
    name: str = "Test Budget",
    scope: str = "tenant",
    limit_amount: float = 1000.0,
    spent_amount: float = 0.0,
    enforcement: str = "soft",
    hard_limit: bool = False,
    tenant_id: str = TENANT_ID,
    alert_thresholds: list[float] | None = None,
) -> Budget:
    return Budget(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        scope=scope,
        limit_amount=limit_amount,
        spent_amount=spent_amount,
        enforcement=enforcement,
        hard_limit=hard_limit,
        alert_thresholds=alert_thresholds or [50.0, 75.0, 90.0, 100.0],
        period="monthly",
        period_start=datetime.now(timezone.utc),
        is_active=True,
    )


def _mock_session_exec(entries: list[Any]) -> AsyncMock:
    """Mock session.exec() to return entries."""
    mock_result = MagicMock()
    mock_result.all.return_value = entries
    mock_result.first.return_value = entries[0] if entries else None
    session = AsyncMock()
    session.exec = AsyncMock(return_value=mock_result)
    session.get = AsyncMock(return_value=None)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


# ══════════════════════════════════════════════════════════════════════
# 1. Token Ledger Tests
# ══════════════════════════════════════════════════════════════════════


class TestTokenLedger:
    """Tests for immutable token ledger recording."""

    @pytest.mark.asyncio
    async def test_record_usage_creates_entry(self) -> None:
        """Recording usage creates an immutable ledger entry."""
        session = _mock_session_exec([])

        event = UsageEvent(
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
        )

        with patch.object(CostService, "_calculate_token_cost", return_value=(0.0025, 0.005)):
            entry = await CostService.record_usage(session, TENANT_ID, event)

        assert entry.provider == "openai"
        assert entry.model == "gpt-4o"
        assert entry.input_tokens == 1000
        assert entry.output_tokens == 500
        assert entry.total_tokens == 1500
        assert entry.tenant_id == TENANT_ID

    @pytest.mark.asyncio
    async def test_record_usage_with_explicit_cost(self) -> None:
        """When cost_usd is provided, it overrides calculated cost."""
        session = _mock_session_exec([])

        event = UsageEvent(
            provider="anthropic",
            model="claude-3-5-sonnet",
            input_tokens=2000,
            output_tokens=1000,
            cost_usd=0.05,
        )

        with patch.object(CostService, "_calculate_token_cost", return_value=(0.006, 0.015)):
            entry = await CostService.record_usage(session, TENANT_ID, event)

        assert entry.total_cost == 0.05

    @pytest.mark.asyncio
    async def test_record_usage_with_attribution(self) -> None:
        """Usage records full attribution chain."""
        session = _mock_session_exec([])
        user_id = uuid4()
        agent_id = uuid4()
        dept_id = uuid4()

        event = UsageEvent(
            provider="openai",
            model="gpt-4o",
            input_tokens=500,
            output_tokens=200,
            user_id=user_id,
            agent_id=agent_id,
            department_id=dept_id,
        )

        with patch.object(CostService, "_calculate_token_cost", return_value=(0.00125, 0.002)):
            entry = await CostService.record_usage(session, TENANT_ID, event)

        assert entry.user_id == user_id
        assert entry.agent_id == agent_id
        assert entry.department_id == dept_id
        assert entry.attribution_chain.tenant_id == TENANT_ID
        assert entry.attribution_chain.provider == "openai"

    @pytest.mark.asyncio
    async def test_ledger_entry_from_orm(self) -> None:
        """TokenLedgerEntry.from_orm_entry correctly maps fields."""
        orm_entry = _make_ledger_entry(
            provider="anthropic",
            model_id="claude-3-5-sonnet",
            input_tokens=3000,
            output_tokens=1500,
            total_cost=0.0315,
        )
        pydantic_entry = TokenLedgerEntry.from_orm_entry(orm_entry)
        assert pydantic_entry.provider == "anthropic"
        assert pydantic_entry.model == "claude-3-5-sonnet"
        assert pydantic_entry.input_tokens == 3000
        assert pydantic_entry.output_tokens == 1500
        assert pydantic_entry.total_tokens == 4500


# ══════════════════════════════════════════════════════════════════════
# 2. Cost Summary Tests
# ══════════════════════════════════════════════════════════════════════


class TestCostSummary:
    """Tests for cost summary aggregation."""

    @pytest.mark.asyncio
    async def test_admin_sees_all_costs(self) -> None:
        """Admin user sees all tenant costs."""
        entries = [
            _make_ledger_entry(provider="openai", total_cost=10.0),
            _make_ledger_entry(provider="anthropic", total_cost=5.0),
        ]
        session = _mock_session_exec(entries)
        user = _admin_user()

        summary = await CostService.get_cost_summary(session, TENANT_ID, user)
        assert summary.total_cost == 15.0
        assert summary.call_count == 2
        assert "openai" in summary.by_provider
        assert "anthropic" in summary.by_provider

    @pytest.mark.asyncio
    async def test_summary_with_period_filter(self) -> None:
        """Summary respects since/until period filters."""
        entries = [_make_ledger_entry(total_cost=7.5)]
        session = _mock_session_exec(entries)
        user = _admin_user()

        now = datetime.now(timezone.utc)
        period = {
            "since": (now - timedelta(days=7)).isoformat(),
            "until": now.isoformat(),
        }
        summary = await CostService.get_cost_summary(
            session, TENANT_ID, user, period=period,
        )
        assert summary.total_cost == 7.5

    @pytest.mark.asyncio
    async def test_empty_ledger_returns_zero(self) -> None:
        """Empty ledger returns zero cost summary."""
        session = _mock_session_exec([])
        user = _admin_user()

        summary = await CostService.get_cost_summary(session, TENANT_ID, user)
        assert summary.total_cost == 0.0
        assert summary.call_count == 0


# ══════════════════════════════════════════════════════════════════════
# 3. Budget Management Tests
# ══════════════════════════════════════════════════════════════════════


class TestBudgetManagement:
    """Tests for budget CRUD and enforcement."""

    @pytest.mark.asyncio
    async def test_create_budget(self) -> None:
        """Creating a budget returns a BudgetResponse."""
        session = _mock_session_exec([])
        user = _admin_user()

        config = BudgetConfig(
            name="Test Budget",
            scope=BudgetScope.TENANT,
            limit_usd=5000.0,
            period=BudgetPeriod.MONTHLY,
            hard_limit=False,
        )

        with patch("app.services.cost_service.AuditLogService") as mock_audit:
            mock_audit.create = AsyncMock()
            response = await CostService.set_budget(session, TENANT_ID, user, config)

        assert isinstance(response, BudgetResponse)
        assert response.tenant_id == TENANT_ID
        assert response.config.name == "Test Budget"
        assert response.remaining == 5000.0
        assert response.status == "active"

    @pytest.mark.asyncio
    async def test_budget_check_allowed(self) -> None:
        """Budget check returns allowed when under limit."""
        budget = _make_budget(limit_amount=1000.0, spent_amount=100.0)
        session = _mock_session_exec([budget])
        user = _admin_user()

        result = await CostService.check_budget(session, TENANT_ID, user, 50.0)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_budget_check_hard_block(self) -> None:
        """Budget check blocks when hard limit is exceeded."""
        budget = _make_budget(
            limit_amount=100.0,
            spent_amount=95.0,
            hard_limit=True,
            enforcement="hard",
        )
        session = _mock_session_exec([budget])
        user = _admin_user()

        result = await CostService.check_budget(session, TENANT_ID, user, 10.0)
        assert result.allowed is False
        assert result.status == "hard_limit_blocked"

    @pytest.mark.asyncio
    async def test_budget_check_soft_warning(self) -> None:
        """Budget check warns when soft limit threshold reached."""
        budget = _make_budget(limit_amount=100.0, spent_amount=75.0)
        budget.alert_threshold_pct = 80.0
        session = _mock_session_exec([budget])
        user = _admin_user()

        result = await CostService.check_budget(session, TENANT_ID, user, 10.0)
        assert result.allowed is True
        assert result.status == "soft_limit_warning"

    @pytest.mark.asyncio
    async def test_budget_check_no_budgets(self) -> None:
        """No budgets means execution is always allowed."""
        session = _mock_session_exec([])
        user = _admin_user()

        result = await CostService.check_budget(session, TENANT_ID, user, 100.0)
        assert result.allowed is True
        assert result.status == "allowed"

    def test_budget_utilization_color(self) -> None:
        """Utilization color: green <75%, yellow 75-90%, red >90%."""
        budget_green = _make_budget(limit_amount=1000.0, spent_amount=500.0)
        budget_yellow = _make_budget(limit_amount=1000.0, spent_amount=800.0)
        budget_red = _make_budget(limit_amount=1000.0, spent_amount=950.0)

        pct_green = (budget_green.spent_amount / budget_green.limit_amount * 100)
        pct_yellow = (budget_yellow.spent_amount / budget_yellow.limit_amount * 100)
        pct_red = (budget_red.spent_amount / budget_red.limit_amount * 100)

        assert pct_green < 75
        assert 75 <= pct_yellow < 90
        assert pct_red >= 90


# ══════════════════════════════════════════════════════════════════════
# 4. Alert Threshold Tests
# ══════════════════════════════════════════════════════════════════════


class TestAlertThresholds:
    """Tests for 50/75/90/100% threshold alerts."""

    @pytest.mark.asyncio
    async def test_threshold_crossing_creates_alert(self) -> None:
        """Crossing an alert threshold creates a CostAlert."""
        budget = _make_budget(
            limit_amount=100.0,
            spent_amount=49.0,
            alert_thresholds=[50.0, 75.0, 90.0, 100.0],
        )
        session = _mock_session_exec([budget])

        await CostService._update_budget_spend(
            session,
            tenant_id=TENANT_ID,
            total_cost=2.0,
            agent_id=None,
            user_id=None,
            department_id=None,
        )

        # Check that session.add was called with a CostAlert
        add_calls = session.add.call_args_list
        alert_adds = [c for c in add_calls if isinstance(c[0][0], CostAlert)]
        assert len(alert_adds) >= 1
        alert = alert_adds[0][0][0]
        assert alert.threshold_pct == 50.0
        assert alert.severity == "info"

    @pytest.mark.asyncio
    async def test_critical_alert_at_100_pct(self) -> None:
        """100% threshold generates critical alert."""
        budget = _make_budget(
            limit_amount=100.0,
            spent_amount=99.0,
            alert_thresholds=[100.0],
        )
        session = _mock_session_exec([budget])

        await CostService._update_budget_spend(
            session,
            tenant_id=TENANT_ID,
            total_cost=2.0,
            agent_id=None,
            user_id=None,
            department_id=None,
        )

        add_calls = session.add.call_args_list
        alert_adds = [c for c in add_calls if isinstance(c[0][0], CostAlert)]
        assert len(alert_adds) >= 1
        alert = alert_adds[0][0][0]
        assert alert.threshold_pct == 100.0
        assert alert.severity == "critical"


# ══════════════════════════════════════════════════════════════════════
# 5. Chargeback Report Tests
# ══════════════════════════════════════════════════════════════════════


class TestChargebackReport:
    """Tests for chargeback report generation."""

    @pytest.mark.asyncio
    async def test_chargeback_report_with_entries(self) -> None:
        """Chargeback report aggregates entries by provider+model."""
        entries = [
            _make_ledger_entry(provider="openai", model_id="gpt-4o", total_cost=10.0),
            _make_ledger_entry(provider="openai", model_id="gpt-4o", total_cost=5.0),
            _make_ledger_entry(provider="anthropic", model_id="claude-3-5-sonnet", total_cost=8.0),
        ]
        session = _mock_session_exec(entries)
        user = _finance_user()

        with patch("app.services.cost_service.AuditLogService") as mock_audit:
            mock_audit.create = AsyncMock()
            report = await CostService.generate_chargeback_report(
                session, TENANT_ID, user,
            )

        assert isinstance(report, ChargebackReport)
        assert report.total == 23.0
        assert len(report.line_items) == 2

        # Check line items
        openai_item = next((i for i in report.line_items if i.provider == "openai"), None)
        assert openai_item is not None
        assert openai_item.cost_usd == 15.0
        assert openai_item.call_count == 2

    @pytest.mark.asyncio
    async def test_chargeback_report_empty(self) -> None:
        """Empty chargeback report."""
        session = _mock_session_exec([])
        user = _finance_user()

        with patch("app.services.cost_service.AuditLogService") as mock_audit:
            mock_audit.create = AsyncMock()
            report = await CostService.generate_chargeback_report(
                session, TENANT_ID, user,
            )

        assert report.total == 0.0
        assert len(report.line_items) == 0


# ══════════════════════════════════════════════════════════════════════
# 6. Forecasting Tests
# ══════════════════════════════════════════════════════════════════════


class TestForecasting:
    """Tests for cost forecasting."""

    @pytest.mark.asyncio
    async def test_forecast_with_data(self) -> None:
        """Forecasting generates daily projections."""
        now = datetime.now(timezone.utc)
        entries = []
        for i in range(14):
            entries.append(
                _make_ledger_entry(
                    total_cost=5.0 + (i * 0.1),
                    created_at=now - timedelta(days=14 - i),
                )
            )
        session = _mock_session_exec(entries)
        user = _admin_user()

        forecast = await CostService.forecast_costs(
            session, TENANT_ID, user, horizon_days=7,
        )

        assert isinstance(forecast, CostForecast)
        assert len(forecast.daily_projections) == 7
        assert forecast.daily_avg > 0
        assert forecast.projected_total > 0

    @pytest.mark.asyncio
    async def test_forecast_empty_data(self) -> None:
        """Empty forecast returns zero values."""
        session = _mock_session_exec([])
        user = _admin_user()

        forecast = await CostService.forecast_costs(session, TENANT_ID, user)
        assert forecast.daily_avg == 0.0
        assert forecast.projected_total == 0.0
        assert forecast.trend == "stable"

    @pytest.mark.asyncio
    async def test_forecast_trend_detection(self) -> None:
        """Forecast detects increasing/decreasing/stable trends."""
        now = datetime.now(timezone.utc)
        # Create increasing cost pattern
        entries = []
        for i in range(14):
            cost = 1.0 + (i * 2.0)  # Strongly increasing
            entries.append(
                _make_ledger_entry(
                    total_cost=cost,
                    created_at=now - timedelta(days=14 - i),
                )
            )
        session = _mock_session_exec(entries)
        user = _admin_user()

        forecast = await CostService.forecast_costs(session, TENANT_ID, user)
        assert forecast.trend == "increasing"


# ══════════════════════════════════════════════════════════════════════
# 7. Optimization Recommendations Tests
# ══════════════════════════════════════════════════════════════════════


class TestOptimizationRecommendations:
    """Tests for cost optimization recommendations."""

    @pytest.mark.asyncio
    async def test_expensive_model_recommendation(self) -> None:
        """Detects expensive model usage and recommends cheaper alternatives."""
        entries = [
            _make_ledger_entry(provider="openai", model_id="gpt-4o", total_cost=50.0),
            _make_ledger_entry(provider="openai", model_id="gpt-4o", total_cost=30.0),
            _make_ledger_entry(provider="openai", model_id="gpt-4o-mini", total_cost=5.0),
        ]
        # First exec returns ledger entries, second returns budgets (empty)
        call_count = 0
        async def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.all.return_value = entries
            else:
                mock_result.all.return_value = []
            return mock_result

        session = AsyncMock()
        session.exec = AsyncMock(side_effect=_side_effect)

        recs = await CostService.get_optimization_recommendations(session, TENANT_ID)
        model_switch = [r for r in recs if r.type == "model_switch"]
        assert len(model_switch) > 0

    @pytest.mark.asyncio
    async def test_high_volume_caching_recommendation(self) -> None:
        """Detects high call volume and recommends caching."""
        entries = [
            _make_ledger_entry(provider="openai", model_id="gpt-4o-mini", total_cost=0.01)
            for _ in range(150)
        ]
        # First exec returns ledger entries, second returns budgets (empty)
        call_count = 0
        async def _side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock_result = MagicMock()
            if call_count == 1:
                mock_result.all.return_value = entries
            else:
                mock_result.all.return_value = []
            return mock_result

        session = AsyncMock()
        session.exec = AsyncMock(side_effect=_side_effect)

        recs = await CostService.get_optimization_recommendations(session, TENANT_ID)
        cache_recs = [r for r in recs if r.type == "cache_usage"]
        assert len(cache_recs) > 0

    @pytest.mark.asyncio
    async def test_no_recommendations_on_empty(self) -> None:
        """No entries yields no recommendations."""
        session = _mock_session_exec([])

        recs = await CostService.get_optimization_recommendations(session, TENANT_ID)
        assert len(recs) == 0


# ══════════════════════════════════════════════════════════════════════
# 8. Budget Enforcement (429) Tests
# ══════════════════════════════════════════════════════════════════════


class TestBudgetEnforcement:
    """Tests for HTTP 429 hard budget enforcement."""

    @pytest.mark.asyncio
    async def test_hard_limit_raises_429(self) -> None:
        """check_budget_enforcement raises HTTP 429 on hard limit."""
        from fastapi import HTTPException
        from app.routes.cost import check_budget_enforcement

        blocked_result = BudgetCheckResult(
            allowed=False,
            budget_id=uuid4(),
            usage_pct=105.0,
            warning_message="Hard budget limit exceeded",
            status="hard_limit_blocked",
        )

        session = AsyncMock()
        user = _admin_user()

        with patch.object(CostService, "check_budget", return_value=blocked_result):
            with pytest.raises(HTTPException) as exc_info:
                await check_budget_enforcement(session, TENANT_ID, user, 10.0)
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_soft_limit_does_not_raise(self) -> None:
        """Soft limit does not raise 429."""
        from app.routes.cost import check_budget_enforcement

        allowed_result = BudgetCheckResult(
            allowed=True,
            status="soft_limit_warning",
        )

        session = AsyncMock()
        user = _admin_user()

        with patch.object(CostService, "check_budget", return_value=allowed_result):
            # Should not raise
            await check_budget_enforcement(session, TENANT_ID, user, 10.0)


# ══════════════════════════════════════════════════════════════════════
# 9. Legacy CostEngine Tests
# ══════════════════════════════════════════════════════════════════════


class TestCostEngineLegacy:
    """Tests for legacy CostEngine service."""

    @pytest.mark.asyncio
    async def test_record_usage_legacy(self) -> None:
        """Legacy record_usage creates a TokenLedger entry."""
        session = _mock_session_exec([])

        with patch.object(CostEngine, "_calculate_token_cost", return_value=(0.0025, 0.005)):
            entry = await CostEngine.record_usage(
                session,
                provider="openai",
                model_id="gpt-4o",
                input_tokens=1000,
                output_tokens=500,
            )

        assert isinstance(entry, TokenLedger)
        session.add.assert_called()

    @pytest.mark.asyncio
    async def test_list_budgets_legacy(self) -> None:
        """Legacy list_budgets returns paginated results."""
        budgets = [_make_budget(name=f"Budget {i}") for i in range(3)]
        session = _mock_session_exec(budgets)

        result, total = await CostEngine.list_budgets(session)
        assert total == 3
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_calculate_cost(self) -> None:
        """Cost calculation returns breakdown."""
        session = _mock_session_exec([])

        with patch.object(CostEngine, "_calculate_token_cost", return_value=(0.005, 0.01)):
            result = await CostEngine.calculate_cost(
                session,
                provider="openai",
                model_id="gpt-4o",
                input_tokens=2000,
                output_tokens=1000,
            )

        assert result["input_cost"] == 0.005
        assert result["output_cost"] == 0.01
        assert result["total_cost"] == 0.015

    @pytest.mark.asyncio
    async def test_create_and_delete_budget(self) -> None:
        """Budget can be created and deleted."""
        budget = _make_budget()
        session = _mock_session_exec([])
        session.get = AsyncMock(return_value=budget)

        created = await CostEngine.create_budget(session, budget)
        assert created.name == "Test Budget"

        deleted = await CostEngine.delete_budget(session, budget.id)
        assert deleted is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_budget(self) -> None:
        """Deleting nonexistent budget returns False."""
        session = _mock_session_exec([])
        session.get = AsyncMock(return_value=None)

        deleted = await CostEngine.delete_budget(session, uuid4())
        assert deleted is False

    @pytest.mark.asyncio
    async def test_update_budget(self) -> None:
        """Budget update modifies fields."""
        budget = _make_budget(limit_amount=500.0)
        session = _mock_session_exec([])
        session.get = AsyncMock(return_value=budget)

        updated = await CostEngine.update_budget(
            session, budget.id, {"limit_amount": 1000.0},
        )
        assert updated is not None
        assert updated.limit_amount == 1000.0

    @pytest.mark.asyncio
    async def test_forecast_with_budget(self) -> None:
        """Forecast scoped to a budget."""
        budget = _make_budget(limit_amount=1000.0, spent_amount=500.0)
        budget.agent_id = uuid4()

        now = datetime.now(timezone.utc)
        entries = [
            _make_ledger_entry(total_cost=10.0, created_at=now - timedelta(days=i))
            for i in range(7)
        ]
        session = _mock_session_exec(entries)
        session.get = AsyncMock(return_value=budget)

        result = await CostEngine.forecast(
            session, budget_id=budget.id, days_ahead=14,
        )
        assert result["daily_avg_cost"] > 0
        assert result["projected_cost"] > 0

    @pytest.mark.asyncio
    async def test_check_budget_legacy_hard_block(self) -> None:
        """Legacy check_budget returns blocked for exhausted hard budgets."""
        budget = _make_budget(
            limit_amount=100.0,
            spent_amount=100.0,
            enforcement="hard",
        )
        session = _mock_session_exec([budget])

        result = await CostEngine.check_budget(session, department_id=uuid4())
        assert result["allowed"] is False


# ══════════════════════════════════════════════════════════════════════
# 10. Pricing Tests
# ══════════════════════════════════════════════════════════════════════


class TestPricing:
    """Tests for provider pricing lookup."""

    @pytest.mark.asyncio
    async def test_calculate_with_db_pricing(self) -> None:
        """Uses DB pricing when available."""
        pricing = ProviderPricing(
            provider="openai",
            model_id="gpt-4o",
            cost_per_input_token=3.0,
            cost_per_output_token=12.0,
            is_active=True,
        )
        mock_result = MagicMock()
        mock_result.first.return_value = pricing
        session = AsyncMock()
        session.exec = AsyncMock(return_value=mock_result)

        input_cost, output_cost = await CostEngine._calculate_token_cost(
            session,
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        assert input_cost == 3.0
        assert output_cost == 12.0

    @pytest.mark.asyncio
    async def test_calculate_with_default_pricing(self) -> None:
        """Falls back to default pricing when no DB entry."""
        mock_result = MagicMock()
        mock_result.first.return_value = None
        session = AsyncMock()
        session.exec = AsyncMock(return_value=mock_result)

        input_cost, output_cost = await CostEngine._calculate_token_cost(
            session,
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # Default: gpt-4o is (2.50, 10.00) per 1M tokens
        assert input_cost == 2.5
        assert output_cost == 10.0


# ══════════════════════════════════════════════════════════════════════
# 11. Model Tests
# ══════════════════════════════════════════════════════════════════════


class TestModels:
    """Tests for Pydantic/SQLModel schemas."""

    def test_token_ledger_defaults(self) -> None:
        """TokenLedger has correct defaults."""
        entry = TokenLedger(
            tenant_id=TENANT_ID,
            provider="openai",
            model_id="gpt-4o",
        )
        assert entry.input_tokens == 0
        assert entry.output_tokens == 0
        assert entry.total_cost == 0.0
        assert entry.latency_ms == 0.0
        assert isinstance(entry.id, UUID)

    def test_usage_event_validation(self) -> None:
        """UsageEvent validates non-negative tokens."""
        event = UsageEvent(
            provider="openai",
            model="gpt-4o",
            input_tokens=100,
            output_tokens=50,
        )
        assert event.input_tokens == 100

        with pytest.raises(Exception):
            UsageEvent(
                provider="openai",
                model="gpt-4o",
                input_tokens=-1,
                output_tokens=50,
            )

    def test_budget_scope_enum(self) -> None:
        """BudgetScope enum values."""
        assert BudgetScope.TENANT == "tenant"
        assert BudgetScope.DEPARTMENT == "department"
        assert BudgetScope.USER == "user"

    def test_budget_period_enum(self) -> None:
        """BudgetPeriod enum values."""
        assert BudgetPeriod.DAILY == "daily"
        assert BudgetPeriod.WEEKLY == "weekly"
        assert BudgetPeriod.MONTHLY == "monthly"
        assert BudgetPeriod.TOTAL == "total"

    def test_cost_summary_fields(self) -> None:
        """CostSummary has expected default fields."""
        summary = CostSummary(total_cost=0.0)
        assert summary.total_input_tokens == 0
        assert summary.total_output_tokens == 0
        assert summary.call_count == 0
        assert summary.by_provider == {}

    def test_chargeback_line_item(self) -> None:
        """ChargebackLineItem holds per-model data."""
        item = ChargebackLineItem(
            provider="openai",
            model="gpt-4o",
            call_count=100,
            input_tokens=50000,
            output_tokens=25000,
            cost_usd=12.50,
        )
        assert item.cost_usd == 12.50
        assert item.call_count == 100

    def test_recommendation_priority(self) -> None:
        """Recommendation priority must be between 1-5."""
        rec = Recommendation(
            type="model_switch",
            description="Switch to cheaper model",
            estimated_savings=100.0,
            priority=1,
        )
        assert rec.priority == 1
        assert rec.effort == "low"

    def test_cost_forecast_defaults(self) -> None:
        """CostForecast has correct defaults."""
        forecast = CostForecast()
        assert forecast.trend == "stable"
        assert forecast.daily_avg == 0.0
        assert forecast.projected_total == 0.0
        assert forecast.daily_projections == []

    def test_budget_check_result(self) -> None:
        """BudgetCheckResult blocked status."""
        result = BudgetCheckResult(
            allowed=False,
            budget_id=uuid4(),
            usage_pct=105.0,
            status="hard_limit_blocked",
            warning_message="Budget exceeded",
        )
        assert result.allowed is False
        assert result.status == "hard_limit_blocked"

    def test_daily_projection(self) -> None:
        """DailyProjection fields."""
        proj = DailyProjection(
            date="2024-01-15",
            projected_cost=10.50,
            cumulative_cost=105.0,
        )
        assert proj.date == "2024-01-15"
        assert proj.projected_cost == 10.50

    def test_cost_alert_model(self) -> None:
        """CostAlert model."""
        alert = CostAlert(
            budget_id=uuid4(),
            alert_type="threshold",
            severity="warning",
            threshold_pct=75.0,
            current_spend=75.0,
            budget_limit=100.0,
            message="Budget at 75%",
        )
        assert alert.is_acknowledged is False
        assert alert.severity == "warning"


# ══════════════════════════════════════════════════════════════════════
# 12. Reconciliation Tests
# ══════════════════════════════════════════════════════════════════════


class TestReconciliation:
    """Tests for invoice reconciliation."""

    @pytest.mark.asyncio
    async def test_reconcile_matched(self) -> None:
        """Reconciliation matches when ledger ≈ invoice."""
        entries = [
            _make_ledger_entry(provider="openai", model_id="gpt-4o", total_cost=100.0),
        ]
        session = _mock_session_exec(entries)

        invoice_data = {
            "period": {},
            "total": 100.0,
            "by_model": {"gpt-4o": 100.0},
        }

        result = await CostService.reconcile_provider_invoice(
            session, TENANT_ID, "openai", invoice_data,
        )
        assert result.status == "matched"
        assert result.match_pct >= 99.0

    @pytest.mark.asyncio
    async def test_reconcile_discrepancy(self) -> None:
        """Reconciliation detects discrepancy."""
        entries = [
            _make_ledger_entry(provider="openai", model_id="gpt-4o", total_cost=90.0),
        ]
        session = _mock_session_exec(entries)

        invoice_data = {
            "period": {},
            "total": 100.0,
            "by_model": {"gpt-4o": 100.0},
        }

        result = await CostService.reconcile_provider_invoice(
            session, TENANT_ID, "openai", invoice_data,
        )
        assert result.status == "discrepancy"


# ══════════════════════════════════════════════════════════════════════
# 13. Route-level Tests (Request/Response schemas)
# ══════════════════════════════════════════════════════════════════════


class TestRouteSchemas:
    """Tests for route request/response schemas."""

    def test_record_usage_request_validation(self) -> None:
        """RecordUsageRequest validates fields."""
        from app.routes.cost import RecordUsageRequest

        req = RecordUsageRequest(
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
        )
        assert req.provider == "openai"
        assert req.cost_usd is None

    def test_budget_create_schema(self) -> None:
        """BudgetCreate schema validation."""
        from app.routes.cost import BudgetCreate

        bc = BudgetCreate(
            name="Test",
            scope="department",
            limit_amount=500.0,
            period="monthly",
        )
        assert bc.enforcement == "soft"

    def test_budget_update_schema(self) -> None:
        """BudgetUpdate schema partial update."""
        from app.routes.cost import BudgetUpdate

        bu = BudgetUpdate(limit_amount=1000.0)
        data = bu.model_dump(exclude_unset=True)
        assert "limit_amount" in data
        assert "name" not in data

    def test_budget_wizard_create_schema(self) -> None:
        """BudgetWizardCreate schema validation."""
        from app.routes.cost import BudgetWizardCreate

        bwc = BudgetWizardCreate(
            name="Production LLM",
            scope="tenant",
            limit_amount=5000.0,
            period="monthly",
            enforcement="hard",
        )
        assert bwc.enforcement == "hard"
        assert bwc.alert_thresholds == [50.0, 75.0, 90.0, 100.0]

    def test_meta_helper(self) -> None:
        """_meta helper builds standard envelope."""
        from app.routes.cost import _meta

        meta = _meta(request_id="test-123")
        assert meta["request_id"] == "test-123"
        assert "timestamp" in meta

    def test_meta_helper_auto_request_id(self) -> None:
        """_meta auto-generates request_id."""
        from app.routes.cost import _meta

        meta = _meta()
        assert len(meta["request_id"]) > 0


# ══════════════════════════════════════════════════════════════════════
# 14. Alerts Service Tests
# ══════════════════════════════════════════════════════════════════════


class TestAlerts:
    """Tests for alert management."""

    @pytest.mark.asyncio
    async def test_list_alerts(self) -> None:
        """List alerts with pagination."""
        alerts = [
            CostAlert(
                budget_id=uuid4(),
                alert_type="threshold",
                severity="warning",
                threshold_pct=75.0,
                current_spend=750.0,
                budget_limit=1000.0,
                message="75% threshold reached",
            )
        ]
        session = _mock_session_exec(alerts)

        result, total = await CostEngine.list_alerts(session)
        assert total == 1
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self) -> None:
        """Acknowledging an alert sets flags."""
        alert = CostAlert(
            id=uuid4(),
            budget_id=uuid4(),
            alert_type="threshold",
            severity="warning",
            threshold_pct=75.0,
            current_spend=750.0,
            budget_limit=1000.0,
            message="75% threshold reached",
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=alert)
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        result = await CostEngine.acknowledge_alert(session, alert.id)
        assert result is not None
        assert result.is_acknowledged is True

    @pytest.mark.asyncio
    async def test_acknowledge_nonexistent_alert(self) -> None:
        """Acknowledging nonexistent alert returns None."""
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        result = await CostEngine.acknowledge_alert(session, uuid4())
        assert result is None
