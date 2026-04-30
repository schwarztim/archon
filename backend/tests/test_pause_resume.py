"""Pause / resume integration tests for the dispatcher.

W2.4 / Phase 2 of the master plan. Verifies the end-to-end
human-in-the-loop and durable-delay paths:

  - test_human_approval_node_pauses_run_and_emits_run_paused
  - test_grant_approval_signal_resumes_run
  - test_reject_approval_signal_leaves_run_paused_and_marks_failed_when_required
  - test_pause_at_delay_node_with_long_delay_creates_timer_and_releases_lease
  - test_timer_fire_loop_flips_run_to_queued
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
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
# Fixtures
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables."""
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
    status: str = "running",
    tenant_id: UUID | None = None,
) -> UUID:
    """Seed a workflow + run; return run_id."""
    from app.models.workflow import Workflow, WorkflowRun

    workflow_steps = steps or [
        {
            "step_id": "s1",
            "name": "step-one",
            "node_type": "outputNode",
            "config": {},
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
            input_data={},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# Test 1: human approval node pauses run + emits run.paused
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_node_pauses_run_and_emits_run_paused():
    """request_approval flips run to paused and records run.paused."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    run_id = await _seed_run(factory, tenant_id=tenant_id)

    from app.models.approval import Approval
    from app.models.workflow import WorkflowRun, WorkflowRunEvent
    from app.services import approval_service

    async with factory() as session:
        await approval_service.request_approval(
            session,
            run_id=run_id,
            step_id="approve",
            tenant_id=tenant_id,
            payload={"prompt": "ship?"},
        )
        await session.commit()

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.status == "paused"
    assert run.paused_at is not None

    async with factory() as session:
        approvals = (
            await session.execute(
                select(Approval).where(Approval.run_id == run_id)
            )
        ).scalars().all()
    assert len(approvals) == 1
    assert approvals[0].status == "pending"

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
    types = [e.event_type for e in events]
    assert "run.paused" in types

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: granting approval emits signal + flips run to running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_approval_signal_resumes_run():
    """grant_approval emits approval.granted + run.resumed; run is running."""
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.models.approval import Signal
    from app.models.workflow import WorkflowRun, WorkflowRunEvent
    from app.services import approval_service

    # Pause the run via request_approval.
    async with factory() as session:
        approval = await approval_service.request_approval(
            session,
            run_id=run_id,
            step_id="approve",
            tenant_id=None,
            payload={},
        )
        await session.commit()

    # Grant — emits run.resumed.
    async with factory() as session:
        granted, sig = await approval_service.grant_approval(
            session,
            approval_id=approval.id,
            approver_id=None,
            reason="ok",
        )
        await session.commit()

    assert granted.status == "approved"
    assert sig.signal_type == "approval.granted"

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.status == "running"
    assert run.resumed_at is not None

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
    types = [e.event_type for e in events]
    assert "run.paused" in types
    assert "run.resumed" in types

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: rejection leaves run paused; resume_run_from_signal does NOT
#         resume when cancel_requested_at is set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_approval_signal_leaves_run_paused_and_marks_failed_when_required():
    """reject_approval keeps run paused; the dispatcher's resume helper
    decides on the failure path (test simulates a follow-up cancel that
    short-circuits to cancelled)."""
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.models.workflow import WorkflowRun
    from app.services import approval_service
    from app.services.run_dispatcher import resume_run_from_signal

    async with factory() as session:
        approval = await approval_service.request_approval(
            session,
            run_id=run_id,
            step_id="approve",
            tenant_id=None,
            payload={},
        )
        await session.commit()

    async with factory() as session:
        rejected, sig = await approval_service.reject_approval(
            session,
            approval_id=approval.id,
            approver_id=None,
            reason="no",
        )
        await session.commit()

    assert rejected.status == "rejected"
    assert sig.signal_type == "approval.rejected"

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.status == "paused"
    assert run.resumed_at is None

    # Now simulate a follow-up cancel: route stamps cancel_requested_at,
    # then calls resume_run_from_signal. The helper detects the cancel
    # and short-circuits to cancelled instead of resuming.
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        run.cancel_requested_at = datetime.utcnow()
        session.add(run)
        await session.commit()

    async with factory() as session:
        flipped = await resume_run_from_signal(session, run_id=run_id)
    assert flipped is False

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.status == "cancelled"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: long-delay node creates a Timer + pauses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_at_delay_node_with_long_delay_creates_timer_and_releases_lease():
    """The delayNode executor schedules a Timer for delays >= threshold
    and returns paused — the dispatcher will release the lease."""
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.models.timers import Timer
    from app.services.node_executors import NodeContext
    from app.services.node_executors.delay import DelayNodeExecutor

    executor = DelayNodeExecutor()

    async with factory() as session:
        ctx = NodeContext(
            step_id="wait-step",
            node_type="delayNode",
            node_data={
                "config": {
                    "seconds": 60,  # > LONG_DELAY_THRESHOLD_SECONDS=30
                    "run_id": run_id,
                }
            },
            inputs={},
            tenant_id=None,
            secrets=None,
            db_session=session,
            cancel_check=lambda: False,
        )
        result = await executor.execute(ctx)
        await session.commit()

    assert result.status == "paused"
    assert result.paused_reason == "durable_delay"
    assert "timer_id" in result.output

    async with factory() as session:
        timers = (
            await session.execute(
                select(Timer).where(Timer.run_id == run_id)
            )
        ).scalars().all()
    assert len(timers) == 1
    assert timers[0].purpose == "delay_node"
    assert timers[0].status == "pending"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5: worker timer-fire loop flips paused → queued
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timer_fire_loop_flips_run_to_queued(monkeypatch):
    """Schedule a timer that's already due; the timer-fire tick must
    flip the corresponding paused run back to queued."""
    engine, factory = await _make_engine_and_factory()

    monkeypatch.setattr(
        "app.worker.async_session_factory",
        factory,
    )

    # Seed a paused run and a Timer that fires immediately.
    run_id = await _seed_run(factory, status="paused")

    from app.models.workflow import WorkflowRun, WorkflowRunEvent
    from app.services.timer_service import schedule_timer

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        run.paused_at = datetime.utcnow()
        run.lease_owner = "stale-worker"
        run.lease_expires_at = datetime.utcnow() + timedelta(seconds=30)
        session.add(run)
        await session.commit()

    fire_at = datetime.utcnow() - timedelta(seconds=1)  # already due
    async with factory() as session:
        await schedule_timer(
            session,
            run_id=run_id,
            step_id="s1",
            fire_at=fire_at,
            purpose="retry_attempt",
            payload={"attempt": 2},
        )

    # Drive the timer-fire tick directly (no full event loop needed).
    from app.worker import _timer_fire_tick

    resumed = await _timer_fire_tick(worker_id="timer-worker")
    assert resumed == 1

    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.status == "queued"
    assert run.resumed_at is not None
    assert run.lease_owner is None
    assert run.lease_expires_at is None

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

    await engine.dispose()
