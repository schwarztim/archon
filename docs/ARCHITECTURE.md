# Archon — Architecture

**Status:** Pre-1.0. Reflects state at 2026-04-29 (post Phase 0–8 verification).
**Authority:** This document tells you the bounded contexts, what's in each, and which ADRs govern them. Concrete inventories live in [`docs/feature-matrix.yaml`](feature-matrix.yaml).

> The previous architecture document advertised "OpenLLMetry," "NeMo Guardrails," "200+ nodes," "50+ connectors," and "PostgreSQL + LlamaIndex + Haystack + Unstructured." None of those were imported anywhere. They have been removed. This document only describes what `import` statements prove exists.

## 1. Bounded contexts

Archon decomposes into **seven** bounded contexts. Each owns its own data, its own boundary, and a small surface of integration points.

```
┌──────────────────────────────────────────────────────────────────┐
│                       1. CONTROL PLANE                           │
│  REST API + Auth + Tenant context + Idempotency + ExecutionFacade│
└─────────────────────────────────┬────────────────────────────────┘
                                  │  enqueue WorkflowRun(pending)
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│        2. DURABLE ORCHESTRATION KERNEL (the spine)               │
│  RunDispatcher · Lease · WorkflowRun · WorkflowRunStep ·         │
│  WorkflowRunEvent (hash-chained) · LangGraph PostgresSaver       │
│  Timer · RetryPolicy · Approval · Signal                         │
└─────────────────┬────────────────────────────┬───────────────────┘
                  │ claim / heartbeat          │ checkpoint
                  ▼                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                  3. WORKER PLANE                                 │
│  worker.py — 5 concurrent loops: heartbeat 10s · drain 5s ·      │
│  reclaim 30s · timer-fire 5s · slow 300s                         │
└─────────────────────────────────┬────────────────────────────────┘
                                  │ dispatch step
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                  4. ACTIVITY LAYER                               │
│  28 NodeExecutors registered via @register("...")                │
│  Stub-block gate: status="stub" → step.failed in prod/staging    │
└────────────┬───────────────────────────────────┬─────────────────┘
             │ call_llm()                        │ scan/policy
             ▼                                   ▼
┌──────────────────────────┐    ┌───────────────────────────────────┐
│ 5. AI POLICY / ROUTING   │    │   6. VISIBILITY                  │
│ litellm · router_service │    │   /metrics · WS events ·         │
│ provider scoring · cost  │    │   audit hash chain · /events     │
└──────────────────────────┘    └───────────────────────────────────┘
                                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                  7. ENTERPRISE OPS                               │
│  Vault (KV-v2 + PKI + Transit) · Keycloak/Entra OIDC · DLP ·    │
│  Tenant strict mode · Backup/restore · Helm umbrella · Terraform │
└──────────────────────────────────────────────────────────────────┘
```

### 1.1 Control plane

**Owns:** [`backend/app/routes/`](../backend/app/routes/), [`backend/app/middleware/`](../backend/app/middleware/), [`backend/app/services/execution_facade.py`](../backend/app/services/execution_facade.py), [`backend/app/services/idempotency_service.py`](../backend/app/services/idempotency_service.py).

**Surface:** FastAPI 0.115+ app at `:8000`. Versioned under `/api/v1/`. WebSocket endpoints under `/ws/`.

**Responsibilities:**
- Authenticate the caller (3-tier JWT — HS256 dev / RS256 Keycloak via JWKS / RS256 Azure Entra via OIDC).
- Resolve tenant context (`middleware/tenant.py`).
- Stamp idempotency key on writes (header `X-Idempotency-Key`; semantics per [ADR-004](adr/orchestration/ADR-004-idempotency-contract.md)).
- Hand off to `ExecutionFacade.create_run()` — the single entry point that resolves agent vs workflow XOR ([ADR-001](adr/orchestration/ADR-001-agent-vs-workflow-execution.md)) and writes a durable `WorkflowRun(status="pending")`.

