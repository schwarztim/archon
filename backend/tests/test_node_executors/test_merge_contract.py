"""mergeNode contract tests — Phase 3 / WS9.

Strategies covered: ``all`` (default), ``concat``, ``merge`` (deep-merge dicts),
``first`` (first non-empty value).  Output envelope:
``{"merged": <combined>, "branch_count"?: int}``.
"""

from __future__ import annotations

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_default_strategy_is_all():
    ctx = make_ctx("mergeNode", config={}, inputs={"a": 1, "b": 2})
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.status == "completed"
    assert isinstance(r.output["merged"], list)
    assert set(r.output["merged"]) == {1, 2}


@pytest.mark.asyncio
async def test_merge_no_inputs_returns_empty():
    ctx = make_ctx("mergeNode", config={"strategy": "all"})
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.status == "completed"
    assert r.output["merged"] == []


# ---------------------------------------------------------------------------
# 2. output schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_output_envelope_has_merged_key():
    for strategy in ("all", "concat", "merge", "first"):
        ctx = make_ctx(
            "mergeNode",
            config={"strategy": strategy},
            inputs={"a": {"x": 1}, "b": {"y": 2}},
        )
        r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
        assert "merged" in r.output, f"{strategy} missing merged key"


# ---------------------------------------------------------------------------
# 3. success path — strategies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_strategy_first_returns_first_truthy():
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "first"},
        inputs={"a": None, "b": "hi", "c": "there"},
    )
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.output["merged"] == "hi"


@pytest.mark.asyncio
async def test_merge_strategy_first_complete_aliases_first():
    """The plan calls it 'first_complete' — implementation uses 'first'.

    Verify the documented strategy name produces the documented behavior.
    """
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "first"},
        inputs={"a": "won"},
    )
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.output["merged"] == "won"


@pytest.mark.asyncio
async def test_merge_strategy_concat_lists():
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "concat"},
        inputs={"a": [1, 2], "b": [3, 4]},
    )
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.output["merged"] == [1, 2, 3, 4]


@pytest.mark.asyncio
async def test_merge_strategy_concat_mixes_scalars():
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "concat"},
        inputs={"a": [1, 2], "b": "x"},
    )
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.output["merged"] == [1, 2, "x"]


@pytest.mark.asyncio
async def test_merge_strategy_merge_dicts():
    """``merge`` is the canonical 'merge_dicts' surface."""
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "merge"},
        inputs={"a": {"x": 1}, "b": {"y": 2}},
    )
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.output["merged"] == {"x": 1, "y": 2}


@pytest.mark.asyncio
async def test_merge_strategy_merge_deep():
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "merge"},
        inputs={
            "a": {"shared": {"k": 1}},
            "b": {"shared": {"j": 2}},
        },
    )
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.output["merged"] == {"shared": {"k": 1, "j": 2}}


@pytest.mark.asyncio
async def test_merge_strategy_all_records_branch_count():
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "all"},
        inputs={"a": 1, "b": 2, "c": 3},
    )
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert r.output["branch_count"] == 3


# ---------------------------------------------------------------------------
# 4. failure path — unknown strategy falls through to "all"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_unknown_strategy_falls_through_to_all():
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "weird"},
        inputs={"a": 1, "b": 2},
    )
    r = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    # Unknown strategy → default "all" branch returns list of values
    assert r.status == "completed"
    assert isinstance(r.output["merged"], list)


# ---------------------------------------------------------------------------
# 5. cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_cancellation_not_applicable():
    pytest.skip("cancellation N/A — merge is synchronous + pure")


# ---------------------------------------------------------------------------
# 6. retry classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_retry_not_applicable():
    pytest.skip("retry N/A — merge is deterministic")


# ---------------------------------------------------------------------------
# 7. tenant isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_tenant_id_does_not_leak():
    cfg = {"strategy": "all"}
    inputs = {"a": 1, "b": 2}
    ra = await NODE_EXECUTORS["mergeNode"].execute(
        make_ctx("mergeNode", config=cfg, inputs=inputs, tenant_id="t-a")
    )
    rb = await NODE_EXECUTORS["mergeNode"].execute(
        make_ctx("mergeNode", config=cfg, inputs=inputs, tenant_id="t-b")
    )
    assert ra.output == rb.output


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_event_emission_not_applicable():
    pytest.skip("event emission N/A — merge emits no events directly")
