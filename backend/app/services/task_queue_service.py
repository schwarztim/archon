"""Task queue service — durable activity queue helpers (W1).

Owned by W1 (Queue Data Model + APIs squad). Closes Wave 1 of the
durable orchestration plan: provides the small SQL surface that W1.5
(dispatcher polling), W3 (activity runtime), and the ExecutionFacade
build against.

Public surface
--------------

    enqueue_task(session, *, tenant_id, run_id, queue_name,
                 task_type, ..., commit=False) -> Task
        Insert a new ``Task`` row in the same transaction as the caller.
        Used by ``ExecutionFacade`` when a workflow step yields an
        activity. Caller controls the commit boundary (``commit=False``
        by default — the run write and the task write must be atomic).

    select_pending_tasks(session, *, tenant_id, queue_names, limit,
                         now=None) -> list[Task]
        Polling helper for the W1.5 dispatcher. Returns up to ``limit``
        tasks with ``status='visible'`` and ``visible_at <= now`` from
        the named queues, ordered by ``(priority DESC, visible_at ASC,
        id ASC)`` so concurrent pollers see a stable sort. Read-only;
        does NOT mutate state — the caller follows up with
        ``claim_task`` to actually take ownership.

    claim_task(session, *, task_id, lease_owner, lease_ttl_seconds,
               now=None) -> Task | None
        Atomic compare-and-swap claim. Flips ``status='visible' →
        'claimed'``, increments ``attempts``, stamps ``lease_owner`` +
        ``lease_expiration`` in a single ``UPDATE ... WHERE
        status='visible'`` so concurrent claimants cannot double-pull.
        Returns the refreshed row on success, ``None`` when another
        worker beat us to the row.

Atomicity notes
---------------

Both ``select_pending_tasks`` and ``claim_task`` are dialect-portable.
SQLite serialises writes implicitly (single-writer engine), and
PostgreSQL relies on row-level write locks: the conditional UPDATE in
``claim_task`` narrows by primary key AND ``status='visible'`` so the
loser of a race observes a 0-row update and falls through to the next
candidate. We deliberately avoid ``SELECT ... FOR UPDATE SKIP LOCKED``
because SQLite does not support it; the conditional UPDATE provides the
same exactly-once guarantee on both engines.

This module performs NO event emission. The dispatcher (W1.5) and the
ExecutionFacade own their own ``workflow_run_events`` writes when a task
is enqueued, claimed, completed, or failed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.task_queue import Task

log = logging.getLogger(__name__)

# Lazy import so metrics_service never creates a circular dependency.
def _metrics():
    from app.services import metrics_service  # noqa: PLC0415
    return metrics_service


def _utcnow() -> datetime:
    """Naive UTC for TIMESTAMP WITHOUT TIME ZONE columns (matches model)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# enqueue_task
# ---------------------------------------------------------------------------


async def enqueue_task(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    run_id: UUID,
    queue_name: str,
    task_type: str,
    step_id: UUID | None = None,
    payload_ref: str | None = None,
    visible_at: datetime | None = None,
    priority: int = 100,
    idempotency_key: str | None = None,
    commit: bool = False,
) -> Task:
    """Insert a new Task row.

    The default ``status`` is ``'visible'`` so it shows up immediately to
    the next ``select_pending_tasks`` poll — callers that want delayed
    delivery should pass ``visible_at`` in the future and the dispatcher
    will skip it until then.

    The ExecutionFacade writes the task in the same transaction as the
    WorkflowRun row, so by default we ``flush`` (to surface integrity
    errors at the call site) but do not commit. Pass ``commit=True`` for
    standalone test/admin paths.
    """
    if not queue_name:
        raise ValueError("queue_name must be a non-empty string")
    if not task_type:
        raise ValueError("task_type must be a non-empty string")

    task = Task(
        id=uuid4(),
        tenant_id=tenant_id,
        run_id=run_id,
        step_id=step_id,
        queue_name=queue_name,
        task_type=task_type,
        payload_ref=payload_ref,
        status="visible",
        visible_at=visible_at or _utcnow(),
        priority=priority,
        idempotency_key=idempotency_key,
    )
    session.add(task)
    await session.flush()
    if commit:
        await session.commit()
        await session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# select_pending_tasks
