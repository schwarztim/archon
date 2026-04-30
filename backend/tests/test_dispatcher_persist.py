"""Persistence + event-chain tests for dispatch_run.

These tests focus on the post-claim persistence layer:
  - workflow_run_steps row inserts (one per step in result["steps"])
  - workflow_run_events hash chain integrity (claim/started/step.*/completed)
  - cost + token_usage propagation to step rows + run.metrics aggregate
  - failure path produces error_code + run.failed event
  - cancellation path skips engine work and emits run.cancelled
  - legacy Execution.id (missing from workflow_runs) returns None

All tests use an in-memory SQLite engine so no external services are
required.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables created."""
    from app.models import (  # noqa: F401
        Agent,
        Execution,
        User,
    )
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _seed_run(
    factory,
    *,
    steps: list[dict] | None = None,
    status: str = "queued",
    cancel_requested_at=None,
):
    """Seed workflow + run, return run_id."""
    from app.models.workflow import Workflow, WorkflowRun

    workflow_steps = steps or [
        {
            "step_id": "s1",
            "name": "step-one",
            "node_type": "outputNode",
            "config": {"value": "ok"},
            "depends_on": [],
        },
        {
            "step_id": "s2",
            "name": "step-two",
            "node_type": "outputNode",
            "config": {"value": "ok2"},
            "depends_on": ["s1"],
        },
    ]

    async with factory() as session:
        wf = Workflow(name="t-wf", steps=workflow_steps, graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            kind="workflow",
            status=status,
            definition_snapshot={
                "kind": "workflow",
                "id": str(wf.id),
                "name": wf.name,
                "steps": workflow_steps,
                "graph_definition": {},
            },
            cancel_requested_at=cancel_requested_at,
            input_data={},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


def _make_engine_result(
    *,
    status: str = "completed",
    duration_ms: int = 10,
    steps: list[dict] | None = None,
):
    """Build a deterministic execute_workflow_dag result."""
    if steps is None:
        steps = [
            {
                "step_id": "s1",
                "name": "step-one",
                "status": "completed",
                "started_at": "2026-04-29T17:00:00+00:00",
                "completed_at": "2026-04-29T17:00:01+00:00",
                "duration_ms": 1000,
                "input_data": {},
                "output_data": {"value": "ok"},
                "error": None,
                "token_usage": {"prompt": 10, "completion": 5},
                "cost_usd": 0.001,
            },
            {
                "step_id": "s2",
                "name": "step-two",
                "status": "completed",
                "started_at": "2026-04-29T17:00:01+00:00",
                "completed_at": "2026-04-29T17:00:02+00:00",
                "duration_ms": 1000,
                "input_data": {"prior": True},
                "output_data": {"value": "ok2"},
                "error": None,
                "token_usage": {"prompt": 8, "completion": 4},
                "cost_usd": 0.0008,
            },
        ]
    return {
        "status": status,
        "duration_ms": duration_ms,
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Test 1: step rows are persisted for every executed step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_persists_step_rows(monkeypatch):
    """Every step in result["steps"] must produce a workflow_run_steps row."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    async def _fake_engine(workflow, **kwargs):
        return _make_engine_result()

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    run_id = await _seed_run(factory, status="queued")

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="persistence-worker")
    assert result is not None
    assert result.status == "completed"

    from app.models.workflow import WorkflowRunStep

    async with factory() as session:
        rows = (
            await session.execute(
                select(WorkflowRunStep)
                .where(WorkflowRunStep.run_id == run_id)
                .order_by(WorkflowRunStep.step_id)
            )
        ).scalars().all()

    assert len(rows) == 2
    assert {r.step_id for r in rows} == {"s1", "s2"}
    for row in rows:
        assert row.status == "completed"
        assert row.worker_id == "persistence-worker"
        assert row.attempt == 1

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: event chain is hash-linked and contains the canonical sequence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_emits_event_history(monkeypatch):
    """Verify the run/step events chain together with monotonic sequence
    and prev_hash → current_hash links."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    async def _fake_engine(workflow, **kwargs):
        return _make_engine_result()

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    run_id = await _seed_run(factory, status="queued")

    from app.services.run_dispatcher import dispatch_run

    await dispatch_run(run_id, worker_id="chain-worker")

    from app.models.workflow import WorkflowRunEvent
    from app.services.event_service import verify_hash_chain

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()

    # Canonical event sequence:
    # 0 run.claimed → 1 run.started → 2 step.completed (s1) →
    # 3 step.completed (s2) → 4 run.completed
    types = [e.event_type for e in events]
    assert types == [
        "run.claimed",
        "run.started",
        "step.completed",
        "step.completed",
        "run.completed",
    ]

    # Sequence is monotonic from 0.
    assert [e.sequence for e in events] == [0, 1, 2, 3, 4]

    # Hash chain links: event[i].prev_hash == event[i-1].current_hash
    for i, ev in enumerate(events):
        if i == 0:
            assert ev.prev_hash is None
        else:
            assert ev.prev_hash == events[i - 1].current_hash
        # Hash is 64 hex chars (sha256).
        assert isinstance(ev.current_hash, str)
        assert len(ev.current_hash) == 64

    # Verify the chain via the event_service helper using a sync session.
    # The verify_hash_chain helper expects a sync sqlmodel Session — we
    # synthesise one against the same SQLite database for the check.
    from sqlalchemy import create_engine as create_sync_engine
    from sqlmodel import Session as SyncSession

    # Reuse the same in-memory DB by extracting the file path / use the
    # engine.url. In-memory SQLite DBs aren't shared across engines, so
    # we instead manually re-run the chain integrity check using the
    # async-loaded events and the documented compute_hash function.
    from app.services.event_service import compute_hash, build_envelope

    expected_prev: str | None = None
    for ev in events:
        envelope = build_envelope(
            run_id=ev.run_id,
            sequence=ev.sequence,
            event_type=ev.event_type,
            payload=ev.payload,
            step_id=ev.step_id,
            tenant_id=ev.tenant_id,
            correlation_id=ev.correlation_id,
            span_id=ev.span_id,
        )
        recomputed = compute_hash(expected_prev, envelope)
        assert recomputed == ev.current_hash, (
            f"hash mismatch at sequence {ev.sequence}"
        )
        expected_prev = ev.current_hash

    # Print 5+ events for the sample-output requirement.
    print("\n=== Event chain ===")
    for ev in events:
        print(
            f"seq={ev.sequence} "
            f"type={ev.event_type:<20} "
            f"prev={(ev.prev_hash or 'None')[:12]} "
            f"cur={ev.current_hash[:12]}"
        )

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: token_usage and cost_usd recorded per step + run-level metrics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_records_token_usage_and_cost_when_step_returns_them(
    monkeypatch,
):
    """When the engine reports token_usage / cost_usd, the step row + the
    run.metrics aggregate both reflect them."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    async def _fake_engine(workflow, **kwargs):
        return _make_engine_result()  # already includes tokens + cost

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    run_id = await _seed_run(factory, status="queued")

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="cost-worker")
    assert result is not None

    from app.models.workflow import WorkflowRun, WorkflowRunStep

    async with factory() as session:
        rows = (
            await session.execute(
                select(WorkflowRunStep)
                .where(WorkflowRunStep.run_id == run_id)
                .order_by(WorkflowRunStep.step_id)
            )
        ).scalars().all()
        run = await session.get(WorkflowRun, run_id)

    assert rows[0].token_usage == {"prompt": 10, "completion": 5}
    assert rows[0].cost_usd == pytest.approx(0.001)
    assert rows[1].token_usage == {"prompt": 8, "completion": 4}
    assert rows[1].cost_usd == pytest.approx(0.0008)

    assert run is not None
    assert run.metrics is not None
    assert run.metrics["step_count"] == 2
    assert run.metrics["cost_usd"] == pytest.approx(0.0018)
    assert run.metrics["token_usage"] == {"prompt": 18, "completion": 9}

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: failed engine result → run.failed event + error_code populated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_marks_failed_run_with_error_code_and_run_failed_event(
    monkeypatch,
):
    """When the engine returns status='failed', the run row is finalised
    failed and a run.failed event is emitted."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    failure_steps = [
        {
            "step_id": "s1",
            "name": "step-one",
            "status": "failed",
            "started_at": None,
            "completed_at": None,
            "duration_ms": 5,
            "input_data": {},
            "output_data": None,
            "error": "boom from engine",
            "error_code": "RuntimeError",
            "token_usage": {},
            "cost_usd": None,
        }
    ]

    async def _fake_engine(workflow, **kwargs):
        return _make_engine_result(status="failed", steps=failure_steps)

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    run_id = await _seed_run(factory, status="queued")

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="fail-worker")
    assert result is not None
    assert result.status == "failed"

    from app.models.workflow import WorkflowRunEvent, WorkflowRunStep

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
        steps = (
            await session.execute(
                select(WorkflowRunStep).where(
                    WorkflowRunStep.run_id == run_id
                )
            )
        ).scalars().all()

    types = [e.event_type for e in events]
    assert "run.failed" in types
    # The run-level failure is the terminal event.
    assert types[-1] == "run.failed"

    # Step rows mirror the failure.
    assert len(steps) == 1
    assert steps[0].status == "failed"
    assert steps[0].error_code == "RuntimeError"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5: cancel_requested_at set before claim short-circuits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_handles_cancel_requested_before_start(monkeypatch):
    """When cancel_requested_at is set before the dispatcher claims the run,
    the run is finalised as cancelled with no step rows and the engine is
    not invoked."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    engine_called = {"count": 0}

    async def _engine_should_not_run(*a, **kw):
        engine_called["count"] += 1
        return _make_engine_result()

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _engine_should_not_run,
    )

    run_id = await _seed_run(
        factory,
        status="queued",
        cancel_requested_at=datetime.utcnow(),
    )

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="cancel-worker")
    assert result is not None
    assert result.status == "cancelled"
    assert result.completed_at is not None

    # Engine never invoked.
    assert engine_called["count"] == 0

    from app.models.workflow import WorkflowRunEvent, WorkflowRunStep

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
        steps = (
            await session.execute(
                select(WorkflowRunStep).where(
                    WorkflowRunStep.run_id == run_id
                )
            )
        ).scalars().all()

    assert [e.event_type for e in events] == ["run.cancelled"]
    assert steps == []

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 6: legacy Execution.id (not in workflow_runs) returns None + log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_returns_none_for_legacy_execution_id(
    monkeypatch,
    caplog,
):
    """Closes Conflict 9: a UUID that resolves only to executions (not
    workflow_runs) must be refused with a clear log line."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    legacy_id = uuid4()  # never inserted into workflow_runs

    from app.services.run_dispatcher import dispatch_run

    caplog.set_level(logging.ERROR, logger="app.services.run_dispatcher")
    result = await dispatch_run(legacy_id)

    assert result is None
    matched = [
        rec for rec in caplog.records
        if "not in workflow_runs" in rec.getMessage()
        and "legacy Execution.id" in rec.getMessage()
    ]
    assert matched, (
        "Expected an explicit ERROR log line citing legacy Execution.id; "
        "the legacy silent-no-op behaviour was removed in W1.3."
    )

    await engine.dispose()
