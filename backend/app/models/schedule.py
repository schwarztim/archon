"""Schedule model — ADR-008 §9.

First-class schedule table for workflow OR agent schedules with overlap
policy, jitter, and catchup. Distinct from ``WorkflowSchedule`` (per-workflow
cron, retained for backward compat). New schedules go here; W7 may later
migrate ``WorkflowSchedule`` rows to this table.

Column names are locked per ADR-008 §Locked column names — ``schedules``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    text,
)
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class Schedule(SQLModel, table=True):
    """First-class durable schedule per ADR-008 §9.

    Supports workflow OR agent targets (XOR contract mirrors WorkflowRun).
    Supports cron, rrule, and interval specs. Overlap policy controls what
    happens when a new fire is due while a previous run is still active.
    """

    __tablename__ = "schedules"
    __table_args__ = (
        # Mirrors WorkflowRun's XOR; preserves ADR-001 invariant.
        CheckConstraint(
            "(workflow_id IS NULL) <> (agent_id IS NULL)",
            name="ck_schedules_workflow_xor_agent",
        ),
        CheckConstraint(
            "spec_kind IN ('cron','rrule','interval')",
            name="ck_schedules_spec_kind",
        ),
        CheckConstraint(
            "overlap_policy IN ('skip','buffer_one','buffer_all',"
            "'cancel_running','terminate_running','allow_all')",
            name="ck_schedules_overlap_policy",
        ),
        # Primary scan index for the schedule loop.
        Index("ix_schedules_next_fire", "next_fire_at", "paused"),
        Index("ix_schedules_tenant_paused", "tenant_id", "paused"),
        Index("ix_schedules_workflow_id", "workflow_id"),
        Index("ix_schedules_agent_id", "agent_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, index=True)
    name: str = Field()
    description: str = Field(default="", sa_column=Column(SAText, nullable=False))

    # ── Action target — same XOR contract as WorkflowRun ─────────────
    workflow_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("workflows.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    agent_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # Pin to a specific definition version; NULL means "latest active".
    definition_version_id: UUID | None = Field(default=None)

    # ── Schedule spec ─────────────────────────────────────────────────
    # cron expression, RRULE, or "interval:N{s|m|h|d}"
    calendar_spec: str = Field()
    spec_kind: str = Field(default="cron")  # "cron" | "rrule" | "interval"
    timezone: str = Field(default="UTC")
    jitter_seconds: int = Field(default=0)
    start_bound: datetime | None = Field(default=None)
    end_bound: datetime | None = Field(default=None)

    # ── Behaviour policy ──────────────────────────────────────────────
    overlap_policy: str = Field(default="skip")
    catchup_window_seconds: int = Field(default=0)
    pause_on_failure: bool = Field(default=False)
    input_template: dict = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    # ── State ─────────────────────────────────────────────────────────
    paused: bool = Field(default=False)
    last_evaluated_at: datetime | None = Field(default=None)
    last_fire_attempted_at: datetime | None = Field(default=None)
    last_fire_succeeded_at: datetime | None = Field(default=None)
    last_successful_run_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    next_fire_at: datetime | None = Field(default=None)
    consecutive_failures: int = Field(default=0)
    notes: str = Field(default="", sa_column=Column(SAText, nullable=False))

    created_by: str = Field(default="")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = ["Schedule"]
