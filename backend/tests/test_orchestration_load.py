"""End-to-end orchestration + scaling load tests (Phase 6).

Combines the multi-worker drain semantics with full dispatcher
execution (event chain + step persistence). These tests are heavier
than ``test_worker_scaling.py`` because they exercise:

  - ``run_dispatcher.dispatch_run`` (real claim_run + event chain)
  - ``run_lifecycle.claim_run`` CAS
  - ``WorkflowRunStep`` row creation
  - ``WorkflowRunEvent`` hash-chained events

The engine itself is stubbed deterministically (per the existing
dispatcher test suite pattern) so we don't pull node executors into the
test path.

Acceptance:
  1. 50 runs, 3 workers, all complete within a generous timeout.
  2. Every run has the canonical event sequence:
     run.claimed → run.started → step.completed → run.completed
  3. Every workflow_run_steps row has a matching workflow_runs row.
  4. lease_count metric is observed per-worker (currently a placeholder
     check — see the test docstring for what we observe and why).
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import Counter, defaultdict
from datetime import datetime
from uuid import UUID

os.environ.setdefault("LLM_STUB_MODE", "true")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401
from app.models.workflow import (
    Workflow,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStep,
)

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def engine_factory():
    """Build the engine + factory pair, with FK enforcement.

    StaticPool ensures every connection checkout returns the same
    in-memory database — required for parallel dispatch tasks that
    each pull their own session.
    """
    eng = create_async_engine(
        SQLITE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    try:
        yield eng, factory
    finally:
        await eng.dispose()


# ── Helpers ────────────────────────────────────────────────────────────


def _engine_result_template(step_id: str = "s1") -> dict:
    """Deterministic engine output: one completed step per run."""
    now = datetime.utcnow().isoformat()
    return {
        "status": "completed",
        "duration_ms": 5,
        "steps": [
            {
                "step_id": step_id,
                "name": "load-step",
                "status": "completed",
                "started_at": now,
                "completed_at": now,
                "duration_ms": 5,
                "input_data": {},
                "output_data": {"value": "ok"},
                "error": None,
                "token_usage": {"prompt": 1, "completion": 1},
                "cost_usd": 0.0,
            }
        ],
    }


async def _seed_workflow(factory) -> UUID:
    async with factory() as session:
        wf = Workflow(name="load-wf", steps=[], graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


async def _seed_runs(factory, workflow_id: UUID, count: int) -> list[UUID]:
    """Insert ``count`` queued runs and return their IDs."""
    snapshot_steps = [
        {
            "step_id": "s1",
            "name": "load-step",
            "node_type": "outputNode",
            "config": {"value": "ok"},
            "depends_on": [],
        }
    ]
    ids: list[UUID] = []
    async with factory() as session:
        for _ in range(count):
            run = WorkflowRun(
                workflow_id=workflow_id,
                kind="workflow",
                status="queued",
                definition_snapshot={
                    "kind": "workflow",
                    "id": str(workflow_id),
                    "name": "load-wf",
                    "steps": snapshot_steps,
                    "graph_definition": {},
                },
                input_data={},
            )
            session.add(run)
            ids.append(run.id)
        await session.commit()
    return ids


async def _drain_with_workers(
    worker_ids: list[str],
    factory,
    *,
    max_iterations: int = 60,
    poll_interval: float = 0.0,
) -> dict[str, int]:
    """Run every worker's drain loop until the queue empties.

    Returns a per-worker dispatch counter so tests can assert balance
    properties.
    """
    import app.worker as worker_mod
    from app.services import run_dispatcher

    # Patch both modules' session factories at the same time.
    real_worker_factory = worker_mod.async_session_factory
    real_dispatcher_factory = run_dispatcher.async_session_factory

    worker_mod.async_session_factory = factory
    run_dispatcher.async_session_factory = factory

    by_worker: Counter = Counter()
    real_dispatch = run_dispatcher.dispatch_run

    async def _instrumented_dispatch(run_id, *, worker_id):
        result = await real_dispatch(run_id, worker_id=worker_id)
        # Only count real claims (a "lost" claim returns None).
        if result is not None and result.lease_owner == worker_id:
            by_worker[worker_id] += 1
        return result

    # Replace the worker's dispatch shim so it routes through the real
    # dispatcher (with claim_run + event chain) without losing the
    # per-worker counter.
    async def _call(rid, *, worker_id):
        await _instrumented_dispatch(rid, worker_id=worker_id)

    real_call_dispatch = worker_mod._call_dispatch_run
    worker_mod._call_dispatch_run = _call

    try:
        for _ in range(max_iterations):
            await asyncio.gather(
                *[
                    worker_mod._drain_loop(wid, asyncio.Semaphore(50), asyncio.Event())
                    for wid in worker_ids
                ]
            )
            if worker_mod._inflight:
                await asyncio.gather(
                    *list(worker_mod._inflight), return_exceptions=True
                )
            if poll_interval > 0:
                await asyncio.sleep(poll_interval)

            async with factory() as session:
                stmt = select(WorkflowRun).where(
                    WorkflowRun.status.in_(["queued", "pending"])
                )
                result = await session.exec(stmt)
                if not list(result.all()):
                    return dict(by_worker)
    finally:
        worker_mod._call_dispatch_run = real_call_dispatch
        worker_mod.async_session_factory = real_worker_factory
        run_dispatcher.async_session_factory = real_dispatcher_factory

    return dict(by_worker)


# ── Test 1: 50 concurrent runs with 3 workers complete within timeout ─


@pytest.mark.asyncio
async def test_50_concurrent_runs_with_3_workers_complete_within_timeout(
    engine_factory, monkeypatch
) -> None:
    """50 runs drained by 3 workers — all reach status='completed' within
    a generous 30s budget. Real dispatcher path with stubbed engine.
    """
    eng, factory = engine_factory

    async def _fake_engine(workflow, **kwargs):
        return _engine_result_template()

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag", _fake_engine
    )

    wf_id = await _seed_workflow(factory)
    run_ids = await _seed_runs(factory, wf_id, 50)

    start = time.perf_counter()
    dispatch_counts = await _drain_with_workers(
        ["worker-A", "worker-B", "worker-C"], factory, max_iterations=30
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 30, f"drain took {elapsed:.1f}s — exceeded 30s budget"

    # Every run completed exactly once.
    async with factory() as session:
        stmt = select(WorkflowRun)
        result = await session.exec(stmt)
        runs = list(result.all())

    assert len(runs) == 50
    statuses = Counter(r.status for r in runs)
    assert statuses["completed"] == 50, (
        f"expected 50 completed, got {statuses}"
    )

    # Every run was claimed once (owner exactly one of the 3 workers).
    owners = {r.lease_owner for r in runs}
    assert owners <= {"worker-A", "worker-B", "worker-C"}
    assert all(r.lease_owner is not None for r in runs)

    # Sum of dispatch counts == 50 (no double-counting).
    total = sum(dispatch_counts.values())
    assert total == 50, f"dispatch count sum {total} != 50 runs"


# ── Test 2: every run has a complete event history ────────────────────


@pytest.mark.asyncio
async def test_event_history_complete_for_every_run_under_load(
    engine_factory, monkeypatch
) -> None:
    """Every run produces the canonical event sequence under load.

    Note on ``run.queued`` / ``run.created``: the dispatcher does NOT
    emit these — they are emitted by REST handlers / route adapters.
    Our seed path inserts directly so we assert only the events the
    dispatcher is responsible for: run.claimed → run.started →
    step.completed → run.completed.
    """
    eng, factory = engine_factory

    async def _fake_engine(workflow, **kwargs):
        return _engine_result_template()

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag", _fake_engine
    )

    wf_id = await _seed_workflow(factory)
    run_ids = await _seed_runs(factory, wf_id, 25)

    await _drain_with_workers(
        ["worker-1", "worker-2", "worker-3"], factory, max_iterations=20
    )

    # Sanity: all completed.
    async with factory() as session:
        stmt = select(WorkflowRun)
        result = await session.exec(stmt)
        runs = list(result.all())
    assert all(r.status == "completed" for r in runs)

    # For each run, fetch its events and assert the canonical sequence.
    expected_types = [
        "run.claimed",
        "run.started",
        "step.completed",
        "run.completed",
    ]
    async with factory() as session:
        for run_id in run_ids:
            stmt = (
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
            result = await session.exec(stmt)
            events = list(result.all())

            types = [e.event_type for e in events]
            assert types == expected_types, (
                f"run {run_id}: events {types} != expected {expected_types}"
            )

            # Hash chain: every event after the first has prev_hash equal
            # to the prior event's current_hash.
            for i, ev in enumerate(events):
                if i == 0:
                    assert ev.prev_hash is None
                else:
                    assert ev.prev_hash == events[i - 1].current_hash, (
                        f"run {run_id} sequence {ev.sequence}: chain broken"
                    )


# ── Test 3: no orphan workflow_run_steps ──────────────────────────────


@pytest.mark.asyncio
async def test_no_orphan_workflow_run_steps(
    engine_factory, monkeypatch
) -> None:
    """Every workflow_run_steps row has a corresponding workflow_runs row."""
    eng, factory = engine_factory

    async def _fake_engine(workflow, **kwargs):
        return _engine_result_template()

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag", _fake_engine
    )

    wf_id = await _seed_workflow(factory)
    await _seed_runs(factory, wf_id, 30)

    await _drain_with_workers(
        ["worker-x", "worker-y"], factory, max_iterations=20
    )

    async with factory() as session:
        stmt_steps = select(WorkflowRunStep)
        result_steps = await session.exec(stmt_steps)
        steps = list(result_steps.all())

        stmt_runs = select(WorkflowRun.id)
        result_runs = await session.exec(stmt_runs)
        run_ids = {row for row in result_runs.all()}

    # Each step's run_id must reference an existing run.
    orphans = [s for s in steps if s.run_id not in run_ids]
    assert not orphans, (
        f"orphan workflow_run_steps rows (no parent run): "
        f"{[(str(s.id), str(s.run_id)) for s in orphans]}"
    )

    # And we should have one step per run (engine emits one step).
    assert len(steps) == 30, f"expected 30 step rows, got {len(steps)}"


# ── Test 4: lease metric observed per-worker ──────────────────────────


@pytest.mark.asyncio
async def test_lease_metric_observed_per_worker(
    engine_factory, monkeypatch
) -> None:
    """Per-worker dispatch counts are observable for ops dashboards.

    The ``WorkerHeartbeat.lease_count`` column exists in the model but
    isn't yet incremented by the dispatcher (Phase 6 — pending wiring).
    Until that lands, the canonical "lease metric" is the per-worker
    dispatch count derived from ``WorkflowRun.lease_owner`` after
    drain — that's what an ops dashboard would aggregate over.

    To exercise multiple workers, we use small batch size + round-robin
    drain rounds so each worker gets a chance at the queue.
    """
    import app.worker as worker_mod

    eng, factory = engine_factory

    async def _fake_engine(workflow, **kwargs):
        return _engine_result_template()

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag", _fake_engine
    )
    monkeypatch.setattr(worker_mod, "_RUN_BATCH_SIZE", 3)

    wf_id = await _seed_workflow(factory)
    await _seed_runs(factory, wf_id, 20)

    # Drain in round-robin to spread work across workers.
    workers = ["lm-w1", "lm-w2", "lm-w3"]
    from app.services import run_dispatcher

    real_worker_factory = worker_mod.async_session_factory
    real_dispatcher_factory = run_dispatcher.async_session_factory
    worker_mod.async_session_factory = factory
    run_dispatcher.async_session_factory = factory

    try:
        for round_num in range(30):
            wid = workers[round_num % len(workers)]
            await worker_mod._drain_loop(
                wid, asyncio.Semaphore(50), asyncio.Event()
            )
            if worker_mod._inflight:
                await asyncio.gather(
                    *list(worker_mod._inflight), return_exceptions=True
                )
            async with factory() as session:
                stmt = select(WorkflowRun).where(
                    WorkflowRun.status.in_(["queued", "pending"])
                )
                result = await session.exec(stmt)
                if not list(result.all()):
                    break
    finally:
        worker_mod.async_session_factory = real_worker_factory
        run_dispatcher.async_session_factory = real_dispatcher_factory

    # Cross-check via the DB-observable lease_owner.
    async with factory() as session:
        stmt = select(WorkflowRun.lease_owner)
        result = await session.exec(stmt)
        observed_owners = list(result.all())

    db_counter = Counter(observed_owners)
    print("\n=== Per-worker lease metric (observed) ===")
    for worker_id, count in sorted(db_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {worker_id}: {count}")

    # All 20 runs claimed once.
    assert sum(db_counter.values()) == 20
    # Owners are within the registered worker set.
    assert set(db_counter.keys()) <= {"lm-w1", "lm-w2", "lm-w3"}
    # At least 2 workers contributed (no full monopoly with 20 rows
    # queued and 3 workers spinning round-robin).
    assert len([w for w in db_counter if db_counter[w] > 0]) >= 2, (
        f"only one worker contributed — {db_counter}"
    )
