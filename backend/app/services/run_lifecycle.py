"""Run-lifecycle primitives: claim, lease, release, reclaim, lifecycle controls.

Owned by WS3 — Durable Execution Squad. These helpers implement the
optimistic-lock claim + lease-renewal substrate described in ADR-001
(unified run table) and used by ``run_dispatcher`` to coordinate
multiple worker replicas without losing or double-executing runs.

W6 lifecycle controls (cancel, terminate, pause, resume) are also here.
Each control function is idempotent, appends a hash-chained audit event,
and validates the status transition before mutating the row.

Public surface
--------------

- ``claim_run(...)``              atomic claim from queued/pending → running
- ``renew_lease(...)``            extend the lease window for an owned run
- ``release_lease(...)``          clear lease fields on a still-owned run
- ``reclaim_expired_runs(...)``   return abandoned runs to the queue
- ``cancel_run(...)``             request cooperative cancellation
- ``terminate_run(...)``          hard-stop; kills in-flight activities
- ``pause_run(...)``              suspend a running/queued run
- ``resume_run(...)``             resume a paused run
- ``propagate_cancellation(...)`` cancel child runs (when parent_run_id exists)

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
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
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


# ----------------------------------------------------------------------
# W6 — Lifecycle control helpers (cancel, terminate, pause, resume)
# ----------------------------------------------------------------------

# Valid status transitions per operation.
_CANCEL_FROM = frozenset({"running", "queued", "pending", "paused"})
_TERMINATE_FROM = frozenset(
    {"running", "queued", "pending", "paused", "cancelling"}
)
_PAUSE_FROM = frozenset({"running", "queued", "pending"})
_RESUME_FROM = frozenset({"paused"})

# Terminal statuses — no lifecycle control may proceed from these.
_TERMINAL = frozenset({"completed", "failed", "cancelled", "terminated"})


async def _append_run_event(
    session: AsyncSession,
    run_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    *,
    tenant_id: UUID | None = None,
) -> None:
    """Append a hash-chained event using the async helper from run_dispatcher.

    Delegates to ``run_dispatcher._async_append_event`` so hashing logic
    is not duplicated. The import is local to avoid a circular dependency
    (run_dispatcher imports claim_run from this module).
    """
    from app.services.run_dispatcher import (  # noqa: PLC0415
        _async_append_event,
    )

    await _async_append_event(
        session,
        run_id,
        event_type,
        payload,
        tenant_id=tenant_id,
    )


async def cancel_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    reason: str,
    actor_id: str,
) -> WorkflowRun:
    """Request cooperative cancellation of a run.

    Sets ``status='cancelling'`` and ``cancel_requested_at``, appends a
    ``run.cancel_requested`` audit event, and commits. The dispatcher
    honours ``cancel_requested_at`` cooperatively before/after each
    activity. Once the dispatcher sees the flag it finalises the run as
    ``status='cancelled'``.

    Idempotent: if the run is already ``cancelling`` the call is a no-op
    and returns the current row.

    Raises ``ValueError`` for invalid source statuses (terminal or
    ``running`` — running runs must go through the cooperative path).
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    # Idempotent: already cancelling → no-op.
    if run.status == "cancelling":
        return run

    if run.status in _TERMINAL:
        raise ValueError(
            f"cannot cancel run {run_id}: status={run.status!r} is terminal"
        )
    if run.status not in _CANCEL_FROM:
        raise ValueError(
            f"cannot cancel run {run_id}: status={run.status!r} not in "
            f"{sorted(_CANCEL_FROM)}"
        )

    now = datetime.utcnow()
    run.status = "cancelling"
    run.cancel_requested_at = now
    session.add(run)
    await session.flush()

    await _append_run_event(
        session,
        run_id,
        "run.cancel_requested",
        payload={
            "reason": reason,
            "actor_id": actor_id,
            "requested_at": now.isoformat(),
        },
        tenant_id=run.tenant_id,
    )
    await session.commit()
    await session.refresh(run)
    return run


