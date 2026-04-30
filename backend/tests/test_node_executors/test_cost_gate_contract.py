"""costGateNode contract tests — Phase 3 / WS9.

The cost gate fails the workflow when the tenant has exceeded a configured
budget for the current billing period.  Output envelope (success):
``{"passed": True, "current_total_usd": float, "max_usd": float,
"remaining_usd": float}``.  On block: ``status="failed"``, error matches
``cost_gate_exceeded`` semantics.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_no_threshold_passes():
    """maxUsd=0 → no threshold; always pass."""
    ctx = make_ctx("costGateNode", config={"maxUsd": 0})
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["reason"] == "no_threshold_configured"


@pytest.mark.asyncio
async def test_cost_gate_camel_and_snake():
    cfg_camel = {"maxUsd": 0}
    cfg_snake = {"max_usd": 0}
    cfg_alt = {"maxCost": 0}
    for cfg in (cfg_camel, cfg_snake, cfg_alt):
        r = await NODE_EXECUTORS["costGateNode"].execute(
            make_ctx("costGateNode", config=cfg)
        )
        assert r.status == "completed"


# ---------------------------------------------------------------------------
# 2. output schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_output_envelope_under_budget():
    ctx = make_ctx(
        "costGateNode",
        config={"maxUsd": 100.0},
        tenant_id="t1",
        db_session=MagicMock(),
    )
    with patch(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        new=AsyncMock(return_value=5.0),
    ):
        r = await NODE_EXECUTORS["costGateNode"].execute(ctx)

    assert r.status == "completed"
    for key in ("passed", "current_total_usd", "max_usd", "remaining_usd"):
        assert key in r.output
    assert r.output["passed"] is True
    assert r.output["remaining_usd"] == 95.0


# ---------------------------------------------------------------------------
# 3. success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_under_budget_completes():
    ctx = make_ctx(
        "costGateNode",
        config={"maxUsd": 50.0},
        tenant_id="t1",
        db_session=MagicMock(),
    )
    with patch(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        new=AsyncMock(return_value=10.0),
    ):
        r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["passed"] is True


# ---------------------------------------------------------------------------
# 4. failure path — over budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_over_budget_fails():
    ctx = make_ctx(
        "costGateNode",
        config={"maxUsd": 10.0},
        tenant_id="t1",
        db_session=MagicMock(),
    )
    with patch(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        new=AsyncMock(return_value=15.0),
    ):
        r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "failed"
    assert "Cost gate exceeded" in (r.error or "")


@pytest.mark.asyncio
async def test_cost_gate_over_budget_error_signals_cost_gate_exceeded():
    """Error string is the contract proxy for error_code='cost_gate_exceeded'."""
    ctx = make_ctx(
        "costGateNode",
        config={"maxUsd": 1.0},
        tenant_id="t1",
        db_session=MagicMock(),
    )
    with patch(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        new=AsyncMock(return_value=2.0),
    ):
        r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    # The contract: failure surface mentions cost gate so retry policy can match
    assert "cost gate exceeded" in (r.error or "").lower()


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_cancellation_not_applicable():
    pytest.skip(
        "cancellation N/A — cost lookup is short-lived and atomic; cancel meaningless"
    )


# ---------------------------------------------------------------------------
# 6. retry classification — query failure → fail-open completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_query_error_fail_open():
    """A DB error during cost lookup intentionally fail-opens.

    The contract: don't block workflows because of a tracking failure.
    Documented in cost_gate.py — log + return passed=True with reason.
    """
    ctx = make_ctx(
        "costGateNode",
        config={"maxUsd": 100.0},
        tenant_id="t1",
        db_session=MagicMock(),
    )
    with patch(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        new=AsyncMock(side_effect=RuntimeError("DB down")),
    ):
        r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["reason"] == "cost_query_failed"


# ---------------------------------------------------------------------------
# 7. tenant isolation — tenant_id forwarded to lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_tenant_id_forwarded_to_query():
    captured: dict = {}

    async def _capture(db_session, tenant_id):
        captured["tenant_id"] = tenant_id
        return 5.0

    ctx = make_ctx(
        "costGateNode",
        config={"maxUsd": 100.0},
        tenant_id="tenant-omega",
        db_session=MagicMock(),
    )
    with patch(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        new=_capture,
    ):
        await NODE_EXECUTORS["costGateNode"].execute(ctx)

    assert captured["tenant_id"] == "tenant-omega"


@pytest.mark.asyncio
async def test_cost_gate_no_tenant_skips_gate():
    """No tenant context AND threshold>0 → fail-open."""
    ctx = make_ctx(
        "costGateNode",
        config={"maxUsd": 100.0},
        tenant_id=None,
        db_session=MagicMock(),
    )
    r = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["reason"] == "no_tenant_context"


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_event_emission_not_applicable():
    pytest.skip("event emission N/A — cost gate emits no events directly")
