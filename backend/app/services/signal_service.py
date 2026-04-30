"""Signal service — durable signal queue for the resume path.

Owned by WS8. Closes Conflict 5 (Phase 2 of master plan).
Extended by W5 (Signals, Queries, and Updates) to add the vendor-neutral
durable message-passing surface.

Public surface
--------------

    # Original dispatcher-internal helpers
    send_signal(session, *, run_id, step_id, signal_type, payload) -> Signal
    consume_pending_signals(session, *, run_id, signal_types=None) -> list[Signal]
    peek_pending_signals(session, *, run_id, signal_types=None) -> list[Signal]

    # W5 additions — vendor-neutral durable message passing
    send_named_signal(session, *, run_id, signal_name, payload,
                      sender_id=None) -> Signal
    query_run_state(session, *, run_id) -> dict
    send_update(session, *, run_id, update_name, payload,
                sender_id=None) -> UpdateResult

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
from app.models.signal import UpdateResult


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


# ---------------------------------------------------------------------------
# W5 additions — vendor-neutral durable message-passing surface
# ---------------------------------------------------------------------------


async def send_named_signal(
    session: AsyncSession,
    *,
    run_id: UUID,
    signal_name: str,
    payload: dict[str, Any] | None = None,
    sender_id: str | None = None,
) -> Signal:
    """Persist a named signal for a run and return it.

    This is the W5 API surface for async fire-and-forget signals.
    Internally it delegates to ``send_signal`` using ``signal_name`` as
    the ``signal_type``.  The ``sender_id`` is stored in the payload so
    it survives without a schema change to the existing Signal table.

    The persisted Signal row IS the durable event history for this signal —
    consumers query ``peek_pending_signals`` / ``consume_pending_signals``
    to inspect or drain it.
    """
    merged_payload = dict(payload or {})
    if sender_id is not None:
        merged_payload.setdefault("sender_id", sender_id)

    return await send_signal(
        session,
        run_id=run_id,
        step_id=None,
        signal_type=signal_name,
        payload=merged_payload,
    )


# _UPDATE_HANDLERS is a lightweight in-process registry that maps
# update_name → callable(payload) -> dict.  An empty registry means all
# updates are accepted by default (open contract).  Register handlers via
# ``register_update_handler``.
_UPDATE_HANDLERS: dict[str, Any] = {}


def register_update_handler(
    update_name: str,
    handler: Any,
) -> None:
    """Register a validation + mutation handler for the given update_name.

    The handler is called with the request payload dict and must return a
    response dict.  If it raises ``ValueError``, the update is rejected
    and the error message is recorded in the UpdateResult row.
    """
    _UPDATE_HANDLERS[update_name] = handler


async def query_run_state(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> dict[str, Any]:
    """Read-only snapshot of a run's current state.

    Returns status, input_data, latest step outputs, pending signal names,
    and active (non-fired) timers.  Makes NO mutations.

    Raises:
        ValueError — run_id does not exist.
    """
    from app.models.workflow import WorkflowRun, WorkflowRunStep
    from app.models.timers import Timer

    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    # Latest step outputs — collect most recent step per step_id.
    steps_stmt = (
        select(WorkflowRunStep)
        .where(WorkflowRunStep.run_id == run_id)
        .order_by(WorkflowRunStep.created_at.asc())
    )
    steps_result = await session.execute(steps_stmt)
    steps = list(steps_result.scalars().all())

    # Collapse to latest-per-step_id snapshot.
    latest_steps: dict[str, dict[str, Any]] = {}
    for step in steps:
        latest_steps[step.step_id] = {
            "step_id": step.step_id,
            "name": step.name,
            "status": step.status,
            "output_data": step.output_data,
            "error": step.error,
        }

    # Pending signals (unconsumed).
    pending_sigs = await peek_pending_signals(session, run_id=run_id)

    # Active timers (pending, not fired/cancelled).
    timers_stmt = (
        select(Timer)
        .where(Timer.run_id == run_id)
        .where(Timer.status == "pending")
    )
    timers_result = await session.execute(timers_stmt)
    active_timers = [
        {
            "id": str(t.id),
            "purpose": t.purpose,
            "step_id": t.step_id,
            "fire_at": t.fire_at.isoformat() if t.fire_at else None,
        }
        for t in timers_result.scalars().all()
    ]

    return {
        "run_id": str(run_id),
        "status": run.status,
        "input_data": run.input_data or {},
        "step_outputs": latest_steps,
        "pending_signals": [s.signal_type for s in pending_sigs],
        "active_timers": active_timers,
    }


async def send_update(
    session: AsyncSession,
    *,
    run_id: UUID,
    update_name: str,
    payload: dict[str, Any] | None = None,
    sender_id: str | None = None,
) -> UpdateResult:
    """Validate and apply a synchronous state change, recording the result.

    If a handler is registered for ``update_name`` it is called with the
    request payload.  On success (no exception), an ``UpdateResult`` with
    status ``applied`` is persisted.  On ``ValueError`` from the handler,
    status is ``rejected`` and ``error_message`` is set.

    If no handler is registered, the update is accepted unconditionally
    (open contract — the caller is responsible for acting on the result).

    Returns the persisted ``UpdateResult``.  Caller commits.
    """
    from app.models.workflow import WorkflowRun

    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    request_payload = dict(payload or {})
    handler = _UPDATE_HANDLERS.get(update_name)

    status = "applied"
    response_payload: dict[str, Any] = {}
    error_message: str | None = None

    if handler is not None:
        try:
            result = handler(request_payload)
            response_payload = result if isinstance(result, dict) else {}
        except ValueError as exc:
            status = "rejected"
            error_message = str(exc)

    record = UpdateResult(
        run_id=run_id,
        tenant_id=run.tenant_id,
        update_name=update_name,
        sender_id=sender_id,
        request_payload=request_payload,
        response_payload=response_payload,
        status=status,
        error_message=error_message,
    )
    session.add(record)
    await session.flush()
    return record


__all__ = [
    "send_signal",
    "peek_pending_signals",
    "consume_pending_signals",
    "send_named_signal",
    "query_run_state",
    "send_update",
    "register_update_handler",
]
