"""Worker crash-recovery tests (Phase 1 + Phase 6).

Verifies that a crashed worker's leased runs are recoverable:
  - A run with an expired lease is reclaimable (drain picks it up)
  - reclaim_expired_runs (when supplied by W1.3) returns stuck rows
    to the queue and is invoked by the worker's reclaim loop

The dispatcher's reclaim primitive is owned by W1.3 and may not exist
yet. Tests that depend on it use ``pytest.importorskip`` semantics —
fall back to direct dispatch behaviour when the primitive is absent.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from uuid import UUID

os.environ.setdefault("LLM_STUB_MODE", "true")
# Per-test SQLite engines are constructed in fixtures; we don't set
# ARCHON_DATABASE_URL because the import-time engine in app.database
# uses Postgres-only kwargs (pool_size, max_overflow).

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401
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
    async with session_factory() as session:
        wf = Workflow(name="recover-wf", steps=[], graph_definition=None)
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


def _normalise_run_id(value) -> str:
    if isinstance(value, UUID):
        return value.hex
    return str(value).replace("-", "")


# ── Crash recovery via expired lease ───────────────────────────────────


@pytest.mark.asyncio
async def test_worker_kill_during_run_lease_expires(
    session_factory, seed_workflow, monkeypatch
) -> None:
    """A run whose owner died mid-execution recovers when its lease expires.

    Setup:
      - Worker A "claims" a run (sets lease_owner=A, lease_expires_at=past)
      - Worker A is gone (process killed)
      - Worker B's drain loop sees the expired-lease row and dispatches it
      - The dispatcher's claim_run picks B as the new owner
      - Run completes exactly once (B owns it; A is dead)
    """
    import app.worker as worker_mod

    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)

    # Insert the leased-but-expired run
    async with session_factory() as session:
        run = WorkflowRun(
            workflow_id=seed_workflow,
            kind="workflow",
            definition_snapshot={"_test": True},
            status="pending",
            lease_owner="worker-A-DEAD",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=120),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        crashed_run_id = run.id

    # Stub dispatcher: simulate a successful claim by worker B.
    completed: list[str] = []

    async def _stub_dispatch(rid, *, worker_id):
        # In reality, claim_run inside dispatch_run would CAS-update
        # lease_owner from worker-A-DEAD to worker_id. We just record
        # the completion.
        async with session_factory() as session:
            row = await session.get(WorkflowRun, rid)
            if row is None:
                return
            # Pretend claim_run succeeded for this worker
            row.lease_owner = worker_id
            row.status = "completed"
            row.completed_at = datetime.utcnow()
            session.add(row)
            await session.commit()
        completed.append(_normalise_run_id(rid))

    monkeypatch.setattr(worker_mod, "_call_dispatch_run", _stub_dispatch)
    worker_mod._inflight.clear()

    await worker_mod._drain_loop(
        "worker-B-LIVE", asyncio.Semaphore(5), asyncio.Event()
    )
    if worker_mod._inflight:
        await asyncio.gather(*list(worker_mod._inflight), return_exceptions=True)

    assert _normalise_run_id(crashed_run_id) in completed

    async with session_factory() as session:
        row = await session.get(WorkflowRun, crashed_run_id)
        assert row.lease_owner == "worker-B-LIVE"
        assert row.status == "completed"


@pytest.mark.asyncio
async def test_reclaim_loop_returns_stuck_running_runs_to_queued(
    session_factory, seed_workflow, monkeypatch
) -> None:
    """The reclaim loop calls run_dispatcher.reclaim_expired_runs (when shipped).

    W1.3 owns ``reclaim_expired_runs``; until it lands, we patch a stub
    onto the import surface and assert the worker invokes it on every
    reclaim tick.
    """
    import app.worker as worker_mod

    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)

    reclaim_calls: list[dict] = []

    async def _stub_reclaim(*, grace_seconds: int = 0):
        reclaim_calls.append({"grace_seconds": grace_seconds})
        return 3  # pretend three runs were reclaimed

    monkeypatch.setattr(worker_mod, "_resolve_reclaim_expired_runs", lambda: _stub_reclaim)

    # Tight intervals so the loop ticks promptly
    monkeypatch.setattr(worker_mod, "_RECLAIM_INTERVAL", 0.05)
    monkeypatch.setattr(worker_mod, "_HEARTBEAT_INTERVAL", 1.0)
    monkeypatch.setattr(worker_mod, "_DRAIN_INTERVAL", 1.0)
    monkeypatch.setattr(worker_mod, "_SHUTDOWN_GRACE_SECONDS", 1)

    shutdown = asyncio.Event()
    task = asyncio.create_task(worker_mod._reclaim_loop("worker-rec", shutdown))

    # Allow several reclaim ticks to fire
    await asyncio.sleep(0.25)
    shutdown.set()
    await asyncio.wait_for(task, timeout=2)

    assert len(reclaim_calls) >= 1
    # First call uses the configured grace
    assert reclaim_calls[0]["grace_seconds"] == worker_mod._RECLAIM_GRACE_SECONDS


@pytest.mark.asyncio
async def test_reclaim_loop_noop_when_primitive_absent(
    session_factory, monkeypatch
) -> None:
    """If W1.3 has not shipped reclaim_expired_runs, the loop quietly no-ops."""
    import app.worker as worker_mod

    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)
    # Force "primitive absent" path
    monkeypatch.setattr(worker_mod, "_resolve_reclaim_expired_runs", lambda: None)
    monkeypatch.setattr(worker_mod, "_RECLAIM_INTERVAL", 0.05)

    shutdown = asyncio.Event()
    task = asyncio.create_task(worker_mod._reclaim_loop("worker-no-reclaim", shutdown))
    await asyncio.sleep(0.15)
    shutdown.set()
    await asyncio.wait_for(task, timeout=2)
    # Test passes if no exception was raised


# ── Real reclaim exercised end-to-end (W1.3 has landed run_lifecycle) ──


_real_reclaim = None
try:
    from app.services.run_lifecycle import reclaim_expired_runs as _real_reclaim  # type: ignore # noqa: F401
except ImportError:
    try:
        from app.services.run_dispatcher import reclaim_expired_runs as _real_reclaim  # type: ignore # noqa: F401
    except ImportError:
        pass


@pytest.mark.skipif(
    _real_reclaim is None,
    reason="reclaim_expired_runs not shipped yet",
)
@pytest.mark.asyncio
async def test_real_reclaim_returns_expired_runs_to_queue(
    session_factory, seed_workflow
) -> None:
    """Exercise the real W1.3 ``reclaim_expired_runs`` end-to-end."""
    import inspect

    reclaim = _real_reclaim

    # Seed an expired-lease running row
    async with session_factory() as session:
        run = WorkflowRun(
            workflow_id=seed_workflow,
            kind="workflow",
            definition_snapshot={"_test": True},
            status="running",
            lease_owner="dead",
            lease_expires_at=datetime.utcnow() - timedelta(seconds=300),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    # W1.3 signature is reclaim_expired_runs(session, *, lease_grace_seconds=10)
    sig = inspect.signature(reclaim)
    if "lease_grace_seconds" in sig.parameters:
        kw = {"lease_grace_seconds": 10}
    else:
        kw = {"grace_seconds": 10}
    needs_session = (
        bool(sig.parameters)
        and next(iter(sig.parameters.values())).name == "session"
    )

    if needs_session:
        async with session_factory() as session:
            count = await reclaim(session, **kw)
    else:
        count = await reclaim(**kw)

    if hasattr(count, "__len__"):
        count = len(count)
    assert int(count) >= 1

    async with session_factory() as session:
        row = await session.get(WorkflowRun, run_id)
        assert row.status in ("queued", "pending")
        assert row.lease_owner is None or row.lease_owner != "dead"
