"""Timer service tests — durable timer scheduling, draining, cancellation.

Runs against an in-memory SQLite engine. The Timer model carries an FK
to ``workflow_runs.id`` (ON DELETE CASCADE), so each test that exercises
the run_id path seeds a Workflow + WorkflowRun pair first. Timers with
NULL run_id (system-level timers) skip that seeding.

These tests focus on contract behaviour, not engine-specific details:
  - rows are persisted with status='pending'
  - fire_pending_timers fires only due rows
  - concurrent fire calls don't double-fire
  - cancel_timer is a soft state flip (no DELETE)
  - list_pending filters by run_id
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from uuid import UUID, uuid4

os.environ.setdefault("LLM_STUB_MODE", "true")

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

# Import only the model modules this suite exercises. Importing the
# whole ``app.models`` package would pull in every table (including
# unrelated WS-owned tables that currently have duplicate-index
# declarations on SQLite), and ``SQLModel.metadata.create_all`` would
# fail before any timer test runs. Limiting to the scoped imports keeps
# WS7's tests independent of unrelated upstream schema noise.
from app.models.workflow import Workflow, WorkflowRun  # noqa: F401
from app.models.timers import Timer
from app.services.timer_service import (
    cancel_timer,
    fire_pending_timers,
    list_pending,
    schedule_timer,
)


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# Tables this suite needs materialised. Restricting create_all to this
# allowlist isolates us from unrelated tables that may have schema bugs.
_TABLES = [
    SQLModel.metadata.tables[name]
    for name in ("workflows", "workflow_runs", "timers")
]


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def engine():
    """Per-test in-memory SQLite engine with the timer-related tables only."""
    eng = create_async_engine(SQLITE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: SQLModel.metadata.create_all(
                sync_conn, tables=_TABLES
            )
        )
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture()
async def session_factory(engine):
    """sessionmaker bound to the per-test engine."""
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture()
async def seed_run(session_factory) -> UUID:
    """Seed a workflow + run row so Timer.run_id FK can resolve."""
    async with session_factory() as session:
        wf = Workflow(name="timer-test-wf", steps=[], graph_definition=None)
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            kind="workflow",
            definition_snapshot={"_test": True},
            status="running",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


# ── schedule_timer ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_timer_persists_with_pending_status(
    session_factory, seed_run
) -> None:
    """A scheduled timer is stored as ``status='pending'`` with no fired_at."""
    fire_at = datetime.utcnow() + timedelta(seconds=60)
    async with session_factory() as session:
        timer = await schedule_timer(
            session,
            run_id=seed_run,
            step_id="step-1",
            fire_at=fire_at,
            purpose="delay_node",
            payload={"step_id": "step-1", "next_step": "step-2"},
        )
        timer_id = timer.id

    async with session_factory() as session:
        fetched = await session.get(Timer, timer_id)
        assert fetched is not None
        assert fetched.status == "pending"
        assert fetched.fired_at is None
        assert fetched.run_id == seed_run
        assert fetched.step_id == "step-1"
        assert fetched.purpose == "delay_node"
        assert fetched.payload == {"step_id": "step-1", "next_step": "step-2"}
        # SQLite stores naive datetimes; compare without tzinfo
        assert fetched.fire_at == fire_at.replace(microsecond=fire_at.microsecond)


@pytest.mark.asyncio
async def test_schedule_timer_with_null_run_id(session_factory) -> None:
    """System-level timers (NULL run_id) are supported."""
    fire_at = datetime.utcnow() + timedelta(seconds=10)
    async with session_factory() as session:
        timer = await schedule_timer(
            session,
            run_id=None,
            step_id=None,
            fire_at=fire_at,
            purpose="lease_renewal",
            payload={"sweep": True},
        )
        timer_id = timer.id

    async with session_factory() as session:
        fetched = await session.get(Timer, timer_id)
        assert fetched is not None
        assert fetched.run_id is None
        assert fetched.purpose == "lease_renewal"


# ── fire_pending_timers ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fire_pending_timers_returns_due_timers_and_marks_fired(
    session_factory, seed_run
) -> None:
    """A timer whose fire_at is in the past is returned + marked fired."""
    past = datetime.utcnow() - timedelta(seconds=5)
    async with session_factory() as session:
        timer = await schedule_timer(
            session,
            run_id=seed_run,
            step_id="step-1",
            fire_at=past,
            purpose="delay_node",
            payload={},
        )
        timer_id = timer.id

    async with session_factory() as session:
        fired = await fire_pending_timers(session, batch_size=10)

    assert len(fired) == 1
    assert fired[0].id == timer_id
    assert fired[0].status == "fired"
    assert fired[0].fired_at is not None

    # Persistence — re-fetch confirms the state was committed
    async with session_factory() as session:
        fetched = await session.get(Timer, timer_id)
        assert fetched.status == "fired"
        assert fetched.fired_at is not None


@pytest.mark.asyncio
async def test_fire_pending_timers_does_not_fire_future_timers(
    session_factory, seed_run
) -> None:
    """Timers whose fire_at is in the future are left untouched."""
    future = datetime.utcnow() + timedelta(seconds=60)
    async with session_factory() as session:
        timer = await schedule_timer(
            session,
            run_id=seed_run,
            step_id="future-step",
            fire_at=future,
            purpose="delay_node",
            payload={},
        )
        timer_id = timer.id

    async with session_factory() as session:
        fired = await fire_pending_timers(session, batch_size=10)
    assert fired == []

    async with session_factory() as session:
        fetched = await session.get(Timer, timer_id)
        assert fetched.status == "pending"
        assert fetched.fired_at is None


@pytest.mark.asyncio
async def test_fire_pending_timers_mixed_due_and_future(
    session_factory, seed_run
) -> None:
    """Only due rows are fired; future rows remain pending."""
    past = datetime.utcnow() - timedelta(seconds=5)
    future = datetime.utcnow() + timedelta(seconds=60)

    async with session_factory() as session:
        due = await schedule_timer(
            session, run_id=seed_run, step_id="due", fire_at=past,
            purpose="delay_node", payload={},
        )
        not_due = await schedule_timer(
            session, run_id=seed_run, step_id="future", fire_at=future,
            purpose="delay_node", payload={},
        )

    async with session_factory() as session:
        fired = await fire_pending_timers(session, batch_size=10)
    fired_ids = {t.id for t in fired}
    assert due.id in fired_ids
    assert not_due.id not in fired_ids

    async with session_factory() as session:
        still_pending = await session.get(Timer, not_due.id)
        assert still_pending.status == "pending"


@pytest.mark.asyncio
async def test_fire_pending_timers_respects_batch_size(
    session_factory, seed_run
) -> None:
    """When more rows are due than batch_size, only batch_size are fired."""
    past = datetime.utcnow() - timedelta(seconds=5)
    async with session_factory() as session:
        for i in range(7):
            await schedule_timer(
                session, run_id=seed_run, step_id=f"s{i}",
                fire_at=past + timedelta(microseconds=i),
                purpose="delay_node", payload={},
            )

    async with session_factory() as session:
        first_batch = await fire_pending_timers(session, batch_size=3)
    assert len(first_batch) == 3

    async with session_factory() as session:
        second_batch = await fire_pending_timers(session, batch_size=10)
    assert len(second_batch) == 4

    async with session_factory() as session:
        third_batch = await fire_pending_timers(session, batch_size=10)
    assert third_batch == []


# ── concurrency ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_fire_pending_timers_does_not_double_fire(
    session_factory, seed_run
) -> None:
    """Two concurrent drainers see disjoint result sets — every timer fires once.

    The CAS ``UPDATE ... WHERE status='pending'`` is the structural
    guarantee. SQLite serialises writes; each updater either wins
    (rowcount=1) or sees the row already drained (rowcount=0).
    """
    past = datetime.utcnow() - timedelta(seconds=5)
    timer_ids: list[UUID] = []
    async with session_factory() as session:
        for i in range(20):
            timer = await schedule_timer(
                session, run_id=seed_run, step_id=f"s{i}",
                fire_at=past + timedelta(microseconds=i),
                purpose="delay_node", payload={"i": i},
            )
            timer_ids.append(timer.id)

    async def _drain_once() -> list[Timer]:
        async with session_factory() as session:
            return await fire_pending_timers(session, batch_size=100)

    # Run two drainers concurrently
    results = await asyncio.gather(_drain_once(), _drain_once())
    fired_a, fired_b = results
    fired_ids_a = {t.id for t in fired_a}
    fired_ids_b = {t.id for t in fired_b}

    # Disjoint
    assert fired_ids_a.isdisjoint(fired_ids_b)
    # Together they cover every scheduled timer
    assert fired_ids_a | fired_ids_b == set(timer_ids)
    # Neither side double-counts within itself
    assert len(fired_a) == len(fired_ids_a)
    assert len(fired_b) == len(fired_ids_b)

    # All rows are now ``fired`` in the DB
    async with session_factory() as session:
        stmt = select(Timer).where(Timer.id.in_(timer_ids))  # type: ignore[union-attr]
        result = await session.exec(stmt)
        rows = list(result.all())
    assert all(r.status == "fired" for r in rows)
    assert all(r.fired_at is not None for r in rows)


# ── cancel_timer ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_timer_marks_cancelled_not_deleted(
    session_factory, seed_run
) -> None:
    """cancel_timer flips status to 'cancelled' but the row is preserved."""
    future = datetime.utcnow() + timedelta(seconds=60)
    async with session_factory() as session:
        timer = await schedule_timer(
            session, run_id=seed_run, step_id="s",
            fire_at=future, purpose="delay_node", payload={},
        )
        timer_id = timer.id

    async with session_factory() as session:
        cancelled = await cancel_timer(session, timer_id=timer_id)
    assert cancelled is True

    async with session_factory() as session:
        fetched = await session.get(Timer, timer_id)
        assert fetched is not None  # NOT deleted
        assert fetched.status == "cancelled"
        assert fetched.fired_at is None


@pytest.mark.asyncio
async def test_cancel_timer_returns_false_for_already_fired(
    session_factory, seed_run
) -> None:
    """A fired timer cannot be cancelled — CAS on status='pending' blocks it."""
    past = datetime.utcnow() - timedelta(seconds=5)
    async with session_factory() as session:
        timer = await schedule_timer(
            session, run_id=seed_run, step_id="s",
            fire_at=past, purpose="delay_node", payload={},
        )
        timer_id = timer.id
    async with session_factory() as session:
        await fire_pending_timers(session, batch_size=10)
    async with session_factory() as session:
        cancelled = await cancel_timer(session, timer_id=timer_id)
    assert cancelled is False
    async with session_factory() as session:
        fetched = await session.get(Timer, timer_id)
        assert fetched.status == "fired"


@pytest.mark.asyncio
async def test_cancel_timer_returns_false_for_unknown_id(session_factory) -> None:
    """Cancelling a non-existent id returns False (no error)."""
    async with session_factory() as session:
        cancelled = await cancel_timer(session, timer_id=uuid4())
    assert cancelled is False


@pytest.mark.asyncio
async def test_fire_pending_timers_skips_cancelled(
    session_factory, seed_run
) -> None:
    """Cancelled rows are not fired even if their fire_at is in the past."""
    past = datetime.utcnow() - timedelta(seconds=5)
    async with session_factory() as session:
        timer = await schedule_timer(
            session, run_id=seed_run, step_id="s",
            fire_at=past, purpose="delay_node", payload={},
        )
        timer_id = timer.id

    # Cancel BEFORE firing. Cancellation needs a future fire_at to win
    # the CAS gate — schedule it in the future, then move it back into
    # the past via a direct UPDATE? Simpler: cancel a future timer, then
    # rewrite fire_at to the past behind the policy's back to assert
    # that the drain query (which filters by status='pending') ignores
    # cancelled rows.
    async with session_factory() as session:
        # Cancel while still pending — CAS succeeds because we just inserted.
        cancelled = await cancel_timer(session, timer_id=timer_id)
    assert cancelled is True

    # Re-set fire_at to the past directly so it would otherwise be due.
    async with session_factory() as session:
        row = await session.get(Timer, timer_id)
        row.fire_at = past
        session.add(row)
        await session.commit()

    async with session_factory() as session:
        fired = await fire_pending_timers(session, batch_size=10)
    assert fired == []

    async with session_factory() as session:
        fetched = await session.get(Timer, timer_id)
        assert fetched.status == "cancelled"


# ── list_pending ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pending_filters_by_run_id(session_factory) -> None:
    """list_pending(run_id=X) returns only rows with that run_id."""
    # Two runs
    async with session_factory() as session:
        wf = Workflow(name="lp-wf", steps=[])
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        run_a = WorkflowRun(
            workflow_id=wf.id, kind="workflow",
            definition_snapshot={"_t": True}, status="running",
        )
        run_b = WorkflowRun(
            workflow_id=wf.id, kind="workflow",
            definition_snapshot={"_t": True}, status="running",
        )
        session.add(run_a)
        session.add(run_b)
        await session.commit()
        await session.refresh(run_a)
        await session.refresh(run_b)
        run_a_id = run_a.id
        run_b_id = run_b.id

    future = datetime.utcnow() + timedelta(seconds=60)
    async with session_factory() as session:
        await schedule_timer(
            session, run_id=run_a_id, step_id="s1",
            fire_at=future, purpose="delay_node", payload={},
        )
        await schedule_timer(
            session, run_id=run_a_id, step_id="s2",
            fire_at=future, purpose="delay_node", payload={},
        )
        await schedule_timer(
            session, run_id=run_b_id, step_id="s3",
            fire_at=future, purpose="delay_node", payload={},
        )
        # System-level timer (NULL run_id) — must NOT appear under
        # either run filter
        await schedule_timer(
            session, run_id=None, step_id=None,
            fire_at=future, purpose="lease_renewal", payload={},
        )

    async with session_factory() as session:
        a_rows = await list_pending(session, run_id=run_a_id)
        b_rows = await list_pending(session, run_id=run_b_id)
        all_rows = await list_pending(session)

    assert len(a_rows) == 2
    assert all(r.run_id == run_a_id for r in a_rows)
    assert len(b_rows) == 1
    assert all(r.run_id == run_b_id for r in b_rows)
    # All-pending count includes the orphan system timer
    assert len(all_rows) == 4


@pytest.mark.asyncio
async def test_list_pending_excludes_fired_and_cancelled(
    session_factory, seed_run
) -> None:
    """Only ``status='pending'`` rows appear in list_pending."""
    past = datetime.utcnow() - timedelta(seconds=5)
    future = datetime.utcnow() + timedelta(seconds=60)

    async with session_factory() as session:
        await schedule_timer(
            session, run_id=seed_run, step_id="due",
            fire_at=past, purpose="delay_node", payload={},
        )
        cancel_target = await schedule_timer(
            session, run_id=seed_run, step_id="cancel",
            fire_at=future, purpose="delay_node", payload={},
        )
        await schedule_timer(
            session, run_id=seed_run, step_id="future",
            fire_at=future, purpose="delay_node", payload={},
        )

    async with session_factory() as session:
        await cancel_timer(session, timer_id=cancel_target.id)
    async with session_factory() as session:
        await fire_pending_timers(session, batch_size=10)

    async with session_factory() as session:
        pending = await list_pending(session, run_id=seed_run)
    # Only the future-only row should remain pending
    assert len(pending) == 1
    assert pending[0].step_id == "future"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