# ---------------------------------------------------------------------------


async def select_pending_tasks(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    queue_names: Sequence[str],
    limit: int,
    now: datetime | None = None,
) -> list[Task]:
    """Polling helper for W1.5 dispatcher.

    Selects up to ``limit`` tasks with ``status='visible'`` and
    ``visible_at <= now`` from the named queues, ordered by
    ``(priority DESC, visible_at ASC, id ASC)`` to ensure stable
    ordering under concurrent pollers.

    Returns an empty list when ``queue_names`` is empty (no implicit
    "poll all queues" — callers must declare the queues they consume so
    capability matching stays explicit).
    """
    if limit <= 0:
        return []
    queues = list(queue_names)
    if not queues:
        return []

    cutoff = now or _utcnow()

    # Column order matches ``ix_task_polling`` so the index can serve
    # the predicate without a sort step. We then ORDER BY priority DESC,
    # visible_at ASC, id ASC for stable ranking; SQLite/Postgres cannot
    # use the polling index for the descending-priority order, but the
    # WHERE clause still narrows to a small candidate set.
    stmt = (
        select(Task)
        .where(Task.tenant_id == tenant_id)
        .where(Task.queue_name.in_(queues))
        .where(Task.status == "visible")
        .where(Task.visible_at <= cutoff)
        .order_by(
            Task.priority.desc(),
            Task.visible_at.asc(),
            Task.id.asc(),
        )
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# claim_task
# ---------------------------------------------------------------------------


async def claim_task(
    session: AsyncSession,
    *,
    task_id: UUID,
    lease_owner: str,
    lease_ttl_seconds: int = 60,
    now: datetime | None = None,
) -> Task | None:
    """Atomically claim a single task for ``lease_owner``.

    Implementation: a single conditional UPDATE keyed on
    ``id=? AND status='visible'``. Two concurrent claims serialize on
    the row write — only one observes ``rowcount > 0`` and gets the
    refreshed row; the loser sees ``rowcount == 0`` and gets ``None``.

    Returns the refreshed ``Task`` on success, ``None`` if the row no
    longer exists or another worker beat us. Caller commits.
    """
    if not lease_owner:
        raise ValueError("lease_owner must be a non-empty string")
    if lease_ttl_seconds <= 0:
        raise ValueError("lease_ttl_seconds must be positive")

    cutoff = now or _utcnow()
    expiration = cutoff + timedelta(seconds=lease_ttl_seconds)

    stmt = (
        update(Task)
        .where(Task.id == task_id)
        .where(Task.status == "visible")
        .values(
            status="claimed",
            lease_owner=lease_owner,
            lease_expiration=expiration,
            attempts=Task.attempts + 1,
            updated_at=cutoff,
        )
    )
    result = await session.execute(stmt)
    if result.rowcount == 0:
        return None

    # Refresh: the conditional UPDATE doesn't return the row on SQLite,
    # so we re-read by id. We use a fresh ``get`` to bypass any
    # identity-map staleness.
    refreshed: Task | None = await session.get(Task, task_id)
    if refreshed is not None:
        await session.refresh(refreshed)
    _metrics().record_task_claimed(queue_name=getattr(refreshed, "queue_name", "unknown") if refreshed else "unknown")
    return refreshed


# ---------------------------------------------------------------------------
# complete_task
# ---------------------------------------------------------------------------


async def complete_task(
    session: AsyncSession,
    *,
    task_id: UUID,
    output_ref: str | None = None,
    now: datetime | None = None,
) -> None:
    """Mark a claimed task as completed.

    No-op when the task is already in a terminal status (idempotent).
    Caller commits.
    """
    cutoff = now or _utcnow()
    # Read queue_name before we update so we can label the metric.
    row: Task | None = await session.get(Task, task_id)
    queue_name = getattr(row, "queue_name", "unknown") if row else "unknown"
    stmt = (
        update(Task)
        .where(Task.id == task_id)
        .where(Task.status == "claimed")
        .values(
            status="completed",
            payload_ref=output_ref,
            lease_owner=None,
            lease_expiration=None,
            updated_at=cutoff,
        )
    )
    await session.execute(stmt)
    _metrics().record_task_completed(queue_name=queue_name)


# ---------------------------------------------------------------------------
# fail_task
# ---------------------------------------------------------------------------


async def fail_task(
    session: AsyncSession,
    *,
    task_id: UUID,
    error_code: str | None = None,
    now: datetime | None = None,
) -> None:
    """Mark a claimed task as failed.

    Increments ``attempts`` (already incremented at claim time, so this
    records the terminal attempt count). Clears the lease. Caller commits.
    """
    cutoff = now or _utcnow()
    row: Task | None = await session.get(Task, task_id)
    queue_name = getattr(row, "queue_name", "unknown") if row else "unknown"
    stmt = (
        update(Task)
        .where(Task.id == task_id)
        .where(Task.status == "claimed")
        .values(
            status="failed",
            lease_owner=None,
            lease_expiration=None,
            updated_at=cutoff,
        )
    )
    await session.execute(stmt)
    _metrics().record_task_failed(queue_name=queue_name)


# ---------------------------------------------------------------------------
# release_task
# ---------------------------------------------------------------------------


async def release_task(
    session: AsyncSession,
    *,
    task_id: UUID,
    now: datetime | None = None,
) -> None:
    """Release a claimed task back to 'visible' for retry.

    Used when a transient error occurs and the task should be retried by
    the next polling worker. Clears the lease without incrementing
    attempts (the claim already did that). Caller commits.
    """
    cutoff = now or _utcnow()
    stmt = (
        update(Task)
        .where(Task.id == task_id)
        .where(Task.status == "claimed")
        .values(
            status="visible",
            lease_owner=None,
            lease_expiration=None,
            updated_at=cutoff,
        )
    )
    await session.execute(stmt)


# ---------------------------------------------------------------------------
# claim_next_task  (convenience composite: select + claim)
# ---------------------------------------------------------------------------


async def claim_next_task(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    queue_names: list[str],
    worker_id: str,
    lease_ttl_seconds: int = 30,
    now: datetime | None = None,
) -> "Task | None":
    """Select the highest-priority visible task and atomically claim it.

    This is a convenience wrapper around ``select_pending_tasks`` + ``claim_task``
    that retries down the candidate list when another worker beats us to the
    first candidate. Returns the claimed ``Task`` on success, ``None`` when
    no eligible tasks exist or all candidates were claimed before us.

    Used by the W1.5 dispatcher as the primary claim path. The fallback to
    the legacy ``WorkflowRun`` drain is in the dispatcher layer.
    """
    if not queue_names:
        return None

    cutoff = now or _utcnow()
    candidates = await select_pending_tasks(
        session,
        tenant_id=tenant_id,
        queue_names=queue_names,
        limit=10,  # small batch to reduce contention; re-polls on next tick
        now=cutoff,
    )

    for candidate in candidates:
        claimed = await claim_task(
            session,
            task_id=candidate.id,
            lease_owner=worker_id,
            lease_ttl_seconds=lease_ttl_seconds,
            now=cutoff,
        )
        if claimed is not None:
            return claimed

    return None


__all__ = [
    "claim_next_task",
    "claim_task",
    "complete_task",
    "enqueue_task",
    "fail_task",
    "release_task",
    "select_pending_tasks",
]
