"""Tests for the W11 workflow definition versioning service.

Covers:
  - test_snapshot_creates_version
  - test_version_number_increments
  - test_deprecate_version
  - test_check_compatibility_empty_set_allows_all
  - test_check_compatibility_with_set
  - test_list_versions_ordered
  - test_get_version_not_found_raises

All tests run against an in-memory SQLite database. --noconftest compatible.
"""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"
TENANT_UUID = UUID("33333333-3333-3333-3333-333333333333")


async def _make_engine_and_factory():
    from app.models import (  # noqa: F401
        Agent,
        Execution,
        RunChain,
        User,
        WorkflowDefinitionVersion,
    )
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )
    from app.models.task_queue import Task, TaskQueue  # noqa: F401

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = OFF")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _seed_workflow(factory) -> UUID:
    """Insert a minimal Workflow; return its id."""
    from app.models.workflow import Workflow

    async with factory() as session:
        wf = Workflow(
            name="ver-test",
            steps=[{"id": "step1", "type": "llmNode"}],
            graph_definition={"nodes": ["step1"]},
            tenant_id=TENANT_UUID,
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_creates_version():
    """snapshot_definition creates a WorkflowDefinitionVersion row."""
    engine, factory = await _make_engine_and_factory()
    workflow_id = await _seed_workflow(factory)

    from app.services.workflow_versioning_service import snapshot_definition

    async with factory() as session:
        version = await snapshot_definition(
            session,
            workflow_id=workflow_id,
            changelog="initial snapshot",
            created_by="tester",
        )

    assert version.id is not None
    assert version.workflow_id == workflow_id
    assert version.version_number == 1
    assert version.changelog == "initial snapshot"
    assert version.deprecated_at is None
    assert "steps" in version.schema_snapshot
    await engine.dispose()


@pytest.mark.asyncio
async def test_version_number_increments():
    """Successive snapshots get monotonically increasing version_numbers."""
    engine, factory = await _make_engine_and_factory()
    workflow_id = await _seed_workflow(factory)

    from app.services.workflow_versioning_service import snapshot_definition

    async with factory() as session:
        v1 = await snapshot_definition(session, workflow_id=workflow_id)
    async with factory() as session:
        v2 = await snapshot_definition(session, workflow_id=workflow_id)
    async with factory() as session:
        v3 = await snapshot_definition(session, workflow_id=workflow_id)

    assert v1.version_number == 1
    assert v2.version_number == 2
    assert v3.version_number == 3
    await engine.dispose()


@pytest.mark.asyncio
async def test_deprecate_version():
    """deprecate_version sets deprecated_at; idempotent on second call."""
    engine, factory = await _make_engine_and_factory()
    workflow_id = await _seed_workflow(factory)

    from app.services.workflow_versioning_service import (
        deprecate_version,
        get_version,
        snapshot_definition,
    )

    async with factory() as session:
        v1 = await snapshot_definition(session, workflow_id=workflow_id)

    async with factory() as session:
        await deprecate_version(
            session, workflow_id=workflow_id, version=v1.version_number
        )

    async with factory() as session:
        fetched = await get_version(
            session, workflow_id=workflow_id, version=1
        )

    assert fetched.deprecated_at is not None

    # Second deprecation is a no-op (idempotent).
    async with factory() as session:
        await deprecate_version(
            session, workflow_id=workflow_id, version=v1.version_number
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_check_compatibility_empty_set_allows_all():
    """An empty compatibility_set accepts any worker_version."""
    engine, factory = await _make_engine_and_factory()
    workflow_id = await _seed_workflow(factory)

    from app.services.workflow_versioning_service import (
        check_compatibility,
        snapshot_definition,
    )

    async with factory() as session:
        v = await snapshot_definition(
            session, workflow_id=workflow_id, compatibility_set=[]
        )

    async with factory() as session:
        compat = await check_compatibility(
            session,
            worker_version="v1.2.3",
            definition_version_id=v.id,
        )

    assert compat is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_check_compatibility_with_set():
    """A non-empty compatibility_set filters by worker_version."""
    engine, factory = await _make_engine_and_factory()
    workflow_id = await _seed_workflow(factory)

    from app.services.workflow_versioning_service import (
        check_compatibility,
        snapshot_definition,
    )

    async with factory() as session:
        v = await snapshot_definition(
            session,
            workflow_id=workflow_id,
            compatibility_set=["v1", "v2"],
        )

    async with factory() as session:
        assert (
            await check_compatibility(
                session, worker_version="v1", definition_version_id=v.id
            )
            is True
        )
        assert (
            await check_compatibility(
                session, worker_version="v3", definition_version_id=v.id
            )
            is False
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_versions_ordered():
    """list_versions returns versions ordered by version_number ascending."""
    engine, factory = await _make_engine_and_factory()
    workflow_id = await _seed_workflow(factory)

    from app.services.workflow_versioning_service import (
        list_versions,
        snapshot_definition,
    )

    for _ in range(3):
        async with factory() as session:
            await snapshot_definition(session, workflow_id=workflow_id)

    async with factory() as session:
        versions = await list_versions(session, workflow_id=workflow_id)

    nums = [v.version_number for v in versions]
    assert nums == sorted(nums)
    assert nums == [1, 2, 3]
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_version_not_found_raises():
    """get_version raises ValueError for an unknown version_number."""
    engine, factory = await _make_engine_and_factory()
    workflow_id = await _seed_workflow(factory)

    from app.services.workflow_versioning_service import get_version

    async with factory() as session:
        with pytest.raises(ValueError, match="not found"):
            await get_version(session, workflow_id=workflow_id, version=99)

    await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_workflow_not_found_raises():
    """snapshot_definition raises ValueError for an unknown workflow_id."""
    engine, factory = await _make_engine_and_factory()

    from app.services.workflow_versioning_service import snapshot_definition

    async with factory() as session:
        with pytest.raises(ValueError, match="not found"):
            await snapshot_definition(session, workflow_id=uuid4())

    await engine.dispose()