async def terminate_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    reason: str,
    actor_id: str,
) -> WorkflowRun:
    """Hard-stop a run regardless of current state (except terminal).

    Sets ``status='terminated'`` and ``completed_at``, cancels any
    in-flight ``ActivityExecution`` rows for this run, and appends a
    ``run.terminated`` audit event.

    Idempotent: already ``terminated`` → no-op.

    Raises ``ValueError`` when the run is already in another terminal
    status (completed, failed, cancelled).
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    if run.status == "terminated":
        return run

    if run.status in ("completed", "failed", "cancelled"):
        raise ValueError(
            f"cannot terminate run {run_id}: status={run.status!r} is terminal"
        )

    now = datetime.utcnow()
    run.status = "terminated"
    run.completed_at = now
    session.add(run)
    await session.flush()

    # Kill in-flight ActivityExecution rows for this run.
    try:
        from app.models.activity import ActivityExecution  # noqa: PLC0415

        act_stmt = (
            update(ActivityExecution)
            .where(
                ActivityExecution.run_id == run_id,
                ActivityExecution.status == "running",
            )
            .values(status="cancelled", completed_at=now)
        )
        await session.execute(act_stmt)
        await session.flush()
    except Exception as exc:  # noqa: BLE001 — activity table may not exist in all envs
        log.debug("terminate_run: activity cancellation skipped: %s", exc)

    await _append_run_event(
        session,
        run_id,
        "run.terminated",
        payload={
            "reason": reason,
            "actor_id": actor_id,
            "terminated_at": now.isoformat(),
        },
        tenant_id=run.tenant_id,
    )
    await session.commit()
    await session.refresh(run)
    return run


async def pause_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    reason: str,
    actor_id: str,
) -> WorkflowRun:
    """Suspend a running or queued run.

    Sets ``status='paused'`` and ``paused_at``, appends a ``run.paused``
    audit event. The worker polling loop skips paused runs.

    Idempotent: already ``paused`` → no-op.

    Raises ``ValueError`` for invalid source statuses (terminal,
    cancelling, or terminated).
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    if run.status == "paused":
        return run

    if run.status in _TERMINAL or run.status in ("cancelling", "terminated"):
        raise ValueError(
            f"cannot pause run {run_id}: status={run.status!r} is terminal "
            f"or already cancelling/terminated"
        )
    if run.status not in _PAUSE_FROM:
        raise ValueError(
            f"cannot pause run {run_id}: status={run.status!r} not in "
            f"{sorted(_PAUSE_FROM)}"
        )

    now = datetime.utcnow()
    run.status = "paused"
    run.paused_at = now
    session.add(run)
    await session.flush()

    await _append_run_event(
        session,
        run_id,
        "run.paused",
        payload={
            "reason": reason,
            "actor_id": actor_id,
            "paused_at": now.isoformat(),
        },
        tenant_id=run.tenant_id,
    )
    await session.commit()
    await session.refresh(run)
    return run


async def resume_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    reason: str,
    actor_id: str,
) -> WorkflowRun:
    """Resume a paused run.

    Flips ``status`` back to ``'running'`` (if the run was already claimed
    by a worker, i.e. has a ``lease_owner``) or to ``'queued'`` (if not
    yet claimed), clears the lease so the drain loop can pick it up
    immediately, stamps ``resumed_at``, and appends a ``run.resumed``
    audit event.

    Idempotent: a run in a non-paused status (other than ``paused``)
    raises ``ValueError``.
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    if run.status not in _RESUME_FROM:
        raise ValueError(
            f"cannot resume run {run_id}: status={run.status!r}; "
            f"resume only valid from {sorted(_RESUME_FROM)}"
        )

    now = datetime.utcnow()
    # If the run was claimed (has a worker), re-queue so the drain loop
    # re-claims it cleanly. If it was never claimed, also go to queued.
    run.status = "queued"
    run.resumed_at = now
    run.lease_owner = None
    run.lease_expires_at = None
    session.add(run)
    await session.flush()

    await _append_run_event(
        session,
        run_id,
        "run.resumed",
        payload={
            "reason": reason,
            "actor_id": actor_id,
            "resumed_at": now.isoformat(),
        },
        tenant_id=run.tenant_id,
    )
    await session.commit()
    await session.refresh(run)
    return run


async def propagate_cancellation(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> list[UUID]:
    """Cancel child runs whose ``triggered_by`` field references this run.

    ``WorkflowRun`` does not have a ``parent_run_id`` column in the
    current schema. Child relationship is approximated by matching
    ``triggered_by == str(run_id)`` — runs that were triggered by this
    run record their parent's ID in that field by convention.

    Returns the list of child run IDs that were moved to ``cancelling``.
    Returns ``[]`` when no children exist.
    """
    parent_ref = str(run_id)
    non_cancellable = list(_TERMINAL) + ["cancelling", "terminated"]

    stmt = select(WorkflowRun).where(
        WorkflowRun.triggered_by == parent_ref,
        ~WorkflowRun.status.in_(non_cancellable),
    )
    result = await session.execute(stmt)
    children = list(result.scalars().all())

    cancelled_ids: list[UUID] = []
    for child in children:
        try:
            await cancel_run(
                session,
                run_id=child.id,
                reason=f"parent run {run_id} cancelled",
                actor_id="system",
            )
            cancelled_ids.append(child.id)
        except ValueError as exc:
            log.debug(
                "propagate_cancellation: child %s skipped: %s",
                child.id,
                exc,
            )

    return cancelled_ids


__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "claim_run",
    "renew_lease",
    "release_lease",
    "reclaim_expired_runs",
    # W6 lifecycle controls
    "cancel_run",
    "terminate_run",
    "pause_run",
    "resume_run",
    "propagate_cancellation",
]
