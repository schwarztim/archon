# ADR-001: Unified Run Model for Agent and Workflow Execution

- **Status:** ACCEPTED
- **Namespace:** orchestration
- **Date:** 2026-04-29
- **Supersedes:** none
- **Superseded by:** none

## Context

Archon currently has two parallel execution surfaces that store run state in
incompatible tables:

- `Execution` — defined in `backend/app/models/__init__.py` lines 77–99.
  Bound to a single agent via `agent_id: UUID = Field(foreign_key="agents.id")`.
  Stores `steps` and `metrics` as JSON blobs on the row itself. Has no link to
  any workflow definition.
- `WorkflowRun` — defined in `backend/app/models/workflow.py` lines 45–61.
  Bound to a workflow via `workflow_id: UUID = Field(index=True,
  foreign_key="workflows.id")` (currently **non-nullable**). No `agent_id`
  column. No definition snapshot — the engine reads the live `Workflow` row
  at run time (`backend/app/services/run_dispatcher.py` lines 69–82).

Pain points observed in code:

1. **Two dispatch paths.** `routes/executions.py` (lines 81–142) creates and
   dispatches `Execution` records via `execution_service.create_execution` +
   `dispatch_run`. `routes/agents.py` (lines 133–156) does the same for the
   `/agents/{agent_id}/execute` endpoint. Meanwhile `worker.py` lines 323–404
   (`_drain_pending_runs`) drains `workflow_runs` only.
2. **Run dispatcher is workflow-only.** `run_dispatcher.dispatch_run`
   (`backend/app/services/run_dispatcher.py`) loads the run as a
   `WorkflowRun` and crashes for any agent execution that wasn't routed
   through a workflow.
3. **Live-definition race.** `dispatch_run` reads `Workflow` at run time. If
   the definition is mutated after the run is queued, the run executes the
   new definition. There is no snapshot.
4. **Schema cohesion.** Two run tables means two replay paths, two query
   surfaces, two UI projections, and two audit-log shapes
   (`ExecutionService` lines 116–122 vs. `dispatch_run` raw status flips).

## Decision

There is **one run table** going forward: `workflow_runs`. Both agent
executions and workflow executions write rows to this table. The schema
admits either an agent or a workflow but not both.

The following columns of `WorkflowRun` change. **All other columns remain
unchanged.**

| Column | Before | After | Notes |
|---|---|---|---|
| `workflow_id` | `UUID` (NOT NULL, FK `workflows.id`) | `UUID \| None` (NULL allowed, FK retained, `ondelete="SET NULL"`) | See ADR-007 |
| `agent_id` | (does not exist) | `UUID \| None` (FK `agents.id`, `ondelete="SET NULL"`) | New |
| `definition_snapshot` | (does not exist) | `dict[str, Any]` (JSON, NOT NULL) | New, mandatory |
| `kind` | (does not exist) | `str` (NOT NULL, default `"workflow"`) | Discriminator, values: `workflow`, `agent` |

**Constraint:** exactly one of `workflow_id` or `agent_id` must be non-null
on every row, enforced by a CHECK constraint:

```sql
CHECK ((workflow_id IS NULL) <> (agent_id IS NULL))
```

The CHECK uses `<>` (XOR) so that exactly one is null. Both-null and
both-non-null rows are rejected by the database.

**Snapshot rule:** `definition_snapshot` is captured at run-creation time
and is immutable for the lifetime of the row. The engine MUST execute the
snapshot, never the live `workflows` or `agents` row.

### SQLModel changes (concrete)

`backend/app/models/workflow.py` — `WorkflowRun` becomes:

```python
class WorkflowRun(SQLModel, table=True):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "(workflow_id IS NULL) <> (agent_id IS NULL)",
            name="ck_workflow_runs_exactly_one_target",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_id: UUID | None = Field(
        default=None,
        index=True,
        foreign_key="workflows.id",
        sa_column_kwargs={"ondelete": "SET NULL"},
    )
    agent_id: UUID | None = Field(
        default=None,
        index=True,
        foreign_key="agents.id",
        sa_column_kwargs={"ondelete": "SET NULL"},
    )
    kind: str = Field(default="workflow", index=True)  # "workflow" | "agent"
    definition_snapshot: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False)
    )
    tenant_id: UUID | None = Field(default=None, index=True)
    status: str = Field(default="pending", index=True)
    trigger_type: str = Field(default="manual")
    input_data: dict | None = Field(default=None, sa_column=Column(JSON))
    triggered_by: str = Field(default="")
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None)
    error: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    created_at: datetime = Field(default_factory=_utcnow)
    # See ADR-004 for idempotency_key column
```

