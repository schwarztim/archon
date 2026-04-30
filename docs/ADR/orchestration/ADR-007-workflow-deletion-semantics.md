# ADR-007: Workflow Deletion and Mid-Run Mutation Semantics

- **Status:** ACCEPTED
- **Namespace:** orchestration
- **Date:** 2026-04-29
- **Supersedes:** none
- **Superseded by:** none

## Context

The current `WorkflowRun.workflow_id` is a non-nullable foreign key with
no `ondelete` clause specified
(`backend/app/models/workflow.py` line 51:
`workflow_id: UUID = Field(index=True, foreign_key="workflows.id")`).
SQLAlchemy default is `NO ACTION`, which means deleting a `Workflow`
fails if any `WorkflowRun` references it. In practice this leaves the
operator with three bad choices:

1. Refuse to delete the workflow (current behaviour) — orphan definitions
   accumulate.
2. Cascade-delete the runs — the audit trail is destroyed.
3. Manually re-point runs to a placeholder — error-prone and lossy.

In addition, `dispatch_run` reads the live `Workflow` row at execution
time (`run_dispatcher.py` lines 69–82). If a workflow definition is
mutated while runs are queued or in-flight, those runs will execute the
new definition without any record of the change.

ADR-001 introduced `definition_snapshot`. This ADR locks down what
happens around the workflow row when runs reference it.

## Decision

Run history is preserved across workflow deletion. The snapshot in
`workflow_runs.definition_snapshot` is the authoritative definition for
that run.

### Cascade behaviour

