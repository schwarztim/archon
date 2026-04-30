# Archon Remediation Report

## Outcome

**Gate B is green.** Acceptance commands all exit 0; the REST canary now drives a durable WorkflowRun to terminal completion through the same dispatcher path the worker uses.

## Files changed

- `/Users/timothy.schwarz/Projects/Archon/backend/app/services/dispatch_runtime.py` (NEW — tracked-task registry + inline-await test mode)
- `/Users/timothy.schwarz/Projects/Archon/backend/app/routes/executions.py` (replaced 2× `asyncio.create_task(dispatch_run(...))` with `await schedule_dispatch(...)`)
- `/Users/timothy.schwarz/Projects/Archon/backend/app/routes/agents.py` (same replacement on the agent-execute site)
- `/Users/timothy.schwarz/Projects/Archon/backend/app/routes/workflows.py` (extended `WorkflowStepCreate` with optional top-level `node_type`/`type`; lift from `config` on persist via `_lift_step_node_type`)
- `/Users/timothy.schwarz/Projects/Archon/backend/app/services/workflow_engine.py` (`_normalize_steps` now falls back to `config.node_type` / `config.type` / `config.nodeType` after top-level lookups)
- `/Users/timothy.schwarz/Projects/Archon/scripts/verify-slice.sh` (rewritten — removed transition mode + brittle `TestClient/httpx` grep; exports `ARCHON_DISPATCH_INLINE=1`)
- `/Users/timothy.schwarz/Projects/Archon/scripts/test-slice.sh` (defaults `ARCHON_DISPATCH_INLINE=1` so the script is self-contained; can be overridden with `ARCHON_DISPATCH_INLINE=0` to soak the worker drain loop)
- `/Users/timothy.schwarz/Projects/Archon/.github/workflows/ci.yml` (`ARCHON_TRANSITION: '1'` removed; `ARCHON_DISPATCH_INLINE: '1'` set on the verify-slice job)
- `/Users/timothy.schwarz/Projects/Archon/tests/integration/test_vertical_slice.py` (stale failure messages updated to current-era diagnostic guidance; xfail decorators preserved)
- `/Users/timothy.schwarz/Projects/Archon/backend/tests/test_dispatch_runtime.py` (NEW — 4 tests: inline await, tracked task, done-callback exception logging, inline-error swallow with log)
- `/Users/timothy.schwarz/Projects/Archon/backend/tests/test_workflow_step_normalization.py` (NEW — 5 tests: top-level wins, fallback to config.node_type, fallback to config.type, agent-only legacy path, neither-given raises)

## Gate B proof

### `python3 scripts/check-feature-matrix.py`

```
... (84 warnings about production-marked entries with empty test_files lists) ...
W: infra_services id=makefile_verify: status=production but test_files is empty
W: infra_services id=prometheus_config: status=production but test_files is empty
OK: 206 entries validated (production=95 beta=79 stub=13 designed=4 missing=15 blocked=0); 84 warning(s).
RC=0
```

### `python3 scripts/check-frontend-backend-parity.py`

```
======================================================================
Frontend↔backend node schema parity
======================================================================
Backend  registered (@register): 28 nodes
Frontend NodeKind union members: 28 nodes
Backend  status_registry rows  : 28 nodes
──────────────────────────────────────────────────────────────────────
OK: 0 DRIFT, 0 warnings
RC=0
```

### `bash scripts/verify-slice.sh`

```
▶ Vertical-slice REST canary (Wave 0)
  PYTHONPATH=backend
  LLM_STUB_MODE=true
  ARCHON_DATABASE_URL=sqlite+aiosqlite:///
  AUTH_DEV_MODE=true

tests/integration/test_vertical_slice.py::TestVerticalSliceRESTHeartbeat::test_rest_execution_creates_durable_workflow_run PASSED [ 25%]
tests/integration/test_vertical_slice.py::TestVerticalSliceNegativePaths::test_legacy_execution_id_in_dispatcher_does_not_silent_pass PASSED [ 50%]
tests/integration/test_vertical_slice.py::TestVerticalSliceCancel::test_running_execution_can_be_cancelled XFAIL [ 75%]
tests/integration/test_vertical_slice.py::TestVerticalSliceIdempotency::test_repeat_post_with_same_idempotency_key_returns_same_run XPASS [100%]

============= 2 passed, 1 xfailed, 1 xpassed, 27 warnings in 0.38s =============
✓ verify-slice passed
RC=0
```

### `bash scripts/test-slice.sh`

