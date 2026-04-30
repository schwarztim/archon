# Phase 6 — Load Test Profiles

Five load profiles validate the unified run dispatcher (`run_dispatcher.py`)
under parallel execution pressure with stubbed LLMs. Each profile dispatches
N workflows simultaneously via `asyncio.gather`, then asserts on durable
substrate invariants: complete-run count, full event chain, no double
execution.

All profiles use:
- `LLM_STUB_MODE=true` — deterministic 30-token stub responses, no API keys
- `LANGGRAPH_CHECKPOINTING=disabled` — sqlite DSN is unparseable by psycopg
- An in-memory SQLite engine (created per test, torn down on exit)

Source: `backend/tests/test_load/`

## Running

```bash
# Local default (N=50)
make load
# or:
bash scripts/run-load-tests.sh

# CI mode (N=10, ~2 min budget)
make load-ci
# or:
bash scripts/run-load-tests.sh --ci

# Custom N
LOAD_TEST_N=100 bash scripts/run-load-tests.sh

# Single profile
bash scripts/run-load-tests.sh -k test_load_fanout_fanin
```

## Profile Catalog

| # | File                                | What it stresses                                | N (local) | N (CI) | Step rows / run | Pass criteria                                                | Local budget | CI budget |
|---|-------------------------------------|-------------------------------------------------|-----------|--------|-----------------|--------------------------------------------------------------|--------------|-----------|
| 1 | `test_load_many_simple_workflows`   | Pure dispatch parallelism; claim contention     | 50        | 10     | 1               | All N complete; canonical event chain; no row dupes          | 30 s         | 60 s      |
| 2 | `test_load_fanout_fanin`            | parallelNode (mode=all) + mergeNode under load  | 20        | 10     | 7 (1+5+1)       | Every branch + merge completes; total rows == N×7            | 60 s         | 120 s     |
| 3 | `test_load_llm_stubs`               | LLM stub call-per-step token accounting         | 30        | 10     | 3 (linear LLM)  | Aggregate token_usage == N × 3 × 30 (deterministic stub)     | 60 s         | 120 s     |
| 4 | `test_load_approval_pause`          | humanApprovalNode pause + bulk grant_approval   | 10        | 10     | n/a (paused)    | All N pause; all N approval rows; bulk grant emits N signals | 60 s         | 120 s     |
| 5 | `test_load_retries_failures`        | RetryPolicy step.retry under parallel pressure  | 20        | 10     | 1 (then retry)  | All N emit step.retry; pause(retry_pending); retry completes | 60 s         | 120 s     |

## Profile Details

### Profile 1 — Many Simple Workflows

```text
[input] → outputNode("ok")
```

Each workflow is a single `outputNode`. Validates the dispatcher's
claim/execute/finalise loop scales horizontally without contention. With
N=50, a healthy system completes all runs in <30 s.

**Asserts:**
- Every `dispatch_run` returns `status="completed"`
- Event chain on every run: `run.claimed → run.started → step.completed → run.completed`
- `workflow_run_steps` row count == N (no double-execute)

**Tunable:** `LOAD_TEST_N` (default 50 local, 10 CI).

### Profile 2 — Fanout / Fan-in

```text
fanout (parallelNode mode=all)
  ├── branch_0 (outputNode)
  ├── branch_1
  ├── branch_2
  ├── branch_3
  └── branch_4
                         join (mergeNode merge_dicts)
```

Each workflow has 1 fanout + 5 branches + 1 merge = 7 step rows. With
N=20, the engine executes 140 steps total, 100 of them in parallel
sub-batches. Validates that branch ordering may vary but the merge
always succeeds with the combined output.

**Asserts:**
- Every run completes
- Each run produces exactly 7 `step.completed` events (one per step)
- Total `workflow_run_steps` rows == N × 7 (no duplicates from parallel race)

**Tunable:** `LOAD_TEST_N` (default 20).

### Profile 3 — LLM Stubs

```text
llmNode → llmNode → llmNode    (3 sequential LLM calls)
```

Each workflow chains 3 `llmNode` steps. With `LLM_STUB_MODE=true`, every
call returns a deterministic 30-token response (10 prompt + 20
completion). The aggregate over N=30 runs is 30 × 3 × 30 = 2,700 tokens
exactly. Any token accounting drift surfaces immediately.

