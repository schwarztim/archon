# Archon — Current State (as of 2026-04-29)

## TL;DR

The kernel is real. The official slice path passes `bash scripts/verify-slice.sh` and `bash scripts/test-slice.sh` end-to-end (REST → durable `WorkflowRun` → step rows → hash-chained event log → terminal `completed` status), but **only under the inline-dispatch script/CI contract** (`ARCHON_DISPATCH_INLINE=1`). Production fire-and-forget worker dispatch end-to-end, mandatory enterprise infrastructure proofs (Postgres RLS in CI, Keycloak/OIDC, Vault token/policy contract), live observability scrape, scale/chaos under load, the security-scan severity threshold, and frontend page reachability are **not yet hard gates**. This document is the canonical truth-table — every other status claim in the repo should defer to it.

## Truth table

| Item | Proven | Script-green only | Implemented but unproven | Missing | Deferred (operator decision) |
|------|--------|-------------------|--------------------------|---------|------------------------------|
| ADRs 1–7 (orchestration) | docs/adr/orchestration/ADR-001..007.md exist with binding decisions and `**Status:** ACCEPTED` | | | | |
| Feature matrix | `python3 scripts/check-feature-matrix.py` RC=0 (206 entries; 84 warnings) | | | | |
| Frontend ↔ backend node parity | `python3 scripts/check-frontend-backend-parity.py` RC=0 (28 backend = 28 frontend = 28 status_registry, 0 DRIFT) | | | | |
| Vertical slice (inline mode) | `bash scripts/test-slice.sh` RC=0 (2 passed, 1 xfailed, 1 xpassed) | | | | |
| Vertical slice (non-inline / production worker mode) | | | Worker drain primitive tested in isolation; non-inline REST canary not present | A canary that issues `POST /api/v1/executions` with `ARCHON_DISPATCH_INLINE=0`, lets a separate worker process drain it, and asserts terminal status | |
| Idempotency contract (ADR-004) | `backend/tests/test_idempotency.py` (8 tests pass); slice XPASS; `(tenant_id, idempotency_key)` partial unique index | | | | Stale `xfail(strict=False)` decorator on the slice idempotency test should be flipped to a positive assertion |
| Cancellation | | | `cancel_requested_at` column + dispatcher pre-step check exist | End-to-end cooperative cancel proof — `TestVerticalSliceCancel::test_running_execution_can_be_cancelled` is honestly XFAIL because cancel propagation between dispatcher mid-step check and the test's polling window has a known race | |
| Pause/resume | `backend/tests/test_approvals.py` + `test_pause_resume.py`: typed Approval + Signal models + REST endpoints + node refactor | | Operator-flow E2E (start → pause → approve → resume → terminal) not exercised in this workspace | | |
| Workflow engine branch / parallel / loop semantics (ADR-003) | `backend/tests/test_node_executors/` — 225 contract tests; engine emits hint envelopes; engine routes per ADR-003 | | | | |
| Stub-block enforcement (production/staging) | `backend/app/services/node_executors/_stub_block.py` + `status_registry.py`; dispatcher emits `step.failed` with `error_code="stub_blocked_in_production"`; 38 status tests | | | | |
| Tenant context | `backend/app/services/tenant_context.py` (ContextVar); `_check_tenant_context_active` startup gate; SQLite app-layer tests pass | | | | |
| RLS — SQLite (app-layer) | App-layer tenant filtering tests pass | | | | |
| RLS — Postgres (db-layer) | | | RLS DDL exists in migrations 0002/0003 (gated on PG dialect); SQLite tests prove app-layer isolation | Postgres-required RLS tests gated behind `ARCHON_TEST_POSTGRES_URL` skip cleanly without it; **mandatory PG RLS CI service is not present** | |
| Cost gate fail-closed | `backend/app/services/budget_service.py`; `BudgetCheckResult` + `cost_gate_budget_exceeded` / `_no_budget` / `_lookup_failed` error codes; production/staging fail-closed branch tested | | Enterprise-mode promotion of `costGateNode` BETA → PRODUCTION (status_registry + feature-matrix.yaml + pin tests) is half done | | |
| Audit hash chain | `backend/app/services/audit_chain.py` — per-tenant chains, tamper detection with `first_corruption_at_id`; verify endpoint; 33 tests in audit_hash_chain + RBAC bundle | | | | |
| Route permission matrix | `scripts/route-permissions-allowlist.txt` (276 entries, 0 DRIFT) + `scripts/check-route-permissions.py` | | | | |
| Model routing + circuit breaker | `backend/app/services/router_service.py`: `Phase4RoutingDecision` + circuit breaker `closed → open → half_open → closed` + tenant policy pin + fallback chain; tests in Phase 4 bundle | | Live LLM smoke against real `OPENAI_API_KEY` not exercised | | Real LLM smoke test gated on opt-in CI secret |
| Checkpointer fail-closed (ADR-005) | `backend/app/langgraph/checkpointer.py` raises `CheckpointerDurabilityFailed` in production; `MemorySaver` rejected; 22 checkpointer tests + 11 startup tests | | | | |
| Durable timers + retry policy | `backend/app/services/timer_service.py` + `retry_policy.py`; `models/timers.py`; alembic 0009; worker timer-fire loop; 13 timer tests + 16 retry tests | | | | |
| Worker leases + drain + reclaim | `backend/app/services/worker_registry.py`; `lease_owner` / `lease_expires_at` columns; `claim_run` / `renew_lease` / `release_lease` / `reclaim_expired_runs`; 15 worker tests | | Multi-process worker drain end-to-end (separate process picks up queued REST run) not exercised by the slice canary | | |
| Metrics emission (canonical names) | 14 canonical Prometheus metrics defined; `docs/metrics-catalog.md`; `scripts/check-grafana-metric-parity.py` | | Live emission during a real REST run (Prometheus scrape with non-zero series) not validated in this workspace | | |
| Tracing (OpenTelemetry) | `backend/app/services/tracing.py` no-op fallback wrapper; `workflow.run → workflow.step → llm.call/http.client` nesting | | Live trace export not validated end-to-end | | |
| Artifacts | `backend/app/services/artifact_service.py`; alembic 0011; threshold-based extraction; `_artifact_ref` pattern; tenant scoping | | Operator-flow artifact inspection E2E not exercised | | |
| Helm chart | `infra/helm/archon-platform/` Chart.yaml + 15 templates + values dev/production with 52 production overrides; `make helm-lint` / `make helm-render`; templates parse via static YAML lint | | `helm install` against a real cluster (kind/minikube) not exercised in this workspace | A real Helm-render-and-deploy smoke test in CI | |
| Backup/restore scripts | `scripts/backup-postgres.sh` + `scripts/restore-postgres.sh` + `backup-vault.sh` + `restore-vault.sh` + `backup-restore-test.sh`; 9 DR scenarios with RTO/RPO in `docs/runbooks/disaster-recovery.md` | | Restore against a real production-like DB not exercised in this workspace | | |
| Frontend page reachability — `ExecutionDetailPage` | `frontend/src/App.tsx:11,68` registers `executions/:id` route | | | | |
| Frontend page reachability — `RunHistoryPage` | | Component + 19 tests exist | | NOT registered in `frontend/src/App.tsx` — operator cannot navigate to it | |
| Frontend page reachability — `ApprovalsPage` | | Component + 21 tests exist | | NOT registered in `frontend/src/App.tsx` — operator cannot navigate to it | |
| Frontend page reachability — `ArtifactsPage` | | Component + 11 tests exist | | NOT registered in `frontend/src/App.tsx` — operator cannot navigate to it | |
| Operator flow E2E | | | Component-level tests exist for each surface | No end-to-end test that ties start → observe → pause → approve → resume → terminal → inspect artifacts/costs together | |
| Replay-from-step | | | Frontend has the disabled control with tooltip | Backend endpoint to replay from a chosen step ID is not implemented | |
| Schedules | `backend/app/routes/schedules.py` registered; pending-run drain loop (5s) | | Schedule-created pending run end-to-end drained by separate worker process not exercised by the official canary | | |
| Webhooks | Routes registered | | End-to-end webhook → durable run → terminal not exercised by the official canary | | |
| Keycloak SSO end-to-end | | | 3-tier JWT auth code + JWKS cache; tests gated on `KEYCLOAK_TEST_URL` skip cleanly | A high-fidelity OIDC contract test or Keycloak-backed CI test is **not** mandatory in CI | |
| Vault integration (token/policy) | Real `hvac` integration; KV-v2 + PKI + Transit + AppRole; in-memory TTL cache | | Live token/policy/path contract test not exercised in CI | | |
| CI security-scan severity threshold | | | `safety check ... \|\| true` exists in `.github/workflows/ci.yml` | A binding severity threshold and explicit allowed-exception list are not configured | Conflict 21 — operator policy decision on acceptable severity threshold |
| Frontend bundle code-splitting | | | Single 1.6 MB bundle | | Operator decision (target <500 KB initial) |
| SQLModel `session.execute()` → `session.exec()` migration | | | Cosmetic deprecation warnings remain | | Operator decision — not blocking |
| 14 stub-blocked node executors | | | `_stub_block.assert_node_runnable` blocks them in production | Real implementations for `embeddingNode`, `visionNode`, `vectorSearchNode`, `documentLoaderNode`, `structuredOutputNode`, `streamOutputNode`, `functionCallNode`, `toolNode`, `mcpToolNode`, `databaseQueryNode`, `humanInputNode`, `loopNode` (production loop body subgraph), `dlpScanNode` (production promotion path) | |
| OPA policy engine | | | Substrate (`ARCHON_ENTERPRISE_STRICT_TENANT` + audit chain + budget gates) chosen as the policy substrate this cycle | OPA wiring | Operator decision — out of scope this cycle |

