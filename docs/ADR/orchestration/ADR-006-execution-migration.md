# ADR-006: Execution Table Migration to WorkflowRun

- **Status:** ACCEPTED
- **Namespace:** orchestration
- **Date:** 2026-04-29
- **Supersedes:** none
- **Superseded by:** none

## Context

ADR-001 makes `workflow_runs` the unified run table. The legacy
`executions` table (`backend/app/models/__init__.py` lines 77–99) holds
agent-execution history written by:

- `ExecutionService.start_execution` —
  `backend/app/services/execution_service.py` lines 65–124
- `ExecutionService.run_execution` — lines 128–274
- `ExecutionService.complete_execution` — lines 474–503
- `ExecutionService.fail_execution` — lines 505–534
- `create_execution` (legacy module-level) — lines 594–600

These rows are referenced by:

- `routes/executions.py` lines 144–256 — list, get, replay, cancel,
  delete endpoints
- `routes/agents.py` lines 133–156 — `POST /agents/{id}/execute` returns
  the execution_id
- The frontend execution detail panel that joins on `agent_id` to enrich
  with `agent_name`

We cannot drop the table. Existing audit-log entries reference
`resource_type="execution"`, `resource_id=<execution_id>` (see
`ExecutionService._audit` line 36), and customers may have external
references to execution UUIDs via API responses or webhooks.

We also cannot keep two write paths indefinitely. The decision below
is the migration shape.

## Decision

Existing `Execution` rows remain readable. New writes go through
`workflow_runs` only.

- Read path: `ExecutionFacade.get(id)` checks `workflow_runs` first; if
  no row matches it falls back to `executions`.
- Write path: closed against `executions`. The legacy
  `create_execution`, `start_execution`, `run_execution`,
  `complete_execution`, `fail_execution`, `cancel_execution` functions
  raise `DeprecationWarning` and forward to the unified path.
- API surface: every endpoint that returns an `Execution` row projects
  it through a stable shape so a `WorkflowRun` row and a legacy
  `Execution` row are indistinguishable to clients during the transition.

### Lookup order (mandatory)

```python
async def get_run_or_legacy_execution(
    session: AsyncSession,
    execution_id: UUID,
    *,
    tenant_id: UUID | None = None,
) -> dict[str, Any] | None:
    # 1. workflow_runs (the canonical table per ADR-001)
    run = await session.get(WorkflowRun, execution_id)
    if run is not None:
        if tenant_id is not None and run.tenant_id != tenant_id:
            return None
        return _project_run_to_legacy_shape(run)

    # 2. executions (legacy)
    execution = await session.get(Execution, execution_id)
    if execution is None:
        return None
    if tenant_id is not None:
        # Tenant scope check via agent->user->tenant join
        if not await _execution_belongs_to_tenant(session, execution, tenant_id):
            return None
    return _project_legacy_to_legacy_shape(execution)
```

The order is fixed: `workflow_runs` first, `executions` second. Any other
order is a violation of this ADR. UUID space collision is impossible (UUID4
collision probability is negligible) so a single ID will resolve to at
most one row across both tables.

### Response projection mapping

`WorkflowRun` is projected to the legacy `Execution` JSON shape using
the table below. `_project_run_to_legacy_shape` MUST output exactly this
shape so that clients calling `GET /executions/{id}` see no diff.

| Legacy `Execution` field | Source on `WorkflowRun` | Notes |
|---|---|---|
| `id` | `run.id` | Direct |
| `agent_id` | `run.agent_id` | NULL when `run.kind = "workflow"` — emit `null` |
| `status` | `run.status` | Same allowed set: `pending`, `queued`, `running`, `completed`, `failed`, `cancelled` |
| `input_data` | `run.input_data` | Direct |
| `output_data` | `run.definition_snapshot.get("last_output")` or aggregation from `WorkflowRunStep` rows | Engine writes a roll-up to `definition_snapshot` on completion (informative, not normative for this ADR) |
| `error` | `run.error` | Direct |
| `steps` | Joined from `workflow_run_steps` and rendered as a list of dicts | Field-by-field same shape as legacy `steps` JSON |
| `metrics` | Computed: `{total_duration_ms: run.duration_ms, total_tokens: <sum>, total_cost: <sum>}` | Tokens / cost summed from `workflow_run_steps` (or 0) |
| `started_at` | `run.started_at` | Direct |
| `completed_at` | `run.completed_at` | Direct |
| `created_at` | `run.created_at` | Direct |
| `updated_at` | Latest of `run.completed_at`, `run.started_at`, `run.created_at` | Compute on the fly — `WorkflowRun` has no `updated_at` column |

`_project_legacy_to_legacy_shape` is the identity function — pass through.

### Endpoint behaviour

- `GET /executions/{id}` — uses `get_run_or_legacy_execution`. Same
  response shape regardless of source.
- `GET /executions` (list) — UNION of `workflow_runs` (where `kind` in
  `{"workflow", "agent"}`) and `executions`, ordered by `created_at` DESC.
  Pagination remains correct because both tables are indexed on
  `created_at`.
