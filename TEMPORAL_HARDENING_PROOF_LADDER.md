# Temporal Hardening Proof Ladder

Archon has implemented a broad architectural skeleton inspired by Temporal's
durable execution model. This document defines the proof gates required
before each capability can be called production-hardened.

Do not implement all of this at once. Each rung is a self-contained proof
with acceptance criteria and commands.

## Rung 1: Deterministic replay under code changes

**Goal:** Prove a running workflow uses its definition snapshot even if the
workflow definition is updated mid-run.

**Test scenario:**
1. Start a workflow run (run A) with definition version 1 (3 steps).
2. While run A is paused (e.g., waiting for approval), update the workflow
   definition to version 2 (4 steps, different step config).
3. Resume run A.
4. Assert run A completes using version 1's snapshot (3 steps), not version 2.
5. Start a new run (run B) after the update.
6. Assert run B uses version 2 (4 steps).

**Files:** `tests/integration/test_replay_determinism.py`

**Command:**
```bash
cd /Users/timothy.schwarz/Projects/Archon
PYTHONPATH=backend ARCHON_ENV=test LLM_STUB_MODE=true \
  ARCHON_AUTH_DEV_MODE=true ARCHON_RATE_LIMIT_ENABLED=false \
  python3 -m pytest tests/integration/test_replay_determinism.py -v
```

**Acceptance:** All tests pass. Run A uses snapshot, run B uses latest.

---

## Rung 2: Postgres SKIP LOCKED multi-worker claim

**Goal:** Prove concurrent workers claim distinct tasks under real Postgres,
not SQLite.

**Test scenario:**
1. Start Postgres (docker compose).
2. Enqueue 20 tasks to the same queue.
3. Start 3 workers polling the same queue concurrently.
4. Assert: every task is claimed exactly once (no double-claim).
5. Assert: all 20 tasks reach terminal state.
6. Assert: worker_id on each task is one of the 3 workers.

**Files:** `tests/integration/test_postgres_multiclaim.py`

**Prerequisites:** Postgres running, `ARCHON_TEST_POSTGRES_URL` set.

**Command:**
```bash
cd /Users/timothy.schwarz/Projects/Archon
ARCHON_TEST_POSTGRES_URL=postgresql+asyncpg://archon:archon@localhost:5432/archon_test \
  PYTHONPATH=backend ARCHON_ENV=test LLM_STUB_MODE=true \
  python3 -m pytest tests/integration/test_postgres_multiclaim.py -v
```

**Acceptance:** 0 double-claims, 20/20 terminal, 3 distinct worker_ids.

---

## Rung 3: Production-scale polling and backpressure

**Goal:** Prove the dispatcher handles backlog, rate limits, and backpressure
under sustained load.

**Test scenario:**
1. Enqueue 1000 tasks across 5 queues with varying priorities.
2. Start 5 workers with max_concurrency=10 each.
3. Queue "high-priority" has rate_limit=50/s.
4. Assert: all 1000 tasks complete within 60 seconds.
5. Assert: high-priority queue respects rate limit (no burst above 50/s).
6. Assert: no orphaned tasks (status stuck in claimed with expired lease).

**Files:** `tests/load/test_backlog_drain.py`, `scripts/run-load-tests.sh`

**Command:**
```bash
cd /Users/timothy.schwarz/Projects/Archon
bash scripts/run-load-tests.sh --profile backlog-drain
```

**Acceptance:** 1000/1000 terminal, rate limit respected, 0 orphans.

---

## Rung 4: Namespace isolation with Postgres RLS

**Goal:** Prove tenant isolation is enforced at the database level, not just
the application layer.

**Test scenario:**
1. Start Postgres with RLS policies enabled.
2. Create runs in tenant A and tenant B.
3. Using tenant A's session, attempt to read tenant B's runs, tasks, events,
   signals, schedules, artifacts, and pipeline correlations.
4. Assert: every cross-tenant read returns 0 rows (not an error, 0 rows).
5. Attempt cross-tenant UPDATE and DELETE.
6. Assert: 0 rows affected.

**Files:** `tests/integration/test_rls_isolation.py`

**Prerequisites:** Postgres with RLS policies applied (migration + RLS DDL).

**Command:**
```bash
cd /Users/timothy.schwarz/Projects/Archon
ARCHON_TEST_POSTGRES_URL=postgresql+asyncpg://archon:archon@localhost:5432/archon_test \
  ARCHON_RLS_ENABLED=true PYTHONPATH=backend ARCHON_ENV=test \
  python3 -m pytest tests/integration/test_rls_isolation.py -v
```

**Acceptance:** All cross-tenant reads return 0 rows. All cross-tenant
writes affect 0 rows.

---

## Rung 5: Cancellation and termination determinism

**Goal:** Remove the cancellation xfail by adding cooperative cancellation
checkpoints at every yield point.

**Test scenario:**
1. Start a 5-step workflow.
2. After step 2 completes, send cancel.
3. Assert: step 3 does NOT start (cancel checked before each activity).
4. Assert: run reaches `cancelled` status (not `failed`).
5. Assert: event history shows `run.cancel_requested` then `run.cancelled`.
6. No xfail markers remain in verify-slice.

**Files:** `backend/tests/test_cancellation_determinism.py`

**Command:**
```bash
cd /Users/timothy.schwarz/Projects/Archon
PYTHONPATH=backend ARCHON_ENV=test LLM_STUB_MODE=true \
  ARCHON_DISPATCH_INLINE=1 ARCHON_AUTH_DEV_MODE=true \
  python3 -m pytest backend/tests/test_cancellation_determinism.py -v
# Then verify xfail is gone:
bash scripts/verify-slice.sh  # should show 4 passed, 0 xfailed
```

**Acceptance:** Cancel test passes. verify-slice shows 0 xfailed.

---

## Rung 6: SDK ergonomics decision

**Goal:** Decide whether Archon stays REST/JSON-only or starts a Python SDK.

**Decision criteria:**
- If the primary consumers are the visual builder + CLI: REST/JSON is sufficient.
- If external developers will write workflows as code: a Python SDK with
  decorators (`@workflow`, `@activity`) is needed.

**If SDK is chosen:**

Files: `sdk/python/archon/`, `sdk/python/archon/client.py`,
`sdk/python/archon/decorators.py`

Minimal viable SDK:
```python
from archon import Client, workflow, activity

client = Client("http://localhost:8000/api/v1")

@activity
async def send_email(to: str, body: str) -> dict:
    ...

@workflow
async def onboarding(user_id: str):
    await send_email(to=user_id, body="Welcome")
    await workflow.sleep(timedelta(days=1))
    await send_email(to=user_id, body="Day 2 check-in")

run = client.start(onboarding, args=["user-123"])
```

**Command:** N/A (design decision, not a test).

**Acceptance:** Decision documented in ADR-009 with rationale.

---

## Execution order

Rungs are ordered by proof value and risk reduction:

1. **Rung 5** (cancellation determinism) -- removes the only xfail, smallest scope
2. **Rung 1** (replay determinism) -- core differentiator, moderate scope
3. **Rung 2** (Postgres multi-worker) -- required for any real deployment
4. **Rung 4** (RLS isolation) -- required for multi-tenant
5. **Rung 3** (scale) -- required for production load
6. **Rung 6** (SDK) -- product decision, not a proof gate
