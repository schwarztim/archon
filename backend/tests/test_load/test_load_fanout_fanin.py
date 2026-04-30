"""Phase 6 load profile #2 — N workflows with parallel fan-out + fan-in.

Each workflow has the topology:

         ┌── a ──┐
         │       │
    fanout ─ b ─ join
         │       │
         ├── c ──┤
         ├── d ──┤
         └── e ──┘

Where ``fanout`` is a ``parallelNode`` mode=all with 5 children, and
``join`` is a ``mergeNode`` (strategy=merge_dicts). Each workflow
produces 1 fanout + 5 branches + 1 merge = 7 step rows. With N=20 runs,
that's 140 step rows total.

Validates:
  * dispatcher handles parallel sub-graphs at scale
  * branch ordering may vary, but merge always succeeds
  * each run's event chain is intact (run.claimed → started → completed)
  * no double-execute (each step appears exactly once per run)

Default N=20 (10 in CI). Per-run step count must be 7.
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")


def _make_fanout_steps(branch_count: int = 5) -> list[dict]:
    """Build a fanout-fanin step list with the given branch count.

    Topology: ``fanout`` (parallelNode mode=all) → branches a..n →
    ``join`` (mergeNode merge_dicts).
    """
    branch_ids = [f"branch_{i}" for i in range(branch_count)]
    steps: list[dict] = [
        {
            "step_id": "fanout",
            "name": "fanout",
            "node_type": "parallelNode",
            "config": {"mode": "all", "step_ids": branch_ids},
            "depends_on": [],
        }
    ]
    for bid in branch_ids:
        steps.append(
            {
                "step_id": bid,
                "name": bid,
                "node_type": "outputNode",
                "config": {"value": bid},
                "depends_on": ["fanout"],
            }
        )
    steps.append(
        {
            "step_id": "join",
            "name": "join",
            "node_type": "mergeNode",
            "config": {"strategy": "merge_dicts"},
            "depends_on": list(branch_ids),
        }
    )
    return steps


@pytest.fixture()
def fanout_n() -> int:
    """Profile 2 N — defaults to 20 locally, but honour LOAD_TEST_N.

    For CI (LOAD_TEST_N=10), keep at 10. The cap is lower than the
    simple-workflow profile because each run produces 7× the rows.
    """
    raw = os.environ.get("LOAD_TEST_N", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 20


BRANCH_COUNT = 5


@pytest.mark.asyncio
async def test_load_fanout_fanin_all_branches_complete(
    fanout_n,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
    wait_terminal_helper,
    double_execute_helper,
    event_chain_helper,
    budget_helper,
):
    """Profile 2: N parallel-merge workflows; total step exec = N × 7."""
    n = fanout_n
    _engine, factory = patched_dispatcher

    steps = _make_fanout_steps(branch_count=BRANCH_COUNT)
    expected_steps_per_run = len(steps)  # 1 + BRANCH_COUNT + 1 = 7

    run_ids = [await seed_run_factory(steps) for _ in range(n)]

    # ── Dispatch ─────────────────────────────────────────────────────
    start = time.monotonic()
    results = await dispatch_helper(run_ids, worker_id_prefix="fanout")
    elapsed = time.monotonic() - start

    # Budget: parallel sub-graphs are heavier than simple workflows.
    # Local (N=20) → 60s; CI (N=10) → 120s
    budget = 60.0 if n >= 20 else 120.0
    budget_helper(elapsed, budget_s=budget, label=f"fanout-N{n}")

    # ── Assert each run completed cleanly ────────────────────────────
    completed = 0
    for rid, outcome in results:
        assert not isinstance(outcome, BaseException), (
            f"dispatch raised for {rid}: {outcome!r}"
        )
        assert outcome is not None, f"dispatch returned None for {rid}"
        assert outcome.status == "completed", (
            f"run {rid} status={outcome.status!r}"
        )

        final = await wait_terminal_helper(factory, rid, timeout=15.0)
        assert final == "completed"

        # Event chain present.
        types = await event_chain_helper(factory, rid)
        # Every branch + the merge must have produced a step.completed.
        step_completed_count = sum(
            1 for t in types if t == "step.completed"
        )
        # We expect at least 1 (fanout) + BRANCH_COUNT (branches) + 1 (join)
        # = 7 step.completed events. The dispatcher emits these via the
        # step persistence loop.
        assert step_completed_count == expected_steps_per_run, (
            f"{rid}: expected {expected_steps_per_run} step.completed "
            f"events, saw {step_completed_count}"
        )

        # No double-execute.
        await double_execute_helper(
            factory, rid, expected_step_count=expected_steps_per_run
        )
        completed += 1

    assert completed == n


@pytest.mark.asyncio
async def test_load_fanout_total_step_rows_matches_expected(
    fanout_n,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
):
    """Total workflow_run_steps row count must equal N × 7 (no dupes)."""
    n = fanout_n
    _engine, factory = patched_dispatcher

    steps = _make_fanout_steps(branch_count=BRANCH_COUNT)
    expected_per_run = len(steps)

    run_ids = [await seed_run_factory(steps) for _ in range(n)]
    await dispatch_helper(run_ids, worker_id_prefix="fanout-rows")

    from sqlalchemy import select

    from app.models.workflow import WorkflowRunStep

    async with factory() as session:
        rows = (
            await session.execute(select(WorkflowRunStep))
        ).scalars().all()

    expected_total = n * expected_per_run
    assert len(rows) == expected_total, (
        f"fanout: expected {expected_total} step rows "
        f"(N={n} × {expected_per_run}), got {len(rows)}"
    )
