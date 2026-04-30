"""Approval service — typed lifecycle for human-in-loop approvals.

Owned by WS8. Closes Conflict 5 (Phase 2 of master plan) by replacing
the broken raw-SQL ``pending_approvals`` write with a model-backed
lifecycle that integrates with the hash-chained event log (ADR-002)
and the durable signal queue.

Public surface
--------------

    request_approval(session, *, run_id, step_id, tenant_id, payload,
                     expires_in_seconds=86400, requester_id=None) -> Approval

    grant_approval(session, *, approval_id, approver_id=None,
                   reason=None) -> tuple[Approval, Signal]

    reject_approval(session, *, approval_id, approver_id=None,
                    reason=None) -> tuple[Approval, Signal]

    expire_pending_approvals(session) -> int

    list_pending(session, *, tenant_id=None, requester_id=None,
                 limit=50) -> list[Approval]

    get_approval(session, approval_id) -> Approval | None

Lifecycle invariants
--------------------

  * ``request_approval`` flips the run's status to ``paused`` (sets
    ``paused_at``) AND inserts a row in ``approvals`` AND emits a
    hash-chained ``run.paused`` event — all in one transaction. Caller
    is responsible for the surrounding commit.

  * ``grant_approval`` / ``reject_approval`` set ``decided_at`` and
    write a single ``Signal`` row carrying the decision. ``grant_approval``
    additionally clears ``paused_at`` semantically by setting
    ``resumed_at`` and flipping status back to ``running`` — and emits
    ``run.resumed``. ``reject_approval`` leaves the run paused; the
    dispatcher (W2.4) decides whether to fail or take an alternate
    branch on resume — that is out of scope for this module.

  * ``expire_pending_approvals`` is a sweep helper. It takes the current
    ``utcnow()`` once and uses it as the decision timestamp on every row
    it transitions, so all rows in a single sweep land with deterministic
    ordering.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.approval import Approval, Signal
from app.models.workflow import WorkflowRun
from app.services import event_service, signal_service

# Reuse the existing async event-append helper used by the dispatcher
# and facade — it owns the hash chain logic and stays bit-for-bit
# identical to sync callers.
from app.services.execution_facade import _async_append_event

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# request_approval
# ---------------------------------------------------------------------------


async def request_approval(
    session: AsyncSession,
    *,
    run_id: UUID,
    step_id: str,
    tenant_id: UUID | None,
    payload: dict[str, Any] | None = None,
    expires_in_seconds: int = 86400,
    requester_id: UUID | None = None,
) -> Approval:
    """Open a pending approval request, pause the run, and emit run.paused.

    Returns the persisted ``Approval``. Caller commits.

    Raises:
        ValueError — run_id does not exist in workflow_runs.
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    now = _utcnow()
    expires_at: datetime | None = None
    if expires_in_seconds and expires_in_seconds > 0:
        expires_at = now + timedelta(seconds=expires_in_seconds)

    approval = Approval(
        run_id=run_id,
        step_id=step_id or "",
        tenant_id=tenant_id,
        requester_id=requester_id,
        status="pending",
        requested_at=now,
        expires_at=expires_at,
        payload=payload or {},
    )
    session.add(approval)
    await session.flush()

    # Pause the run: status + paused_at. Only flip if not already terminal.
    if run.status not in ("completed", "failed", "cancelled"):
        run.status = "paused"
        run.paused_at = now
        session.add(run)

    await _async_append_event(
        session,
        run_id,
        "run.paused",
        payload={
            "approval_id": str(approval.id),
            "step_id": step_id,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "reason": "awaiting_human_approval",
        },
        tenant_id=tenant_id,
        step_id=step_id or None,
    )

    logger.info(
        "approval_service.request_approval",
        extra={
            "approval_id": str(approval.id),
            "run_id": str(run_id),
            "step_id": step_id,
        },
    )
    return approval


# ---------------------------------------------------------------------------
# grant_approval / reject_approval
# ---------------------------------------------------------------------------


async def _decide(
    session: AsyncSession,
    *,
    approval_id: UUID,
    new_status: str,
    signal_type: str,
    approver_id: UUID | None,
    reason: str | None,
) -> tuple[Approval, Signal]:
    """Internal: apply a terminal decision (approved/rejected) to an Approval.

    Writes a ``Signal`` row carrying the decision, sets ``decided_at`` and
    ``approver_id`` / ``decision_reason`` on the approval.
    """
    if new_status not in ("approved", "rejected", "expired"):
        raise ValueError(f"invalid terminal status {new_status!r}")

    approval: Approval | None = await session.get(Approval, approval_id)
    if approval is None:
        raise ValueError(f"approval {approval_id} not found")
    if approval.status != "pending":
        raise ValueError(
            f"approval {approval_id} is not pending (status={approval.status!r})"
        )

    now = _utcnow()
    approval.status = new_status
    approval.decided_at = now
    if approver_id is not None:
        approval.approver_id = approver_id
    if reason is not None:
        approval.decision_reason = reason
    session.add(approval)

    sig = await signal_service.send_signal(
        session,
        run_id=approval.run_id,
        step_id=approval.step_id or None,
        signal_type=signal_type,
        payload={
            "approval_id": str(approval.id),
            "approver_id": str(approver_id) if approver_id else None,
            "reason": reason,
        },
    )

    return approval, sig


