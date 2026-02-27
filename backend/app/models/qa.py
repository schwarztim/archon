"""QA Workflow Request model for Azure Logic Apps integration."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.utcnow()


class QAWorkflowRequest(SQLModel, table=True):
    """Tracks a QA workflow trigger request and its lifecycle."""

    __tablename__ = "qa_workflow_requests"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    workflow_id: str | None = Field(default=None, index=True)
    workflow_run_id: str | None = Field(default=None)
    trigger_source: str = Field(default="manual")  # manual, workflow_completion, api
    status: str = Field(
        default="pending"
    )  # pending, submitted, in_progress, completed, failed
    logic_apps_run_id: str | None = Field(default=None)  # Logic Apps correlation ID
    request_payload: dict | None = Field(default=None, sa_column=Column(JSON))
    response_payload: dict | None = Field(default=None, sa_column=Column(JSON))
    callback_received: bool = Field(default=False)
    tenant_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = Field(default=None)
    error_message: str | None = Field(default=None)


__all__ = ["QAWorkflowRequest"]
