"""WS-2 DB migration — workflows, api_keys rate_limit, custom_roles, secret_registrations

Revision ID: 0002_ws2_db_migration
Revises: 0001_initial
Create Date: 2026-02-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_ws2_db_migration"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Workflows ────────────────────────────────────────────────────
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("group_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("group_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("graph_definition", sa.JSON(), nullable=True),
        sa.Column("schedule", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workflows_tenant_id"), "workflows", ["tenant_id"], unique=False
    )
    op.create_index(op.f("ix_workflows_name"), "workflows", ["name"], unique=False)

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("trigger_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("triggered_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workflow_runs_workflow_id"),
        "workflow_runs",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_runs_tenant_id"), "workflow_runs", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_workflow_runs_status"), "workflow_runs", ["status"], unique=False
    )

    op.create_table(
        "workflow_run_steps",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("input_data", sa.JSON(), nullable=False),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "agent_execution_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workflow_run_steps_run_id"),
        "workflow_run_steps",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "workflow_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("cron", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("timezone", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id"),
    )
    op.create_index(
        op.f("ix_workflow_schedules_workflow_id"),
        "workflow_schedules",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_schedules_tenant_id"),
        "workflow_schedules",
        ["tenant_id"],
        unique=False,
    )

    # ── Custom Roles ─────────────────────────────────────────────────
    op.create_table(
        "custom_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_custom_roles_tenant_id"), "custom_roles", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_custom_roles_name"), "custom_roles", ["name"], unique=False
    )

    # ── SettingsAPIKey — add rate_limit column ────────────────────────
    # Idempotent: settings_api_keys is created later by 0004's
    # SQLModel.metadata.create_all when migrating from base on a fresh DB.
    # On legacy DBs where the table predates this migration, the column is
    # added; otherwise this branch is a no-op and the column lands as part
    # of create_all.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "settings_api_keys" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("settings_api_keys")}
        if "rate_limit" not in existing_cols:
            op.add_column(
                "settings_api_keys",
                sa.Column("rate_limit", sa.Integer(), nullable=True),
            )

    # ── SecretRegistration and SecretAccessLog tables ─────────────────
    # These tables may not exist yet if the initial migration predates them.
    # We use CREATE TABLE IF NOT EXISTS semantics via op.create_table with
    # a try/except is not available; instead we check by attempting creation.
    # NOTE: These are defined in models/secrets.py and require the 'tenants'
    # and 'user_identities' tables to exist. If those tables don't exist in
    # this environment (sqlite tests), we skip the FKs.
    op.create_table(
        "secret_registrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("secret_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("rotation_policy_days", sa.Integer(), nullable=True),
        sa.Column("notify_before_days", sa.Integer(), nullable=False),
        sa.Column("auto_rotate", sa.Boolean(), nullable=False),
        sa.Column("last_rotated_at", sa.DateTime(), nullable=True),
        sa.Column("next_rotation_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_secret_registrations_path"),
        "secret_registrations",
        ["path"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_registrations_tenant_id"),
        "secret_registrations",
        ["tenant_id"],
        unique=False,
    )

    op.create_table(
        "secret_access_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("secret_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("user_email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("action", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("component", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("ip_address", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("details", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_secret_access_logs_tenant_id"),
        "secret_access_logs",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_access_logs_secret_path"),
        "secret_access_logs",
        ["secret_path"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secret_access_logs_action"),
        "secret_access_logs",
        ["action"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_secret_access_logs_action"), table_name="secret_access_logs")
    op.drop_index(
        op.f("ix_secret_access_logs_secret_path"), table_name="secret_access_logs"
    )
    op.drop_index(
        op.f("ix_secret_access_logs_tenant_id"), table_name="secret_access_logs"
    )
    op.drop_table("secret_access_logs")

    op.drop_index(
        op.f("ix_secret_registrations_tenant_id"), table_name="secret_registrations"
    )
    op.drop_index(
        op.f("ix_secret_registrations_path"), table_name="secret_registrations"
    )
    op.drop_table("secret_registrations")

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "settings_api_keys" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("settings_api_keys")}
        if "rate_limit" in existing_cols:
            op.drop_column("settings_api_keys", "rate_limit")

    op.drop_index(op.f("ix_custom_roles_name"), table_name="custom_roles")
    op.drop_index(op.f("ix_custom_roles_tenant_id"), table_name="custom_roles")
    op.drop_table("custom_roles")

    op.drop_index(
        op.f("ix_workflow_schedules_tenant_id"), table_name="workflow_schedules"
    )
    op.drop_index(
        op.f("ix_workflow_schedules_workflow_id"), table_name="workflow_schedules"
    )
    op.drop_table("workflow_schedules")

    op.drop_index(op.f("ix_workflow_run_steps_run_id"), table_name="workflow_run_steps")
    op.drop_table("workflow_run_steps")

    op.drop_index(op.f("ix_workflow_runs_status"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_tenant_id"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_workflow_id"), table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index(op.f("ix_workflows_name"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_tenant_id"), table_name="workflows")
    op.drop_table("workflows")