**What does NOT live here:** Step execution, branching logic, retries, LLM calls. Those are in the kernel + activity layer.

### 1.2 Durable orchestration kernel

**Owns:** [`backend/app/models/workflow.py`](../backend/app/models/workflow.py), [`backend/app/services/run_dispatcher.py`](../backend/app/services/run_dispatcher.py), [`backend/app/services/run_lifecycle.py`](../backend/app/services/run_lifecycle.py), [`backend/app/services/event_service.py`](../backend/app/services/event_service.py), [`backend/app/services/timer_service.py`](../backend/app/services/timer_service.py), [`backend/app/services/retry_policy.py`](../backend/app/services/retry_policy.py), [`backend/app/services/approval_service.py`](../backend/app/services/approval_service.py), [`backend/app/services/signal_service.py`](../backend/app/services/signal_service.py), [`backend/app/services/worker_registry.py`](../backend/app/services/worker_registry.py), [`backend/app/langgraph/checkpointer.py`](../backend/app/langgraph/checkpointer.py).

**Surface:** Internal Python API. The dispatcher is the only thing that mutates `WorkflowRun.status`.

**Tables:**
- `workflow_runs` — 29 columns. Single XOR target (`workflow_id` OR `agent_id`). Lease columns. Idempotency columns. Status timeline (`queued_at`, `claimed_at`, `started_at`, `paused_at`, `resumed_at`, `cancel_requested_at`, `completed_at`).
- `workflow_run_steps` — 23 columns. Per-step status, `attempt`, `retry_count`, `token_usage`, `cost_usd`, `worker_id`.
- `workflow_run_events` — append-only. 15 valid `type` values per [ADR-002](adr/orchestration/ADR-002-event-ownership.md). Each row's `hash` is `sha256(prev_hash || canonical_json(envelope))`.
- `timers` — durable scheduled wakeups.
- `approvals`, `signals` — pause / resume substrate.
- `worker_registry` — heartbeating workers + concurrency caps.

**ADR coverage:**
| ADR | Topic |
|-----|-------|
| [ADR-001](adr/orchestration/ADR-001-agent-vs-workflow-execution.md) | Single run table; XOR check on `(workflow_id, agent_id)`. |
| [ADR-002](adr/orchestration/ADR-002-event-ownership.md) | Event ownership; the dispatcher owns terminal events; executors emit step events via `event_service.append`. |
| [ADR-003](adr/orchestration/ADR-003-branch-fanin-semantics.md) | Branch routing (condition / switch); fan-out + fan-in (parallel `all`/`any`/`n_of_m`). |
| [ADR-004](adr/orchestration/ADR-004-idempotency-contract.md) | `X-Idempotency-Key` precedence; partial unique index `(tenant_id, idempotency_key)`; 200/201/409 semantics. |
| [ADR-005](adr/orchestration/ADR-005-production-durability-policy.md) | Postgres checkpointer fail-closed in production / staging. |
| [ADR-006](adr/orchestration/ADR-006-execution-migration.md) | `Execution` → `WorkflowRun` projection for backwards compatibility. |
| [ADR-007](adr/orchestration/ADR-007-workflow-deletion-semantics.md) | `workflow_id` is `nullable=True`, `ondelete=SET NULL` — runs survive workflow deletion. |

### 1.3 Worker plane

**Owns:** [`backend/app/worker.py`](../backend/app/worker.py).

**Surface:** A standalone process started by `python -m app.worker`. Containerized via [`backend/Dockerfile.worker`](../backend/Dockerfile.worker).

**Five concurrent loops:**

| Loop | Cadence | Purpose |
|------|---------|---------|
| `heartbeat` | 10s | Refresh `worker_registry` heartbeat; advertise concurrency capacity. |
| `drain` | 5s | Pick up `WorkflowRun(status="pending")`, claim a lease, dispatch via `run_dispatcher.dispatch_run`. |
| `reclaim` | 30s | Find runs whose `lease_expires_at` is past; reset to pending so another worker can claim. |
| `timer_fire` | 5s | Fire durable timers whose `fire_at` is past; resume their owning run. |
| `slow` | 300s | Cron evaluation, scheduled-trigger dispatch, budget alerts, audit chain checkpoint. |