```
▶ Vertical-slice REST canary (Wave 0)
  PYTHONPATH=backend
  LLM_STUB_MODE=true
  ARCHON_DATABASE_URL=sqlite+aiosqlite:///
  AUTH_DEV_MODE=true

tests/integration/test_vertical_slice.py::TestVerticalSliceRESTHeartbeat::test_rest_execution_creates_durable_workflow_run PASSED [ 25%]
tests/integration/test_vertical_slice.py::TestVerticalSliceNegativePaths::test_legacy_execution_id_in_dispatcher_does_not_silent_pass PASSED [ 50%]
tests/integration/test_vertical_slice.py::TestVerticalSliceCancel::test_running_execution_can_be_cancelled XFAIL [ 75%]
tests/integration/test_vertical_slice.py::TestVerticalSliceIdempotency::test_repeat_post_with_same_idempotency_key_returns_same_run XPASS [100%]

============= 2 passed, 1 xfailed, 1 xpassed, 27 warnings in 0.36s =============
RC=0
```

### Invariant greps (must be empty)

```
$ grep -rn "ARCHON_TRANSITION" scripts/ .github/ backend/
(no matches)

$ grep -rn 'asyncio\.create_task(dispatch_run' backend/app/routes/
(no matches)
```

## Focused tests

```
$ ARCHON_DISPATCH_INLINE=1 LLM_STUB_MODE=true ARCHON_AUTH_DEV_MODE=true \
  ARCHON_RATE_LIMIT_ENABLED=false ARCHON_ENV=test PYTHONPATH=backend \
  python3 -m pytest \
    tests/integration/test_vertical_slice.py \
    backend/tests/test_execution_facade.py \
    backend/tests/test_run_dispatcher.py \
    backend/tests/test_dispatcher_persist.py \
    backend/tests/test_dispatcher_integration.py \
    backend/tests/test_idempotency.py \
    backend/tests/test_dispatch_runtime.py \
    backend/tests/test_workflow_step_normalization.py \
    -q

43 passed, 1 xfailed, 1 xpassed, 74 warnings in 4.52s
RC=0
```

The 1 xfailed remains `TestVerticalSliceCancel::test_running_execution_can_be_cancelled` (pre-existing — Phase 2 cancel propagation gap, documented). The 1 xpassed is the idempotency canary that flipped to passing earlier this cycle (`strict=False` xfail decorator means xpass is benign).

## What was actually fixed

**1. Dispatch contract.** The previous implementation did `asyncio.create_task(dispatch_run(run.id))` at three sites (`routes/executions.py:206`, `routes/executions.py:271`, `routes/agents.py:192`). Under the in-process FastAPI `TestClient` used by the canary, this returns before dispatch starts, the task reference can be garbage-collected, and any exception raised inside the coroutine is silently dropped. The canary's 5-second polling budget therefore observed `status="queued"` for the entire window and timed out.

The fix introduces `backend/app/services/dispatch_runtime.py` with two contracts:
- **Production default** — `schedule_dispatch(coro)` calls `asyncio.create_task(coro)`, retains the task in a module-level set so the GC cannot drop it, and attaches a `_on_done` callback that logs unhandled exceptions via `log.error(..., exc_info=...)`.
- **Test/CI mode** — when `ARCHON_DISPATCH_INLINE` is truthy, `schedule_dispatch(coro)` simply `await`s the coroutine inline, swallowing exceptions with a logged traceback. The REST handler returns only after dispatch is durable, so the canary observes terminal state on its first GET.

Both REST routes call `await schedule_dispatch(dispatch_run(run.id))`. No raw `asyncio.create_task(dispatch_run(...))` remains under `backend/app/routes/`.

**2. Step normalization.** `WorkflowStepCreate` (the Pydantic schema for `POST /workflows`) only accepted `name`, `agent_id`, `config`, `depends_on`. Slice helpers persist `node_type` inside `step["config"]["node_type"]` because there was no top-level field. `_normalize_steps` only consulted top-level `node_type` / `type` / `nodeType`, so REST-created workflows fell through to the legacy `agent_id` path and never executed the `inputNode → llmNode → outputNode` chain.

The fix is two-pronged:
- `_normalize_steps` now falls back through `config.node_type` / `config.type` / `config.nodeType` after the top-level lookup, in that order.
- `WorkflowStepCreate` gained optional `node_type` / `type` top-level fields; `create_workflow` and `update_workflow` run a `_lift_step_node_type` helper that copies the resolved value to top-level on the persisted JSON shape, so the canonical lifted form is what hits the DB and downstream code never depends on the lookup fallback after a single creation cycle.

**3. verify-slice mode.** The previous `verify-slice.sh` greppered the test file for `TestClient` / `httpx`, defaulted to fail-closed when the heuristic missed (the slice uses helper fixtures, not direct imports), and offered a transition-mode bypass via `ARCHON_TRANSITION=1` that CI was actively setting. The result was a "green" CI gate that ran in degraded mode against logic that no longer existed.

