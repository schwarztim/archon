"""VisibilityIndex model — denormalised search row per WorkflowRun (W13 / ADR-008 §7).

Column names and index names are locked per ADR-008 §Locked.
Table name: visibility_indexes
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class VisibilityIndex(SQLModel, table=True):
    """Denormalised search row maintained 1:1 with WorkflowRun.

    Updated by update_visibility_index() in visibility_service after every
    terminal transition on a run. Never the source of truth — WorkflowRun is.
    See ADR-008 §7 for the update-mechanism decision.
    """

    __tablename__ = "visibility_indexes"
    __table_args__ = (
        UniqueConstraint("workflow_run_id", name="uq_visibility_workflow_run_id"),
        # Compound search indexes as specified in ADR-008 §7
        Index(
            "ix_visibility_tenant_status_started",
            "tenant_id",
            "status",
            "started_at",
        ),
        Index(
            "ix_visibility_tenant_queue_started",
            "tenant_id",
            "queue_name",
            "started_at",
        ),
        Index("ix_visibility_tenant_worker", "tenant_id", "worker_id"),
        Index("ix_visibility_external_run", "external_provider", "external_run_id"),
        Index("ix_visibility_failure_code", "tenant_id", "failure_code"),
        Index("ix_visibility_cost", "tenant_id", "cost_total_usd"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    workflow_run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
            unique=True,
        )
    )
    tenant_id: UUID | None = Field(default=None, index=True)

    # ── Mirrored from WorkflowRun ─────────────────────────────────────
    status: str = Field()
    workflow_id: UUID | None = Field(default=None, index=True)
    agent_id: UUID | None = Field(default=None, index=True)

    # ── From RunChain (populated when run is part of a continue-as-new chain) ─
    chain_id: UUID | None = Field(default=None, index=True)

    # ── Queue and worker attribution ──────────────────────────────────
    queue_name: str | None = Field(default=None, index=True)
    worker_id: str | None = Field(default=None, index=True)
    definition_version_id: UUID | None = Field(default=None, index=True)

    # ── Operator tags (arbitrary key-value pairs) ─────────────────────
    tags_json: dict = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    # ── Cost and duration aggregates ──────────────────────────────────
    cost_total_usd: float = Field(default=0.0)
    duration_ms: int | None = Field(default=None)
    step_count: int = Field(default=0)
    failure_code: str | None = Field(default=None, index=True)

    # ── Pipeline correlation fields (mirrored from PipelineCorrelation) ─
    external_provider: str | None = Field(default=None, index=True)
    external_run_id: str | None = Field(default=None, index=True)
    external_branch: str | None = Field(default=None, index=True)
    external_environment: str | None = Field(default=None, index=True)

    # ── Timeline ─────────────────────────────────────────────────────
    started_at: datetime | None = Field(default=None, index=True)
    completed_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = ["VisibilityIndex"]
