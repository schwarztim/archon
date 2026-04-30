"""SQLModel definition for PipelineCorrelation (W8 / ADR-008 §4).

Links a WorkflowRun to an external CI/CD pipeline event. This is a
SEPARATE table — pipeline/provider identity is NOT added to WorkflowRun
per ADR-001's workflow-vs-agent XOR contract.

Column names and index names are locked per ADR-008 §Locked.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy import CheckConstraint
from sqlalchemy.types import Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


_VALID_PROVIDERS = (
    "github_actions",
    "azure_devops",
    "jenkins",
    "gitlab",
    "generic_webhook",
)


class PipelineCorrelation(SQLModel, table=True):
    """Links a WorkflowRun to an external CI/CD pipeline event.

    One row per (provider, external_event_id) — the unique constraint
    at the schema layer prevents duplicate webhook deliveries from
    creating duplicate correlations.

    ``idempotency_key`` is application-computed as sha256(provider +
    external_event_id) and carries a partial-unique index that mirrors
    ADR-004's pattern on WorkflowRun.
    """

    __tablename__ = "pipeline_correlations"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_event_id",
            name="uq_pipeline_corr_provider_event",
        ),
        Index(
            "uq_pipeline_corr_idem",
            "tenant_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        CheckConstraint(
            "provider IN ('github_actions','azure_devops','jenkins',"
            "'gitlab','generic_webhook')",
            name="ck_pipeline_corr_provider",
        ),
        Index("ix_pipeline_corr_run", "workflow_run_id"),
        Index("ix_pipeline_corr_external", "provider", "external_run_id"),
        Index("ix_pipeline_corr_tenant_created", "tenant_id", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Tenant — nullable in schema per ADR-008; W8 enforces non-null at app layer.
    tenant_id: UUID | None = Field(
        default=None,
        sa_column=Column(SAUuid, nullable=True, index=True),
    )

    # FK to workflow_runs — CASCADE so deleting a run cleans up correlation rows.
    workflow_run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    # Provider identity (one of the five locked values).
    provider: str = Field(nullable=False)

    # Provider-specific event identifiers.
    external_event_id: str = Field(nullable=False)
    external_run_id: str | None = Field(default=None)
    external_pipeline_id: str | None = Field(default=None)
    external_commit_sha: str | None = Field(default=None)
    external_branch: str | None = Field(default=None)
    external_actor: str | None = Field(default=None)
    environment: str | None = Field(default=None)

    # Callback destination (raw URL stored; secret is in vault, not here).
    callback_url: str | None = Field(default=None)
    callback_url_secret_ref: str | None = Field(default=None)

    # Application-computed idempotency key: sha256(provider + external_event_id).
    idempotency_key: str = Field(nullable=False)

    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


__all__ = ["PipelineCorrelation"]