**Concurrency:** `ARCHON_WORKER_CONCURRENCY` (default 4). The dispatcher acquires a semaphore before each step so the worker honours its declared cap.

### 1.4 Activity layer

**Owns:** [`backend/app/services/node_executors/`](../backend/app/services/node_executors/) — 28 modules.

**Registry:** `NODE_EXECUTORS: dict[str, NodeExecutor]` populated by the `@register("nodeType")` decorator at import time.

**Status registry** (per [`status_registry.py`](../backend/app/services/node_executors/status_registry.py)):

| Status | Behaviour | Examples |
|--------|-----------|----------|
| `production` | Wired end-to-end; safe in enterprise mode. | `llmNode`, `inputNode`, `outputNode` |
| `beta` | Code exists; partial proof; see [`feature-matrix.yaml`](feature-matrix.yaml) `gap` field. | `conditionNode`, `switchNode`, `parallelNode`, `httpRequestNode`, `costGateNode`, `dlpScanNode`, `delayNode`, `humanApprovalNode`, `mergeNode`, `subAgentNode`, `subWorkflowNode`, `webhookTriggerNode`, `scheduleTriggerNode` |
| `stub` | Returns success without doing real work; **must be blocked in production / staging** by `_stub_block.py`. | `loopNode`, `humanInputNode`, `mcpToolNode`, `toolNode`, `databaseQueryNode`, `functionCallNode`, `embeddingNode`, `vectorSearchNode`, `documentLoaderNode`, `visionNode`, `structuredOutputNode`, `streamOutputNode` |

**Stub-block enforcement:** When a step's `type` resolves to a `stub` executor and `ARCHON_ENV in {production, staging}`, the dispatcher emits `step.failed` with `error_code="stub_blocked_in_production"` instead of running the executor. This is a structural truth gate — the visual builder cannot draw a workflow that lies about what it does.

### 1.5 AI policy / routing

**Owns:** [`backend/app/langgraph/llm.py`](../backend/app/langgraph/llm.py), [`backend/app/services/router_service.py`](../backend/app/services/router_service.py), [`backend/app/services/cost_service.py`](../backend/app/services/cost_service.py).

**LLM gateway:** A single `call_llm(prompt, model, **opts)` function in `langgraph/llm.py` wraps `litellm.acompletion`. Returns `LLMResponse(content, prompt_tokens, completion_tokens, total_tokens, cost_usd, model_used, latency_ms)`. `LLM_STUB_MODE=true` produces deterministic 30-token stub responses for tests.

**Router:** DB-backed model registry. Classification + capability + geo filtering. Circuit breaker. Real Azure OpenAI HTTP calls with 429-aware retry. The router's scoring API is callable but the auto-selection path is opt-in — `llmNode` defaults to the configured model unless the `routing_rule_id` is set.

**Cost service:** Records usage per step (`record_usage`); aggregates per-tenant running totals (`tenant_running_total`); summarizes (`cost_summary`). Reads token counts from the `LLMResponse` (no `random.*`).

### 1.6 Visibility

**Owns:** [`backend/app/middleware/metrics_middleware.py`](../backend/app/middleware/metrics_middleware.py), [`backend/app/routes/events.py`](../backend/app/routes/events.py), [`backend/app/websocket/events_manager.py`](../backend/app/websocket/events_manager.py), [`backend/app/services/audit_chain.py`](../backend/app/services/audit_chain.py).

**Surfaces:**
- `GET /metrics` — Prometheus scrape. Metrics catalogued in [`docs/metrics-catalog.md`](metrics-catalog.md). CI gate `scripts/check-grafana-metric-parity.py` rejects drift.
- `GET /api/v1/runs/{run_id}/events` — paged event log.
- `GET /api/v1/runs/{run_id}/events/verify` — verify hash chain integrity.
- WebSocket `/ws/runs/{run_id}` — live stream + replay (24h TTL, 500-entry cap).
- Grafana dashboards in `infra/grafana/dashboards/archon-*.json`.

