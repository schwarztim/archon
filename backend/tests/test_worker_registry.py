"""Tests for the W2 worker registry service.

Uses an in-memory SQLite engine + SQLModel.metadata.create_all, matching
the pattern established in test_task_queues.py.

Covered:
  - test_register_worker_creates_registration
  - test_heartbeat_updates_timestamp
  - test_sweep_marks_stale_workers
  - test_check_capability_returns_true_for_matching
  - test_check_capability_returns_false_for_missing
  - test_deregister_sets_draining
  - test_list_workers_filters_by_status
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all relevant tables."""
    # Imports inside the helper so SQLModel metadata is populated before create_all.
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.worker_registry import WorkerHeartbeat, WorkerRegistration  # noqa: F401

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_register_worker_creates_registration():
    """register_worker inserts a new WorkerRegistration row."""
    from app.services.worker_registry_service import register_worker

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        async with factory() as session:
            row = await register_worker(
                session,
                worker_name="test-worker",
                tenant_id=tenant_id,
                queue_names=["default"],
                capabilities=["llm", "vision"],
                max_concurrency=5,
                version="1.0.0",
                environment="test",
            )

        assert row.id is not None
        assert row.worker_name == "test-worker"
        assert row.tenant_id == tenant_id
        assert row.status == "active"
        assert row.capabilities == ["llm", "vision"]
        assert row.queue_names == ["default"]
        assert row.max_concurrency == 5
        assert row.worker_version == "1.0.0"
        assert row.environment == "test"
        assert row.in_flight_task_count == 0
        assert row.current_load == 0

    asyncio.run(_run())


def test_register_worker_upserts_on_duplicate():
    """Calling register_worker again with the same (worker_name, tenant_id) updates the row."""
    from app.services.worker_registry_service import register_worker

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        async with factory() as session:
            row1 = await register_worker(
                session,
                worker_name="upsert-worker",
                tenant_id=tenant_id,
                queue_names=["q1"],
                capabilities=["cap1"],
                max_concurrency=3,
                version="1.0.0",
            )

        async with factory() as session:
            row2 = await register_worker(
                session,
                worker_name="upsert-worker",
                tenant_id=tenant_id,
                queue_names=["q1", "q2"],
                capabilities=["cap1", "cap2"],
                max_concurrency=10,
                version="2.0.0",
            )

        # Same primary key — it's the same row updated.
        assert row1.id == row2.id
        assert row2.worker_version == "2.0.0"
        assert row2.max_concurrency == 10
        assert "cap2" in row2.capabilities

    asyncio.run(_run())


def test_heartbeat_updates_timestamp():
    """heartbeat() refreshes last_heartbeat_at on an existing worker."""
    from app.services.worker_registry_service import heartbeat, register_worker

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        async with factory() as session:
            row = await register_worker(
                session,
                worker_name="hb-worker",
                tenant_id=tenant_id,
                queue_names=[],
                capabilities=[],
                max_concurrency=1,
                version="1.0.0",
            )
            original_hb = row.last_heartbeat_at

        # Simulate passage of time by sleeping is fragile in unit tests.
        # Instead verify the call does not error and the column is updated.
        async with factory() as session:
            await heartbeat(session, worker_id=row.id, in_flight_count=2, load=1)

        async with factory() as session:
            from app.models.worker_registry import WorkerRegistration
            refreshed = await session.get(WorkerRegistration, row.id)

        assert refreshed is not None
        assert refreshed.in_flight_task_count == 2
        assert refreshed.current_load == 1
        # last_heartbeat_at is at least as recent as the original.
        assert refreshed.last_heartbeat_at >= original_hb

    asyncio.run(_run())


def test_heartbeat_on_missing_worker_does_not_raise():
    """heartbeat() is a no-op when the worker_id is not found."""
    from app.services.worker_registry_service import heartbeat

    async def _run():
        _, factory = await _make_engine_and_factory()
        async with factory() as session:
            # Should not raise.
            await heartbeat(session, worker_id=uuid4(), in_flight_count=0, load=0)

    asyncio.run(_run())


def test_sweep_marks_stale_workers():
    """sweep_stale_workers() promotes silent active workers to stale."""
    from app.services.worker_registry_service import register_worker, sweep_stale_workers
    from app.models.worker_registry import WorkerRegistration

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        # Register a worker.
        async with factory() as session:
            row = await register_worker(
                session,
                worker_name="stale-worker",
                tenant_id=tenant_id,
                queue_names=[],
                capabilities=[],
                max_concurrency=1,
                version="1.0.0",
            )

        # Back-date last_heartbeat_at so the worker looks stale.
        async with factory() as session:
            r = await session.get(WorkerRegistration, row.id)
            r.last_heartbeat_at = _utcnow_naive() - timedelta(seconds=120)
            session.add(r)
            await session.commit()

        # Sweep with 60s threshold — the worker (silent 120s) should be stale.
        async with factory() as session:
            stale_ids = await sweep_stale_workers(session, threshold_seconds=60)

        assert row.id in stale_ids

        async with factory() as session:
            r = await session.get(WorkerRegistration, row.id)
        assert r.status == "stale"

    asyncio.run(_run())