## What "proven" means here

A claim is **proven** only if all three are true:

1. There is a test or canary that exercises the production path (not just an isolated unit).
2. The acceptance command exits 0 in the current workspace.
3. The proof does not depend on a special environment variable that is not the documented production default.

If any of (1)/(2)/(3) fail, the claim downgrades to "Script-green only" or "Implemented but unproven."

## What "script-green only" means

The acceptance script passes (e.g. `bash scripts/test-slice.sh` exits 0), **BUT** it depends on `ARCHON_DISPATCH_INLINE=1` — the test/CI contract — not the production fire-and-forget contract.

Why the inline-dispatch contract is not the production contract:

- Production routes go through `await schedule_dispatch(dispatch_run(run.id))` in `backend/app/routes/executions.py` and `backend/app/routes/agents.py`. With `ARCHON_DISPATCH_INLINE=0` (production default), `schedule_dispatch` calls `asyncio.create_task(coro)` and tracks it in a module-level set with a `_on_done` callback that logs unhandled exceptions.
- That logging path does not yet update `WorkflowRun.status` to `failed` if the background task raises. A crash in the background dispatch is recorded in logs but the run remains in whatever state it was in.
- The slice canary observes terminal state on the first GET only because inline mode awaits the coroutine before the route returns. In production mode, the route returns first and dispatch happens after; there is currently no canary that proves a separate worker drains a queued run end-to-end.

