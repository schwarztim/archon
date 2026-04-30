# Archon — Current State (as of 2026-04-30)

## TL;DR

The kernel is real. The official slice path passes `bash scripts/verify-slice.sh` and `bash scripts/test-slice.sh` end-to-end (REST → durable `WorkflowRun` → step rows → hash-chained event log → terminal `completed` status). The non-inline worker canary (3/3 tests) and background dispatch failure persistence are proven locally. Frontend routes for `/runs`, `/approvals`, and `/artifacts` are registered. The ExecutionFacade bypass gate is GREEN. Production infrastructure proofs (Postgres RLS in CI, Keycloak/OIDC, Vault token/policy contract), live observability scrape, scale/chaos under load, the security-scan severity threshold, and the worker canary as a hard CI gate are **not yet hard gates**. This document is the canonical truth-table — every other status claim in the repo should defer to it.

## Truth table

| Item | Proven locally | Impl. but not production-proven | Configured / awaiting real CI proof | Missing / deferred |
|------|---------------|---------------------------------|-------------------------------------|---------------------|
| ADRs 1–8 (orchestration) | `docs/adr/orchestration/ADR-001..008.md` exist with binding decisions and `**Status:** ACCEPTED` | | | |
| Feature matrix | `python3 scripts/check-feature-matrix.py` exits 1 — 4 pipeline executor files (`pipeline_artifact`, `pipeline_cancel`, `pipeline_start`, `pipeline_wait`) have no feature-matrix.yaml entries; all other validation passes with warnings | | | 4 missing entries for pipeline node executors |
| Frontend ↔ backend node parity | `python3 scripts/check-frontend-backend-parity.py` RC=0 (28 backend = 28 frontend = 28 status_registry, 0 DRIFT) | | | |
| Vertical slice (inline mode) | `bash scripts/test-slice.sh` RC=0 (2 passed, 1 xfailed, 1 xpassed) | | | |
| Vertical slice (non-inline / production worker mode) | `tests/integration/test_worker_canary.py` TestNonInlineWorkerCanary (3/3 pass) via `bash scripts/test-worker-canary.sh` RC=0 — run claims worker_id, has step rows, emits lifecycle events | | | Non-inline canary not a hard CI gate in `.github/workflows/ci.yml` |
| Background dispatch failure persistence | `tests/integration/test_worker_canary.py::TestNonInlineFailureFinalisation` + `backend/tests/test_dispatch_runtime_failure.py` (7 tests); `_persist_failed_run` transitions run to `failed` with `run.failed` event via `drain_tracked_tasks` | | | traceback hash / worker_id / correlation_id fields not yet on the emitted event payload |
| Idempotency contract (ADR-004) | `backend/tests/test_idempotency.py` (8 tests pass); slice XPASS; `(tenant_id, idempotency_key)` partial unique index | | | Stale `xfail(strict=False)` on slice idempotency test should be flipped |
| Cancellation | | `cancel_requested_at` column + dispatcher pre-step check exist | | End-to-end cooperative cancel proof is XFAIL — race between dispatcher mid-step check and test polling window |
| Pause/resume | `backend/tests/test_approvals.py` + `test_pause_resume.py`: typed Approval + Signal models + REST endpoints + node refactor | | | Operator-flow E2E (start → pause → approve → resume → terminal) not exercised |
| Workflow engine branch / parallel / loop semantics (ADR-003) | `backend/tests/test_node_executors/` — 225 contract tests; engine emits hint envelopes; engine routes per ADR-003 | | | |
| Stub-block enforcement (production/staging) | `backend/app/services/node_executors/_stub_block.py` + `status_registry.py`; dispatcher emits `step.failed` with `error_code="stub_blocked_in_production"`; 38 status tests | | | |
| Tenant context | `backend/app/services/tenant_context.py` (ContextVar); `_check_tenant_context_active` startup gate; SQLite app-layer tests pass | | | |
| RLS — SQLite (app-layer) | App-layer tenant filtering tests pass | | | |
| RLS — Postgres (db-layer) | | | RLS DDL exists in migrations 0002/0003 (gated on PG dialect); mandatory PG RLS CI service is not present | |
| Cost gate fail-closed | `backend/app/services/budget_service.py`; `BudgetCheckResult` + `cost_gate_budget_exceeded` / `_no_budget` / `_lookup_failed` error codes; production/staging fail-closed branch tested | | | Enterprise-mode promotion of `costGateNode` BETA → PRODUCTION half done |
| Audit hash chain | `backend/app/services/audit_chain.py` — per-tenant chains, tamper detection with `first_corruption_at_id`; verify endpoint; 33 tests in audit_hash_chain + RBAC bundle | | | |
| Route permission matrix | `scripts/route-permissions-allowlist.txt` (276 entries, 0 DRIFT) + `scripts/check-route-permissions.py` | | | |
| Model routing + circuit breaker | `backend/app/services/router_service.py`: `Phase4RoutingDecision` + circuit breaker `closed → open → half_open → closed` + tenant policy pin + fallback chain | | Live LLM smoke against real `OPENAI_API_KEY` not exercised | Real LLM smoke test gated on opt-in CI secret |
| Checkpointer fail-closed (ADR-005) | `backend/app/langgraph/checkpointer.py` raises `CheckpointerDurabilityFailed` in production; `MemorySaver` rejected; 22 checkpointer tests + 11 startup tests | | | |
| Durable timers + retry policy | `backend/app/services/timer_service.py` + `retry_policy.py`; `models/timers.py`; alembic 0009; worker timer-fire loop; 13 timer tests + 16 retry tests | | | |
| Worker registry with heartbeat + stale sweep | `backend/app/services/worker_registry.py`; `lease_owner` / `lease_expires_at` columns; `claim_run` / `renew_lease` / `release_lease` / `reclaim_expired_runs`; heartbeat + stale sweep; 12 worker registry tests | | | Multi-process worker drain end-to-end not exercised as a separate OS process |
| Activity runtime (heartbeat, cancel, retry, artifact, legacy adapter) | `backend/app/services/activity_runtime.py`; 22 tests (`backend/tests/test_activity_runtime.py`) | | | |
| Dispatcher task-queue polling with legacy fallback | `backend/app/services/run_dispatcher.py`; task-queue polling + legacy fallback path; 9 tests | | | |
| Signals / queries / updates endpoints | 7 tests covering signal delivery, query responses, and update processing | | | |
| Cancel / terminate / pause / resume lifecycle controls | 17 tests covering full lifecycle control surface | | | |
| Schedule engine with 6 overlap policies | `backend/app/routes/schedules.py` registered; pending-run drain loop (5s); 9 tests covering all 6 overlap policies | | | Schedule-created pending run end-to-end not exercised by the official canary (worker.py was a bypass — now through ExecutionFacade per bypass gate green) |
| Pipeline ingress for 5 providers + correlation tracking | 5 provider adapters (`github_actions`, `azure_devops`, `jenkins`, `gitlab`, `generic_webhook`); `PipelineCorrelation` model; 9 tests | | | Provider adapters mocked in tests; no real provider credentials tested |
| Pipeline activities (start/wait/cancel/artifact) | `pipeline_start.py`, `pipeline_wait.py`, `pipeline_cancel.py`, `pipeline_artifact.py` executors; 27 tests | | | 4 executor files not referenced in `docs/feature-matrix.yaml` (flagged by check-feature-matrix.py E:) |
| Replay with hash-chain verification | Replay endpoint; hash-chain integrity check on replay path; 6 tests | | | Deterministic replay under code changes (snapshot isolation when definition changes mid-run) not proven |
| Definition versioning | `WorkflowDefinitionVersion` model + migration; 8 tests | | | |
| Continue-as-new with RunChain | `RunChain` model + migration; continue-as-new semantics; 5 tests | | | |
| Visibility search + timeline + graph | `VisibilityIndex` model + migration; search, timeline, and graph queries; 7 tests | | | |
| CLI with 14 commands | CLI module; 10 tests covering 14 commands | | | |
| Tenant isolation guard | Tenant context enforcement; 7 tests | | | |
| Policy gates with enterprise fail-closed | `ARCHON_ENTERPRISE_STRICT_TENANT` + audit chain + budget gates; enterprise fail-closed path; 9 tests | | | |
| Payload codec | Payload encoding/decoding; 13 tests | | | |
| Chaos tests (lifecycle crash, storm, enterprise policy) | 32 chaos tests across lifecycle crash, storm, and enterprise policy scenarios | | | Production-scale polling not load-tested beyond 100-task chaos drain |
| Metrics service with 16 archon_ prefixed metrics | `backend/app/services/metrics_service.py`; 16 `archon_`-prefixed Prometheus metrics; 5 tests (`backend/tests/test_metrics_real.sh` 6/6 via live emission) | | Live Prometheus scrape against running REST workflow not validated end-to-end | |
| Tracing (OpenTelemetry) | `backend/app/services/tracing.py` no-op fallback wrapper; `workflow.run → workflow.step → llm.call/http.client` nesting | | Live trace export not validated end-to-end | |
| Artifacts | `backend/app/services/artifact_service.py`; alembic 0011; threshold-based extraction; `_artifact_ref` pattern; tenant scoping | | | Operator-flow artifact inspection E2E not exercised |
| TaskQueue / Task models + migrations (0012–0013) | `backend/app/models/task_queue.py`; alembic 0012 + 0013 | | | |
| ActivityExecution model + migration (0013) | `backend/app/models/activity.py`; alembic 0013 | | | |
| Schedule / PipelineCorrelation / WorkflowDefinitionVersion / RunChain / VisibilityIndex models + migrations (0014–0018) | Models present; alembic 0014–0018; single head confirmed: `0018_add_visibility_index` | | | |
| Alembic: single head (0018), clean upgrade | `alembic heads` → `0018_add_visibility_index (head)` — single head confirmed | | | |
| 10 executor promotions to BETA | `embeddingNode`, `structuredOutputNode`, `visionNode` (LiteLLM multi-modal wrapper) + 7 additional nodes promoted STUB → BETA per recent commits | | | |
| ExecutionFacade bypass gate GREEN | `bash scripts/check-direct-run-bypasses.sh` → `OK: no direct WorkflowRun construction outside ExecutionFacade` (RC=0) | | | |
| Vendor reference scrub GREEN | `bash scripts/check-vendor-refs.sh` → `OK: no unallowed vendor references` (RC=0) | | | |
| Frontend page reachability — `ExecutionDetailPage` | `frontend/src/App.tsx:11,71` registers `executions/:id` route | | | |
| Frontend page reachability — `RunHistoryPage` | `frontend/src/App.tsx:12,72` registers `/runs` route | | | |
| Frontend page reachability — `ApprovalsPage` | `frontend/src/App.tsx:13,73` registers `/approvals` route | | | |
| Frontend page reachability — `ArtifactsPage` | `frontend/src/App.tsx:14,74` registers `/artifacts` route | | | |
| Helm chart | `infra/helm/archon-platform/` Chart.yaml + 15 templates + values dev/production; `make helm-lint` / `make helm-render` parse statically | | `helm install` against a real cluster (kind/minikube) not exercised | kind/minikube Helm deploy smoke test in CI |
| Backup/restore scripts | `scripts/backup-postgres.sh` + `scripts/restore-postgres.sh` + `backup-vault.sh` + `restore-vault.sh` + `backup-restore-test.sh`; 9 DR scenarios in `docs/runbooks/disaster-recovery.md` | | Restore against a real production-like DB not exercised | |
| Operator flow E2E | | | Component-level tests exist for each surface | No end-to-end test that ties start → observe → pause → approve → resume → terminal → inspect artifacts/costs together |
| Replay-from-step | | Frontend has the disabled control with tooltip | | Backend endpoint to replay from a chosen step ID is not implemented |
| Keycloak SSO end-to-end | | 3-tier JWT auth code + JWKS cache; tests skip cleanly on `KEYCLOAK_TEST_URL` absent | | A high-fidelity OIDC contract test or Keycloak-backed CI test is not present |
| Vault integration (token/policy) | | Real `hvac` integration; KV-v2 + PKI + Transit + AppRole; in-memory TTL cache | | Live token/policy/path contract test not exercised in CI |
| CI security-scan severity threshold | | `safety check ... \|\| true` exists in `.github/workflows/ci.yml` | | Binding severity threshold and explicit allowed-exception list not configured — operator policy decision |
| Frontend bundle code-splitting | | Single 1.6 MB bundle | | Operator decision (target <500 KB initial) |
| SQLModel `session.execute()` → `session.exec()` migration | | Cosmetic deprecation warnings remain | | Operator decision — not blocking |
| 10 stub-blocked node executors (remaining after 10 BETA promotions) | | `_stub_block.assert_node_runnable` blocks them in production | | Real implementations for: `vectorSearchNode`, `documentLoaderNode`, `streamOutputNode`, `functionCallNode`, `toolNode`, `mcpToolNode`, `databaseQueryNode`, `humanInputNode`, `loopNode` (production loop body subgraph), `dlpScanNode` (production promotion path) |
| OPA policy engine | | | Substrate chosen: `ARCHON_ENTERPRISE_STRICT_TENANT` + audit chain + budget gates | OPA wiring — operator decision, out of scope this cycle |
| Multi-SKIP-LOCKED (Postgres) | | SQL is correct but only tested against SQLite | | No load test beyond 100-task chaos drain |
| Python/TypeScript SDK | | | | REST/JSON only for now — deferred |
| Multi-node cluster replication | | | | Deferred |
| Sub-50ms task claim latency proof | | | | No load test at target scale |

