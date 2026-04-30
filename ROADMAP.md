# Archon — Roadmap

**Status:** Pre-1.0. Evidence-backed phase ledger.
**Last updated:** 2026-04-29
**Authoritative reports:** [`CURRENT_STATE.md`](CURRENT_STATE.md) (canonical truth-table), [`REMEDIATION_REPORT.md`](REMEDIATION_REPORT.md) (2026-04-29 corrective action), [`PHASE_0_9_EXECUTION_REPORT.md`](PHASE_0_9_EXECUTION_REPORT.md) (historical narrative with reconciliation note), [`PHASE_0_3_EXECUTION_REPORT.md`](PHASE_0_3_EXECUTION_REPORT.md) (mid-cycle snapshot), [`RE_EVALUATION_CYCLE_REPORT.md`](RE_EVALUATION_CYCLE_REPORT.md), [`RE_EVALUATION_REPORT.md`](RE_EVALUATION_REPORT.md)

> Each phase below is closed by passing tests, an ADR (where applicable), and a verification gate run by an independent reviewer. Phases without verifier sign-off are marked **NEXT** or **DEFERRED**, never "complete." The phrase "production ready" does not appear in this document.

## Current state (2026-04-29)

This section supersedes any earlier "all phases complete" claim. The canonical authority is [`CURRENT_STATE.md`](CURRENT_STATE.md) — the truth-table that classifies every item as proven / script-green only / implemented-but-unproven / missing / deferred.

**Done under the script/CI contract:**

- ADRs (1–7) — orchestration ([`docs/adr/orchestration/`](docs/adr/orchestration/))
- Feature matrix + 28-node frontend ↔ backend parity
- Compose: vault + worker
- Canonical execution model (`WorkflowRun`, `WorkflowRunStep`, `WorkflowRunEvent`, hash-chained events)
- `ExecutionFacade` + REST unification + idempotency contract (ADR-004)
- Dispatcher claim/persist; worker leases + drain; events API + WS replay
- Postgres checkpointer fail-closed (ADR-005); durable timers + retry policy; approvals + signals; cancellation hooks
- Node honesty (status registry; stub-block enforcement; ADR-003 hint envelope; per-node contract tests; frontend parity)
- Tenant context (sqlite + Postgres-skipped); cost gate fail-closed (production/staging mode); audit hash chain; route permission matrix; model routing + circuit breaker
- Canonical metrics + tracing wrappers + artifacts + Grafana dashboards + alerts
- Quotas + chaos suite + load profiles + worker scaling proofs
- Frontend pages: `RunHistoryPage`, `ExecutionDetailPage`, `ApprovalsPage`, `ArtifactsPage` (plus components and tests)
- Helm chart with production overrides; backup/restore + DR runbooks
- Documentation truth pass

**Blocked / not yet hard gates:**

- Non-inline worker dispatch end-to-end canary in CI (P0 — currently green only with `ARCHON_DISPATCH_INLINE=1`)
- Background dispatch failure → run.failed terminal state (P0)
- Stale xfail / xpass metadata cleanup (P0 — `TestVerticalSliceIdempotency` is XPASS; `TestVerticalSliceCancel` remains an honest XFAIL)
- Postgres RLS in mandatory CI service (P2 — currently env-gated behind `ARCHON_TEST_POSTGRES_URL`)
- Keycloak/OIDC end-to-end CI test (P2 — currently env-gated behind `KEYCLOAK_TEST_URL`)
- Vault token/policy contract test (P2)
- Helm template + cluster smoke in CI (P2 — kind/minikube deploy proof not exercised)
- CI security-scan severity threshold (P2 — Conflict 21; `safety check ... \|\| true` remains advisory)
- Frontend page reachability via `App.tsx` routes for `RunHistoryPage`, `ApprovalsPage`, `ArtifactsPage` (P3 — one-line addition each; only `ExecutionDetailPage` is currently registered)
- Operator-flow E2E test (P3 — start → observe → pause → approve → resume → terminal → inspect artifacts/costs as one connected scenario)
- Live metrics emission proof against running workflow (P3 — Prometheus scrape with non-zero series)
- Replay-from-step backend (P3 — frontend has the disabled control with tooltip; no backend endpoint)