To promote from script-green to proven, see plan §P0 ("Harden Gate B from script-green to production-proof").

## What is proven (acceptance command + result)

| Claim | Acceptance command | Result (citation) |
|-------|--------------------|-------------------|
| Feature matrix valid | `python3 scripts/check-feature-matrix.py` | RC=0 — `206 entries validated (production=95 beta=79 stub=13 designed=4 missing=15 blocked=0); 84 warning(s)` (REMEDIATION_REPORT.md §"Gate B proof") |
| Frontend ↔ backend node parity | `python3 scripts/check-frontend-backend-parity.py` | RC=0 — `Backend registered (@register): 28 nodes; Frontend NodeKind union members: 28 nodes; Backend status_registry rows: 28 nodes; OK: 0 DRIFT, 0 warnings` (REMEDIATION_REPORT.md §"Gate B proof") |
| REST canary green (inline, via verify wrapper) | `bash scripts/verify-slice.sh` | RC=0 — `2 passed, 1 xfailed, 1 xpassed, 27 warnings in 0.38s` (REMEDIATION_REPORT.md §"Gate B proof") |
| REST canary green (inline, direct) | `bash scripts/test-slice.sh` | RC=0 — `2 passed, 1 xfailed, 1 xpassed, 27 warnings in 0.36s` (REMEDIATION_REPORT.md §"Gate B proof") |
| Focused Gate B bundle (env-dependent — see plan §P0) | `ARCHON_DISPATCH_INLINE=1 LLM_STUB_MODE=true ARCHON_AUTH_DEV_MODE=true ARCHON_RATE_LIMIT_ENABLED=false ARCHON_ENV=test PYTHONPATH=backend python3 -m pytest tests/integration/test_vertical_slice.py backend/tests/test_execution_facade.py backend/tests/test_run_dispatcher.py backend/tests/test_dispatcher_persist.py backend/tests/test_dispatcher_integration.py backend/tests/test_idempotency.py backend/tests/test_dispatch_runtime.py backend/tests/test_workflow_step_normalization.py -q` | `43 passed, 1 xfailed, 1 xpassed, 74 warnings in 4.52s` (REMEDIATION_REPORT.md §"Focused tests") |
| `dispatch_run` rejects unknown ID with explicit log | `tests/integration/test_vertical_slice.py::TestVerticalSliceNegativePaths::test_legacy_execution_id_in_dispatcher_does_not_silent_pass` | PASSED (REMEDIATION_REPORT.md slice output) |
| No raw `asyncio.create_task(dispatch_run(...))` remains in routes | `grep -rn 'asyncio\.create_task(dispatch_run' backend/app/routes/` | (no matches) (REMEDIATION_REPORT.md §"Invariant greps") |
| No `ARCHON_TRANSITION` remains in scripts/CI/backend | `grep -rn "ARCHON_TRANSITION" scripts/ .github/ backend/` | (no matches) (REMEDIATION_REPORT.md §"Invariant greps") |

