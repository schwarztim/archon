"""conditionNode contract tests — Phase 3 / WS9.

Coverage dimensions: input schema, output schema (branch envelope), success
(true/false), failure (missing/invalid expression), cancellation (N/A —
purely synchronous), retry classification (N/A — deterministic), tenant
isolation (no DB calls), event emission (N/A — dispatcher-side).
"""

from __future__ import annotations

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_missing_expression_is_failed():
    ctx = make_ctx("conditionNode", config={})
    result = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert result.status == "failed"
    assert "expression" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_condition_accepts_condition_group():
    """The visual builder may emit a ``conditions`` block instead of an expression."""
    ctx = make_ctx(
        "conditionNode",
        config={
            "conditions": {
                "logic": "AND",
                "conditions": [
                    {"field": "status", "operator": "equals", "value": "ok"},
                ],
            },
        },
    )
    result = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    # expression compiles; result is a literal-comparison so should evaluate
    assert result.status == "completed"
    assert result.output["branch"] in {"true", "false"}


# ---------------------------------------------------------------------------
# 2. output schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_output_envelope_shape():
    ctx = make_ctx("conditionNode", config={"expression": "1 == 1"})
    result = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert result.status == "completed"
    assert "branch" in result.output
    assert "result" in result.output
    assert result.output["branch"] in {"true", "false"}
    assert isinstance(result.output["result"], bool)


# ---------------------------------------------------------------------------
# 3. success path — true / false branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_true_branch():
    ctx = make_ctx("conditionNode", config={"expression": "1 == 1"})
    r = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["branch"] == "true"
    assert r.output["result"] is True


@pytest.mark.asyncio
async def test_condition_false_branch():
    ctx = make_ctx("conditionNode", config={"expression": "1 == 2"})
    r = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["branch"] == "false"
    assert r.output["result"] is False


@pytest.mark.asyncio
async def test_condition_uses_upstream_inputs():
    """Inputs flatten into the eval namespace (both ``step.field`` and ``field``)."""
    ctx = make_ctx(
        "conditionNode",
        config={"expression": "score > 50"},
        inputs={"upstream": {"score": 75}},
    )
    r = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["branch"] == "true"


# ---------------------------------------------------------------------------
# 4. failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_invalid_expression_is_failed():
    ctx = make_ctx("conditionNode", config={"expression": "this is not python"})
    r = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert r.status == "failed"
    assert r.error is not None


@pytest.mark.asyncio
async def test_condition_disallowed_function_call():
    """simpleeval rejects function calls — contract: status=failed."""
    ctx = make_ctx("conditionNode", config={"expression": "__import__('os')"})
    r = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert r.status == "failed"


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_cancellation_not_applicable():
    pytest.skip("cancellation N/A — condition is a synchronous pure function")


# ---------------------------------------------------------------------------
# 6. retry classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_retry_classification_not_applicable():
    pytest.skip("retry N/A — condition is deterministic; failure is permanent")


# ---------------------------------------------------------------------------
# 7. tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_tenant_id_does_not_leak():
    """No DB calls; tenant_id has no observable effect on output."""
    ctx_a = make_ctx(
        "conditionNode", config={"expression": "1 == 1"}, tenant_id="tenant-a"
    )
    ctx_b = make_ctx(
        "conditionNode", config={"expression": "1 == 1"}, tenant_id="tenant-b"
    )
    a = await NODE_EXECUTORS["conditionNode"].execute(ctx_a)
    b = await NODE_EXECUTORS["conditionNode"].execute(ctx_b)
    assert a.output == b.output


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_event_emission_not_applicable():
    pytest.skip("event emission N/A — condition emits no events directly")
