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
    return datetime.utcnow()


class Workflow(SQLModel, table=True):
    __tablename__ = "workflows"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, index=True)
    name: str
    description: str = Field(default="", sa_column=Column(SAText, nullable=False))
    group_id: str = Field(default="")
    group_name: str = Field(default="")
    steps: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    graph_definition: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    schedule: str | None = Field(default=None)
    is_active: bool = Field(default=True)
    created_by: str = Field(default="")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class WorkflowRun(SQLModel, table=True):
    __tablename__ = "workflow_runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID | None = Field(default=None, index=True)
    workflow_id: UUID = Field(foreign_key="workflows.id", index=True)
    status: str = Field(default="running")
    trigger_type: str = Field(default="manual")
    triggered_by: str = Field(default="")
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None)


class WorkflowRunStep(SQLModel, table=True):
    __tablename__ = "workflow_run_steps"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    step_id: str = Field(default="")
    name: str = Field(default="")
    status: str = Field(default="skipped")
    started_at: str | None = Field(default=None)
    completed_at: str | None = Field(default=None)
    duration_ms: int = Field(default=0)
    input_data: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    output_data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    error: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    agent_execution_id: str | None = Field(default=None)


class WorkflowSchedule(SQLModel, table=True):
    __tablename__ = "workflow_schedules"

    workflow_id: UUID = Field(foreign_key="workflows.id", primary_key=True)
    cron: str
    timezone: str = Field(default="UTC")
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = ["Workflow", "WorkflowRun", "WorkflowRunStep", "WorkflowSchedule"]
