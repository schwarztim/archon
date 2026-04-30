"""Tests for W1.5 — Task-queue dispatcher polling.

Covers:
  - ExecutionFacade creates a Task row alongside the WorkflowRun.
  - Dispatcher claims a Task before falling back to legacy WorkflowRun scan.
  - Task is marked completed after successful dispatch.
  - Task is marked failed after dispatch raises.
  - No double-claim across concurrent workers.
  - Legacy fallback still works when no tasks exist.

These tests use an in-memory SQLite engine + SQLModel.metadata.create_all,
following the same pattern as test_task_queues.py.

Run with:
    /Users/timothy.schwarz/Projects/Archon/.venv/bin/python \
        -m pytest tests/test_dispatcher_task_queue_polling.py -v --noconftest
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Keep the environment safe for import-time guards in the app modules.
os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Engine / factory helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build a shared in-memory SQLite engine with all required tables."""
    # Import models so their metadata is registered before create_all.
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.task_queue import Task, TaskQueue  # noqa: F401
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _seed_workflow(factory) -> UUID:
    """Insert a Workflow and return its id."""
    from app.models.workflow import Workflow

    async with factory() as session:
        wf = Workflow(name="poll-wf", steps=[], graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


async def _seed_run(factory, *, workflow_id: UUID, tenant_id: UUID, status: str = "queued") -> UUID:
    """Insert a WorkflowRun and return its id."""
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


async def _seed_task(factory, *, run_id: UUID, tenant_id: UUID, status: str = "visible") -> UUID:
    """Insert a Task in the default queue and return its id."""
    from app.models.task_queue import Task

    async with factory() as session:
        task = Task(
            tenant_id=tenant_id,
            run_id=run_id,
            queue_name="default",
            task_type="workflow",
            status=status,
            visible_at=_utcnow(),
            priority=100,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        return task.id


async def _count_tasks(factory, *, run_id: UUID, status: str) -> int:
    from app.models.task_queue import Task
    from sqlmodel import select

    async with factory() as session:
        result = await session.execute(
            select(Task)
            .where(Task.run_id == run_id)
            .where(Task.status == status)
        )
        return len(result.scalars().all())


# ---------------------------------------------------------------------------
# test_facade_creates_task_on_run_creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_facade_creates_task_on_run_creation():
    """ExecutionFacade.create_run must create a Task row in the default queue."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf_id = await _seed_workflow(factory)

    # Patch the session factory used inside execution_facade so it uses our
    # in-memory engine. We inject the factory via a session override on the
    # session passed to create_run itself, but _enqueue_task_for_run also
    # needs a session. Since create_run passes the session along, we just
    # need to ensure create_run gets a session from our factory.
    from app.services.execution_facade import ExecutionFacade

    async with factory() as session:
        # Patch _async_append_event so we don't need event_service wired up.
        import app.services.execution_facade as ef_mod

        async def _noop_event(s, run_id, event_type, payload, **kw):
            from app.models.workflow import WorkflowRunEvent
            return WorkflowRunEvent(
                run_id=run_id,
                sequence=0,
                event_type=event_type,
                payload=payload,
                prev_hash=None,
                current_hash="testhash",
            )

        with patch.object(ef_mod, "_async_append_event", side_effect=_noop_event):
            # Also patch idempotency_service to skip the check.
            import app.services.idempotency_service as idem_mod
            with patch.object(idem_mod, "check_and_acquire", return_value=(None, False)):
                run, is_new = await ExecutionFacade.create_run(
                    session,
                    kind="workflow",
                    workflow_id=wf_id,
                    tenant_id=tenant_id,
                    input_data={},
                )

    assert is_new is True
    assert run.id is not None

    # Now verify a Task row was created.
    task_count = await _count_tasks(factory, run_id=run.id, status="visible")
    assert task_count == 1, f"Expected 1 visible task, got {task_count}"

    await engine.dispose()


# ---------------------------------------------------------------------------
# test_dispatcher_claims_task_before_legacy_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_claims_task_before_legacy_run():
    """claim_next_task_for_dispatch returns a task when one is available."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf_id = await _seed_workflow(factory)
    run_id = await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant_id)
    task_id = await _seed_task(factory, run_id=run_id, tenant_id=tenant_id)

    from app.services.run_dispatcher import claim_next_task_for_dispatch

    async with factory() as session:
        task = await claim_next_task_for_dispatch(
            session,
            queue_names=["default"],
            worker_id="test-worker",
            tenant_id=tenant_id,
            lease_seconds=30,
        )
        await session.commit()

    assert task is not None
    assert task.id == task_id
    assert task.status == "claimed"
    assert task.lease_owner == "test-worker"
    assert task.run_id == run_id

    await engine.dispose()


# ---------------------------------------------------------------------------
# test_claimed_task_is_completed_after_dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claimed_task_is_completed_after_dispatch():
    """After dispatch_next_from_task_queue succeeds, the task becomes completed."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf_id = await _seed_workflow(factory)
    run_id = await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant_id)
    task_id = await _seed_task(factory, run_id=run_id, tenant_id=tenant_id)

    from app.models.task_queue import Task
    from app.services.run_dispatcher import dispatch_next_from_task_queue

    # Stub dispatch_run to return a fake completed run.
    fake_run = type("FakeRun", (), {"status": "completed", "id": run_id})()

    with patch(
        "app.services.run_dispatcher.dispatch_run",
        new=AsyncMock(return_value=fake_run),
    ), patch(
        "app.services.run_dispatcher.async_session_factory",
        return_value=factory(),
    ):
        # dispatch_next_from_task_queue creates its own sessions. We need
        # to patch the session factory it uses.
        import app.services.run_dispatcher as disp_mod

        original_factory = disp_mod.async_session_factory

        # Override the factory inside the dispatcher module for this test.
        disp_mod.async_session_factory = factory  # type: ignore[assignment]
        try:
            result = await dispatch_next_from_task_queue(
                queue_names=["default"],
                worker_id="test-worker",
                tenant_id=tenant_id,
                lease_seconds=30,
            )
        finally:
            disp_mod.async_session_factory = original_factory

    assert result is not None

    # Verify task is now completed.
    async with factory() as session:
        task = await session.get(Task, task_id)
        await session.refresh(task)
    assert task.status == "completed", f"Expected completed, got {task.status}"

    await engine.dispose()


# ---------------------------------------------------------------------------
# test_failed_dispatch_releases_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_dispatch_releases_task():
    """When dispatch_run raises, the task is released back to visible."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf_id = await _seed_workflow(factory)
    run_id = await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant_id)
    task_id = await _seed_task(factory, run_id=run_id, tenant_id=tenant_id)

    from app.models.task_queue import Task
    from app.services.run_dispatcher import dispatch_next_from_task_queue
    import app.services.run_dispatcher as disp_mod

    original_factory = disp_mod.async_session_factory
    disp_mod.async_session_factory = factory  # type: ignore[assignment]
    try:
        with patch(
            "app.services.run_dispatcher.dispatch_run",
            new=AsyncMock(side_effect=RuntimeError("engine exploded")),
        ):
            result = await dispatch_next_from_task_queue(
                queue_names=["default"],
                worker_id="test-worker",
                tenant_id=tenant_id,
                lease_seconds=30,
            )
    finally:
        disp_mod.async_session_factory = original_factory

    assert result is None

    # Task should be released back to visible for retry.
    async with factory() as session:
        task = await session.get(Task, task_id)
        await session.refresh(task)
    assert task.status == "visible", f"Expected visible after failure, got {task.status}"

    await engine.dispose()


