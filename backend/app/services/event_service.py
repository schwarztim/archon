"""Hash-chained event log helpers for workflow_run_events.

Owned by WS1 — Data Model squad. Schema bound by ADR-002.

Public surface (route handlers come later in W1.5):
  - EVENT_TYPES — frozenset of the 15 valid event_type values
  - canonical_json(payload) — deterministic JSON serialisation
  - compute_hash(prev_hash, envelope) — sha256 chain link
  - append_event(...) — atomically append a single event
  - verify_hash_chain(session, run_id) — tamper-evidence check

Concurrency strategy (documented):
  Sequence assignment is serialised by the (run_id, sequence)
  UNIQUE constraint on workflow_run_events. Two concurrent appenders
  for the same run_id will race on MAX(sequence)+1; the loser sees an
  IntegrityError and must retry. SELECT ... FOR UPDATE on the parent
  workflow_runs row narrows the race window in PostgreSQL; SQLite
  serialises writes implicitly. This module provides the building
  block — the surrounding transaction is owned by the caller.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from app.models.workflow import WorkflowRunEvent

# ── Event type enumeration (ADR-002) ───────────────────────────────────

#: All allowed event_type values. Adding a new entry requires an ADR-002
#: amendment AND the matching CHECK constraint update on the
#: workflow_run_events table.
EVENT_TYPES: frozenset[str] = frozenset(
    {
        # Run-level (9)
        "run.created",
        "run.queued",
        "run.claimed",
        "run.started",
        "run.completed",
        "run.failed",
        "run.cancelled",
        "run.paused",
        "run.resumed",
        # Step-level (6)
        "step.started",
        "step.completed",
        "step.failed",
        "step.skipped",
        "step.retry",
        "step.paused",
    }
)


# ── Canonical JSON ─────────────────────────────────────────────────────


def canonical_json(payload: Any) -> str:
    """Serialise to deterministic JSON per ADR-002 rules.

    Rules (mandatory, no exceptions):
      - keys sorted lexicographically at every depth
      - no insignificant whitespace
      - UTF-8 bytes
      - ensure_ascii=False so non-ASCII characters are preserved verbatim

    The deterministic serialisation is what makes the hash chain
    reproducible across processes, machines, and Python versions.
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


# ── Hash chain ─────────────────────────────────────────────────────────


