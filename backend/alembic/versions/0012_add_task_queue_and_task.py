"""task_queues + tasks — durable activity queue substrate (W1)

Revision ID: 0012_add_task_queue_and_task
Revises: 0011_artifacts
Create Date: 2026-04-30

Owned by W1 (Queue Data Model + APIs squad). Closes Wave 1 of the durable
orchestration plan: introduces named, tenant-scoped task queues with
rate/concurrency caps and a durable ``tasks`` table that the W1.5
dispatcher polls for work.

Schema:
  task_queues
    id                  UUID  PRIMARY KEY
    tenant_id           UUID  NOT NULL  (indexed)
    name                TEXT  NOT NULL
    queue_type          TEXT  NOT NULL  (server_default 'default')
    description         TEXT  NULLABLE
    max_dispatch_rate   INT   NULLABLE  (events per second; NULL = uncapped)
    concurrency_limit   INT   NULLABLE  (NULL = uncapped)
    retention_days      INT   NOT NULL  (server_default '30')
    paused              BOOL  NOT NULL  (server_default '0')
    created_at          TS    NOT NULL  (server_default current_timestamp)
    updated_at          TS    NOT NULL  (server_default current_timestamp)
  UNIQUE (tenant_id, name)  uq_taskqueue_tenant_name

  tasks
    id                  UUID  PRIMARY KEY
    tenant_id           UUID  NOT NULL  (indexed)
    run_id              UUID  NOT NULL  FK workflow_runs(id) ON DELETE CASCADE  (indexed)
    step_id             UUID  NULLABLE  FK workflow_run_steps(id) ON DELETE SET NULL
    queue_name          TEXT  NOT NULL  (indexed)
    task_type           TEXT  NOT NULL
    payload_ref         TEXT  NULLABLE  (artifact pointer for oversize payloads)
    status              TEXT  NOT NULL  (server_default 'pending')
    visible_at          TS    NOT NULL  (server_default current_timestamp, indexed)
    attempts            INT   NOT NULL  (server_default '0')
    lease_owner         TEXT  NULLABLE
    lease_expiration    TS    NULLABLE
    priority            INT   NOT NULL  (server_default '100')
    idempotency_key     TEXT  NULLABLE  (indexed)
    created_at          TS    NOT NULL  (server_default current_timestamp)
    updated_at          TS    NOT NULL  (server_default current_timestamp)

Indexes:
  ix_task_polling           on (tenant_id, queue_name, status, visible_at, priority)
                            — composite hot path for dispatcher polling
  ix_task_idempotency_unique  partial unique on
                            (tenant_id, queue_name, idempotency_key)
                            WHERE idempotency_key IS NOT NULL
                            — allows multiple NULL keys; collides on duplicate non-NULL

Idempotent — matches the inline-fix convention of 0007–0011 so re-running
upgrade on a database that already has the tables is a no-op.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — required for Alembic Mako template parity
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "0012_add_task_queue_and_task"
down_revision: Union[str, None] = "0011_artifacts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    """Idempotency helper — used by both upgrade and downgrade."""
    return name in sa.inspect(op.get_bind()).get_table_names()


def _index_exists(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return any(i["name"] == name for i in insp.get_indexes(table))


def _unique_constraint_exists(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return any(uc.get("name") == name for uc in insp.get_unique_constraints(table))


def upgrade() -> None:
    """Create task_queues + tasks tables and their indexes. Idempotent."""

    # ── task_queues ───────────────────────────────────────────────────
    if not _table_exists("task_queues"):
        op.create_table(
            "task_queues",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column(
                "queue_type",
                sa.String(),
                nullable=False,
                server_default="default",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("max_dispatch_rate", sa.Integer(), nullable=True),
            sa.Column("concurrency_limit", sa.Integer(), nullable=True),
            sa.Column(
                "retention_days",
                sa.Integer(),
                nullable=False,
                server_default="30",
            ),
            sa.Column(
                "paused",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id", "name", name="uq_taskqueue_tenant_name"
            ),
        )

    # ``tenant_id`` is declared via ``Field(index=True)`` on the model;
    # SQLAlchemy auto-names that index ``ix_task_queues_tenant_id``.
    if not _index_exists("task_queues", "ix_task_queues_tenant_id"):
        op.create_index(
            "ix_task_queues_tenant_id",
            "task_queues",
            ["tenant_id"],
            unique=False,
        )

    # ── tasks ─────────────────────────────────────────────────────────
    if not _table_exists("tasks"):
        op.create_table(
            "tasks",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("step_id", sa.Uuid(), nullable=True),
            sa.Column("queue_name", sa.String(), nullable=False),
            sa.Column("task_type", sa.String(), nullable=False),
            sa.Column("payload_ref", sa.String(), nullable=True),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "visible_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "attempts",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("lease_owner", sa.String(), nullable=True),
            sa.Column("lease_expiration", sa.DateTime(), nullable=True),
            sa.Column(
                "priority",
                sa.Integer(),
                nullable=False,
                server_default="100",
            ),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["run_id"], ["workflow_runs.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["step_id"],
                ["workflow_run_steps.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    # Auto-generated single-column indexes from ``Field(index=True)``.
    if not _index_exists("tasks", "ix_tasks_tenant_id"):
        op.create_index(
            "ix_tasks_tenant_id", "tasks", ["tenant_id"], unique=False
        )
    if not _index_exists("tasks", "ix_tasks_run_id"):
        op.create_index(
            "ix_tasks_run_id", "tasks", ["run_id"], unique=False
        )
    if not _index_exists("tasks", "ix_tasks_queue_name"):
        op.create_index(
            "ix_tasks_queue_name",
            "tasks",
            ["queue_name"],
            unique=False,
        )
    if not _index_exists("tasks", "ix_tasks_visible_at"):
        op.create_index(
            "ix_tasks_visible_at",
            "tasks",
            ["visible_at"],
            unique=False,
        )
    if not _index_exists("tasks", "ix_tasks_idempotency_key"):
        op.create_index(
            "ix_tasks_idempotency_key",
            "tasks",
            ["idempotency_key"],
            unique=False,
        )

    # Polling composite index (ADR-008-locked name).
    if not _index_exists("tasks", "ix_task_polling"):
        op.create_index(
            "ix_task_polling",
            "tasks",
            [
                "tenant_id",
                "queue_name",
                "status",
                "visible_at",
                "priority",
            ],
            unique=False,
        )

    # Partial unique idempotency index (ADR-008-locked name). Both
    # ``sqlite_where`` and ``postgresql_where`` are supplied so SQLite test
    # runs and Postgres production runs both produce the same partial index.
    if not _index_exists("tasks", "ix_task_idempotency_unique"):
        op.create_index(
            "ix_task_idempotency_unique",
            "tasks",
            ["tenant_id", "queue_name", "idempotency_key"],
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        )


def downgrade() -> None:
    """Drop tasks + task_queues tables and their indexes (reverse order)."""

    # ── tasks ─────────────────────────────────────────────────────────
    for ix in (
        "ix_task_idempotency_unique",
        "ix_task_polling",
        "ix_tasks_idempotency_key",
        "ix_tasks_visible_at",
        "ix_tasks_queue_name",
        "ix_tasks_run_id",
        "ix_tasks_tenant_id",
    ):
        if _index_exists("tasks", ix):
            op.drop_index(ix, table_name="tasks")
    if _table_exists("tasks"):
        op.drop_table("tasks")

    # ── task_queues ───────────────────────────────────────────────────
    if _index_exists("task_queues", "ix_task_queues_tenant_id"):
        op.drop_index("ix_task_queues_tenant_id", table_name="task_queues")
    if _table_exists("task_queues"):
        op.drop_table("task_queues")
