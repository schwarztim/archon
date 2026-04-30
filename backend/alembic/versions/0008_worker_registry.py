"""worker_registry — heartbeat table for the Worker Plane (Phase 6)

Revision ID: 0008_worker_registry
Revises: 0007_canonical_run_substrate
Create Date: 2026-04-29

Creates the ``worker_heartbeats`` table that the worker process upserts
into on start, refreshes every HEARTBEAT_INTERVAL seconds, and deletes
on graceful shutdown. Stale rows are pruned by
``WorkerRegistry.prune_stale``; their owned leases are reclaimed by
``run_dispatcher.reclaim_expired_runs`` (W1.3 owns that primitive).

Schema:
  worker_id          TEXT  PRIMARY KEY
  hostname           TEXT  NOT NULL
  pid                INT   NOT NULL
  started_at         TS    NOT NULL  (server_default = current_timestamp)
  last_heartbeat_at  TS    NOT NULL  (server_default = current_timestamp, indexed)
  lease_count        INT   NOT NULL  (server_default = 0)
  capabilities       JSON  NOT NULL  (server_default = '{}')
  version            TEXT  NULLABLE
  tenant_affinity    JSON  NULLABLE

Indexes:
  ix_worker_heartbeats_last_heartbeat_at  on (last_heartbeat_at)

The migration is idempotent (matches the wave-0 + 0007 inline-fix
convention): it checks existence via sa.inspect before each create.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — required for Alembic Mako template parity
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0008_worker_registry"
down_revision: Union[str, None] = "0007_canonical_run_substrate"
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
    """Create worker_heartbeats. Idempotent: skip if already present."""
    if not _table_exists("worker_heartbeats"):
        op.create_table(
            "worker_heartbeats",
            sa.Column("worker_id", sa.String(), nullable=False),
            sa.Column("hostname", sa.String(), nullable=False),
            sa.Column("pid", sa.Integer(), nullable=False),
            sa.Column(
                "started_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "last_heartbeat_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "lease_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "capabilities",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("version", sa.String(), nullable=True),
            sa.Column("tenant_affinity", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("worker_id"),
        )

    if not _index_exists("worker_heartbeats", "ix_worker_heartbeats_last_heartbeat_at"):
        op.create_index(
            "ix_worker_heartbeats_last_heartbeat_at",
            "worker_heartbeats",
            ["last_heartbeat_at"],
            unique=False,
        )


def downgrade() -> None:
    """Drop the worker_heartbeats table and its index."""
    if _index_exists("worker_heartbeats", "ix_worker_heartbeats_last_heartbeat_at"):
        op.drop_index(
            "ix_worker_heartbeats_last_heartbeat_at",
            table_name="worker_heartbeats",
        )
    if _table_exists("worker_heartbeats"):
        op.drop_table("worker_heartbeats")
