"""Approval and Signal models — typed substrate for the human-in-loop pause/resume cycle.

Owned by WS8 — Signals/Approvals Squad. Phase 2 of the master plan.

Closes Conflict 5: replaces the broken raw-SQL ``pending_approvals`` write that
``humanApprovalNode`` was performing against a table that may not exist. This
module provides:

  - ``Approval`` — explicit lifecycle for a pending human decision
    (pending → approved/rejected/expired).

  - ``Signal`` — generic durable signal queue. The dispatcher consumes
    signals to decide whether a paused run can resume (approval granted,
    input provided, cancel injected, etc.).

Design notes
------------

Both tables are FK-bound to ``workflow_runs.id`` so cascading run deletes
clean them up. ``payload`` is JSON for forward-compatible domain data
(approver constraints, input field schema, custom signal bodies, etc.).

``Signal.consumed_at`` implements the "exactly-once consume" pattern: the
dispatcher's signal-consumer scans WHERE ``consumed_at IS NULL`` and
atomically updates the timestamp. Dual-readers cannot double-process a
signal as long as the UPDATE is bound by the row's primary key.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, Index  # noqa: F401 — Index used in Signal __table_args__
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class Approval(SQLModel, table=True):
    """A pending human approval request, gated by an explicit decision.

    Lifecycle:
      pending  → approved | rejected | expired

    The status column is the source of truth — every state mutation is
    accompanied by a matching ``Signal`` row written in the same
    transaction so the dispatcher's resume path is deterministic.

    Tenant scoping: ``tenant_id`` is set by the requesting code path
    (the human_approval node executor reads it from ``ctx.tenant_id``)
    and is the basis for cross-tenant isolation in the REST surface.

    Index policy:
      ``ix_approvals_run_id`` is declared exactly once — via
      ``index=True`` on the ``run_id`` Column below. Do NOT also add
      ``Index("ix_approvals_run_id", ...)`` in a ``__table_args__``
      tuple — SQLModel allows the duplicate names but Alembic / SQLite
      reject them at upgrade time.
    """

    __tablename__ = "approvals"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,  # creates ix_approvals_run_id — single source of truth
        )
    )
    step_id: str = Field(default="")
    tenant_id: UUID | None = Field(default=None, index=True)
    requester_id: UUID | None = Field(default=None)
    approver_id: UUID | None = Field(default=None)
    status: str = Field(default="pending", index=True)
    decision_reason: str | None = Field(default=None)
    requested_at: datetime = Field(default_factory=_utcnow)
    decided_at: datetime | None = Field(default=None)
    expires_at: datetime | None = Field(default=None)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )


class Signal(SQLModel, table=True):
    """Generic durable signal queue.

    Signal types in use today:
      - ``approval.granted``  — paired with ``Approval(status='approved')``
      - ``approval.rejected`` — paired with ``Approval(status='rejected')``
      - ``approval.expired``  — paired with ``Approval(status='expired')``
      - ``input.requested``   — emitted by ``humanInputNode`` when pausing
      - ``input.provided``    — operator-injected; resumes a humanInputNode
      - ``cancel``            — operator-injected; signals a paused run to abort
      - ``custom``            — extension point; payload defines semantics

    The dispatcher (W2.4) consumes signals atomically — consume_pending_signals
    flips ``consumed_at`` from NULL to now() and returns the rows so a single
    signal can never trigger two resume attempts.
    """

    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_run_id_consumed_at", "run_id", "consumed_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    step_id: str | None = Field(default=None)
    signal_type: str = Field(index=True)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    consumed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = ["Approval", "Signal"]
