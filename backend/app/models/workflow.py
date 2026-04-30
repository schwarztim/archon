"""SQLModel database models for Archon workflow orchestration.

Schema bound by:
  - ADR-001 — unified run model (workflow_runs admits agent or workflow)
  - ADR-002 — run event ownership and hash-chained event log
  - ADR-004 — idempotency contract (idempotency_key, input_hash columns)
  - ADR-007 — workflow deletion semantics (workflow_id is nullable, ondelete=SET NULL)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class Workflow(SQLModel, table=True):
    """Workflow definition stored in the platform."""

    __tablename__ = "workflows"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, index=True)
    name: str = Field(index=True)
    description: str = Field(default="", sa_column=Column(SAText, nullable=False))
    group_id: str = Field(default="")
    group_name: str = Field(default="")
    steps: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    graph_definition: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    trigger_config: dict | None = Field(default=None, sa_column=Column(JSON))
    schedule: str | None = Field(default=None)
    is_active: bool = Field(default=True)
    created_by: str = Field(default="")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkflowRun(SQLModel, table=True):
    """Unified record of a single execution — workflow OR agent.

    See ADR-001 for the schema rationale and ADR-007 for cascade semantics.
    Exactly one of (workflow_id, agent_id) must be set on every row,
    enforced by the ck_workflow_runs_workflow_xor_agent CHECK constraint.
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "(workflow_id IS NULL) <> (agent_id IS NULL)",
            name="ck_workflow_runs_workflow_xor_agent",
        ),
        # ADR-004 partial unique index — tenant-scoped idempotency. The
        # ``sqlite_where`` / ``postgresql_where`` arguments make this work
        # on both engines (SQLite ≥ 3.8, Postgres ≥ 9.0).
        Index(
            "uq_workflow_runs_tenant_idem",
            "tenant_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_workflow_runs_tenant_id_status",
            "tenant_id",
            "status",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # ── Target (XOR — exactly one of these is set) ──────────────────────
    workflow_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    agent_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )

    # ── Discriminator + immutable definition snapshot ──────────────────
    kind: str = Field(default="workflow", index=True)  # "workflow" | "agent"
    # ``none_as_null=True`` makes Python ``None`` map to SQL ``NULL`` so the
    # NOT NULL constraint actually fires on snapshot omission. Without it,
    # SQLAlchemy serialises Python None to the JSON literal "null", which
    # passes NOT NULL.
    definition_snapshot: dict[str, Any] = Field(
        sa_column=Column(JSON(none_as_null=True), nullable=False)
    )
    definition_version: str | None = Field(default=None)

    # ── Tenant + lifecycle status ──────────────────────────────────────
    tenant_id: UUID | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    trigger_type: str = Field(default="manual")
    input_data: dict | None = Field(default=None, sa_column=Column(JSON))
    triggered_by: str = Field(default="")

    # ── Timeline ───────────────────────────────────────────────────────
    queued_at: datetime | None = Field(default=None)
    claimed_at: datetime | None = Field(default=None)
    started_at: datetime | None = Field(default=None)
    paused_at: datetime | None = Field(default=None)
    resumed_at: datetime | None = Field(default=None)
    cancel_requested_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None)

    # ── Worker leasing (optimistic-lock claim) ─────────────────────────
    lease_owner: str | None = Field(default=None)
    lease_expires_at: datetime | None = Field(default=None)
    attempt: int = Field(default=0)

    # ── Idempotency (ADR-004) ──────────────────────────────────────────
    idempotency_key: str | None = Field(default=None)
    input_hash: str | None = Field(default=None)

    # ── Outputs / observability ────────────────────────────────────────
    output_data: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    metrics: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error_code: str | None = Field(default=None)
    error: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))

    created_at: datetime = Field(default_factory=_utcnow)


class WorkflowRunStep(SQLModel, table=True):
    """Individual step result within a workflow run.

    Step state is a current-snapshot view; ordered transitions live in
    workflow_run_events with step_id populated. See ADR-002.
    """

    __tablename__ = "workflow_run_steps"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(index=True, foreign_key="workflow_runs.id")
    step_id: str = Field(default="")
    name: str = Field(default="")
    status: str = Field(default="pending")
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    duration_ms: int = Field(default=0)
    input_data: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    output_data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    error: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    agent_execution_id: str | None = Field(default=None)

    # ── Retries / idempotency ──────────────────────────────────────────
    attempt: int = Field(default=0)
    retry_count: int = Field(default=0)
    idempotency_key: str | None = Field(default=None)

    # ── LangGraph checkpointer linkage (see ADR-005) ──────────────────
    checkpoint_thread_id: str | None = Field(default=None)

    # ── Hash-chain alignment + artifact pointer ────────────────────────
    input_hash: str | None = Field(default=None)
    output_artifact_id: UUID | None = Field(default=None)

    # ── Cost + worker observability ────────────────────────────────────
    token_usage: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    cost_usd: float | None = Field(default=None)
    worker_id: str | None = Field(default=None)
    error_code: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)


class WorkflowRunEvent(SQLModel, table=True):
    """Append-only, hash-chained event log for run state transitions.

    Owned by WS1 — the Data Model squad. Schema is bound by ADR-002.
    Every state mutation on workflow_runs / workflow_run_steps emits one
    event in the same database transaction; hash chain provides tamper
    evidence. Sequence is monotonic per run_id (UNIQUE(run_id, sequence)).
    """

    __tablename__ = "workflow_run_events"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "sequence", name="uq_run_events_run_sequence"
        ),
        # CHECK constraint enforces the closed enumeration of event types.
        CheckConstraint(
            "event_type IN ("
            "'run.created','run.queued','run.claimed','run.started',"
            "'run.completed','run.failed','run.cancelled',"
            "'run.paused','run.resumed',"
            "'step.started','step.completed','step.failed',"
            "'step.skipped','step.retry','step.paused'"
            ")",
            name="ck_run_events_event_type",
        ),
        Index("ix_run_events_run_id_sequence", "run_id", "sequence"),
        Index("ix_run_events_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_run_events_correlation_id", "correlation_id"),
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
    sequence: int = Field()  # monotonic per run, starts at 0
    event_type: str = Field()
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    tenant_id: UUID | None = Field(default=None, index=True)
    correlation_id: str | None = Field(default=None)
    span_id: str | None = Field(default=None)
    step_id: str | None = Field(default=None)
    prev_hash: str | None = Field(default=None)  # NULL only for sequence=0
    current_hash: str = Field()  # 64-char hex sha256
    created_at: datetime = Field(default_factory=_utcnow)


class WorkflowSchedule(SQLModel, table=True):
    """Cron schedule configuration for a workflow."""

    __tablename__ = "workflow_schedules"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            unique=True,
        )
    )
    tenant_id: UUID | None = Field(default=None, index=True)
    cron: str
    timezone: str = Field(default="UTC")
    enabled: bool = Field(default=True)
    last_run_at: datetime | None = Field(default=None)
    next_run_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "Workflow",
    "WorkflowRun",
    "WorkflowRunStep",
    "WorkflowRunEvent",
    "WorkflowSchedule",
]
