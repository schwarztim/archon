"""SQLModel definitions for the durable task queue (W1).

Schema bound by:
  - The Wave 1 task-queue plan: named queues with rate/concurrency caps,
    durable Task rows with lease-based claim, partial-unique idempotency
    per (tenant_id, queue_name), and a polling index for the dispatcher.

Ownership:
  - W1 owns this file end-to-end. Migrations land via the schema/contracts
    worker; the model declarations here are the type contract that W1.5
    (dispatcher polling) and W4a-d (executor groups) build against.

Conventions match ``app/models/workflow.py``:
  - ``Field(sa_column=Column(...))`` for everything beyond a bare scalar
  - Naive UTC timestamps via ``_utcnow`` for TIMESTAMP WITHOUT TIME ZONE
  - Primary keys are UUIDs with ``default_factory=uuid4``
  - Cross-table FKs use SAUuid + ondelete semantics on the Column, not on
    the SQLModel ``foreign_key=...`` shorthand
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
from sqlalchemy import Text as SAText
from sqlalchemy.types import Uuid as SAUuid
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TaskQueue(SQLModel, table=True):
    """Named task queue scoped to a tenant.

    Workers register against one or more queue names; the dispatcher polls
    only queues a worker is registered for. Rate/concurrency caps are
    enforced by W1.5 (dispatcher polling); ``paused`` halts dispatch
    without dropping queued work.
    """

    __tablename__ = "task_queues"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "name", name="uq_taskqueue_tenant_name"
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    name: str = Field()
    queue_type: str = Field(default="default")
    description: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    # Events per second; ``None`` means uncapped.
    max_dispatch_rate: int | None = Field(default=None)
    concurrency_limit: int | None = Field(default=None)
    retention_days: int = Field(default=30)
    paused: bool = Field(default=False)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Task(SQLModel, table=True):
    """A single durable unit of work routed through a TaskQueue.

    ``status`` lifecycle (enforced by W1.5):
        ``pending`` -> ``visible`` -> ``claimed`` -> ``completed``
                                     \\-> ``failed`` / ``cancelled``

    Idempotency: ``(tenant_id, queue_name, idempotency_key)`` is uniquely
    indexed when ``idempotency_key IS NOT NULL`` — partial unique index
    so callers can omit the key without colliding on NULL.

    Polling: the composite index
    ``(tenant_id, queue_name, status, visible_at, priority)`` powers
    ``select_pending_tasks(...)`` from W1.5.
    """

    __tablename__ = "tasks"  # type: ignore[assignment]
    __table_args__ = (
        Index(
            "ix_task_polling",
            "tenant_id",
            "queue_name",
            "status",
            "visible_at",
            "priority",
        ),
        # Partial unique index — works on SQLite >= 3.8 and Postgres >= 9.0.
        Index(
            "ix_task_idempotency_unique",
            "tenant_id",
            "queue_name",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    run_id: UUID = Field(
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    step_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            SAUuid,
            ForeignKey("workflow_run_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    queue_name: str = Field(index=True)
    task_type: str = Field()
    # Pointer to the artifact carrying the payload when oversize. ``None``
    # for in-row payloads handled at the application layer.
    payload_ref: str | None = Field(default=None)
    # Lifecycle status — see class docstring for the transition graph.
    status: str = Field(default="pending")
    visible_at: datetime = Field(default_factory=_utcnow, index=True)
    attempts: int = Field(default=0)
    lease_owner: str | None = Field(default=None)
    lease_expiration: datetime | None = Field(default=None)
    priority: int = Field(default=100)
    idempotency_key: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "Task",
    "TaskQueue",
]