## What "proven locally" means here

A claim is **proven locally** only if all three are true:

1. There is a test or canary that exercises the production path (not just an isolated unit).
2. The acceptance command exits 0 in the current workspace.
3. The proof does not depend on a special environment variable that is not the documented production default (exception: `ARCHON_DISPATCH_INLINE=0` is explicitly set by the worker canary to prove the non-inline path).

## What "implemented but not production-proven" means

Code and isolated tests exist, but no live or end-to-end product proof has been run in this workspace. These are honest gaps — the feature is present but its production-path behavior under real conditions has not been exercised.

## What "configured / awaiting real CI proof" means

The relevant infrastructure or integration is present and statically valid, but the test or CI gate that would exercise it against a real external service has not been run. No structural enforcement makes these mandatory before merge.

## R3 evidence — gate commands and results

```
# Feature matrix (RC=1 — 4 pipeline executor files missing from feature-matrix.yaml)
$ python3 scripts/check-feature-matrix.py 2>&1 | tail -5
  W: infra_services id=prometheus_config: status=production but test_files is empty
[errors]
  E: node_executors: executor files not referenced by any entry: ['pipeline_artifact', 'pipeline_cancel', 'pipeline_start', 'pipeline_wait']
EXIT: 1

# ExecutionFacade bypass gate GREEN
$ bash scripts/check-direct-run-bypasses.sh
OK: no direct WorkflowRun construction outside ExecutionFacade

# Vendor reference scrub GREEN
$ bash scripts/check-vendor-refs.sh
OK: no unallowed vendor references

# Alembic single head — 0018
$ cd backend && PYTHONPATH=. .venv/bin/python -m alembic heads
0018_add_visibility_index (head)
```

