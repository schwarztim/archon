"""Signal service — durable signal queue for the resume path.

Owned by WS8. Closes Conflict 5 (Phase 2 of master plan).

Public surface
--------------

    send_signal(session, *, run_id, step_id, signal_type, payload) -> Signal
    consume_pending_signals(session, *, run_id, signal_types=None) -> list[Signal]
    peek_pending_signals(session, *, run_id, signal_types=None) -> list[Signal]

Atomicity model
---------------

``consume_pending_signals`` is the ONLY caller that mutates ``consumed_at``.
It uses a SELECT-then-UPDATE pattern bounded by the row primary key. Two
concurrent consumers cannot both flip the same row from NULL → now()
because the second UPDATE will see ``consumed_at IS NOT NULL`` and skip.

The implementation is dialect-portable:
  * SQLite serializes writes implicitly (single-writer engine).
  * PostgreSQL relies on row-level write locks: the SELECT picks ids,
    the UPDATE narrows to ``id IN (...) AND consumed_at IS NULL``,
    so the loser of the race observes a 0-row update and the rows it
    already returned are still safe (it can no longer flip them).

We deliberately avoid ``SELECT ... FOR UPDATE`` because SQLite doesn't
support it; the conditional UPDATE provides the same exactly-once guarantee
on both engines. See ``test_concurrent_consume_no_double_processing``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.approval import Signal


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------


async def send_signal(
    session: AsyncSession,
    *,
    run_id: UUID,
    step_id: str | None,
    signal_type: str,
    payload: dict[str, Any] | None = None,
) -> Signal:
    """Persist a new pending signal and return it.

    The caller is responsible for the surrounding commit. We flush so
    callers that need the row id immediately can use it without an
    intermediate commit.
    """
    if not signal_type or not isinstance(signal_type, str):
        raise ValueError("signal_type must be a non-empty string")

    sig = Signal(
        run_id=run_id,
        step_id=step_id,
        signal_type=signal_type,
        payload=payload or {},
    )
    session.add(sig)
    await session.flush()
    return sig


# ---------------------------------------------------------------------------
# peek (read without consuming)
# ---------------------------------------------------------------------------


async def peek_pending_signals(
    session: AsyncSession,
    *,
    run_id: UUID,
    signal_types: list[str] | None = None,
) -> list[Signal]:
    """Return pending (unconsumed) signals for a run without marking them.

    Useful for the dispatcher to make a routing decision before committing
    to consumption (e.g. to look at the most recent ``approval.granted``
    signal alongside an outstanding ``cancel`` signal).
    """
    stmt = (
        select(Signal)
        .where(Signal.run_id == run_id)
        .where(Signal.consumed_at.is_(None))
        .order_by(Signal.created_at.asc())
    )
    if signal_types:
        stmt = stmt.where(Signal.signal_type.in_(signal_types))

    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# consume (atomic SELECT + UPDATE)
# ---------------------------------------------------------------------------


async def consume_pending_signals(
    session: AsyncSession,
    *,
    run_id: UUID,
    signal_types: list[str] | None = None,
) -> list[Signal]:
    """Atomically claim and return pending signals for a run.

    Pattern:
      1. SELECT all pending rows for this run (filtered by signal_types
         if supplied) — ordered oldest-first.
      2. For each candidate, run a conditional UPDATE that flips
         ``consumed_at`` from NULL → now() *only if it is still NULL*.
      3. Collect the rows whose UPDATE actually mutated a row. The loser
         of any race sees rowcount == 0 and skips that row.

    Returns the rows we successfully claimed. The caller commits the
    surrounding transaction.
    """
    # Phase 1: candidate read.
    candidates = await peek_pending_signals(
        session, run_id=run_id, signal_types=signal_types
    )
    if not candidates:
        return []

    now = _utcnow()
    claimed: list[Signal] = []
    for sig in candidates:
        # Phase 2: conditional UPDATE bound by primary key + NULL check.
        # ``execute`` returns a CursorResult; rowcount tells us whether
        # WE were the writer who flipped this row.
        from sqlalchemy import update

        stmt = (
            update(Signal)
            .where(Signal.id == sig.id)
            .where(Signal.consumed_at.is_(None))
            .values(consumed_at=now)
        )
        result = await session.execute(stmt)
        if (result.rowcount or 0) > 0:
            # We won the race — refresh in-memory copy so the returned
            # object reflects the new consumed_at value.
            sig.consumed_at = now
            claimed.append(sig)
        # rowcount == 0 means another consumer flipped it first — skip silently.

    return claimed


__all__ = [
    "send_signal",
    "peek_pending_signals",
    "consume_pending_signals",
]
