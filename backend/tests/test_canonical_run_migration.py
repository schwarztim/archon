"""Migration test: 0007_canonical_run_substrate upgrade + downgrade.

Strategy: a fresh in-memory SQLite database is created with the
pre-migration shape (built from SQLModel.metadata after temporarily
hiding the ADR-001/002/004 additions). The migration's upgrade() is
run via Alembic's MigrationContext on that connection; the schema is
asserted; a row is round-tripped; downgrade() is run; the schema is
asserted again to confirm a clean reversal.

This pattern bypasses Alembic's ScriptDirectory loader so that pre-
existing chain issues in unrelated revisions cannot mask correctness
of the 0007 migration logic. The migration module is loaded directly
via importlib.

Acceptance:
  - Upgrade applies cleanly on fresh sqlite, all new columns and the
    workflow_run_events table exist.
  - A backfill of a legacy row produces kind="workflow" and a non-empty
    definition_snapshot.
  - Downgrade drops everything 0007 added (idempotent on the columns
    that pre-existed the migration).
"""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0007_canonical_run_substrate.py"
)


def _load_migration_module():
    """Import the 0007 migration module directly without alembic.script."""
    spec = importlib.util.spec_from_file_location(
        "archon_migration_0007", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_pre_migration_schema(conn) -> None:
    """Create the workflow_runs / workflow_run_steps tables in the shape
    they had immediately before 0007 ran.

    We do NOT call SQLModel.metadata.create_all here because the SQLModel
    metadata reflects the POST-0007 model (it is the target shape, not
    the prior shape). Hand-crafting the prior shape keeps the test
    isolated from model drift.
    """
    # Minimal workflows + agents + users tables for FK satisfaction.
    conn.execute(text(
        "CREATE TABLE users ("
        "id BLOB PRIMARY KEY, email TEXT, name TEXT, role TEXT,"
        "tenant_id BLOB, created_at DATETIME, updated_at DATETIME)"
    ))
    conn.execute(text(
        "CREATE TABLE agents ("
        "id BLOB PRIMARY KEY, name TEXT, definition JSON,"
        "owner_id BLOB, created_at DATETIME, updated_at DATETIME,"
        "FOREIGN KEY(owner_id) REFERENCES users(id))"
    ))
    conn.execute(text(
        "CREATE TABLE workflows ("
        "id BLOB PRIMARY KEY,"
        "tenant_id BLOB, name TEXT, description TEXT,"
        "group_id TEXT, group_name TEXT,"
        "steps JSON NOT NULL, graph_definition JSON,"
        "trigger_config JSON, schedule TEXT, is_active BOOLEAN,"
        "created_by TEXT, created_at DATETIME, updated_at DATETIME)"
    ))
    # Pre-0007 workflow_runs (workflow_id NOT NULL, no agent_id, no snapshot)
    conn.execute(text(
        "CREATE TABLE workflow_runs ("
        "id BLOB PRIMARY KEY,"
        "workflow_id BLOB NOT NULL,"
        "tenant_id BLOB,"
        "status TEXT,"
        "trigger_type TEXT,"
        "input_data JSON,"
        "triggered_by TEXT,"
        "started_at DATETIME,"
        "completed_at DATETIME,"
        "duration_ms INTEGER,"
        "error TEXT,"
        "created_at DATETIME,"
        "FOREIGN KEY(workflow_id) REFERENCES workflows(id))"
    ))
    conn.execute(text(
        "CREATE TABLE workflow_run_steps ("
        "id BLOB PRIMARY KEY,"
        "run_id BLOB NOT NULL,"
        "step_id TEXT,"
        "name TEXT,"
        "status TEXT,"
        "started_at DATETIME,"
        "completed_at DATETIME,"
        "duration_ms INTEGER,"
        "input_data JSON NOT NULL,"
        "output_data JSON,"
        "error TEXT,"
        "agent_execution_id TEXT,"
        "created_at DATETIME,"
        "FOREIGN KEY(run_id) REFERENCES workflow_runs(id))"
    ))


@pytest.fixture()
def engine():
    """Fresh on-disk SQLite engine (a few migration ops require the
    engine to be on disk so PRAGMA foreign_keys interacts with batch
    operations correctly). Cleaned up after the test."""
    import tempfile

    fd, path = tempfile.mkstemp(prefix="archon-mig-", suffix=".db")
    os.close(fd)
    eng = create_engine(f"sqlite:///{path}")
    try:
        yield eng
    finally:
        eng.dispose()
        try:
            os.remove(path)
        except OSError:
            pass


def test_upgrade_applies_cleanly_on_fresh_sqlite(engine) -> None:
    """0007 upgrade adds all expected columns + the events table."""
    mod = _load_migration_module()

    with engine.begin() as conn:
        _build_pre_migration_schema(conn)
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.upgrade()

    insp = inspect(engine)
    runs_cols = {c["name"] for c in insp.get_columns("workflow_runs")}
    expected_added = {
        "agent_id",
        "kind",
        "definition_snapshot",
        "definition_version",
        "queued_at",
        "claimed_at",
        "paused_at",
        "resumed_at",
        "cancel_requested_at",
        "lease_owner",
        "lease_expires_at",
        "attempt",
        "idempotency_key",
        "input_hash",
        "output_data",
        "metrics",
        "error_code",
    }
    missing = expected_added - runs_cols
    assert not missing, f"workflow_runs missing columns: {missing}"

    steps_cols = {c["name"] for c in insp.get_columns("workflow_run_steps")}
    expected_step_added = {
        "attempt",
        "retry_count",
        "idempotency_key",
        "checkpoint_thread_id",
        "input_hash",
        "output_artifact_id",
        "token_usage",
        "cost_usd",
        "worker_id",
        "error_code",
    }
    missing_step = expected_step_added - steps_cols
    assert not missing_step, f"workflow_run_steps missing: {missing_step}"

    # workflow_run_events table exists with all 12 columns.
    events_cols = {c["name"] for c in insp.get_columns("workflow_run_events")}
    expected_event_cols = {
        "id",
        "run_id",
        "sequence",
        "event_type",
        "payload",
        "tenant_id",
        "correlation_id",
        "span_id",
        "step_id",
        "prev_hash",
        "current_hash",
        "created_at",
    }
    assert events_cols >= expected_event_cols

    # Indexes exist.
    run_idx = {ix["name"] for ix in insp.get_indexes("workflow_runs")}
    assert "ix_workflow_runs_agent_id" in run_idx
    assert "ix_workflow_runs_kind" in run_idx
    assert "ix_workflow_runs_tenant_id_status" in run_idx
    assert "uq_workflow_runs_tenant_idem" in run_idx

    event_idx = {ix["name"] for ix in insp.get_indexes("workflow_run_events")}
    assert "ix_run_events_run_id_sequence" in event_idx
    assert "ix_run_events_tenant_id_created_at" in event_idx


def test_legacy_row_backfill(engine) -> None:
    """A legacy workflow_runs row inserted before upgrade gets the
    server-default kind="workflow" and a non-null definition_snapshot."""
    mod = _load_migration_module()

    workflow_id = uuid4().bytes
    run_id = uuid4().bytes
    now = datetime.utcnow().isoformat()

    with engine.begin() as conn:
        _build_pre_migration_schema(conn)
        # Seed a parent workflow + a legacy run.
        conn.execute(text(
            "INSERT INTO workflows (id, name, description, group_id, group_name,"
            " steps, graph_definition, is_active, created_at, updated_at)"
            " VALUES (:id, 't', '', '', '', '[]', '{}', 1, :now, :now)"
        ), {"id": workflow_id, "now": now})
        conn.execute(text(
            "INSERT INTO workflow_runs (id, workflow_id, status,"
            " trigger_type, triggered_by, created_at)"
            " VALUES (:id, :wf, 'pending', 'manual', '', :now)"
        ), {"id": run_id, "wf": workflow_id, "now": now})

        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.upgrade()

    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT kind, definition_snapshot FROM workflow_runs WHERE id = :id"
        ), {"id": run_id}).one()
        assert result[0] == "workflow"
        # SQLite returns JSON columns as TEXT; the server default we wrote
        # was the literal string '{"_legacy":true}'.
        assert "_legacy" in str(result[1])


