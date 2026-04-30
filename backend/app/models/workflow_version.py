"""WorkflowDefinitionVersion model — ADR-008 §5.

Versioned snapshot of a workflow definition. Used by W11 (definition
versioning) and W12 (continue-as-new — child runs reference the parent's
version snapshot).

Schema is frozen by ADR-008. Table name ``workflow_definition_versions``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class WorkflowDefinitionVersion(SQLModel, table=True):
    """Immutable versioned snapshot of a workflow definition.

    version_number is monotonic per workflow_id starting at 1.
    schema_snapshot captures the full graph_definition + steps at cut time.
    compatibility_set lists worker version tags allowed to run this version.
    deprecated_at is a soft-deprecation marker: in-flight runs continue,
    new starts are blocked.

    ADR-008 §5 locks the table name, columns, constraints, and indexes.
    """

    __tablename__ = "workflow_definition_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_workflow_def_version_number",
        ),
        Index(
            "ix_workflow_def_version_active",
            "workflow_id",
            "deprecated_at",
        ),
        Index(
            "ix_workflow_def_version_tenant",
            "tenant_id",
            "created_at",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflows.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    tenant_id: UUID | None = Field(default=None, index=True)
    version_number: int = Field()
    schema_snapshot: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False)
    )
    compatibility_set: list[Any] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    changelog: str = Field(
        default="", sa_column=Column(SAText, nullable=False)
    )
    created_by: str = Field(default="")
    created_at: datetime = Field(default_factory=_utcnow)
    deprecated_at: datetime | None = Field(default=None)


__all__ = ["WorkflowDefinitionVersion"]