See [`CURRENT_STATE.md`](CURRENT_STATE.md) for the canonical truth-table.

---

## Heat-map

| Phase | Theme | State | Verifier gate (script/CI contract) | Notes |
|-------|-------|-------|------------------------------------|-------|
| **A** | Kernel + execution substrate | DONE (script-green under inline dispatch) | Gate B — V2 PASS | Non-inline worker canary still missing — see P0 |
| **B** | Durability semantics | DONE | Gate C — V3 PASS | Cancel propagation has a known race; `TestVerticalSliceCancel` is honestly XFAIL |
| **C** | Node honesty | DONE | Gate D — V4 PASS | 12 stubs blocked in production via `_stub_block.py`; 14 stub executors await real implementations |
| **D** | Enterprise governance | DONE (sqlite app-layer) | Phase 4 verifiers | Postgres RLS + Keycloak + Vault contract tests not mandatory in CI — see P2 |
| **E** | Observability | DONE (catalog + dashboards + alerts) | Phase 5 verifiers | Live Prometheus scrape against a real run not validated — see P3 |
| **F** | Scale + chaos | DONE | Phase 6 verifiers | All under `ARCHON_DISPATCH_INLINE=1`; multi-process worker drain end-to-end not exercised |
| **G** | Operator UX | DONE (component-level) | Phase 7 verifiers | `RunHistoryPage` / `ApprovalsPage` / `ArtifactsPage` not in `App.tsx` — see P3 |
| **H** | Deploy + ops | DONE (templates parse + scripts validated) | Phase 8 verifiers | `helm install` against kind/minikube not exercised — see P2 |
| **I** | Production hardening | NEXT | — | See plan §P0–§P3 below and `CURRENT_STATE.md` |

---

## Phase A — Kernel + execution substrate (DONE)

> Goal: One canonical run path. REST → durable WorkflowRun → step rows → hash-chained event log → terminal status. No `_simulate_execution`.

**ADRs accepted:** [ADR-001](docs/adr/orchestration/ADR-001-agent-vs-workflow-execution.md), [ADR-002](docs/adr/orchestration/ADR-002-event-ownership.md), [ADR-004](docs/adr/orchestration/ADR-004-idempotency-contract.md), [ADR-006](docs/adr/orchestration/ADR-006-execution-migration.md), [ADR-007](docs/adr/orchestration/ADR-007-workflow-deletion-semantics.md)

**What landed:**
- `WorkflowRun` (29 columns) — unified run record for workflow XOR agent execution; XOR CHECK enforced.
- `WorkflowRunStep` (23 columns) — per-step state with `attempt`, `retry_count`, `token_usage`, `cost_usd`, `worker_id`.
- `WorkflowRunEvent` — sha256 hash-chained event log, 15-type CHECK constraint, replay support.
- `ExecutionFacade` ([`backend/app/services/execution_facade.py`](backend/app/services/execution_facade.py)) — single entry point for REST; resolves `agent_id` vs `workflow_id` XOR; stamps idempotency.
- `IdempotencyService` — partial unique index + 200/201/409 semantics per ADR-004.
- `RunDispatcher` ([`backend/app/services/run_dispatcher.py`](backend/app/services/run_dispatcher.py)) — claim → persist → emit → terminal.
- Worker leasing — `lease_owner` / `lease_expires_at` + `claim_run` / `renew_lease` / `release_lease` / `reclaim_expired_runs`.
- REST events API — `GET /api/v1/runs/{run_id}/events`, WebSocket replay.

**Tests:** 68 added — facade 19, dispatcher 16, worker 15, events 16, vertical slice 2.

**Verification:** Gate B (V2, Sonnet 4.6) — PASS. Vertical slice REST canary now drives `POST /api/v1/executions` → durable `WorkflowRun` → terminal.

