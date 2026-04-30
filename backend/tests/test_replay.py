"""Tests for the W10 replay service.

Covers:
  - test_reconstruct_state_from_events
  - test_verify_chain_detects_tampering
  - test_replay_to_specific_event

All tests run against an in-memory SQLite database with tables created via
SQLModel.metadata.create_all. No conftest required (--noconftest compatible).
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
TENANT_UUID = UUID("22222222-2222-2222-2222-222222222222")


# ── In-memory SQLite setup ────────────────────────────────────────────


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables created."""
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


async def _seed_run_with_events(factory) -> UUID:
    """Insert Workflow + WorkflowRun + two hash-chained events; return run.id."""
    from app.models.workflow import Workflow, WorkflowRun
    from app.services import event_service

    async with factory() as session:
        wf = Workflow(
            name="replay-test",
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
            status="running",
            definition_snapshot={"kind": "workflow", "name": "replay-test"},
            tenant_id=TENANT_UUID,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        # Append run.created (sequence=0)
        from app.services.execution_facade import _async_append_event

        await _async_append_event(
            session,
            run.id,
            "run.created",
            payload={"kind": "workflow"},
            tenant_id=TENANT_UUID,
        )
        # Append run.queued (sequence=1)
        await _async_append_event(
            session,
            run.id,
            "run.queued",
            payload={"queued_at": "2026-01-01T00:00:00"},
            tenant_id=TENANT_UUID,
        )
        await session.commit()
        return run.id


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconstruct_state_from_events():
    """Reconstructed state reflects event log transitions."""
    engine, factory = await _make_engine_and_factory()

    run_id = await _seed_run_with_events(factory)

    from app.services.replay_service import reconstruct_state

    async with factory() as session:
        state = await reconstruct_state(session, run_id=run_id)

    assert state["run_id"] == str(run_id)
    assert state["kind"] == "workflow"
    # After run.created + run.queued events, status should be queued.
    assert state["status"] == "queued"
    assert len(state["events_applied"]) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_verify_chain_integrity():
    """verify_event_chain returns True for an untampered chain."""
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run_with_events(factory)

    from app.services.replay_service import verify_event_chain

    async with factory() as session:
        valid = await verify_event_chain(session, run_id=run_id)

    assert valid is True
    await engine.dispose()


@pytest.mark.asyncio
async def test_verify_chain_detects_tampering():
    """verify_event_chain returns False when a hash is mutated."""
    from sqlalchemy import update
    from app.models.workflow import WorkflowRunEvent

    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run_with_events(factory)

    # Tamper: overwrite current_hash of sequence=0 with garbage.
    async with factory() as session:
        stmt = (
            update(WorkflowRunEvent)
            .where(WorkflowRunEvent.run_id == run_id)
            .where(WorkflowRunEvent.sequence == 0)
            .values(current_hash="a" * 64)
        )
        await session.execute(stmt)
        await session.commit()

    from app.services.replay_service import verify_event_chain

    async with factory() as session:
        valid = await verify_event_chain(session, run_id=run_id)

    assert valid is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_replay_to_specific_event():
    """replay_to_event with target_sequence=0 returns state after first event."""
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run_with_events(factory)

    from app.services.replay_service import replay_to_event

    async with factory() as session:
        state = await replay_to_event(
            session, run_id=run_id, target_sequence=0
        )

    # Only run.created applied — status should be "created"
    assert state["status"] == "created"
    assert len(state["events_applied"]) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_compare_replay_no_diff_on_fresh_run():
    """compare_replay returns empty diff for a run with no completed state."""
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run_with_events(factory)

    from app.services.replay_service import compare_replay

    async with factory() as session:
        result = await compare_replay(session, run_id=run_id)

    assert result["chain_valid"] is True
    assert isinstance(result["diff"], dict)
    assert isinstance(result["reconstructed"], dict)
    assert isinstance(result["current"], dict)

    await engine.dispose()


@pytest.mark.asyncio
async def test_reconstruct_state_run_not_found():
    """reconstruct_state raises ValueError for unknown run_id."""
    engine, factory = await _make_engine_and_factory()

    from app.services.replay_service import reconstruct_state

    async with factory() as session:
        with pytest.raises(ValueError, match="not found"):
            await reconstruct_state(session, run_id=uuid4())

    await engine.dispose()
