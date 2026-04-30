"""Tests for the W1 task-queue substrate.

Covers:
  - Migration creates ``task_queues`` + ``tasks`` with the polling and
    idempotency-unique indexes.
  - Route surface CRUD (create idempotent, list tenant-scoped, pause/resume,
    delete blocked when active tasks).
  - Service helpers (``select_pending_tasks`` ordering + tenant isolation,
    ``claim_task`` atomic CAS, partial unique allows multiple NULL keys).

These tests use an in-memory SQLite engine + ``SQLModel.metadata.create_all``
to mirror the existing ``test_approvals.py`` / ``test_dispatcher_claim.py``
pattern. The migration test uses Alembic's offline upgrade path against a
file-backed SQLite DB so it actually exercises the ``op.create_*`` calls in
``0012_add_task_queue_and_task.py``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
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
    # Imports MUST happen inside the helper so the metadata is populated
    # before ``create_all``. Order matters — workflow_runs is referenced
    # by the tasks FKs, so it has to be importable first.
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )
    from app.models.task_queue import Task, TaskQueue  # noqa: F401

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _seed_run(factory, *, tenant_id: UUID | None = None) -> UUID:
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


async def _seed_queue(
    factory,
    *,
    tenant_id: UUID,
    name: str,
    paused: bool = False,
) -> UUID:
    """Insert a TaskQueue row and return its id."""
    from app.models.task_queue import TaskQueue

    async with factory() as session:
        queue = TaskQueue(
            tenant_id=tenant_id,
            name=name,
            paused=paused,
        )
        session.add(queue)
        await session.commit()
        await session.refresh(queue)
        return queue.id


# ---------------------------------------------------------------------------
# Migration test (Alembic-driven, file-backed SQLite)
# ---------------------------------------------------------------------------


def test_migration_creates_tables(tmp_path):
    """Boot a fresh SQLite DB, run alembic upgrade head, assert schema."""
    db_path = tmp_path / "archon_w1_migration.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    # Run alembic upgrade head against the fresh DB. Use a subprocess so
    # the alembic context doesn't pollute the test runner's metadata.
    import subprocess
    import sys

    backend_dir = Path(__file__).parent.parent
    env = os.environ.copy()
    env["ARCHON_DATABASE_URL"] = db_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic upgrade failed:\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )

    # Verify schema via the synchronous sqlite3 driver — the async engine
    # would need an event loop, and we just want to inspect.
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Tables exist.
    tables = {
        row[0]
        for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "task_queues" in tables
    assert "tasks" in tables

    # Polling and idempotency-unique indexes exist.
    indexes = {
        row[0]
        for row in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='tasks'"
        )
    }
    assert "ix_task_polling" in indexes
    assert "ix_task_idempotency_unique" in indexes

    # The unique index is partial (WHERE idempotency_key IS NOT NULL).
    cur.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='index' AND name='ix_task_idempotency_unique'"
    )
    sql = cur.fetchone()[0]
    assert sql is not None
    assert "WHERE" in sql.upper()
    assert "IDEMPOTENCY_KEY" in sql.upper()

    # uq_taskqueue_tenant_name unique constraint exists.
    cur.execute(
        "SELECT sql FROM sqlite_master "
        "WHERE type='table' AND name='task_queues'"
    )
    table_sql = cur.fetchone()[0]
    assert "uq_taskqueue_tenant_name" in table_sql

    conn.close()


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_pending_tasks_orders_by_priority_then_visible_at():
    """Insert 5 tasks with varied priority/visible_at; verify ordering."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    run_id = await _seed_run(factory, tenant_id=tenant)

    from app.models.task_queue import Task
    from app.services import task_queue_service

    base = datetime(2026, 4, 30, 12, 0, 0)
    # (priority, visible_at_offset_seconds, label)
    plan = [
        (50, 0, "low-old"),
        (200, 100, "high-newest"),
        (200, 0, "high-oldest"),
        (100, 50, "med"),
        (200, 50, "high-mid"),
    ]
    async with factory() as session:
        for priority, offset, label in plan:
            session.add(
                Task(
                    tenant_id=tenant,
                    run_id=run_id,
                    queue_name="default",
                    task_type=label,
                    status="visible",
                    visible_at=base + timedelta(seconds=offset),
                    priority=priority,
                )
            )
        await session.commit()

    # Cutoff is well after all visible_at — every task is eligible.
    cutoff = base + timedelta(hours=1)

    async with factory() as session:
        rows = await task_queue_service.select_pending_tasks(
            session,
            tenant_id=tenant,
            queue_names=["default"],
            limit=10,
            now=cutoff,
        )

    # Expected order: priority DESC, visible_at ASC for ties.
    assert [r.task_type for r in rows] == [
        "high-oldest",
        "high-mid",
        "high-newest",
        "med",
        "low-old",
    ]

    await engine.dispose()