## What is implemented but unproven

Items with code + isolated tests but no live or end-to-end product proof:

- Production fire-and-forget worker dispatch end-to-end (a non-inline REST canary that drains via a separate worker process and asserts terminal status).
- Background dispatch failure path: when the tracked background task raises, the run should durably transition to `failed` with a `run.failed` event. Currently exceptions are logged but the run state is not updated.
- Postgres RLS at the database layer (DDL exists; no mandatory CI Postgres service exercises it).
- Keycloak SSO end-to-end CI test (3-tier JWT code present; tests skip cleanly without `KEYCLOAK_TEST_URL`).
- Vault token/policy/path contract test (`hvac` integration present; not exercised in CI).
- `helm install` on a real cluster (kind/minikube). Templates parse; no live deploy proof.
- Live Prometheus scrape against a running REST workflow with assertions on emitted series (catalog and dashboards exist; live ingest not validated).
- Live OpenTelemetry trace export (no-op fallback wrapper present; live exporter not validated).
- Operator-flow artifact inspection end-to-end.
- Multi-process worker drain (worker primitives tested in isolation; no end-to-end "second process picks up queued run" canary).
- Schedule-created pending run drained by worker (5s drain loop exists; no end-to-end canary).

## What is missing

Items with no implementation OR honest gaps in the workspace:

