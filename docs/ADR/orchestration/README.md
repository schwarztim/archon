# Orchestration ADRs

This namespace holds binding architectural decisions for Archon's
**run orchestration layer** — the path from `POST /executions` (or
`POST /agents/{id}/execute` or a scheduler tick) through dispatch,
DAG traversal, fan-in, checkpointing, and audit.

These ADRs are **ACCEPTED**. Downstream implementation agents MUST read
the relevant ADRs before modifying any runtime file in the affected
modules. Decisions in this namespace constitute the contract for the
next implementation cycle.

## Why a separate namespace

The repository's pre-existing ADRs at `docs/adr/001`–`013` cover
unrelated topics (API response format, auth, tenancy, audit, secrets,
high-level orchestration engine choice). This namespace
(`docs/adr/orchestration/`) is dedicated to the unified-run model and
its supporting policies. Numbering restarts at 001 inside this folder;
references from outside the folder MUST use the
`orchestration/ADR-NNN` form to disambiguate.

## Index

| ADR | Title | Status | Decision (one line) |
|-----|-------|--------|---------------------|
| [ADR-001](ADR-001-agent-vs-workflow-execution.md) | Unified run model for agent and workflow execution | ACCEPTED | One `workflow_runs` table; `workflow_id` and `agent_id` both nullable, exactly one required; `definition_snapshot` JSON mandatory at run creation. |
| [ADR-002](ADR-002-event-ownership.md) | Run event ownership and hash-chained event log | ACCEPTED | New `workflow_run_events` table owned by WS1 Data Model squad; 15 enumerated event types; sha256 prev/current hash chain over canonical JSON. |
| [ADR-003](ADR-003-branch-fanin-semantics.md) | Branch selection and fan-in semantics owned by the engine | ACCEPTED | Executors emit hints (`{"_hint": {"kind": "branch|fanout", ...}}`); the engine — not the executors — decides downstream runnability for `condition`, `switch`, and `parallelNode` `all`/`any`/`n_of_m`. |
| [ADR-004](ADR-004-idempotency-contract.md) | Idempotency contract for run creation | ACCEPTED | `X-Idempotency-Key` header (or `idempotency_key` body field; header wins) scoped to `(tenant_id, key)`; partial unique index portable across SQLite and Postgres; 201 / 200 (replay) / 409 (conflict) response codes. |
| [ADR-005](ADR-005-production-durability-policy.md) | Production durability policy for the LangGraph checkpointer | ACCEPTED | In `production`/`staging`, failed Postgres checkpointer setup is FATAL — process exits non-zero; `MemorySaver` permitted only when `ARCHON_ENV` ∈ {`dev`, `test`}. |
| [ADR-006](ADR-006-execution-migration.md) | Execution table migration to WorkflowRun | ACCEPTED | Reads check `workflow_runs` first, fall back to legacy `executions`; `ExecutionFacade.get(id)` is the canonical lookup; deprecation runs N+0 → N+4 over four release cycles. |
| [ADR-007](ADR-007-workflow-deletion-semantics.md) | Workflow deletion and mid-run mutation semantics | ACCEPTED | `ondelete=SET NULL` on `workflow_runs.workflow_id`; snapshot wins for in-flight runs; deleted-workflow names are reusable but the snapshot still anchors history. |

## Read order

Implementation agents should read in numeric order. ADR-001 establishes
the schema baseline; ADR-002 through ADR-007 each depend on it.

## Cross-reference map

```
ADR-001  ◄── ADR-002 (events reference workflow_runs.id)
   ▲     ◄── ADR-003 (engine consumes definition_snapshot)
   │     ◄── ADR-004 (adds idempotency_key + input_hash columns)
   │     ◄── ADR-005 (durability per-run)
   │     ◄── ADR-006 (migration target table)
   └──── ADR-007 (justifies nullable workflow_id and snapshot mandate)

ADR-002  ◄── ADR-003 (skip/fanout events emitted by engine)
         ◄── ADR-005 (run.paused / run.resumed events)
         ◄── ADR-006 (legacy Execution rows do NOT emit events)
         ◄── ADR-007 (workflow_deleted is audit-log, NOT a run event)

ADR-006  ◄── ADR-007 (deletion semantics presuppose snapshot read-fallback)
```

