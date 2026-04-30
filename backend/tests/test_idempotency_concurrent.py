"""Concurrency hardening for ExecutionFacade.create_run + idempotency.

W2.4 / Phase 2 of master plan. Validates that concurrent ``create_run``
calls with the same idempotency key converge to a single workflow_runs
row (the partial unique index serialises the race; the loser sees
IntegrityError and rebinds to the winner per ADR-004 §Behaviour).

Tests:
  - test_concurrent_post_same_key_results_in_single_run
  - test_concurrent_post_different_keys_create_distinct_runs
"""

from __future__ import annotations

import asyncio
import os
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
os.environ.setdefault(
    "ARCHON_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t"
)
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def engine_and_factory(tmp_path):
    """File-backed SQLite engine shared across concurrent sessions.

    A file-backed database is required for genuine concurrency: each
    session opens its own connection in its own greenlet, and SQLite
    serialises the writes via the file lock. With ``:memory:`` and the
    default pool every session gets a separate database; with
    ``:memory:`` + StaticPool sessions share a single connection that
    can't sustain concurrent transactions.

    The on-disk file is auto-cleaned via tmp_path.
    """
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )

    db_path = tmp_path / "concurrent.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


@pytest_asyncio.fixture()
async def seeded_workflow(engine_and_factory):
    """Seed a single Workflow row used by all create_run calls."""
    from app.models.workflow import Workflow

    _, factory = engine_and_factory
    wf_id = uuid4()
    async with factory() as session:
        wf = Workflow(
            id=wf_id,
            name="concurrent-wf",
            description="",
            steps=[{"name": "s", "config": {"type": "inputNode"}, "depends_on": []}],
            graph_definition={"nodes": [], "edges": []},
            is_active=True,
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
    return wf_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_run(factory, *, workflow_id, tenant_id, key, payload):
    """Open a fresh session per call to simulate independent requests."""
    from app.services.execution_facade import ExecutionFacade

    async with factory() as session:
        run, is_new = await ExecutionFacade.create_run(
            session,
            kind="workflow",
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            input_data=payload,
            idempotency_key=key,
        )
        return run, is_new


# ---------------------------------------------------------------------------
# Test 1: concurrent same-key collapses to a single row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_post_same_key_results_in_single_run(
    engine_and_factory, seeded_workflow
):
    """5 simultaneous calls with the same key produce exactly 1 workflow_runs row."""
    _, factory = engine_and_factory
    tenant_id = uuid4()
    key = "concurrent-key-1"
    payload = {"x": 42}

    coros = [
        _create_run(
            factory,
            workflow_id=seeded_workflow,
            tenant_id=tenant_id,
            key=key,
            payload=payload,
        )
        for _ in range(5)
    ]

    results = await asyncio.gather(*coros, return_exceptions=True)

    # No exception raised — all five calls succeeded (some via replay).
    for r in results:
        if isinstance(r, BaseException):
            raise r

    runs = [r[0] for r in results]
    is_new_flags = [r[1] for r in results]

    # All five returned the same run id.
    run_ids = {run.id for run in runs}
    assert len(run_ids) == 1, (
        f"expected exactly one run id across 5 concurrent calls, got "
        f"{len(run_ids)} unique ids: {run_ids}"
    )

    # Exactly one is_new=True; the other four are is_new=False (replay).
    assert sum(is_new_flags) == 1
    assert is_new_flags.count(False) == 4

    # Database state confirms exactly one row.
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        rows = (
            await session.execute(
                select(WorkflowRun).where(
                    WorkflowRun.tenant_id == tenant_id,
                    WorkflowRun.idempotency_key == key,
                )
            )
        ).scalars().all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Test 2: concurrent different keys produce distinct rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_post_different_keys_create_distinct_runs(
    engine_and_factory, seeded_workflow
):
    """5 simultaneous calls with different keys produce 5 distinct workflow_runs rows."""
    _, factory = engine_and_factory
    tenant_id = uuid4()
    payload = {"y": 1}

    coros = [
        _create_run(
            factory,
            workflow_id=seeded_workflow,
            tenant_id=tenant_id,
            key=f"distinct-key-{i}",
            payload=payload,
        )
        for i in range(5)
    ]

    results = await asyncio.gather(*coros)
    runs = [r[0] for r in results]
    is_new_flags = [r[1] for r in results]

    run_ids = {run.id for run in runs}
    assert len(run_ids) == 5
    assert all(is_new_flags) is True

    from app.models.workflow import WorkflowRun

    async with factory() as session:
        rows = (
            await session.execute(
                select(WorkflowRun).where(
                    WorkflowRun.tenant_id == tenant_id,
                )
            )
        ).scalars().all()
    assert len(rows) == 5
    assert {r.idempotency_key for r in rows} == {
        f"distinct-key-{i}" for i in range(5)
    }
