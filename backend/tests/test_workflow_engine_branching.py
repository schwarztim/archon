"""Branch-aware engine tests — ADR-003 condition / switch routing.

Verify that:
  * conditionNode true_branch run; false_branch + descendants get step.skipped
  * conditionNode false_branch run; true_branch + descendants get step.skipped
  * switchNode selects the matching case; non-matching cases get step.skipped
  * switchNode falls through to default_step_id
  * malformed branch hints (unknown step_id) raise WorkflowValidationError

The engine emits ``step_skipped`` events through the on_step_event callback
for unselected branches.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services.workflow_engine import (  # noqa: E402
    WorkflowValidationError,
    execute_workflow_dag,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_step(
    step_id: str,
    *,
    node_type: str = "outputNode",
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


def _collect_events() -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = []

    async def _on(payload: dict[str, Any]) -> None:
        events.append(payload)

    return events, _on


# ---------------------------------------------------------------------------
# conditionNode — true branch wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_true_branch_runs_false_branch_skipped():
    """true_branch executes; false_branch is marked skipped with step.skipped event."""
    events, on_event = _collect_events()
    workflow = {
        "id": "wf-cond-true",
        "name": "cond-true",
        "steps": [
            _stub_step(
                "cond",
                node_type="conditionNode",
                config={
                    "expression": "1 == 1",
                    "true_branch": "true_step",
                    "false_branch": "false_step",
                },
            ),
            _stub_step("true_step", depends_on=["cond"]),
            _stub_step("false_step", depends_on=["cond"]),
        ],
    }

    result = await execute_workflow_dag(workflow, on_step_event=on_event)

    assert result["status"] == "completed"
    by_id = {s["step_id"]: s for s in result["steps"]}
    assert by_id["cond"]["status"] == "completed"
    assert by_id["true_step"]["status"] == "completed"
    assert by_id["false_step"]["status"] == "skipped"
    assert by_id["false_step"]["error"] == "branch_not_selected"

    # The engine emitted a step_skipped event for false_step.
    skipped_events = [
        e for e in events
        if e.get("type") == "step_skipped" and e.get("step_id") == "false_step"
    ]
    assert skipped_events, "expected a step_skipped event for the unselected branch"
    assert skipped_events[0]["reason"] == "branch_not_selected"


# ---------------------------------------------------------------------------
# conditionNode — false branch wins
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_false_branch_runs_true_branch_skipped():
    """false_branch executes; true_branch is marked skipped with step.skipped event."""
    events, on_event = _collect_events()
    workflow = {
        "id": "wf-cond-false",
        "name": "cond-false",
        "steps": [
            _stub_step(
                "cond",
                node_type="conditionNode",
                config={
                    "expression": "1 == 2",
                    "true_branch": "true_step",
                    "false_branch": "false_step",
                },
            ),
            _stub_step("true_step", depends_on=["cond"]),
            _stub_step("false_step", depends_on=["cond"]),
        ],
    }

    result = await execute_workflow_dag(workflow, on_step_event=on_event)

    assert result["status"] == "completed"
    by_id = {s["step_id"]: s for s in result["steps"]}
    assert by_id["true_step"]["status"] == "skipped"
    assert by_id["false_step"]["status"] == "completed"

    skipped_events = [
        e for e in events
        if e.get("type") == "step_skipped" and e.get("step_id") == "true_step"
    ]
    assert skipped_events


# ---------------------------------------------------------------------------
# switchNode — matching case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_selects_matching_case():
    events, on_event = _collect_events()
    workflow = {
        "id": "wf-switch-match",
        "name": "switch-match",
        "steps": [
            _stub_step(
                "sw",
                node_type="switchNode",
                config={
                    "value_expr": "'red'",
                    "cases": {"red": "red_step", "blue": "blue_step"},
                    "default_step_id": "default_step",
                },
            ),
            _stub_step("red_step", depends_on=["sw"]),
            _stub_step("blue_step", depends_on=["sw"]),
            _stub_step("default_step", depends_on=["sw"]),
        ],
    }

    result = await execute_workflow_dag(workflow, on_step_event=on_event)
    assert result["status"] == "completed"
    by_id = {s["step_id"]: s for s in result["steps"]}
    assert by_id["red_step"]["status"] == "completed"
    assert by_id["blue_step"]["status"] == "skipped"
    assert by_id["default_step"]["status"] == "skipped"

    skipped_ids = {
        e["step_id"] for e in events if e.get("type") == "step_skipped"
    }
    assert "blue_step" in skipped_ids
    assert "default_step" in skipped_ids


# ---------------------------------------------------------------------------
# switchNode — falls through to default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_falls_through_to_default():
    events, on_event = _collect_events()
    workflow = {
        "id": "wf-switch-default",
        "name": "switch-default",
        "steps": [
            _stub_step(
                "sw",
                node_type="switchNode",
                config={
                    "value_expr": "'green'",
                    "cases": {"red": "red_step", "blue": "blue_step"},
                    "default_step_id": "default_step",
                },
            ),
            _stub_step("red_step", depends_on=["sw"]),
            _stub_step("blue_step", depends_on=["sw"]),
            _stub_step("default_step", depends_on=["sw"]),
        ],
    }

    result = await execute_workflow_dag(workflow, on_step_event=on_event)
    assert result["status"] == "completed"
    by_id = {s["step_id"]: s for s in result["steps"]}
    assert by_id["default_step"]["status"] == "completed"
    assert by_id["red_step"]["status"] == "skipped"
    assert by_id["blue_step"]["status"] == "skipped"


# ---------------------------------------------------------------------------
# Branch hint with invalid step_id raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_hint_invalid_step_id_raises():
    """If a branch hint references a step_id not present in the workflow,
    the engine raises WorkflowValidationError.
    """
    workflow = {
        "id": "wf-cond-invalid",
        "name": "cond-invalid",
        "steps": [
            _stub_step(
                "cond",
                node_type="conditionNode",
                config={
                    "expression": "1 == 1",
                    "true_branch": "ghost_step",  # not in workflow
                    "false_branch": "false_step",
                },
            ),
            _stub_step("false_step", depends_on=["cond"]),
        ],
    }

    with pytest.raises(WorkflowValidationError):
        await execute_workflow_dag(workflow)


# ---------------------------------------------------------------------------
# Branch hint propagates skip to descendants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_skip_propagates_to_descendants():
    """When a branch is unselected, its transitive descendants are skipped too."""
    events, on_event = _collect_events()
    workflow = {
        "id": "wf-cond-deep",
        "name": "cond-deep",
        "steps": [
            _stub_step(
                "cond",
                node_type="conditionNode",
                config={
                    "expression": "1 == 1",
                    "true_branch": "true_step",
                    "false_branch": "false_step",
                },
            ),
            _stub_step("true_step", depends_on=["cond"]),
            _stub_step("false_step", depends_on=["cond"]),
            _stub_step("false_descendant", depends_on=["false_step"]),
        ],
    }

    result = await execute_workflow_dag(workflow, on_step_event=on_event)
    assert result["status"] == "completed"
    by_id = {s["step_id"]: s for s in result["steps"]}
    assert by_id["true_step"]["status"] == "completed"
    assert by_id["false_step"]["status"] == "skipped"
    assert by_id["false_descendant"]["status"] == "skipped"
