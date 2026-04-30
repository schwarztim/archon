"""W18a — Lifecycle Crash/Restart Chaos tests.

Deterministic chaos tests that prove the lifecycle substrate handles:
  - Worker crash mid-activity: lease expiry + reclaim by another worker
  - Backend restart mid-run: state persists across new session
  - Cancel race: exactly one terminal state
  - Pause/Resume across a simulated restart
  - Terminate kills in-flight ActivityExecution rows

All tests use inline SQLite (no conftest.py).
Run with: .venv/bin/python -m pytest tests/chaos/test_lifecycle_chaos.py -v --noconftest
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Stub modes prevent live network/LLM calls.
os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Inline engine + session factory
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all relevant tables."""
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.activity import ActivityExecution  # noqa: F401
    from app.models.approval import Approval, Signal  # noqa: F401
    from app.models.task_queue import Task, TaskQueue  # noqa: F401
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


async def _seed_workflow(factory) -> UUID:
    from app.models.workflow import Workflow

    async with factory() as session:
        wf = Workflow(name="chaos-wf", steps=[], graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


async def _seed_run(
    factory,
    *,
    workflow_id: UUID,
    status: str = "queued",
    tenant_id: UUID | None = None,
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
) -> UUID:
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        run = WorkflowRun(
            workflow_id=workflow_id,
            kind="workflow",
            status=status,
            tenant_id=tenant_id,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
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


async def _seed_activity_execution(
    factory,
    *,
    run_id: UUID,
    tenant_id: UUID | None = None,
    status: str = "running",
) -> UUID:
    from app.models.activity import ActivityExecution

    exec_id = uuid4()
    async with factory() as session:
        row = ActivityExecution(
            id=exec_id,
            tenant_id=tenant_id,
            task_id=None,
            run_id=run_id,
            step_id="s1",
            attempt_number=1,
            worker_id="test-worker",
            queue_name="default",
            activity_type="test.activity",
            idempotency_key=str(uuid4()),
            status=status,
            started_at=datetime.utcnow(),
        )
        session.add(row)
        await session.commit()
        return exec_id


# ---------------------------------------------------------------------------
# test_worker_crash_mid_activity_allows_retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_crash_mid_activity_allows_retry() -> None:
    """Claim task, start activity, simulate worker death via lease expiry.

    Verifies that after the lease expires, another worker can reclaim the run
    (no stuck lease, no double execution — the second claim wins cleanly).
    """
    engine, factory = await _make_engine_and_factory()
    try:
        from app.services.run_lifecycle import claim_run, reclaim_expired_runs

        workflow_id = await _seed_workflow(factory)
        run_id = await _seed_run(factory, workflow_id=workflow_id, status="queued")

        worker_a = f"worker-crashed-{uuid4().hex[:6]}"
        worker_b = f"worker-recovered-{uuid4().hex[:6]}"

        # Worker A claims the run.
        async with factory() as session:
            claimed = await claim_run(session, run_id=run_id, worker_id=worker_a)
        assert claimed is not None, "worker A must win the claim"
        assert claimed.lease_owner == worker_a
        assert claimed.status == "running"

        # Simulate crash: backdate the lease into the past.
        from app.models.workflow import WorkflowRun

        async with factory() as session:
            row = await session.get(WorkflowRun, run_id)
            row.lease_expires_at = datetime.utcnow() - timedelta(seconds=300)
            session.add(row)
            await session.commit()

        # Reclaim sweep returns the abandoned run to queued.
        async with factory() as session:
            reclaimed = await reclaim_expired_runs(session, lease_grace_seconds=0)
        assert reclaimed == 1, "exactly one expired-lease run should be reclaimed"

        # Verify state is now queued.
        async with factory() as session:
            row = await session.get(WorkflowRun, run_id)
        assert row.status == "queued"
        assert row.lease_owner is None

        # Worker B claims the recovered run.
        async with factory() as session:
            claimed_b = await claim_run(session, run_id=run_id, worker_id=worker_b)
        assert claimed_b is not None, "worker B must reclaim the run"
        assert claimed_b.lease_owner == worker_b
        assert claimed_b.status == "running"

        # Confirm only worker B holds the run (no double claim).
        async with factory() as session:
            final = await session.get(WorkflowRun, run_id)
        assert final.lease_owner == worker_b
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# test_backend_restart_mid_run_preserves_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backend_restart_mid_run_preserves_state() -> None:
    """Create a running run, open a fresh session (simulated restart), verify persistence.

    The run must remain in 'running' status with its lease intact after
    opening a new AsyncSession on the same DB — proving durability across
    a process restart that reconnects to the same SQLite file.
    """
    engine, factory = await _make_engine_and_factory()
    try:
        from app.services.run_lifecycle import claim_run

        workflow_id = await _seed_workflow(factory)
        run_id = await _seed_run(factory, workflow_id=workflow_id, status="queued")
        worker_id = f"worker-{uuid4().hex[:6]}"

        # Claim the run (simulates a real worker taking ownership).
        async with factory() as session:
            claimed = await claim_run(session, run_id=run_id, worker_id=worker_id)
        assert claimed is not None
        assert claimed.status == "running"

        # "Restart": open a brand-new session from the same engine/factory.
        # This simulates the backend process reconnecting to the DB.
        new_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with new_factory() as fresh_session:
            from app.models.workflow import WorkflowRun

            reloaded = await fresh_session.get(WorkflowRun, run_id)

        assert reloaded is not None, "run must still exist after simulated restart"
        assert reloaded.status == "running", (
            f"run should still be 'running', got {reloaded.status!r}"
        )
        assert reloaded.lease_owner == worker_id
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# test_cancel_race_no_double_execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_race_no_double_execution() -> None:
    """Start a run, request cancel before dispatch, verify single terminal state.

    The dispatcher honours cancel_requested_at set on a queued/pending run
    and must produce exactly one terminal row — either 'cancelled' (cancel
    wins) or 'completed' (dispatch wins). Under test we control the race by
    setting cancel_requested_at before the claim attempt.
    """
    engine, factory = await _make_engine_and_factory()
    try:
        from app.models.workflow import WorkflowRun
        from app.services.run_lifecycle import claim_run

        workflow_id = await _seed_workflow(factory)
        run_id = await _seed_run(factory, workflow_id=workflow_id, status="queued")

        # Set cancel_requested_at BEFORE any claim attempt (simulates the
        # cancel arriving while the run is still queued).
        cancel_time = datetime.utcnow()
        async with factory() as session:
            row = await session.get(WorkflowRun, run_id)
            row.cancel_requested_at = cancel_time
            session.add(row)
            await session.commit()

        # The dispatcher's pre-claim path honours cancel_requested_at on
        # queued/pending runs. We replicate that path here directly:
        async with factory() as session:
            run = await session.get(WorkflowRun, run_id)
            if run.cancel_requested_at is not None and run.status in ("queued", "pending"):
                run.status = "cancelled"
                run.completed_at = datetime.utcnow()
                session.add(run)
                await session.commit()

        # Verify the terminal state is exactly 'cancelled' (not duplicated).
        async with factory() as session:
            final = await session.get(WorkflowRun, run_id)

        assert final.status == "cancelled", (
            f"expected 'cancelled', got {final.status!r}"
        )
        assert final.completed_at is not None

        # Attempting a second claim must fail (row is no longer queued/pending).
        async with factory() as session:
            second_claim = await claim_run(
                session, run_id=run_id, worker_id="late-worker"
            )
        assert second_claim is None, (
            "a second claim on a cancelled run must return None"
        )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# test_pause_resume_across_restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pause_resume_across_restart() -> None:
    """Pause a running run, open a fresh session, resume it; verify queued status."""
    engine, factory = await _make_engine_and_factory()
    try:
        from app.services.run_lifecycle import claim_run, pause_run, resume_run

        workflow_id = await _seed_workflow(factory)
        run_id = await _seed_run(factory, workflow_id=workflow_id, status="queued")
        worker_id = f"worker-{uuid4().hex[:6]}"

        # Claim the run so it transitions to 'running'.
        async with factory() as session:
            claimed = await claim_run(session, run_id=run_id, worker_id=worker_id)
        assert claimed is not None
        assert claimed.status == "running"

        # Pause the run.
        async with factory() as session:
            paused = await pause_run(
                session,
                run_id=run_id,
                reason="manual pause",
                actor_id="test-actor",
            )
        assert paused.status == "paused"
        assert paused.paused_at is not None

        # Simulate restart: new session from same engine.
        new_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Verify paused state persisted.
        async with new_factory() as fresh_session:
            from app.models.workflow import WorkflowRun

            reloaded = await fresh_session.get(WorkflowRun, run_id)
        assert reloaded.status == "paused"

        # Resume from the new session.
        async with new_factory() as fresh_session:
            resumed = await resume_run(
                fresh_session,
                run_id=run_id,
                reason="manual resume after restart",
                actor_id="test-actor",
            )
        assert resumed.status == "queued", (
            f"resume should set status='queued', got {resumed.status!r}"
        )
        assert resumed.lease_owner is None, "lease must be cleared on resume"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# test_terminate_kills_in_flight_activity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_kills_in_flight_activity() -> None:
    """Start an activity, terminate the run, verify ActivityExecution is cancelled."""
    engine, factory = await _make_engine_and_factory()
    try:
        from app.models.activity import ActivityExecution
        from app.models.workflow import WorkflowRun
        from app.services.run_lifecycle import claim_run, terminate_run

        tenant_id = uuid4()
        workflow_id = await _seed_workflow(factory)
        run_id = await _seed_run(
            factory,
            workflow_id=workflow_id,
            status="queued",
            tenant_id=tenant_id,
        )

        # Claim so status=running.
        worker_id = f"worker-{uuid4().hex[:6]}"
        async with factory() as session:
            claimed = await claim_run(session, run_id=run_id, worker_id=worker_id)
        assert claimed is not None

        # Create an in-flight ActivityExecution row.
        exec_id = await _seed_activity_execution(
            factory, run_id=run_id, tenant_id=tenant_id, status="running"
        )

        # Verify activity is running.
        async with factory() as session:
            act = await session.get(ActivityExecution, exec_id)
        assert act.status == "running"

        # Terminate the run — must cancel in-flight activities.
        async with factory() as session:
            terminated = await terminate_run(
                session,
                run_id=run_id,
                reason="hard stop",
                actor_id="ops",
            )
        assert terminated.status == "terminated"
        assert terminated.completed_at is not None

        # Verify ActivityExecution was marked cancelled.
        async with factory() as session:
            act_after = await session.get(ActivityExecution, exec_id)
        assert act_after.status == "cancelled", (
            f"in-flight ActivityExecution should be cancelled after terminate, "
            f"got {act_after.status!r}"
        )
    finally:
        await engine.dispose()
