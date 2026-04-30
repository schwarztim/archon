"""Tests for run_lifecycle claim/lease/release/reclaim primitives.

Verifies the optimistic-lock semantics that the dispatcher relies on
to coordinate multiple workers without losing or double-running rows
(ADR-001 unified run table + lease columns).

Tests:
    1. test_claim_run_succeeds_for_queued_run
    2. test_claim_run_returns_none_if_already_claimed_by_another
    3. test_claim_run_takes_over_expired_lease
    4. test_renew_lease_only_for_owner
    5. test_release_lease_clears_lease_fields
    6. test_reclaim_expired_runs_returns_to_queued
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables."""
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
    status: str = "queued",
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
):
    """Insert a Workflow + WorkflowRun and return the run_id."""
    from app.models.workflow import Workflow, WorkflowRun

    async with factory() as session:
        wf = Workflow(name="t-wf", steps=[], graph_definition={})
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
                "steps": [],
            },
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# Test 1: claim succeeds for a queued run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_run_succeeds_for_queued_run():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory, status="queued")

    from app.services.run_lifecycle import claim_run

    async with factory() as session:
        claimed = await claim_run(
            session,
            run_id=run_id,
            worker_id="worker-A",
            lease_ttl_seconds=60,
        )

    assert claimed is not None
    assert claimed.id == run_id
    assert claimed.status == "running"
    assert claimed.lease_owner == "worker-A"
    assert claimed.attempt == 1
    assert claimed.claimed_at is not None
    assert claimed.started_at is not None
    assert claimed.lease_expires_at is not None

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: claim returns None when another worker already owns the row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_run_returns_none_if_already_claimed_by_another():
    engine, factory = await _make_engine_and_factory()
    # Pre-seed a row with an active (non-expired) lease.
    fresh_expiry = datetime.utcnow() + timedelta(minutes=5)
    run_id = await _seed_run(
        factory,
        status="running",
        lease_owner="worker-A",
        lease_expires_at=fresh_expiry,
    )

    from app.services.run_lifecycle import claim_run

    async with factory() as session:
        claimed = await claim_run(
            session,
            run_id=run_id,
            worker_id="worker-B",
        )

    assert claimed is None

    # Confirm the row is still owned by worker-A.
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        row = await session.get(WorkflowRun, run_id)
    assert row is not None
    assert row.lease_owner == "worker-A"
    assert row.status == "running"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: claim takes over an expired lease
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_run_takes_over_expired_lease():
    """When a worker dies mid-run, the next caller can claim once the lease
    expires (subject to grace via reclaim_expired_runs in production).

    Here we test the claim_run path directly: the row is in status='queued'
    after a prior reclaim cycle, and a brand-new worker_id can take it
    even though lease_expires_at is in the past.
    """
    engine, factory = await _make_engine_and_factory()
    expired = datetime.utcnow() - timedelta(minutes=5)

    # Simulate a reclaimed-but-not-yet-cleared row: status='queued' with
    # an old lease_expires_at. claim_run's predicate explicitly accepts
    # lease_expires_at IN THE PAST (or NULL).
    run_id = await _seed_run(
        factory,
        status="queued",
        lease_owner="dead-worker",
        lease_expires_at=expired,
    )

    from app.services.run_lifecycle import claim_run

    async with factory() as session:
        claimed = await claim_run(
            session,
            run_id=run_id,
            worker_id="fresh-worker",
        )

    assert claimed is not None
    assert claimed.lease_owner == "fresh-worker"
    assert claimed.status == "running"
    assert claimed.attempt == 1  # incremented from 0

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: renew_lease only succeeds for the owner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_renew_lease_only_for_owner():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory, status="queued")

    from app.services.run_lifecycle import claim_run, renew_lease

    async with factory() as session:
        await claim_run(session, run_id=run_id, worker_id="worker-A")

    # Owner can renew.
    async with factory() as session:
        ok = await renew_lease(session, run_id=run_id, worker_id="worker-A")
    assert ok is True

    # A different worker cannot renew.
    async with factory() as session:
        ok = await renew_lease(session, run_id=run_id, worker_id="worker-B")
    assert ok is False

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5: release_lease clears lease fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_release_lease_clears_lease_fields():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory, status="queued")

    from app.models.workflow import WorkflowRun
    from app.services.run_lifecycle import claim_run, release_lease

    async with factory() as session:
        claimed = await claim_run(session, run_id=run_id, worker_id="worker-A")
    assert claimed is not None
    assert claimed.lease_owner == "worker-A"

    async with factory() as session:
        await release_lease(session, run_id=run_id, worker_id="worker-A")

    async with factory() as session:
        row = await session.get(WorkflowRun, run_id)
    assert row is not None
    assert row.lease_owner is None
    assert row.lease_expires_at is None
    # Status not affected by release_lease (the dispatcher controls that).
    assert row.status == "running"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 6: reclaim_expired_runs returns expired rows to queued
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reclaim_expired_runs_returns_to_queued():
    engine, factory = await _make_engine_and_factory()
    expired_at = datetime.utcnow() - timedelta(minutes=10)

    # Two rows: one expired+running (should be reclaimed), one fresh+running
    # (should be left alone).
    expired_run_id = await _seed_run(
        factory,
        status="running",
        lease_owner="dead-worker",
        lease_expires_at=expired_at,
    )
    fresh_run_id = await _seed_run(
        factory,
        status="running",
        lease_owner="alive-worker",
        lease_expires_at=datetime.utcnow() + timedelta(minutes=5),
    )

    from app.models.workflow import WorkflowRun
    from app.services.run_lifecycle import reclaim_expired_runs

    async with factory() as session:
        count = await reclaim_expired_runs(session, lease_grace_seconds=10)

    assert count == 1

    async with factory() as session:
        expired_row = await session.get(WorkflowRun, expired_run_id)
        fresh_row = await session.get(WorkflowRun, fresh_run_id)

    assert expired_row is not None
    assert expired_row.status == "queued"
    assert expired_row.lease_owner is None
    assert expired_row.lease_expires_at is None

    assert fresh_row is not None
    assert fresh_row.status == "running"
    assert fresh_row.lease_owner == "alive-worker"

    await engine.dispose()
