"""Tests for the W7 Schedule Engine.

Covers:
  - Schedule model persistence (create_schedule_persists)
  - evaluate_schedule fires through ExecutionFacade (test_evaluate_fires_through_facade)
  - overlap_policy=skip prevents duplicate (test_overlap_skip_prevents_duplicate)
  - overlap_policy=cancel_running cancels active (test_overlap_cancel_running_cancels_active)
  - overlap_policy=allow_all starts regardless (test_overlap_allow_all_starts_regardless)
  - pause stops evaluation (test_pause_schedule_stops_evaluation)
  - resume with catchup (test_resume_schedule_with_catchup)
  - backfill creates expected runs (test_backfill_creates_expected_runs)
  - idempotency key prevents duplicate fires (test_idempotency_key_prevents_duplicate_fires)

Pattern: inline SQLite (--noconftest), mirrors test_task_queues.py.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all relevant tables."""
    # Import order matters — FK references must exist before create_all.
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
        WorkflowSchedule,
    )
    from app.models.task_queue import Task, TaskQueue  # noqa: F401
    from app.models.schedule import Schedule  # noqa: F401

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _seed_workflow(factory) -> UUID:
    """Insert a minimal Workflow and return its id."""
    from app.models.workflow import Workflow

    async with factory() as session:
        wf = Workflow(name="sched-wf", steps=[], graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


async def _seed_run(
    factory,
    *,
    workflow_id: UUID,
    tenant_id: UUID | None,
    status: str = "running",
) -> UUID:
    """Insert a WorkflowRun with a given status and return its id."""
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        run = WorkflowRun(
            workflow_id=workflow_id,
            kind="workflow",
            status=status,
            tenant_id=tenant_id,
            definition_snapshot={
                "kind": "workflow",
                "id": str(workflow_id),
                "steps": [],
            },
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_schedule_persists():
    """create_schedule writes a row and computes next_fire_at."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    wf_id = await _seed_workflow(factory)

    from app.services import schedule_service

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="every-minute",
            calendar_spec="* * * * *",
            spec_kind="cron",
            workflow_id=wf_id,
        )

    assert s.id is not None
    assert s.name == "every-minute"
    assert s.tenant_id == tenant
    assert s.workflow_id == wf_id
    assert s.paused is False
    # next_fire_at should be set (within the next 2 minutes from creation)
    assert s.next_fire_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_evaluate_fires_through_facade():
    """evaluate_schedule with a past-due next_fire_at creates a run via the facade."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000002")
    wf_id = await _seed_workflow(factory)

    from app.services import schedule_service

    # Set next_fire_at in the past so the schedule is immediately due.
    past = datetime(2026, 1, 1, 0, 0, 0)

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="fire-now",
            calendar_spec="* * * * *",
            spec_kind="cron",
            workflow_id=wf_id,
        )
        s.next_fire_at = past
        session.add(s)
        await session.commit()
        await session.refresh(s)
        schedule_id = s.id

    now = datetime(2026, 1, 1, 0, 5, 0)
    async with factory() as session:
        run_ids = await schedule_service.evaluate_schedule(
            session, schedule_id=schedule_id, now=now
        )

    assert len(run_ids) >= 1, "Expected at least one run to be created"

    await engine.dispose()


