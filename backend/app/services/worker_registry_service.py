"""Worker registration service (W2).

Provides the operational surface over the ``WorkerRegistration`` model:
UPSERT on boot, heartbeat refresh, drain/stale lifecycle, capability
matching, and listing.

The legacy ``WorkerHeartbeat`` table (managed by ``WorkerRegistry`` in
``worker_registry.py``) is preserved for backwards compatibility. This
module operates exclusively on ``WorkerRegistration``.

All datetime values use naive UTC (``datetime.now(timezone.utc).replace(tzinfo=None)``)
to match the project pattern established in ``worker_registry.py`` and
``task_queues.py``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.worker_registry import WorkerRegistration

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC timestamp — matches WorkerRegistration column type."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def register_worker(
    session: AsyncSession,
    *,
    worker_name: str,
    tenant_id: UUID,
    queue_names: list[str],
    capabilities: list[str],
    max_concurrency: int,
    version: str,
    environment: str = "production",
    deployment_id: str | None = None,
) -> WorkerRegistration:
    """UPSERT a WorkerRegistration row by ``(worker_name, tenant_id)``.

    If a row already exists for this (worker_name, tenant_id) pair, its
    mutable fields are refreshed and ``started_at`` / ``last_heartbeat_at``
    are bumped to now. Status is reset to 'active' — a re-registering worker
    is assumed to have just started.

    Returns the up-to-date ``WorkerRegistration`` row.
    """
    now = _utcnow()

    stmt = (
        select(WorkerRegistration)
        .where(WorkerRegistration.worker_name == worker_name)
        .where(WorkerRegistration.tenant_id == tenant_id)
        .limit(1)
    )
    result = await session.exec(stmt)
    existing = result.first()

    if existing is None:
        row = WorkerRegistration(
            tenant_id=tenant_id,
            worker_name=worker_name,
            worker_version=version,
            environment=environment,
            queue_names=queue_names,
            capabilities=capabilities,
            max_concurrency=max_concurrency,
            started_at=now,
            last_heartbeat_at=now,
            status="active",
            deployment_id=deployment_id,
            current_load=0,
            in_flight_task_count=0,
        )
        session.add(row)
    else:
        existing.worker_version = version
        existing.environment = environment
        existing.queue_names = queue_names
        existing.capabilities = capabilities
        existing.max_concurrency = max_concurrency
        existing.started_at = now
        existing.last_heartbeat_at = now
        existing.status = "active"
        existing.deployment_id = deployment_id
        existing.current_load = 0
        existing.in_flight_task_count = 0
        session.add(existing)
        row = existing

    await session.commit()
    await session.refresh(row)
    log.info(
        "worker_registration.upserted",
        worker_name=worker_name,
        worker_id=str(row.id),
        tenant_id=str(tenant_id),
    )
    return row


async def heartbeat(
    session: AsyncSession,
    *,
    worker_id: UUID,
    in_flight_count: int = 0,
    load: int = 0,
) -> None:
    """Refresh liveness columns on an existing WorkerRegistration row.

    Updates ``last_heartbeat_at``, ``in_flight_task_count``, and
    ``current_load``. No-ops (with a warning log) when the worker_id is
    not found — the caller (worker boot loop) handles re-registration.
    """
    row = await session.get(WorkerRegistration, worker_id)
    if row is None:
        log.warning(
            "worker_registry_service.heartbeat_miss worker_id=%s",
            worker_id,
        )
        return

    row.last_heartbeat_at = _utcnow()
    row.in_flight_task_count = in_flight_count
    row.current_load = load
    session.add(row)
    await session.commit()


async def deregister_worker(
    session: AsyncSession,
    *,
    worker_id: UUID,
) -> None:
    """Set a worker's status to 'draining'.

    Draining workers finish in-flight tasks but do not accept new claims.
    The row is retained for observability; the stale sweep will eventually
    promote it to 'stale' if the heartbeat stops.
    """
    row = await session.get(WorkerRegistration, worker_id)
    if row is None:
        log.warning(
            "worker_registry_service.deregister_miss worker_id=%s",
            worker_id,
        )
        return

    row.status = "draining"
    session.add(row)
    await session.commit()
    log.info(
        "worker_registration.draining",
        worker_id=str(worker_id),
        worker_name=row.worker_name,
    )


async def sweep_stale_workers(
    session: AsyncSession,
    *,
    threshold_seconds: int = 60,
) -> list[UUID]:
    """Find workers whose heartbeat has exceeded the threshold and mark them stale.

    Only ``active`` workers are promoted to ``stale`` — draining workers
    are already winding down and their liveness signal is expected to decay.

    Returns the list of worker IDs that were marked stale so the caller
    can trigger lease reclamation.
    """
    cutoff = _utcnow()
    from datetime import timedelta  # local import avoids top-level clutter

    cutoff = cutoff - timedelta(seconds=threshold_seconds)

    stmt = (
        select(WorkerRegistration)
        .where(WorkerRegistration.status == "active")
        .where(WorkerRegistration.last_heartbeat_at < cutoff)
    )
    result = await session.exec(stmt)
    stale_rows = list(result.all())

    stale_ids: list[UUID] = []
    for row in stale_rows:
        row.status = "stale"
        session.add(row)
        stale_ids.append(row.id)

    if stale_rows:
        await session.commit()
        log.info(
            "worker_registry_service.stale_sweep",
            count=len(stale_ids),
            threshold_seconds=threshold_seconds,
        )

    return stale_ids


async def list_workers(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    status_filter: str | None = None,
) -> list[WorkerRegistration]:
    """Return WorkerRegistration rows for a given tenant.

    When ``status_filter`` is provided, only rows with that status are
    returned. Ordered by ``started_at`` descending (newest first).
    """
    stmt = select(WorkerRegistration).where(
        WorkerRegistration.tenant_id == tenant_id
    )
    if status_filter is not None:
        stmt = stmt.where(WorkerRegistration.status == status_filter)
    stmt = stmt.order_by(WorkerRegistration.started_at.desc())  # type: ignore[union-attr]

    result = await session.exec(stmt)
    return list(result.all())


async def check_capability(
    session: AsyncSession,
    *,
    worker_id: UUID,
    required_capability: str,
) -> bool:
    """Return True when the worker's capabilities list contains the required item.

    Returns False for missing workers or when the capability is absent.
    """
    row = await session.get(WorkerRegistration, worker_id)
    if row is None:
        return False
    caps: list[Any] = row.capabilities or []
    return required_capability in caps


__all__ = [
    "check_capability",
    "deregister_worker",
    "heartbeat",
    "list_workers",
    "register_worker",
    "sweep_stale_workers",
]
