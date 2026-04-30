"""Tests for the per-tenant + per-workflow concurrency quota service.

Phase 6 (WS17) — these tests exercise the quota_service surface against
an in-memory SQLite engine seeded with TenantQuota + WorkflowRun rows.

Coverage:
    1. ``check_quota`` returns headroom when no runs are active.
    2. ``reserve_slot`` succeeds when below the cap.
    3. ``reserve_slot`` blocks when the tenant-wide cap is reached.
    4. ``reserve_slot`` blocks when the per-workflow cap is reached.
    5. ``check_quota`` falls back to defaults when no quota row exists.
    6. Concurrent ``reserve_slot`` calls with cap=1 race fairly: at
       least one denies once the slot is filled (the snapshot reflects
       reality before the claim, so reserve_slot itself is a read-only
       check; the atomic 1-winner property comes from claim_run).
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all relevant tables created."""
    # Import models so SQLModel.metadata is populated.
    from app.models import (  # noqa: F401
        Agent,
        Execution,
        User,
    )
    from app.models.tenancy import Tenant, TenantQuota  # noqa: F401
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


async def _seed_tenant(factory, tenant_id):
    """Insert a Tenant row so FK references in TenantQuota succeed."""
    from app.models.tenancy import Tenant

    async with factory() as session:
        t = Tenant(
            id=tenant_id,
            name=f"tenant-{str(tenant_id)[:8]}",
            slug=f"slug-{str(tenant_id)[:8]}",
            owner_email="t@example.com",
        )
        session.add(t)
        await session.commit()


async def _seed_quota(
    factory,
    *,
    tenant_id,
    max_concurrent_runs: int = 10,
    max_concurrent_per_workflow: int = 5,
):
    """Insert a TenantQuota row with the given concurrency caps."""
    from app.models.tenancy import TenantQuota

    await _seed_tenant(factory, tenant_id)
    async with factory() as session:
        quota = TenantQuota(
            tenant_id=tenant_id,
            max_concurrent_runs=max_concurrent_runs,
            max_concurrent_per_workflow=max_concurrent_per_workflow,
        )
        session.add(quota)
        await session.commit()


