"""post_audit_consolidated — merge branches and add missing tables

Revision ID: 0004_post_audit_consolidated
Revises: 0003_add_audit_logs_table, 0002_ws2_db_migration
Create Date: 2026-04-28

Merges the two migration branches that diverged from 0001_initial:
  - Branch A: 0001 → 0002_add_router_cost_dlp_tables → 0003_add_audit_logs_table
  - Branch B: 0001 → 0002_ws2_db_migration

This migration resolves the multi-head state and creates any tables
declared by SQLModel models that are not yet present in the schema,
using CREATE TABLE IF NOT EXISTS semantics via SQLModel.metadata.create_all.

After this migration, `alembic upgrade head` can be called idempotently
without data loss. The startup hook (init_db) no longer drops tables.

NOTE: This migration cannot use autogenerate because autogenerate requires
a live database connection. Instead, we use SQLModel.metadata.create_all
which is safe for tables that do not yet exist and is a no-op for tables
that already exist.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# Module-level imports so SQLModel.metadata is fully populated before upgrade()
# runs. Wildcard imports inside function bodies are a SyntaxError under Python
# 3.12 in some configurations; keeping this at module level is portable.
import app.models  # noqa: F401, E402

# revision identifiers, used by Alembic.
revision: str = "0004_post_audit_consolidated"
# Merges both branch heads into a single head.
down_revision: Union[tuple[str, ...], None] = (
    "0003_add_audit_logs_table",
    "0002_ws2_db_migration",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create any tables not yet in the schema.

    Uses create_all(checkfirst=True) which is a no-op for existing tables.
    This is intentionally safe: calling upgrade() twice has no effect.
    """
    # Models already imported at module level (see top of file).
    # SQLModel.metadata is fully populated by the time upgrade() runs.
    from sqlmodel import SQLModel

    bind = op.get_bind()
    # create_all with checkfirst=True is equivalent to CREATE TABLE IF NOT EXISTS.
    # It will not drop, alter, or re-create any existing table.
    SQLModel.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    """No destructive downgrade.

    Splitting a merge migration back into two branches is not safely
    automatable. To tear down schema, use `make db-reset` explicitly.
    """
    pass