# ---------------------------------------------------------------------------
# test_no_double_claim_across_workers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_double_claim_across_workers():
    """Two concurrent claim attempts on the same task — exactly one wins."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf_id = await _seed_workflow(factory)
    run_id = await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant_id)
    task_id = await _seed_task(factory, run_id=run_id, tenant_id=tenant_id)

    from app.services.run_dispatcher import claim_next_task_for_dispatch

    async def _try_claim(worker: str):
        async with factory() as session:
            task = await claim_next_task_for_dispatch(
                session,
                queue_names=["default"],
                worker_id=worker,
                tenant_id=tenant_id,
                lease_seconds=30,
            )
            await session.commit()
            return task

    results = await asyncio.gather(
        _try_claim("worker-A"),
        _try_claim("worker-B"),
    )

    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]

    assert len(winners) == 1, f"Expected exactly 1 winner, got {len(winners)}"
    assert len(losers) == 1, f"Expected exactly 1 loser, got {len(losers)}"
    assert winners[0].status == "claimed"
    assert winners[0].lease_owner in {"worker-A", "worker-B"}

    await engine.dispose()


# ---------------------------------------------------------------------------
# test_legacy_fallback_still_works_when_no_tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_fallback_still_works_when_no_tasks():
    """claim_next_task_for_dispatch returns None when no tasks are visible.

    This verifies the legacy WorkflowRun drain is not blocked — when the
    task queue is empty the dispatcher returns None from the task path,
    allowing the caller to fall back to the legacy WorkflowRun query.
    """
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()

    from app.services.run_dispatcher import claim_next_task_for_dispatch

    async with factory() as session:
        task = await claim_next_task_for_dispatch(
            session,
            queue_names=["default"],
            worker_id="test-worker",
            tenant_id=tenant_id,
            lease_seconds=30,
        )

    assert task is None

    await engine.dispose()


# ---------------------------------------------------------------------------
# test_complete_task_and_fail_task_helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_task_marks_status_completed():
    """complete_task flips status from claimed → completed."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf_id = await _seed_workflow(factory)
    run_id = await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant_id)

    from app.models.task_queue import Task
    from app.services.task_queue_service import claim_task, complete_task, enqueue_task

    # Enqueue and claim the task so it is in 'claimed' state.
    async with factory() as session:
        task = await enqueue_task(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            queue_name="default",
            task_type="workflow",
            commit=True,
        )
        task_id = task.id

    async with factory() as session:
        claimed = await claim_task(
            session,
            task_id=task_id,
            lease_owner="worker-X",
            lease_ttl_seconds=30,
        )
        await session.commit()

    assert claimed is not None
    assert claimed.status == "claimed"

    async with factory() as session:
        await complete_task(session, task_id=task_id)
        await session.commit()

    async with factory() as session:
        row = await session.get(Task, task_id)
        await session.refresh(row)
    assert row.status == "completed"

    await engine.dispose()


