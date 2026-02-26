"""Unit tests for CostEngine — token ledger, cost calculation, budget CRUD,
budget limit checks, forecasting, alerts, and provider pricing CRUD.

All tests mock the async database session so no live DB is required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.models.cost import Budget, CostAlert, ProviderPricing, TokenLedger
from app.services.cost import CostEngine, _DEFAULT_PRICING

# ── Fixed UUIDs ─────────────────────────────────────────────────────

BUDGET_ID = UUID("bb000001-0001-0001-0001-000000000001")
AGENT_ID = UUID("aa000001-0001-0001-0001-000000000001")
USER_ID = UUID("00000001-0001-0001-0001-000000000001")
DEPT_ID = UUID("dd000001-0001-0001-0001-000000000001")
ALERT_ID = UUID("cc000001-0001-0001-0001-000000000001")
PRICING_ID = UUID("00000002-0002-0002-0002-000000000002")
ENTRY_ID = UUID("ee000001-0001-0001-0001-000000000001")
ACK_USER_ID = UUID("00000003-0003-0003-0003-000000000003")
NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ── Factories ───────────────────────────────────────────────────────


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _budget(
    *,
    bid: UUID = BUDGET_ID,
    name: str = "Test Budget",
    scope: str = "department",
    department_id: UUID | None = DEPT_ID,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
    limit_amount: float = 100.0,
    spent_amount: float = 0.0,
    enforcement: str = "soft",
    is_active: bool = True,
    alert_thresholds: list[float] | None = None,
) -> Budget:
    """Build a Budget with controllable fields."""
    return Budget(
        id=bid,
        name=name,
        scope=scope,
        department_id=department_id,
        user_id=user_id,
        agent_id=agent_id,
        limit_amount=limit_amount,
        spent_amount=spent_amount,
        enforcement=enforcement,
        is_active=is_active,
        alert_thresholds=alert_thresholds if alert_thresholds is not None else [50.0, 75.0, 90.0, 100.0],
        created_at=NOW,
        updated_at=NOW,
    )


def _pricing(
    *,
    pid: UUID = PRICING_ID,
    provider: str = "openai",
    model_id: str = "gpt-4o",
    cost_per_input_token: float = 5.0,
    cost_per_output_token: float = 15.0,
    is_active: bool = True,
) -> ProviderPricing:
    """Build a ProviderPricing with controllable fields."""
    return ProviderPricing(
        id=pid,
        provider=provider,
        model_id=model_id,
        display_name=f"{provider}/{model_id}",
        cost_per_input_token=cost_per_input_token,
        cost_per_output_token=cost_per_output_token,
        is_active=is_active,
        effective_from=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _alert(
    *,
    aid: UUID = ALERT_ID,
    budget_id: UUID = BUDGET_ID,
    alert_type: str = "threshold",
    severity: str = "warning",
    threshold_pct: float = 75.0,
    current_spend: float = 80.0,
    budget_limit: float = 100.0,
    is_acknowledged: bool = False,
) -> CostAlert:
    """Build a CostAlert with controllable fields."""
    return CostAlert(
        id=aid,
        budget_id=budget_id,
        alert_type=alert_type,
        severity=severity,
        threshold_pct=threshold_pct,
        current_spend=current_spend,
        budget_limit=budget_limit,
        message=f"Budget reached {threshold_pct}%",
        is_acknowledged=is_acknowledged,
        created_at=NOW,
    )


def _ledger_entry(
    *,
    eid: UUID | None = None,
    provider: str = "openai",
    model_id: str = "gpt-4o",
    input_tokens: int = 1000,
    output_tokens: int = 500,
    total_cost: float = 0.0075,
    created_at: datetime | None = None,
) -> TokenLedger:
    """Build a TokenLedger entry with controllable fields."""
    return TokenLedger(
        id=eid or uuid4(),
        provider=provider,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        input_cost=total_cost * 0.4,
        output_cost=total_cost * 0.6,
        total_cost=total_cost,
        latency_ms=150.0,
        extra_metadata={},
        created_at=created_at or NOW,
    )


def _exec_result(rows: list[Any]) -> MagicMock:
    """Create a mock result object whose .all() and .first() work."""
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


# ═══════════════════════════════════════════════════════════════════
# Cost Calculation
# ═══════════════════════════════════════════════════════════════════


class TestCostCalculation:
    """Tests for calculate_cost and _calculate_token_cost."""

    @pytest.mark.asyncio
    async def test_calculate_cost_uses_default_pricing(self) -> None:
        """When no DB pricing exists, falls back to _DEFAULT_PRICING."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.calculate_cost(
            session, provider="openai", model_id="gpt-4o",
            input_tokens=1_000_000, output_tokens=1_000_000,
        )

        assert result["input_cost"] == 2.50
        assert result["output_cost"] == 10.00
        assert result["total_cost"] == 12.50

    @pytest.mark.asyncio
    async def test_calculate_cost_uses_db_pricing_when_available(self) -> None:
        """DB pricing overrides default pricing."""
        session = _mock_session()
        custom = _pricing(cost_per_input_token=5.0, cost_per_output_token=20.0)
        session.exec = AsyncMock(return_value=_exec_result([custom]))

        result = await CostEngine.calculate_cost(
            session, provider="openai", model_id="gpt-4o",
            input_tokens=1_000_000, output_tokens=1_000_000,
        )

        assert result["input_cost"] == 5.0
        assert result["output_cost"] == 20.0
        assert result["total_cost"] == 25.0

    @pytest.mark.asyncio
    async def test_calculate_cost_unknown_provider_returns_zero(self) -> None:
        """Unknown provider/model returns zero cost."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.calculate_cost(
            session, provider="unknown_provider", model_id="nonexistent",
            input_tokens=1000, output_tokens=500,
        )

        assert result["input_cost"] == 0.0
        assert result["output_cost"] == 0.0
        assert result["total_cost"] == 0.0

    @pytest.mark.asyncio
    async def test_calculate_cost_zero_tokens(self) -> None:
        """Zero tokens should yield zero cost."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.calculate_cost(
            session, provider="openai", model_id="gpt-4o",
            input_tokens=0, output_tokens=0,
        )

        assert result["total_cost"] == 0.0

    @pytest.mark.asyncio
    async def test_calculate_cost_anthropic_defaults(self) -> None:
        """Verify Anthropic default pricing is used correctly."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.calculate_cost(
            session, provider="anthropic", model_id="claude-3-5-sonnet",
            input_tokens=1_000_000, output_tokens=1_000_000,
        )

        assert result["input_cost"] == 3.0
        assert result["output_cost"] == 15.0

    @pytest.mark.asyncio
    async def test_calculate_cost_small_token_count(self) -> None:
        """Cost calculation rounds properly for small token counts."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.calculate_cost(
            session, provider="openai", model_id="gpt-4o",
            input_tokens=100, output_tokens=50,
        )

        # 100 / 1M * 2.50 = 0.00025, 50 / 1M * 10.0 = 0.0005
        assert result["input_cost"] == 0.00025
        assert result["output_cost"] == 0.0005


