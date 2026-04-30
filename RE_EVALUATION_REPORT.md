# Archon Re-Evaluation Report

**Date:** 2026-04-28
**Method:** 8-agent parallel research swarm (Sonnet 4.6) → Opus synthesis
**Authority:** Read-only audit. Citations are file:line. No prior "completion" doc was trusted; every claim was verified against code, tests, or runtime evidence.

---

## Working thesis

The user does not need another "milestone complete" report. Archon's documentation has overclaimed completion in every prior cycle (`COMPLETION_SUMMARY.txt`, `FINAL_REPORT.md`, `CRITICAL_STUBS_FIXED.md`, `FIXES_SUMMARY.txt`, etc.) and the most recent intent document — `ARCHON_OVERHAUL_PROMPT.md` — explicitly contradicts those completion claims by stating that 34 contract violations, 13 priority features, and 33 stub test files remain unaddressed.

This report establishes ground truth, names the architectural bottleneck preventing enterprise workflow orchestration, and produces an executable agent swarm plan.

---

## What is proven

These are validated by code reads and (where applicable) passing tests:

- **Auth (`backend/app/middleware/auth.py`)** — 3-tier JWT validation: HS256 dev mode, RS256 Keycloak via JWKS, RS256 Azure Entra ID via OIDC discovery. Real `python-jose` signature verification with `verify_exp=True`. JWKS caching with 1-hour TTL. Dev bypass requires explicit `AUTH_DEV_MODE=true` (off by default).
- **RBAC (`backend/app/middleware/rbac.py`, 170 LOC)** — 4 built-in roles + custom role table. Sync fast-path + async DB lookup. Real role-to-action mapping.
- **Vault integration (`backend/app/secrets/manager.py`, 534 LOC)** — Real `hvac` client. KV-v2, PKI cert issuance, dynamic credentials, namespace-per-tenant, in-memory TTL cache, graceful fallback to `_StubSecretsManager`. Strongest enterprise component in the codebase.
- **Audit logging (`backend/app/middleware/`)** — Structured JSON via `structlog` + Azure Sentinel-compatible processor. Real.
- **WebSocket (`backend/app/websocket/manager.py`, 670 LOC)** — Redis-backed `ExecutionStreamManager` with 500-entry cap, 24h TTL, heartbeat/pong, event replay.
- **DLP (`backend/app/services/dlp_service.py`, 1,718 LOC)** — Presidio integration with regex fallback. Real PII detection. 26 tests passing.
- **Router scoring engine (`backend/app/services/router_service.py`, 1,710 LOC)** — DB-backed model registry, classification/capability/geo filtering, circuit breaker, cost budgeting, real Azure OpenAI HTTP calls with 429-aware retry. 22 tests passing. **Critical caveat:** scoring works as a standalone API but is NOT WIRED INTO WORKFLOW EXECUTION.
- **SentinelScan service (`backend/app/services/sentinelscan_service.py`, 2,334 LOC)** — Real risk scoring + DB persistence. **Critical caveat:** the FastAPI router is not registered in `main.py`, so the UI 404s for every call.
- **Red-team engine (`security/red_team/`, 526 LOC)** — 13 OWASP-aligned attacks across 6 categories, concurrent campaigns, weighted resilience score.
- **Frontend visual builder** — 27 node types registered (matches "27+" claim), full `@xyflow/react` canvas, drag-drop wired, undo/redo with 50-entry history, real save to backend, validation overlay. Most complete UI piece.
- **DLP frontend** — Functional 4-tab UI (Dashboard, Policies, Test Scanner, Detections). Real API connectivity.
- **Operations dashboard** — Real API data (agents, executions, router models, cost summary, audit events, health). Not mocked.
- **DAG executor (`backend/app/services/workflow_engine.py`, 360 LOC)** — Real `asyncio.gather` fan-out, dependency resolution, per-step persistence to `WorkflowRunStep`. **Critical caveat:** REST API does NOT call this — it calls `_simulate_execution()` instead.
- **Scheduler (`backend/app/worker.py`, 345 LOC)** — Real `croniter` cron evaluation, creates `WorkflowRun(status="pending")` rows on schedule. **Critical caveat:** no consumer exists to execute pending runs.
- **Vault Helm chart** — Substantive `vault-init.sh` (316 LOC, idempotent KV-v2 + Transit + PKI + AppRole).
- **AWS Terraform** (`infra/terraform/aws/main.tf`, 409 LOC) — VPC + EKS + RDS PG16 multi-AZ + ElastiCache + S3 with KMS. Substantive.
- **Test suite outcomes** — 764 backend/tests pass (clean). 35 gateway/tests pass. 2,035/2,199 in tests/ pass.
- **CI lint + build steps** work.

---

