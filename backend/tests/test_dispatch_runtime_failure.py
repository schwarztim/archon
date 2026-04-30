"""Tests for the failure-persistence path in app.services.dispatch_runtime.

P0 hardening (plan a6a915dc):
    Tracked background dispatch failure used to be log-only — the run row
    stayed in ``status='queued'`` forever. ``schedule_dispatch`` now accepts
    a ``run_id`` kwarg; when provided, dispatch failures (inline OR
    background) persist a terminal ``status='failed'`` state on the row and
    emit a ``run.failed`` event.

These tests seed an in-memory SQLite database, point both
``app.database.async_session_factory`` and the dispatch_runtime helper at
the test factory, drive a deterministically-failing coroutine through
``schedule_dispatch``, and assert on the row state + event chain.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services import dispatch_runtime  # noqa: E402

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _set_env(key: str, value: str | None):
    original = os.environ.get(key)
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


async def _make_engine_and_factory():
    """Build a fresh in-memory SQLite engine + session factory."""
    # Importing the models registers them on SQLModel.metadata so create_all
    # produces the workflow_runs / workflow_run_events / workflow_run_steps
    # tables that the persistence path needs.
    from app.models import (  # noqa: F401, PLC0415
        Agent,
        Execution,
        User,
    )
    from app.models.workflow import (  # noqa: F401, PLC0415
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


async def _seed_run(factory, *, status: str = "queued") -> UUID:
    """Insert a minimal Workflow + WorkflowRun pair, return the run id."""
    from app.models.workflow import Workflow, WorkflowRun

    async with factory() as session:
        wf = Workflow(name="t-fail-wf", steps=[], graph_definition={})
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
                "steps": [],
                "graph_definition": {},
            },
            input_data={},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


def _patch_factory(monkeypatch, factory) -> None:
    """Point dispatch_runtime AND the database module at our test factory.

    ``_persist_failed_run`` does ``from app.database import async_session_factory``
    *inside* the function body (late import), so we have to patch the
    ``app.database`` attribute that the late import reads — patching only
    ``dispatch_runtime`` would be a no-op.
    """
    import app.database as _db  # noqa: PLC0415

    monkeypatch.setattr(_db, "async_session_factory", factory)


async def _read_run(factory, run_id: UUID):
    from app.models.workflow import WorkflowRun

    async with factory() as session:
        return await session.get(WorkflowRun, run_id)


async def _read_events(factory, run_id: UUID):
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        stmt = (
            select(WorkflowRunEvent)
            .where(WorkflowRunEvent.run_id == run_id)
            .order_by(WorkflowRunEvent.sequence)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def _drain_until(predicate, *, max_iters: int = 50, delay: float = 0.01):
    """Yield to the loop until predicate() is true, bounded retries."""
    for _ in range(max_iters):
        if await predicate():
            return True
        await asyncio.sleep(delay)
    return False


# ---------------------------------------------------------------------------
# Tests — background (non-inline) failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_failure_persists_run_failed_status(
    monkeypatch,
) -> None:
    """Background dispatch raises -> run row reaches status='failed'."""
    _engine, factory = await _make_engine_and_factory()
    _patch_factory(monkeypatch, factory)
    run_id = await _seed_run(factory)

    async def boom() -> None:
        raise RuntimeError("background boom")

    with _set_env("ARCHON_DISPATCH_INLINE", None):
        await dispatch_runtime.schedule_dispatch(boom(), run_id=run_id)

        async def _is_failed() -> bool:
            run = await _read_run(factory, run_id)
            return run is not None and run.status == "failed"

        assert await _drain_until(_is_failed), (
            "expected run.status='failed' after background dispatch raised"
        )

    run = await _read_run(factory, run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.completed_at is not None
    assert run.error is not None
    assert "RuntimeError" in run.error
    assert "background boom" in run.error
    assert run.error_code == "background_dispatch_failed"


@pytest.mark.asyncio
async def test_background_failure_emits_run_failed_event(
    monkeypatch,
) -> None:
    """Background dispatch raises -> a run.failed event is appended."""
    _engine, factory = await _make_engine_and_factory()
    _patch_factory(monkeypatch, factory)
    run_id = await _seed_run(factory)

    async def boom() -> None:
        raise ValueError("evented boom")

    with _set_env("ARCHON_DISPATCH_INLINE", None):
        await dispatch_runtime.schedule_dispatch(boom(), run_id=run_id)

        async def _has_event() -> bool:
            events = await _read_events(factory, run_id)
            return any(e.event_type == "run.failed" for e in events)

        assert await _drain_until(_has_event), (
            "expected run.failed event after background dispatch raised"
        )

    events = await _read_events(factory, run_id)
    failed = [e for e in events if e.event_type == "run.failed"]
    assert len(failed) == 1, f"expected exactly one run.failed event, got {events!r}"
    payload = failed[0].payload
    assert payload.get("reason") == "background_dispatch_failed"
    assert payload.get("exception") == "ValueError"
    assert "evented boom" in str(payload.get("message"))


# ---------------------------------------------------------------------------
# Tests — inline failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inline_failure_persists_run_failed_status(monkeypatch) -> None:
    """Inline dispatch raises -> run row reaches status='failed' synchronously."""
    _engine, factory = await _make_engine_and_factory()
    _patch_factory(monkeypatch, factory)
    run_id = await _seed_run(factory)

    async def boom() -> None:
        raise RuntimeError("inline boom")

    with _set_env("ARCHON_DISPATCH_INLINE", "1"):
        # schedule_dispatch must NOT propagate — the route layer cannot
        # tolerate a 5xx from a swallowed dispatch error.
        await dispatch_runtime.schedule_dispatch(boom(), run_id=run_id)

    run = await _read_run(factory, run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.completed_at is not None
    assert run.error_code == "background_dispatch_failed"
    assert "inline boom" in (run.error or "")


@pytest.mark.asyncio
async def test_inline_failure_emits_run_failed_event(monkeypatch) -> None:
    """Inline dispatch raises -> a run.failed event is appended synchronously."""
    _engine, factory = await _make_engine_and_factory()
    _patch_factory(monkeypatch, factory)
    run_id = await _seed_run(factory)

    async def boom() -> None:
        raise KeyError("inline-evented")

    with _set_env("ARCHON_DISPATCH_INLINE", "1"):
        await dispatch_runtime.schedule_dispatch(boom(), run_id=run_id)

    events = await _read_events(factory, run_id)
    failed = [e for e in events if e.event_type == "run.failed"]
    assert len(failed) == 1, (
        f"expected exactly one run.failed event in inline mode, got {events!r}"
    )
    assert failed[0].payload.get("exception") == "KeyError"


# ---------------------------------------------------------------------------
# Tests — guard rails
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_already_terminal_is_not_overwritten(monkeypatch) -> None:
    """A run already in completed/failed/cancelled is not re-marked."""
    _engine, factory = await _make_engine_and_factory()
    _patch_factory(monkeypatch, factory)

    # Seed a run that is already 'completed' (e.g. dispatcher finished and
    # the engine raised AFTER the row finalised — should stay completed).
    from app.models.workflow import WorkflowRun

    run_id = await _seed_run(factory)
    async with factory() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        run.output_data = {"result": "already-done"}
        session.add(run)
        await session.commit()

    async def boom() -> None:
        raise RuntimeError("late boom")

    with _set_env("ARCHON_DISPATCH_INLINE", "1"):
        await dispatch_runtime.schedule_dispatch(boom(), run_id=run_id)

    run = await _read_run(factory, run_id)
    assert run is not None
    assert run.status == "completed", (
        "completed run must not be overwritten by a late dispatch failure"
    )
    # No run.failed event should have been appended either.
    events = await _read_events(factory, run_id)
    assert not any(e.event_type == "run.failed" for e in events)


@pytest.mark.asyncio
async def test_run_id_missing_does_not_crash(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """schedule_dispatch without run_id must keep the legacy log-only behaviour."""
    _engine, factory = await _make_engine_and_factory()
    _patch_factory(monkeypatch, factory)

    async def boom() -> None:
        raise RuntimeError("no run_id boom")

    with _set_env("ARCHON_DISPATCH_INLINE", None):
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger=dispatch_runtime.log.name):
            await dispatch_runtime.schedule_dispatch(boom())  # no run_id
            for _ in range(50):
                await asyncio.sleep(0)
                if any(
                    "background_dispatch_failed" in rec.message
                    for rec in caplog.records
                ):
                    break

    assert any(
        "background_dispatch_failed" in rec.message for rec in caplog.records
    ), "legacy path must still log the failure"
    # No DB rows touched: the only run we seeded is untouched, and we never
    # created any row keyed off the missing run_id.


@pytest.mark.asyncio
async def test_persist_failure_handles_db_error_silently(
    monkeypatch, caplog: pytest.LogCaptureFixture
) -> None:
    """If the persist itself fails, schedule_dispatch must not raise."""
    _engine, factory = await _make_engine_and_factory()
    _patch_factory(monkeypatch, factory)
    run_id = await _seed_run(factory)

    # Force the late ``async_session_factory()`` call inside _persist_failed_run
    # to raise. We monkeypatch on app.database (where it is imported from).
    import app.database as _db

    def _broken_factory(*_args, **_kwargs):
        raise RuntimeError("DB connection exploded")

    monkeypatch.setattr(_db, "async_session_factory", _broken_factory)

    async def boom() -> None:
        raise RuntimeError("primary boom")

    with _set_env("ARCHON_DISPATCH_INLINE", "1"):
        caplog.clear()
        with caplog.at_level(
            logging.ERROR, logger=dispatch_runtime.log.name
        ):
            # Must NOT raise even though both the dispatch coroutine AND the
            # persist helper failed — the route layer cannot tolerate either.
            await dispatch_runtime.schedule_dispatch(boom(), run_id=run_id)

    # Both errors should be in the log: the original inline_dispatch_failed,
    # and the persist's exception handler logging the secondary failure.
    msgs = [rec.message for rec in caplog.records]
    assert any("inline_dispatch_failed" in m for m in msgs), msgs
    assert any(
        "background_dispatch_failed_state_persist_error" in m for m in msgs
    ), msgs
