"""SQLModel database models for Archon workflow orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
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
    """Record of a single workflow execution."""

    __tablename__ = "workflow_runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_id: UUID = Field(index=True, foreign_key="workflows.id")
    tenant_id: UUID | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    trigger_type: str = Field(default="manual")
    input_data: dict | None = Field(default=None, sa_column=Column(JSON))
    triggered_by: str = Field(default="")
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    error: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow)


class WorkflowRunStep(SQLModel, table=True):
    """Individual step result within a workflow run."""

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
    created_at: datetime = Field(default_factory=_utcnow)


class WorkflowSchedule(SQLModel, table=True):
    """Cron schedule configuration for a workflow."""

    __tablename__ = "workflow_schedules"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_id: UUID = Field(index=True, foreign_key="workflows.id", unique=True)
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
    "WorkflowSchedule",
]
