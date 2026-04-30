"""canonical_run_substrate — unified run model + hash-chained event log

Revision ID: 0007_canonical_run_substrate
Revises: 0006_add_tenant_id_to_visual_rule
Create Date: 2026-04-29

Implements ADR-001 (unified WorkflowRun for workflow + agent runs),
ADR-002 (workflow_run_events with hash chain),
ADR-004 (idempotency_key, input_hash, partial unique index),
ADR-007 (workflow_id nullable, ondelete=SET NULL).

Schema deltas applied here:
  - workflow_runs gains 19 columns (agent_id, kind, definition_snapshot,
    definition_version, queued_at, claimed_at, paused_at, resumed_at,
    cancel_requested_at, lease_owner, lease_expires_at, attempt,
    idempotency_key, input_hash, output_data, metrics, error_code).
  - workflow_runs.workflow_id becomes nullable; FK gains
    ondelete="SET NULL".
  - workflow_runs gains the ck_workflow_runs_workflow_xor_agent
    CHECK constraint and a partial unique index on
    (tenant_id, idempotency_key) WHERE idempotency_key IS NOT NULL.
  - workflow_run_steps gains 10 columns (attempt, retry_count,
    idempotency_key, checkpoint_thread_id, input_hash,
    output_artifact_id, token_usage, cost_usd, worker_id, error_code).
  - workflow_run_events table is created from scratch with the 11
    columns required by ADR-002.

Backfill: existing WorkflowRun rows with workflow_id IS NOT NULL get
kind="workflow" and definition_snapshot={"_legacy": True}.

The migration uses op.batch_alter_table for SQLite compatibility on the
constraint+nullability changes; PostgreSQL falls through to direct ALTER.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_canonical_run_substrate"
down_revision: Union[str, None] = "0006_add_tenant_id_to_visual_rule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_sqlite() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "sqlite"


def _table_exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def _index_exists(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return any(i["name"] == name for i in insp.get_indexes(table))


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    """Idempotent op.add_column — skip if 0004's create_all already added it."""
    if not _column_exists(table, column.name):
        op.add_column(table, column)


def _create_index_if_missing(
    name: str, table: str, cols: list[str], **kwargs
) -> None:
    if not _index_exists(table, name):
        op.create_index(name, table, cols, **kwargs)


