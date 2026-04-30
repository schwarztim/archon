# ADR-002: Run Event Ownership and Hash-Chained Event Log

- **Status:** ACCEPTED
- **Namespace:** orchestration
- **Date:** 2026-04-29
- **Owner:** WS1 — Data Model squad
- **Supersedes:** none
- **Superseded by:** none

## Context

Run state is currently mutated in place by:

- `run_dispatcher.dispatch_run` — `backend/app/services/run_dispatcher.py`
  lines 60–116. Sets `run.status = "running" | "completed" | "failed" |
  "cancelled"` directly on the `WorkflowRun` row and commits.
- `worker._dispatch_already_running` — `backend/app/worker.py` lines 424–495.
  Same pattern, parallel implementation.
- `ExecutionService.start_execution` / `run_execution` /
  `complete_execution` / `fail_execution` /  `cancel_execution` —
  `backend/app/services/execution_service.py`. Mutates `Execution.status`
  in place.
- `_check_scheduled_workflows` — `backend/app/worker.py` lines 190–283.
  Inserts a `WorkflowRun` directly with `status="pending"`.

Every one of these write paths emits **only the final state** to the row.
There is no append-only log, no per-step event ordering, no tamper
evidence. The `WorkflowRunStep` table records per-step outcomes but has no
sequence number across the run, no causal chain, and is itself mutable
(`session.add(step); session.commit()`).

For audit, replay, debugging, and the streaming UI we need an immutable,
ordered, hash-chained event log. Multiple modules currently want to emit
events; without a single owner the schema will fork.

## Decision

A new table `workflow_run_events` is introduced. It is owned by **WS1, the
Data Model squad**. No other squad may extend, alter, or fork the schema.
Adding new event types is permitted (see "Adding new event types" below);
adding columns or indexes requires a Data Model squad change.

All run-state transitions on `workflow_runs` and `workflow_run_steps` MUST
emit one event per transition. The row mutation and the event insert MUST
happen in the same database transaction. If the event insert fails, the
state mutation MUST roll back.

### Schema

```python
class WorkflowRunEvent(SQLModel, table=True):
    __tablename__ = "workflow_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),
        Index("ix_run_events_run_id_sequence", "run_id", "sequence"),
        Index("ix_run_events_tenant_id", "tenant_id"),
        Index("ix_run_events_correlation_id", "correlation_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(index=True, foreign_key="workflow_runs.id")
    sequence: int = Field()  # monotonic per run, starts at 0
    event_type: str = Field()  # see enumeration below
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    tenant_id: UUID | None = Field(default=None, index=True)
    correlation_id: str | None = Field(default=None, index=True)
    span_id: str | None = Field(default=None)
    step_id: str | None = Field(default=None)  # nullable; only step.* events set this
    prev_hash: str | None = Field(default=None)  # NULL only for sequence=0
    current_hash: str = Field()  # 64-char hex (sha256)
    created_at: datetime = Field(default_factory=_utcnow)
```

### Enumerated `event_type` values (exhaustive)

Run-level (15 total):

- `run.created` — row inserted, sequence=0, snapshot present
- `run.queued` — visible to dispatcher (status flips to `queued`)
- `run.claimed` — worker won the optimistic-lock race (`worker.py`
  lines 369–384)
- `run.started` — execution begins (status flips to `running`)
- `run.completed` — terminal success
- `run.failed` — terminal failure
- `run.cancelled` — caller or system cancelled
- `run.paused` — checkpointer suspended the run (see ADR-005)
- `run.resumed` — checkpointer resumed the run

Step-level (6 total):

- `step.started`
- `step.completed`
- `step.failed`
- `step.skipped`
- `step.retry`
- `step.paused`

These 15 are the **complete** allowed set. New types require a Data Model
squad ADR amendment (this file). Unknown types MUST be rejected at insert.

### Hash chain

Each event carries:

- `prev_hash` — `current_hash` of the prior event for the same `run_id`,
  ordered by `sequence`. NULL when `sequence = 0`.
- `current_hash` — `sha256(prev_hash_bytes || canonical_json(payload_with_envelope))`
  rendered as lowercase hex.

The hashed envelope is:

```json
{
  "run_id": "<uuid>",
  "sequence": <int>,
  "event_type": "<string>",
  "step_id": "<string|null>",
  "tenant_id": "<uuid|null>",
  "correlation_id": "<string|null>",
  "span_id": "<string|null>",
  "payload": <user payload object>
}
```

`canonical_json` rules (mandatory, no exceptions):

- UTF-8 bytes
- Keys sorted lexicographically at every depth
- No insignificant whitespace (`json.dumps(obj, sort_keys=True,
  separators=(",", ":"), ensure_ascii=False)`)
- `null`, `true`, `false` lowercase
- Numbers: integers as integers, floats with no trailing zeros
- Nested objects/arrays follow the same rules recursively

#### Pseudocode