@pytest.mark.asyncio
async def test_overlap_skip_prevents_duplicate():
    """overlap_policy=skip: no new run if there is already an active run."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000003")
    wf_id = await _seed_workflow(factory)

    # Pre-create an active run for this workflow.
    await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant, status="running")

    from app.services import schedule_service

    past = datetime(2026, 1, 1, 0, 0, 0)

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="skip-test",
            calendar_spec="* * * * *",
            spec_kind="cron",
            workflow_id=wf_id,
            overlap_policy="skip",
        )
        s.next_fire_at = past
        session.add(s)
        await session.commit()
        schedule_id = s.id

    now = datetime(2026, 1, 1, 0, 5, 0)
    async with factory() as session:
        run_ids = await schedule_service.evaluate_schedule(
            session, schedule_id=schedule_id, now=now
        )

    assert run_ids == [], f"Expected skip to produce no runs; got {run_ids}"

    await engine.dispose()


@pytest.mark.asyncio
async def test_overlap_cancel_running_cancels_active():
    """overlap_policy=cancel_running: the active run is cancelled and a new run is created."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000004")
    wf_id = await _seed_workflow(factory)

    # Pre-create a running run.
    active_run_id = await _seed_run(
        factory, workflow_id=wf_id, tenant_id=tenant, status="running"
    )

    from app.services import schedule_service

    past = datetime(2026, 1, 1, 0, 0, 0)

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="cancel-running-test",
            calendar_spec="* * * * *",
            spec_kind="cron",
            workflow_id=wf_id,
            overlap_policy="cancel_running",
        )
        s.next_fire_at = past
        session.add(s)
        await session.commit()
        schedule_id = s.id

    now = datetime(2026, 1, 1, 0, 5, 0)
    async with factory() as session:
        run_ids = await schedule_service.evaluate_schedule(
            session, schedule_id=schedule_id, now=now
        )

    # A new run must have been created.
    assert len(run_ids) >= 1, "Expected a new run after cancel_running"

    # The previously active run should now be cancelled.
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        old_run = await session.get(WorkflowRun, active_run_id)

    assert old_run is not None
    assert old_run.status == "cancelled", (
        f"Expected old run to be cancelled; got {old_run.status}"
    )

    await engine.dispose()


@pytest.mark.asyncio
async def test_overlap_allow_all_starts_regardless():
    """overlap_policy=allow_all: new run starts even with existing active runs."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000005")
    wf_id = await _seed_workflow(factory)

    # Pre-create TWO active runs.
    await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant, status="running")
    await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant, status="running")

    from app.services import schedule_service

    past = datetime(2026, 1, 1, 0, 0, 0)

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="allow-all-test",
            calendar_spec="* * * * *",
            spec_kind="cron",
            workflow_id=wf_id,
            overlap_policy="allow_all",
        )
        s.next_fire_at = past
        session.add(s)
        await session.commit()
        schedule_id = s.id

    now = datetime(2026, 1, 1, 0, 5, 0)
    async with factory() as session:
        run_ids = await schedule_service.evaluate_schedule(
            session, schedule_id=schedule_id, now=now
        )

    assert len(run_ids) >= 1, "Expected a run despite active runs (allow_all)"

    await engine.dispose()


@pytest.mark.asyncio
async def test_pause_schedule_stops_evaluation():
    """A paused schedule returns empty from evaluate_schedule."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000006")
    wf_id = await _seed_workflow(factory)

    from app.services import schedule_service

    past = datetime(2026, 1, 1, 0, 0, 0)

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="pause-test",
            calendar_spec="* * * * *",
            spec_kind="cron",
            workflow_id=wf_id,
        )
        s.next_fire_at = past
        session.add(s)
        await session.commit()
        schedule_id = s.id

    # Pause the schedule.
    async with factory() as session:
        await schedule_service.pause_schedule(session, schedule_id=schedule_id)

    now = datetime(2026, 1, 1, 0, 5, 0)
    async with factory() as session:
        run_ids = await schedule_service.evaluate_schedule(
            session, schedule_id=schedule_id, now=now
        )

    assert run_ids == [], "Paused schedule should not fire"

    await engine.dispose()