## What is implemented but unproven

- **DLP detector pipeline** — only the regex layer is implemented. The 4-stage pipeline (regex → NER → semantic → policy) declared in `docs/ARCHITECTURE.md:327-334` is not implemented end-to-end. Presidio is wired but no NeMo Guardrails, no Garak harness in the runtime path.
- **Multi-tenancy** — `tenant_id` filter at the SQLAlchemy layer (`middleware/tenant.py`, 118 LOC). Not Postgres RLS. Application-layer filtering only. The `_DEFAULT_TENANT = UUID("00000000-...")` hardcoded zero UUID at `routes/workflows.py:58` undermines isolation.
- **Worker scheduling** — Single-process polling loop with no distributed lock. Two replicas would double-fire schedules.
- **Frontend execution streaming** — WebSocket protocol implemented but the builder's "Test Run" panel does not connect (`TestRunPanel.tsx:129` has the comment with no body). Live streaming works only on `/executions/:id` page.

---

## What is overclaimed

These are claims contradicted by code or test evidence:

- **"PRODUCTION READY"** (`COMPLETION_SUMMARY.txt:13`, `FINAL_REPORT.md:434`, `docs/FINAL_SUMMARY.md:321`) — invalidated by `ARCHON_OVERHAUL_PROMPT.md:5` ("the 34 frontend-backend contract violations, all 13 priority features, and the 33 stub test files are still unaddressed"). 0 of hundreds of ROADMAP checkboxes complete.
- **"27+ node types" vs "200+ node types"** — README says 27, ARCHITECTURE.md and ROADMAP say 200+. Reality: 27.
- **"50+ data connectors"** — Reality: 5 (Postgres, S3, Slack, REST, Google Drive). Off by 10x.
- **"shadcn/ui"** — Not installed. Hand-rolled lookalikes in `frontend/src/components/ui/` (5 files).
- **"OpenLLMetry"** — Not present. Not in requirements.txt. Not imported anywhere.
- **"NeMo Guardrails"** — Not integrated. `gateway/app/guardrails/middleware.py` is rate limit + input validation + audit log; doesn't call any Guardrails AI or NeMo library.
- **"LiteLLM"** — Declared in requirements.txt; **never imported**. Zero `import litellm`. The advertised cross-provider gateway is absent.
- **"Celery"** — Declared in requirements.txt; **never imported**. The "background jobs" claim is satisfied by a bare asyncio polling loop.
- **"LangGraph state machines · 17 specialized agents"** — Two-node echo stub exists in `backend/app/langgraph/nodes.py`. No agents directory at the top level. The 17 agents are documentation, not code.
- **"All workstreams ✅ COMPLETE"** (`docs/FINAL_SUMMARY.md:14-35`) — Same doc at line 306 admits "SCIM implementation — Incomplete," line 309 admits "Vault integration is partial," line 307 admits "Rate limiting won't scale; migrate to Redis."
- **"Reviewed by: Automated Verification System"** (`FINAL_REPORT.md:454`) — AI agent self-approving its own work as production-ready, with no human in the loop.
- **Test failure counts disagree** across docs: 58 (`docs/FINAL_SUMMARY.md:47`), 55 (`docs/HEALTH_REPORT.md:28`), 56 (`docs/INTEGRATION_TEST_REPORT.md:23`).

---

## What is missing

