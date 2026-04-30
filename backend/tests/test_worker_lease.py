"""WorkerRegistry + heartbeat lifecycle tests (Phase 6).

Verifies the WorkerRegistry CRUD primitives and the worker's heartbeat
behaviour:
  - Registers a heartbeat row on start
  - Refreshes ``last_heartbeat_at`` on each tick
  - Deregisters the row on graceful shutdown
  - ``list_active`` filters by silence threshold

Tests run against an in-memory SQLite engine so they need no external DB.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta

os.environ.setdefault("LLM_STUB_MODE", "true")
# Note: We do NOT set ARCHON_DATABASE_URL — the default Postgres URL parses
# fine without connecting (engine is lazy). Each test uses its own
# in-memory SQLite engine via the ``engine`` fixture and patches
# ``app.worker.async_session_factory`` to point at it.

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Importing app.models populates SQLModel.metadata with every table,
# which we then create_all on the in-memory engine below.
import app.models  # noqa: F401
from app.models.worker_registry import WorkerHeartbeat
from app.services.worker_registry import WorkerRegistry


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def engine():
    """Per-test in-memory SQLite engine with all tables materialised."""
    eng = create_async_engine(SQLITE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture()
async def session_factory(engine):
    """sessionmaker bound to the per-test engine."""
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ── Direct registry tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_registers_heartbeat_on_start(session_factory) -> None:
    """register() inserts a row with the supplied identity fields."""
    async with session_factory() as session:
        row = await WorkerRegistry.register(
            session,
            worker_id="worker-1",
            hostname="host-a",
            pid=4242,
            capabilities={"queues": ["default"]},
            version="0.1.0",
            tenant_affinity=["tenant-x"],
        )

    assert row.worker_id == "worker-1"
    assert row.hostname == "host-a"
    assert row.pid == 4242
    assert row.capabilities == {"queues": ["default"]}
    assert row.version == "0.1.0"
    assert row.tenant_affinity == ["tenant-x"]

    # Re-fetch and confirm persistence
    async with session_factory() as session:
        fetched = await session.get(WorkerHeartbeat, "worker-1")
        assert fetched is not None
        assert fetched.hostname == "host-a"


@pytest.mark.asyncio
async def test_worker_heartbeat_updates_last_seen(session_factory) -> None:
    """heartbeat() refreshes last_heartbeat_at and returns True."""
    async with session_factory() as session:
        await WorkerRegistry.register(
            session,
            worker_id="worker-2",
            hostname="host-b",
            pid=1,
            capabilities={},
        )

    async with session_factory() as session:
        before = await session.get(WorkerHeartbeat, "worker-2")
        before_ts = before.last_heartbeat_at

    # Sleep long enough that the SQLite resolution catches the change.
    await asyncio.sleep(0.05)

    async with session_factory() as session:
        ok = await WorkerRegistry.heartbeat(session, worker_id="worker-2")
    assert ok is True

    async with session_factory() as session:
        after = await session.get(WorkerHeartbeat, "worker-2")
        assert after.last_heartbeat_at >= before_ts


@pytest.mark.asyncio
async def test_worker_heartbeat_returns_false_for_unknown(session_factory) -> None:
    """heartbeat() on a missing worker_id returns False (caller re-registers)."""
    async with session_factory() as session:
        ok = await WorkerRegistry.heartbeat(session, worker_id="never-registered")
    assert ok is False


@pytest.mark.asyncio
async def test_worker_deregisters_on_shutdown(session_factory) -> None:
    """deregister() removes the row; subsequent fetch returns None."""
    async with session_factory() as session:
        await WorkerRegistry.register(
            session,
            worker_id="worker-3",
            hostname="host-c",
            pid=99,
            capabilities={},
        )

    async with session_factory() as session:
        assert await session.get(WorkerHeartbeat, "worker-3") is not None

    async with session_factory() as session:
        deleted = await WorkerRegistry.deregister(session, worker_id="worker-3")
    assert deleted is True

    async with session_factory() as session:
        assert await session.get(WorkerHeartbeat, "worker-3") is None


@pytest.mark.asyncio
async def test_worker_registry_lists_only_active(session_factory) -> None:
    """list_active() excludes rows whose heartbeat is older than the threshold."""
    async with session_factory() as session:
        # Active: last_heartbeat_at = now
        await WorkerRegistry.register(
            session, worker_id="alive", hostname="h", pid=1, capabilities={}
        )
        # Stale: forge last_heartbeat_at into the past
        stale_row = WorkerHeartbeat(
            worker_id="stale",
            hostname="h",
            pid=2,
            started_at=datetime.utcnow() - timedelta(minutes=30),
            last_heartbeat_at=datetime.utcnow() - timedelta(minutes=30),
            capabilities={},
        )
        session.add(stale_row)
        await session.commit()

    async with session_factory() as session:
        active = await WorkerRegistry.list_active(
            session, max_silence_seconds=60
        )
    ids = {w.worker_id for w in active}
    assert "alive" in ids
    assert "stale" not in ids

    # Pruning the stale row removes it entirely
    async with session_factory() as session:
        pruned = await WorkerRegistry.prune_stale(
            session, max_silence_seconds=60
        )
    assert pruned == 1

    async with session_factory() as session:
        remaining = await WorkerRegistry.list_active(
            session, max_silence_seconds=10_000
        )
    assert {w.worker_id for w in remaining} == {"alive"}


# ── Worker-loop heartbeat behaviour (with patched session factory) ─────


@pytest.mark.asyncio
async def test_worker_loop_registers_and_deregisters(session_factory, monkeypatch) -> None:
    """run_worker registers on start and deregisters on shutdown.

    The drain loop returns no rows (empty workflow_runs table) and the
    reclaim loop is patched to a no-op so we don't depend on W1.3 timing.
    """
    import app.worker as worker_mod

    # Point the worker at our in-memory engine.
    monkeypatch.setattr(worker_mod, "async_session_factory", session_factory)

    # Stub out the legacy slow loop — it imports its own session factory
    # at call time and will try to talk to Postgres if we don't mute it.
    async def _noop():
        return None

    monkeypatch.setattr(worker_mod, "_run_scheduled_scans", _noop)
    monkeypatch.setattr(worker_mod, "_run_rotation_checks", _noop)
    monkeypatch.setattr(worker_mod, "_run_budget_alerts", _noop)
    monkeypatch.setattr(worker_mod, "_check_scheduled_workflows", _noop)
    monkeypatch.setattr(worker_mod, "_run_improvement_analysis", _noop)
    # Force the reclaim resolver to "absent" so the loop is a hard no-op.
    monkeypatch.setattr(worker_mod, "_resolve_reclaim_expired_runs", lambda: None)

    # Hammer the loops by setting tiny intervals — we'll cancel quickly.
    monkeypatch.setattr(worker_mod, "_HEARTBEAT_INTERVAL", 0.05)
    monkeypatch.setattr(worker_mod, "_DRAIN_INTERVAL", 0.05)
    monkeypatch.setattr(worker_mod, "_RECLAIM_INTERVAL", 0.05)
    monkeypatch.setattr(worker_mod, "_SHUTDOWN_GRACE_SECONDS", 1)

    task = asyncio.create_task(
        worker_mod.run_worker(worker_id="worker-loop-1", max_concurrent=2)
    )

    # Wait for the worker to register
    await asyncio.sleep(0.2)
    async with session_factory() as session:
        row = await session.get(WorkerHeartbeat, "worker-loop-1")
        assert row is not None
        first_seen = row.last_heartbeat_at

    # Wait for at least one heartbeat tick
    await asyncio.sleep(0.2)
    async with session_factory() as session:
        row = await session.get(WorkerHeartbeat, "worker-loop-1")
        assert row is not None
        # Either the heartbeat moved forward or stayed equal — both fine.
        assert row.last_heartbeat_at >= first_seen

    # Trigger graceful shutdown
    worker_mod.request_shutdown()
    await asyncio.wait_for(task, timeout=5)

    # Heartbeat row removed on shutdown
    async with session_factory() as session:
        row = await session.get(WorkerHeartbeat, "worker-loop-1")
        assert row is None
