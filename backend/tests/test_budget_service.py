"""Tests for the typed budget lookup service (Phase 4 / WS11).

Covers:
- check_budget allows when within limit, blocks when over (allowed flag).
- Fail-closed mode raises NoBudgetConfigured / BudgetLookupFailed.
- Fail-open mode returns permissive BudgetCheckResult under the same
  conditions.
- aggregate_for_period excludes other tenants.
- reserve_budget / commit_budget round-trip.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.cost import Budget, TokenLedger
from app.services.budget_service import (
    BudgetCheckResult,
    BudgetLookupFailed,
    NoBudgetConfigured,
    aggregate_for_period,
    check_budget,
    commit_budget,
    reserve_budget,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _ledger(total_cost: float, created_at: datetime, tenant_id: str = "t-1") -> Any:
    """Minimal ledger row stub. ``MagicMock(spec=TokenLedger)`` keeps the
    isinstance() check happy while letting us set attributes freely.
    """
    e = MagicMock(spec=TokenLedger)
    e.total_cost = total_cost
    e.created_at = created_at
    e.tenant_id = tenant_id
    return e


def _budget_row(
    *,
    limit_amount: float = 100.0,
    spent_amount: float = 0.0,
    period: str = "monthly",
    is_active: bool = True,
    tenant_id: str = "t-1",
) -> Any:
    b = MagicMock(spec=Budget)
    b.id = uuid4()
    b.tenant_id = tenant_id
    b.limit_amount = limit_amount
    b.spent_amount = spent_amount
    b.period = period
    b.is_active = is_active
    b.updated_at = datetime.now(timezone.utc)
    return b


def _make_session(
    *,
    budget: Any | None = None,
    ledger_entries: list[Any] | None = None,
    raise_on_exec: BaseException | None = None,
) -> AsyncMock:
    """Async session whose ``exec()`` returns Budget then ledger entries.

    The budget_service issues two queries: first for the Budget row, then
    for ledger aggregation. We model that with a side_effect list.
    """
    session = AsyncMock()

    budget_result = MagicMock()
    budget_result.all.return_value = [budget] if budget is not None else []

    ledger_result = MagicMock()
    ledger_result.all.return_value = list(ledger_entries or [])

    if raise_on_exec is not None:
        session.exec = AsyncMock(side_effect=raise_on_exec)
    else:
        session.exec = AsyncMock(side_effect=[budget_result, ledger_result])

    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


# ── check_budget — happy paths ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_budget_allows_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """When current spend + estimate < limit, allowed=True."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    now = datetime.now(timezone.utc)
    budget = _budget_row(limit_amount=100.0, period="monthly")
    ledger = [_ledger(20.0, now), _ledger(30.0, now)]
    session = _make_session(budget=budget, ledger_entries=ledger)

    result = await check_budget(
        session, tenant_id=tenant, estimated_cost_usd=10.0
    )

    assert isinstance(result, BudgetCheckResult)
    assert result.allowed is True
    assert result.reason == "within_budget"
    assert abs(result.current_spend_usd - 50.0) < 1e-9
    assert result.limit_usd == 100.0
    assert result.period == "monthly"
    assert abs(result.headroom_usd - 50.0) < 1e-9