# ═══════════════════════════════════════════════════════════════════
# Token Ledger — record_usage
# ═══════════════════════════════════════════════════════════════════


class TestRecordUsage:
    """Tests for record_usage (token ledger recording)."""

    @pytest.mark.asyncio
    async def test_record_usage_creates_entry(self) -> None:
        """record_usage should add a TokenLedger entry, flush, commit, and refresh."""
        session = _mock_session()
        # _calculate_token_cost query
        session.exec = AsyncMock(return_value=_exec_result([]))
        # _update_budget_spend queries: 3 scope checks + 1 global = 4 calls,
        # but only the relevant ones fire. For no matching scope IDs, just global.
        # We need exec to return empty results for budget queries after the pricing query.
        pricing_result = _exec_result([])
        budget_empty = _exec_result([])
        session.exec = AsyncMock(side_effect=[pricing_result, budget_empty])

        entry = await CostEngine.record_usage(
            session,
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            latency_ms=150.0,
        )

        assert entry.provider == "openai"
        assert entry.model_id == "gpt-4o"
        assert entry.input_tokens == 1000
        assert entry.output_tokens == 500
        assert entry.total_tokens == 1500
        session.add.assert_called()
        session.flush.assert_awaited_once()
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_usage_calculates_cost(self) -> None:
        """Recorded entry should have correct cost from default pricing."""
        session = _mock_session()
        pricing_result = _exec_result([])
        budget_empty = _exec_result([])
        session.exec = AsyncMock(side_effect=[pricing_result, budget_empty])

        entry = await CostEngine.record_usage(
            session,
            provider="openai",
            model_id="gpt-4o",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        assert entry.input_cost == 2.5
        assert entry.output_cost == 10.0
        assert entry.total_cost == 12.5

    @pytest.mark.asyncio
    async def test_record_usage_with_metadata(self) -> None:
        """Extra metadata should be stored on the entry."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([]), _exec_result([])])

        entry = await CostEngine.record_usage(
            session,
            provider="openai",
            model_id="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            metadata={"task": "summarization"},
        )

        assert entry.extra_metadata == {"task": "summarization"}

    @pytest.mark.asyncio
    async def test_record_usage_none_metadata_defaults_to_dict(self) -> None:
        """When metadata is None, extra_metadata should default to empty dict."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([]), _exec_result([])])

        entry = await CostEngine.record_usage(
            session,
            provider="openai",
            model_id="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            metadata=None,
        )

        assert entry.extra_metadata == {}

    @pytest.mark.asyncio
    async def test_record_usage_with_scope_ids(self) -> None:
        """record_usage propagates agent_id, user_id, department_id to the entry."""
        session = _mock_session()
        # Pricing + budget scope queries (department_id + user_id + agent_id = 3, + global = 4)
        session.exec = AsyncMock(side_effect=[
            _exec_result([]),  # pricing
            _exec_result([]),  # agent_id budget
            _exec_result([]),  # user_id budget
            _exec_result([]),  # department_id budget
            _exec_result([]),  # global budget
        ])

        entry = await CostEngine.record_usage(
            session,
            provider="openai",
            model_id="gpt-4o",
            input_tokens=100,
            output_tokens=50,
            agent_id=AGENT_ID,
            user_id=USER_ID,
            department_id=DEPT_ID,
        )

        assert entry.agent_id == AGENT_ID
        assert entry.user_id == USER_ID
        assert entry.department_id == DEPT_ID


# ═══════════════════════════════════════════════════════════════════
# Token Ledger — get_ledger_entry
# ═══════════════════════════════════════════════════════════════════


class TestGetLedgerEntry:
    """Tests for get_ledger_entry."""

    @pytest.mark.asyncio
    async def test_get_existing_entry(self) -> None:
        """Returns entry when found."""
        entry = _ledger_entry(eid=ENTRY_ID)
        session = _mock_session()
        session.get = AsyncMock(return_value=entry)

        result = await CostEngine.get_ledger_entry(session, ENTRY_ID)

        assert result is not None
        assert result.id == ENTRY_ID
        session.get.assert_awaited_once_with(TokenLedger, ENTRY_ID)

    @pytest.mark.asyncio
    async def test_get_nonexistent_entry(self) -> None:
        """Returns None when entry does not exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await CostEngine.get_ledger_entry(session, uuid4())

        assert result is None


# ═══════════════════════════════════════════════════════════════════
# Token Ledger — list_ledger
# ═══════════════════════════════════════════════════════════════════


class TestListLedger:
    """Tests for list_ledger."""

    @pytest.mark.asyncio
    async def test_list_ledger_returns_entries_and_count(self) -> None:
        """list_ledger returns (entries, total_count) tuple."""
        entries = [_ledger_entry(), _ledger_entry()]
        session = _mock_session()
        count_result = _exec_result(entries)
        page_result = _exec_result(entries)
        session.exec = AsyncMock(side_effect=[count_result, page_result])

        result_entries, total = await CostEngine.list_ledger(session)

        assert len(result_entries) == 2
        assert total == 2

    @pytest.mark.asyncio
    async def test_list_ledger_empty(self) -> None:
        """list_ledger returns empty list and zero count when no entries."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([]), _exec_result([])])

        result_entries, total = await CostEngine.list_ledger(session)

        assert result_entries == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_ledger_with_filters(self) -> None:
        """list_ledger with filters still calls session.exec twice."""
        entry = _ledger_entry(provider="anthropic")
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([entry]), _exec_result([entry])])

        result_entries, total = await CostEngine.list_ledger(
            session, provider="anthropic", model_id="claude-3-5-sonnet",
            limit=10, offset=0,
        )

        assert total == 1
        assert len(result_entries) == 1
        assert session.exec.await_count == 2