**Asserts:**
- Every run completes within 60 s
- Per-run aggregated `token_usage.total_tokens` == 90 (3 × 30)
- Grand total across all runs == N × 90 (catches per-step writes
  overwritten by a wrong step's payload under parallel load)

**Tunable:** `LOAD_TEST_N` (default 30).

### Profile 4 — Approval / Pause

```text
pre (outputNode) → approve (humanApprovalNode) → post (outputNode)
```

Each workflow pauses at the approval step. We then bulk-grant every
pending `Approval` row. The dispatcher's complete-after-resume path is
out of scope for unit-test load (the worker drain loop owns that
re-dispatch lifecycle), but the structural invariants below are
asserted at scale.

**Implementation note:** `humanApprovalNode` reads `run_id` from
`ctx.node_data`. Tests inject `run_id` into the snapshot's step dict
after seeding so the executor takes the real-DB path (writes Approval
rows) instead of the synthetic-id fallback.

**Asserts:**
- All N runs land in `status="paused"` after first dispatch
- Exactly N pending `Approval` rows are created
- Bulk `grant_approval` produces N `approval.granted` `Signal` rows
- Every run flips back to `status="running"` and stamps `resumed_at`
- Event chain on every run includes `run.paused` → `run.resumed`

**Tunable:** `LOAD_TEST_N` (default 10).

### Profile 5 — Retries / Failures

```text
flaky (loadFlakyNode, RetryPolicy max_attempts=3)
```

Each workflow has a single `loadFlakyNode` (registered at module
import) whose first call fails with `error="TransientError: ..."`. The
dispatcher's `_maybe_schedule_retry` reads the class name from the
error string, computes an exponential backoff, schedules a Timer, and
emits `step.retry` + `run.paused(reason=retry_pending)`.

The retry path is then driven manually (clear lease, stamp
`_attempt=2` on the snapshot, re-dispatch) — under N=20 parallel runs,
every retry succeeds.

**Asserts:**
- All N runs land in `status="paused"` (retry_pending) after first dispatch
- Every run has a `step.retry` event in its chain
- Every run has a `run.paused` event with `payload.reason="retry_pending"`
- No double-execute on the failed step (one row per run after first dispatch)
- After the simulated retry, all N runs complete

**Tunable:** `LOAD_TEST_N` (default 20).

## Environment Variables

| Variable                   | Purpose                                                | Default                                |
|----------------------------|--------------------------------------------------------|----------------------------------------|
| `LOAD_TEST_N`              | Override N for every profile                            | 50 (local) / 10 (CI / `--ci`)          |
| `LLM_STUB_MODE`            | Force stub LLM (load tests refuse to run without)       | `true`                                 |
| `LANGGRAPH_CHECKPOINTING`  | Disable LangGraph postgres checkpointer for sqlite     | `disabled`                             |
| `PYTEST_TIMEOUT`           | Per-test wall-clock timeout (when pytest-timeout present)| 180 s (local) / 120 s (`--ci`)         |
| `PYTHONPATH`               | Resolve `app.*` imports                                 | `backend`                              |
| `ARCHON_ENV`               | `test` — disables prod-only safety gates                | `test`                                 |

## Authoring New Profiles

When adding a profile under `backend/tests/test_load/`, follow the
existing pattern:

1. Use the shared `conftest.py` fixtures: `patched_dispatcher`,
   `seed_run_factory`, `dispatch_helper`, `wait_terminal_helper`,
   `double_execute_helper`, `event_chain_helper`, `budget_helper`.
2. Honour `LOAD_TEST_N` via the per-profile fixture (e.g. `fanout_n`,
   `llm_n`) so CI can scale down. Local default ≥ 10; CI default ≤ 10.
3. Always assert: (a) total completed runs == N, (b) full event chain
   for every run, (c) no double-execute via `double_execute_helper`.
4. Set a wall-clock budget appropriate for the topology — never gate
   on absolute clock time without `budget_helper` so test failures
   include the actual elapsed seconds.

## Related Suites

- `backend/tests/test_run_dispatcher.py` — dispatcher unit tests (single-run paths)
- `backend/tests/test_dispatcher_persist.py` — persistence + event chain (single-run)
- `backend/tests/test_dispatcher_integration.py` — integration with worker drain
- `backend/tests/test_pause_resume.py` — approval + delay + signal pathways (single-run)
- `backend/tests/test_retry_policy.py` — RetryPolicy unit tests
- `tests/integration/test_vertical_slice.py` — REST→DB end-to-end heartbeat