@pytest.mark.asyncio
async def test_resume_schedule_with_catchup():
    """Resume with catchup_window_seconds > 0 fires missed intervals."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000007")
    wf_id = await _seed_workflow(factory)

    from app.services import schedule_service

    # Use interval:1m so we can precisely control fire times.
    # Set last_evaluated_at 5 minutes ago, catchup_window=600s (10 min).
    now = datetime(2026, 1, 1, 0, 10, 0)
    five_min_ago = datetime(2026, 1, 1, 0, 5, 0)

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="catchup-test",
            calendar_spec="interval:1m",
            spec_kind="interval",
            workflow_id=wf_id,
            catchup_window_seconds=600,
        )
        # Simulate paused with last_evaluated_at 5 minutes ago.
        s.paused = True
        s.last_evaluated_at = five_min_ago
        s.next_fire_at = five_min_ago
        session.add(s)
        await session.commit()
        schedule_id = s.id

    # Resume triggers catchup.
    async with factory() as session:
        # Patch _utcnow in schedule_service to control "now" during resume.
        import app.services.schedule_service as svc
        original_utcnow = svc._utcnow
        svc._utcnow = lambda: now  # type: ignore[assignment]
        try:
            resumed = await schedule_service.resume_schedule(
                session, schedule_id=schedule_id
            )
        finally:
            svc._utcnow = original_utcnow  # type: ignore[assignment]

    assert resumed.paused is False
    # Catchup should have fired at least one run.
    assert resumed.last_successful_run_id is not None or resumed.last_fire_succeeded_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_creates_expected_runs():
    """backfill_schedule creates runs for each cron slot in [start, end]."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000008")
    wf_id = await _seed_workflow(factory)

    from app.services import schedule_service

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="backfill-test",
            calendar_spec="interval:1m",
            spec_kind="interval",
            workflow_id=wf_id,
        )
        schedule_id = s.id

    # Backfill a 5-minute window — expect 5 runs (at +1m, +2m, +3m, +4m, +5m).
    start = datetime(2026, 2, 1, 12, 0, 0)
    end = datetime(2026, 2, 1, 12, 5, 0)

    async with factory() as session:
        run_ids = await schedule_service.backfill_schedule(
            session,
            schedule_id=schedule_id,
            start_time=start,
            end_time=end,
        )

    assert len(run_ids) == 5, (
        f"Expected 5 backfill runs (at :01, :02, :03, :04, :05); got {len(run_ids)}"
    )

    await engine.dispose()


@pytest.mark.asyncio
async def test_idempotency_key_prevents_duplicate_fires():
    """Evaluating the same past fire_time twice produces the same run_id both times."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000009")
    wf_id = await _seed_workflow(factory)

    from app.services import schedule_service

    past = datetime(2026, 1, 1, 0, 0, 0)

    async with factory() as session:
        s = await schedule_service.create_schedule(
            session,
            tenant_id=tenant,
            name="idem-test",
            calendar_spec="* * * * *",
            spec_kind="cron",
            workflow_id=wf_id,
            overlap_policy="allow_all",
        )
        s.next_fire_at = past
        session.add(s)
        await session.commit()
        schedule_id = s.id

    # First evaluation: fires.
    now = datetime(2026, 1, 1, 0, 1, 0)
    async with factory() as session:
        run_ids_1 = await schedule_service.evaluate_schedule(
            session, schedule_id=schedule_id, now=now
        )

    assert len(run_ids_1) >= 1, "First evaluation should fire"

    # Second evaluation: reset next_fire_at to the same past slot to force a retry.
    async with factory() as session:
        sched = await session.get(schedule_service.Schedule, schedule_id)
        sched.next_fire_at = past  # type: ignore[union-attr]
        session.add(sched)
        await session.commit()

    async with factory() as session:
        run_ids_2 = await schedule_service.evaluate_schedule(
            session, schedule_id=schedule_id, now=now
        )

    # The idempotency key should return the same run (is_new=False) or no new run.
    # In either case, no *new* distinct run UUIDs should appear.
    new_in_second = set(run_ids_2) - set(run_ids_1)
    assert len(new_in_second) == 0, (
        f"Duplicate fire created new run IDs: {new_in_second}"
    )

    await engine.dispose()