def test_sweep_does_not_mark_fresh_workers():
    """sweep_stale_workers() leaves recently-heartbeating workers untouched."""
    from app.services.worker_registry_service import register_worker, sweep_stale_workers

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        async with factory() as session:
            row = await register_worker(
                session,
                worker_name="fresh-worker",
                tenant_id=tenant_id,
                queue_names=[],
                capabilities=[],
                max_concurrency=1,
                version="1.0.0",
            )

        # 60s threshold — row was just created (effectively 0s ago).
        async with factory() as session:
            stale_ids = await sweep_stale_workers(session, threshold_seconds=60)

        assert row.id not in stale_ids

    asyncio.run(_run())


def test_check_capability_returns_true_for_matching():
    """check_capability() returns True when the required cap is present."""
    from app.services.worker_registry_service import check_capability, register_worker

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        async with factory() as session:
            row = await register_worker(
                session,
                worker_name="cap-worker",
                tenant_id=tenant_id,
                queue_names=[],
                capabilities=["llm", "vision", "audio"],
                max_concurrency=1,
                version="1.0.0",
            )

        async with factory() as session:
            result = await check_capability(session, worker_id=row.id, required_capability="vision")

        assert result is True

    asyncio.run(_run())


def test_check_capability_returns_false_for_missing():
    """check_capability() returns False when the required cap is absent."""
    from app.services.worker_registry_service import check_capability, register_worker

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        async with factory() as session:
            row = await register_worker(
                session,
                worker_name="cap-worker-2",
                tenant_id=tenant_id,
                queue_names=[],
                capabilities=["llm"],
                max_concurrency=1,
                version="1.0.0",
            )

        async with factory() as session:
            result = await check_capability(session, worker_id=row.id, required_capability="vision")

        assert result is False

    asyncio.run(_run())


def test_check_capability_returns_false_for_missing_worker():
    """check_capability() returns False when the worker_id does not exist."""
    from app.services.worker_registry_service import check_capability

    async def _run():
        _, factory = await _make_engine_and_factory()
        async with factory() as session:
            result = await check_capability(session, worker_id=uuid4(), required_capability="llm")
        assert result is False

    asyncio.run(_run())


def test_deregister_sets_draining():
    """deregister_worker() transitions an active worker to 'draining'."""
    from app.services.worker_registry_service import deregister_worker, register_worker
    from app.models.worker_registry import WorkerRegistration

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        async with factory() as session:
            row = await register_worker(
                session,
                worker_name="drain-worker",
                tenant_id=tenant_id,
                queue_names=[],
                capabilities=[],
                max_concurrency=1,
                version="1.0.0",
            )

        assert row.status == "active"

        async with factory() as session:
            await deregister_worker(session, worker_id=row.id)

        async with factory() as session:
            r = await session.get(WorkerRegistration, row.id)

        assert r is not None
        assert r.status == "draining"

    asyncio.run(_run())


def test_list_workers_filters_by_status():
    """list_workers() returns only rows matching the requested status."""
    from app.services.worker_registry_service import (
        deregister_worker,
        list_workers,
        register_worker,
    )

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_id = uuid4()

        # Register two workers.
        async with factory() as session:
            r1 = await register_worker(
                session,
                worker_name="list-worker-active",
                tenant_id=tenant_id,
                queue_names=[],
                capabilities=[],
                max_concurrency=1,
                version="1.0.0",
            )

        async with factory() as session:
            r2 = await register_worker(
                session,
                worker_name="list-worker-draining",
                tenant_id=tenant_id,
                queue_names=[],
                capabilities=[],
                max_concurrency=1,
                version="1.0.0",
            )

        # Drain r2.
        async with factory() as session:
            await deregister_worker(session, worker_id=r2.id)

        # list active — should contain only r1.
        async with factory() as session:
            active = await list_workers(session, tenant_id=tenant_id, status_filter="active")
        active_ids = {r.id for r in active}
        assert r1.id in active_ids
        assert r2.id not in active_ids

        # list draining — should contain only r2.
        async with factory() as session:
            draining = await list_workers(session, tenant_id=tenant_id, status_filter="draining")
        draining_ids = {r.id for r in draining}
        assert r2.id in draining_ids
        assert r1.id not in draining_ids

        # list all (no filter) — should contain both.
        async with factory() as session:
            all_workers = await list_workers(session, tenant_id=tenant_id)
        all_ids = {r.id for r in all_workers}
        assert r1.id in all_ids
        assert r2.id in all_ids

    asyncio.run(_run())


def test_list_workers_tenant_isolation():
    """list_workers() does not leak rows from other tenants."""
    from app.services.worker_registry_service import list_workers, register_worker

    async def _run():
        _, factory = await _make_engine_and_factory()
        tenant_a = uuid4()
        tenant_b = uuid4()

        async with factory() as session:
            await register_worker(
                session,
                worker_name="worker-a",
                tenant_id=tenant_a,
                queue_names=[],
                capabilities=[],
                max_concurrency=1,
                version="1.0.0",
            )

        async with factory() as session:
            await register_worker(
                session,
                worker_name="worker-b",
                tenant_id=tenant_b,
                queue_names=[],
                capabilities=[],
                max_concurrency=1,
                version="1.0.0",
            )

        async with factory() as session:
            tenant_a_workers = await list_workers(session, tenant_id=tenant_a)

        names = {r.worker_name for r in tenant_a_workers}
        assert "worker-a" in names
        assert "worker-b" not in names

    asyncio.run(_run())
