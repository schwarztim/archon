"""switchNode contract tests — Phase 3 / WS9.

Multi-branch routing.  Output envelope: ``{"branch": "<value|default>",
"matched": bool, "evaluated_value": str}``.
"""

from __future__ import annotations

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_missing_expression_is_failed():
    ctx = make_ctx("switchNode", config={"cases": [{"value": "x"}]})
    r = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert r.status == "failed"
    assert "expression" in (r.error or "").lower()


@pytest.mark.asyncio
async def test_switch_missing_cases_falls_to_default():
    """No cases at all → default branch, matched=False."""
    ctx = make_ctx("switchNode", config={"expression": "'red'"})
    r = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["branch"] == "default"
    assert r.output["matched"] is False


# ---------------------------------------------------------------------------
# 2. output schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_output_envelope_shape():
    ctx = make_ctx(
        "switchNode",
        config={"expression": "'red'", "cases": [{"value": "red"}]},
    )
    r = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert r.status == "completed"
    for key in ("branch", "matched", "evaluated_value"):
        assert key in r.output


# ---------------------------------------------------------------------------
# 3. success path — match + default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_matches_first_case():
    ctx = make_ctx(
        "switchNode",
        config={
            "expression": "'red'",
            "cases": [{"value": "red"}, {"value": "blue"}],
        },
    )
    r = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert r.output["branch"] == "red"
    assert r.output["matched"] is True


@pytest.mark.asyncio
async def test_switch_falls_to_default_when_no_match():
    ctx = make_ctx(
        "switchNode",
        config={
            "expression": "'green'",
            "cases": [{"value": "red"}, {"value": "blue"}],
        },
    )
    r = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert r.output["branch"] == "default"
    assert r.output["matched"] is False


@pytest.mark.asyncio
async def test_switch_uses_upstream_inputs():
    ctx = make_ctx(
        "switchNode",
        config={
            "expression": "color",
            "cases": [{"value": "red"}, {"value": "blue"}],
        },
        inputs={"u1": {"color": "blue"}},
    )
    r = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert r.output["branch"] == "blue"


# ---------------------------------------------------------------------------
# 4. failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_invalid_expression_falls_through_to_default():
    """A bad expression is caught and treated as the literal expression value.

    Contract: never crash; default branch when no case matches the literal.
    """
    ctx = make_ctx(
        "switchNode",
        config={
            "expression": "((((not python",
            "cases": [{"value": "red"}],
        },
    )
    r = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["branch"] == "default"


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_cancellation_not_applicable():
    pytest.skip("cancellation N/A — switch is synchronous + pure")


# ---------------------------------------------------------------------------
# 6. retry classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_retry_not_applicable():
    pytest.skip("retry N/A — switch is deterministic")


# ---------------------------------------------------------------------------
# 7. tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_tenant_id_does_not_leak():
    cfg = {"expression": "'red'", "cases": [{"value": "red"}]}
    ra = await NODE_EXECUTORS["switchNode"].execute(
        make_ctx("switchNode", config=cfg, tenant_id="t-a")
    )
    rb = await NODE_EXECUTORS["switchNode"].execute(
        make_ctx("switchNode", config=cfg, tenant_id="t-b")
    )
    assert ra.output == rb.output


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_event_emission_not_applicable():
    pytest.skip("event emission N/A — switch emits no events directly")
