# Archon — WorkflowRun State Machine

**Authority:** [`backend/app/services/run_dispatcher.py`](../backend/app/services/run_dispatcher.py), [`backend/app/services/run_lifecycle.py`](../backend/app/services/run_lifecycle.py), [`backend/app/models/workflow.py`](../backend/app/models/workflow.py).
**Governing ADRs:** [ADR-001](adr/orchestration/ADR-001-agent-vs-workflow-execution.md) (run model), [ADR-002](adr/orchestration/ADR-002-event-ownership.md) (event ownership), [ADR-004](adr/orchestration/ADR-004-idempotency-contract.md) (idempotency), [ADR-005](adr/orchestration/ADR-005-production-durability-policy.md) (durability), [ADR-007](adr/orchestration/ADR-007-workflow-deletion-semantics.md) (deletion).

> The dispatcher is the **only** mutator of `WorkflowRun.status`. Executors return `NodeResult`; the dispatcher decides terminal status. This is a structural invariant — no other code path is permitted to write `workflow_runs.status`.

## 1. Status enum

The valid values for `WorkflowRun.status`:

| Status | Persisted columns set | Meaning |
|--------|------------------------|---------|
| `pending` | `queued_at` | Created by `ExecutionFacade.create_run()`. Waiting for a worker to claim. |
| `queued` | `queued_at` | Transient — emitted as `run.queued` event but rarely persisted on the row (status moves directly from `pending` to `claimed` once a worker picks it up). |
| `claimed` | `claimed_at`, `lease_owner`, `lease_expires_at` | A worker has obtained the optimistic lock. Dispatcher is about to begin executing the first step. |
| `running` | `started_at` | First step has begun. The dispatcher is iterating through the graph. |
| `paused` | `paused_at` | An executor returned `paused` (e.g. `humanApprovalNode`) or a signal arrived. The run is durably parked; the lease is released. |
| `completed` | `completed_at`, `output_data`, `metrics`, `duration_ms` | All terminal steps finished successfully. Final event `run.completed` written. |
| `failed` | `completed_at`, `error_code`, `error`, `duration_ms` | A non-retriable step error or a `stub_blocked_in_production` rejection occurred. Final event `run.failed` written. |
| `cancelled` | `cancel_requested_at`, `completed_at` | An operator called `POST /api/v1/runs/{id}/cancel`. Dispatcher checks `cancel_requested_at` before each step and exits cleanly. |

## 2. Transitions diagram (canonical)

```
                            ┌─────────────────┐
                            │     pending     │  ← ExecutionFacade.create_run()
                            └────────┬────────┘
                                     │ worker.drain_loop picks it up
                                     │ run_lifecycle.claim_run() succeeds
                                     ▼
                            ┌─────────────────┐
                            │     claimed     │
                            └────────┬────────┘
                                     │ dispatcher begins first step
                                     ▼
                            ┌─────────────────┐
                  ┌────────▶│     running     │◀─────────┐
                  │         └─┬───┬───┬─────┬─┘          │
                  │           │   │   │     │            │
                  │     ┌─────┘   │   │     │            │
                  │     │ all     │   │ pause            │ resume
                  │     │ steps   │   │ requested        │ (signal /
                  │     │ done    │   │                  │ approval grant)
                  │     │         │   │                  │
                  │     ▼         │   ▼                  │
                  │ ┌────────┐    │ ┌────────┐           │
                  │ │complete│    │ │ paused │───────────┘
                  │ │   d    │    │ └────────┘
                  │ └────────┘    │
                  │     │         │ cancel_requested_at set
                  │ retry          ▼
                  │ exhausted   ┌──────────┐
                  │             │cancelled │
                  │             └──────────┘
                  │     │
                  │     ▼
                  │ ┌────────┐
                  │ │ failed │
                  │ └────────┘
                  │
                  │ lease expired (worker died)
                  │ reclaim_loop fires
                  └─── runs back to pending (attempt += 1)
```

