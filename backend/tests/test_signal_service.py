"""Tests for ``app.services.signal_service``.

Verifies the durable signal queue contract used by the dispatcher's
resume path:

    1. send_signal persists with consumed_at NULL
    2. consume_pending_signals atomically marks consumed
    3. consume filters by signal_types
    4. peek does not mark consumed
    5. concurrent consume cannot double-process the same row

Tests use an in-memory aiosqlite engine and create the schema directly
from SQLModel.metadata so they don't depend on alembic chain ordering.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables."""
    # Importing app.models registers every SQLModel subclass on
    # SQLModel.metadata, so create_all materialises the full schema.
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


async def _seed_run(factory) -> "UUID":  # noqa: F821 - forward ref
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


# ---------------------------------------------------------------------------
# Test 1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_signal_persists_with_consumed_at_null():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    async with factory() as session:
        sig = await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id="step-1",
            signal_type="approval.granted",
            payload={"approval_id": "abc"},
        )
        await session.commit()

        assert sig.id is not None
        assert sig.consumed_at is None
        assert sig.signal_type == "approval.granted"
        assert sig.run_id == run_id
        assert sig.step_id == "step-1"
        assert sig.payload == {"approval_id": "abc"}

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_pending_signals_marks_consumed_atomic():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    async with factory() as session:
        await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id="s",
            signal_type="approval.granted",
            payload={},
        )
        await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id="s",
            signal_type="approval.granted",
            payload={"k": "v"},
        )
        await session.commit()

    async with factory() as session:
        consumed = await signal_service.consume_pending_signals(
            session, run_id=run_id
        )
        await session.commit()

    assert len(consumed) == 2
    for sig in consumed:
        assert sig.consumed_at is not None

    # Second consume returns nothing.
    async with factory() as session:
        again = await signal_service.consume_pending_signals(
            session, run_id=run_id
        )
        await session.commit()
    assert again == []

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_filters_by_signal_types():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    async with factory() as session:
        await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id=None,
            signal_type="approval.granted",
            payload={},
        )
        await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id=None,
            signal_type="cancel",
            payload={},
        )
        await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id=None,
            signal_type="input.provided",
            payload={"value": 42},
        )
        await session.commit()

    async with factory() as session:
        # Filter to only the cancel signal.
        consumed = await signal_service.consume_pending_signals(
            session,
            run_id=run_id,
            signal_types=["cancel"],
        )
        await session.commit()
    assert len(consumed) == 1
    assert consumed[0].signal_type == "cancel"

    # Remaining two are still pending.
    async with factory() as session:
        peek = await signal_service.peek_pending_signals(
            session, run_id=run_id
        )
    types = sorted(s.signal_type for s in peek)
    assert types == ["approval.granted", "input.provided"]

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_peek_does_not_mark_consumed():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    async with factory() as session:
        await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id=None,
            signal_type="custom",
            payload={},
        )
        await session.commit()

    async with factory() as session:
        peek = await signal_service.peek_pending_signals(
            session, run_id=run_id
        )
    assert len(peek) == 1
    assert peek[0].consumed_at is None

    # A subsequent consume still finds it.
    async with factory() as session:
        consumed = await signal_service.consume_pending_signals(
            session, run_id=run_id
        )
        await session.commit()
    assert len(consumed) == 1
    assert consumed[0].consumed_at is not None

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_consume_no_double_processing():
    """Two consumers hitting the same run must collectively consume each
    pending signal exactly once.
    """
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    # Seed five signals.
    async with factory() as session:
        for i in range(5):
            await signal_service.send_signal(
                session,
                run_id=run_id,
                step_id=None,
                signal_type="custom",
                payload={"i": i},
            )
        await session.commit()

    async def _consumer():
        async with factory() as session:
            rows = await signal_service.consume_pending_signals(
                session, run_id=run_id
            )
            await session.commit()
            return [str(r.id) for r in rows]

    results = await asyncio.gather(_consumer(), _consumer())
    flat: list[str] = []
    for batch in results:
        flat.extend(batch)
    # No duplicate consumption; total is exactly the number of seeded rows.
    assert len(flat) == 5
    assert len(set(flat)) == 5

    # And nothing remains pending.
    async with factory() as session:
        rest = await signal_service.peek_pending_signals(
            session, run_id=run_id
        )
    assert rest == []

    await engine.dispose()
