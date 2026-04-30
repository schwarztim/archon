"""Timer model — durable, restart-safe timer records.

Owned by WS7 — Timers/Retries Squad. Schema is bound by migration
0009_timers_table. Every timer scheduled via ``timer_service.schedule_timer``
inserts one row here; the worker drains fired rows in batch and resumes the
corresponding workflow run.

Design notes:
  - Independent of ``workflow_runs`` — ``run_id`` is nullable so the table
    also supports system-level timers (e.g. lease renewal sweeps) that have
    no associated run.
  - ``status`` follows a closed three-state machine: ``pending → fired`` or
    ``pending → cancelled``. There is no fired→cancelled transition.
  - ``fire_at`` is the only column the dispatcher sweeps on; it is indexed
    independently so the SELECT-WHERE-fire_at <= now scan stays cheap as the
    table grows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC — matches WorkflowRun / WorkerHeartbeat column type."""
    return datetime.utcnow()


class Timer(SQLModel, table=True):
    """Durable timer record. Worker drains fired timers and resumes the run.

    The worker dispatcher is responsible for periodically calling
    ``timer_service.fire_pending_timers`` and acting on the returned rows
    (e.g. resuming a paused run, scheduling the next retry attempt).

    Status transitions:
      pending  →  fired      (fire_at reached, worker drained it)
      pending  →  cancelled  (run cancelled, retry abandoned, etc.)

    Cancellation is soft (status flip) rather than DELETE so the audit
    trail is preserved for forensics.
    """

    __tablename__ = "timers"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    step_id: str | None = Field(default=None)
    fire_at: datetime = Field(index=True)
    fired_at: datetime | None = Field(default=None)
    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    purpose: str = Field()  # "delay_node" | "retry_attempt" | "lease_renewal" | etc.
    status: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = ["Timer"]