The fix removes all transition-mode logic, removes the brittle grep entirely, exports `ARCHON_DISPATCH_INLINE=1`, delegates to `test-slice.sh`, and surfaces the pytest exit code. `test-slice.sh` itself now defaults `ARCHON_DISPATCH_INLINE=1` so it is self-contained when invoked directly. `.github/workflows/ci.yml` had `ARCHON_TRANSITION: '1'` replaced with `ARCHON_DISPATCH_INLINE: '1'` on the verify-slice job. Repo-wide `grep ARCHON_TRANSITION` returns zero matches.

## What remains open

- **`test_running_execution_can_be_cancelled` is still XFAIL.** Phase 2 cancel propagation between the dispatcher's mid-step check and the test's polling window has a known race; the xfail reason is accurate. Not blocking Gate B.
- **`test_repeat_post_with_same_idempotency_key_returns_same_run` is XPASS.** The idempotency feature works; the original `xfail(strict=False)` decorator allows xpass as benign. Should be flipped to a positive assertion in a follow-up.
- **84 feature-matrix warnings** — production-marked entries with empty `test_files` lists. The validator passes (warnings, not errors); this is feature-matrix maintenance, not a slice gate.
- **Conflict 21 (advisory security scan).** `safety check ... || true` remains in `.github/workflows/ci.yml` security-scan job. Out of remediation scope (the directive listed it as Conflict 21 carry-forward); operator policy decision on severity threshold.
- **Pre-existing SQLModel deprecation warnings** for `session.execute()` vs `session.exec()`. Cosmetic; tests pass.
- **Helm CLI not installed locally**, so `make helm-lint` / `make helm-render` are deferred to CI / operator. Templates parse via static YAML lint.

## Claims you are allowed to make now

### Proven
- REST `POST /api/v1/executions` with a `{workflow_id, input_data}` body creates a durable `workflow_runs` row, executes the dispatcher path, persists `workflow_run_steps` rows, emits hash-chained `workflow_run_events`, and reaches terminal `completed` status. Demonstrated by `test_rest_execution_creates_durable_workflow_run` PASSED.
- Idempotency: same key + same input returns the same `run_id`; same key + different input returns 409. Demonstrated by `test_idempotency.py` (8 tests pass) plus the slice's XPASS.
- Dispatcher claim/persist/event emission. 16 dispatcher tests + 5 dispatch_runtime tests + 5 workflow step normalization tests all pass.
- Verify-slice gate is strict — no transition mode, no brittle heuristic. CI uses the same gate.
- Frontend↔backend node schema parity: 28 nodes both sides, 0 DRIFT.
- Conflict 9 closed: `dispatch_run` rejects unknown ID with explicit log, no silent no-op. `test_legacy_execution_id_in_dispatcher_does_not_silent_pass` PASSED.

### Implemented but unproven
- Production fire-and-forget mode (`ARCHON_DISPATCH_INLINE=0`) with worker drain loop end-to-end. Worker tests prove the drain primitive in isolation; the slice exercises only the inline path. A "real worker process picks up the queued run" smoke test would close this.
- Postgres RLS — code exists, SQLite tests prove application-layer isolation, Postgres tests skip cleanly without `ARCHON_TEST_POSTGRES_URL`. Real-PG run not exercised this remediation cycle.
- Helm chart — templates parse, `make helm-lint`/`make helm-render` deferred to CI / operator. Real `helm install` against kind/minikube not exercised.
- Keycloak SSO — tests skip cleanly without `KEYCLOAK_TEST_URL`. Real OIDC end-to-end not exercised.

### Missing
- Postgres RLS in CI as a mandatory job (not env-gated).
- Keycloak/OIDC and Vault integration tests in CI.
- kind/minikube Helm deploy smoke test in CI.
- Operator E2E flow test (start → observe → pause → approve → resume → terminal → inspect artifacts/costs).
- Real metrics-emission proof against a live Prometheus scrape.
- Replay-from-step backend (frontend has the disabled control with tooltip).
- `App.tsx` route registration for `RunHistoryPage` / `ApprovalsPage` / `ArtifactsPage` (one-line additions documented).

### Deferred
- Conflict 21: security-scan severity threshold (operator policy).
- Frontend bundle code-splitting.
- Pre-existing SQLModel `session.execute()` → `session.exec()` migration sweep.
- 14 stub-blocked node executors (embedding, vision, vector_search, document_loader, structured_output, function_call, tool, mcp_tool, etc.) — production implementations are individual workstreams, blocked in production by `_stub_block.assert_node_runnable`.