@pytest.mark.asyncio
async def test_select_pending_tasks_skips_other_tenants():
    """Tenant isolation — only the caller's tenant's tasks are returned."""
    engine, factory = await _make_engine_and_factory()
    tenant_a = UUID("00000000-0000-0000-0000-00000000000a")
    tenant_b = UUID("00000000-0000-0000-0000-00000000000b")
    run_a = await _seed_run(factory, tenant_id=tenant_a)
    run_b = await _seed_run(factory, tenant_id=tenant_b)

    from app.models.task_queue import Task
    from app.services import task_queue_service

    now = datetime(2026, 4, 30, 12, 0, 0)
    async with factory() as session:
        for _ in range(3):
            session.add(
                Task(
                    tenant_id=tenant_a,
                    run_id=run_a,
                    queue_name="default",
                    task_type="a",
                    status="visible",
                    visible_at=now,
                )
            )
        for _ in range(3):
            session.add(
                Task(
                    tenant_id=tenant_b,
                    run_id=run_b,
                    queue_name="default",
                    task_type="b",
                    status="visible",
                    visible_at=now,
                )
            )
        await session.commit()

    async with factory() as session:
        rows = await task_queue_service.select_pending_tasks(
            session,
            tenant_id=tenant_a,
            queue_names=["default"],
            limit=10,
            now=now + timedelta(seconds=1),
        )
    assert len(rows) == 3
    assert all(r.task_type == "a" for r in rows)

    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_task_atomic_under_contention():
    """Two concurrent claims on the same task; exactly one wins."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    run_id = await _seed_run(factory, tenant_id=tenant)

    from app.models.task_queue import Task
    from app.services import task_queue_service

    async with factory() as session:
        task = Task(
            tenant_id=tenant,
            run_id=run_id,
            queue_name="default",
            task_type="contend",
            status="visible",
            visible_at=datetime(2026, 4, 30, 12, 0, 0),
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    async def _try_claim(owner: str):
        async with factory() as session:
            claimed = await task_queue_service.claim_task(
                session,
                task_id=task_id,
                lease_owner=owner,
                lease_ttl_seconds=60,
            )
            await session.commit()
            return claimed

    # Run both claims concurrently. Only one should observe a non-None
    # return — SQLite serialises writes, but the conditional UPDATE is
    # the structural guarantee.
    results = await asyncio.gather(
        _try_claim("worker-A"),
        _try_claim("worker-B"),
    )
    winners = [r for r in results if r is not None]
    losers = [r for r in results if r is None]
    assert len(winners) == 1
    assert len(losers) == 1
    assert winners[0].status == "claimed"
    assert winners[0].lease_owner in {"worker-A", "worker-B"}
    assert winners[0].attempts == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_idempotency_partial_unique_allows_null_keys():
    """Two tasks with NULL idempotency_key succeed; same non-null key collides."""
    engine, factory = await _make_engine_and_factory()
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    run_id = await _seed_run(factory, tenant_id=tenant)

    from app.models.task_queue import Task

    # Two NULL-keyed tasks succeed.
    async with factory() as session:
        for _ in range(2):
            session.add(
                Task(
                    tenant_id=tenant,
                    run_id=run_id,
                    queue_name="default",
                    task_type="null-key",
                    status="visible",
                    idempotency_key=None,
                )
            )
        await session.commit()

    # First non-null-keyed insert OK.
    async with factory() as session:
        session.add(
            Task(
                tenant_id=tenant,
                run_id=run_id,
                queue_name="default",
                task_type="key-1",
                status="visible",
                idempotency_key="dedup-key-X",
            )
        )
        await session.commit()

    # Second insert with the SAME (tenant, queue, idempotency_key) collides.
    async with factory() as session:
        session.add(
            Task(
                tenant_id=tenant,
                run_id=run_id,
                queue_name="default",
                task_type="key-1-dup",
                status="visible",
                idempotency_key="dedup-key-X",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()

    await engine.dispose()


# ---------------------------------------------------------------------------
# Route-surface tests (TestClient + dependency overrides)
# ---------------------------------------------------------------------------


def _make_test_client(*, tenant_id: UUID, role: str = "admin"):
    """Build a TestClient with a fresh in-memory engine + auth override.

    Returns (client, engine_dispose_callable). The caller must invoke
    the dispose callable at the end of the test.
    """
    # Import here to avoid touching the heavy app.main imports unless
    # the test actually runs.
    from fastapi.testclient import TestClient

    from app.database import get_session
    from app.interfaces.models.enterprise import AuthenticatedUser
    from app.main import app
    from app.middleware.auth import get_current_user
    from app.models.task_queue import Task, TaskQueue  # noqa: F401
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )
    from app.models import Agent, Execution, User  # noqa: F401

    # Build a function-scoped engine + sessionmaker.
    loop = asyncio.new_event_loop()

    async def _build():
        engine = create_async_engine(SQLITE_URL, echo=False)
        async with engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
            await conn.run_sync(SQLModel.metadata.create_all)
        return engine

    engine = loop.run_until_complete(_build())
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_session():
        async with factory() as session:
            yield session

    async def _override_auth():
        return AuthenticatedUser(
            id=str(uuid4()),
            email="t@example.com",
            tenant_id=str(tenant_id),
            roles=[role],
        )

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_auth

    def _dispose():
        app.dependency_overrides.clear()

        async def _shutdown():
            await engine.dispose()

        loop.run_until_complete(_shutdown())
        loop.close()

    return TestClient(app), _dispose, factory, loop


def test_create_queue_idempotent_on_name():
    """POST same name twice → second returns 409 with existing queue id."""
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    client, dispose, _, _ = _make_test_client(tenant_id=tenant)
    try:
        resp = client.post(
            "/api/v1/task-queues",
            json={"name": "default", "queue_type": "default"},
        )
        assert resp.status_code == 200, resp.text
        first_id = resp.json()["data"]["id"]

        resp2 = client.post(
            "/api/v1/task-queues",
            json={"name": "default", "queue_type": "default"},
        )
        assert resp2.status_code == 409, resp2.text
        body = resp2.json()
        # FastAPI envelopes structured detail at body["detail"].
        detail = body.get("detail", {})
        assert detail.get("code") == "QUEUE_ALREADY_EXISTS"
        assert detail.get("queue_id") == first_id
    finally:
        dispose()


def test_list_queues_tenant_scoped():
    """Two tenants × three queues each — each tenant sees only their three."""
    tenant_a = UUID("00000000-0000-0000-0000-00000000000a")
    tenant_b = UUID("00000000-0000-0000-0000-00000000000b")

    # Tenant A creates three queues. Use 'developer' role so we can't
    # leak across tenants by accident.
    client_a, dispose_a, factory_a, loop_a = _make_test_client(
        tenant_id=tenant_a, role="developer"
    )
    try:
        for n in ("alpha", "beta", "gamma"):
            r = client_a.post("/api/v1/task-queues", json={"name": n})
            assert r.status_code == 200, r.text

        # Seed tenant B's queues directly (separate test client would
        # use a fresh engine; we use the factory hooked into the same
        # override).
        async def _seed_b():
            from app.models.task_queue import TaskQueue

            async with factory_a() as session:
                for n in ("zero", "one", "two"):
                    session.add(TaskQueue(tenant_id=tenant_b, name=n))
                await session.commit()

        loop_a.run_until_complete(_seed_b())

        r = client_a.get("/api/v1/task-queues")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        names = sorted(q["name"] for q in data)
        assert names == ["alpha", "beta", "gamma"]
    finally:
        dispose_a()


def test_pause_resume_changes_paused_flag():
    """Pause then resume — assert the flag flips on each call."""
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    client, dispose, _, _ = _make_test_client(tenant_id=tenant)
    try:
        r = client.post("/api/v1/task-queues", json={"name": "default"})
        assert r.status_code == 200, r.text
        queue_id = r.json()["data"]["id"]

        r = client.post(f"/api/v1/task-queues/{queue_id}/pause")
        assert r.status_code == 200
        assert r.json()["data"]["paused"] is True

        r = client.post(f"/api/v1/task-queues/{queue_id}/resume")
        assert r.status_code == 200
        assert r.json()["data"]["paused"] is False
    finally:
        dispose()


def test_delete_queue_blocked_when_active_tasks_present():
    """Active task referencing the queue → DELETE returns 409."""
    tenant = UUID("00000000-0000-0000-0000-000000000001")
    client, dispose, factory, loop = _make_test_client(tenant_id=tenant)
    try:
        r = client.post("/api/v1/task-queues", json={"name": "default"})
        assert r.status_code == 200, r.text
        queue_id = r.json()["data"]["id"]

        # Insert a Task with status='claimed' — that's an active state.
        async def _seed():
            from app.models.task_queue import Task
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
                    tenant_id=tenant,
                    definition_snapshot={
                        "kind": "workflow",
                        "id": str(wf.id),
                        "steps": [],
                    },
                )
                session.add(run)
                await session.commit()
                await session.refresh(run)

                task = Task(
                    tenant_id=tenant,
                    run_id=run.id,
                    queue_name="default",
                    task_type="t",
                    status="claimed",
                )
                session.add(task)
                await session.commit()

        loop.run_until_complete(_seed())

        r = client.delete(f"/api/v1/task-queues/{queue_id}")
        assert r.status_code == 409, r.text
        detail = r.json().get("detail", {})
        assert detail.get("code") == "QUEUE_HAS_ACTIVE_TASKS"
        assert detail.get("active_task_count") == 1
    finally:
        dispose()
