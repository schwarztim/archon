"""Tests for approval_service + approvals route surface.

Covers:
  - request_approval creates a pending row, sets run.status='paused',
    and emits a run.paused event in the chain.
  - grant_approval emits approval.granted signal + run.resumed event.
  - reject_approval emits approval.rejected signal; run remains paused.
  - expire_pending_approvals transitions stale rows.
  - Route handlers respect tenant scoping and return the expected envelope.
  - human_approval node executor returns paused + creates an Approval row.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Schema fixture
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables."""
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.approval import Approval, Signal  # noqa: F401
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


async def _seed_run(factory, *, tenant_id: UUID | None = None) -> UUID:
    """Insert a Workflow + WorkflowRun and return run_id."""
    from app.models.workflow import Workflow, WorkflowRun

    async with factory() as session:
        wf = Workflow(name="t-wf", steps=[], graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            kind="workflow",
            status="running",
            tenant_id=tenant_id,
            definition_snapshot={
                "kind": "workflow",
                "id": str(wf.id),
                "steps": [],
            },
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


async def _events_for(factory, run_id: UUID):
    """Return the ordered event_type list for a run."""
    from app.models.workflow import WorkflowRunEvent
    from sqlmodel import select

    async with factory() as session:
        result = await session.execute(
            select(WorkflowRunEvent)
            .where(WorkflowRunEvent.run_id == run_id)
            .order_by(WorkflowRunEvent.sequence.asc())
        )
        rows = list(result.scalars().all())
    return [r.event_type for r in rows]


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_approval_creates_pending_row_and_emits_run_paused_event():
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000123")
    run_id = await _seed_run(factory, tenant_id=tenant)

    from app.models.approval import Approval
    from app.models.workflow import WorkflowRun
    from app.services import approval_service

    async with factory() as session:
        approval = await approval_service.request_approval(
            session,
            run_id=run_id,
            step_id="step-7",
            tenant_id=tenant,
            payload={"prompt": "go?"},
            expires_in_seconds=3600,
        )
        await session.commit()

    assert approval.status == "pending"
    assert approval.run_id == run_id
    assert approval.tenant_id == tenant
    assert approval.payload == {"prompt": "go?"}
    assert approval.expires_at is not None

    # Run flipped to paused.
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.status == "paused"
    assert run.paused_at is not None

    # Approval row materialised.
    async with factory() as session:
        row = await session.get(Approval, approval.id)
    assert row is not None
    assert row.status == "pending"

    # run.paused event in chain.
    types = await _events_for(factory, run_id)
    assert "run.paused" in types

    await engine.dispose()


@pytest.mark.asyncio
async def test_grant_approval_creates_signal_and_emits_run_resumed_event():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.models.approval import Signal
    from app.models.workflow import WorkflowRun
    from app.services import approval_service

    async with factory() as session:
        approval = await approval_service.request_approval(
            session,
            run_id=run_id,
            step_id="s",
            tenant_id=None,
            payload={},
        )
        await session.commit()

    async with factory() as session:
        granted, sig = await approval_service.grant_approval(
            session,
            approval_id=approval.id,
            approver_id=None,
            reason="ok",
        )
        await session.commit()

    assert granted.status == "approved"
    assert granted.decision_reason == "ok"
    assert granted.decided_at is not None
    assert sig.signal_type == "approval.granted"
    assert sig.payload["approval_id"] == str(approval.id)

    # Signal row exists.
    async with factory() as session:
        sig_row = await session.get(Signal, sig.id)
    assert sig_row is not None

    # Run resumed.
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
    assert run.status == "running"
    assert run.resumed_at is not None

    # Both run.paused and run.resumed in chain.
    types = await _events_for(factory, run_id)
    assert "run.paused" in types
    assert "run.resumed" in types

    await engine.dispose()


@pytest.mark.asyncio
async def test_reject_approval_creates_signal_run_remains_paused():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.models.workflow import WorkflowRun
    from app.services import approval_service

    async with factory() as session:
        approval = await approval_service.request_approval(
            session,
            run_id=run_id,
            step_id="s",
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
    # Run still paused — dispatcher (W2.4) decides on resume.
    assert run.status == "paused"
    assert run.resumed_at is None

    types = await _events_for(factory, run_id)
    assert "run.paused" in types
    assert "run.resumed" not in types

    await engine.dispose()


@pytest.mark.asyncio
async def test_expire_pending_approvals_transitions_to_expired():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.models.approval import Approval, Signal
    from app.services import approval_service
    from sqlmodel import select

    # Insert an approval whose expires_at is already in the past.
    past = datetime.utcnow() - timedelta(seconds=60)
    async with factory() as session:
        approval = Approval(
            run_id=run_id,
            step_id="s",
            tenant_id=None,
            status="pending",
            requested_at=past - timedelta(seconds=1),
            expires_at=past,
            payload={},
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)

    async with factory() as session:
        n = await approval_service.expire_pending_approvals(session)
        await session.commit()
    assert n == 1

    async with factory() as session:
        row = await session.get(Approval, approval.id)
    assert row.status == "expired"
    assert row.decided_at is not None

    # An approval.expired signal was written.
    async with factory() as session:
        result = await session.execute(
            select(Signal).where(Signal.signal_type == "approval.expired")
        )
        sigs = list(result.scalars().all())
    assert len(sigs) == 1
    assert sigs[0].run_id == run_id

    await engine.dispose()


# ---------------------------------------------------------------------------
# Node executor test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_node_returns_paused_status_and_creates_approval():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.models.approval import Approval
    from app.services.node_executors import NodeContext
    from app.services.node_executors.human_approval import (
        HumanApprovalNodeExecutor,
    )
    from sqlmodel import select

    executor = HumanApprovalNodeExecutor()

    async with factory() as session:
        ctx = NodeContext(
            step_id="approve-step",
            node_type="humanApprovalNode",
            node_data={
                "config": {
                    "prompt": "ship it?",
                    "timeoutHours": 1,
                    "approvers": ["op@x"],
                },
                "run_id": str(run_id),
            },
            inputs={},
            tenant_id=None,
            secrets=None,
            db_session=session,
        )
        result = await executor.execute(ctx)
        await session.commit()

    assert result.status == "paused"
    assert result.paused_reason == "awaiting_human_approval"
    assert "approval_id" in result.output
    assert result.output["_hint"]["kind"] == "approval_required"
    assert result.output["_hint"]["step_id"] == "approve-step"

    # The corresponding Approval row exists.
    async with factory() as session:
        result_rows = await session.execute(
            select(Approval).where(Approval.run_id == run_id)
        )
        rows = list(result_rows.scalars().all())
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].step_id == "approve-step"

    await engine.dispose()


# ---------------------------------------------------------------------------
# REST surface tests
# ---------------------------------------------------------------------------


def _build_test_client(factory):
    """Wire the FastAPI app to use the supplied session factory + a stub user.

    Returns (TestClient, [stub_user]) so tests can mutate the user fixture
    in place to switch tenants between requests.
    """
    from app.database import get_session
    from app.interfaces.models.enterprise import AuthenticatedUser
    from app.main import app
    from app.middleware.auth import get_current_user

    stub = {
        "user": AuthenticatedUser(
            id="00000000-0000-0000-0000-000000000001",
            email="admin@archon.local",
            tenant_id="00000000-0000-0000-0000-000000000123",
            roles=["admin", "operator"],
            permissions=["*"],
            mfa_verified=True,
            session_id="t",
        )
    }

    async def _override_session():
        async with factory() as session:
            yield session

    async def _override_user():
        return stub["user"]

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app), stub