def _to_str(value: Any) -> str | None:
    """Coerce UUIDs to their canonical string form; pass through None/str."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def build_envelope(
    run_id: UUID | str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
    *,
    step_id: str | None,
    tenant_id: UUID | str | None,
    correlation_id: str | None,
    span_id: str | None,
) -> dict[str, Any]:
    """Construct the canonical envelope hashed for a single event.

    The envelope shape is fixed by ADR-002 §Hash chain. Adding fields
    here is a hash-breaking change — a versioned chain or migration
    is required.
    """
    return {
        "run_id": _to_str(run_id),
        "sequence": sequence,
        "event_type": event_type,
        "step_id": step_id,
        "tenant_id": _to_str(tenant_id),
        "correlation_id": correlation_id,
        "span_id": span_id,
        "payload": payload,
    }


def compute_hash(prev_hash: str | None, envelope: dict[str, Any]) -> str:
    """Compute sha256 of (prev_hash_bytes || canonical_json(envelope)).

    Returns lowercase hex (64 chars). For sequence=0, prev_hash is None
    and an empty byte string is prefixed. The byte concatenation order
    is fixed by ADR-002 — DO NOT swap it.
    """
    body = canonical_json(envelope).encode("utf-8")
    prev = b"" if prev_hash is None else bytes.fromhex(prev_hash)
    return hashlib.sha256(prev + body).hexdigest()


# ── Append (atomic per call, sequence assigned inside transaction) ────


def append_event(
    session: Session,
    run_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    *,
    tenant_id: UUID | None = None,
    step_id: str | None = None,
    correlation_id: str | None = None,
    span_id: str | None = None,
) -> WorkflowRunEvent:
    """Append a single event to the run's chain.

    Steps:
      1. Validate event_type against the closed enumeration.
      2. Read the prior event for this run (highest sequence) to extract
         prev_hash and prior sequence. (Sequence ordering is enforced by
         the UNIQUE(run_id, sequence) constraint, so the read is best-
         effort; concurrent inserts fail with IntegrityError.)
      3. Build envelope, compute current_hash.
      4. Insert the row. The caller commits the surrounding transaction.

    Raises:
      ValueError — unknown event_type.
      sqlalchemy.exc.IntegrityError — concurrent inserter won the race;
        the caller MUST roll back and retry.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(
            f"unknown event_type {event_type!r}; must be one of EVENT_TYPES "
            "(see ADR-002 for the canonical list)"
        )

    # Read prior event, if any. Use a lock-friendly query — SQLAlchemy
    # will pick up the dialect's row-locking semantics if the surrounding
    # transaction is configured for it.
    prior_stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .order_by(WorkflowRunEvent.sequence.desc())
        .limit(1)
    )
    prior = session.exec(prior_stmt).first()

    if prior is None:
        next_sequence = 0
        prev_hash: str | None = None
    else:
        next_sequence = prior.sequence + 1
        prev_hash = prior.current_hash

    envelope = build_envelope(
        run_id=run_id,
        sequence=next_sequence,
        event_type=event_type,
        payload=payload,
        step_id=step_id,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        span_id=span_id,
    )
    current_hash = compute_hash(prev_hash, envelope)

    event = WorkflowRunEvent(
        run_id=run_id,
        sequence=next_sequence,
        event_type=event_type,
        payload=payload,
        tenant_id=tenant_id,
        correlation_id=correlation_id,
        span_id=span_id,
        step_id=step_id,
        prev_hash=prev_hash,
        current_hash=current_hash,
    )
    session.add(event)
    session.flush()  # surface IntegrityError now, before the caller commits
    return event


# ── Verification ──────────────────────────────────────────────────────


def verify_hash_chain(session: Session, run_id: UUID) -> bool:
    """Re-hash every event for a run and confirm chain integrity.

    Returns True iff every event's recorded current_hash equals the
    re-computed hash from its prev_hash and envelope. A False result
    means the database row was tampered with after insert.

    The function is read-only and side-effect free.
    """
    events_stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .order_by(WorkflowRunEvent.sequence.asc())
    )
    events = session.exec(events_stmt).all()

    expected_prev: str | None = None
    expected_sequence = 0
    for event in events:
        # Sequence must be contiguous from 0.
        if event.sequence != expected_sequence:
            return False
        # prev_hash must match the previous event's current_hash (or None
        # for sequence=0).
        if event.prev_hash != expected_prev:
            return False
        envelope = build_envelope(
            run_id=event.run_id,
            sequence=event.sequence,
            event_type=event.event_type,
            payload=event.payload,
            step_id=event.step_id,
            tenant_id=event.tenant_id,
            correlation_id=event.correlation_id,
            span_id=event.span_id,
        )
        recomputed = compute_hash(event.prev_hash, envelope)
        if recomputed != event.current_hash:
            return False
        expected_prev = event.current_hash
        expected_sequence += 1

    return True


# ── Async helpers for SQLAlchemy AsyncSession callers (route handlers)

# The synchronous functions above support the standard sqlmodel.Session.
# Route handlers in this codebase use sqlalchemy.ext.asyncio.AsyncSession;
# adapters live in W1.5. Keeping the helper surface synchronous lets the
# pure-Python helpers (canonical_json, compute_hash, build_envelope,
# EVENT_TYPES) be reused unchanged on the async path.


__all__ = [
    "EVENT_TYPES",
    "append_event",
    "build_envelope",
    "canonical_json",
    "compute_hash",
    "verify_hash_chain",
]


# ── Reference: aggregate count helper for diagnostics ────────────────


def event_count(session: Session, run_id: UUID) -> int:
    """Return the number of events recorded for a run."""
    stmt = select(func.count()).select_from(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run_id
    )
    result = session.exec(stmt).one()
    # session.exec(...).one() may return a Row or scalar; coerce.
    if isinstance(result, tuple):
        return int(result[0])
    return int(result)