async def _seed_workflow(factory, *, tenant_id):
    """Insert a Workflow row owned by ``tenant_id`` and return its id."""
    from app.models.workflow import Workflow

    async with factory() as session:
        wf = Workflow(
            name="quota-test-wf",
            tenant_id=tenant_id,
            steps=[],
            graph_definition={},
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


async def _seed_run(
    factory,
    *,
    tenant_id,
    workflow_id,
    status: str = "running",
):
    """Insert a WorkflowRun row directly into the given status."""
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        run = WorkflowRun(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            kind="workflow",
            status=status,
            definition_snapshot={
                "kind": "workflow",
                "id": str(workflow_id),
                "name": "quota-test-wf",
                "steps": [],
                "graph_definition": {},
            },
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# Test 1: headroom when nothing is running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_quota_returns_headroom_with_no_active_runs():
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    workflow_id = await _seed_workflow(factory, tenant_id=tenant_id)
    await _seed_quota(
        factory,
        tenant_id=tenant_id,
        max_concurrent_runs=10,
        max_concurrent_per_workflow=5,
    )

    from app.services.quota_service import check_quota

    async with factory() as session:
        snap = await check_quota(
            session, tenant_id=tenant_id, workflow_id=workflow_id
        )

    assert snap.is_throttled is False
    assert snap.current_running == 0
    assert snap.headroom == 5  # min(10, 5) = 5
    assert snap.max_concurrent_runs == 10
    assert snap.max_concurrent_per_workflow == 5

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: reserve_slot succeeds under cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reserve_slot_succeeds_under_cap():
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    workflow_id = await _seed_workflow(factory, tenant_id=tenant_id)
    await _seed_quota(
        factory,
        tenant_id=tenant_id,
        max_concurrent_runs=10,
        max_concurrent_per_workflow=5,
    )
    # Seed 1 running run → still 4 workflow slots and 9 tenant slots.
    await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=workflow_id, status="running"
    )

    from app.services.quota_service import reserve_slot

    async with factory() as session:
        allowed = await reserve_slot(
            session,
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            run_id=uuid4(),
        )

    assert allowed is True

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: reserve_slot blocks at tenant cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reserve_slot_blocks_at_tenant_cap():
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    # Two workflows so we can hit the tenant cap without exceeding the
    # per-workflow cap (which would also block, ambiguating the test).
    wf_a = await _seed_workflow(factory, tenant_id=tenant_id)
    wf_b = await _seed_workflow(factory, tenant_id=tenant_id)
    await _seed_quota(
        factory,
        tenant_id=tenant_id,
        max_concurrent_runs=2,
        max_concurrent_per_workflow=10,
    )
    # Saturate the tenant cap with 2 runs across different workflows.
    await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf_a, status="running"
    )
    await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf_b, status="running"
    )

    from app.services.quota_service import check_quota, reserve_slot

    async with factory() as session:
        snap = await check_quota(session, tenant_id=tenant_id)
        assert snap.current_running == 2
        assert snap.headroom == 0
        assert snap.is_throttled is True

        allowed = await reserve_slot(
            session,
            tenant_id=tenant_id,
            workflow_id=wf_a,
            run_id=uuid4(),
        )

    assert allowed is False

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: reserve_slot blocks at per-workflow cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reserve_slot_blocks_at_workflow_cap():
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf = await _seed_workflow(factory, tenant_id=tenant_id)
    await _seed_quota(
        factory,
        tenant_id=tenant_id,
        max_concurrent_runs=100,  # tenant cap not the limiting factor
        max_concurrent_per_workflow=2,
    )
    # Fill the workflow cap.
    await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="running"
    )
    await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="running"
    )

    from app.services.quota_service import check_quota, reserve_slot

    async with factory() as session:
        snap = await check_quota(
            session, tenant_id=tenant_id, workflow_id=wf
        )
        # current_running reports workflow-scoped count when workflow_id given.
        assert snap.current_running == 2
        assert snap.headroom == 0
        assert snap.is_throttled is True

        allowed = await reserve_slot(
            session,
            tenant_id=tenant_id,
            workflow_id=wf,
            run_id=uuid4(),
        )

    assert allowed is False

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5: missing TenantQuota row → defaults applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_quota_unset_quota_uses_default():
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    # No TenantQuota row inserted.
    workflow_id = await _seed_workflow(factory, tenant_id=tenant_id)

    from app.services.quota_service import (
        DEFAULT_MAX_CONCURRENT_PER_WORKFLOW,
        DEFAULT_MAX_CONCURRENT_RUNS,
        check_quota,
    )

    async with factory() as session:
        snap = await check_quota(
            session, tenant_id=tenant_id, workflow_id=workflow_id
        )

    assert snap.max_concurrent_runs == DEFAULT_MAX_CONCURRENT_RUNS
    assert snap.max_concurrent_per_workflow == DEFAULT_MAX_CONCURRENT_PER_WORKFLOW
    assert snap.is_throttled is False
    assert snap.current_running == 0

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 6: concurrent reserve_slot races over a 1-slot tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_reserve_only_one_wins():
    """Once a slot is consumed, subsequent reserve_slot calls deny.

    ``reserve_slot`` is a read-only check — it does not itself "win" a
    slot. Atomic single-winner behaviour is provided by
    ``run_lifecycle.claim_run``'s optimistic UPDATE. This test verifies
    the *quota* property: after a ``running`` row is committed, every
    concurrent reservation against a 1-slot cap denies. We simulate the
    "1 winner" effect by seeding one running run, then issuing 5
    concurrent reservations against the now-exhausted cap.
    """
    engine, factory = await _make_engine_and_factory()
    tenant_id = uuid4()
    wf = await _seed_workflow(factory, tenant_id=tenant_id)
    await _seed_quota(
        factory,
        tenant_id=tenant_id,
        max_concurrent_runs=1,
        max_concurrent_per_workflow=1,
    )
    # The "winner" — the one slot is consumed.
    await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="running"
    )

    from app.services.quota_service import reserve_slot

    async def _attempt() -> bool:
        async with factory() as session:
            return await reserve_slot(
                session,
                tenant_id=tenant_id,
                workflow_id=wf,
                run_id=uuid4(),
            )

    results = await asyncio.gather(*[_attempt() for _ in range(5)])

    # All 5 concurrent reservations must deny — slot is exhausted.
    assert results.count(True) == 0
    assert results.count(False) == 5

    await engine.dispose()