# ═══════════════════════════════════════════════════════════════════
# Budget CRUD
# ═══════════════════════════════════════════════════════════════════


class TestBudgetCRUD:
    """Tests for budget create, read, update, delete operations."""

    @pytest.mark.asyncio
    async def test_create_budget(self) -> None:
        """create_budget adds, commits, and refreshes."""
        budget = _budget()
        session = _mock_session()

        result = await CostEngine.create_budget(session, budget)

        assert result.name == "Test Budget"
        assert result.limit_amount == 100.0
        session.add.assert_called_once_with(budget)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(budget)

    @pytest.mark.asyncio
    async def test_get_budget_found(self) -> None:
        """get_budget returns budget when found."""
        budget = _budget()
        session = _mock_session()
        session.get = AsyncMock(return_value=budget)

        result = await CostEngine.get_budget(session, BUDGET_ID)

        assert result is not None
        assert result.id == BUDGET_ID

    @pytest.mark.asyncio
    async def test_get_budget_not_found(self) -> None:
        """get_budget returns None when not found."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await CostEngine.get_budget(session, uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_list_budgets_returns_paginated(self) -> None:
        """list_budgets returns (budgets, total) tuple."""
        budgets = [_budget(), _budget(bid=uuid4(), name="Budget 2")]
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result(budgets), _exec_result(budgets)])

        result_budgets, total = await CostEngine.list_budgets(session)

        assert len(result_budgets) == 2
        assert total == 2

    @pytest.mark.asyncio
    async def test_list_budgets_with_scope_filter(self) -> None:
        """list_budgets filters by scope."""
        budget = _budget(scope="agent")
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([budget]), _exec_result([budget])])

        result_budgets, total = await CostEngine.list_budgets(session, scope="agent")

        assert total == 1

    @pytest.mark.asyncio
    async def test_list_budgets_with_active_filter(self) -> None:
        """list_budgets filters by is_active."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([]), _exec_result([])])

        result_budgets, total = await CostEngine.list_budgets(session, is_active=False)

        assert total == 0

    @pytest.mark.asyncio
    async def test_update_budget_success(self) -> None:
        """update_budget patches fields and commits."""
        budget = _budget()
        session = _mock_session()
        session.get = AsyncMock(return_value=budget)

        result = await CostEngine.update_budget(
            session, BUDGET_ID, {"name": "Updated", "limit_amount": 200.0},
        )

        assert result is not None
        assert result.name == "Updated"
        assert result.limit_amount == 200.0
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_budget_not_found(self) -> None:
        """update_budget returns None when budget doesn't exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await CostEngine.update_budget(session, uuid4(), {"name": "x"})

        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_budget_ignores_unknown_fields(self) -> None:
        """update_budget skips fields not present on the model."""
        budget = _budget()
        session = _mock_session()
        session.get = AsyncMock(return_value=budget)

        result = await CostEngine.update_budget(
            session, BUDGET_ID, {"nonexistent_field": 42, "name": "Valid"},
        )

        assert result is not None
        assert result.name == "Valid"
        assert not hasattr(result, "nonexistent_field")

    @pytest.mark.asyncio
    async def test_delete_budget_success(self) -> None:
        """delete_budget returns True and commits when budget exists."""
        budget = _budget()
        session = _mock_session()
        session.get = AsyncMock(return_value=budget)

        result = await CostEngine.delete_budget(session, BUDGET_ID)

        assert result is True
        session.delete.assert_awaited_once_with(budget)
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_budget_not_found(self) -> None:
        """delete_budget returns False when budget doesn't exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await CostEngine.delete_budget(session, uuid4())

        assert result is False
        session.commit.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════
