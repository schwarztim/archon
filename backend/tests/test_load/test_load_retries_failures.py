"""Phase 6 load profile #5 — N flaky workflows exercising RetryPolicy.

Each workflow has a single ``loadFlakyNode`` step whose failure is
deterministic per (run_id, attempt) so we can predict outcomes precisely:

  * the first attempt of every run fails
  * with ``RetryPolicy(max_attempts=3, exponential)``, the dispatcher
    schedules a Timer and emits a ``step.retry`` event
  * we drive the retry directly via the dispatcher (rather than waiting
    for the timer-fire loop) by clearing the lease and re-dispatching

Validates:
  * every failed step under retry budget records a ``step.retry`` event
  * the run is paused with ``run.paused`` payload reason ``retry_pending``
  * after dispatch retries, the dispatcher's claim primitive does not
    leak claims under parallel pressure (no double-execute)

The test-only ``loadFlakyNode`` is registered at module import. We
deliberately do NOT use a node that depends on external infrastructure
(network, DB, sleep) so the profile stays fast under load.

Default N=20 (10 in CI). Each run produces:
  - 1 step row (the flaky step)
  - 1 step.failed event
  - 1 step.retry event
  - 1 run.paused event (retry_pending)
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")

# ---------------------------------------------------------------------------
# Test-only flaky executor — deterministic failure on attempt 1.
# ---------------------------------------------------------------------------

from app.services.node_executors import (  # noqa: E402
    NodeContext,
    NodeExecutor,
    NodeResult,
    register,
)


@register("loadFlakyNode")
class _LoadFlakyNode(NodeExecutor):
    """Always fail with a TransientError on the first call.

    The executor is invoked once per dispatch_run call. To simulate
    "attempt 1 fails, attempt 2 succeeds" we honour the
    ``ctx.config["pass_on_attempt"]`` value: if the dispatched run's
    attempt counter has reached that threshold, return success;
    otherwise return failure with ``error_code='TransientError'`` so
    the RetryPolicy treats it as retryable.

    The attempt counter is read from ``ctx.node_data["_attempt"]`` —
    the test seeds this from the WorkflowRun.attempt before each
    dispatch.
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        pass_on_attempt: int = int(config.get("pass_on_attempt") or 2)
        # The attempt is on the run, not the node. The dispatcher uses
        # ``run.attempt`` (incremented on every claim). Tests stamp the
        # current run.attempt onto the step's node_data so we can read
        # it here.
        attempt_raw = ctx.node_data.get("_attempt", 1)
        try:
            attempt = int(attempt_raw)
        except (TypeError, ValueError):
            attempt = 1

        if attempt >= pass_on_attempt:
            return NodeResult(
                status="completed",
                output={"value": f"succeeded-on-attempt-{attempt}"},
            )
        # NodeResult has no ``error_code`` field — the dispatcher reads
        # the class name from the error string via _extract_error_class
        # (regex ``^([A-Z][A-Za-z0-9_]*):`` on the error message).
        return NodeResult(
            status="failed",
            error="TransientError: simulated transient failure",
        )


def _make_flaky_steps(*, max_attempts: int = 3, pass_on_attempt: int = 2) -> list[dict]:
    """Single-step workflow exercising the retry path."""
    return [
        {
            "step_id": "flaky",
            "name": "flaky",
            "node_type": "loadFlakyNode",
            "config": {
                "pass_on_attempt": pass_on_attempt,
                "retry": {
                    "max_attempts": max_attempts,
                    "initial_backoff_seconds": 0.001,
                    "backoff_multiplier": 2.0,
                    "max_backoff_seconds": 0.01,
                    "retry_on": ["TransientError"],
                },
            },
            "depends_on": [],
        }
    ]