### 1.7 Enterprise ops

**Owns:** [`backend/app/secrets/manager.py`](../backend/app/secrets/manager.py), [`backend/app/middleware/auth.py`](../backend/app/middleware/auth.py), [`backend/app/middleware/rbac.py`](../backend/app/middleware/rbac.py), [`backend/app/middleware/tenant.py`](../backend/app/middleware/tenant.py), [`backend/app/services/dlp_service.py`](../backend/app/services/dlp_service.py), [`backend/app/startup_checks.py`](../backend/app/startup_checks.py), [`infra/`](../infra/).

**Surfaces:**
- Vault — `hvac` client; KV-v2 + PKI + Transit + AppRole; namespace-per-tenant.
- Keycloak / Azure Entra OIDC — JWT verification with JWKS caching.
- DLP — Presidio integration with regex fallback. Default action `flag`; `block` in enterprise mode.
- Startup gates — see [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md).
- Backup / restore — `scripts/backup-postgres.sh` + `scripts/restore-postgres.sh`.
- Deploy — Docker Compose (8 services), Helm umbrella `infra/helm/archon-platform/`, AWS Terraform `infra/terraform/aws/main.tf`.

---

## 2. Lifecycle diagram (text)

```
                           ┌────────────┐
                           │   pending  │   queued_at set
                           └──────┬─────┘
                                  │ worker.drain claims a lease
                                  ▼
                           ┌────────────┐
                           │   queued   │   (transient — only emitted as event)
                           └──────┬─────┘
                                  │ dispatcher.claim_run sets lease_owner
                                  ▼
                           ┌────────────┐
                           │  claimed   │   claimed_at set, lease_expires_at set
                           └──────┬─────┘
                                  │ dispatcher.advance_step starts
                                  ▼
                ┌──────────────────────────────────┐
                │           running                │
                │ for each step in graph:          │
                │   - check cancel_requested_at    │
                │   - dispatch executor (status    │
                │     gated; stubs blocked in prod)│
                │   - persist WorkflowRunStep      │
                │   - emit step.completed event    │
                │   - on failure → retry policy    │
                │   - on pause → approval service  │
                │   - on timer → timer service     │
                └────┬──────────┬──────────┬───────┘
                     │          │          │
                     │ all      │ pause    │ cancel_requested_at set
                     │ steps    │ requested│
                     │ complete │          │
                     ▼          ▼          ▼
              ┌──────────┐ ┌───────┐ ┌───────────┐
              │completed │ │paused │ │cancelled  │
              └──────────┘ └───┬───┘ └───────────┘
                                │ approval granted /
                                │ signal received
                                ▼
                            (back to running, resumed_at set)

                           ┌────────────┐
                           │   failed   │   error_code, error set
                           └────────────┘
```

For the canonical state machine including retry transitions and lease reclaim, see [`docs/STATE_MACHINE.md`](STATE_MACHINE.md).

---

## 3. Dispatcher control flow (text)

```
RunDispatcher.dispatch_run(run_id):
  run = load WorkflowRun(run_id)
  if run.status not in {pending, queued, claimed}: return  # idempotent
  graph = load definition_snapshot
  for step in topological_order(graph):
    if cancel_requested_at: emit run.cancelled, persist, return
    if signal received: pause, persist, return
    executor = NODE_EXECUTORS[step.type]
    if executor.status == "stub" and ARCHON_ENV in {production, staging}:
      emit step.failed (error_code=stub_blocked_in_production)
      continue
    result = await executor.execute(NodeContext(...))
    persist WorkflowRunStep
    emit step.<status> event
    if result.status == "failed" and retry_policy:
      schedule retry, update step.attempt
    if result.status == "paused":
      request_approval, persist run.paused
      return
  emit run.completed (or run.failed if any terminal step failed)
  release_lease
```