## 3. Allowed transitions (table)

| From | To | Trigger | Persistence |
|------|-----|---------|-------------|
| (nothing) | `pending` | `ExecutionFacade.create_run()` | Insert row; `queued_at` set; `run.queued` event |
| `pending` | `claimed` | `run_lifecycle.claim_run(worker_id)` | Optimistic UPDATE WHERE `lease_owner IS NULL`; sets `lease_owner`, `lease_expires_at`, `claimed_at`; `run.claimed` event |
| `claimed` | `running` | First `step.started` event | `started_at` set |
| `running` | `running` | Each step completes; advance to next | `WorkflowRunStep` row inserted; `step.completed` event |
| `running` | `running` | Step fails but retry policy permits | `step.retry` event; `attempt` incremented; backoff via `Timer` |
| `running` | `paused` | Executor returns `NodeResult(status="paused")` | `paused_at` set; lease released; `run.paused` event; `Approval` row inserted if `humanApprovalNode` |
| `paused` | `running` | `signal_service.send` matches; OR `approval_service.grant`; OR `Timer` fires | `resumed_at` set; `run.resumed` event; lease re-acquired |
| `running` | `cancelled` | Pre-step check sees `cancel_requested_at` IS NOT NULL | `completed_at` set; `run.cancelled` event |
| `paused` | `cancelled` | Same check on resume | Same |
| `running` | `completed` | Last terminal step succeeds | `completed_at`, `output_data`, `metrics`, `duration_ms`; `run.completed` event |
| `running` | `failed` | Step fails, retry exhausted; OR stub-blocked in prod; OR fatal exception | `completed_at`, `error_code`, `error`, `duration_ms`; `run.failed` event |
| `claimed` | `pending` | Lease expires; `reclaim_loop` resets | `lease_owner` and `lease_expires_at` cleared; `attempt` may stay or increment per policy |
| `running` | `pending` | Worker crashes mid-step; lease expires; reclaim_loop resets | Same |

**Disallowed:**
- `completed` → anything (terminal).
- `failed` → anything (terminal). Re-running a failed run requires creating a new `WorkflowRun` (typically via the replay endpoint).
- `cancelled` → anything (terminal).
- Any non-dispatcher code path writing `workflow_runs.status`.

## 4. Lease ownership lifecycle

Worker leases prevent two replicas from double-executing a run.

| Field | Type | Set by | Cleared by |
|-------|------|--------|-----------|
| `lease_owner` | `str` (worker_id) | `claim_run` | `release_lease` (clean exit), `reclaim_expired_runs` (timeout) |
| `lease_expires_at` | `datetime` | `claim_run` (initial), `renew_lease` (heartbeat) | Same as above |
| `attempt` | `int` | Incremented on each `claim_run` | (Never reset) |

**Optimistic-lock SQL** (per [`run_lifecycle.claim_run`](../backend/app/services/run_lifecycle.py)):

```sql
UPDATE workflow_runs
   SET lease_owner = :worker_id,
       lease_expires_at = :now + interval '30 seconds',
       claimed_at = :now,
       attempt = attempt + 1,
       status = 'claimed'
 WHERE id = :run_id
   AND lease_owner IS NULL
   AND status = 'pending';
```

If `rowcount == 0`, another worker won the race; this worker re-enters its drain loop without a claim.

**Heartbeat:** Every `worker_registry` heartbeat (10s) triggers `renew_lease` for all runs the worker currently owns. The lease window is 30s; missing one heartbeat is tolerated, missing two means the run is reclaimed.

**Reclaim:** `reclaim_loop` (30s) selects runs with `status='claimed'` and `lease_expires_at < now()`, then resets `lease_owner=NULL`, `lease_expires_at=NULL`, and `status='pending'`. The next drain cycle picks them up.

## 5. Idempotency contract (ADR-004)

