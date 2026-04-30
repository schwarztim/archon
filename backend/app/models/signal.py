"""UpdateResult model — durable record for validated state-change operations.

Owned by W5 (Signals, Queries, and Updates).

``UpdateResult`` persists the outcome of a ``send_update`` call: the applied
or rejected state, request/response payloads, and any error message.  It is
separate from ``Signal`` (which lives in ``app.models.approval``) because
updates carry a validated response payload and an explicit applied/rejected
status rather than the unconsumed/consumed lifecycle of signals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey
from sqlalchemy.types import JSON, Text as SAText, Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class UpdateResult(SQLModel, table=True):
    """Durable record for a send_update call on a workflow run.

    Lifecycle:
      applied  — payload validated and mutation accepted
      rejected — payload failed validation or handler returned an error

    ``request_payload`` is the caller-supplied body; ``response_payload``
    is the handler's return value (empty dict when rejected).
    ``error_message`` is populated only on rejection.
    """

    __tablename__ = "update_results"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    tenant_id: UUID | None = Field(default=None, index=True)
    update_name: str = Field(index=True)
    sender_id: str | None = Field(default=None)
    request_payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    response_payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    status: str = Field(default="applied", index=True)  # "applied" | "rejected"
    error_message: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    created_at: datetime = Field(default_factory=_utcnow)


__all__ = ["UpdateResult"]
