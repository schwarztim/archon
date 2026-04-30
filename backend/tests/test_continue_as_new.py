"""Tests for the W12 continue-as-new / history compaction service.

Covers:
  - test_continue_as_new_creates_linked_run
  - test_run_chain_traversal
  - test_generation_number_increments

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
TENANT_UUID = UUID("44444444-4444-4444-4444-444444444444")


# ── In-memory SQLite setup ────────────────────────────────────────────


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


async def _seed_workflow_run(factory) -> tuple[UUID, UUID]:
    """Insert Workflow + WorkflowRun; return (workflow_id, run_id)."""
    from app.models.workflow import Workflow, WorkflowRun

    async with factory() as session:
        wf = Workflow(
            name="can-test",
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
            status="completed",
            definition_snapshot={"kind": "workflow", "name": "can-test"},
            tenant_id=TENANT_UUID,
            output_data={"result": "done"},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return wf.id, run.id


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_continue_as_new_creates_linked_run():
    """continue_as_new creates a new WorkflowRun linked by RunChain."""
    engine, factory = await _make_engine_and_factory()
    _, run_id = await _seed_workflow_run(factory)

    from app.services.history_compaction import continue_as_new, get_run_chain

    async with factory() as session:
        child = await continue_as_new(
            session,
            run_id=run_id,
            new_input={"restart": True},
            reason="history_size_threshold",
        )

    assert child.id != run_id
    assert child.trigger_type == "continue_as_new"
    assert child.input_data == {"restart": True}

    # Chain should contain root (gen=0) + child (gen=1) = 2 entries.
    async with factory() as session:
        chain = await get_run_chain(session, run_id=run_id)

    assert len(chain) == 2
    gens = [entry["generation_number"] for entry in chain]
    assert 0 in gens
    assert 1 in gens

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_chain_traversal():
    """get_run_chain returns all entries for a chain ordered by generation."""
    engine, factory = await _make_engine_and_factory()
    _, run_id = await _seed_workflow_run(factory)

    from app.services.history_compaction import continue_as_new, get_run_chain
    from app.models.workflow import WorkflowRun

    # First continuation.
    async with factory() as session:
        child1 = await continue_as_new(
            session,
            run_id=run_id,
            reason="first_rollover",
        )

    # Make child1 complete-ish and continue from it.
    async with factory() as session:
        c1 = await session.get(WorkflowRun, child1.id)
        c1.status = "completed"
        session.add(c1)
        await session.commit()

    async with factory() as session:
        child2 = await continue_as_new(
            session,
            run_id=child1.id,
            reason="second_rollover",
        )

    # Chain accessed from the original run should include all 3 entries.
    async with factory() as session:
        chain = await get_run_chain(session, run_id=run_id)

    assert len(chain) == 3
    gens = [e["generation_number"] for e in chain]
    assert gens == sorted(gens), "chain not ordered by generation_number"
    assert gens[0] == 0  # root
    assert gens[1] == 1  # first child
    assert gens[2] == 2  # second child

    await engine.dispose()


@pytest.mark.asyncio
async def test_generation_number_increments():
    """generation_number in RunChain increments with each continuation."""
    engine, factory = await _make_engine_and_factory()
    _, run_id = await _seed_workflow_run(factory)

    from app.services.history_compaction import continue_as_new, get_run_chain
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        c1 = await continue_as_new(
            session, run_id=run_id, reason="gen1"
        )

    async with factory() as session:
        run = await session.get(WorkflowRun, c1.id)
        run.status = "completed"
        session.add(run)
        await session.commit()

    async with factory() as session:
        c2 = await continue_as_new(
            session, run_id=c1.id, reason="gen2"
        )

    async with factory() as session:
        chain = await get_run_chain(session, run_id=run_id)

    by_gen = {e["generation_number"]: e for e in chain}
    assert by_gen[0]["run_id"] == str(run_id)
    assert by_gen[1]["run_id"] == str(c1.id)
    assert by_gen[2]["run_id"] == str(c2.id)

    # Verify compacted_state carries forward from parent.
    assert by_gen[1]["compacted_state"]["parent_run_id"] == str(run_id)
    assert by_gen[2]["compacted_state"]["parent_run_id"] == str(c1.id)

    await engine.dispose()


@pytest.mark.asyncio
async def test_continue_as_new_run_not_found_raises():
    """continue_as_new raises ValueError for an unknown run_id."""
    engine, factory = await _make_engine_and_factory()

    from app.services.history_compaction import continue_as_new

    async with factory() as session:
        with pytest.raises(ValueError, match="not found"):
            await continue_as_new(
                session,
                run_id=uuid4(),
                reason="should_fail",
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_run_chain_not_in_chain_returns_empty():
    """get_run_chain returns [] for a run not part of any chain."""
    engine, factory = await _make_engine_and_factory()
    _, run_id = await _seed_workflow_run(factory)

    from app.services.history_compaction import get_run_chain

    async with factory() as session:
        chain = await get_run_chain(session, run_id=run_id)

    # Run exists but has no chain entry yet.
    assert chain == []

    await engine.dispose()