---

## Phase B — Durability semantics (DONE)

> Goal: A workflow that pauses survives a worker restart. A retry actually retries. A cancel actually stops.

**ADR accepted:** [ADR-005](docs/adr/orchestration/ADR-005-production-durability-policy.md)

**What landed:**
- `LangGraph` Postgres checkpointer fail-closed — `CheckpointerDurabilityFailed` raised in production; `MemorySaver` rejected.
- [`backend/app/startup_checks.py`](backend/app/startup_checks.py) — production startup aborts on dev JWT secret, `sqlite`, `MemorySaver`, `AUTH_DEV_MODE=true`, `LANGGRAPH_CHECKPOINTING=disabled`, `ARCHON_ENTERPRISE_STRICT_TENANT=false`. See [`docs/PRODUCTION_CONFIG.md`](docs/PRODUCTION_CONFIG.md).
- Durable timers — `Timer` model + `timer_service` + worker timer-fire loop. `delayNode` schedules long delays via Timer, not in-process `asyncio.sleep`.
- `RetryPolicy` dataclass + dispatcher integration — exponential backoff, `step.retry` events.
- Approvals — typed `Approval` + `Signal` models + REST endpoints; `humanApprovalNode` writes through the model, not raw SQL.
- Cancellation — `cancel_requested_at` + dispatcher pre-step check + signal-driven resume.
- Pause/resume — `request_approval` / `grant_approval` / signal-driven resume end-to-end.
- Event hash chain — `sha256(prev_hash || canonical_json(envelope))` with verify endpoint and tamper detection.

**Tests:** 89 added + 1 Postgres-required skip — checkpointer 22, startup 11, timers 13, retry 16, approvals 12, signals 5, dispatcher integration 13, cancel 3, pause/resume 5.

**Verification:** Gate C (V3, Sonnet 4.6) — PASS.

---

## Phase C — Node honesty (DONE)

> Goal: The visual builder cannot draw a workflow that lies about what it does. Stubs return `step.failed` with `error_code="stub_blocked_in_production"` in production / staging.

**ADR accepted:** [ADR-003](docs/adr/orchestration/ADR-003-branch-fanin-semantics.md)

**What landed:**
- [`status_registry.py`](backend/app/services/node_executors/status_registry.py) + `_stub_block.py` — every executor declares its status; dispatcher gates `stub` executors in production / staging.
- 12 stub-blocked executors: `loopNode`, `humanInputNode`, `mcpToolNode`, `toolNode`, `databaseQueryNode`, `functionCallNode`, `embeddingNode`, `vectorSearchNode`, `documentLoaderNode`, `visionNode`, `structuredOutputNode`, `streamOutputNode`.
- Branch-aware engine — `condition`, `switch`, `parallel(all|any|n_of_m)`, `merge`, `loop` semantics in [`workflow_engine.py`](backend/app/services/workflow_engine.py); executors emit hint envelopes; engine routes per ADR-003.
- Per-node contract tests — 12 new files in `backend/tests/test_node_executors/`.
- Frontend ↔ backend type parity — [`frontend/src/types/nodes.ts`](frontend/src/types/nodes.ts), `workflow_run.ts`, `events.ts`. `scripts/check-frontend-backend-parity.py` enforces drift detection.

**Tests:** 313 added — status 38, engine 18, contracts 225, frontend 32.

**Verification:** Gate D (V4, Sonnet 4.6) — PASS.

**Authoritative inventory:** [`docs/feature-matrix.yaml`](docs/feature-matrix.yaml) — 206 entries, of which production=95, beta=79, stub=13, designed=4, missing=15.

---

## Phase D — Enterprise governance (DONE)

> Goal: Multi-tenant isolation that actually isolates. Audit trail that detects tampering. Cost gates that fail closed in enterprise mode.

