"""parallelNode contract tests — Phase 3 / WS9.

The parallel node itself does NOT execute branches; it records a fan-out
hint that the workflow engine reads to apply parallel semantics.  Output
envelope: ``{"execution_mode": "all|any|n_of_m", "n": int,
"_fanout_hint": True}``.
"""

from __future__ import annotations

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 1. input schema — accepts mode and n
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_default_mode_is_all():
    ctx = make_ctx("parallelNode", config={})
    r = await NODE_EXECUTORS["parallelNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["execution_mode"] == "all"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["all", "any", "n_of_m"])
async def test_parallel_accepts_known_modes(mode: str):
    ctx = make_ctx("parallelNode", config={"executionMode": mode})
    r = await NODE_EXECUTORS["parallelNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["execution_mode"] == mode


@pytest.mark.asyncio
async def test_parallel_n_of_m_records_n():
    ctx = make_ctx("parallelNode", config={"executionMode": "n_of_m", "n": 2})
    r = await NODE_EXECUTORS["parallelNode"].execute(ctx)
    assert r.output["n"] == 2


# ---------------------------------------------------------------------------
# 2. output schema — fanout hint envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_output_envelope_shape():
    ctx = make_ctx("parallelNode", config={"executionMode": "all"})
    r = await NODE_EXECUTORS["parallelNode"].execute(ctx)
    for key in ("execution_mode", "n", "_fanout_hint"):
        assert key in r.output
    assert r.output["_fanout_hint"] is True


# ---------------------------------------------------------------------------
# 3. success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_success_with_minimal_config():
    ctx = make_ctx("parallelNode", config={"executionMode": "any"})
    r = await NODE_EXECUTORS["parallelNode"].execute(ctx)
    assert r.status == "completed"


# ---------------------------------------------------------------------------
# 4. failure path — node is permissive: garbage modes pass through verbatim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_unknown_mode_passes_through():
    """Unknown modes are recorded verbatim — the engine validates them later."""
    ctx = make_ctx("parallelNode", config={"executionMode": "weirdmode"})
    r = await NODE_EXECUTORS["parallelNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["execution_mode"] == "weirdmode"


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_cancellation_not_applicable():
    pytest.skip(
        "cancellation N/A — parallel node is a fan-out hint; no work to cancel"
    )


# ---------------------------------------------------------------------------
# 6. retry classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_retry_not_applicable():
    pytest.skip("retry N/A — parallel hint is pure / deterministic")


# ---------------------------------------------------------------------------
# 7. tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_tenant_id_does_not_leak():
    cfg = {"executionMode": "all"}
    ra = await NODE_EXECUTORS["parallelNode"].execute(
        make_ctx("parallelNode", config=cfg, tenant_id="t-a")
    )
    rb = await NODE_EXECUTORS["parallelNode"].execute(
        make_ctx("parallelNode", config=cfg, tenant_id="t-b")
    )
    assert ra.output == rb.output


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_event_emission_not_applicable():
    pytest.skip(
        "event emission N/A — parallel records hint; engine emits step events"
    )
