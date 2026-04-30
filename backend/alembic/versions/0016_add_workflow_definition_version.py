"""workflow_definition_versions — W11 / ADR-008 §5

Revision ID: 0016_add_workflow_definition_version
Revises: 0015_add_pipeline_correlation
Create Date: 2026-04-30

Owned by W11 (Definition Versioning). Creates the
``workflow_definition_versions`` table per ADR-008 §5.

Column names, constraints, and indexes are locked per ADR-008 §Locked.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0016_add_workflow_definition_version"
down_revision = "0015_add_pipeline_correlation"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _table_exists("workflow_definition_versions"):
        return
    op.create_table(
        "workflow_definition_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_snapshot", sa.JSON(), nullable=False),
        sa.Column("compatibility_set", sa.JSON(), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("deprecated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_workflow_def_version_number",
        ),
    )
    op.create_index(
        "ix_workflow_def_version_active",
        "workflow_definition_versions",
        ["workflow_id", "deprecated_at"],
    )
    op.create_index(
        "ix_workflow_def_version_tenant",
        "workflow_definition_versions",
        ["tenant_id", "created_at"],
    )
    # Standard indexed columns
    op.create_index(
        "ix_workflow_definition_versions_workflow_id",
        "workflow_definition_versions",
        ["workflow_id"],
    )
    op.create_index(
        "ix_workflow_definition_versions_tenant_id",
        "workflow_definition_versions",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_definition_versions_tenant_id",
        table_name="workflow_definition_versions",
    )
    op.drop_index(
        "ix_workflow_definition_versions_workflow_id",
        table_name="workflow_definition_versions",
    )
    op.drop_index(
        "ix_workflow_def_version_tenant",
        table_name="workflow_definition_versions",
    )
    op.drop_index(
        "ix_workflow_def_version_active",
        table_name="workflow_definition_versions",
    )
    op.drop_table("workflow_definition_versions")
