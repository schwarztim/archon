"""visibility_indexes — denormalised search row per WorkflowRun (W13 / ADR-008 §7)

Revision ID: 0018_add_visibility_index
Revises: 0015_add_pipeline_correlation
Create Date: 2026-04-30

Owned by W13 (Visibility and Search). Creates the ``visibility_indexes``
table as specified in ADR-008 §7. The table is a denormalised search index
maintained 1:1 with WorkflowRun — never the source of truth.

Column names and index names are locked per ADR-008 §Locked.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0018_add_visibility_index"
down_revision = "0015_add_pipeline_correlation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visibility_indexes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        # ── Mirrored from WorkflowRun ─────────────────────────────────
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("chain_id", sa.Uuid(), nullable=True),
        # ── Queue and worker attribution ──────────────────────────────
        sa.Column("queue_name", sa.String(), nullable=True),
        sa.Column("worker_id", sa.String(), nullable=True),
        sa.Column("definition_version_id", sa.Uuid(), nullable=True),
        # ── Operator tags ─────────────────────────────────────────────
        sa.Column("tags_json", sa.JSON(), nullable=False, server_default="{}"),
        # ── Aggregates ────────────────────────────────────────────────
        sa.Column(
            "cost_total_usd",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.0"),
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_code", sa.String(), nullable=True),
        # ── Pipeline correlation mirrors ──────────────────────────────
        sa.Column("external_provider", sa.String(), nullable=True),
        sa.Column("external_run_id", sa.String(), nullable=True),
        sa.Column("external_branch", sa.String(), nullable=True),
        sa.Column("external_environment", sa.String(), nullable=True),
        # ── Timeline ─────────────────────────────────────────────────
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # ── Constraints ───────────────────────────────────────────────
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", name="uq_visibility_workflow_run_id"),
    )

    # Per-column indexes
    op.create_index(
        "ix_visibility_indexes_tenant_id",
        "visibility_indexes",
        ["tenant_id"],
    )
    op.create_index(
        "ix_visibility_indexes_workflow_run_id",
        "visibility_indexes",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_visibility_indexes_workflow_id",
        "visibility_indexes",
        ["workflow_id"],
    )
    op.create_index(
        "ix_visibility_indexes_agent_id",
        "visibility_indexes",
        ["agent_id"],
    )
    op.create_index(
        "ix_visibility_indexes_chain_id",
        "visibility_indexes",
        ["chain_id"],
    )
    op.create_index(
        "ix_visibility_indexes_queue_name",
        "visibility_indexes",
        ["queue_name"],
    )
    op.create_index(
        "ix_visibility_indexes_worker_id",
        "visibility_indexes",
        ["worker_id"],
    )
    op.create_index(
        "ix_visibility_indexes_definition_version_id",
        "visibility_indexes",
        ["definition_version_id"],
    )
    op.create_index(
        "ix_visibility_indexes_failure_code",
        "visibility_indexes",
        ["failure_code"],
    )
    op.create_index(
        "ix_visibility_indexes_external_provider",
        "visibility_indexes",
        ["external_provider"],
    )
    op.create_index(
        "ix_visibility_indexes_external_run_id",
        "visibility_indexes",
        ["external_run_id"],
    )
    op.create_index(
        "ix_visibility_indexes_external_branch",
        "visibility_indexes",
        ["external_branch"],
    )
    op.create_index(
        "ix_visibility_indexes_external_environment",
        "visibility_indexes",
        ["external_environment"],
    )
    op.create_index(
        "ix_visibility_indexes_started_at",
        "visibility_indexes",
        ["started_at"],
    )

    # Compound indexes from ADR-008 §7
    op.create_index(
        "ix_visibility_tenant_status_started",
        "visibility_indexes",
        ["tenant_id", "status", "started_at"],
    )
    op.create_index(
        "ix_visibility_tenant_queue_started",
        "visibility_indexes",
        ["tenant_id", "queue_name", "started_at"],
    )
    op.create_index(
        "ix_visibility_tenant_worker",
        "visibility_indexes",
        ["tenant_id", "worker_id"],
    )
    op.create_index(
        "ix_visibility_external_run",
        "visibility_indexes",
        ["external_provider", "external_run_id"],
    )
    op.create_index(
        "ix_visibility_failure_code",
        "visibility_indexes",
        ["tenant_id", "failure_code"],
    )
    op.create_index(
        "ix_visibility_cost",
        "visibility_indexes",
        ["tenant_id", "cost_total_usd"],
    )


def downgrade() -> None:
    op.drop_index("ix_visibility_cost", table_name="visibility_indexes")
    op.drop_index("ix_visibility_failure_code", table_name="visibility_indexes")
    op.drop_index("ix_visibility_external_run", table_name="visibility_indexes")
    op.drop_index("ix_visibility_tenant_worker", table_name="visibility_indexes")
    op.drop_index("ix_visibility_tenant_queue_started", table_name="visibility_indexes")
    op.drop_index(
        "ix_visibility_tenant_status_started", table_name="visibility_indexes"
    )
    op.drop_index("ix_visibility_indexes_started_at", table_name="visibility_indexes")
    op.drop_index(
        "ix_visibility_indexes_external_environment", table_name="visibility_indexes"
    )
    op.drop_index(
        "ix_visibility_indexes_external_branch", table_name="visibility_indexes"
    )
    op.drop_index(
        "ix_visibility_indexes_external_run_id", table_name="visibility_indexes"
    )
    op.drop_index(
        "ix_visibility_indexes_external_provider", table_name="visibility_indexes"
    )
    op.drop_index("ix_visibility_indexes_failure_code", table_name="visibility_indexes")
    op.drop_index(
        "ix_visibility_indexes_definition_version_id", table_name="visibility_indexes"
    )
    op.drop_index("ix_visibility_indexes_worker_id", table_name="visibility_indexes")
    op.drop_index("ix_visibility_indexes_queue_name", table_name="visibility_indexes")
    op.drop_index("ix_visibility_indexes_chain_id", table_name="visibility_indexes")
    op.drop_index("ix_visibility_indexes_agent_id", table_name="visibility_indexes")
    op.drop_index("ix_visibility_indexes_workflow_id", table_name="visibility_indexes")
    op.drop_index(
        "ix_visibility_indexes_workflow_run_id", table_name="visibility_indexes"
    )
    op.drop_index("ix_visibility_indexes_tenant_id", table_name="visibility_indexes")
    op.drop_table("visibility_indexes")