- **Real LLM execution path.** No `import litellm` anywhere. No LangChain/OpenAI/Anthropic SDK calls in any node, executor, or service. `langgraph/nodes.py:28` `process_node` returns `f"Processed: {content}"`. The advertised AI orchestration produces echo strings.
- **REST → DAG executor wiring.** `routes/executions.py:51,149,168` calls `_simulate_execution()` which generates random mock steps. The real `workflow_engine.execute_workflow_dag` is never invoked from the API.
- **LangGraph checkpointing.** `engine.py:46-58` calls `compile()` without a `checkpointer`. No `MemorySaver`, no `PostgresSaver`. Process restart loses workflow state.
- **Pending run consumer.** Worker creates `WorkflowRun(status="pending")` for cron + webhook + event triggers. Nothing dequeues them. They accumulate.
- **Node-type interpreter.** `workflow_engine.py` reads only `step["agent_id"]` and dispatches identically. `LoopNode`, `HumanApprovalNode`, `DLPScanNode`, `ParallelNode`, `SubWorkflowNode`, `CostGateNode`, `ConditionNode`, `SwitchNode` are decorative UI metadata with no backend semantics.
- **OAuth implementation.** `services/connectors/oauth.py:155` — fake token: `hashlib.sha256(code.encode()).hexdigest()`.
- **RAG pipeline.** `integrations/docforge/pipeline.py:90` `embed()` returns `[[0.0] * 384 for _ in chunks]`. `search()` returns first N chunks by index. No vector similarity. No LlamaIndex, PGVector, Haystack, Unstructured imports anywhere.
- **Cost calculation.** `services/execution_service.py` `_generate_mock_steps()` returns random token counts. No rate-card lookup. No real provider cost.
- **Workflow versioning.** No `version_number` or snapshot fields on `Workflow` model. `updated_at` overwrites in place.
- **Step retries with policy.** `retryPolicy` field exists in frontend `WfNodeData`; backend never reads it. No retry loop in `workflow_engine.py`.
- **Workflow run cancel/pause/resume.** Endpoints absent. Redis `send_signal` endpoint publishes to a channel with zero subscribers.
- **Idempotency keys** for workflow run creation.
- **Per-tenant concurrency / quotas.**
- **`make verify` / `make test-slice`** Makefile targets.
- **`infra/k8s/` raw manifests.** Directory has only `.gitkeep`.
- **`ops/` cost engine.** Directory has only `.gitkeep`.
- **`contracts/events.yaml`.** Roadmap milestone unchecked.
- **`contracts/shared-types.ts`.** Roadmap milestone unchecked.
- **CI contract validation.** No Spectral/Dredd/Prism/schemathesis. The OpenAPI spec is aspirational documentation.
- **CD staging deploy.** Helm upgrade step in `cd.yml` is entirely commented out.
- **HPA / PDB Helm templates.** `values.yaml` claims enabled; templates absent.
- **Helm umbrella `archon-platform`** never had `helm dependency update` run; sub-chart `charts/` directory absent.
- **OpenTelemetry SDK** not in requirements.txt; only conditional `try/except ImportError` imports that silently no-op.
- **Cost / token metrics** — Grafana dashboards query `archon_token_usage_total` and `archon_cost_total`; backend emits neither.
- **Alert metric name alignment** — `infra/monitoring/prometheus-values.yaml` rules use `http_requests_total` and `http_request_duration_seconds_bucket`; backend emits `archon_requests_total` and `archon_request_duration_seconds`. Alerts will never fire.
- **`docker-compose.yml` `vault` and `vault-init` services** — `make vault-up` / `make secrets-init` invoke services that aren't defined.
- **`docs/screenshots/*.png`** — referenced by README; existence not verified by audit (likely placeholders).

---

## Production-fatal footguns

These will destroy data or cause silent enterprise failures:

1. **`backend/app/database.py:38` runs `SQLModel.metadata.drop_all` then `create_all` on every startup.** Called from `main.py:275` startup event. Every restart wipes the database.
2. **Alembic env.py imports only 3 of 70+ models** (per Feb 27 recon in `.temp/mcpu-responses/`). Auto-generated migrations are incomplete — production schemas would diverge from declared models.
3. **In-memory state on critical paths** — rate limiter (`gateway/app/guardrails/middleware.py:119`), SSO config (`routes/sso.py` `_sso_config = SSOConfigData()`), visual rules store (`routes/router.py:233-234` `_visual_rules_store: list[dict] = []`), tenant cache (`middleware/tenant.py` `_tenant_cache: dict = {}`). None survives restart or horizontal scale.
4. **AUTH_DEV_MODE bypass exists.** `gateway/app/auth/middleware.py:216` accepts the literal string `"dev-token"` when `AUTH_DEV_MODE=true`. `env.example` defaults `DEV_MODE=true` — a fresh operator runs in bypass.
5. **JWT_SECRET hardcoded in compose** (`docker-compose.yml`: `ARCHON_JWT_SECRET: "dev-secret-key-for-testing"`). Must be overridden for prod; override path not documented inline.

---

## The real bottleneck

**Three layers each work in isolation. They are not connected:**

```
[Visual Builder]   ──drawing─→  [Workflow JSON]  ──save─→  [DB]
       │                              │                      │
       │                              ↓                      │
       │                       [REST /executions]            │
       │                              │                      │
       │                              ↓                      │
       │                       [_simulate_execution]   ←─── decoration
       │                              │
       │                              ↓
       │                       [Random mock data] ←── what user sees
       │
       │                       (workflow_engine.py exists  ←─ orphaned
       │                        as a 360-line module
       │                        nothing calls)
       │
       │                       (langgraph/engine.py exists
       │                        as a 2-node echo stub
       │                        no LLM call)
```

**Single-sentence bottleneck:** The visual builder, DAG executor, LangGraph runtime, and infrastructure layer all exist as functioning isolated components, but **the REST execution endpoint bypasses all of them and returns random simulation data**; even if it called the executor, the executor treats every node identically and the LangGraph stub never calls an LLM.

