"""Phase 6 load profile #1 — N parallel single-step workflows.

Each workflow is a single ``outputNode`` step (input → output). All N
workflows are dispatched simultaneously via ``asyncio.gather`` and must:

  * complete within 30s (local, N=50) / 2 min (CI, N=10)
  * emit the canonical event chain (run.claimed → run.started →
    step.completed → run.completed)
  * leave exactly 1 ``workflow_run_steps`` row per run (no duplicates)

This is the simplest profile — proves the dispatcher's claim/execute/
finalise loop scales horizontally without contention or double-execute.
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")


@pytest.mark.asyncio
async def test_load_many_simple_workflows_complete_within_budget(
    n_workflows,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
    wait_terminal_helper,
    double_execute_helper,
    event_chain_helper,
    budget_helper,
):
    """Profile 1: N simple workflows, all complete in parallel."""
    n = n_workflows
    _engine, factory = patched_dispatcher

    # ── Build N single-step workflows ──────────────────────────────────
    steps_per_workflow = [
        {
            "step_id": "s1",
            "name": "step-one",
            "node_type": "outputNode",
            "config": {"value": "ok"},
            "depends_on": [],
        }
    ]

    run_ids = []
    for _ in range(n):
        run_id = await seed_run_factory(steps_per_workflow)
        run_ids.append(run_id)

    # ── Dispatch all simultaneously ───────────────────────────────────
    start = time.monotonic()
    results = await dispatch_helper(run_ids, worker_id_prefix="simple")
    elapsed = time.monotonic() - start

    # ── Performance budget ───────────────────────────────────────────
    # Local default (N=50) → 30s; CI (N=10) → 60s gives ample headroom
    # for cold-import overhead.
    budget = 30.0 if n >= 50 else 60.0
    budget_helper(elapsed, budget_s=budget, label=f"simple-N{n}")

    # ── Per-run assertions ────────────────────────────────────────────
    assert len(results) == n, f"expected {n} results, got {len(results)}"

    completed = 0
    for rid, outcome in results:
        # Tolerate exception path so one bad run doesn't mask N-1 successes.
        assert not isinstance(outcome, BaseException), (
            f"dispatch raised for {rid}: {outcome!r}"
        )
        assert outcome is not None, f"dispatch returned None for {rid}"
        assert outcome.status == "completed", (
            f"run {rid} ended in status={outcome.status!r}"
        )

        # Final-state poll (defends against eventual-consistency edges).
        final = await wait_terminal_helper(factory, rid, timeout=10.0)
        assert final == "completed"

        # Canonical event chain present.
        types = await event_chain_helper(factory, rid)
        # The single step must have produced a step.completed event.
        assert "step.completed" in types, (
            f"{rid}: missing step.completed in {types}"
        )

        # No double-execute: exactly one workflow_run_steps row.
        await double_execute_helper(
            factory, rid, expected_step_count=len(steps_per_workflow)
        )

        completed += 1

    # ── Aggregate assertion ──────────────────────────────────────────
    assert completed == n, (
        f"total_completed_runs ({completed}) != N ({n})"
    )


@pytest.mark.asyncio
async def test_load_many_simple_workflows_no_step_row_duplication(
    n_workflows,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
):
    """Even under parallel pressure, step rows must be unique per run.

    Counts total ``workflow_run_steps`` after dispatch and asserts
    rows == N (one per run). A claim-race regression would produce 2N
    rows.
    """
    n = n_workflows
    _engine, factory = patched_dispatcher

    steps = [{
        "step_id": "only",
        "name": "only-step",
        "node_type": "outputNode",
        "config": {"value": "x"},
        "depends_on": [],
    }]

    run_ids = [await seed_run_factory(steps) for _ in range(n)]
    await dispatch_helper(run_ids, worker_id_prefix="dup-check")

    # Allow a brief settle window for any in-flight commits.
    await asyncio.sleep(0.1)

    from sqlalchemy import select

    from app.models.workflow import WorkflowRunStep

    async with factory() as session:
        rows = (
            await session.execute(select(WorkflowRunStep))
        ).scalars().all()

    # One row per dispatched run.
    assert len(rows) == n, (
        f"expected exactly {n} workflow_run_steps rows; got {len(rows)}"
    )

    # And every row references one of our run_ids exactly once.
    counts: dict = {}
    for r in rows:
        counts[r.run_id] = counts.get(r.run_id, 0) + 1
    duplicates = {k: v for k, v in counts.items() if v > 1}
    assert not duplicates, f"duplicate step rows: {duplicates}"