# Budget Limit Checks
# ═══════════════════════════════════════════════════════════════════


class TestCheckBudget:
    """Tests for check_budget — budget limit checking and enforcement."""

    @pytest.mark.asyncio
    async def test_no_budgets_allows_execution(self) -> None:
        """When no budgets match, execution is allowed."""
        session = _mock_session()
        # global budget query returns empty
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.check_budget(session)

        assert result["allowed"] is True
        assert result["budgets"] == []
        assert result["reason"] is None

    @pytest.mark.asyncio
    async def test_soft_budget_exceeded_still_allows(self) -> None:
        """Soft enforcement budget over limit still allows execution."""
        budget = _budget(
            enforcement="soft",
            limit_amount=100.0,
            spent_amount=150.0,
        )
        session = _mock_session()
        # global budget query
        session.exec = AsyncMock(return_value=_exec_result([budget]))

        result = await CostEngine.check_budget(session)

        assert result["allowed"] is True
        assert len(result["budgets"]) == 1
        assert result["budgets"][0]["pct_used"] == 150.0

    @pytest.mark.asyncio
    async def test_hard_budget_exceeded_blocks(self) -> None:
        """Hard enforcement budget at/over limit blocks execution."""
        budget = _budget(
            enforcement="hard",
            limit_amount=100.0,
            spent_amount=100.0,
        )
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([budget]))

        result = await CostEngine.check_budget(session)

        assert result["allowed"] is False
        assert "exhausted" in result["reason"]

    @pytest.mark.asyncio
    async def test_hard_budget_under_limit_allows(self) -> None:
        """Hard enforcement budget under limit allows execution."""
        budget = _budget(
            enforcement="hard",
            limit_amount=100.0,
            spent_amount=50.0,
        )
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([budget]))

        result = await CostEngine.check_budget(session)

        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_check_budget_with_agent_id(self) -> None:
        """check_budget queries by agent_id scope."""
        budget = _budget(scope="agent", agent_id=AGENT_ID, department_id=None)
        session = _mock_session()
        agent_result = _exec_result([budget])
        global_result = _exec_result([])
        session.exec = AsyncMock(side_effect=[agent_result, global_result])

        result = await CostEngine.check_budget(session, agent_id=AGENT_ID)

        assert result["allowed"] is True
        assert len(result["budgets"]) == 1

    @pytest.mark.asyncio
    async def test_check_budget_remaining_calculation(self) -> None:
        """Budget status includes correct remaining amount and percentage."""
        budget = _budget(limit_amount=200.0, spent_amount=80.0)
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([budget]))

        result = await CostEngine.check_budget(session)
        status = result["budgets"][0]

        assert status["remaining"] == 120.0
        assert status["pct_used"] == 40.0
        assert status["limit"] == 200.0
        assert status["spent"] == 80.0

    @pytest.mark.asyncio
    async def test_check_budget_zero_limit(self) -> None:
        """Budget with zero limit_amount reports 0% used, no division error."""
        budget = _budget(limit_amount=0.0, spent_amount=0.0, enforcement="hard")
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([budget]))

        result = await CostEngine.check_budget(session)

        status = result["budgets"][0]
        assert status["pct_used"] == 0.0
        # remaining = 0 - 0 = 0, so hard limit check: remaining <= 0 → blocked
        assert result["allowed"] is False


