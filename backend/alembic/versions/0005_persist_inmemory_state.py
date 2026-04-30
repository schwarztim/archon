"""persist_inmemory_state — add sso_configs and visual_rules tables

Revision ID: 0005_persist_inmemory_state
Revises: 0004_post_audit_consolidated
Create Date: 2026-04-28

Replaces the in-memory dicts/lists in:
  - backend/app/routes/sso_config.py  (_sso_configs dict)
  - backend/app/routes/router.py      (_visual_rules_store list)

with proper DB-backed tables so data survives restarts and works
correctly across horizontally-scaled replicas.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_persist_inmemory_state"
down_revision: Union[str, None] = "0004_post_audit_consolidated"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create sso_configs and visual_rules tables."""
    op.create_table(
        "sso_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("sso_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("protocol", sa.String(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        # OIDC fields
        sa.Column("discovery_url", sa.String(), nullable=False, server_default=""),
        sa.Column("client_id", sa.String(), nullable=False, server_default=""),
        sa.Column("scopes", sa.JSON(), nullable=True),
        # SAML fields
        sa.Column("metadata_url", sa.String(), nullable=False, server_default=""),
        sa.Column("metadata_xml", sa.String(), nullable=False, server_default=""),
        sa.Column("entity_id", sa.String(), nullable=False, server_default=""),
        sa.Column("acs_url", sa.String(), nullable=False, server_default=""),
        # LDAP fields
        sa.Column("host", sa.String(), nullable=False, server_default=""),
        sa.Column("port", sa.Integer(), nullable=False, server_default="389"),
        sa.Column("use_tls", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("base_dn", sa.String(), nullable=False, server_default=""),
        sa.Column("bind_dn", sa.String(), nullable=False, server_default=""),
        sa.Column("user_filter", sa.String(), nullable=False, server_default="(objectClass=person)"),
        sa.Column("group_filter", sa.String(), nullable=False, server_default="(objectClass=group)"),
        # Secret presence flags
        sa.Column("client_secret_set", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("certificate_set", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("bind_secret_set", sa.Boolean(), nullable=False, server_default="false"),
        # JSON blob for claim mappings
        sa.Column("claim_mappings", sa.JSON(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sso_id"),
    )
    op.create_index("ix_sso_configs_tenant_id", "sso_configs", ["tenant_id"])
    op.create_index("ix_sso_configs_sso_id", "sso_configs", ["sso_id"])

    op.create_table(
        "visual_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("action", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop sso_configs and visual_rules tables."""
    op.drop_index("ix_sso_configs_sso_id", table_name="sso_configs")
    op.drop_index("ix_sso_configs_tenant_id", table_name="sso_configs")
    op.drop_table("sso_configs")
    op.drop_table("visual_rules")