def test_downgrade_drops_added_artifacts(engine) -> None:
    """downgrade() removes everything 0007 added in reverse order."""
    mod = _load_migration_module()

    with engine.begin() as conn:
        _build_pre_migration_schema(conn)
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.upgrade()

    # Sanity: workflow_run_events exists post-upgrade.
    insp = inspect(engine)
    assert "workflow_run_events" in insp.get_table_names()

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            mod.downgrade()

    # workflow_run_events table is gone.
    insp = inspect(engine)
    assert "workflow_run_events" not in insp.get_table_names()

    # All columns 0007 added to workflow_runs are removed.
    runs_cols = {c["name"] for c in insp.get_columns("workflow_runs")}
    must_be_gone = {
        "agent_id",
        "kind",
        "definition_snapshot",
        "definition_version",
        "queued_at",
        "claimed_at",
        "paused_at",
        "resumed_at",
        "cancel_requested_at",
        "lease_owner",
        "lease_expires_at",
        "attempt",
        "idempotency_key",
        "input_hash",
        "output_data",
        "metrics",
        "error_code",
    }
    leftover = must_be_gone & runs_cols
    assert not leftover, f"downgrade left columns behind: {leftover}"

    # Same for workflow_run_steps.
    steps_cols = {c["name"] for c in insp.get_columns("workflow_run_steps")}
    must_be_gone_steps = {
        "attempt",
        "retry_count",
        "idempotency_key",
        "checkpoint_thread_id",
        "input_hash",
        "output_artifact_id",
        "token_usage",
        "cost_usd",
        "worker_id",
        "error_code",
    }
    leftover_step = must_be_gone_steps & steps_cols
    assert not leftover_step, f"step downgrade left columns: {leftover_step}"

    # Idempotency partial index is gone.
    run_idx = {ix["name"] for ix in insp.get_indexes("workflow_runs")}
    assert "uq_workflow_runs_tenant_idem" not in run_idx