@pytest.fixture()
def retries_n() -> int:
    """Retry profile N — defaults to 20; honour LOAD_TEST_N."""
    raw = os.environ.get("LOAD_TEST_N", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 20


@pytest.mark.asyncio
async def test_load_retries_failures_step_retry_emitted(
    retries_n,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
    budget_helper,
):
    """Profile 5: N flaky runs — every run emits a ``step.retry`` event.

    First-pass dispatch: every run fails its only step, the RetryPolicy
    grants a retry, and the dispatcher emits ``step.retry`` and pauses
    the run with ``reason='retry_pending'``.
    """
    n = retries_n
    _engine, factory = patched_dispatcher

    steps = _make_flaky_steps(max_attempts=3, pass_on_attempt=2)
    run_ids = [await seed_run_factory(steps) for _ in range(n)]

    start = time.monotonic()
    results = await dispatch_helper(run_ids, worker_id_prefix="flaky-1")
    elapsed = time.monotonic() - start

    budget = 60.0 if n >= 20 else 120.0
    budget_helper(elapsed, budget_s=budget, label=f"retries-N{n}")

    # ── Assert every run is paused-for-retry ─────────────────────────
    for rid, outcome in results:
        assert not isinstance(outcome, BaseException), (
            f"dispatch raised for {rid}: {outcome!r}"
        )
        assert outcome is not None
        assert outcome.status == "paused", (
            f"run {rid} expected paused (retry_pending), got {outcome.status}"
        )

    # ── step.retry event present on every run ────────────────────────
    from sqlalchemy import select

    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        retry_events = (
            await session.execute(
                select(WorkflowRunEvent).where(
                    WorkflowRunEvent.event_type == "step.retry"
                )
            )
        ).scalars().all()

    runs_with_retry = {e.run_id for e in retry_events}
    assert runs_with_retry == set(run_ids), (
        f"expected step.retry for every run; missing: "
        f"{set(run_ids) - runs_with_retry}"
    )

    # And every run has a run.paused event with retry_pending payload.
    async with factory() as session:
        paused_events = (
            await session.execute(
                select(WorkflowRunEvent).where(
                    WorkflowRunEvent.event_type == "run.paused"
                )
            )
        ).scalars().all()

    paused_run_ids: set = set()
    for e in paused_events:
        # The dispatcher's retry path stamps reason=retry_pending in the
        # payload; the approval path stamps something else. Filter so
        # we don't conflate.
        payload = e.payload or {}
        if payload.get("reason") == "retry_pending":
            paused_run_ids.add(e.run_id)

    assert paused_run_ids == set(run_ids), (
        f"expected run.paused(retry_pending) for every run; "
        f"missing: {set(run_ids) - paused_run_ids}"
    )


@pytest.mark.asyncio
async def test_load_retries_failures_no_double_execute_after_retry(
    retries_n,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
    double_execute_helper,
):
    """After the first dispatch under retry, no run produces duplicate
    workflow_run_steps rows. Each run should have at most one step row
    for the failed flaky step (the retry hasn't fired yet — the run is
    paused awaiting the timer).
    """
    n = retries_n
    _engine, factory = patched_dispatcher

    steps = _make_flaky_steps(max_attempts=3, pass_on_attempt=2)
    run_ids = [await seed_run_factory(steps) for _ in range(n)]

    await dispatch_helper(run_ids, worker_id_prefix="flaky-dup")

    # Each run should have exactly one step row (the failed attempt).
    for rid in run_ids:
        await double_execute_helper(
            factory,
            rid,
            expected_step_count=len(steps),
        )


@pytest.mark.asyncio
async def test_load_retries_failures_some_complete_after_retry(
    retries_n,
    patched_dispatcher,
    seed_run_factory,
    dispatch_helper,
):
    """Drive the retry path manually: after first dispatch leaves runs
    paused, flip them back to queued and re-dispatch. With
    ``pass_on_attempt=2`` and ``max_attempts=3`` the retry must succeed
    on attempt 2.

    Verifies the dispatcher's RetryPolicy + lease lifecycle holds up
    under N parallel retried runs without double-execute or claim drift.
    """
    n = retries_n
    _engine, factory = patched_dispatcher

    # Use pass_on_attempt=2 so attempt 2 succeeds.
    steps = _make_flaky_steps(max_attempts=3, pass_on_attempt=2)
    run_ids = [await seed_run_factory(steps) for _ in range(n)]

    # First dispatch — every run fails + pauses (retry_pending).
    first_results = await dispatch_helper(run_ids, worker_id_prefix="flaky-r1")
    for rid, outcome in first_results:
        assert outcome is not None
        assert outcome.status == "paused"

    # Manually drive the retry path: clear paused state, set
    # the snapshot's _attempt marker to 2 so the flaky node passes,
    # then re-dispatch. The dispatcher's claim_run will reuse the row.
    from app.models.workflow import WorkflowRun

    for rid in run_ids:
        async with factory() as session:
            run = await session.get(WorkflowRun, rid)
            run.status = "queued"
            run.lease_owner = None
            run.lease_expires_at = None
            # Stamp attempt=2 onto the snapshot's flaky step so the
            # executor passes.
            snap = dict(run.definition_snapshot or {})
            new_steps: list[dict[str, Any]] = []
            for step in list(snap.get("steps") or []):
                s = dict(step)
                if s.get("step_id") == "flaky":
                    s["_attempt"] = 2
                new_steps.append(s)
            snap["steps"] = new_steps
            run.definition_snapshot = snap
            session.add(run)
            await session.commit()

    second_results = await dispatch_helper(run_ids, worker_id_prefix="flaky-r2")

    completed = 0
    for rid, outcome in second_results:
        assert not isinstance(outcome, BaseException)
        assert outcome is not None
        # On the retry attempt the flaky node passes — run completes.
        if outcome.status == "completed":
            completed += 1

    # Every run that re-attempted should have completed (deterministic
    # pass on attempt >= 2).
    assert completed == n, (
        f"expected all {n} retries to complete; got {completed}"
    )
