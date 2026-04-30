"""run_chains — W12 / ADR-008 §6

Revision ID: 0017_add_run_chain
Revises: 0016_add_workflow_definition_version
Create Date: 2026-04-30

Owned by W12 (Continue-as-New). Creates the ``run_chains`` table per
ADR-008 §6. WorkflowRun itself does NOT gain chain_id / parent_run_id
columns — join through RunChain.run_id.

Column names, constraints, and indexes are locked per ADR-008 §Locked.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0017_add_run_chain"
down_revision = "0016_add_workflow_definition_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_chains",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chain_id", sa.Uuid(), nullable=False),
        sa.Column("root_run_id", sa.Uuid(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("generation_number", sa.Integer(), nullable=False),
        sa.Column("compacted_state", sa.JSON(), nullable=True),
        sa.Column("continue_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(
            ["root_run_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["workflow_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chain_id",
            "generation_number",
            name="uq_run_chain_chain_generation",
        ),
        sa.UniqueConstraint(
            "run_id",
            name="uq_run_chain_run_id",
        ),
    )
    op.create_index(
        "ix_run_chain_chain",
        "run_chains",
        ["chain_id", "generation_number"],
    )
    op.create_index(
        "ix_run_chain_root",
        "run_chains",
        ["root_run_id"],
    )
    op.create_index(
        "ix_run_chain_parent",
        "run_chains",
        ["parent_run_id"],
    )
    op.create_index(
        "ix_run_chains_chain_id",
        "run_chains",
        ["chain_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_chains_chain_id", table_name="run_chains")
    op.drop_index("ix_run_chain_parent", table_name="run_chains")
    op.drop_index("ix_run_chain_root", table_name="run_chains")
    op.drop_index("ix_run_chain_chain", table_name="run_chains")
    op.drop_table("run_chains")
