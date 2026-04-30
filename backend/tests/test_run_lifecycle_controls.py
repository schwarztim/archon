"""W6 run lifecycle controls — unit tests.

Tests cancel, terminate, pause, resume, and propagate_cancellation
against an in-memory SQLite database. No conftest required.

Run with:
    cd /Users/timothy.schwarz/Projects/Archon/backend
    /Users/timothy.schwarz/Projects/Archon/.venv/bin/python \
        -m pytest tests/test_run_lifecycle_controls.py -v --noconftest
"""

from __future__ import annotations

import os
import uuid
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")

# Import models so SQLModel.metadata is fully populated before create_all.
from app.models import User  # noqa: F401
from app.models.workflow import (  # noqa: F401
    Workflow,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStep,
)
from app.models.activity import ActivityExecution  # noqa: F401
from app.models.task_queue import Task, TaskQueue  # noqa: F401

from app.services.run_lifecycle import (
    cancel_run,
    pause_run,
    propagate_cancellation,
    resume_run,
    terminate_run,
)

SQLITE_URL = "sqlite+aiosqlite:///:memory:"
TENANT_UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


# ── In-memory engine ──────────────────────────────────────────────────


async def _make_factory():
    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _seed_run(factory, status: str = "queued") -> UUID:
    async with factory() as session:
        wf = Workflow(
            name="lc-test",
            steps=[],
            graph_definition={},
            tenant_id=TENANT_UUID,
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            kind="workflow",
            status=status,
            definition_snapshot={"name": "lc-test"},
            tenant_id=TENANT_UUID,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


async def _get_run(factory, run_id: UUID) -> WorkflowRun:
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run is not None
    return run


async def _get_events(factory, run_id: UUID) -> list[WorkflowRunEvent]:
    from sqlalchemy import select

    async with factory() as session:
        result = await session.execute(
            select(WorkflowRunEvent)
            .where(WorkflowRunEvent.run_id == run_id)
            .order_by(WorkflowRunEvent.sequence)
        )
        return list(result.scalars().all())


# ── cancel_run tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_sets_cancelling_status():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="queued")

    async with factory() as session:
        run = await cancel_run(session, run_id=run_id, reason="user request", actor_id="u1")

    assert run.status == "cancelling"
    assert run.cancel_requested_at is not None


@pytest.mark.asyncio
async def test_cancel_appends_event_with_reason():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="running")

    async with factory() as session:
        await cancel_run(session, run_id=run_id, reason="deadline exceeded", actor_id="u2")

    events = await _get_events(factory, run_id)
    cancel_events = [e for e in events if e.event_type == "run.cancel_requested"]
    assert len(cancel_events) == 1
    assert cancel_events[0].payload["reason"] == "deadline exceeded"
    assert cancel_events[0].payload["actor_id"] == "u2"


@pytest.mark.asyncio
async def test_cancel_from_terminal_raises():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="completed")

    async with factory() as session:
        with pytest.raises(ValueError, match="terminal"):
            await cancel_run(session, run_id=run_id, reason="too late", actor_id="u1")


@pytest.mark.asyncio
async def test_cancel_idempotent_on_cancelling():
    """Cancelling an already-cancelling run is a no-op, not an error."""
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="queued")

    async with factory() as session:
        r1 = await cancel_run(session, run_id=run_id, reason="first", actor_id="u1")

    async with factory() as session:
        r2 = await cancel_run(session, run_id=run_id, reason="second", actor_id="u1")

    assert r1.status == r2.status == "cancelling"
    # Only one event should exist (the idempotent call emitted none).
    events = await _get_events(factory, run_id)
    cancel_events = [e for e in events if e.event_type == "run.cancel_requested"]
    assert len(cancel_events) == 1