`WorkflowRun.workflow_id` is `ondelete="SET NULL"` (already set in
ADR-001's schema). Deleting a `Workflow` row:

- Sets `workflow_id` to `NULL` on every `WorkflowRun` that referenced it.
- Leaves `definition_snapshot`, `kind`, `status`, `input_data`, all
  events, and all step rows intact.
- Does NOT cascade to `workflow_run_events` or `workflow_run_steps`.
- Triggers a `run.workflow_deleted` audit-log entry per affected run
  (audit-log only — not a `WorkflowRunEvent`, because run state is
  unchanged; only the parent reference cleared).

`WorkflowSchedule.workflow_id` keeps its existing `unique=True`
constraint (`models/workflow.py` line 94). Deleting a workflow ALSO
deletes its schedule via `ondelete="CASCADE"` — schedules are useless
without their workflow.

### Mid-run definition mutation

When the engine executes a run, it executes `definition_snapshot`. The
live `workflows` row is read at most once: at run-creation time, when
the snapshot is captured.

A workflow mutated mid-run:

- Has no effect on in-flight runs. They continue executing the snapshot
  they captured.
- Affects only runs created AFTER the mutation.
- Is recorded as a regular workflow update in the audit log; in-flight
  runs are NOT notified (nothing for them to do).

Snapshot wins. There is no "live override" mechanism. Operators that
want a mutation to apply to in-flight runs must cancel and re-create
them.

### Replay reproducibility

`POST /executions/{id}/replay` (`routes/executions.py` lines 194–218)
copies the original `definition_snapshot` to the new run. This means a
replay of a run whose workflow was later deleted or modified still
executes the original snapshot. The replay path MUST NOT re-read the
`workflows` table.

### Workflow name reuse

When a workflow is deleted, its name becomes available again. A new
workflow may be created with the same `name` as a deleted one. The new
workflow has a fresh `id`. Runs of the deleted workflow remain anchored
to their snapshot (which preserves the original `name` and `id` inside
the snapshot JSON for audit).

This is a deliberate operator-facing behaviour: name reuse must not
imply identity. The UI and API SHOULD render snapshot-internal `name`
fields with a "(deleted)" suffix when `workflow_id IS NULL` for the
referencing run, so operators can distinguish historical from current
references.

## Consequences

### Positive

- Operators can freely delete obsolete workflows without losing run
  history. Audit and compliance retain full visibility.
- In-flight runs are deterministic — the snapshot is the contract, not
  the live row.
- Replay is bit-for-bit reproducible for the captured definition,
  regardless of subsequent edits.

### Negative

- A run with `workflow_id IS NULL` cannot be re-pointed at a different
  workflow. Operators who delete a workflow by mistake cannot trivially
  re-attach the runs — they must restore the workflow row with its
  original `id`. (Soft-delete via a flag is RECOMMENDED but out of scope
  for this ADR.)
- The "edit workflow, see effect on running runs" mental model that
  some operators may carry from other systems does NOT apply here. The
  UI MUST make this explicit.
- Storage cost: every run carries its full definition. For a workflow
  with thousands of runs this multiplies storage. This is a known cost
  paid for reproducibility; compression is permitted but the snapshot
  shape is not optional.

### Neutral

- `workflow_run_steps` already references `run_id`, not `workflow_id`,
  so its cascade behaviour is unaffected.
- The legacy `executions` table (per ADR-006) has no relationship to
  `workflows` and is unaffected.

## Implementation notes

### Foreign-key and constraint definitions

```python
class WorkflowRun(SQLModel, table=True):
    workflow_id: UUID | None = Field(
        default=None,
        index=True,
        foreign_key="workflows.id",
        sa_column_kwargs={"ondelete": "SET NULL"},
    )
    # See ADR-001 for the rest of the schema.

class WorkflowSchedule(SQLModel, table=True):
    workflow_id: UUID = Field(
        index=True,
        foreign_key="workflows.id",
        sa_column_kwargs={"ondelete": "CASCADE"},
        unique=True,
    )
```

### Audit-log emission on cascade

The cascade SET NULL is performed by the database. The application does
not see individual cascade events. To capture them in the audit log,
the deletion endpoint MUST:

1. Query affected runs:
   `SELECT id FROM workflow_runs WHERE workflow_id = :workflow_id`.
2. Emit one `AuditLog` entry per run with
   `action="run.workflow_deleted"`,
   `resource_type="workflow_run"`,
   `resource_id=<run_id>`,
   `details={"workflow_id": "<deleted_workflow_id>", "workflow_name": "<name>"}`.
3. Then issue the `DELETE FROM workflows WHERE id = :workflow_id`.

The order is important — querying after the delete returns nothing.

The audit emission is best-effort: a database failure between step 2
and step 3 leaves stale audit rows that point at a still-existing
workflow. This is acceptable and self-correcting on the next attempt.

### Snapshot integrity at creation

The capture of `definition_snapshot` MUST occur synchronously in the same
database transaction that inserts the `WorkflowRun` row. Capturing the
snapshot from a stale read of `workflows` outside the transaction
permits a write race where the run thinks it captured definition v1
but actually captured v2.

Concrete pattern (every run-creation site):

```python
async with session.begin():
    workflow = await session.get(Workflow, workflow_id, with_for_update=True)
    if workflow is None:
        raise NotFoundError(...)
    snapshot = build_snapshot_from_workflow(workflow)
    run = WorkflowRun(
        workflow_id=workflow.id,
        kind="workflow",
        definition_snapshot=snapshot,
        ...
    )
    session.add(run)
# transaction commits; SELECT FOR UPDATE released
```

For agent runs, the same pattern using `Agent`.

### UI rendering rule

When the API returns a run row with `workflow_id IS NULL`:

- Show `definition_snapshot.name + " (deleted)"` as the workflow name.
- Disable any "open workflow" link.
- Show the original `workflow_id` from `definition_snapshot.id` as a
  read-only field (so operators can correlate with backups or audit).

### Forbidden

- ON DELETE CASCADE on `workflow_runs.workflow_id` — destroys history.
- Re-reading the `workflows` table during dispatch — would defeat the
  snapshot.
- Reusing a deleted `Workflow.id` for a new workflow — UUIDs are
  globally unique and the database will refuse this anyway.

## See also

- ADR-001 — defines `workflow_id` as nullable and `definition_snapshot`
  as mandatory; this ADR is the policy that justifies that schema
- ADR-002 — `run.workflow_deleted` is an audit-log event, NOT a
  `WorkflowRunEvent`. Run-state events are reserved for the run's
  internal lifecycle
- ADR-006 — legacy `Execution` rows have no FK to `workflows`; deletion
  semantics in this ADR apply only to the unified `workflow_runs`
  table