### Snapshot shape

`definition_snapshot` is a JSON object with this shape (engine-agnostic):

```json
{
  "kind": "workflow|agent",
  "id": "<source UUID>",
  "name": "<source name>",
  "version": "<optional version label>",
  "steps": [...],
  "graph_definition": {...},
  "captured_at": "2026-04-29T17:00:00Z"
}
```

For `kind="workflow"` the snapshot is built from the `Workflow` row's
`steps` and `graph_definition` columns (see `models/workflow.py` lines 31–36).

For `kind="agent"` the snapshot is built from the `Agent` row's `steps`,
`graph_definition`, `definition`, `llm_config`, and `tools` columns
(see `models/__init__.py` lines 44–71).

### Run-dispatcher contract

`run_dispatcher.dispatch_run(run_id)` MUST:

1. Load the row, read `kind`.
2. Execute strictly from `definition_snapshot`, never from the live source row.
3. Reject rows where the CHECK constraint would have prevented insert
   (defensive — should never happen in a healthy database).

The `workflow_dict` constructed in `run_dispatcher.py` lines 76–82 changes
to read `run.definition_snapshot` rather than re-loading the `Workflow` row.

## Consequences

### Positive

- One canonical run table. One replay path. One UI projection. One audit
  shape. Removes the entire `Execution` write path long-term (see ADR-006
  for migration).
- Definition snapshot eliminates the live-definition race. Replays produce
  the exact same execution graph as the original run.
- Workflow deletion no longer cascades into history loss (see ADR-007).

### Negative

- Existing `Execution` rows must be readable for the deprecation period
  (see ADR-006).
- Migration must add the new columns, backfill `definition_snapshot` for
  in-flight runs, and only then make `workflow_id` nullable. A partial
  rollout that flips nullability before the snapshot column is populated
  will fail the CHECK constraint.
- Every existing call site that constructs a `WorkflowRun(...)` literal
  must now also pass `definition_snapshot` and one of `(workflow_id,
  agent_id)`. Concrete impact:
  - `worker.py` line 236: `_check_scheduled_workflows` constructs a
    `WorkflowRun` literal — must read the workflow at trigger time and
    embed a snapshot.

### Neutral

- Tenant scoping, RBAC, and audit-log emission are unchanged.
- The `WorkflowRunStep` table (`models/workflow.py` lines 64–85) is
  unchanged — it already references `run_id`, not workflow_id.

## Implementation notes

### Alembic migration sequence (mandatory order)

1. `ALTER TABLE workflow_runs ADD COLUMN agent_id UUID NULL REFERENCES agents(id) ON DELETE SET NULL;`
2. `ALTER TABLE workflow_runs ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'workflow';`
3. `ALTER TABLE workflow_runs ADD COLUMN definition_snapshot JSON NOT NULL DEFAULT '{}'::json;` (Postgres) / `JSON NOT NULL DEFAULT '{}'` (SQLite via `batch_op`).
4. **Backfill** `definition_snapshot` for all existing rows by joining to
   `workflows` and serialising `{steps, graph_definition, id, name}`.
5. `ALTER TABLE workflow_runs ALTER COLUMN workflow_id DROP NOT NULL;`
6. `ALTER TABLE workflow_runs ADD CONSTRAINT ck_workflow_runs_exactly_one_target CHECK ((workflow_id IS NULL) <> (agent_id IS NULL));`
7. Drop the `DEFAULT '{}'` from `definition_snapshot` after backfill —
   future inserts must supply it explicitly.

### Forbidden states

- `workflow_id IS NULL AND agent_id IS NULL` — rejected by CHECK.
- `workflow_id IS NOT NULL AND agent_id IS NOT NULL` — rejected by CHECK.
- `definition_snapshot IS NULL` or `'{}'::json` after backfill — invalid.

### Indexes

- Existing index on `workflow_id` is retained.
- Add index on `agent_id`.
- `kind` is indexed because UI projections will commonly filter by it.

## See also

- ADR-002 — event ownership (every state transition on a `WorkflowRun`
  emits a `WorkflowRunEvent`)
- ADR-003 — branch and fan-in semantics (consumes the snapshot)
- ADR-004 — idempotency contract (adds one more column to this table)
- ADR-005 — production durability policy (engine reading the snapshot must
  be checkpointed)
- ADR-006 — execution migration (legacy `Execution` table read-path)
- ADR-007 — workflow deletion semantics (justifies `ondelete="SET NULL"`)