# ═══════════════════════════════════════════════════════════════════
# Budget Spend Updates & Alert Emission
# ═══════════════════════════════════════════════════════════════════


class TestUpdateBudgetSpend:
    """Tests for _update_budget_spend (called internally by record_usage)."""

    @pytest.mark.asyncio
    async def test_budget_spend_incremented(self) -> None:
        """_update_budget_spend increments spent_amount on matching budgets."""
        budget = _budget(spent_amount=10.0, limit_amount=100.0)
        session = _mock_session()
        # department_id match + global query
        session.exec = AsyncMock(side_effect=[
            _exec_result([budget]),  # department budget
            _exec_result([]),        # global budget
        ])

        await CostEngine._update_budget_spend(
            session, total_cost=5.0,
            agent_id=None, user_id=None, department_id=DEPT_ID,
        )

        assert budget.spent_amount == 15.0

    @pytest.mark.asyncio
    async def test_alert_emitted_on_threshold_crossing(self) -> None:
        """Crossing an alert threshold emits a CostAlert."""
        budget = _budget(
            spent_amount=49.0, limit_amount=100.0,
            alert_thresholds=[50.0, 75.0, 100.0],
        )
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([budget]),
            _exec_result([]),
        ])

        await CostEngine._update_budget_spend(
            session, total_cost=2.0,
            agent_id=None, user_id=None, department_id=DEPT_ID,
        )

        # Should have called session.add for: budget update + alert
        add_calls = session.add.call_args_list
        alert_added = any(
            isinstance(call.args[0], CostAlert)
            for call in add_calls
        )
        assert alert_added, "CostAlert should be emitted when threshold is crossed"

    @pytest.mark.asyncio
    async def test_no_alert_when_threshold_not_crossed(self) -> None:
        """No alert when spend doesn't cross any threshold."""
        budget = _budget(
            spent_amount=10.0, limit_amount=100.0,
            alert_thresholds=[50.0, 75.0, 100.0],
        )
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([budget]),
            _exec_result([]),
        ])

        await CostEngine._update_budget_spend(
            session, total_cost=1.0,
            agent_id=None, user_id=None, department_id=DEPT_ID,
        )

        add_calls = session.add.call_args_list
        alert_added = any(
            isinstance(call.args[0], CostAlert)
            for call in add_calls
        )
        assert not alert_added

    @pytest.mark.asyncio
    async def test_alert_severity_critical_at_100(self) -> None:
        """Alert severity is 'critical' when crossing 100% threshold."""
        budget = _budget(
            spent_amount=99.0, limit_amount=100.0,
            alert_thresholds=[100.0],
        )
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([budget]),
            _exec_result([]),
        ])

        await CostEngine._update_budget_spend(
            session, total_cost=2.0,
            agent_id=None, user_id=None, department_id=DEPT_ID,
        )

        add_calls = session.add.call_args_list
        alerts = [c.args[0] for c in add_calls if isinstance(c.args[0], CostAlert)]
        assert len(alerts) == 1
        assert alerts[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_alert_severity_info_below_75(self) -> None:
        """Alert severity is 'info' for thresholds below 75%."""
        budget = _budget(
            spent_amount=49.0, limit_amount=100.0,
            alert_thresholds=[50.0],
        )
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([budget]),
            _exec_result([]),
        ])

        await CostEngine._update_budget_spend(
            session, total_cost=2.0,
            agent_id=None, user_id=None, department_id=DEPT_ID,
        )

        add_calls = session.add.call_args_list
        alerts = [c.args[0] for c in add_calls if isinstance(c.args[0], CostAlert)]
        assert len(alerts) == 1
        assert alerts[0].severity == "info"

    @pytest.mark.asyncio
    async def test_alert_severity_warning_at_75(self) -> None:
        """Alert severity is 'warning' for thresholds at 75-99%."""
        budget = _budget(
            spent_amount=74.0, limit_amount=100.0,
            alert_thresholds=[75.0],
        )
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[
            _exec_result([budget]),
            _exec_result([]),
        ])

        await CostEngine._update_budget_spend(
            session, total_cost=2.0,
            agent_id=None, user_id=None, department_id=DEPT_ID,
        )

        add_calls = session.add.call_args_list
        alerts = [c.args[0] for c in add_calls if isinstance(c.args[0], CostAlert)]
        assert len(alerts) == 1
        assert alerts[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_deduplicates_budgets_by_id(self) -> None:
        """_update_budget_spend should not double-count the same budget."""
        budget = _budget(spent_amount=10.0, scope="global")
        session = _mock_session()
        # budget found both in department scope AND global scope
        session.exec = AsyncMock(side_effect=[
            _exec_result([budget]),  # department match
            _exec_result([budget]),  # global match (same budget)
        ])

        await CostEngine._update_budget_spend(
            session, total_cost=5.0,
            agent_id=None, user_id=None, department_id=DEPT_ID,
        )

        # Should only be incremented once
        assert budget.spent_amount == 15.0


# ═══════════════════════════════════════════════════════════════════
# Forecasting
# ═══════════════════════════════════════════════════════════════════


class TestForecast:
    """Tests for the linear forecasting logic."""

    @pytest.mark.asyncio
    async def test_forecast_no_data(self) -> None:
        """Forecast with no ledger data returns zeroes and low confidence."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.forecast(session, days_ahead=30)

        assert result["daily_avg_cost"] == 0.0
        assert result["projected_cost"] == 0.0
        assert result["budget_exhaustion_date"] is None
        assert result["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_forecast_with_data(self) -> None:
        """Forecast projects daily average forward."""
        entries = []
        for i in range(15):
            entries.append(_ledger_entry(
                total_cost=10.0,
                created_at=NOW - timedelta(days=i),
            ))
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result(entries))

        result = await CostEngine.forecast(session, days_ahead=30)

        assert result["daily_avg_cost"] == 10.0
        assert result["projected_cost"] == 300.0
        assert result["days_ahead"] == 30
        assert result["confidence"] == "high"  # >= 14 days

    @pytest.mark.asyncio
    async def test_forecast_medium_confidence(self) -> None:
        """7-13 days of data yields medium confidence."""
        entries = []
        for i in range(10):
            entries.append(_ledger_entry(
                total_cost=5.0,
                created_at=NOW - timedelta(days=i),
            ))
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result(entries))

        result = await CostEngine.forecast(session, days_ahead=7)

        assert result["confidence"] == "medium"

    @pytest.mark.asyncio
    async def test_forecast_low_confidence(self) -> None:
        """Fewer than 7 days of data yields low confidence."""
        entries = [
            _ledger_entry(total_cost=20.0, created_at=NOW - timedelta(days=i))
            for i in range(3)
        ]
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result(entries))

        result = await CostEngine.forecast(session, days_ahead=30)

        assert result["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_forecast_with_budget_exhaustion(self) -> None:
        """Forecast calculates budget exhaustion date when budget is provided."""
        budget = _budget(limit_amount=100.0, spent_amount=50.0)
        entries = [
            _ledger_entry(total_cost=10.0, created_at=NOW - timedelta(days=i))
            for i in range(14)
        ]
        session = _mock_session()
        session.get = AsyncMock(return_value=budget)
        session.exec = AsyncMock(return_value=_exec_result(entries))

        result = await CostEngine.forecast(session, budget_id=BUDGET_ID, days_ahead=30)

        assert result["budget_exhaustion_date"] is not None
        assert result["daily_avg_cost"] == 10.0
        # remaining=50, daily=10 → exhaustion in 5 days

    @pytest.mark.asyncio
    async def test_forecast_no_exhaustion_when_budget_fully_spent(self) -> None:
        """When remaining <= 0, no exhaustion date is set."""
        budget = _budget(limit_amount=100.0, spent_amount=120.0)
        entries = [
            _ledger_entry(total_cost=10.0, created_at=NOW - timedelta(days=i))
            for i in range(14)
        ]
        session = _mock_session()
        session.get = AsyncMock(return_value=budget)
        session.exec = AsyncMock(return_value=_exec_result(entries))

        result = await CostEngine.forecast(session, budget_id=BUDGET_ID, days_ahead=30)

        assert result["budget_exhaustion_date"] is None

    @pytest.mark.asyncio
    async def test_forecast_no_budget_found(self) -> None:
        """When budget_id given but not found, forecasts without scoping."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.forecast(session, budget_id=uuid4(), days_ahead=30)

        assert result["projected_cost"] == 0.0

    @pytest.mark.asyncio
    async def test_forecast_scopes_to_agent_budget(self) -> None:
        """When budget has agent_id, forecast scopes ledger query."""
        budget = _budget(scope="agent", agent_id=AGENT_ID, department_id=None)
        session = _mock_session()
        session.get = AsyncMock(return_value=budget)
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.forecast(session, budget_id=BUDGET_ID, days_ahead=30)

        assert result["projected_cost"] == 0.0
        session.get.assert_awaited_once_with(Budget, BUDGET_ID)


# ═══════════════════════════════════════════════════════════════════
# Cost Reports
# ═══════════════════════════════════════════════════════════════════


class TestCostReport:
    """Tests for generate_cost_report."""

    @pytest.mark.asyncio
    async def test_report_empty(self) -> None:
        """Empty ledger produces zero totals and empty breakdown."""
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.generate_cost_report(session)

        assert result["totals"]["total_cost"] == 0.0
        assert result["totals"]["call_count"] == 0
        assert result["breakdown"] == {}

    @pytest.mark.asyncio
    async def test_report_groups_by_provider(self) -> None:
        """Report groups entries by provider by default."""
        entries = [
            _ledger_entry(provider="openai", total_cost=10.0),
            _ledger_entry(provider="openai", total_cost=5.0),
            _ledger_entry(provider="anthropic", total_cost=8.0),
        ]
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result(entries))

        result = await CostEngine.generate_cost_report(session)

        assert result["group_by"] == "provider"
        assert "openai" in result["breakdown"]
        assert "anthropic" in result["breakdown"]
        assert result["breakdown"]["openai"]["call_count"] == 2
        assert result["breakdown"]["anthropic"]["call_count"] == 1
        assert result["totals"]["call_count"] == 3
        assert result["totals"]["total_cost"] == 23.0

    @pytest.mark.asyncio
    async def test_report_groups_by_model(self) -> None:
        """Report can group by model_id."""
        entries = [
            _ledger_entry(model_id="gpt-4o", total_cost=10.0),
            _ledger_entry(model_id="claude-3-5-sonnet", total_cost=8.0),
        ]
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result(entries))

        result = await CostEngine.generate_cost_report(session, group_by="model_id")

        assert "gpt-4o" in result["breakdown"]
        assert "claude-3-5-sonnet" in result["breakdown"]

    @pytest.mark.asyncio
    async def test_report_period_in_output(self) -> None:
        """Report includes the time period in the output."""
        since = NOW - timedelta(days=7)
        until = NOW
        session = _mock_session()
        session.exec = AsyncMock(return_value=_exec_result([]))

        result = await CostEngine.generate_cost_report(
            session, since=since, until=until,
        )

        assert result["period"]["since"] == since.isoformat()
        assert result["period"]["until"] == until.isoformat()