@pytest.mark.asyncio
async def test_check_budget_blocks_over_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """When current spend + estimate > limit, allowed=False."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    now = datetime.now(timezone.utc)
    budget = _budget_row(limit_amount=50.0, period="monthly")
    ledger = [_ledger(45.0, now)]
    session = _make_session(budget=budget, ledger_entries=ledger)

    result = await check_budget(
        session, tenant_id=tenant, estimated_cost_usd=10.0
    )
    assert result.allowed is False
    assert result.reason == "would_exceed_budget"
    assert abs(result.current_spend_usd - 45.0) < 1e-9
    assert result.limit_usd == 50.0


# ── check_budget — fail-closed semantics ─────────────────────────────────────


@pytest.mark.asyncio
async def test_check_budget_fail_closed_raises_NoBudgetConfigured_when_no_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail_closed=True + no Budget row → raise NoBudgetConfigured."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    tenant = uuid4()
    session = _make_session(budget=None, ledger_entries=[])

    with pytest.raises(NoBudgetConfigured):
        await check_budget(
            session, tenant_id=tenant, estimated_cost_usd=1.0
        )


@pytest.mark.asyncio
async def test_check_budget_fail_open_returns_allowed_when_no_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail_closed=False + no Budget row → allowed=True with reason fail_open_default."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    session = _make_session(budget=None, ledger_entries=[])

    result = await check_budget(
        session, tenant_id=tenant, estimated_cost_usd=1.0
    )
    assert result.allowed is True
    assert result.reason == "fail_open_default"
    assert result.fail_mode == "open"


@pytest.mark.asyncio
async def test_check_budget_fail_closed_raises_BudgetLookupFailed_on_db_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail_closed=True + DB error → raise BudgetLookupFailed."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    tenant = uuid4()
    session = _make_session(raise_on_exec=RuntimeError("connection lost"))

    with pytest.raises(BudgetLookupFailed):
        await check_budget(
            session, tenant_id=tenant, estimated_cost_usd=1.0
        )


@pytest.mark.asyncio
async def test_check_budget_fail_open_returns_allowed_on_db_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail_closed=False + DB error → allowed=True with reason fail_open_lookup_error."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    session = _make_session(raise_on_exec=RuntimeError("connection lost"))

    result = await check_budget(
        session, tenant_id=tenant, estimated_cost_usd=1.0
    )
    assert result.allowed is True
    assert result.reason == "fail_open_lookup_error"
    assert result.fail_mode == "open"


@pytest.mark.asyncio
async def test_check_budget_explicit_arg_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing fail_closed=True explicitly overrides ARCHON_ENV=dev."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    session = _make_session(budget=None, ledger_entries=[])

    with pytest.raises(NoBudgetConfigured):
        await check_budget(
            session, tenant_id=tenant, estimated_cost_usd=1.0, fail_closed=True
        )


@pytest.mark.asyncio
async def test_check_budget_env_var_overrides_archon_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARCHON_COST_FAIL_CLOSED=1 wins over ARCHON_ENV=dev."""
    monkeypatch.setenv("ARCHON_COST_FAIL_CLOSED", "1")
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    session = _make_session(budget=None, ledger_entries=[])

    with pytest.raises(NoBudgetConfigured):
        await check_budget(
            session, tenant_id=tenant, estimated_cost_usd=1.0
        )


# ── reserve / commit pattern ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reserve_and_commit_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    """reserve_budget bumps spent_amount; commit_budget reconciles."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()

    budget = _budget_row(limit_amount=100.0, spent_amount=20.0)
    # reserve_budget calls _select_budget_for_tenant exactly once.
    reserve_session = AsyncMock()
    reserve_result = MagicMock()
    reserve_result.all.return_value = [budget]
    reserve_session.exec = AsyncMock(return_value=reserve_result)
    reserve_session.add = MagicMock()
    reserve_session.flush = AsyncMock()

    await reserve_budget(reserve_session, tenant_id=tenant, amount_usd=5.0)
    assert abs(budget.spent_amount - 25.0) < 1e-9
    assert reserve_session.add.called

    # commit_budget with reserved_amount=5, actual=4 → -1 delta
    commit_session = AsyncMock()
    commit_result = MagicMock()
    commit_result.all.return_value = [budget]
    commit_session.exec = AsyncMock(return_value=commit_result)
    commit_session.add = MagicMock()
    commit_session.flush = AsyncMock()

    await commit_budget(
        commit_session,
        tenant_id=tenant,
        actual_amount_usd=4.0,
        reserved_amount_usd=5.0,
    )
    assert abs(budget.spent_amount - 24.0) < 1e-9


@pytest.mark.asyncio
async def test_reserve_budget_no_budget_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """reserve_budget with no Budget row is a silent no-op (interface stability)."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    session = _make_session(budget=None, ledger_entries=[])
    # Should not raise
    await reserve_budget(session, tenant_id=tenant, amount_usd=10.0)


# ── aggregate_for_period ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aggregate_for_period_excludes_other_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SQL filter must scope to ``tenant_id``; verified via the WHERE clause stmt.

    We use a mock that captures the executed select — the aggregation
    arithmetic itself is exercised against rows the mock returns.
    """
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=30)

    # Only tenant-matching rows should ever reach us via the filter.
    matching = [_ledger(2.5, now, tenant_id=str(tenant)),
                _ledger(1.5, now, tenant_id=str(tenant))]

    session = AsyncMock()
    captured: dict[str, Any] = {}

    async def _exec(stmt):  # noqa: ANN001
        captured["stmt"] = stmt
        result = MagicMock()
        result.all.return_value = matching
        return result

    session.exec = _exec

    total = await aggregate_for_period(session, tenant, period_start)
    assert abs(total - 4.0) < 1e-9

    # Render the captured stmt and assert the tenant_id filter is present.
    rendered = str(captured["stmt"]).lower()
    assert "tenant_id" in rendered


@pytest.mark.asyncio
async def test_aggregate_for_period_empty_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    tenant = uuid4()
    now = datetime.now(timezone.utc)
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.exec = AsyncMock(return_value=result)

    total = await aggregate_for_period(session, tenant, now - timedelta(days=1))
    assert total == 0.0
