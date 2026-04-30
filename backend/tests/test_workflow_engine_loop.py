"""Loop engine tests — ADR-003 body-iteration semantics.

Verify that:
  * loopNode runs the body sub-graph max_iterations times when no condition.
  * loopNode exits early when condition_expr evaluates to False after an iteration.
  * loopNode hard-caps at max_iterations (engine + executor enforce both).
  * accumulate_mode "list" returns per-iteration outputs.
  * accumulate_mode "last" returns the final iteration's outputs only.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register  # noqa: E402
from app.services.workflow_engine import execute_workflow_dag  # noqa: E402


# ---------------------------------------------------------------------------
# A counter executor — increments a counter per call so we can observe how
# many times the loop body actually ran.  The counter is module-level so
# fixtures can reset it between tests.
# ---------------------------------------------------------------------------


_COUNTER: dict[str, int] = {"calls": 0}


@register("testCounterNode")
class _CounterNode(NodeExecutor):
    async def execute(self, ctx: NodeContext) -> NodeResult:
        _COUNTER["calls"] += 1
        # Read the iteration_var to surface it in the output for
        # accumulator inspection.
        iteration_var = ctx.config.get("iteration_var", "index")
        idx = ctx.inputs.get(iteration_var)
        return NodeResult(
            status="completed",
            output={
                "calls": _COUNTER["calls"],
                "iteration": idx,
                "step_id": ctx.step_id,
            },
        )


@pytest.fixture(autouse=True)
def _reset_counter():
    _COUNTER["calls"] = 0
    yield
    _COUNTER["calls"] = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step(
    step_id: str,
    *,
    node_type: str = "testCounterNode",
    config: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "name": step_id,
        "node_type": node_type,
        "config": config or {},
        "depends_on": depends_on or [],
    }


# ---------------------------------------------------------------------------
# Loop runs body up to max_iterations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_runs_body_max_iterations_times():
    """A loop with max_iterations=3 and no condition runs body 3 times."""
    workflow = {
        "id": "wf-loop-3",
        "name": "loop-3",
        "steps": [
            _step(
                "loop",
                node_type="loopNode",
                config={
                    "body_step_ids": ["body"],
                    "max_iterations": 3,
                    "accumulate_mode": "list",
                },
            ),
            _step("body", config={}, depends_on=["loop"]),
        ],
    }
    result = await execute_workflow_dag(workflow)
    assert result["status"] == "completed"
    # Body executor was invoked 3 times.
    assert _COUNTER["calls"] == 3
    by_id = {s["step_id"]: s for s in result["steps"]}
    loop_out = by_id["loop"]["output_data"]
    assert loop_out["completed_iterations"] == 3
    # accumulate_mode=list returns one entry per iteration.
    assert isinstance(loop_out["result"], list)
    assert len(loop_out["result"]) == 3


# ---------------------------------------------------------------------------
# Loop exits early when condition is False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_exits_early_when_condition_false():
    """A condition_expr evaluating to False after iteration N halts the loop."""
    # Condition: keep going while iteration index is < 1 (so we run twice
    # — index 0 and index 1 — then halt because at end of iteration 1
    # condition `index < 1` is False).
    workflow = {
        "id": "wf-loop-cond",
        "name": "loop-cond",
        "steps": [
            _step(
                "loop",
                node_type="loopNode",
                config={
                    "body_step_ids": ["body"],
                    "max_iterations": 10,
                    "accumulate_mode": "list",
                    "condition_expr": "index < 1",
                    "iteration_var": "index",
                },
            ),
            _step("body", config={}, depends_on=["loop"]),
        ],
    }
    result = await execute_workflow_dag(workflow)
    assert result["status"] == "completed"
    # Body ran twice, then condition was False after iteration 1.
    assert _COUNTER["calls"] == 2


# ---------------------------------------------------------------------------
# Loop hard-cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_max_iterations_hard_cap():
    """max_iterations=3 with an always-True condition still stops at 3."""
    workflow = {
        "id": "wf-loop-cap",
        "name": "loop-cap",
        "steps": [
            _step(
                "loop",
                node_type="loopNode",
                config={
                    "body_step_ids": ["body"],
                    "max_iterations": 3,
                    "accumulate_mode": "last",
                    "condition_expr": "True",  # always continue
                    "iteration_var": "index",
                },
            ),
            _step("body", config={}, depends_on=["loop"]),
        ],
    }
    result = await execute_workflow_dag(workflow)
    assert result["status"] == "completed"
    # Body capped at 3.
    assert _COUNTER["calls"] == 3
    by_id = {s["step_id"]: s for s in result["steps"]}
    assert by_id["loop"]["output_data"]["completed_iterations"] == 3


# ---------------------------------------------------------------------------
# accumulate_mode == "list"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_accumulate_list_returns_per_iteration_outputs():
    workflow = {
        "id": "wf-loop-list",
        "name": "loop-list",
        "steps": [
            _step(
                "loop",
                node_type="loopNode",
                config={
                    "body_step_ids": ["body"],
                    "max_iterations": 3,
                    "accumulate_mode": "list",
                },
            ),
            _step("body", config={}, depends_on=["loop"]),
        ],
    }
    result = await execute_workflow_dag(workflow)
    by_id = {s["step_id"]: s for s in result["steps"]}
    loop_out = by_id["loop"]["output_data"]
    assert isinstance(loop_out["result"], list)
    assert len(loop_out["result"]) == 3
    # Each entry contains the body step's output for that iteration.
    for i, entry in enumerate(loop_out["result"]):
        assert "body" in entry
        assert entry["body"]["status"] == "completed"


# ---------------------------------------------------------------------------
# accumulate_mode == "last"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_accumulate_last_returns_final_output_only():
    workflow = {
        "id": "wf-loop-last",
        "name": "loop-last",
        "steps": [
            _step(
                "loop",
                node_type="loopNode",
                config={
                    "body_step_ids": ["body"],
                    "max_iterations": 3,
                    "accumulate_mode": "last",
                },
            ),
            _step("body", config={}, depends_on=["loop"]),
        ],
    }
    result = await execute_workflow_dag(workflow)
    by_id = {s["step_id"]: s for s in result["steps"]}
    loop_out = by_id["loop"]["output_data"]
    # accumulate_mode="last" — the result is the final iteration's
    # outputs dict (not a list of all iterations).
    assert isinstance(loop_out["result"], dict)
    assert "body" in loop_out["result"]
    # The iteration counter saw 3 calls (last iteration's body output
    # records calls=3).
    body_output = loop_out["result"]["body"]["output"]
    assert body_output["calls"] == 3
