"""approvals + signals — typed substrate for human-in-loop pause/resume

Revision ID: 0010_approvals_signals
Revises: 0009_timers_table
Create Date: 2026-04-29

Owned by WS8. Closes Conflict 5 from the master plan: replaces the
broken raw-SQL ``pending_approvals`` insert that ``humanApprovalNode``
was performing. The two new tables provide:

  approvals   — explicit lifecycle for a pending human decision
                (pending → approved/rejected/expired). Tenant-scoped.

  signals     — generic durable signal queue. The dispatcher consumes
                signals to drive the resume path (approval granted,
                input provided, cancel injected, custom).

Schema:
  approvals
    id              UUID  PRIMARY KEY
    run_id          UUID  NOT NULL  FK workflow_runs(id) ON DELETE CASCADE
    step_id         TEXT  NOT NULL  (server_default '')
    tenant_id       UUID  NULLABLE  (indexed)
    requester_id    UUID  NULLABLE
    approver_id     UUID  NULLABLE
    status          TEXT  NOT NULL  (server_default 'pending', indexed)
    decision_reason TEXT  NULLABLE
    requested_at    TS    NOT NULL  (server_default current_timestamp)
    decided_at      TS    NULLABLE
    expires_at      TS    NULLABLE
    payload         JSON  NOT NULL  (server_default '{}')

  signals
    id           UUID  PRIMARY KEY
    run_id       UUID  NOT NULL  FK workflow_runs(id) ON DELETE CASCADE
    step_id      TEXT  NULLABLE
    signal_type  TEXT  NOT NULL  (indexed)
    payload      JSON  NOT NULL  (server_default '{}')
    consumed_at  TS    NULLABLE
    created_at   TS    NOT NULL  (server_default current_timestamp)

Indexes:
  ix_approvals_run_id     on (run_id)
  ix_approvals_tenant_id  on (tenant_id)
  ix_approvals_status     on (status)
  ix_signals_run_id       on (run_id)
  ix_signals_signal_type  on (signal_type)
  ix_signals_run_id_consumed_at on (run_id, consumed_at) — atomic-consume hot path

Idempotent (matches 0007 / 0008 / 0009 inline-fix convention): each
create is gated by inspector existence checks so re-running an upgrade
on a database that already has the tables is a no-op.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401  — required for Alembic Mako template parity
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0010_approvals_signals"
down_revision: Union[str, None] = "0009_timers_table"
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
    """Create approvals + signals tables and their indexes. Idempotent."""

    # ── approvals ─────────────────────────────────────────────────────
    if not _table_exists("approvals"):
        op.create_table(
            "approvals",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column(
                "step_id", sa.String(), nullable=False, server_default=""
            ),
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
            sa.Column("requester_id", sa.Uuid(), nullable=True),
            sa.Column("approver_id", sa.Uuid(), nullable=True),
            sa.Column(
                "status",
                sa.String(),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("decision_reason", sa.String(), nullable=True),
            sa.Column(
                "requested_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column(
                "payload",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.ForeignKeyConstraint(
                ["run_id"], ["workflow_runs.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists("approvals", "ix_approvals_run_id"):
        op.create_index(
            "ix_approvals_run_id", "approvals", ["run_id"], unique=False
        )
    if not _index_exists("approvals", "ix_approvals_tenant_id"):
        op.create_index(
            "ix_approvals_tenant_id",
            "approvals",
            ["tenant_id"],
            unique=False,
        )
    if not _index_exists("approvals", "ix_approvals_status"):
        op.create_index(
            "ix_approvals_status", "approvals", ["status"], unique=False
        )

    # ── signals ───────────────────────────────────────────────────────
    if not _table_exists("signals"):
        op.create_table(
            "signals",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("step_id", sa.String(), nullable=True),
            sa.Column("signal_type", sa.String(), nullable=False),
            sa.Column(
                "payload",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column("consumed_at", sa.DateTime(), nullable=True),
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

    if not _index_exists("signals", "ix_signals_run_id"):
        op.create_index(
            "ix_signals_run_id", "signals", ["run_id"], unique=False
        )
    if not _index_exists("signals", "ix_signals_signal_type"):
        op.create_index(
            "ix_signals_signal_type",
            "signals",
            ["signal_type"],
            unique=False,
        )
    if not _index_exists("signals", "ix_signals_run_id_consumed_at"):
        op.create_index(
            "ix_signals_run_id_consumed_at",
            "signals",
            ["run_id", "consumed_at"],
            unique=False,
        )


def downgrade() -> None:
    """Drop signals + approvals tables and their indexes."""

    # ── signals ───────────────────────────────────────────────────────
    for ix in (
        "ix_signals_run_id_consumed_at",
        "ix_signals_signal_type",
        "ix_signals_run_id",
    ):
        if _index_exists("signals", ix):
            op.drop_index(ix, table_name="signals")
    if _table_exists("signals"):
        op.drop_table("signals")

    # ── approvals ─────────────────────────────────────────────────────
    for ix in (
        "ix_approvals_status",
        "ix_approvals_tenant_id",
        "ix_approvals_run_id",
    ):
        if _index_exists("approvals", ix):
            op.drop_index(ix, table_name="approvals")
    if _table_exists("approvals"):
        op.drop_table("approvals")