@pytest.mark.asyncio
async def test_route_approve_returns_200_with_signal_id():
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000123")
    run_id = await _seed_run(factory, tenant_id=tenant)

    from app.services import approval_service

    async with factory() as session:
        approval = await approval_service.request_approval(
            session,
            run_id=run_id,
            step_id="s",
            tenant_id=tenant,
            payload={},
        )
        await session.commit()

    client, _ = _build_test_client(factory)
    try:
        resp = client.post(
            f"/api/v1/approvals/{approval.id}/approve",
            json={"reason": "looks good"},
        )
    finally:
        from app.main import app

        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["approval"]["status"] == "approved"
    assert body["data"]["signal_id"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_route_reject_returns_200():
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000123")
    run_id = await _seed_run(factory, tenant_id=tenant)

    from app.services import approval_service

    async with factory() as session:
        approval = await approval_service.request_approval(
            session,
            run_id=run_id,
            step_id="s",
            tenant_id=tenant,
            payload={},
        )
        await session.commit()

    client, _ = _build_test_client(factory)
    try:
        resp = client.post(
            f"/api/v1/approvals/{approval.id}/reject",
            json={"reason": "nope"},
        )
    finally:
        from app.main import app

        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert resp.json()["data"]["approval"]["status"] == "rejected"

    await engine.dispose()


@pytest.mark.asyncio
async def test_route_list_pending_tenant_scoped():
    engine, factory = await _make_engine_and_factory()
    tenant_a = UUID("00000000-0000-0000-0000-0000000000aa")
    tenant_b = UUID("00000000-0000-0000-0000-0000000000bb")
    run_a = await _seed_run(factory, tenant_id=tenant_a)
    run_b = await _seed_run(factory, tenant_id=tenant_b)

    from app.services import approval_service

    async with factory() as session:
        await approval_service.request_approval(
            session,
            run_id=run_a,
            step_id="s",
            tenant_id=tenant_a,
            payload={"who": "a"},
        )
        await approval_service.request_approval(
            session,
            run_id=run_b,
            step_id="s",
            tenant_id=tenant_b,
            payload={"who": "b"},
        )
        await session.commit()

    # Build a non-admin operator scoped to tenant_a.
    from app.database import get_session
    from app.interfaces.models.enterprise import AuthenticatedUser
    from app.main import app
    from app.middleware.auth import get_current_user

    async def _override_session():
        async with factory() as session:
            yield session

    async def _override_user_tenant_a():
        return AuthenticatedUser(
            id="00000000-0000-0000-0000-000000000001",
            email="op@a",
            tenant_id=str(tenant_a),
            roles=["operator"],
            permissions=[],
            mfa_verified=True,
            session_id="t",
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user_tenant_a
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/approvals?status=pending")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    rows = resp.json()["data"]
    assert len(rows) == 1
    assert rows[0]["tenant_id"] == str(tenant_a)
    assert rows[0]["payload"]["who"] == "a"

    await engine.dispose()


@pytest.mark.asyncio
async def test_route_404_for_other_tenant():
    engine, factory = await _make_engine_and_factory()
    tenant_a = UUID("00000000-0000-0000-0000-0000000000aa")
    tenant_b = UUID("00000000-0000-0000-0000-0000000000bb")
    run_b = await _seed_run(factory, tenant_id=tenant_b)

    from app.services import approval_service

    async with factory() as session:
        approval = await approval_service.request_approval(
            session,
            run_id=run_b,
            step_id="s",
            tenant_id=tenant_b,
            payload={},
        )
        await session.commit()

    # Caller is in tenant_a — must get 404 for tenant_b's approval.
    from app.database import get_session
    from app.interfaces.models.enterprise import AuthenticatedUser
    from app.main import app
    from app.middleware.auth import get_current_user

    async def _override_session():
        async with factory() as session:
            yield session

    async def _override_user_tenant_a():
        return AuthenticatedUser(
            id="00000000-0000-0000-0000-000000000099",
            email="op@a",
            tenant_id=str(tenant_a),
            roles=["operator"],
            permissions=[],
            mfa_verified=True,
            session_id="t",
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user_tenant_a
    try:
        client = TestClient(app)
        resp_get = client.get(f"/api/v1/approvals/{approval.id}")
        resp_approve = client.post(
            f"/api/v1/approvals/{approval.id}/approve",
            json={"reason": "x"},
        )
        resp_reject = client.post(
            f"/api/v1/approvals/{approval.id}/reject",
            json={"reason": "x"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp_get.status_code == 404
    assert resp_approve.status_code == 404
    assert resp_reject.status_code == 404

    await engine.dispose()
