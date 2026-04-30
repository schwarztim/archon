"""loopNode contract tests — Phase 3 / WS9.

v1 loop is a counter-based hint: records ``max_iterations``, ``condition``
(string passed through), and ``iteration_var``; the engine interprets the
loop semantics at the DAG level.  Output envelope:
``{"max_iterations": int, "condition": str|None, "iteration_var": str,
"_loop_hint": True}``.
"""

from __future__ import annotations

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_default_max_iterations_is_10():
    ctx = make_ctx("loopNode", config={})
    r = await NODE_EXECUTORS["loopNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["max_iterations"] == 10


@pytest.mark.asyncio
async def test_loop_camel_and_snake_case():
    ctx_camel = make_ctx("loopNode", config={"maxIterations": 7})
    ctx_snake = make_ctx("loopNode", config={"max_iterations": 7})
    r_c = await NODE_EXECUTORS["loopNode"].execute(ctx_camel)
    r_s = await NODE_EXECUTORS["loopNode"].execute(ctx_snake)
    assert r_c.output["max_iterations"] == 7
    assert r_s.output["max_iterations"] == 7


# ---------------------------------------------------------------------------
# 2. output schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_output_envelope_shape():
    ctx = make_ctx(
        "loopNode",
        config={"maxIterations": 5, "condition": "x < 10", "iterationVar": "i"},
    )
    r = await NODE_EXECUTORS["loopNode"].execute(ctx)
    for key in ("max_iterations", "condition", "iteration_var", "_loop_hint"):
        assert key in r.output
    assert r.output["_loop_hint"] is True


# ---------------------------------------------------------------------------
# 3. success path — honors max_iterations cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_max_iterations_recorded():
    ctx = make_ctx("loopNode", config={"maxIterations": 5})
    r = await NODE_EXECUTORS["loopNode"].execute(ctx)
    assert r.output["max_iterations"] == 5


@pytest.mark.asyncio
async def test_loop_condition_passed_through():
    ctx = make_ctx("loopNode", config={"maxIterations": 3, "condition": "i < 3"})
    r = await NODE_EXECUTORS["loopNode"].execute(ctx)
    assert r.output["condition"] == "i < 3"


@pytest.mark.asyncio
async def test_loop_default_iteration_var_is_index():
    ctx = make_ctx("loopNode", config={"maxIterations": 1})
    r = await NODE_EXECUTORS["loopNode"].execute(ctx)
    assert r.output["iteration_var"] == "index"


# ---------------------------------------------------------------------------
# 4. failure path — non-numeric maxIterations raises ValueError before pass-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_non_numeric_max_iterations_raises():
    """int(...) coercion raises; the dispatcher catches it as a step failure."""
    ctx = make_ctx("loopNode", config={"maxIterations": "not-a-number"})
    with pytest.raises((ValueError, TypeError)):
        await NODE_EXECUTORS["loopNode"].execute(ctx)


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_cancellation_not_applicable():
    pytest.skip("cancellation N/A — loop v1 is a hint; no body executed inline")


# ---------------------------------------------------------------------------
# 6. retry classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_retry_not_applicable():
    pytest.skip("retry N/A — loop hint is deterministic")


# ---------------------------------------------------------------------------
# 7. tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_tenant_id_does_not_leak():
    cfg = {"maxIterations": 3}
    ra = await NODE_EXECUTORS["loopNode"].execute(
        make_ctx("loopNode", config=cfg, tenant_id="t-a")
    )
    rb = await NODE_EXECUTORS["loopNode"].execute(
        make_ctx("loopNode", config=cfg, tenant_id="t-b")
    )
    assert ra.output == rb.output


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_event_emission_not_applicable():
    pytest.skip("event emission N/A — loop hint emits no events")
