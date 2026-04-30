"""Timer service — durable, restart-safe timers.

Owned by WS7 — Timers/Retries Squad. Provides the only supported entry
points for scheduling, draining, cancelling, and listing rows in the
``timers`` table (see ``app.models.timers.Timer`` and migration
0009_timers_table).

Atomicity contract (the heart of the module):
  ``fire_pending_timers`` MUST select-and-mark each due timer in a single
  transaction so that two concurrent dispatcher workers cannot drain the
  same row twice. The implementation uses a per-timer compare-and-swap
  UPDATE keyed on ``status='pending'``: only one updater wins, and the
  loser sees ``rowcount == 0`` and skips the row.

  This works on both Postgres and SQLite without dialect-specific
  ``SELECT ... FOR UPDATE SKIP LOCKED`` — SQLite implicitly serialises
  writes and Postgres' UPDATE is atomic on the row. The cost is one
  UPDATE round-trip per due row; on a hot dispatcher we'd batch via a
  single ``UPDATE ... RETURNING`` on Postgres, but for now the per-row
  CAS keeps the contract identical across engines.

This module performs NO event emission. Callers (W2.4 dispatcher) own
the surrounding ``workflow_run_events`` writes when a fired timer
resumes a run.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.timers import Timer

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC — matches Timer column type (TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.utcnow()


# ── schedule ────────────────────────────────────────────────────────────


async def schedule_timer(
    session: AsyncSession,
    *,
    run_id: UUID | None,
    step_id: str | None,
    fire_at: datetime,
    purpose: str,
    payload: dict[str, Any] | None = None,
) -> Timer:
    """Insert a new ``pending`` timer row.

    The caller is responsible for choosing ``fire_at`` (UTC). ``payload``
    is opaque to the timer service; the dispatcher reads it back when
    the timer fires (e.g. ``{"step_id": ..., "next_step": ...}``).

    Commits on success and refreshes the row.
    """
    timer = Timer(
        run_id=run_id,
        step_id=step_id,
        fire_at=fire_at,
        payload=payload or {},
        purpose=purpose,
        status="pending",
    )
    session.add(timer)
    await session.commit()
    await session.refresh(timer)
    log.debug(
        "timer.scheduled",
        extra={
            "timer_id": str(timer.id),
            "run_id": str(run_id) if run_id else None,
            "purpose": purpose,
            "fire_at": fire_at.isoformat(),
        },
    )
    return timer


# ── drain (atomic) ──────────────────────────────────────────────────────


async def fire_pending_timers(
    session: AsyncSession,
    *,
    batch_size: int = 100,
    now: datetime | None = None,
) -> list[Timer]:
    """Return — and mark fired — every due timer in this batch.

    Steps:
      1. SELECT up to ``batch_size`` rows where
         ``fire_at <= now AND status = 'pending'`` ordered by
         ``fire_at ASC`` (oldest first).
      2. For each candidate, run a CAS UPDATE that sets
         ``status='fired'`` and ``fired_at=now`` only if the row is
         still ``pending``. ``rowcount == 1`` means we won; ``0`` means
         a peer already drained it.
      3. Return only the rows we successfully marked. The caller acts
         on these — concurrent peers see disjoint result sets.

    The function commits once at the end; a partial batch (some peer
    won the race on some rows) is still durable.
    """
    fire_threshold = now or _utcnow()

    candidates_stmt = (
        select(Timer)
        .where(Timer.status == "pending")
        .where(Timer.fire_at <= fire_threshold)
        .order_by(Timer.fire_at.asc())  # type: ignore[union-attr]
        .limit(batch_size)
    )
    result = await session.exec(candidates_stmt)
    candidates: list[Timer] = list(result.all())

    fired: list[Timer] = []
    for timer in candidates:
        cas_stmt = (
            update(Timer)
            .where(Timer.id == timer.id)
            .where(Timer.status == "pending")
            .values(status="fired", fired_at=fire_threshold)
        )
        cas_result = await session.execute(cas_stmt)
        # rowcount: 1 if we won, 0 if a concurrent peer won first
        if (cas_result.rowcount or 0) == 1:
            # Reflect the new state on the in-memory object so callers
            # see ``status="fired"`` / ``fired_at`` without an extra
            # round-trip.
            timer.status = "fired"
            timer.fired_at = fire_threshold
            fired.append(timer)

    if fired:
        await session.commit()

    log.debug(
        "timer.batch_fired",
        extra={
            "candidate_count": len(candidates),
            "fired_count": len(fired),
            "batch_size": batch_size,
        },
    )
    return fired


# ── cancel ──────────────────────────────────────────────────────────────


async def cancel_timer(
    session: AsyncSession,
    *,
    timer_id: UUID,
) -> bool:
    """Mark a pending timer as cancelled (soft state flip — not DELETE).

    Returns True if a pending row was cancelled, False if the row was
    missing OR already in a terminal state (fired/cancelled). The CAS
    is on ``status='pending'`` so a fired-but-not-yet-acted-on timer
    is NOT cancellable — the caller must coordinate with the
    dispatcher in that race window.
    """
    cas_stmt = (
        update(Timer)
        .where(Timer.id == timer_id)
        .where(Timer.status == "pending")
        .values(status="cancelled")
    )
    result = await session.execute(cas_stmt)
    cancelled = (result.rowcount or 0) == 1
    if cancelled:
        await session.commit()
    return cancelled


# ── list ────────────────────────────────────────────────────────────────


async def list_pending(
    session: AsyncSession,
    *,
    run_id: UUID | None = None,
) -> list[Timer]:
    """Return all pending timers, optionally filtered by ``run_id``.

    When ``run_id`` is None the result is unfiltered (all pending
    timers system-wide). Used for diagnostics and the cancellation
    sweep when a run is cancelled.

    Sentinel: passing ``run_id=None`` is "no filter" — to query timers
    that have NULL run_id, use ``list_orphan_pending`` (not implemented
    here — extend when needed).
    """
    stmt = select(Timer).where(Timer.status == "pending")
    if run_id is not None:
        stmt = stmt.where(Timer.run_id == run_id)
    stmt = stmt.order_by(Timer.fire_at.asc())  # type: ignore[union-attr]

    result = await session.exec(stmt)
    return list(result.all())


__all__ = [
    "cancel_timer",
    "fire_pending_timers",
    "list_pending",
    "schedule_timer",
]