The missing primitive: **a node-type-aware durable executor that (a) is invoked by the REST API instead of `_simulate_execution`, (b) interprets each visual node type with real semantics, (c) calls real LLMs via LiteLLM, and (d) checkpoints state to PostgreSQL so workflows survive restart.**

Once that primitive exists, downstream features (cost tracking, observability, retries, human-in-loop pause/resume, scheduled run consumption) can be wired in.

---

## Highest-leverage next steps (ranked)

1. **Make execution real.** Replace `_simulate_execution` with `workflow_engine.execute_workflow_dag`. Implement real LLM nodes via `litellm.acompletion`. Wire LangGraph `PostgresSaver` checkpointer. Without this, no other work matters for the user's enterprise orchestration goal.
2. **Stop wiping the database.** Remove `drop_all/create_all` from startup. Switch to Alembic migrations. Fix `env.py` to import all models.
3. **Drain pending runs.** Add a worker consumer that picks up `WorkflowRun(status="pending")` and invokes the executor. Without this, scheduled runs and webhook-triggered runs accumulate and never execute.
4. **Build the node-type interpreter.** Map each of the 27 visual node types to backend behavior (loop, conditional, parallel fan-in mode, human approval pause, DLP injection, cost gate, sub-workflow, retry policy). Without this, the visual builder is decorative.
5. **Wire real cost tracking.** Replace `_generate_mock_steps`. Read token counts from LiteLLM responses, look up rate cards, persist to `cost_records`, emit `archon_token_usage_total` / `archon_cost_total` Prometheus metrics. This makes the cost dashboard real.
6. **Fix observability metric mismatch.** Either rename emitted metrics to match Grafana dashboards / alert rules, or update the dashboards / rules. Today the entire observability layer is silent at runtime.
7. **`make verify` + `make test-slice`.** Add the gates referenced throughout ROADMAP. Make `test-slice` a real end-to-end heartbeat (POST /agents → POST /executions → assert real LLM completion arrived). This is the heartbeat the project has been missing.
8. **Documentation truth.** Delete or supersede `COMPLETION_SUMMARY.txt`, `FINAL_REPORT.md`, `CRITICAL_STUBS_FIXED.md`, `FIXES_SUMMARY.txt`. Replace with this report. Update README node count from "27+" to actual, connector count from "50+" to actual.
9. **Persist in-memory state.** Move rate limiter to Redis. Move SSO config and visual rules to DB.
10. **Register orphaned routers.** SentinelScan, connector test/health, model router provider management, etc. Either wire them or return 503 with clear "not implemented" messages.

---

## What not to build yet

- 50+ connectors. Stick with the 5 real ones; the catalog is a distraction until execution works.
- 200+ node types. The 27 are sufficient — complete their backend semantics first.
- Full RAG pipeline (LlamaIndex/PGVector/Haystack). Defer until the execution substrate is durable.
- Mobile builder/router/DLP screens. The mobile app is a 3-screen stub; defer.
- Multi-cloud Terraform parity (Azure, GCP). AWS module is enough for first deployment.
- ArgoCD application sync. Single-cluster Helm install is sufficient until v1.
- ML-based DLP (Presidio NER). Keep regex + Presidio with graceful fallback.
- New agent frameworks (`.sdd`, `.claude-flow`, `.swarm`). Claude Flow V3 ran zero tasks. Stop installing frameworks; ship code.

---

## Salvageable artifacts (carry forward)

- `.sdd/learnings/` — 5 real pitfalls documented from prior runs. Keep.
- `ARCHON_OVERHAUL_PROMPT.md` — accurate gap analysis. Reference, don't trust as a build spec.
- `contracts/openapi.yaml` — 3,339-line hand-rolled spec. Reasonable starting point for contract-first.
- All real services already cited in "What is proven" above.
- AWS Terraform module.
- Vault Helm chart and `vault-init.sh`.

## Discard

- `.claude-flow/` — zero runs. Adds noise.
- `.temp/mcpu-responses/` — historical only.
- `COMPLETION_SUMMARY.txt`, `FINAL_REPORT.md`, `FIXES_SUMMARY.txt`, `CRITICAL_STUBS_FIXED.md`, `WIZARD_TEMPLATES_EXAMPLES.md`, `VERIFICATION_CHECKLIST.md`, `DOCUMENTATION_INDEX.md`, `docs/FINAL_SUMMARY.md`, `docs/HEALTH_REPORT.md`, `docs/INTEGRATION_TEST_REPORT.md` — overclaim documents demonstrably contradicted by ground truth. Move to `docs/_archive/` so git history is preserved but they don't show up in directory listings as authoritative.

---

*Generated: 2026-04-28*
*Reviewed by: 8-agent Sonnet 4.6 research swarm + Opus synthesis*
*Cycle: re-evaluation #1 (verification cycle to follow)*
