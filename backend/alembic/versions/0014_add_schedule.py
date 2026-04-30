"""schedules — first-class schedule table (W7 / ADR-008 §9)

Revision ID: 0014_add_schedule
Revises: 0013_add_activity_execution
Create Date: 2026-04-30

Owned by W7 (Schedule Engine). Creates the ``schedules`` table with overlap
policy, jitter, catchup window, and XOR workflow/agent target per ADR-008 §9.

Column names and index names are locked per ADR-008 §Locked.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_add_schedule"
down_revision = "0013_add_activity_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        # Action target — XOR workflow or agent.
        sa.Column("workflow_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("definition_version_id", sa.Uuid(), nullable=True),
        # Schedule spec.
        sa.Column("calendar_spec", sa.Text(), nullable=False),
        sa.Column("spec_kind", sa.Text(), nullable=False, server_default="cron"),
        sa.Column("timezone", sa.Text(), nullable=False, server_default="UTC"),
        sa.Column("jitter_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_bound", sa.DateTime(), nullable=True),
        sa.Column("end_bound", sa.DateTime(), nullable=True),
        # Behaviour policy.
        sa.Column(
            "overlap_policy",
            sa.Text(),
            nullable=False,
            server_default="skip",
        ),
        sa.Column(
            "catchup_window_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "pause_on_failure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("input_template", sa.JSON(), nullable=False, server_default="{}"),
        # State columns.
        sa.Column(
            "paused",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("last_fire_attempted_at", sa.DateTime(), nullable=True),
        sa.Column("last_fire_succeeded_at", sa.DateTime(), nullable=True),
        sa.Column("last_successful_run_id", sa.Uuid(), nullable=True),
        sa.Column("next_fire_at", sa.DateTime(), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        # Constraints (locked per ADR-008).
        sa.CheckConstraint(
            "(workflow_id IS NULL) <> (agent_id IS NULL)",
            name="ck_schedules_workflow_xor_agent",
        ),
        sa.CheckConstraint(
            "spec_kind IN ('cron','rrule','interval')",
            name="ck_schedules_spec_kind",
        ),
        sa.CheckConstraint(
            "overlap_policy IN ('skip','buffer_one','buffer_all',"
            "'cancel_running','terminate_running','allow_all')",
            name="ck_schedules_overlap_policy",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_successful_run_id"],
            ["workflow_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Locked indexes per ADR-008.
    op.create_index("ix_schedules_tenant_paused", "schedules", ["tenant_id", "paused"])
    op.create_index("ix_schedules_next_fire", "schedules", ["next_fire_at", "paused"])
    op.create_index("ix_schedules_workflow_id", "schedules", ["workflow_id"])
    op.create_index("ix_schedules_agent_id", "schedules", ["agent_id"])
    op.create_index("ix_schedules_tenant_id", "schedules", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_schedules_agent_id", table_name="schedules")
    op.drop_index("ix_schedules_workflow_id", table_name="schedules")
    op.drop_index("ix_schedules_next_fire", table_name="schedules")
    op.drop_index("ix_schedules_tenant_paused", table_name="schedules")
    op.drop_index("ix_schedules_tenant_id", table_name="schedules")
    op.drop_table("schedules")