# ═══════════════════════════════════════════════════════════════════
# Alerts
# ═══════════════════════════════════════════════════════════════════


class TestAlerts:
    """Tests for alert listing and acknowledgement."""

    @pytest.mark.asyncio
    async def test_list_alerts_returns_paginated(self) -> None:
        """list_alerts returns (alerts, total) tuple."""
        alerts = [_alert(), _alert(aid=uuid4())]
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result(alerts), _exec_result(alerts)])

        result_alerts, total = await CostEngine.list_alerts(session)

        assert len(result_alerts) == 2
        assert total == 2

    @pytest.mark.asyncio
    async def test_list_alerts_empty(self) -> None:
        """list_alerts returns empty when no alerts exist."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([]), _exec_result([])])

        result_alerts, total = await CostEngine.list_alerts(session)

        assert result_alerts == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_alerts_filter_by_budget(self) -> None:
        """list_alerts filters by budget_id."""
        alert = _alert(budget_id=BUDGET_ID)
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([alert]), _exec_result([alert])])

        result_alerts, total = await CostEngine.list_alerts(session, budget_id=BUDGET_ID)

        assert total == 1

    @pytest.mark.asyncio
    async def test_list_alerts_filter_acknowledged(self) -> None:
        """list_alerts filters by is_acknowledged."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([]), _exec_result([])])

        result_alerts, total = await CostEngine.list_alerts(session, is_acknowledged=True)

        assert total == 0

    @pytest.mark.asyncio
    async def test_acknowledge_alert_success(self) -> None:
        """acknowledge_alert sets is_acknowledged and timestamps."""
        alert = _alert()
        session = _mock_session()
        session.get = AsyncMock(return_value=alert)

        result = await CostEngine.acknowledge_alert(
            session, ALERT_ID, acknowledged_by=ACK_USER_ID,
        )

        assert result is not None
        assert result.is_acknowledged is True
        assert result.acknowledged_by == ACK_USER_ID
        assert result.acknowledged_at is not None
        session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_acknowledge_alert_not_found(self) -> None:
        """acknowledge_alert returns None when alert doesn't exist."""
        session = _mock_session()
        session.get = AsyncMock(return_value=None)

        result = await CostEngine.acknowledge_alert(session, uuid4())

        assert result is None
        session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_acknowledge_alert_without_user(self) -> None:
        """acknowledge_alert works without acknowledged_by."""
        alert = _alert()
        session = _mock_session()
        session.get = AsyncMock(return_value=alert)

        result = await CostEngine.acknowledge_alert(session, ALERT_ID)

        assert result is not None
        assert result.is_acknowledged is True
        assert result.acknowledged_by is None


