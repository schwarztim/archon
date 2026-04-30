"""Worker heartbeat registry — Phase 6 Worker Plane.

Owns the ``worker_heartbeats`` table. Each worker process upserts a row
on start, refreshes ``last_heartbeat_at`` periodically, and deletes the
row on graceful shutdown.

Stale rows (``last_heartbeat_at`` older than ``max_silence_seconds``)
are pruned by ``prune_stale``. Run-lease reclamation is owned by the
dispatcher (``run_dispatcher.reclaim_expired_runs``) — this module ONLY
manages the heartbeat row.

Concurrency: ``register`` is an UPSERT keyed on ``worker_id``, so
restarting a worker with the same id collapses to one row. Heartbeats
are best-effort writes — a missed tick is recovered by the next one.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.worker_registry import WorkerHeartbeat

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC — matches WorkerHeartbeat / WorkflowRun column type."""
    return datetime.utcnow()


class WorkerRegistry:
    """CRUD-style operations on ``worker_heartbeats``.

    All methods take an explicit ``AsyncSession`` so the caller controls
    the surrounding transaction. Methods commit on success.
    """

    @staticmethod
    async def register(
        session: AsyncSession,
        *,
        worker_id: str,
        hostname: str,
        pid: int,
        capabilities: dict[str, Any] | None = None,
        version: str | None = None,
        tenant_affinity: list[str] | None = None,
    ) -> WorkerHeartbeat:
        """Create or refresh a worker heartbeat row (UPSERT semantics).

        If a row with this ``worker_id`` already exists, its mutable
        fields (hostname, pid, capabilities, version, tenant_affinity)
        are updated and ``last_heartbeat_at`` is refreshed. ``started_at``
        is bumped to now on re-register, treating the prior row as a
        stale corpse from a previous incarnation.
        """
        now = _utcnow()
        existing = await session.get(WorkerHeartbeat, worker_id)
        if existing is None:
            row = WorkerHeartbeat(
                worker_id=worker_id,
                hostname=hostname,
                pid=pid,
                started_at=now,
                last_heartbeat_at=now,
                lease_count=0,
                capabilities=capabilities or {},
                version=version,
                tenant_affinity=tenant_affinity,
            )
            session.add(row)
        else:
            existing.hostname = hostname
            existing.pid = pid
            existing.capabilities = capabilities or {}
            existing.version = version
            existing.tenant_affinity = tenant_affinity
            existing.started_at = now
            existing.last_heartbeat_at = now
            session.add(existing)
            row = existing

        await session.commit()
        await session.refresh(row)
        return row

    @staticmethod
    async def heartbeat(
        session: AsyncSession,
        *,
        worker_id: str,
    ) -> bool:
        """Refresh ``last_heartbeat_at`` for an existing worker.

        Returns True if the row was updated, False if no row exists for
        this id (caller should re-register).
        """
        row = await session.get(WorkerHeartbeat, worker_id)
        if row is None:
            return False
        row.last_heartbeat_at = _utcnow()
        session.add(row)
        await session.commit()
        return True

    @staticmethod
    async def deregister(
        session: AsyncSession,
        *,
        worker_id: str,
    ) -> bool:
        """Delete the heartbeat row for a worker.

        Returns True if a row was deleted, False if none existed.
        """
        row = await session.get(WorkerHeartbeat, worker_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True

    @staticmethod
    async def list_active(
        session: AsyncSession,
        *,
        max_silence_seconds: int = 60,
    ) -> list[WorkerHeartbeat]:
        """Return workers whose heartbeat is fresher than the threshold.

        Default 60s aligns with the worker's 10s heartbeat cadence — a
        worker is "active" if it pinged within the last minute.
        """
        cutoff = _utcnow() - timedelta(seconds=max_silence_seconds)
        stmt = (
            select(WorkerHeartbeat)
            .where(WorkerHeartbeat.last_heartbeat_at >= cutoff)
            .order_by(WorkerHeartbeat.last_heartbeat_at.desc())  # type: ignore[union-attr]
        )
        result = await session.exec(stmt)
        return list(result.all())

    @staticmethod
    async def prune_stale(
        session: AsyncSession,
        *,
        max_silence_seconds: int = 600,
    ) -> int:
        """Delete heartbeat rows silent longer than the threshold.

        Returns the number of rows deleted. The default 600s (10min) is
        generous — the dispatcher's ``reclaim_expired_runs`` reclaims
        leases on a much shorter timer (lease_expires_at, typically 30s).
        Pruning here is bookkeeping only.
        """
        cutoff = _utcnow() - timedelta(seconds=max_silence_seconds)
        stmt = select(WorkerHeartbeat).where(
            WorkerHeartbeat.last_heartbeat_at < cutoff
        )
        result = await session.exec(stmt)
        stale = list(result.all())
        for row in stale:
            await session.delete(row)
        if stale:
            await session.commit()
        return len(stale)


__all__ = ["WorkerRegistry"]
