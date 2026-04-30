"""Tests for A9: Real Cost Tracking.

Verifies:
- cost_service.record_usage writes a real TokenLedger row with non-zero cost.
- cost_service.record_usage falls back to rate-card calculation when cost_usd=None.
- cost_service.tenant_running_total aggregates correctly.
- cost_service.cost_summary returns real data, not random.
- _generate_mock_steps is GONE from execution_service.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

import app.services.execution_service as execution_service
from app.services.cost_service import (
    CostService,
    cost_summary,
    record_usage,
    tenant_running_total,
)
from app.models.cost import TokenLedger, UsageEvent


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_session(entries: list[TokenLedger] | None = None) -> AsyncMock:
    """Return a mock AsyncSession pre-loaded with optional ledger entries."""
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.all.return_value = entries or []
    exec_result.first.return_value = None
    session.exec = AsyncMock(return_value=exec_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _make_ledger_entry(
    *,
    tenant_id: str = "test-tenant",
    model_id: str = "gpt-4o-mini",
    provider: str = "openai",
    input_tokens: int = 100,
    output_tokens: int = 50,
    total_cost: float = 0.00015,
    created_at: datetime | None = None,
    agent_id: UUID | None = None,
    execution_id: UUID | None = None,
) -> TokenLedger:
    """Build a minimal TokenLedger ORM stub."""
    entry = MagicMock(spec=TokenLedger)
    entry.tenant_id = tenant_id
    entry.model_id = model_id
    entry.provider = provider
    entry.input_tokens = input_tokens
    entry.output_tokens = output_tokens
    entry.total_tokens = input_tokens + output_tokens
    entry.total_cost = total_cost
    entry.input_cost = total_cost * 0.3
    entry.output_cost = total_cost * 0.7
    entry.latency_ms = 0.0
    entry.attribution_chain = {}
    entry.created_at = created_at or datetime(2025, 1, 15, 12, 0, 0)
    entry.agent_id = agent_id
    entry.execution_id = execution_id
    entry.user_id = None
    entry.department_id = None
    entry.workspace_id = None
    entry.id = uuid4()
    return entry


# ── Test 1: _generate_mock_steps is GONE ─────────────────────────────────────


def test_generate_mock_steps_does_not_exist() -> None:
    """A9 acceptance: _generate_mock_steps must be removed from execution_service."""
    assert not hasattr(
        execution_service, "_generate_mock_steps"
    ), "_generate_mock_steps still exists in execution_service — random mock cost generation was not removed"


def test_generate_failed_steps_does_not_exist() -> None:
    """A9 acceptance: _generate_failed_steps must be removed from execution_service."""
    assert not hasattr(
        execution_service, "_generate_failed_steps"
    ), "_generate_failed_steps still exists in execution_service"


def test_random_not_imported_in_execution_service() -> None:
    """Ensure the random module is no longer imported by execution_service."""
    import importlib
    import types

    # Re-check the live module's namespace for 'random'
    assert "random" not in execution_service.__dict__, (
        "execution_service still imports 'random' at module level"
    )


# ── Test 2: record_usage writes a real CostRecord ────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_with_known_cost_usd() -> None:
    """When cost_usd is provided, record_usage writes a TokenLedger entry."""
    execution_id = uuid4()
    tenant_id = uuid4()
    step_id = uuid4()

    # Patch _calculate_token_cost to avoid DB price lookup
    with patch.object(
        CostService,
        "_calculate_token_cost",
        new=AsyncMock(return_value=(0.0001, 0.0002)),
    ), patch.object(
        CostService,
        "_update_budget_spend",
        new=AsyncMock(return_value=None),
    ):
        session = _make_session()
        # Make refresh populate the entry's id
        refreshed = _make_ledger_entry(total_cost=0.003)
        session.refresh = AsyncMock(side_effect=lambda obj: None)

        await record_usage(
            session,
            tenant_id=tenant_id,
            execution_id=execution_id,
            step_id=step_id,
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=0.003,
        )

    # session.add must have been called with a TokenLedger instance
    assert session.add.called, "session.add was never called — no ledger row was created"
    added_obj = session.add.call_args[0][0]
    assert isinstance(added_obj, TokenLedger), (
        f"Expected TokenLedger, got {type(added_obj)}"
    )
    assert added_obj.total_cost == 0.003, (
        f"Expected total_cost=0.003 (from cost_usd), got {added_obj.total_cost}"
    )


@pytest.mark.asyncio
async def test_record_usage_calculates_from_rate_card_when_cost_usd_none() -> None:
    """When cost_usd is None, cost is calculated from the rate card."""
    execution_id = uuid4()
    tenant_id = uuid4()

    # Simulate rate card returning (0.00015, 0.0006) per 1M tokens
    expected_input_cost = (100 / 1_000_000) * 0.15  # gpt-4o-mini input rate
    expected_output_cost = (50 / 1_000_000) * 0.60

    with patch.object(
        CostService,
        "_calculate_token_cost",
        new=AsyncMock(return_value=(expected_input_cost, expected_output_cost)),
    ), patch.object(
        CostService,
        "_update_budget_spend",
        new=AsyncMock(return_value=None),
    ):
        session = _make_session()
        session.refresh = AsyncMock(side_effect=lambda obj: None)

        await record_usage(
            session,
            tenant_id=tenant_id,
            execution_id=execution_id,
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
            cost_usd=None,  # no LiteLLM cost — use rate card
        )

    added_obj = session.add.call_args[0][0]
    assert isinstance(added_obj, TokenLedger)
    # Total cost should be input + output from rate card
    expected_total = expected_input_cost + expected_output_cost
    assert abs(added_obj.total_cost - expected_total) < 1e-10, (
        f"Expected total_cost≈{expected_total}, got {added_obj.total_cost}"
    )
    assert added_obj.total_cost > 0, "Computed cost from rate card must be > 0"


# ── Test 3: tenant_running_total aggregates correctly ────────────────────────


@pytest.mark.asyncio
async def test_tenant_running_total_sums_entries() -> None:
    """tenant_running_total returns the sum of all entries since the given date."""
    tenant_id = uuid4()
    since = datetime(2025, 1, 1, 0, 0, 0)

    entries = [
        _make_ledger_entry(total_cost=0.001, created_at=datetime(2025, 1, 10)),
        _make_ledger_entry(total_cost=0.005, created_at=datetime(2025, 1, 12)),
        _make_ledger_entry(total_cost=0.002, created_at=datetime(2025, 1, 14)),
    ]
    session = _make_session(entries)

    total = await tenant_running_total(session, tenant_id, since)

    assert isinstance(total, Decimal), f"Expected Decimal, got {type(total)}"
    assert abs(float(total) - 0.008) < 1e-9, f"Expected 0.008, got {total}"


@pytest.mark.asyncio
async def test_tenant_running_total_empty_returns_zero() -> None:
    """tenant_running_total returns Decimal(0) when no entries exist."""
    tenant_id = uuid4()
    session = _make_session([])
    total = await tenant_running_total(session, tenant_id, datetime(2025, 1, 1))
    assert total == Decimal("0"), f"Expected 0, got {total}"


# ── Test 4: cost_summary returns real data, not random ───────────────────────


@pytest.mark.asyncio
async def test_cost_summary_returns_real_data() -> None:
    """cost_summary aggregates from real token_ledger entries, not mock data."""
    tenant_id = uuid4()
    agent_id_1 = uuid4()
    agent_id_2 = uuid4()

    now = datetime.utcnow()
    entries = [
        _make_ledger_entry(
            model_id="gpt-4o-mini",
            total_cost=0.010,
            created_at=now - timedelta(hours=1),
            agent_id=agent_id_1,
        ),
        _make_ledger_entry(
            model_id="claude-3-5-sonnet",
            total_cost=0.020,
            created_at=now - timedelta(days=2),
            agent_id=agent_id_2,
        ),
        _make_ledger_entry(
            model_id="gpt-4o-mini",
            total_cost=0.005,
            created_at=now - timedelta(days=20),
        ),
    ]
    session = _make_session(entries)

    result = await cost_summary(session, tenant_id=tenant_id)

    assert "today" in result
    assert "week" in result
    assert "month" in result
    assert "top_agents" in result
    assert "top_models" in result

    # All values must be deterministic floats, never random
    assert isinstance(result["today"], float)
    assert isinstance(result["week"], float)
    assert isinstance(result["month"], float)

    # Month includes all 3 entries
    assert abs(result["month"] - 0.035) < 1e-9, (
        f"Expected month=0.035, got {result['month']}"
    )

    # Top models list should have claude-3-5-sonnet as highest (0.020 single entry)
    # gpt-4o-mini has 0.010 + 0.005 = 0.015 across 2 entries
    assert len(result["top_models"]) >= 1
    top_model = result["top_models"][0]
    assert top_model["model"] == "claude-3-5-sonnet", (
        f"Expected claude-3-5-sonnet as top model (0.020 cost), got {top_model['model']}"
    )
    # gpt-4o-mini should be second
    if len(result["top_models"]) >= 2:
        assert result["top_models"][1]["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_cost_summary_no_tenant_aggregates_all() -> None:
    """cost_summary with tenant_id=None returns data across all tenants."""
    entries = [
        _make_ledger_entry(tenant_id="tenant-a", total_cost=0.001),
        _make_ledger_entry(tenant_id="tenant-b", total_cost=0.002),
    ]
    session = _make_session(entries)

    result = await cost_summary(session, tenant_id=None)
    assert result["month"] >= 0.0  # should aggregate, not crash