The dispatcher is the **only** mutator of `WorkflowRun.status`. The executors emit results; the dispatcher decides terminal status.

---

## 4. Worker loop architecture (text)

```
worker.py:
  await run_startup_checks()    # ADR-005 fail-closed gate
  asyncio.gather(
    heartbeat_loop(10s),        # write to worker_registry
    drain_loop(5s),              # claim pending runs, dispatch
    reclaim_loop(30s),           # reset expired leases to pending
    timer_fire_loop(5s),         # fire due timers, signal owning run
    slow_loop(300s),             # cron, budget, audit chain
  )
```

Two replicas of `worker` running together do NOT double-dispatch. The dispatcher's `claim_run` uses an optimistic lock on `lease_owner` — only the first claim wins.

---

## 5. Frontend → Backend wiring

The visual builder ([`frontend/src/components/builder/`](../frontend/src/components/builder/)) draws workflows. The "Test Run" panel ([`TestRunPanel.tsx`](../frontend/src/components/builder/TestRunPanel.tsx)) issues a `POST /api/v1/executions` and connects to the WebSocket. The detail page ([`ExecutionDetailPage.tsx`](../frontend/src/pages/ExecutionDetailPage.tsx)) issues `GET /api/v1/runs/{id}/events` for hash-chained replay.

**Type parity** is enforced by [`scripts/check-frontend-backend-parity.py`](../scripts/check-frontend-backend-parity.py) — Pydantic / SQLModel schemas in `backend/app/models/` must match TypeScript declarations in [`frontend/src/types/`](../frontend/src/types/). CI gate `verify-contracts` runs the check.

---

## 6. What is NOT in the architecture

These items are referenced in older docs (now archived) but **do not exist** as code:

| Claim | Reality |
|-------|---------|
| OpenLLMetry | Not imported. Not in requirements.txt. |
| NeMo Guardrails | Not integrated. Gateway has rate-limit + input validation + audit; no Guardrails AI / NeMo library. |
| LiteLLM cross-provider gateway | The wrapper exists in `langgraph/llm.py`. The "gateway" framing was overclaimed. |
| 200+ node types | 28 registered. |
| 50+ data connectors | 5 reference connectors (Postgres, S3, Slack, REST, Google Drive). |
| 17 specialized agents | The "17 agents" were documentation, not code. |
| LlamaIndex / PGVector / Haystack / Unstructured RAG pipeline | Not imported. The prior `embed()` returned `[[0.0] * 384 for _ in chunks]`. The endpoint has been removed. |
| Celery | Declared in requirements; never imported. The "background jobs" claim is satisfied by the worker's asyncio loops. |
| Federated agent mesh, edge runtime with sync, marketplace | Designed primitives only; no implementation. |

---

## 7. Cross-references

- [`README.md`](../README.md) — surface description for new operators.
- [`docs/STATE_MACHINE.md`](STATE_MACHINE.md) — `WorkflowRun` lifecycle.
- [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md) — every `ARCHON_*` env var.
- [`docs/feature-matrix.yaml`](feature-matrix.yaml) — what's `production` / `beta` / `stub`.
- [`docs/FEATURE_MAPPING.md`](FEATURE_MAPPING.md) — feature → code → tests → docs map.
- [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md) — residual ledger.
- [`docs/DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) — dev / staging / production deploy.
- [`docs/CONTRIBUTING.md`](CONTRIBUTING.md) — branch strategy, PR gates, definition of done.
- [`docs/adr/orchestration/`](adr/orchestration/) — the seven binding ADRs.
- [`docs/adr/`](adr/) — the eight cross-cutting ADRs (auth, secrets, audit, tenant, etc.).
- [`docs/runbooks/observability.md`](runbooks/observability.md) — Grafana / Prometheus operational guide.
- [`docs/metrics-catalog.md`](metrics-catalog.md) — canonical metric set.
- [`docs/load-test-profiles.md`](load-test-profiles.md) — Phase F load test profiles.