async def grant_approval(
    session: AsyncSession,
    *,
    approval_id: UUID,
    approver_id: UUID | None = None,
    reason: str | None = None,
) -> tuple[Approval, Signal]:
    """Mark an approval as approved + emit ``approval.granted`` + ``run.resumed``.

    The run row is moved from ``paused`` → ``running`` and ``resumed_at``
    is stamped so the dispatcher's resume path can pick it up.
    """
    approval, sig = await _decide(
        session,
        approval_id=approval_id,
        new_status="approved",
        signal_type="approval.granted",
        approver_id=approver_id,
        reason=reason,
    )

    # Resume the run: clear paused state.
    run: WorkflowRun | None = await session.get(WorkflowRun, approval.run_id)
    if run is not None and run.status == "paused":
        now = _utcnow()
        run.status = "running"
        run.resumed_at = now
        session.add(run)

        await _async_append_event(
            session,
            run.id,
            "run.resumed",
            payload={
                "approval_id": str(approval.id),
                "step_id": approval.step_id,
                "signal_id": str(sig.id),
                "decision": "approved",
            },
            tenant_id=run.tenant_id,
            step_id=approval.step_id or None,
        )

    logger.info(
        "approval_service.grant_approval",
        extra={
            "approval_id": str(approval.id),
            "run_id": str(approval.run_id),
            "signal_id": str(sig.id),
        },
    )
    return approval, sig


async def reject_approval(
    session: AsyncSession,
    *,
    approval_id: UUID,
    approver_id: UUID | None = None,
    reason: str | None = None,
) -> tuple[Approval, Signal]:
    """Mark an approval as rejected + emit ``approval.rejected``.

    The run remains paused — the dispatcher (W2.4) will decide on resume
    whether to fail the run or take an alternate branch. We do NOT emit
    ``run.resumed`` here because the run has not in fact resumed.
    """
    approval, sig = await _decide(
        session,
        approval_id=approval_id,
        new_status="rejected",
        signal_type="approval.rejected",
        approver_id=approver_id,
        reason=reason,
    )

    logger.info(
        "approval_service.reject_approval",
        extra={
            "approval_id": str(approval.id),
            "run_id": str(approval.run_id),
            "signal_id": str(sig.id),
        },
    )
    return approval, sig


# ---------------------------------------------------------------------------
# expire_pending_approvals
# ---------------------------------------------------------------------------


async def expire_pending_approvals(session: AsyncSession) -> int:
    """Transition pending approvals whose ``expires_at`` is in the past.

    For each row, marks status='expired', sets decided_at=now, and emits
    a corresponding ``approval.expired`` signal. Returns the number of
    rows transitioned. Caller commits.
    """
    now = _utcnow()
    stmt = (
        select(Approval)
        .where(Approval.status == "pending")
        .where(Approval.expires_at.is_not(None))
        .where(Approval.expires_at < now)
    )
    result = await session.execute(stmt)
    expiring = list(result.scalars().all())
    if not expiring:
        return 0

    count = 0
    for approval in expiring:
        approval.status = "expired"
        approval.decided_at = now
        if approval.decision_reason is None:
            approval.decision_reason = "expired"
        session.add(approval)
        await signal_service.send_signal(
            session,
            run_id=approval.run_id,
            step_id=approval.step_id or None,
            signal_type="approval.expired",
            payload={"approval_id": str(approval.id)},
        )
        count += 1

    logger.info(
        "approval_service.expire_pending_approvals",
        extra={"count": count},
    )
    return count


# ---------------------------------------------------------------------------
# read helpers
# ---------------------------------------------------------------------------


async def list_pending(
    session: AsyncSession,
    *,
    tenant_id: UUID | None = None,
    requester_id: UUID | None = None,
    limit: int = 50,
) -> list[Approval]:
    """List pending approvals, optionally scoped by tenant or requester."""
    stmt = select(Approval).where(Approval.status == "pending")
    if tenant_id is not None:
        stmt = stmt.where(Approval.tenant_id == tenant_id)
    if requester_id is not None:
        stmt = stmt.where(Approval.requester_id == requester_id)
    stmt = stmt.order_by(Approval.requested_at.asc()).limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_approval(
    session: AsyncSession, approval_id: UUID
) -> Approval | None:
    """Return an Approval by id, or None when missing."""
    return await session.get(Approval, approval_id)


__all__ = [
    "request_approval",
    "grant_approval",
    "reject_approval",
    "expire_pending_approvals",
    "list_pending",
    "get_approval",
]


# Sanity check at import time: confirm event_service has the events we
# emit. Better to fail loudly at startup than silently mis-emit during
# a paused run.
for _evt in ("run.paused", "run.resumed"):
    if _evt not in event_service.EVENT_TYPES:  # pragma: no cover - import guard
        raise RuntimeError(
            f"approval_service requires event_service.EVENT_TYPES to include "
            f"{_evt!r}; check ADR-002 alignment"
        )
