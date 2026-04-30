"""Integration tests for the dispatcher's retry / signal / cancel / pause wiring.

W2.4 — Phase 2 of the master plan. Verifies the cross-cutting integration
points between ``run_dispatcher``, ``retry_policy``, ``signal_service``,
``timer_service``, and the engine's per-step result shape.

Covers:
  - test_step_failure_with_retry_policy_schedules_retry_timer
  - test_step_failure_exceeding_max_attempts_marks_failed
  - test_step_failure_non_retryable_class_marks_failed_immediately
  - test_run_resumes_from_paused_to_completed_after_signal_consumed
  - test_dispatcher_persists_token_usage_and_cost_aggregation

All tests run against an in-memory SQLite engine — no external services.
"""

from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all run + signal + timer tables."""
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.approval import Approval, Signal  # noqa: F401
    from app.models.timers import Timer  # noqa: F401
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
    tenant_id: UUID | None = None,
) -> UUID:
    """Seed workflow + run, return run_id."""
    from app.models.workflow import Workflow, WorkflowRun

    workflow_steps = steps or [
        {
            "step_id": "s1",
            "name": "step-one",
            "node_type": "outputNode",
            "config": {
                "value": "ok",
                "retry": {
                    "max_attempts": 3,
                    "initial_backoff_seconds": 1.0,
                    "backoff_multiplier": 2.0,
                    "max_backoff_seconds": 10.0,
                    "retry_on": ["TransientError", "TimeoutError"],
                    "no_retry_on": ["ValidationError"],
                },
            },
            "depends_on": [],
        }
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
            tenant_id=tenant_id,
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


def _failed_step_payload(
    *,
    step_id: str = "s1",
    error: str = "TransientError: kaboom",
    error_code: str = "TransientError",
    duration_ms: int = 5,
) -> dict:
    return {
        "step_id": step_id,
        "name": step_id,
        "status": "failed",
        "started_at": None,
        "completed_at": None,
        "duration_ms": duration_ms,
        "input_data": {},
        "output_data": None,
        "error": error,
        "error_code": error_code,
        "token_usage": {},
        "cost_usd": None,
    }


# ---------------------------------------------------------------------------
# Test 1: retryable failure schedules a Timer + step.retry event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_failure_with_retry_policy_schedules_retry_timer(monkeypatch):
    """A failed step under a retry policy schedules a Timer and pauses the run."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "failed",
            "duration_ms": 5,
            "steps": [_failed_step_payload()],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    run_id = await _seed_run(factory, status="queued")

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="retry-worker")

    # Run should be paused — a retry timer was scheduled.
    assert result is not None
    assert result.status == "paused", (
        f"expected paused (retry pending), got {result.status}"
    )
    assert result.paused_at is not None

    # A pending Timer with purpose=retry_attempt exists.
    from app.models.timers import Timer

    async with factory() as session:
        timers = (
            await session.execute(
                select(Timer).where(Timer.run_id == run_id)
            )
        ).scalars().all()
    assert len(timers) == 1
    assert timers[0].purpose == "retry_attempt"
    assert timers[0].status == "pending"
    assert timers[0].step_id == "s1"
    assert timers[0].payload.get("attempt") == 2
    assert timers[0].payload.get("delay_seconds") == 1.0

    # Event chain should contain step.failed → step.retry → run.paused.
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
    types = [e.event_type for e in events]
    assert "step.failed" in types
    assert "step.retry" in types
    assert types[-1] == "run.paused"

    # step.retry payload carries the attempt count.
    retry_event = next(e for e in events if e.event_type == "step.retry")
    assert retry_event.payload["attempt"] == 2

    # Print sample retry chain for the report.
    print("\n=== Retry chain ===")
    for e in events:
        attempt = e.payload.get("attempt") if isinstance(e.payload, dict) else None
        print(f"seq={e.sequence} {e.event_type:<20} attempt={attempt}")

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: retry exhaustion → run.failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_failure_exceeding_max_attempts_marks_failed(monkeypatch):
    """When attempt >= max_attempts, the run is finalised failed (no timer)."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "failed",
            "duration_ms": 5,
            "steps": [_failed_step_payload()],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    # Seed a run whose attempt is already at max_attempts (3) — the next
    # claim bumps to 4, exceeding the budget. (claim adds +1 each call.)
    run_id = await _seed_run(factory, status="queued")
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        run.attempt = 3
        session.add(run)
        await session.commit()

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="exhaust-worker")

    assert result is not None
    assert result.status == "failed"

    # No timer was scheduled.
    from app.models.timers import Timer

    async with factory() as session:
        timers = (
            await session.execute(
                select(Timer).where(Timer.run_id == run_id)
            )
        ).scalars().all()
    assert timers == []

    # run.failed terminal event present.
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
    types = [e.event_type for e in events]
    assert types[-1] == "run.failed"
    assert "step.retry" not in types

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: non-retryable error class skips retry, marks failed immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_failure_non_retryable_class_marks_failed_immediately(
    monkeypatch,
):
    """A ValidationError is in no_retry_on — we must fail without retry."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "failed",
            "duration_ms": 5,
            "steps": [
                _failed_step_payload(
                    error="ValidationError: bad input",
                    error_code="ValidationError",
                )
            ],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    run_id = await _seed_run(factory, status="queued")

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="validation-worker")

    assert result is not None
    assert result.status == "failed"

    from app.models.timers import Timer
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        timers = (
            await session.execute(
                select(Timer).where(Timer.run_id == run_id)
            )
        ).scalars().all()
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()

    assert timers == []  # no retry timer
    types = [e.event_type for e in events]
    assert "step.retry" not in types
    assert types[-1] == "run.failed"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: signal-driven resume flips paused → queued and run completes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_resumes_from_paused_to_completed_after_signal_consumed(
    monkeypatch,
):
    """Send a signal, call resume_run_from_signal, dispatch picks up & completes."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    # Engine returns success on the resumed dispatch.
    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "completed",
            "duration_ms": 1,
            "steps": [
                {
                    "step_id": "s1",
                    "name": "step-one",
                    "status": "completed",
                    "started_at": None,
                    "completed_at": None,
                    "duration_ms": 1,
                    "input_data": {},
                    "output_data": {"value": "ok"},
                    "error": None,
                    "token_usage": {},
                    "cost_usd": 0.0,
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    # Seed a paused run (e.g. awaiting approval).
    run_id = await _seed_run(factory, status="paused")
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        run.paused_at = datetime.utcnow()
        session.add(run)
        await session.commit()

    # Send an approval.granted signal.
    from app.services import signal_service

    async with factory() as session:
        await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id="s1",
            signal_type="approval.granted",
            payload={},
        )
        await session.commit()

    # Call the resume helper — flips paused → queued.
    from app.services.run_dispatcher import resume_run_from_signal

    async with factory() as session:
        flipped = await resume_run_from_signal(session, run_id=run_id)
    assert flipped is True

    # Dispatch the run; the drain loop's claim-from-queued path executes.
    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="resume-worker")
    assert result is not None
    assert result.status == "completed"

    # Event chain ends with run.completed; run.resumed appears earlier.
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
    types = [e.event_type for e in events]
    assert "run.resumed" in types
    assert types[-1] == "run.completed"

    # Print sample pause/resume chain for the report.
    print("\n=== Pause/Resume chain ===")
    for e in events:
        print(f"seq={e.sequence} {e.event_type}")

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5: token usage + cost aggregation across multi-step run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_persists_token_usage_and_cost_aggregation(monkeypatch):
    """Multi-step run aggregates token_usage + cost_usd into run.metrics."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "completed",
            "duration_ms": 10,
            "steps": [
                {
                    "step_id": "s1",
                    "name": "s1",
                    "status": "completed",
                    "duration_ms": 5,
                    "started_at": None,
                    "completed_at": None,
                    "input_data": {},
                    "output_data": {"v": 1},
                    "error": None,
                    "token_usage": {"prompt": 100, "completion": 50},
                    "cost_usd": 0.005,
                },
                {
                    "step_id": "s2",
                    "name": "s2",
                    "status": "completed",
                    "duration_ms": 5,
                    "started_at": None,
                    "completed_at": None,
                    "input_data": {},
                    "output_data": {"v": 2},
                    "error": None,
                    "token_usage": {"prompt": 80, "completion": 40},
                    "cost_usd": 0.004,
                },
            ],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    multi_steps = [
        {
            "step_id": "s1",
            "name": "s1",
            "node_type": "outputNode",
            "config": {},
            "depends_on": [],
        },
        {
            "step_id": "s2",
            "name": "s2",
            "node_type": "outputNode",
            "config": {},
            "depends_on": ["s1"],
        },
    ]
    run_id = await _seed_run(factory, status="queued", steps=multi_steps)

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="cost-worker")
    assert result is not None
    assert result.status == "completed"

    # run.metrics aggregates both steps.
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.metrics is not None
    assert run.metrics["step_count"] == 2
    assert run.metrics["cost_usd"] == pytest.approx(0.009)
    assert run.metrics["token_usage"] == {"prompt": 180, "completion": 90}

    await engine.dispose()