- `POST /executions` and `POST /agents/{id}/execute` — write only to
  `workflow_runs`. Behaviour change: the `id` returned is a
  `WorkflowRun.id`, not an `Execution.id`. Clients that already received
  a legacy `Execution.id` continue to read it via the fallback path.
- `POST /executions/{id}/replay` — reads original via the unified lookup.
  Writes the new run to `workflow_runs`.
- `POST /executions/{id}/cancel` — operates on whichever table holds the
  row. For `workflow_runs` rows, also emits `run.cancelled` event per
  ADR-002. For `executions` rows, it remains a row mutation only — the
  event log does NOT backfill legacy rows.
- `DELETE /executions/{id}` — operates on whichever table holds the row.

### Deprecation timeline

| Stage | Trigger | Action |
|---|---|---|
| **N+0** | This ADR ACCEPTED | Read fallback live. New writes route to `workflow_runs`. Legacy write functions emit `DeprecationWarning`. |
| **N+1** | One full release cycle | Frontend list endpoint reads exclusively from `workflow_runs` (no UNION). Legacy read fallback retained. |
| **N+2** | Two full release cycles | Legacy `Execution` write functions become no-op stubs that raise `RuntimeError` if called. |
| **N+3** | Three full release cycles | Read-only migration: a one-time job copies `executions` rows into `workflow_runs` with `kind="agent"` and a synthesised `definition_snapshot`. Audit-log `resource_type` is updated to `"workflow_run"`. |
| **N+4** | After N+3 verified clean | `executions` table dropped via Alembic migration. |

A release cycle is one calendar quarter unless the operator overrides.
The agent implementing this MUST NOT skip stages.

## Consequences

### Positive

- Single canonical run path going forward without breaking external
  references to old execution UUIDs.
- Frontend can adopt the new shape without a flag day — projection is
  identical for both sources.
- Legacy table removal is bounded and predictable.

### Negative

- The `_project_run_to_legacy_shape` aggregation requires a join from
  `workflow_runs` to `workflow_run_steps`. List endpoints that return
  many rows will incur N+1 queries unless eager-loaded. The
  implementation MUST use `selectinload` or equivalent to avoid this.
- `metrics` field projection is approximate during the transition —
  legacy `Execution.metrics` is a JSON blob written verbatim, while
  `WorkflowRun` derives its metrics by summation. Operators should not
  cross-compare metrics across the two sources during the transition.
- The legacy `cancel_execution` endpoint cannot emit a `run.cancelled`
  event for legacy rows, because there is no event log row to chain
  from (per ADR-002).

### Neutral

- The `executions` table is unchanged at the schema level until N+4.
  No risky in-place migrations during the transition.
- Existing audit-log rows are unchanged; they retain
  `resource_type="execution"` until N+3.

## Implementation notes

### New module: `backend/app/services/execution_facade.py`

```python
class ExecutionFacade:
    @staticmethod
    async def get(
        session: AsyncSession, execution_id: UUID, *, tenant_id: UUID | None = None
    ) -> dict[str, Any] | None:
        """Look up a run by ID. workflow_runs first, executions fallback."""
        ...

    @staticmethod
    async def list(
        session: AsyncSession, *, tenant_id: UUID | None = None,
        agent_id: UUID | None = None, status: str | None = None,
        limit: int = 20, offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """UNION query over workflow_runs and executions during the transition."""
        ...

    @staticmethod
    async def cancel(
        session: AsyncSession, execution_id: UUID, *, tenant_id: UUID, user
    ) -> dict[str, Any] | None:
        """Cancel a run on whichever table holds it."""
        ...
```

This module is the single entrypoint for the API routes during the
transition. Routes call `ExecutionFacade.get(...)` instead of
`execution_service.get_execution(...)`.

### Test invariants (must hold at every stage)

1. A POST that creates a run returns an ID that resolves through the
   facade.
2. An ID that existed before this ADR continues to resolve through the
   facade for the entire transition.
3. The legacy and unified projection shapes are byte-identical for the
   keys listed in the projection table.
4. `DELETE` on a legacy row removes it; subsequent `GET` returns 404.
5. `DELETE` on a unified row removes it; the event log retains the
   `run.cancelled` / final event chain for forensic queries.

### Forbidden

- Writing to both tables for the same run (no dual-write, no shadow
  copies).
- Returning a 404 for an ID that exists in `executions` while the
  fallback is active.
- Skipping a deprecation stage. Each stage MUST be released and verified
  before the next.

## See also

- ADR-001 — defines the unified `workflow_runs` schema this ADR migrates
  to
- ADR-002 — events are emitted only for `workflow_runs` rows; legacy
  `Execution` rows do not produce events
- ADR-004 — idempotency keys apply to `workflow_runs` only; legacy
  `executions` insertions never had keys
- ADR-007 — workflow deletion preserves run history; this is a
  precondition for the read-fallback path to remain useful after a
  workflow is removed