@pytest.mark.asyncio
async def test_fail_task_marks_status_failed():
    """fail_task flips status from claimed → failed."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf_id = await _seed_workflow(factory)
    run_id = await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant_id)

    from app.models.task_queue import Task
    from app.services.task_queue_service import claim_task, enqueue_task, fail_task

    async with factory() as session:
        task = await enqueue_task(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            queue_name="default",
            task_type="workflow",
            commit=True,
        )
        task_id = task.id

    async with factory() as session:
        await claim_task(
            session,
            task_id=task_id,
            lease_owner="worker-X",
            lease_ttl_seconds=30,
        )
        await session.commit()

    async with factory() as session:
        await fail_task(session, task_id=task_id, error_code="engine_error")
        await session.commit()

    async with factory() as session:
        row = await session.get(Task, task_id)
        await session.refresh(row)
    assert row.status == "failed"

    await engine.dispose()


@pytest.mark.asyncio
async def test_release_task_returns_to_visible():
    """release_task flips status from claimed → visible (retry path)."""
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf_id = await _seed_workflow(factory)
    run_id = await _seed_run(factory, workflow_id=wf_id, tenant_id=tenant_id)

    from app.models.task_queue import Task
    from app.services.task_queue_service import claim_task, enqueue_task, release_task

    async with factory() as session:
        task = await enqueue_task(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            queue_name="default",
            task_type="workflow",
            commit=True,
        )
        task_id = task.id

    async with factory() as session:
        await claim_task(
            session,
            task_id=task_id,
            lease_owner="worker-X",
            lease_ttl_seconds=30,
        )
        await session.commit()

    async with factory() as session:
        await release_task(session, task_id=task_id)
        await session.commit()

    async with factory() as session:
        row = await session.get(Task, task_id)
        await session.refresh(row)
    assert row.status == "visible"
    assert row.lease_owner is None

    await engine.dispose()
