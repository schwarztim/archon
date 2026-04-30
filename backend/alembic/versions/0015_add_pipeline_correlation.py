"""pipeline_correlations — CI/CD pipeline ingress correlation (W8 / ADR-008 §4)

Revision ID: 0015_add_pipeline_correlation
Revises: 0014_add_schedule
Create Date: 2026-04-30

Owned by W8 (Pipeline Ingress and Run Correlation). Creates the
``pipeline_correlations`` table linking WorkflowRun rows to external
CI/CD pipeline events with provider-event idempotency and signed callbacks.

Column names and index names are locked per ADR-008 §Locked.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0015_add_pipeline_correlation"
down_revision = "0014_add_schedule"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("pipeline_correlations"):
        return
    op.create_table(
        "pipeline_correlations",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Tenant — nullable in schema; W8 enforces non-null at app layer.
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        # FK to workflow_runs with CASCADE delete.
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        # Provider identity — locked enum via CHECK constraint.
        sa.Column("provider", sa.Text(), nullable=False),
        # Provider-specific event identifiers.
        sa.Column("external_event_id", sa.Text(), nullable=False),
        sa.Column("external_run_id", sa.Text(), nullable=True),
        sa.Column("external_pipeline_id", sa.Text(), nullable=True),
        sa.Column("external_commit_sha", sa.Text(), nullable=True),
        sa.Column("external_branch", sa.Text(), nullable=True),
        sa.Column("external_actor", sa.Text(), nullable=True),
        sa.Column("environment", sa.Text(), nullable=True),
        # Callback destination (secret path, not the secret itself).
        sa.Column("callback_url", sa.Text(), nullable=True),
        sa.Column("callback_url_secret_ref", sa.Text(), nullable=True),
        # Application-computed idempotency key: sha256(provider + external_event_id).
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # PK.
        sa.PrimaryKeyConstraint("id"),
        # Locked constraints per ADR-008 §4.
        sa.UniqueConstraint(
            "provider",
            "external_event_id",
            name="uq_pipeline_corr_provider_event",
        ),
        sa.CheckConstraint(
            "provider IN ('github_actions','azure_devops','jenkins',"
            "'gitlab','generic_webhook')",
            name="ck_pipeline_corr_provider",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
    )

    # Partial-unique index for application idempotency key (ADR-004 pattern).
    op.execute(
        """
        CREATE UNIQUE INDEX uq_pipeline_corr_idem
        ON pipeline_correlations (tenant_id, idempotency_key)
        WHERE idempotency_key IS NOT NULL
        """
    )

    # Locked indexes per ADR-008 §4.
    op.create_index("ix_pipeline_corr_run", "pipeline_correlations", ["workflow_run_id"])
    op.create_index(
        "ix_pipeline_corr_external",
        "pipeline_correlations",
        ["provider", "external_run_id"],
    )
    op.create_index(
        "ix_pipeline_corr_tenant_created",
        "pipeline_correlations",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_pipeline_corr_tenant_id",
        "pipeline_correlations",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_corr_tenant_id", table_name="pipeline_correlations")
    op.drop_index("ix_pipeline_corr_tenant_created", table_name="pipeline_correlations")
    op.drop_index("ix_pipeline_corr_external", table_name="pipeline_correlations")
    op.drop_index("ix_pipeline_corr_run", table_name="pipeline_correlations")
    op.execute("DROP INDEX IF EXISTS uq_pipeline_corr_idem")
    op.drop_table("pipeline_correlations")