# ═══════════════════════════════════════════════════════════════════
# Provider Pricing CRUD
# ═══════════════════════════════════════════════════════════════════


class TestPricingCRUD:
    """Tests for provider pricing set and list operations."""

    @pytest.mark.asyncio
    async def test_set_pricing(self) -> None:
        """set_pricing adds, commits, and refreshes."""
        pricing = _pricing()
        session = _mock_session()

        result = await CostEngine.set_pricing(session, pricing)

        assert result.provider == "openai"
        assert result.model_id == "gpt-4o"
        session.add.assert_called_once_with(pricing)
        session.commit.assert_awaited_once()
        session.refresh.assert_awaited_once_with(pricing)

    @pytest.mark.asyncio
    async def test_list_pricing_returns_paginated(self) -> None:
        """list_pricing returns (entries, total) tuple."""
        entries = [_pricing(), _pricing(pid=uuid4(), model_id="gpt-4o-mini")]
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result(entries), _exec_result(entries)])

        result_entries, total = await CostEngine.list_pricing(session)

        assert len(result_entries) == 2
        assert total == 2

    @pytest.mark.asyncio
    async def test_list_pricing_filter_by_provider(self) -> None:
        """list_pricing filters by provider."""
        entry = _pricing(provider="anthropic", model_id="claude-3-5-sonnet")
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([entry]), _exec_result([entry])])

        result_entries, total = await CostEngine.list_pricing(session, provider="anthropic")

        assert total == 1

    @pytest.mark.asyncio
    async def test_list_pricing_empty(self) -> None:
        """list_pricing returns empty when no entries."""
        session = _mock_session()
        session.exec = AsyncMock(side_effect=[_exec_result([]), _exec_result([])])

        result_entries, total = await CostEngine.list_pricing(session)

        assert total == 0
        assert result_entries == []