- Replay-from-step backend endpoint (frontend has the disabled control with a tooltip; no backend endpoint to replay from a chosen step ID).
- Operator-flow E2E test (start → observe → pause → approve → resume → terminal → inspect artifacts/costs as one connected scenario).
- 14 stub-blocked node executors awaiting real implementations (embedding, vision, vector_search, document_loader, structured_output, stream_output, function_call, tool, mcp_tool, database_query, human_input, loop body subgraph, dlpScanNode production promotion).
- `RunHistoryPage`, `ApprovalsPage`, `ArtifactsPage` route registration in `frontend/src/App.tsx` (one-line addition each; components and tests exist but the operator cannot navigate to them).
- Mandatory Postgres RLS CI service (currently env-gated and skipped when `ARCHON_TEST_POSTGRES_URL` absent).
- Mandatory Keycloak/OIDC CI service (currently env-gated and skipped when `KEYCLOAK_TEST_URL` absent).
- Mandatory Vault integration test in CI (currently not present).
- kind/minikube Helm deploy smoke test in CI.
- Non-inline (`ARCHON_DISPATCH_INLINE=0`) worker canary in CI.
- Background-dispatch-failure → run.failed terminal state path.

## Deferred (operator decision)

- CI security-scan severity threshold — `safety check ... || true` is advisory; choosing the binding threshold and the allowed-exception list is an operator policy decision (Conflict 21).
- Frontend bundle code-splitting — current 1.6 MB monolithic bundle; target <500 KB initial. Operator decision.
- SQLModel `session.execute()` → `session.exec()` migration — cosmetic deprecation warnings; tests pass. Operator decision.
- Real LLM smoke test against a live `OPENAI_API_KEY`-gated CI job — requires opt-in CI secret. Operator decision.
- OPA policy engine integration — Phase 4 chose `ARCHON_ENTERPRISE_STRICT_TENANT` + audit chain + budget gates as the policy substrate. Operator decision whether to add OPA on top.

## Citations

Every row in the truth table cites a file path or command output. The authoritative supporting documents are:

- `REMEDIATION_REPORT.md` (2026-04-29) — corrective action that landed Gate B for the inline-dispatch script contract; contains verbatim command outputs.
- `PHASE_0_9_EXECUTION_REPORT.md` (2026-04-29, with reconciliation note prepended) — historical phase-by-phase narrative.
- `tests/integration/test_vertical_slice.py` — the canary itself.
- `backend/app/services/dispatch_runtime.py` — inline-await test mode + tracked-task registry.
- `backend/app/routes/executions.py`, `backend/app/routes/agents.py` — routes that call `await schedule_dispatch(dispatch_run(run.id))`.
- `backend/app/services/run_dispatcher.py` — claim/persist/event-emission.
- `backend/app/services/execution_facade.py` — single REST entry point.
- `backend/app/services/idempotency_service.py` — partial unique index + 200/201/409 semantics per ADR-004.
- `backend/app/services/workflow_engine.py` — ADR-003 hint envelope routing.
- `backend/app/services/node_executors/_stub_block.py` + `status_registry.py` — production stub-block enforcement.
- `frontend/src/App.tsx` — route registration source of truth.
- `docs/adr/orchestration/ADR-001..007.md` — binding decisions.
- `docs/feature-matrix.yaml` + `scripts/check-feature-matrix.py` — 206-entry inventory.
- `scripts/check-frontend-backend-parity.py` — parity drift gate.
- `scripts/verify-slice.sh` + `scripts/test-slice.sh` — REST canary scripts (export `ARCHON_DISPATCH_INLINE=1`).
- `.github/workflows/ci.yml` — verify-slice job sets `ARCHON_DISPATCH_INLINE: '1'`; security-scan job retains `safety check ... || true`.
