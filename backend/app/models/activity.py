"""SQLModel for the durable ActivityExecution row (W3).

Schema bound by:
  - ADR-008 §3 — one row per activity attempt; heartbeat details are
    inline JSONB on this row, not a separate ActivityHeartbeat table.
  - The W3 plan section in ``archon-durable-orchestration-worker-plan.md``
    — runtime persists this row through the activity lifecycle.

Ownership:
  - W3 owns this file end-to-end. The runtime in
    ``app/services/activity_runtime.py`` is the only writer; downstream
    workers (W4a/W4b/W4c/W4d) read it via the runtime, never directly.

Invariants enforced at the schema level:
  - ``(task_id, attempt_number)`` is unique — natural key from the
    dispatcher's perspective; one row per attempt.
  - ``status`` is restricted to the lifecycle enumeration via a CHECK
    constraint that mirrors ``ActivityResult.status`` (plus ``running``
    for the in-flight state the runtime sets on insert).
  - ``attempt_number`` is positive — guard against off-by-one bugs in the
    dispatcher's claim path.

Indexes:
  - ``ix_activity_execution_lookup`` on (task_id, attempt_number) — joins
    back to a Task by its current attempt.
  - ``ix_activity_execution_run_step`` on (run_id, step_id) — joins back
    to ``workflow_run_steps`` for the operator UI.
  - ``ix_activity_execution_heartbeat_stale`` on (status, heartbeat_at)
    — the janitor scan that promotes silent ``running`` rows to ``failed``
    after the heartbeat threshold elapses.

Conventions match ``app/models/workflow.py`` and ``app/models/task_queue.py``:
  - ``Field(sa_column=Column(...))`` for non-trivial columns
  - Naive UTC timestamps via ``_utcnow`` for TIMESTAMP WITHOUT TIME ZONE
  - Primary keys are UUIDs with ``default_factory=uuid4``
  - Cross-table FKs use SAUuid + ondelete on the Column
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Naive UTC for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ActivityExecution(SQLModel, table=True):
    """One row per activity attempt — the durable record of activity work.

    Lifecycle:
      1. Runtime INSERTs with ``status='running'`` when the executor is
         about to run.
      2. The executor's heartbeat callbacks update ``heartbeat_at`` +
         ``heartbeat_details`` (buffered to bound write amplification).
      3. On terminal status, runtime UPDATEs ``status``, ``completed_at``,
         and one of ``output_ref`` / ``error_code`` + ``error_message`` /
         ``retry_after_seconds`` depending on the outcome.

    Relationship to ``WorkflowRunStep`` (see ADR-008 §3): step rows are
    per logical step (current snapshot); ActivityExecution is per attempt.
    The dispatcher writes the step row only after the activity row is
    finalised, so a chain consumer never observes a step without a
    matching ActivityExecution.
    """

    __tablename__ = "activity_executions"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "attempt_number",
            name="uq_activity_executions_task_attempt",
        ),
        CheckConstraint(
            "status IN ('running','completed','failed','paused',"
            "'cancelled','retry_scheduled')",
            name="ck_activity_executions_status",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_activity_executions_attempt_pos",
        ),
        # Polling/janitor + lookup indexes documented in the module
        # docstring. Kept inline here so downstream tests can assert
        # presence without reaching into Alembic metadata.
        Index(
            "ix_activity_execution_lookup",
            "task_id",
            "attempt_number",
        ),
        Index(
            "ix_activity_execution_run_step",
            "run_id",
            "step_id",
        ),
        Index(
            "ix_activity_execution_heartbeat_stale",
            "status",
            "heartbeat_at",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, index=True)

    # ── Linkage to the dispatch / run substrate ───────────────────────
    task_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    step_id: str = Field()

    # ── Attempt + identity ────────────────────────────────────────────
    attempt_number: int = Field()
    worker_id: str = Field()
    queue_name: str = Field()
    activity_type: str = Field()
    idempotency_key: str | None = Field(default=None)

    # ── Lifecycle status ──────────────────────────────────────────────
    status: str = Field(default="running")
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None)

    # ── Result payload / error / retry hint ───────────────────────────
    # ``output_ref`` is the ``artifact://...`` URI emitted by the
    # artifact_service. We store the URI rather than inlining JSON because
    # the runtime always extracts outputs to artifacts so the chain stays
    # the same shape regardless of payload size.
    output_ref: str | None = Field(default=None)
    error_code: str | None = Field(default=None)
    error_message: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    non_retryable: bool = Field(default=False)
    retry_after_seconds: int | None = Field(default=None)

    # ── Heartbeat (inline JSONB) ──────────────────────────────────────
    # ``heartbeat_at`` is indexed (declared in __table_args__ above so it
    # combines with ``status`` for the janitor scan). ``heartbeat_details``
    # is a JSON blob — overwritten on each beat per ADR-008.
    heartbeat_at: datetime | None = Field(default=None)
    heartbeat_details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow)


__all__ = ["ActivityExecution"]