All four gates captured on 2026-04-30 in this workspace.

## Citations

Every row in the truth table cites a file path or command output. The authoritative supporting documents are:

- `P0-DELTA.md` (2026-04-30) — Wave-0 worker status: P0-A (background dispatch failure) DONE, P0-B (non-inline canary) PARTIAL (not a CI hard gate), P0-C (frontend routes) DONE, P0-D (schema/ADR freeze) DONE, P0-E (bypass gate) resolved GREEN.
- `REMEDIATION_REPORT.md` — Round-1 remediation; Gate B inline-dispatch proof.
- `REMEDIATION_REPORT_R2.md` — Round-2 remediation; worker canary, background dispatch failure, frontend routes.
- `tests/integration/test_vertical_slice.py` — inline-dispatch REST canary.
- `tests/integration/test_worker_canary.py` — non-inline worker canary (3/3) + failure-finalisation companion.
- `backend/tests/test_dispatch_runtime_failure.py` — 7-test failure-persistence bundle.
- `backend/app/services/dispatch_runtime.py` — `_persist_failed_run`, `schedule_dispatch`, `drain_tracked_tasks`.
- `backend/app/services/activity_runtime.py` — activity runtime with heartbeat, cancel, retry, artifact, legacy adapter.
- `backend/app/services/task_queue_service.py` — task queue service.
- `backend/app/services/worker_registry.py` — worker registry with heartbeat + stale sweep.
- `backend/app/services/run_dispatcher.py` — task-queue polling + legacy fallback.
- `backend/app/routes/executions.py`, `backend/app/routes/agents.py` — routes calling `ExecutionFacade.create_run`.
- `backend/app/services/execution_facade.py` — single REST entry point.
- `backend/app/services/idempotency_service.py` — partial unique index + 200/201/409 semantics.
- `backend/app/services/workflow_engine.py` — ADR-003 hint envelope routing.
- `backend/app/services/node_executors/_stub_block.py` + `status_registry.py` — production stub-block enforcement.
- `backend/app/models/task_queue.py`, `backend/app/models/activity.py` — new durable orchestration models.
- `backend/alembic/versions/0012_add_task_queue_and_task.py` through `0018_add_visibility_index.py` — durable schema migrations.
- `frontend/src/App.tsx` — route registration source of truth (all 4 pages registered at lines 11–14, 71–74).
- `docs/adr/orchestration/ADR-001..008.md` — binding decisions.
- `docs/feature-matrix.yaml` + `scripts/check-feature-matrix.py` — feature inventory (RC=1, 4 pipeline executor entries missing).
- `scripts/check-frontend-backend-parity.py` — parity drift gate.
- `scripts/check-direct-run-bypasses.sh` — bypass detection gate (GREEN).
- `scripts/check-vendor-refs.sh` — vendor reference gate (GREEN).
- `scripts/verify-slice.sh` + `scripts/test-slice.sh` — REST canary scripts (export `ARCHON_DISPATCH_INLINE=1`).
- `scripts/test-worker-canary.sh` — non-inline worker canary script.
- `.github/workflows/ci.yml` — verify-slice job sets `ARCHON_DISPATCH_INLINE: '1'`; worker canary not yet a CI hard gate; security-scan job retains `safety check ... || true`.
