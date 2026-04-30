"""Replay service — W10.

Provides event-log replay and hash-chain verification for WorkflowRuns.

Public surface:
  - reconstruct_state(session, *, run_id) -> dict
        Walk event history in sequence order and rebuild run state.
  - verify_event_chain(session, *, run_id) -> bool
        Verify hash-chain integrity (each event's prev_hash matches prior).
  - replay_to_event(session, *, run_id, target_sequence) -> dict
        Reconstruct state up to and including a specific sequence number.
  - compare_replay(session, *, run_id) -> dict
        Reconstruct vs current state; return diff.

All functions accept sqlalchemy.ext.asyncio.AsyncSession and are async.
Chain verification delegates to event_service.build_envelope and
event_service.compute_hash so the hash logic is not duplicated.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import WorkflowRun, WorkflowRunEvent
from app.services import event_service

log = logging.getLogger(__name__)


async def reconstruct_state(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> dict[str, Any]:
    """Reconstruct run state by walking the event log from sequence 0.

    Applies each event's payload to an accumulator dict in sequence order.
    Returns the final accumulated state dict.

    Raises ValueError if the run does not exist.
    """
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    events = await _load_events(session, run_id)
    return _apply_events(run, events)


async def verify_event_chain(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> bool:
    """Verify the hash-chain integrity for all events on a run.

    Re-hashes every event using the same envelope + compute_hash logic
    as the original writer (event_service). Returns True iff every
    recorded current_hash equals the re-computed value.

    A False result means a database row was tampered with after insert.

    Raises ValueError if the run does not exist.
    """
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    events = await _load_events(session, run_id)

    expected_prev: str | None = None
    expected_sequence = 0

    for event in events:
        if event.sequence != expected_sequence:
            log.warning(
                "verify_event_chain: sequence gap at %d (expected %d) for run %s",
                event.sequence,
                expected_sequence,
                run_id,
            )
            return False

        if event.prev_hash != expected_prev:
            log.warning(
                "verify_event_chain: prev_hash mismatch at sequence %d for run %s",
                event.sequence,
                run_id,
            )
            return False

        envelope = event_service.build_envelope(
            run_id=event.run_id,
            sequence=event.sequence,
            event_type=event.event_type,
            payload=event.payload,
            step_id=event.step_id,
            tenant_id=event.tenant_id,
            correlation_id=event.correlation_id,
            span_id=event.span_id,
        )
        recomputed = event_service.compute_hash(event.prev_hash, envelope)
        if recomputed != event.current_hash:
            log.warning(
                "verify_event_chain: hash mismatch at sequence %d for run %s "
                "(stored=%s recomputed=%s)",
                event.sequence,
                run_id,
                event.current_hash[:16],
                recomputed[:16],
            )
            return False

        expected_prev = event.current_hash
        expected_sequence += 1

    return True


async def replay_to_event(
    session: AsyncSession,
    *,
    run_id: UUID,
    target_sequence: int,
) -> dict[str, Any]:
    """Reconstruct run state up to and including target_sequence.

    Useful for point-in-time debugging. Returns the accumulated state
    dict after applying events 0 … target_sequence (inclusive).

    Raises ValueError if the run does not exist or target_sequence is
    negative.
    """
    if target_sequence < 0:
        raise ValueError(
            f"target_sequence must be >= 0, got {target_sequence}"
        )

    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    events = await _load_events(session, run_id)
    # Include only events up to and including the target sequence.
    events_to_replay = [e for e in events if e.sequence <= target_sequence]
    return _apply_events(run, events_to_replay)


async def compare_replay(
    session: AsyncSession,
    *,
    run_id: UUID,
) -> dict[str, Any]:
    """Compare reconstructed state against current WorkflowRun row state.

    Returns a dict with:
      - reconstructed: the state rebuilt from the event log
      - current: relevant fields from the live WorkflowRun row
      - diff: keys where the values differ between the two
      - chain_valid: bool — result of verify_event_chain
    """
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    events = await _load_events(session, run_id)
    reconstructed = _apply_events(run, events)

    current = {
        "status": run.status,
        "input_data": run.input_data,
        "output_data": run.output_data,
        "error": run.error,
        "error_code": run.error_code,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }

    diff: dict[str, Any] = {}
    for key in current:
        rec_val = reconstructed.get(key)
        cur_val = current[key]
        if rec_val != cur_val:
            diff[key] = {"reconstructed": rec_val, "current": cur_val}

    chain_valid = await verify_event_chain(session, run_id=run_id)

    return {
        "reconstructed": reconstructed,
        "current": current,
        "diff": diff,
        "chain_valid": chain_valid,
    }


# ── Internal helpers ──────────────────────────────────────────────────


async def _load_events(
    session: AsyncSession,
    run_id: UUID,
) -> list[WorkflowRunEvent]:
    """Load all events for a run ordered by sequence ascending."""
    stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .order_by(WorkflowRunEvent.sequence.asc())
    )
    result = await session.exec(stmt)
    return list(result.all())


def _apply_events(
    run: WorkflowRun,
    events: list[WorkflowRunEvent],
) -> dict[str, Any]:
    """Apply event payloads to reconstruct run state.

    Starts from the run's initial snapshot (input_data, kind, etc.)
    and overlays fields from each event's payload in sequence order.

    The resulting dict represents the run's logical state as of the
    last event applied.
    """
    state: dict[str, Any] = {
        "run_id": str(run.id),
        "kind": run.kind,
        "status": "pending",
        "input_data": run.input_data,
        "output_data": None,
        "error": None,
        "error_code": None,
        "started_at": None,
        "completed_at": None,
        "events_applied": [],
    }

    # Status progression mapping based on event type.
    _STATUS_FROM_EVENT = {
        "run.created": "created",
        "run.queued": "queued",
        "run.claimed": "running",
        "run.started": "running",
        "run.completed": "completed",
        "run.failed": "failed",
        "run.cancelled": "cancelled",
        "run.paused": "paused",
        "run.resumed": "queued",
        "run.cancel_requested": "cancelling",
        "run.terminated": "terminated",
    }

    for event in events:
        state["events_applied"].append(
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
            }
        )

        # Update status from run-level events.
        if event.event_type in _STATUS_FROM_EVENT:
            state["status"] = _STATUS_FROM_EVENT[event.event_type]

        payload = event.payload or {}

        # Extract well-known fields from payloads.
        if event.event_type == "run.started":
            state["started_at"] = payload.get("started_at")
        elif event.event_type in ("run.completed", "run.failed",
                                   "run.cancelled", "run.terminated"):
            state["completed_at"] = payload.get("completed_at") or payload.get(
                "terminated_at"
            )
            if "output_data" in payload:
                state["output_data"] = payload["output_data"]
            if "error" in payload:
                state["error"] = payload["error"]
            if "error_code" in payload:
                state["error_code"] = payload["error_code"]

    return state


__all__ = [
    "compare_replay",
    "reconstruct_state",
    "replay_to_event",
    "verify_event_chain",
]