def upgrade() -> None:
    """Apply ADR-001 / ADR-002 / ADR-004 / ADR-007 schema deltas.

    Idempotent: 0004's SQLModel.metadata.create_all may have already
    materialised these schema elements when migrating from base on a
    fresh DB. We skip operations that would collide with existing
    schema state instead of failing.
    """

    # ── 1. Extend workflow_runs ────────────────────────────────────────
    # Add new columns (all initially nullable / with server_default so the
    # ALTER does not need to backfill row-by-row).
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("agent_id", sa.Uuid(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="workflow",
        ),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column(
            "definition_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{\"_legacy\":true}'"),
        ),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("definition_version", sa.String(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("queued_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("paused_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("resumed_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("lease_owner", sa.String(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("input_hash", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("output_data", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("metrics", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_runs",
        sa.Column("error_code", sa.String(), nullable=True),
    )

    # Backfill kind for any pre-existing rows (server_default already
    # applied "workflow" for us; this is a defensive pass).
    op.execute(
        "UPDATE workflow_runs "
        "SET kind = 'workflow' "
        "WHERE kind IS NULL OR kind = ''"
    )

    # ── 2. Make workflow_id nullable + repoint FK with ondelete=SET NULL.
    # ── 3. Add CHECK and the agent_id FK.
    # SQLite cannot ALTER constraints in place. We pass a naming_convention
    # to the batch context so that reflected unnamed FKs get a deterministic
    # name we can drop, then add the replacement FK with ondelete=SET NULL
    # and the agent_id FK.
    # Skip the batch_alter_table dance entirely if the CHECK constraint
    # already exists (i.e. 0004's metadata.create_all already produced the
    # final schema). Idempotency for fresh-DB upgrades.
    insp = sa.inspect(op.get_bind())
    existing_check_names = {
        ck.get("name") for ck in insp.get_check_constraints("workflow_runs")
    } if "workflow_runs" in insp.get_table_names() else set()
    if "ck_workflow_runs_workflow_xor_agent" not in existing_check_names:
        naming_convention = {
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        }
        with op.batch_alter_table(
            "workflow_runs",
            recreate="always",
            naming_convention=naming_convention,
        ) as batch_op:
            batch_op.alter_column(
                "workflow_id",
                existing_type=sa.Uuid(),
                nullable=True,
            )
            try:
                batch_op.drop_constraint(
                    "fk_workflow_runs_workflow_id_workflows", type_="foreignkey"
                )
            except Exception:
                pass  # FK may not exist on fresh-create-all schemas
            batch_op.create_foreign_key(
                "fk_workflow_runs_workflow_id_workflows",
                "workflows",
                ["workflow_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_foreign_key(
                "fk_workflow_runs_agent_id_agents",
                "agents",
                ["agent_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch_op.create_check_constraint(
                "ck_workflow_runs_workflow_xor_agent",
                "(workflow_id IS NULL) <> (agent_id IS NULL)",
            )

    _create_index_if_missing(
        "ix_workflow_runs_agent_id",
        "workflow_runs",
        ["agent_id"],
        unique=False,
    )
    _create_index_if_missing(
        "ix_workflow_runs_kind",
        "workflow_runs",
        ["kind"],
        unique=False,
    )
    _create_index_if_missing(
        "ix_workflow_runs_tenant_id_status",
        "workflow_runs",
        ["tenant_id", "status"],
        unique=False,
    )

    # ── 4. ADR-004 partial unique index on (tenant_id, idempotency_key).
    _create_index_if_missing(
        "uq_workflow_runs_tenant_idem",
        "workflow_runs",
        ["tenant_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # Drop the server_default we used to land definition_snapshot — future
    # inserts must supply the snapshot explicitly (ADR-001 §Forbidden).
    with op.batch_alter_table("workflow_runs", recreate="auto") as batch_op:
        batch_op.alter_column(
            "definition_snapshot",
            existing_type=sa.JSON(),
            server_default=None,
            existing_nullable=False,
        )
        batch_op.alter_column(
            "kind",
            existing_type=sa.String(length=32),
            server_default=None,
            existing_nullable=False,
        )

    # ── 5. Extend workflow_run_steps ───────────────────────────────────
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("checkpoint_thread_id", sa.String(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("input_hash", sa.String(length=64), nullable=True),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("output_artifact_id", sa.Uuid(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column(
            "token_usage",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("cost_usd", sa.Float(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("worker_id", sa.String(), nullable=True),
    )
    _add_column_if_missing(
        "workflow_run_steps",
        sa.Column("error_code", sa.String(), nullable=True),
    )
    _create_index_if_missing(
        "ix_workflow_run_steps_run_id_attempt",
        "workflow_run_steps",
        ["run_id", "attempt"],
        unique=False,
    )

    # ── 6. Create workflow_run_events table (ADR-002) ──────────────────
    if not _table_exists("workflow_run_events"):
        op.create_table(
            "workflow_run_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("tenant_id", sa.Uuid(), nullable=True),
            sa.Column("correlation_id", sa.String(), nullable=True),
            sa.Column("span_id", sa.String(), nullable=True),
            sa.Column("step_id", sa.String(), nullable=True),
            sa.Column("prev_hash", sa.String(length=64), nullable=True),
            sa.Column("current_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["run_id"], ["workflow_runs.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint(
                "run_id", "sequence", name="uq_run_events_run_sequence"
            ),
            sa.CheckConstraint(
                "event_type IN ("
                "'run.created','run.queued','run.claimed','run.started',"
                "'run.completed','run.failed','run.cancelled',"
                "'run.paused','run.resumed',"
                "'step.started','step.completed','step.failed',"
                "'step.skipped','step.retry','step.paused'"
                ")",
                name="ck_run_events_event_type",
            ),
        )
    _create_index_if_missing(
        "ix_workflow_run_events_run_id",
        "workflow_run_events",
        ["run_id"],
        unique=False,
    )
    _create_index_if_missing(
        "ix_run_events_run_id_sequence",
        "workflow_run_events",
        ["run_id", "sequence"],
        unique=False,
    )
    _create_index_if_missing(
        "ix_workflow_run_events_tenant_id",
        "workflow_run_events",
        ["tenant_id"],
        unique=False,
    )
    _create_index_if_missing(
        "ix_run_events_tenant_id_created_at",
        "workflow_run_events",
        ["tenant_id", "created_at"],
        unique=False,
    )
    _create_index_if_missing(
        "ix_run_events_correlation_id",
        "workflow_run_events",
        ["correlation_id"],
        unique=False,
    )


def downgrade() -> None:
    """Reverse the upgrade in strict reverse order."""

    # ── 6. Drop workflow_run_events ────────────────────────────────────
    op.drop_index("ix_run_events_correlation_id", table_name="workflow_run_events")
    op.drop_index(
        "ix_run_events_tenant_id_created_at", table_name="workflow_run_events"
    )
    op.drop_index(
        "ix_workflow_run_events_tenant_id", table_name="workflow_run_events"
    )
    op.drop_index("ix_run_events_run_id_sequence", table_name="workflow_run_events")
    op.drop_index("ix_workflow_run_events_run_id", table_name="workflow_run_events")
    op.drop_table("workflow_run_events")

    # ── 5. Strip workflow_run_steps additions ──────────────────────────
    op.drop_index(
        "ix_workflow_run_steps_run_id_attempt", table_name="workflow_run_steps"
    )
    op.drop_column("workflow_run_steps", "error_code")
    op.drop_column("workflow_run_steps", "worker_id")
    op.drop_column("workflow_run_steps", "cost_usd")
    op.drop_column("workflow_run_steps", "token_usage")
    op.drop_column("workflow_run_steps", "output_artifact_id")
    op.drop_column("workflow_run_steps", "input_hash")
    op.drop_column("workflow_run_steps", "checkpoint_thread_id")
    op.drop_column("workflow_run_steps", "idempotency_key")
    op.drop_column("workflow_run_steps", "retry_count")
    op.drop_column("workflow_run_steps", "attempt")

    # ── 4. Drop the partial unique index ──────────────────────────────
    op.drop_index("uq_workflow_runs_tenant_idem", table_name="workflow_runs")

    # ── 3. + 2. Drop CHECK / FKs / new indexes from workflow_runs ─────
    op.drop_index("ix_workflow_runs_tenant_id_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_kind", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_agent_id", table_name="workflow_runs")

    # Drop CHECK + agent_id FK + reset workflow_id FK to the
    # pre-migration shape (no ondelete clause). We use ``naming_convention``
    # so the auto-named FK we created on upgrade can be dropped by name on
    # SQLite where it would otherwise be anonymous.
    naming_convention = {
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    }
    with op.batch_alter_table(
        "workflow_runs",
        recreate="always",
        naming_convention=naming_convention,
    ) as batch_op:
        batch_op.drop_constraint(
            "ck_workflow_runs_workflow_xor_agent", type_="check"
        )
        batch_op.drop_constraint(
            "fk_workflow_runs_agent_id_agents", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_workflow_runs_workflow_id_workflows", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_workflow_runs_workflow_id_workflows",
            "workflows",
            ["workflow_id"],
            ["id"],
        )
    # Note: We do NOT re-impose NOT NULL on workflow_id because rows
    # inserted post-upgrade are permitted to have workflow_id IS NULL.
    # Re-imposing it would break a downgrade following any insert of an
    # agent run. This is the correct, lossless downgrade.

    # ── 1. Strip workflow_runs additions ───────────────────────────────
    op.drop_column("workflow_runs", "error_code")
    op.drop_column("workflow_runs", "metrics")
    op.drop_column("workflow_runs", "output_data")
    op.drop_column("workflow_runs", "input_hash")
    op.drop_column("workflow_runs", "idempotency_key")
    op.drop_column("workflow_runs", "attempt")
    op.drop_column("workflow_runs", "lease_expires_at")
    op.drop_column("workflow_runs", "lease_owner")
    op.drop_column("workflow_runs", "cancel_requested_at")
    op.drop_column("workflow_runs", "resumed_at")
    op.drop_column("workflow_runs", "paused_at")
    op.drop_column("workflow_runs", "claimed_at")
    op.drop_column("workflow_runs", "queued_at")
    op.drop_column("workflow_runs", "definition_version")
    op.drop_column("workflow_runs", "definition_snapshot")
    op.drop_column("workflow_runs", "kind")
    op.drop_column("workflow_runs", "agent_id")
