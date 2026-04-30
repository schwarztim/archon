"""Integration tests for concurrency backpressure (Phase 6 — WS17).

Exercises the quota-aware path through ``run_dispatcher.dispatch_run``
and the worker drain hook (``_dispatch_with_semaphore`` →
``_quota_drain_allows``). Verifies:

    1. The dispatcher skips a throttled tenant — leaves the run in
       ``queued`` status, no claim attempted, no ``run.claimed`` event.
    2. After a slot frees, a previously-throttled run is picked up.
    3. Tenant isolation: tenant A at cap does NOT starve tenant B.
    4. ``archon_quota_throttled_total`` counter increments on a denied
       claim.

All tests use an in-memory SQLite engine and stub the engine itself so
nothing real executes.
"""

from __future__ import annotations

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
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables."""
    from app.models import (  # noqa: F401
        Agent,
        Execution,
        User,
    )
    from app.models.tenancy import TenantQuota  # noqa: F401
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
    """Insert a Tenant row so FK references from TenantQuota succeed."""
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
    max_concurrent_runs: int = 1,
    max_concurrent_per_workflow: int = 1,
):
    from app.models.tenancy import TenantQuota

    await _seed_tenant(factory, tenant_id)
    async with factory() as session:
        q = TenantQuota(
            tenant_id=tenant_id,
            max_concurrent_runs=max_concurrent_runs,
            max_concurrent_per_workflow=max_concurrent_per_workflow,
        )
        session.add(q)
        await session.commit()


async def _seed_workflow(factory, *, tenant_id):
    from app.models.workflow import Workflow

    async with factory() as session:
        wf = Workflow(
            name="bp-wf",
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
    status: str = "queued",
):
    """Insert a WorkflowRun directly. Returns its id."""
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
                "name": "bp-wf",
                "steps": [],
                "graph_definition": {},
            },
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


async def _get_run(factory, run_id):
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        return await session.get(WorkflowRun, run_id)


# ---------------------------------------------------------------------------
# Test 1: dispatcher skips a throttled tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatcher_skips_throttled_tenant(monkeypatch):
    """At-cap tenant: dispatch_run returns None, no claim, no events."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    tenant_id = uuid4()
    wf = await _seed_workflow(factory, tenant_id=tenant_id)
    await _seed_quota(
        factory,
        tenant_id=tenant_id,
        max_concurrent_runs=1,
        max_concurrent_per_workflow=1,
    )

    # Saturate the cap with 1 running row.
    await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="running"
    )

    # Now queue a fresh run — it must be denied.
    queued_id = await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="queued"
    )

    # Engine MUST NOT run for a throttled dispatch.
    engine_calls = {"count": 0}

    async def _engine_should_not_run(*a, **kw):
        engine_calls["count"] += 1
        return {"status": "completed", "duration_ms": 0, "steps": []}

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _engine_should_not_run,
    )

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(queued_id, worker_id="bp-worker")

    assert result is None
    assert engine_calls["count"] == 0

    # Run still queued, no claim recorded.
    refreshed = await _get_run(factory, queued_id)
    assert refreshed.status == "queued"
    assert refreshed.lease_owner is None
    assert refreshed.attempt == 0

    # No events on the throttled row.
    from sqlalchemy import select
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent).where(
                    WorkflowRunEvent.run_id == queued_id
                )
            )
        ).scalars().all()
    assert events == []

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: throttled run remains queued; later dispatch succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_throttled_run_remains_queued(monkeypatch):
    """Once the in-flight run completes, the previously-throttled run drains."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    tenant_id = uuid4()
    wf = await _seed_workflow(factory, tenant_id=tenant_id)
    await _seed_quota(
        factory,
        tenant_id=tenant_id,
        max_concurrent_runs=1,
        max_concurrent_per_workflow=1,
    )

    busy_id = await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="running"
    )
    queued_id = await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="queued"
    )

    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "completed",
            "duration_ms": 1,
            "steps": [],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    from app.services.run_dispatcher import dispatch_run

    # First attempt — denied (cap reached).
    first = await dispatch_run(queued_id, worker_id="bp-worker-1")
    assert first is None

    refreshed = await _get_run(factory, queued_id)
    assert refreshed.status == "queued"

    # Free the slot — finalise the busy run.
    from app.models.workflow import WorkflowRun
    from datetime import datetime

    async with factory() as session:
        busy = await session.get(WorkflowRun, busy_id)
        busy.status = "completed"
        busy.completed_at = datetime.utcnow()
        session.add(busy)
        await session.commit()

    # Second attempt — should now succeed.
    second = await dispatch_run(queued_id, worker_id="bp-worker-2")
    assert second is not None
    assert second.status == "completed"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: tenant A at cap does not starve tenant B
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_tenant_isolation_does_not_starve(monkeypatch):
    """Tenant A maxed out → tenant B's runs still drain unaffected."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    tenant_a = uuid4()
    tenant_b = uuid4()
    wf_a = await _seed_workflow(factory, tenant_id=tenant_a)
    wf_b = await _seed_workflow(factory, tenant_id=tenant_b)
    await _seed_quota(
        factory,
        tenant_id=tenant_a,
        max_concurrent_runs=1,
        max_concurrent_per_workflow=1,
    )
    await _seed_quota(
        factory,
        tenant_id=tenant_b,
        max_concurrent_runs=10,
        max_concurrent_per_workflow=10,
    )

    # Saturate tenant A.
    await _seed_run(
        factory, tenant_id=tenant_a, workflow_id=wf_a, status="running"
    )
    a_queued = await _seed_run(
        factory, tenant_id=tenant_a, workflow_id=wf_a, status="queued"
    )

    # Tenant B has no in-flight; queue one.
    b_queued = await _seed_run(
        factory, tenant_id=tenant_b, workflow_id=wf_b, status="queued"
    )

    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "completed",
            "duration_ms": 1,
            "steps": [],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    from app.services.run_dispatcher import dispatch_run

    # Tenant A's queued run should be throttled.
    a_result = await dispatch_run(a_queued, worker_id="iso-a")
    assert a_result is None

    # Tenant B's queued run should drain.
    b_result = await dispatch_run(b_queued, worker_id="iso-b")
    assert b_result is not None
    assert b_result.status == "completed"

    # Tenant A's run is still queued — not starved by tenant B's success.
    a_refreshed = await _get_run(factory, a_queued)
    assert a_refreshed.status == "queued"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: archon_quota_throttled_total increments on denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quota_metric_emitted(monkeypatch):
    """A throttled dispatch must increment the quota-throttle counter."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    tenant_id = uuid4()
    wf = await _seed_workflow(factory, tenant_id=tenant_id)
    await _seed_quota(
        factory,
        tenant_id=tenant_id,
        max_concurrent_runs=1,
        max_concurrent_per_workflow=1,
    )
    await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="running"
    )
    queued_id = await _seed_run(
        factory, tenant_id=tenant_id, workflow_id=wf, status="queued"
    )

    from app.services import run_dispatcher

    # Capture the pre-call counter so we can assert a delta even if
    # other tests in the same session bumped it earlier.
    before = run_dispatcher._get_quota_throttled_count(
        tenant_id=str(tenant_id), workflow_id=str(wf)
    )

    result = await run_dispatcher.dispatch_run(queued_id, worker_id="metric-w")
    assert result is None

    after = run_dispatcher._get_quota_throttled_count(
        tenant_id=str(tenant_id), workflow_id=str(wf)
    )
    assert after == before + 1

    await engine.dispose()
