"""artifacts — durable large-output storage (Phase 5)

Revision ID: 0011_artifacts
Revises: 0010_approvals_signals
Create Date: 2026-04-29

Owned by WS5 — Observability/Artifacts Squad. Phase 5 of the master plan
introduces a durable artifact substrate so step outputs that exceed the
inline threshold (default 32 KiB) can be persisted out-of-band and
referenced from ``workflow_run_steps.output_data`` via a tiny JSON
``_artifact_ref`` shim.

Schema:
  artifacts
    id              UUID  PRIMARY KEY
    run_id          UUID  NULLABLE  FK workflow_runs(id) ON DELETE CASCADE
    step_id         TEXT  NULLABLE
    tenant_id       UUID  NULLABLE  (indexed)
    content_type    TEXT  NOT NULL  (server_default 'application/octet-stream')
    content_hash    TEXT  NOT NULL  (indexed)   — sha256 hex of bytes
    size_bytes      INT   NOT NULL  (server_default '0')
    storage_backend TEXT  NOT NULL  (server_default 'local')
    storage_uri     TEXT  NOT NULL  (server_default '')
    retention_days  INT   NULLABLE
    expires_at      TS    NULLABLE  (indexed)   — sweep target
    created_at      TS    NOT NULL  (server_default current_timestamp)
    meta            JSON  NOT NULL  (server_default '{}')

Indexes:
  ix_artifacts_run_id        on (run_id)         — list by run
  ix_artifacts_tenant_id     on (tenant_id)      — tenant-scoped queries
  ix_artifacts_content_hash  on (content_hash)   — dedup / integrity
  ix_artifacts_expires_at    on (expires_at)     — retention sweep hot path

Idempotent — matches the inline-fix convention used by 0007–0010 so
re-running upgrade on a database that already has the table is a no-op.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — required for Alembic Mako template parity
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0011_artifacts"
down_revision: Union[str, None] = "0010_approvals_signals"
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
    """Create the artifacts table and its indexes. Idempotent."""
    if not _table_exists("artifacts"):
        op.create_table(
            "artifacts",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=True),
            sa.Column("step_id", sa.String(), nullable=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
            sa.Column(
                "content_type",
                sa.String(),
                nullable=False,
                server_default="application/octet-stream",
            ),
            sa.Column("content_hash", sa.String(), nullable=False),
            sa.Column(
                "size_bytes",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "storage_backend",
                sa.String(),
                nullable=False,
                server_default="local",
            ),
            sa.Column(
                "storage_uri",
                sa.String(),
                nullable=False,
                server_default="",
            ),
            sa.Column("retention_days", sa.Integer(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "meta",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.ForeignKeyConstraint(
                ["run_id"], ["workflow_runs.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists("artifacts", "ix_artifacts_run_id"):
        op.create_index(
            "ix_artifacts_run_id", "artifacts", ["run_id"], unique=False
        )
    if not _index_exists("artifacts", "ix_artifacts_tenant_id"):
        op.create_index(
            "ix_artifacts_tenant_id",
            "artifacts",
            ["tenant_id"],
            unique=False,
        )
    if not _index_exists("artifacts", "ix_artifacts_content_hash"):
        op.create_index(
            "ix_artifacts_content_hash",
            "artifacts",
            ["content_hash"],
            unique=False,
        )
    if not _index_exists("artifacts", "ix_artifacts_expires_at"):
        op.create_index(
            "ix_artifacts_expires_at",
            "artifacts",
            ["expires_at"],
            unique=False,
        )


def downgrade() -> None:
    """Drop the artifacts table and its indexes."""
    for ix in (
        "ix_artifacts_expires_at",
        "ix_artifacts_content_hash",
        "ix_artifacts_tenant_id",
        "ix_artifacts_run_id",
    ):
        if _index_exists("artifacts", ix):
            op.drop_index(ix, table_name="artifacts")
    if _table_exists("artifacts"):
        op.drop_table("artifacts")