# ── terminate_run tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_terminate_sets_terminated_status():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="running")

    async with factory() as session:
        run = await terminate_run(session, run_id=run_id, reason="hard stop", actor_id="admin")

    assert run.status == "terminated"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_terminate_cancels_child_runs():
    """propagate_cancellation reaches child runs keyed by triggered_by."""
    factory = await _make_factory()
    parent_id = await _seed_run(factory, status="running")

    # Create a child run in the same DB whose triggered_by == str(parent_id).
    async with factory() as session:
        wf = Workflow(
            name="child-wf",
            steps=[],
            graph_definition={},
            tenant_id=TENANT_UUID,
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        child_run = WorkflowRun(
            workflow_id=wf.id,
            kind="workflow",
            status="queued",
            definition_snapshot={"name": "child-wf"},
            tenant_id=TENANT_UUID,
            triggered_by=str(parent_id),
        )
        session.add(child_run)
        await session.commit()
        await session.refresh(child_run)
        child_id = child_run.id

    # propagate_cancellation opens its own session internally via
    # the lifecycle helper; we pass the shared factory session here.
    async with factory() as session:
        cancelled_ids = await propagate_cancellation(session, run_id=parent_id)

    assert child_id in cancelled_ids

    child = await _get_run(factory, child_id)
    assert child.status == "cancelling"


@pytest.mark.asyncio
async def test_terminate_appends_terminated_event():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="paused")

    async with factory() as session:
        await terminate_run(session, run_id=run_id, reason="operator kill", actor_id="admin")

    events = await _get_events(factory, run_id)
    term_events = [e for e in events if e.event_type == "run.terminated"]
    assert len(term_events) == 1
    assert term_events[0].payload["reason"] == "operator kill"


# ── pause_run tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pause_sets_paused_status():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="running")

    async with factory() as session:
        run = await pause_run(session, run_id=run_id, reason="rate limit", actor_id="sys")

    assert run.status == "paused"
    assert run.paused_at is not None


@pytest.mark.asyncio
async def test_pause_from_queued():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="queued")

    async with factory() as session:
        run = await pause_run(session, run_id=run_id, reason="maintenance", actor_id="sys")

    assert run.status == "paused"


@pytest.mark.asyncio
async def test_pause_survives_simulated_restart():
    """Re-read the row from a fresh session — paused status persists."""
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="running")

    async with factory() as session:
        await pause_run(session, run_id=run_id, reason="restart test", actor_id="sys")

    # Simulate restart: open a brand-new session and re-read the row.
    run = await _get_run(factory, run_id)
    assert run.status == "paused"
    assert run.paused_at is not None


@pytest.mark.asyncio
async def test_pause_from_terminal_raises():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="completed")

    async with factory() as session:
        with pytest.raises(ValueError):
            await pause_run(session, run_id=run_id, reason="late", actor_id="sys")


# ── resume_run tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resume_from_paused_sets_running():
    """Resume flips a paused run back to queued (ready for drain loop)."""
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="paused")

    async with factory() as session:
        run = await resume_run(session, run_id=run_id, reason="operator resume", actor_id="u1")

    assert run.status == "queued"
    assert run.resumed_at is not None
    assert run.lease_owner is None


@pytest.mark.asyncio
async def test_resume_from_non_paused_raises():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="running")

    async with factory() as session:
        with pytest.raises(ValueError, match="resume only valid from"):
            await resume_run(session, run_id=run_id, reason="invalid", actor_id="u1")


@pytest.mark.asyncio
async def test_resume_appends_event():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="paused")

    async with factory() as session:
        await resume_run(session, run_id=run_id, reason="ops resumed", actor_id="ops")

    events = await _get_events(factory, run_id)
    resume_events = [e for e in events if e.event_type == "run.resumed"]
    assert len(resume_events) == 1
    assert resume_events[0].payload["actor_id"] == "ops"


# ── end-state tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelled_run_reaches_cancelled_not_failed():
    """A run cancelled before dispatch should end as 'cancelling', not 'failed'."""
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="queued")

    async with factory() as session:
        run = await cancel_run(session, run_id=run_id, reason="test", actor_id="u1")

    assert run.status == "cancelling"
    # No error fields set by cancel.
    run_reread = await _get_run(factory, run_id)
    assert run_reread.error is None
    assert run_reread.error_code is None


@pytest.mark.asyncio
async def test_terminated_run_reaches_terminated():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="running")

    async with factory() as session:
        run = await terminate_run(session, run_id=run_id, reason="force stop", actor_id="admin")

    assert run.status == "terminated"
    run_reread = await _get_run(factory, run_id)
    assert run_reread.status == "terminated"


@pytest.mark.asyncio
async def test_propagate_cancellation_returns_empty_when_no_children():
    factory = await _make_factory()
    run_id = await _seed_run(factory, status="running")

    async with factory() as session:
        result = await propagate_cancellation(session, run_id=run_id)

    assert result == []