**What landed:**
- **Tenant isolation** — `ARCHON_ENTERPRISE_STRICT_TENANT` startup gate; tenant context propagation through dispatcher; partial unique idempotency index is `(tenant_id, idempotency_key)`. See [ADR-012](docs/adr/012-tenant-isolation.md).
- **Audit hash chain** — `audit_chain.py` service; verify endpoint detects tampering; tied to event hash chain from Phase A.
- **Vault** — KV-v2 + PKI cert issuance + dynamic credentials + namespace-per-tenant; in-memory TTL cache; graceful fallback. The strongest enterprise component in the codebase. See [ADR-010](docs/adr/010-secrets-management.md).
- **Auth** — 3-tier JWT validation (HS256 dev, RS256 Keycloak via JWKS, RS256 Azure Entra via OIDC); JWKS cache 1h TTL; dev bypass requires explicit opt-in. See [ADR-011](docs/adr/011-auth-flows.md).
- **DLP** — Presidio integration with regex fallback. Default action is `flag` outside enterprise; `block` inside. See [`backend/app/services/dlp_service.py`](backend/app/services/dlp_service.py).
- **Cost gate** — `costGateNode` with three fail-open paths in standard mode; full fail-closed in enterprise mode is the next planned gate (Conflict 6, partially closed).

**Deferred to Phase I:**
- OPA policy engine integration.
- RLS enforcement on Postgres for the full tenant isolation matrix.
- SCIM 2.0 user / group provisioning end-to-end.

---

## Phase E — Observability (DONE)

> Goal: Every emitted metric has a dashboard that queries it. Every dashboard panel queries an emitted metric. No dark dashboards.

**What landed:**
- [`docs/metrics-catalog.md`](docs/metrics-catalog.md) — canonical metric set; the contract between emitters and dashboards / alerts.
- [`scripts/check-grafana-metric-parity.py`](scripts/check-grafana-metric-parity.py) — CI gate that fails on metric drift.
- Run-level metrics: `archon_workflow_runs_total`, `archon_workflow_run_duration_seconds`, `archon_step_duration_seconds` — emitted from `run_dispatcher`.
- Cost metrics: `archon_token_usage_total`, `archon_cost_total` — emitted from `cost_service`.
- HTTP metrics: `archon_requests_total`, `archon_request_duration_seconds`, `archon_active_agents`, `archon_vault_status` — emitted by `MetricsMiddleware`.
- Grafana dashboards in `infra/grafana/dashboards/archon-*.json`. See [`docs/runbooks/observability.md`](docs/runbooks/observability.md).

---

## Phase F — Scale + chaos (DONE)

> Goal: Prove the kernel under pressure. Crash a worker mid-run. 429-storm an LLM. Lose Redis. Lose Postgres for 30s.

**What landed:**
- 5 load-test profiles (`make load`) — simple, fanout, llm, approval, retry. See [`docs/load-test-profiles.md`](docs/load-test-profiles.md).
- 4 chaos-test scenarios (`make chaos`) — worker crash mid-step, transient DB outage, 429 storm, Redis-down. See `scripts/run-chaos-tests.sh`.
- Worker concurrency cap honoured under load.
- Dispatcher idempotency holds at N=50 parallel POSTs (no double-execution).

---

## Phase G — Operator UX (DONE)

> Goal: When a workflow runs, the operator can see the steps as they execute, in real time, without crafting a curl loop.

**What landed:**
- Builder live stream — `TestRunPanel.tsx` connects WebSocket; renders step timeline + tokens + cost + cancel button.
- Executions detail page — connects to `/api/v1/runs/{run_id}/events` for hash-chained replay.
- Approval UI — pending approvals queue + grant / deny.
- Run history list with cursor pagination (frontend; pagination cursor returned by backend).

**Deferred to Phase I:**
- Frontend bundle code-splitting (current 1.6 MB → target <500 KB initial).
- Dashboard density polish.
- Mobile builder (3-screen stub remains; deferred indefinitely).

---

## Phase H — Deploy + ops (DONE)

> Goal: A second instance of Archon, in a fresh cluster, with one operator running one playbook.

