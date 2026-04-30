"""activity_executions — durable per-attempt activity row (W3 / Wave 1)

Revision ID: 0013_add_activity_execution
Revises: 0012_add_task_queue_and_task
Create Date: 2026-04-30

Owned by W3 (Activity Runtime). Phase 2 / Wave 1 of the master durable
orchestration plan introduces a per-attempt durable row so each activity
execution carries its own status, heartbeat, output_ref, and error
metadata independently of the latest WorkflowRunStep snapshot.

Schema (matches ``app/models/activity.py`` + ADR-008 §3 — heartbeat
details inline JSONB, no separate ``ActivityHeartbeat`` table):

  activity_executions
    id                    UUID  PRIMARY KEY
    tenant_id             UUID  NULLABLE     (indexed)
    task_id               UUID  NULLABLE     FK tasks(id) ON DELETE CASCADE
    run_id                UUID  NOT NULL     FK workflow_runs(id) ON DELETE CASCADE
    step_id               TEXT  NOT NULL
    attempt_number        INT   NOT NULL
    worker_id             TEXT  NOT NULL
    queue_name            TEXT  NOT NULL
    activity_type         TEXT  NOT NULL
    idempotency_key       TEXT  NULLABLE
    status                TEXT  NOT NULL  default 'running'
    started_at            TS    NOT NULL  default current_timestamp
    completed_at          TS    NULLABLE
    duration_ms           INT   NULLABLE
    output_ref            TEXT  NULLABLE
    error_code            TEXT  NULLABLE
    error_message         TEXT  NULLABLE
    non_retryable         BOOL  NOT NULL  default false
    retry_after_seconds   INT   NULLABLE
    heartbeat_at          TS    NULLABLE
    heartbeat_details     JSON  NOT NULL  default '{}'   (JSONB on Postgres)
    created_at            TS    NOT NULL  default current_timestamp

Constraints:
  uq_activity_executions_task_attempt   UNIQUE (task_id, attempt_number)
  ck_activity_executions_status         CHECK status IN (...)
  ck_activity_executions_attempt_pos    CHECK attempt_number >= 1

Indexes:
  ix_activity_execution_lookup           (task_id, attempt_number)
  ix_activity_execution_run_step         (run_id, step_id)
  ix_activity_execution_heartbeat_stale  (status, heartbeat_at)
  ix_activity_executions_tenant_id       (tenant_id)
  ix_activity_executions_task_id         (task_id)
  ix_activity_executions_run_id          (run_id)

Idempotent — matches the inline-fix convention used by 0007–0011 so
re-running upgrade on a database that already has the table is a no-op.

Dialect guard: ``heartbeat_details`` uses ``sa.JSON()`` which renders as
``JSON`` on SQLite and ``JSONB`` on Postgres via the existing dialect-
aware path (``app.database`` configures the JSON variant when binding to
Postgres). The migration itself does not need an explicit
``dialect.name`` branch — ``sa.JSON()`` is portable.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — required for Alembic Mako template parity
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0013_add_activity_execution"
down_revision: Union[str, None] = "0012_add_task_queue_and_task"
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


def upgrade() -> None:
    """Create the activity_executions table and its indexes. Idempotent."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Pick the JSON column type. ``sa.JSON()`` renders as JSON on SQLite
    # and JSONB on Postgres when ``none_as_null=True``-style hints are
    # not needed. Per ADR-008 the heartbeat blob is a small dict, so the
    # generic JSON variant is sufficient for both backends.
    if dialect_name == "postgresql":
        # Postgres prefers JSONB for indexing/predicate ops.
        from sqlalchemy.dialects.postgresql import JSONB as _JSON  # noqa: PLC0415
        json_type = _JSON()
    else:
        json_type = sa.JSON()

    if not _table_exists("activity_executions"):
        op.create_table(
            "activity_executions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
            sa.Column("task_id", sa.Uuid(), nullable=True),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("step_id", sa.String(), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column("worker_id", sa.String(), nullable=False),
            sa.Column("queue_name", sa.String(), nullable=False),
            sa.Column("activity_type", sa.String(), nullable=False),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="running",
            ),
            sa.Column(
                "started_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("output_ref", sa.String(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "non_retryable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
            sa.Column(
                "heartbeat_details",
                json_type,
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["run_id"], ["workflow_runs.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["task_id"], ["tasks.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "task_id",
                "attempt_number",
                name="uq_activity_executions_task_attempt",
            ),
            sa.CheckConstraint(
                "status IN ('running','completed','failed','paused',"
                "'cancelled','retry_scheduled')",
                name="ck_activity_executions_status",
            ),
            sa.CheckConstraint(
                "attempt_number >= 1",
                name="ck_activity_executions_attempt_pos",
            ),
        )

    if not _index_exists("activity_executions", "ix_activity_execution_lookup"):
        op.create_index(
            "ix_activity_execution_lookup",
            "activity_executions",
            ["task_id", "attempt_number"],
            unique=False,
        )
    if not _index_exists(
        "activity_executions", "ix_activity_execution_run_step"
    ):
        op.create_index(
            "ix_activity_execution_run_step",
            "activity_executions",
            ["run_id", "step_id"],
            unique=False,
        )
    if not _index_exists(
        "activity_executions", "ix_activity_execution_heartbeat_stale"
    ):
        op.create_index(
            "ix_activity_execution_heartbeat_stale",
            "activity_executions",
            ["status", "heartbeat_at"],
            unique=False,
        )
    if not _index_exists(
        "activity_executions", "ix_activity_executions_tenant_id"
    ):
        op.create_index(
            "ix_activity_executions_tenant_id",
            "activity_executions",
            ["tenant_id"],
            unique=False,
        )
    if not _index_exists(
        "activity_executions", "ix_activity_executions_task_id"
    ):
        op.create_index(
            "ix_activity_executions_task_id",
            "activity_executions",
            ["task_id"],
            unique=False,
        )
    if not _index_exists(
        "activity_executions", "ix_activity_executions_run_id"
    ):
        op.create_index(
            "ix_activity_executions_run_id",
            "activity_executions",
            ["run_id"],
            unique=False,
        )


def downgrade() -> None:
    """Drop the activity_executions table and its indexes."""
    for ix in (
        "ix_activity_executions_run_id",
        "ix_activity_executions_task_id",
        "ix_activity_executions_tenant_id",
        "ix_activity_execution_heartbeat_stale",
        "ix_activity_execution_run_step",
        "ix_activity_execution_lookup",
    ):
        if _index_exists("activity_executions", ix):
            op.drop_index(ix, table_name="activity_executions")
    if _table_exists("activity_executions"):
        op.drop_table("activity_executions")
