"""timers — durable timer registry for delay nodes and retries

Revision ID: 0009_timers_table
Revises: 0008_worker_registry
Create Date: 2026-04-29

Creates the ``timers`` table consumed by ``timer_service``. Every long
delay node and every retry attempt schedules a row here; the dispatcher
sweeps ``fire_at <= now AND status = 'pending'`` in batches and resumes
the owning workflow_run.

Schema:
  id          UUID  PRIMARY KEY
  run_id      UUID  NULLABLE  FK workflow_runs(id) ON DELETE CASCADE  (indexed)
  step_id     TEXT  NULLABLE
  fire_at     TS    NOT NULL  (indexed)
  fired_at    TS    NULLABLE
  payload     JSON  NOT NULL  (server_default = '{}')
  purpose     TEXT  NOT NULL
  status      TEXT  NOT NULL  (server_default = 'pending', indexed)
  created_at  TS    NOT NULL  (server_default = current_timestamp)

Indexes:
  ix_timers_run_id   on (run_id)            — surface all timers per run
  ix_timers_fire_at  on (fire_at)           — drain hot path
  ix_timers_status   on (status)            — drain hot path

Idempotent (matches the wave-0 + 0007 + 0008 inline-fix convention).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — required for Alembic Mako template parity
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0009_timers_table"
down_revision: Union[str, None] = "0008_worker_registry"
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
    """Create the timers table and its indexes. Idempotent."""
    if not _table_exists("timers"):
        op.create_table(
            "timers",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=True),
            sa.Column("step_id", sa.String(), nullable=True),
            sa.Column("fire_at", sa.DateTime(), nullable=False),
            sa.Column("fired_at", sa.DateTime(), nullable=True),
            sa.Column(
                "payload",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="pending",
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
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists("timers", "ix_timers_run_id"):
        op.create_index(
            "ix_timers_run_id", "timers", ["run_id"], unique=False
        )
    if not _index_exists("timers", "ix_timers_fire_at"):
        op.create_index(
            "ix_timers_fire_at", "timers", ["fire_at"], unique=False
        )
    if not _index_exists("timers", "ix_timers_status"):
        op.create_index(
            "ix_timers_status", "timers", ["status"], unique=False
        )


def downgrade() -> None:
    """Drop the timers table and its indexes."""
    for ix in ("ix_timers_status", "ix_timers_fire_at", "ix_timers_run_id"):
        if _index_exists("timers", ix):
            op.drop_index(ix, table_name="timers")
    if _table_exists("timers"):
        op.drop_table("timers")