## Source files referenced

These ADRs cite specific code locations. Implementation agents will need
to read these before editing:

- `backend/app/models/workflow.py` — `Workflow`, `WorkflowRun`, `WorkflowRunStep`, `WorkflowSchedule`
- `backend/app/models/__init__.py` — `Execution`, `Agent`, `User`, `AuditLog`
- `backend/app/services/run_dispatcher.py` — `dispatch_run`
- `backend/app/services/execution_service.py` — legacy execution write paths
- `backend/app/services/node_executors/parallel.py` — fanout hint shape
- `backend/app/routes/executions.py` — REST surface for executions
- `backend/app/routes/agents.py` — REST surface for agent execution
- `backend/app/worker.py` — drain loop, scheduled-workflow tick
- `backend/app/langgraph/checkpointer.py` — checkpointer factory

## Inconsistencies discovered while authoring

The following deviations from the plan's idealised model were observed
in the source. They are flagged here, not silently overridden:

1. **`worker.py` line 506 docstring is wrong** about the checkpointer
   default. The comment claims "set `LANGGRAPH_CHECKPOINTING=memory`
   (default) for in-process state". The actual code default in
   `checkpointer.py` line 99 is `postgres`. ADR-005 mandates the
   docstring be corrected to reflect the postgres-default policy and
   the new fatal behaviour in durable environments.

2. **Execution.metrics is a write-once JSON blob** in
   `execution_service.py` lines 238–242, while the unified
   `WorkflowRun` does not have a `metrics` column at all — its
   per-step metrics live in `workflow_run_steps`. ADR-006's
   `_project_run_to_legacy_shape` synthesises the legacy `metrics` shape
   from a sum across steps, which is approximate during the transition.
   Operators must not cross-compare metrics across the two sources.

3. **No `updated_at` on `WorkflowRun`** (compare `models/workflow.py`
   lines 45–61 to `models/__init__.py` lines 77–99 where `Execution`
   has both). ADR-006 instructs the projection to compute `updated_at`
   on the fly from the latest of `created_at`, `started_at`,
   `completed_at`. If a true `updated_at` is needed in the future it
   would require its own ADR addendum.

4. **`parallelNode` already emits hint shape** but uses the legacy
   `_fanout_hint: True` flag (`node_executors/parallel.py` line 36)
   rather than the canonical `_hint.kind = "fanout"` envelope. ADR-003
   defines the canonical shape; the implementation will rename the
   field. The legacy flag should be accepted by the engine for the
   transition window only (one release cycle), then removed.

5. **Two parallel dispatch paths** —
   `run_dispatcher.dispatch_run` (lines 31–116) and
   `worker._dispatch_already_running` (lines 424–495) — duplicate
   nearly the entire body of run-state mutation logic. ADR-001 and
   ADR-002 require both to be modified consistently. A future
   refactor should consolidate them; that consolidation is out of
   scope for this ADR set but is a known follow-up.

6. **`Workflow.tenant_id` is `UUID | None`** but `Agent.tenant_id` is
   `str | None` (`models/__init__.py` line 47). The unified
   `workflow_runs` row already uses `UUID | None` for `tenant_id`, so
   agent runs will need to coerce. This is an Agent-side type bug
   pre-dating this ADR set; flagged for a separate fix, not addressed
   here.

7. **`naive UTC timestamps`** are used everywhere
   (`_utcnow()` in `models/workflow.py` line 15 and
   `models/__init__.py` line 15). The audit log and event hash
   computation in ADR-002 assume timestamps are deterministic; the
   canonical-JSON serialisation will render them as ISO-8601 without
   timezone. This is consistent across the schema but will surface as
   a UX issue in clients that assume UTC suffix. Out of scope.

## Status governance

These ADRs are ACCEPTED for the next implementation cycle. They become
binding the moment this README is committed. Modifying any ADR in this
folder requires a new ADR with `Supersedes: orchestration/ADR-NNN`.
