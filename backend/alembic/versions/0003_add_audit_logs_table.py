"""add_audit_logs_table

Revision ID: 0003_add_audit_logs_table
Revises: 0002_add_router_cost_dlp_tables
Create Date: 2026-02-25

Creates the consolidated audit_logs table with tamper-evident hash chain
and RLS tenant isolation policy.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_add_audit_logs_table"
down_revision: Union[str, None] = "0002_add_router_cost_dlp_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Text(),
            nullable=False,
            server_default="default",
        ),
        sa.Column("correlation_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        # Tamper-evident SHA-256 hash chain
        sa.Column("hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("prev_hash", sa.Text(), nullable=False, server_default="genesis"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )

    # Indexes for efficient lookups
    op.create_index(
        "ix_audit_logs_tenant_id",
        "audit_logs",
        ["tenant_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_audit_logs_correlation_id",
        "audit_logs",
        ["correlation_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_audit_logs_actor_id",
        "audit_logs",
        ["actor_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_audit_logs_resource_type",
        "audit_logs",
        ["resource_type"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_audit_logs_resource_id",
        "audit_logs",
        ["resource_id"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_audit_logs_hash",
        "audit_logs",
        ["hash"],
        unique=False,
        if_not_exists=True,
    )
    op.create_index(
        "ix_audit_logs_created_at",
        "audit_logs",
        ["created_at"],
        unique=False,
        if_not_exists=True,
    )

    # Enable RLS with tenant isolation (Postgres-only; no-op on SQLite)
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY")
        op.execute("""
            CREATE POLICY rls_tenant_policy ON audit_logs
            USING (tenant_id::text = current_setting('app.tenant_id', true))
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS rls_tenant_policy ON audit_logs")
        op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")
    op.drop_table("audit_logs", if_exists=True)
