"""Cancellation enforcement tests.

W2.4 / Phase 2 of the master plan. Verifies cancellation honoured at
the three structural points:

  1. Pre-flight (before claim/dispatch)
  2. Mid-flight / between batches (cancel_check inside the engine)
  3. Paused → cancel injection (resume_run_from_signal short-circuits to
     cancelled instead of resuming)

Tests:
  - test_cancel_before_dispatch_results_in_run_cancelled_no_steps_executed
  - test_cancel_during_run_finalizes_with_run_cancelled_event
  - test_cancel_paused_run_short_circuits_resume
"""

from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID

import pytest
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
    status: str = "queued",
    cancel_requested_at=None,
) -> UUID:
    """Seed workflow + run; return run_id."""
    from app.models.workflow import Workflow, WorkflowRun

    workflow_steps = [
        {
            "step_id": "s1",
            "name": "step-one",
            "node_type": "outputNode",
            "config": {},
            "depends_on": [],
        }
    ]

    async with factory() as session:
        wf = Workflow(name="cancel-wf", steps=workflow_steps, graph_definition={})
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


# ---------------------------------------------------------------------------
# Test 1: cancel before dispatch — no engine work, run.cancelled emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_before_dispatch_results_in_run_cancelled_no_steps_executed(
    monkeypatch,
):
    """A queued run with cancel_requested_at set is not dispatched."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    # Engine MUST NOT execute.
    engine_calls = {"count": 0}

    async def _engine(workflow, **kwargs):
        engine_calls["count"] += 1
        return {"status": "completed", "duration_ms": 0, "steps": []}

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _engine,
    )

    cancel_at = datetime.utcnow()
    run_id = await _seed_run(
        factory,
        status="queued",
        cancel_requested_at=cancel_at,
    )

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="cancel-worker")
    assert result is not None
    assert result.status == "cancelled"
    assert engine_calls["count"] == 0

    # Steps were NOT persisted.
    from app.models.workflow import WorkflowRunStep, WorkflowRunEvent

    async with factory() as session:
        steps = (
            await session.execute(
                select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)
            )
        ).scalars().all()
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()

    assert steps == []
    types = [e.event_type for e in events]
    assert types[-1] == "run.cancelled"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: cancel mid-run finalises as run.cancelled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_during_run_finalizes_with_run_cancelled_event(monkeypatch):
    """An engine that returns status='cancelled' results in run.cancelled."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    # Simulate engine seeing the cancel mid-run: returns status=cancelled
    # along with a partial step record.
    async def _engine(workflow, **kwargs):
        return {
            "status": "cancelled",
            "duration_ms": 5,
            "steps": [
                {
                    "step_id": "s1",
                    "name": "s1",
                    "status": "skipped",
                    "started_at": None,
                    "completed_at": None,
                    "duration_ms": 0,
                    "input_data": {},
                    "output_data": None,
                    "error": "cancelled",
                    "token_usage": {},
                    "cost_usd": None,
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _engine,
    )

    run_id = await _seed_run(factory, status="queued")

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="cancel-mid-worker")
    assert result is not None
    assert result.status == "cancelled"

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
    assert types[-1] == "run.cancelled"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: cancel on paused run short-circuits resume
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_paused_run_short_circuits_resume():
    """A paused run with cancel_requested_at → resume_run_from_signal
    finalises as cancelled instead of flipping to queued."""
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory, status="paused")

    from app.models.workflow import WorkflowRun, WorkflowRunEvent
    from app.services.run_dispatcher import resume_run_from_signal

    # Stamp cancel on the paused run.
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        run.cancel_requested_at = datetime.utcnow()
        run.paused_at = datetime.utcnow()
        session.add(run)
        await session.commit()

    # Now call resume_run_from_signal — should short-circuit.
    async with factory() as session:
        flipped = await resume_run_from_signal(session, run_id=run_id)
    assert flipped is False

    # Run is cancelled, not queued.
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.status == "cancelled"

    # run.cancelled emitted.
    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
    types = [e.event_type for e in events]
    assert types[-1] == "run.cancelled"

    await engine.dispose()
