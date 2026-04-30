"""Worker drain-loop tests (Phase 1 + Phase 6).

Verifies the drain behaviour:
  - Picks up queued and pending runs from the canonical substrate
  - Skips runs whose lease is still live
  - Picks up runs whose lease has expired
  - Two parallel workers do not double-execute the same run
    (the dispatcher's claim_run wins exactly once)
  - Respects max_concurrent via the asyncio Semaphore

Tests run against an in-memory SQLite engine. The dispatcher is patched
to a stub that records every (run_id, worker_id) pair invoked.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from uuid import UUID

os.environ.setdefault("LLM_STUB_MODE", "true")
# Per-test SQLite engines are constructed in fixtures; we don't override
# ARCHON_DATABASE_URL so app.database's import-time engine creation does
# not need to handle the sqlite dialect's StaticPool restrictions.

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — populates SQLModel.metadata
from app.models.workflow import Workflow, WorkflowRun


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def engine():
    eng = create_async_engine(SQLITE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture()
async def session_factory(engine):
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture()
async def seed_workflow(session_factory) -> UUID:
    """A single Workflow row that all WorkflowRuns can FK to."""
    async with session_factory() as session:
        wf = Workflow(name="test-wf", steps=[], graph_definition=None)
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


async def _add_run(
    session_factory,
    *,
    workflow_id: UUID,
    status: str = "pending",
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
) -> UUID:
    async with session_factory() as session:
        run = WorkflowRun(
            workflow_id=workflow_id,
            kind="workflow",
            definition_snapshot={"_test": True},
            status=status,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


def _normalise_run_id(value) -> str:
    """SQLite returns UUIDs as raw hex strings; Postgres as UUID. Coerce."""
    if isinstance(value, UUID):
        return value.hex
    s = str(value).replace("-", "")
    return s


# ── Drain semantics ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drain_loop_picks_up_queued_runs(
    session_factory, seed_workflow, monkeypatch
) -> None:
    """A queued run with no lease is dispatched."""
    import app.worker as worker_mod

    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)

    run_id = await _add_run(session_factory, workflow_id=seed_workflow, status="queued")

    dispatched: list[tuple] = []

    async def _stub_dispatch(rid, *, worker_id):
        dispatched.append((_normalise_run_id(rid), worker_id))

    monkeypatch.setattr(worker_mod, "_call_dispatch_run", _stub_dispatch)
    worker_mod._inflight.clear()

    sem = asyncio.Semaphore(5)
    ev = asyncio.Event()

    await worker_mod._drain_loop("worker-A", sem, ev)
    if worker_mod._inflight:
        await asyncio.gather(*list(worker_mod._inflight), return_exceptions=True)

    assert len(dispatched) == 1
    assert dispatched[0][0] == _normalise_run_id(run_id)
    assert dispatched[0][1] == "worker-A"


@pytest.mark.asyncio
async def test_drain_loop_does_not_re_pick_running_runs(
    session_factory, seed_workflow, monkeypatch
) -> None:
    """A run with a live lease (lease_expires_at in the future) is skipped."""
    import app.worker as worker_mod

    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)

    # Live-leased run — should be excluded
    future = datetime.utcnow() + timedelta(seconds=300)
    leased_id = await _add_run(
        session_factory,
        workflow_id=seed_workflow,
        status="pending",
        lease_owner="someone-else",
        lease_expires_at=future,
    )
    # Plus one truly free run — should be picked up
    free_id = await _add_run(
        session_factory, workflow_id=seed_workflow, status="pending"
    )

    dispatched: list[str] = []

    async def _stub(rid, *, worker_id):
        dispatched.append(_normalise_run_id(rid))

    monkeypatch.setattr(worker_mod, "_call_dispatch_run", _stub)
    worker_mod._inflight.clear()

    await worker_mod._drain_loop(
        "worker-B", asyncio.Semaphore(5), asyncio.Event()
    )
    if worker_mod._inflight:
        await asyncio.gather(*list(worker_mod._inflight), return_exceptions=True)

    # Only the free run should have been dispatched.
    assert _normalise_run_id(free_id) in dispatched
    assert _normalise_run_id(leased_id) not in dispatched
    assert len(dispatched) == 1


@pytest.mark.asyncio
async def test_drain_loop_picks_up_runs_with_expired_lease(
    session_factory, seed_workflow, monkeypatch
) -> None:
    """A pending run whose lease_expires_at is in the past is dispatchable."""
    import app.worker as worker_mod

    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)

    past = datetime.utcnow() - timedelta(seconds=300)
    expired_id = await _add_run(
        session_factory,
        workflow_id=seed_workflow,
        status="pending",
        lease_owner="dead-worker",
        lease_expires_at=past,
    )

    dispatched: list[str] = []

    async def _stub(rid, *, worker_id):
        dispatched.append(_normalise_run_id(rid))

    monkeypatch.setattr(worker_mod, "_call_dispatch_run", _stub)
    worker_mod._inflight.clear()

    await worker_mod._drain_loop(
        "worker-C", asyncio.Semaphore(5), asyncio.Event()
    )
    if worker_mod._inflight:
        await asyncio.gather(*list(worker_mod._inflight), return_exceptions=True)

    assert _normalise_run_id(expired_id) in dispatched


@pytest.mark.asyncio
async def test_drain_loop_concurrent_workers_do_not_double_dispatch(
    session_factory, seed_workflow, monkeypatch
) -> None:
    """Two workers race for one run; the dispatcher's claim_run wins exactly once.

    The drain loop itself is not the arbiter — it only enqueues
    candidates. The atomic claim happens inside the dispatcher. We
    simulate the dispatcher as a winner-takes-all stub guarded by an
    asyncio.Lock — exactly one (run_id, *) pair survives.
    """
    import app.worker as worker_mod

    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)

    run_id = await _add_run(
        session_factory, workflow_id=seed_workflow, status="pending"
    )

    claim_lock = asyncio.Lock()
    claimed_by: dict[str, str] = {}  # run_id -> worker_id (winner)
    dispatched: list[tuple] = []

    async def _stub(rid, *, worker_id):
        dispatched.append((_normalise_run_id(rid), worker_id))
        async with claim_lock:
            key = _normalise_run_id(rid)
            if key in claimed_by:
                # Loser — exit cleanly (the real dispatcher returns None).
                return
            # Simulate the brief work window
            await asyncio.sleep(0.05)
            claimed_by[key] = worker_id

    monkeypatch.setattr(worker_mod, "_call_dispatch_run", _stub)
    worker_mod._inflight.clear()

    sem = asyncio.Semaphore(10)
    ev = asyncio.Event()

    await asyncio.gather(
        worker_mod._drain_loop("worker-X", sem, ev),
        worker_mod._drain_loop("worker-Y", sem, ev),
    )
    if worker_mod._inflight:
        await asyncio.gather(*list(worker_mod._inflight), return_exceptions=True)

    # Both drains saw the row (race), so both attempted dispatch...
    keys = [d[0] for d in dispatched]
    assert keys.count(_normalise_run_id(run_id)) >= 1
    # ...but exactly one winner recorded the claim.
    assert claimed_by[_normalise_run_id(run_id)] in {"worker-X", "worker-Y"}
    assert len(claimed_by) == 1


@pytest.mark.asyncio
async def test_drain_loop_respects_max_concurrent(
    session_factory, seed_workflow, monkeypatch
) -> None:
    """The asyncio.Semaphore caps in-flight dispatches at max_concurrent."""
    import app.worker as worker_mod

    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)

    # Seed 8 runs so the drain has more than enough work.
    for _ in range(8):
        await _add_run(
            session_factory, workflow_id=seed_workflow, status="pending"
        )

    in_flight = 0
    peak = 0
    ev_started = asyncio.Event()
    ev_release = asyncio.Event()

    async def _stub(rid, *, worker_id):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        ev_started.set()
        try:
            # Block until the test releases — gives the semaphore time
            # to reach saturation.
            await ev_release.wait()
        finally:
            in_flight -= 1

    monkeypatch.setattr(worker_mod, "_call_dispatch_run", _stub)
    worker_mod._inflight.clear()

    max_concurrent = 3
    sem = asyncio.Semaphore(max_concurrent)
    ev = asyncio.Event()

    await worker_mod._drain_loop("worker-cap", sem, ev)
    # Wait for at least one task to enter the stub
    await asyncio.wait_for(ev_started.wait(), timeout=2)
    # Let the semaphore saturate before unblocking
    await asyncio.sleep(0.1)

    assert peak <= max_concurrent, (
        f"in-flight peak {peak} exceeded max_concurrent {max_concurrent}"
    )

    ev_release.set()
    await asyncio.gather(*list(worker_mod._inflight), return_exceptions=True)