```python
def compute_event_hash(
    prev_hash: str | None,
    run_id: UUID,
    sequence: int,
    event_type: str,
    payload: dict,
    *,
    step_id: str | None,
    tenant_id: UUID | None,
    correlation_id: str | None,
    span_id: str | None,
) -> str:
    envelope = {
        "run_id": str(run_id),
        "sequence": sequence,
        "event_type": event_type,
        "step_id": step_id,
        "tenant_id": str(tenant_id) if tenant_id else None,
        "correlation_id": correlation_id,
        "span_id": span_id,
        "payload": payload,
    }
    body = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    prev = b"" if prev_hash is None else bytes.fromhex(prev_hash)
    return hashlib.sha256(prev + body).hexdigest()
```

### Sequence assignment

Inside the transaction that inserts the event:

```sql
SELECT COALESCE(MAX(sequence) + 1, 0)
FROM workflow_run_events
WHERE run_id = :run_id
FOR UPDATE;
```

The `(run_id, sequence)` unique constraint serialises concurrent inserters.
If two transactions race, the loser sees a unique-violation and must
retry by re-reading MAX(sequence). This is acceptable because the dispatcher
is the only writer for run-level events and per-step writers are
single-step-per-thread.

## Consequences

### Positive

- A single ordered, immutable, tamper-evident log per run.
- Replays can verify the chain: any divergence in `current_hash` means
  the payload or sequence was altered.
- UI streaming consumes a single source — events ordered by `(run_id,
  sequence)` is the canonical timeline.
- Step-level events carry the `step_id` natively; no need to join
  `workflow_run_steps` for ordering.

### Negative

- Every state-mutation site listed in the Context section must be modified
  to emit events transactionally. Failure to do so will leave runs in
  inconsistent visible state with no event trail.
- Hash computation must be deterministic across Python versions and
  systems; the canonical_json rules are non-negotiable.
- Schema is owned by WS1; other squads cannot add columns. New event
  types are added by extending the enumeration in this ADR.

### Neutral

- The `WorkflowRunStep` table is retained for current step row state, but
  per-step events also live in `workflow_run_events` with `step_id`
  populated. The two are not redundant — `WorkflowRunStep` is the current
  state, `workflow_run_events` is the history.
- OpenTelemetry `span_id` is captured opportunistically when present
  (`routes/executions.py` already uses `_tracer`).

## Implementation notes

### Required transactional pattern (every emitter)

```python
async def emit_event(
    session: AsyncSession,
    run_id: UUID,
    event_type: str,
    payload: dict,
    *,
    step_id: str | None = None,
    tenant_id: UUID | None = None,
    correlation_id: str | None = None,
    span_id: str | None = None,
) -> WorkflowRunEvent:
    # 1. Acquire row-level lock on workflow_runs.id to serialise sequence
    #    assignment for this run.
    # 2. SELECT MAX(sequence) FOR UPDATE.
    # 3. Compute prev_hash from the prior event (or None at sequence=0).
    # 4. Compute current_hash via the canonical envelope.
    # 5. INSERT the event.
    # 6. Caller commits the surrounding transaction (which also commits
    #    the run-state mutation that triggered the event).
```

The function lives in `backend/app/services/run_events.py` (new module).
Every state-mutation site MUST call it. Direct `session.add(WorkflowRun(...))`
without a corresponding event is a parity violation.

### Event payload shapes (informative, not normative)

Run-level payloads SHOULD include:

- `run.created` — `{"workflow_id" | "agent_id", "input_data", "trigger_type", "triggered_by"}`
- `run.completed` — `{"duration_ms", "metrics": {...}}`
- `run.failed` — `{"duration_ms", "error": "<truncated to 500 chars>"}`

Step-level payloads SHOULD include:

- `step.started` — `{"step_id", "name", "input_data"}`
- `step.completed` — `{"step_id", "output_data", "duration_ms"}`
- `step.failed` — `{"step_id", "error", "duration_ms"}`

These shapes are not enforced by the database (payload is JSON), but
consumers will assume them.

### Index rationale

- `(run_id, sequence)` UNIQUE — chain integrity + ordered queries.
- `(tenant_id)` — multi-tenant isolation queries.
- `(correlation_id)` — cross-run tracing (e.g. trigger -> child run).

### Adding new event types

A new event type is added by:

1. Amending the enumeration in this file.
2. Updating the validator in `backend/app/services/run_events.py`.
3. Updating any consumer (UI, audit exporter) that whitelists by type.

Without this ADR amendment, the validator MUST reject unknown types.

## See also

- ADR-001 — establishes `workflow_runs` as the unified run table that
  events reference
- ADR-003 — branch hints emit events with `step.started` / `step.completed`
  payloads that the engine reads
- ADR-005 — paused / resumed event types are produced by the LangGraph
  checkpointer
- ADR-006 — events from legacy `Execution` rows are NOT backfilled; only
  new `WorkflowRun` rows produce events