**What landed:**
- Docker Compose — 8 services (postgres, redis, backend, worker, frontend, keycloak, vault, vault-init). `vault-init` is a one-shot service the backend depends on (`service_completed_successfully`). See [`docker-compose.yml`](docker-compose.yml).
- Helm umbrella chart — [`infra/helm/archon-platform/`](infra/helm/archon-platform).
- Vault Helm chart with idempotent init script — [`infra/helm/vault/vault-init.sh`](infra/helm/vault/vault-init.sh) (KV-v2 + Transit + PKI + AppRole).
- AWS Terraform module — VPC + EKS + RDS PG16 multi-AZ + ElastiCache + S3 with KMS — [`infra/terraform/aws/main.tf`](infra/terraform/aws/main.tf).
- Backup/restore — `scripts/backup-postgres.sh` + `scripts/restore-postgres.sh`.
- 5 verify gates — unit, integration, frontend, contracts, slice (`make verify`).

See [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md).

---

## Phase I — Production hardening (NEXT)

> Goal: Close the residual gaps before the 1.0 cut.

| Item | Severity | Owner |
|------|----------|-------|
| Cost gate fail-closed in enterprise mode (Conflict 6 closure) | High | Phase I-1 |
| RLS enforcement on Postgres + tenant isolation matrix tests | High | Phase I-1 |
| 14 stub node executors (embedding, vision, vector_search, document_loader, structured_output, function_call, tool, mcp_tool, etc.) | Medium | Phase I-2 |
| OPA policy engine integration | Medium | Phase I-3 |
| Real LLM smoke test against an `OPENAI_API_KEY`-gated CI job | Medium | Phase I-2 |
| Frontend bundle code-splitting + lazy loading | Low | Phase I-4 |
| Additional connectors (current: 5) | Low | Phase I-5 |
| Multi-cloud Terraform parity (Azure, GCP) | Low | Phase I-6 |
| ArgoCD application sync | Low | Phase I-6 |
| `dispatch_run` vs `Execution`/`WorkflowRun` legacy shim removal | Low | Phase I-1 |

See [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md) for the full remaining-work ledger.

---

## Out of scope (explicit decisions)

The following items are commonly requested but are **not** on the path to 1.0:

| Item | Why deferred |
|------|--------------|
| 50+ data connectors | Five real connectors (Postgres, S3, Slack, REST, Google Drive) are sufficient for 1.0; the catalog is a distraction until execution is hardened. |
| 200+ node types | The 28 registered executors are sufficient; the priority is honesty (12 stubs blocked in production) and completeness (14 stubs to implement), not surface area. |
| Full RAG pipeline (LlamaIndex / PGVector / Haystack / Unstructured) | Defer until execution substrate is durable. The advertised "RAG engine" was a zero-vector embed in prior cycles; it has been removed from the README. |
| Mobile builder / router / DLP screens | The mobile app is a 3-screen stub; not in scope for 1.0. |
| Federated agent mesh, edge runtime with sync, marketplace | Designed primitives only; not in scope for 1.0. |
| New agent frameworks (`.sdd`, `.claude-flow`, `.swarm`) | Tried in prior cycles; Claude Flow V3 ran zero tasks. The verdict: stop installing frameworks; ship code. |

---

## Reading order for new contributors

1. [`README.md`](README.md) — what works today, quickstart, links.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the seven bounded contexts.
3. [`docs/STATE_MACHINE.md`](docs/STATE_MACHINE.md) — `WorkflowRun` lifecycle.
4. [`docs/PRODUCTION_CONFIG.md`](docs/PRODUCTION_CONFIG.md) — every `ARCHON_*` env var.
5. [`docs/feature-matrix.yaml`](docs/feature-matrix.yaml) — what's `production` / `beta` / `stub` / `designed` / `missing`, with file paths.
6. [`docs/adr/orchestration/`](docs/adr/orchestration/) — the seven binding ADRs.
7. [`docs/GAP_ANALYSIS.md`](docs/GAP_ANALYSIS.md) — the residual ledger.
