"""add_tenant_id_to_visual_rule

Adds ``tenant_id`` column to the ``visual_rules`` table so that routing rules
are scoped per-tenant, preventing one tenant's config from overwriting another's.

Revision ID: 0006_add_tenant_id_to_visual_rule
Revises: 0005_persist_inmemory_state
Create Date: 2026-04-28

Note: column is added as nullable=True. Backfilling existing rows with the
correct tenant_id is the operator's responsibility before enabling strict
tenant filtering in the route handlers (backend/app/routes/router.py).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_add_tenant_id_to_visual_rule"
down_revision: Union[str, None] = "0005_persist_inmemory_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tenant_id column and index to visual_rules."""
    op.add_column(
        "visual_rules",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_visual_rules_tenant_id",
        "visual_rules",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove tenant_id column and index from visual_rules."""
    op.drop_index("ix_visual_rules_tenant_id", table_name="visual_rules")
    op.drop_column("visual_rules", "tenant_id")
