"""Tests for the unified run dispatcher (W1.3 — durable execution).

The dispatcher rewrite (claim → execute → persist → finalise) changed
the contract considerably from the legacy best-effort implementation.
These tests preserve the original behavioural assertions (no silent
no-op on missing IDs, idempotent on terminal status, pending → completed
end-to-end) but updated for the new claim/lease + event chain shape.

All tests run with LLM_STUB_MODE=true — no API keys or live DB required.

Tests:
    1. dispatch_run on a missing run_id logs an error and returns None
       (closes Conflict 9 — the legacy ``Execution.id`` silent-no-op).
    2. dispatch_run on an already-terminal run returns the run unchanged
       (no claim, no execution, no events appended).
    3. dispatch_run end-to-end: pending → claim → execute → completed
       with persisted step rows + run.completed event.
    4. dispatch_run on a status='running' row that already has another
       lease owner is treated as non-claimable.

NOTE: A 5th legacy test for ``_drain_pending_runs`` was removed when
the worker drain loop was rebuilt to call ``dispatch_run`` directly via
the new state machine; that scaffolding now belongs to W1.4 and is
tested in the worker test suite.
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


# ---------------------------------------------------------------------------
# Fixture: in-memory SQLite engine + session factory wired into the dispatcher
# ---------------------------------------------------------------------------


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables created."""
    # Import all models so SQLModel.metadata is populated.
    from app.models import (  # noqa: F401
        Agent,
        Execution,
        User,
    )
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


# ---------------------------------------------------------------------------
# Helpers — seed a workflow + run row directly via the engine
# ---------------------------------------------------------------------------


async def _seed_workflow_and_run(
    factory,
    *,
    steps: list[dict] | None = None,
    status: str = "queued",
    cancel_requested_at=None,
):
    """Insert a Workflow + WorkflowRun pair and return (workflow_id, run_id)."""
    from app.models.workflow import Workflow, WorkflowRun

    workflow_steps = steps or [
        {
            "step_id": "s1",
            "name": "step-one",
            "node_type": "outputNode",
            "config": {"value": "ok"},
            "depends_on": [],
        }
    ]

    async with factory() as session:
        wf = Workflow(name="t-wf", steps=workflow_steps, graph_definition={})
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
                "name": wf.name,
                "steps": workflow_steps,
                "graph_definition": {},
            },
            cancel_requested_at=cancel_requested_at,
            input_data={},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

        return wf.id, run.id


# ---------------------------------------------------------------------------
# Test 1: dispatch_run on a missing run_id returns None (Conflict 9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_does_not_silent_no_op_on_unknown_id(
    monkeypatch,
    caplog,
):
    """A run_id that is not in workflow_runs must produce a clear error log.

    The legacy best-effort dispatcher silently returned, masking the
    ADR-006 split between executions and workflow_runs. The rewrite
    closes that gap.
    """
    engine, factory = await _make_engine_and_factory()

    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    from app.services.run_dispatcher import dispatch_run

    missing_id = uuid4()

    import logging
    caplog.set_level(logging.ERROR, logger="app.services.run_dispatcher")
    result = await dispatch_run(missing_id)

    assert result is None
    # The error log line must mention the missing run id and the
    # legacy-Execution explanation so operators don't lose the trail.
    matched = [
        rec for rec in caplog.records
        if "not in workflow_runs" in rec.getMessage()
    ]
    assert matched, (
        "dispatch_run must log an explicit error when the run_id is missing "
        "(Conflict 9: legacy Execution.id must not silent-no-op)"
    )

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 2: dispatch_run on an already-terminal run returns without side effects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_idempotent_on_completed(monkeypatch):
    """A run already in a terminal status must not be re-executed."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    _, run_id = await _seed_workflow_and_run(factory, status="completed")

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id)

    # Returns the run row but doesn't mutate it. Status stays terminal.
    assert result is not None
    assert result.status == "completed"
    assert result.attempt == 0  # no claim attempted

    # No events were appended (idempotent on terminal status).
    from sqlalchemy import select
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent).where(
                    WorkflowRunEvent.run_id == run_id
                )
            )
        ).scalars().all()
    assert events == []

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 3: dispatch_run end-to-end — pending → claim → execute → completed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_pending_to_completed(monkeypatch):
    """Full happy path: pending workflow_run → completed with steps + events."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    # Stub the engine with a deterministic result; the workflow steps
    # don't need to actually execute for this test — we're verifying the
    # dispatcher's claim/persist/finalise wiring around the engine.
    async def _fake_engine(workflow, **kwargs):
        return {
            "status": "completed",
            "duration_ms": 5,
            "steps": [
                {
                    "step_id": "s1",
                    "name": "step-one",
                    "status": "completed",
                    "started_at": None,
                    "completed_at": None,
                    "duration_ms": 5,
                    "input_data": {},
                    "output_data": {"value": "ok"},
                    "error": None,
                    "token_usage": {},
                    "cost_usd": 0.0,
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    _, run_id = await _seed_workflow_and_run(factory, status="queued")

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="test-worker")

    assert result is not None
    assert result.status == "completed"
    assert result.attempt == 1
    assert result.completed_at is not None

    # Event chain present (no need to fully walk it here — that is the
    # job of test_dispatcher_persist.py).
    from sqlalchemy import select
    from app.models.workflow import WorkflowRunEvent, WorkflowRunStep

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
        steps = (
            await session.execute(
                select(WorkflowRunStep).where(
                    WorkflowRunStep.run_id == run_id
                )
            )
        ).scalars().all()

    assert [e.event_type for e in events] == [
        "run.claimed",
        "run.started",
        "step.completed",
        "run.completed",
    ]
    assert len(steps) == 1
    assert steps[0].status == "completed"

    await engine.dispose()


# ---------------------------------------------------------------------------
# Test 4: dispatch_run on a status='running' row treated as non-claimable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_skips_when_already_running(monkeypatch):
    """A row already in status='running' is not contended for."""
    engine, factory = await _make_engine_and_factory()
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )

    _, run_id = await _seed_workflow_and_run(factory, status="running")

    # Engine MUST NOT run for already-running rows.
    called = {"engine": 0}

    async def _engine_should_not_run(*a, **kw):
        called["engine"] += 1
        return {"status": "completed", "duration_ms": 0, "steps": []}

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _engine_should_not_run,
    )

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id)

    # We get back the row in its current state and the engine is never
    # invoked.
    assert result is not None
    assert result.status == "running"
    assert called["engine"] == 0

    await engine.dispose()