Two POSTs with the same `X-Idempotency-Key` (or computed `input_hash`) and the same `tenant_id` resolve to **the same `WorkflowRun.id`**.

| Scenario | Resolution |
|----------|-----------|
| First POST | 201 Created; new `WorkflowRun` row; `idempotency_key` stamped; `run.queued` emitted. |
| Second POST, same key, same input | 200 OK; returns the existing row. |
| Second POST, same key, **different input** | 409 Conflict; the new input is rejected because the partial unique index `(tenant_id, idempotency_key)` collides. |
| POST with no header, no derivable key | New row. No idempotency.

**Index** (per [`models/workflow.py`](../backend/app/models/workflow.py)):

```sql
CREATE UNIQUE INDEX uq_workflow_runs_tenant_idem
    ON workflow_runs (tenant_id, idempotency_key)
 WHERE idempotency_key IS NOT NULL;
```

The partial-where clause makes this work on both SQLite (test) and Postgres (production).

## 6. Retry / cancel decisions

### Retry

When a step fails with `NodeResult(status="failed")`, the dispatcher consults the step's `retry_policy`:

```python
@dataclass
class RetryPolicy:
    max_attempts: int = 1
    initial_delay_ms: int = 1000
    backoff_factor: float = 2.0
    max_delay_ms: int = 60_000
    retriable_errors: list[str] = []  # error codes that trigger retry
```

If `step.attempt < retry_policy.max_attempts` AND the error code is retriable:
1. Compute backoff: `delay_ms = min(initial_delay_ms * (backoff_factor ** attempt), max_delay_ms)`.
2. Insert a `Timer(fire_at=now + delay_ms, target=run_id, payload={"step_id": ...})`.
3. Emit `step.retry` event.
4. Release the lease.

When the timer fires, the worker's `timer_fire_loop` resumes the run; the dispatcher re-runs the failed step.

If retries are exhausted, the dispatcher emits `step.failed` (terminal for that step) and decides whether the run should `fail` (default) or continue (if `on_failure: continue`).

### Cancel

`POST /api/v1/runs/{id}/cancel` writes `cancel_requested_at = now()` to the row but does **not** change `status`. The dispatcher's pre-step check (in `dispatch_run` and on every resume from a `paused` state) inspects `cancel_requested_at`; if it is non-null, it transitions to `cancelled` cleanly.

**This is intentional.** The dispatcher is the only writer of status; the cancel endpoint is just a flag.

## 7. Event hash chain (ADR-002)

Every transition produces a row in `workflow_run_events`. Each row carries:

```
type           : str (one of 15 values per ADR-002)
run_id         : UUID
step_id        : UUID | None
sequence       : int  (monotonically increasing per run_id)
envelope       : JSONB
prev_hash      : str  (hash of the previous event for this run_id)
hash           : sha256(prev_hash || canonical_json(envelope))
created_at     : timestamp
```

The 15 valid event types:
- `run.queued`, `run.claimed`, `run.started`, `run.paused`, `run.resumed`, `run.cancelled`, `run.completed`, `run.failed`
- `step.started`, `step.completed`, `step.failed`, `step.retry`, `step.skipped`
- `signal.received`
- `approval.granted`

`GET /api/v1/runs/{id}/events/verify` recomputes hashes against the stored `prev_hash` chain and returns `{"verified": true, "tampered_indices": []}` or pinpoints any tampered row.

## 8. Cross-references

- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — the seven bounded contexts.
- [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md) — the env vars that gate startup.
- [`docs/adr/orchestration/`](adr/orchestration/) — the seven binding ADRs.
- [`backend/tests/test_dispatcher_integration.py`](../backend/tests/test_dispatcher_integration.py) — happy path + retry + cancel + pause/resume tests.
- [`backend/tests/test_pause_resume.py`](../backend/tests/test_pause_resume.py) — full pause / resume coverage.
- [`backend/tests/test_cancellation.py`](../backend/tests/test_cancellation.py) — cancel before / during step.
