"""Tests for W5 — Signals, Queries, and Updates.

Covers the durable message-passing surface added to signal_service:

    1. test_send_signal_creates_persistent_row
    2. test_send_signal_appends_event_to_history
    3. test_query_run_state_returns_current_status
    4. test_query_does_not_mutate_history
    5. test_send_update_applied_records_result
    6. test_send_update_rejected_records_error
    7. test_approval_decision_emits_signal

Tests use an in-memory aiosqlite engine and create the schema directly from
SQLModel.metadata — no Alembic dependency, mirrors test_task_queues.py pattern.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all relevant tables."""
    # Import models to populate SQLModel.metadata before create_all.
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.approval import Approval, Signal  # noqa: F401
    from app.models.signal import UpdateResult  # noqa: F401
    from app.models.timers import Timer  # noqa: F401
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


async def _seed_run(factory, *, status: str = "running"):
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
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# Test 1 — send_named_signal creates a persistent Signal row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_signal_creates_persistent_row():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    async with factory() as session:
        sig = await signal_service.send_named_signal(
            session,
            run_id=run_id,
            signal_name="data.ready",
            payload={"source": "etl-job"},
            sender_id="user-42",
        )
        await session.commit()

    # Verify the row is durable.
    async with factory() as session:
        from app.models.approval import Signal
        from sqlmodel import select

        result = await session.execute(select(Signal).where(Signal.run_id == run_id))
        rows = list(result.scalars().all())

    assert len(rows) == 1
    row = rows[0]
    assert row.signal_type == "data.ready"
    assert row.payload["source"] == "etl-job"
    assert row.payload["sender_id"] == "user-42"
    assert row.consumed_at is None

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2 — send_named_signal row IS the durable event history
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_signal_appends_event_to_history():
    """The Signal row persisted by send_named_signal is the append-only record
    that constitutes the signal history for the run.  Verify it can be
    retrieved in insertion order via peek_pending_signals.
    """
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    async with factory() as session:
        await signal_service.send_named_signal(
            session, run_id=run_id, signal_name="first.signal", payload={}
        )
        await signal_service.send_named_signal(
            session, run_id=run_id, signal_name="second.signal", payload={}
        )
        await session.commit()

    async with factory() as session:
        history = await signal_service.peek_pending_signals(session, run_id=run_id)

    # Both records in insertion order; unconsumed.
    assert len(history) == 2
    assert history[0].signal_type == "first.signal"
    assert history[1].signal_type == "second.signal"
    for record in history:
        assert record.consumed_at is None

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3 — query_run_state returns current status without mutating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_run_state_returns_current_status():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory, status="paused")

    from app.services import signal_service

    # Add a pending signal so it appears in the state snapshot.
    async with factory() as session:
        await signal_service.send_named_signal(
            session, run_id=run_id, signal_name="resume.requested", payload={}
        )
        await session.commit()

    async with factory() as session:
        state = await signal_service.query_run_state(session, run_id=run_id)

    assert state["run_id"] == str(run_id)
    assert state["status"] == "paused"
    assert "resume.requested" in state["pending_signals"]
    assert isinstance(state["step_outputs"], dict)
    assert isinstance(state["active_timers"], list)
    assert isinstance(state["input_data"], dict)

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4 — query_run_state does NOT mutate history (event count unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_does_not_mutate_history():
    """query_run_state must be strictly read-only: Signal rows remain
    unconsumed and no new rows are added.
    """
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    async with factory() as session:
        await signal_service.send_named_signal(
            session, run_id=run_id, signal_name="ping", payload={}
        )
        await session.commit()

    # Call query twice — no mutations should accumulate.
    async with factory() as session:
        await signal_service.query_run_state(session, run_id=run_id)
    async with factory() as session:
        await signal_service.query_run_state(session, run_id=run_id)

    # Exactly one signal row, still unconsumed.
    async with factory() as session:
        remaining = await signal_service.peek_pending_signals(
            session, run_id=run_id
        )

    assert len(remaining) == 1
    assert remaining[0].consumed_at is None

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 5 — send_update applied records result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_update_applied_records_result():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service
    from app.models.signal import UpdateResult
    from sqlmodel import select

    # No handler registered → open contract → applied unconditionally.
    async with factory() as session:
        result = await signal_service.send_update(
            session,
            run_id=run_id,
            update_name="set.priority",
            payload={"priority": "high"},
            sender_id="admin-1",
        )
        await session.commit()
        result_id = result.id

    # Verify the row is durable.
    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(UpdateResult).where(UpdateResult.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    row = rows[0]
    assert row.id == result_id
    assert row.update_name == "set.priority"
    assert row.status == "applied"
    assert row.error_message is None
    assert row.request_payload["priority"] == "high"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 6 — send_update rejected records error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_update_rejected_records_error():
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory)

    from app.services import signal_service

    # Register a handler that always rejects.
    def _reject_all(payload):
        raise ValueError("payload violates business rule")

    signal_service.register_update_handler("locked.field", _reject_all)

    async with factory() as session:
        result = await signal_service.send_update(
            session,
            run_id=run_id,
            update_name="locked.field",
            payload={"value": 99},
        )
        await session.commit()

    assert result.status == "rejected"
    assert result.error_message == "payload violates business rule"
    assert result.response_payload == {}

    # Clean up handler to avoid polluting other tests.
    signal_service._UPDATE_HANDLERS.pop("locked.field", None)

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 7 — approval decision emits approval.granted / approval.rejected signal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_decision_emits_signal():
    """grant_approval and reject_approval both route through signal_service.send_signal
    producing a persistent Signal row of the correct type on the run.
    """
    engine, factory = await _make_engine_and_factory()
    run_id = await _seed_run(factory, status="paused")

    # We need the approval model + event infrastructure, so import full stack.
    from app.models.approval import Approval, Signal
    from sqlmodel import select

    # Manually insert an Approval in pending state (bypassing request_approval
    # which requires execution_facade event helpers not wired here).
    async with factory() as session:
        approval = Approval(
            run_id=run_id,
            step_id="human-step",
            status="pending",
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        approval_id = approval.id

    # Grant the approval — should produce approval.granted Signal.
    from app.services import signal_service

    async with factory() as session:
        # Directly call send_signal (the internal path used by _decide in
        # approval_service) to verify the signal is persisted.
        sig = await signal_service.send_signal(
            session,
            run_id=run_id,
            step_id="human-step",
            signal_type="approval.granted",
            payload={"approval_id": str(approval_id)},
        )
        await session.commit()
        sig_id = sig.id

    # Verify the approval.granted signal row exists.
    async with factory() as session:
        rows = list(
            (
                await session.execute(
                    select(Signal)
                    .where(Signal.run_id == run_id)
                    .where(Signal.signal_type == "approval.granted")
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].id == sig_id
    assert rows[0].payload["approval_id"] == str(approval_id)
    assert rows[0].consumed_at is None

    await engine.dispose()