# ═══════════════════════════════════════════════════════════════════
# Default Pricing Constants
# ═══════════════════════════════════════════════════════════════════


class TestDefaultPricing:
    """Tests for the built-in _DEFAULT_PRICING dict."""

    def test_default_pricing_has_all_providers(self) -> None:
        """Default pricing covers openai, anthropic, google, azure."""
        assert "openai" in _DEFAULT_PRICING
        assert "anthropic" in _DEFAULT_PRICING
        assert "google" in _DEFAULT_PRICING
        assert "azure" in _DEFAULT_PRICING

    def test_default_pricing_values_are_tuples(self) -> None:
        """Each model entry is a (input_cost, output_cost) tuple."""
        for provider, models in _DEFAULT_PRICING.items():
            for model_id, prices in models.items():
                assert isinstance(prices, tuple), f"{provider}/{model_id}"
                assert len(prices) == 2, f"{provider}/{model_id}"
                assert prices[0] >= 0, f"{provider}/{model_id} input cost negative"
                assert prices[1] >= 0, f"{provider}/{model_id} output cost negative"

    def test_output_cost_gte_input_cost(self) -> None:
        """Output tokens typically cost >= input tokens."""
        for provider, models in _DEFAULT_PRICING.items():
            for model_id, (inp, out) in models.items():
                assert out >= inp, f"{provider}/{model_id}: output < input"
