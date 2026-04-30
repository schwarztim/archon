"""Cost-gate node fail-closed tests (Phase 4 / WS11).

The previous cost gate fail-OPENed on:
- DB query exceptions
- No Budget configured for the tenant

In production / staging this is unsafe — a misconfigured tenant could
burn unbounded spend before anyone notices. These tests pin the new
contract: in fail-closed mode the gate blocks; in dev/test it preserves
the legacy fail-open behaviour for backward compatibility.

The tests exercise the node at the executor boundary — they do NOT
touch the dispatcher, routes, or facade. The "blocks dispatcher" test
asserts the node returns ``status='failed'``, which is the mechanism
by which the dispatcher would skip downstream steps.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.budget_service import (
    BudgetCheckResult,
    BudgetLookupFailed,
    NoBudgetConfigured,
)
from app.services.node_executors import NODE_EXECUTORS
from tests.test_node_executors import make_ctx


# ── 1. Allowed path ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_completes_when_budget_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_budget returns allowed=True → node status='completed'."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    fake_result = BudgetCheckResult(
        allowed=True,
        reason="within_budget",
        current_spend_usd=10.0,
        limit_usd=100.0,
        period="monthly",
        headroom_usd=90.0,
        fail_mode="closed",
    )
    monkeypatch.setattr(
        "app.services.budget_service.check_budget",
        AsyncMock(return_value=fake_result),
    )

    ctx = make_ctx(
        "costGateNode",
        config={
            "enforceBudget": True,
            "estimatedCostUsd": 5.0,
        },
        tenant_id=str(uuid4()),
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["passed"] is True
    assert "budget_check" in r.output
    assert r.output["budget_check"]["allowed"] is True


# ── 2. Over-budget path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_fails_when_over_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_budget returns allowed=False → status='failed', error_code matches."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    fake_result = BudgetCheckResult(
        allowed=False,
        reason="would_exceed_budget",
        current_spend_usd=95.0,
        limit_usd=100.0,
        period="monthly",
        headroom_usd=5.0,
        fail_mode="closed",
    )
    monkeypatch.setattr(
        "app.services.budget_service.check_budget",
        AsyncMock(return_value=fake_result),
    )

    ctx = make_ctx(
        "costGateNode",
        config={
            "enforceBudget": True,
            "estimatedCostUsd": 10.0,
        },
        tenant_id=str(uuid4()),
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "failed"
    assert r.output["error_code"] == "cost_gate_budget_exceeded"
    assert "Cost gate exceeded" in (r.error or "")


# ── 3. No Budget configured — fail-closed in production ──────────────────────


@pytest.mark.asyncio
async def test_node_fails_closed_in_production_when_no_budget_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARCHON_ENV=production + no Budget → cost_gate_no_budget."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    monkeypatch.setattr(
        "app.services.budget_service.check_budget",
        AsyncMock(side_effect=NoBudgetConfigured("no budget for tenant")),
    )

    ctx = make_ctx(
        "costGateNode",
        config={
            "enforceBudget": True,
            "estimatedCostUsd": 1.0,
        },
        tenant_id=str(uuid4()),
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "failed"
    assert r.output["error_code"] == "cost_gate_no_budget"
    assert r.output["fail_mode"] == "closed"


# ── 4. No Budget configured — fail-open in dev ───────────────────────────────


@pytest.mark.asyncio
async def test_node_passes_in_dev_when_no_budget_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARCHON_ENV=dev + no Budget → permissive BudgetCheckResult, node completed."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    fake_result = BudgetCheckResult(
        allowed=True,
        reason="fail_open_default",
        current_spend_usd=0.0,
        limit_usd=0.0,
        period="unknown",
        headroom_usd=0.0,
        fail_mode="open",
    )
    monkeypatch.setattr(
        "app.services.budget_service.check_budget",
        AsyncMock(return_value=fake_result),
    )

    ctx = make_ctx(
        "costGateNode",
        config={
            "enforceBudget": True,
            "estimatedCostUsd": 1.0,
        },
        tenant_id=str(uuid4()),
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["passed"] is True
    assert r.output["budget_check"]["fail_mode"] == "open"


# ── 5. DB error — fail-closed in production ──────────────────────────────────


@pytest.mark.asyncio
async def test_node_fail_closed_on_db_error_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARCHON_ENV=production + BudgetLookupFailed → cost_gate_lookup_failed."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    monkeypatch.setattr(
        "app.services.budget_service.check_budget",
        AsyncMock(side_effect=BudgetLookupFailed("connection lost")),
    )

    ctx = make_ctx(
        "costGateNode",
        config={
            "enforceBudget": True,
            "estimatedCostUsd": 1.0,
        },
        tenant_id=str(uuid4()),
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "failed"
    assert r.output["error_code"] == "cost_gate_lookup_failed"
    assert r.output["fail_mode"] == "closed"


# ── 6. Output payload includes budget metadata ───────────────────────────────


@pytest.mark.asyncio
async def test_node_records_budget_check_in_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The completed node payload includes a structured budget_check dict."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    fake_result = BudgetCheckResult(
        allowed=True,
        reason="within_budget",
        current_spend_usd=12.345678,
        limit_usd=100.0,
        period="monthly",
        headroom_usd=87.654322,
        fail_mode="closed",
    )
    monkeypatch.setattr(
        "app.services.budget_service.check_budget",
        AsyncMock(return_value=fake_result),
    )

    ctx = make_ctx(
        "costGateNode",
        config={
            "enforceBudget": True,
            "estimatedCostUsd": 5.0,
        },
        tenant_id=str(uuid4()),
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    bc = r.output["budget_check"]
    for key in (
        "allowed",
        "reason",
        "current_spend_usd",
        "limit_usd",
        "period",
        "headroom_usd",
        "fail_mode",
    ):
        assert key in bc, f"missing budget_check field: {key}"
    assert bc["limit_usd"] == 100.0
    assert bc["period"] == "monthly"


# ── 7. Failed node "blocks the dispatcher" via NodeResult.status='failed' ────
#
# The dispatcher's contract is to skip downstream steps when a step
# returns status='failed' (verified in test_dispatcher_*).
# This test exercises only the executor boundary — that the gate
# returns the failed status so the dispatcher would then skip.


@pytest.mark.asyncio
async def test_node_blocks_dispatcher_when_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An over-budget cost gate returns status='failed' (dispatcher skips downstream)."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    fake_result = BudgetCheckResult(
        allowed=False,
        reason="would_exceed_budget",
        current_spend_usd=200.0,
        limit_usd=100.0,
        period="monthly",
        headroom_usd=0.0,
        fail_mode="closed",
    )
    monkeypatch.setattr(
        "app.services.budget_service.check_budget",
        AsyncMock(return_value=fake_result),
    )

    ctx = make_ctx(
        "costGateNode",
        config={
            "enforceBudget": True,
            "estimatedCostUsd": 5.0,
        },
        tenant_id=str(uuid4()),
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)

    # Contract that the dispatcher relies on:
    assert r.status == "failed"
    # error_code is what run-finalisation surfaces for retry policy / SLO.
    assert r.output["error_code"] == "cost_gate_budget_exceeded"
    # passed=False is the boolean other steps may branch on.
    assert r.output["passed"] is False


# ── 8. Fail-closed when DB / tenant context missing ──────────────────────────


@pytest.mark.asyncio
async def test_node_fails_closed_no_tenant_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARCHON_ENV=production + tenant_id=None → fail-closed even without budget call."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "production")

    ctx = make_ctx(
        "costGateNode",
        config={
            "enforceBudget": True,
            "estimatedCostUsd": 1.0,
        },
        tenant_id=None,
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "failed"
    assert r.output["error_code"] == "cost_gate_lookup_failed"


# ── 9. Backward-compatible legacy threshold path still works ─────────────────


@pytest.mark.asyncio
async def test_legacy_max_usd_path_unaffected_in_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy maxUsd config without enforceBudget keeps original behaviour in dev."""
    monkeypatch.delenv("ARCHON_COST_FAIL_CLOSED", raising=False)
    monkeypatch.setenv("ARCHON_ENV", "dev")

    monkeypatch.setattr(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        AsyncMock(return_value=5.0),
    )

    ctx = make_ctx(
        "costGateNode",
        config={"maxUsd": 100.0},
        tenant_id="tenant-legacy",
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["remaining_usd"] == 95.0
