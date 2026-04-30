"""Run-lifecycle primitives: claim, lease, release, reclaim.

Owned by WS3 — Durable Execution Squad. These helpers implement the
optimistic-lock claim + lease-renewal substrate described in ADR-001
(unified run table) and used by ``run_dispatcher`` to coordinate
multiple worker replicas without losing or double-executing runs.

Public surface
--------------

- ``claim_run(...)``      atomic claim from queued/pending → running
- ``renew_lease(...)``    extend the lease window for an owned run
- ``release_lease(...)``  clear lease fields on a still-owned run
- ``reclaim_expired_runs(...)`` return abandoned runs to the queue

All functions are async and operate on a SQLAlchemy AsyncSession. The
caller is responsible for the surrounding transaction; each helper
``flush``es its UPDATE so the row state is observable, and ``commit``s
when it owns the session entirely (claim_run / reclaim_expired_runs).

Concurrency contract
--------------------

The claim step uses a ``WHERE status IN (...) AND (lease_expires_at IS
NULL OR lease_expires_at < now)`` predicate inside an UPDATE so two
workers racing for the same run are arbitrated by the database — the
loser sees ``rowcount == 0`` and ``claim_run`` returns ``None``. We
double-check the post-condition by reloading the row and confirming the
lease_owner matches the worker_id we attempted, which closes the
race window where another worker also satisfied the predicate but
committed first.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import WorkflowRun

log = logging.getLogger(__name__)


# Default lease window — runs whose ``lease_expires_at`` is older than
# (now - lease_grace) without a heartbeat are considered abandoned and
# may be reclaimed by another worker.
DEFAULT_LEASE_TTL_SECONDS = 60


# ----------------------------------------------------------------------
# claim_run
# ----------------------------------------------------------------------


async def claim_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    worker_id: str,
    lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> WorkflowRun | None:
    """Atomically claim a queued/pending run for ``worker_id``.

    The UPDATE only matches rows where ``status`` is ``queued`` or
    ``pending`` AND the lease is unset or already expired. The matched
    row is moved to ``status='running'`` with the lease and timeline
    fields populated.

    Returns the freshly loaded ``WorkflowRun`` whose ``lease_owner``
    equals ``worker_id`` — or ``None`` if the claim was lost (another
    worker won, the row is in a terminal state, or the row does not
    exist).
    """
    now = datetime.utcnow()
    expires = now + timedelta(seconds=lease_ttl_seconds)

    stmt = (
        update(WorkflowRun)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.status.in_(["queued", "pending"]),
            (WorkflowRun.lease_expires_at.is_(None))
            | (WorkflowRun.lease_expires_at < now),
        )
        .values(
            status="running",
            claimed_at=now,
            lease_owner=worker_id,
            lease_expires_at=expires,
            attempt=WorkflowRun.attempt + 1,
        )
    )
    result = await session.execute(stmt)
    rowcount = result.rowcount or 0

    if rowcount != 1:
        # Either no row matched (lost race or terminal state), or an
        # implementation oddity where the UPDATE matched >1 row (impossible
        # with a primary-key predicate). Either way: claim lost.
        await session.commit()
        return None

    # Backfill started_at on the very first attempt of the run. We do
    # this in a second UPDATE so the COALESCE-equivalent is portable
    # across SQLite + Postgres without dialect-specific SQL.
    started_stmt = (
        update(WorkflowRun)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.started_at.is_(None),
        )
        .values(started_at=now)
    )
    await session.execute(started_stmt)
    await session.commit()

    # Re-read the canonical row state and verify the claim still belongs
    # to us (closes the post-commit race where a reaper could clobber
    # the lease in the gap between commits).
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.lease_owner != worker_id:
        return None
    return run


# ----------------------------------------------------------------------
# renew_lease
# ----------------------------------------------------------------------


async def renew_lease(
    session: AsyncSession,
    *,
    run_id: UUID,
    worker_id: str,
    lease_ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
) -> bool:
    """Extend the lease window for a run still owned by ``worker_id``.

    Returns ``True`` when the renewal succeeded (the row was still in
    ``status='running'`` with ``lease_owner == worker_id``); ``False``
    otherwise. A ``False`` result is the signal that ownership was
    revoked (the run was reclaimed, cancelled, or completed elsewhere)
    and the caller MUST stop work and abandon the row.
    """
    now = datetime.utcnow()
    expires = now + timedelta(seconds=lease_ttl_seconds)

    stmt = (
        update(WorkflowRun)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.lease_owner == worker_id,
            WorkflowRun.status == "running",
        )
        .values(lease_expires_at=expires)
    )
    result = await session.execute(stmt)
    await session.commit()
    rowcount = result.rowcount or 0
    return rowcount == 1


# ----------------------------------------------------------------------
# release_lease
# ----------------------------------------------------------------------


async def release_lease(
    session: AsyncSession,
    *,
    run_id: UUID,
    worker_id: str,
) -> None:
    """Clear lease fields on a run still owned by ``worker_id``.

    Idempotent: if the run is no longer owned by ``worker_id`` (because
    a reaper already reclaimed it, or the run has moved to a terminal
    state) the call silently no-ops.
    """
    stmt = (
        update(WorkflowRun)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.lease_owner == worker_id,
        )
        .values(lease_owner=None, lease_expires_at=None)
    )
    await session.execute(stmt)
    await session.commit()


# ----------------------------------------------------------------------
# reclaim_expired_runs
# ----------------------------------------------------------------------


async def reclaim_expired_runs(
    session: AsyncSession,
    *,
    lease_grace_seconds: int = 10,
) -> int:
    """Return abandoned ``running`` runs to the queue for re-pickup.

    A run is "abandoned" when ``status='running'`` and
    ``lease_expires_at < now - grace``. The grace window absorbs minor
    clock skew between worker replicas; the standard grace is short
    (10s) because ``lease_ttl_seconds`` is already the primary cushion.

    Returns the number of rows reset to ``queued``.
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=lease_grace_seconds)

    stmt = (
        update(WorkflowRun)
        .where(
            WorkflowRun.status == "running",
            WorkflowRun.lease_expires_at.isnot(None),
            WorkflowRun.lease_expires_at < cutoff,
        )
        .values(
            status="queued",
            lease_owner=None,
            lease_expires_at=None,
        )
    )
    result = await session.execute(stmt)
    await session.commit()
    return int(result.rowcount or 0)


__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "claim_run",
    "renew_lease",
    "release_lease",
    "reclaim_expired_runs",
]
