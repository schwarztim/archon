# Archon Feature Matrix

**Generated:** 2026-04-29
**Source of truth:** [`docs/feature-matrix.yaml`](./feature-matrix.yaml)
**Validator:** `python3 scripts/check-feature-matrix.py`

This document is a **human-readable rendering of `feature-matrix.yaml`**.
The YAML is the canonical source — when they disagree, the YAML wins. The
validator script enforces that source files referenced here exist, that
every registered node executor has an entry, and that the `status_summary`
counts agree with the actual entry counts.

---

## Status legend

| Badge | Status | Meaning |
| :---: | :----- | :------ |
| ✅ | `production` | Code exists, tests prove it, wired end-to-end, safe in enterprise mode |
| ⚠️ | `beta`       | Code exists, partially proven, may have caveats — see Gap |
| 🚫 | `stub`       | Returns success but does not perform real work — must be blocked in enterprise mode |
| 📐 | `designed`   | Schema/route exists but no implementation |
| ❌ | `missing`    | Referenced in docs but not in code |
| ⛔ | `blocked`    | Explicitly disabled (e.g., kill-switch envvar) — see Notes |

## Top-level summary

| Status | Count |
| :----- | ----: |
| ✅ production | 93 |
| ⚠️ beta       | 79 |
| 🚫 stub       | 13 |
| 📐 designed   | 4  |
| ❌ missing    | 15 |
| ⛔ blocked    | 0  |
| **Total**    | **204** |

---

## 1. Node executors

These are the visual-builder node types registered via `@register("...")`
in `backend/app/services/node_executors/`. Workflow execution dispatches
to whichever executor is keyed by the step's `type` field.

| Status | id | Source | Tests | Gap |
| :---: | :-- | :-- | :-- | :-- |
| ✅ | `llmNode` | `node_executors/llm.py` | yes | — |
| ⚠️ | `conditionNode` | `node_executors/condition.py` | yes | Engine-side branch routing per ADR-003 not yet wired through durable run path |
| ⚠️ | `switchNode` | `node_executors/switch.py` | yes | Multi-branch downstream routing per ADR-003 still designed |
| ⚠️ | `parallelNode` | `node_executors/parallel.py` | yes | Engine implements `all` only; `any` and `n_of_m` per ADR-003 still designed |
| ⚠️ | `mergeNode` | `node_executors/merge.py` | yes | Engine fan-in coordination tied to upstream parallel is incomplete |
| 🚫 | `loopNode` | `node_executors/loop.py` | (registry only) | Returns `_loop_hint` without iterating any body — must be blocked in enterprise mode |
| ⚠️ | `delayNode` | `node_executors/delay.py` | yes | In-process `asyncio.sleep` is non-durable; durable timer table per ADR-005 missing |
| ⚠️ | `humanApprovalNode` | `node_executors/human_approval.py` | yes | Pause is recorded via raw SQL but no decision endpoint, signal bus, or resume path |
| 🚫 | `humanInputNode` | `node_executors/human_input.py` | — | Returns `completed` with `_stub: True`; TODO(v2) explicitly says it should pause |
| ⚠️ | `dlpScanNode` | `node_executors/dlp_scan.py` | yes | Default action is `flag` (fail-open); enterprise mode must default to `block` |
| ⚠️ | `costGateNode` | `node_executors/cost_gate.py` | yes | Three fail-open paths: no threshold, no tenant context, query exception — all return `passed=true` |
| ⚠️ | `httpRequestNode` | `node_executors/http_request.py` | yes | No SSRF allow/deny list, no per-tenant rate limit, no DLP scan of response body |
| 🚫 | `mcpToolNode` | `node_executors/mcp_tool.py` | — | Returns `_stub: true` with `result: null` — must be blocked in enterprise mode |
| 🚫 | `toolNode` | `node_executors/tool.py` | — | No tool registry; stub success — must be blocked |
| 🚫 | `databaseQueryNode` | `node_executors/database_query.py` | — | No connector framework wiring; stub success — must be blocked |
| 🚫 | `functionCallNode` | `node_executors/function_call.py` | — | No sandbox runner (RestrictedPython / subprocess) — must be blocked |
| ⚠️ | `subAgentNode` | `node_executors/sub_agent.py` | — | Real recursion via `execute_agent`; cycle/depth detection absent |
| ⚠️ | `subWorkflowNode` | `node_executors/sub_workflow.py` | — | Stub fallback hides missing definitions; cycle detection absent |
| 🚫 | `embeddingNode` | `node_executors/embedding.py` | — | No `litellm.aembedding` wiring; stub success — must be blocked |
| 🚫 | `vectorSearchNode` | `node_executors/vector_search.py` | — | No PGVector / Pinecone / Weaviate; stub — must be blocked |
| 🚫 | `documentLoaderNode` | `node_executors/document_loader.py` | — | No chunker / connector wiring — must be blocked |
| 🚫 | `visionNode` | `node_executors/vision.py` | — | No multimodal call_llm payload — must be blocked |
| 🚫 | `structuredOutputNode` | `node_executors/structured_output.py` | — | No `json_mode=True` call_llm — must be blocked |
| 🚫 | `streamOutputNode` | `node_executors/stream_output.py` | — | Output is collected, not pushed incrementally — must be blocked for streaming consumers |
| ✅ | `inputNode` | `node_executors/input_node.py` | yes | — |
| ✅ | `outputNode` | `node_executors/output_node.py` | yes | — |
| ⚠️ | `webhookTriggerNode` | `node_executors/webhook_trigger.py` | yes | Trigger ingestion (HMAC verification, replay protection) lives elsewhere |
| ⚠️ | `scheduleTriggerNode` | `node_executors/schedule_trigger.py` | yes | Cron evaluator + drift handling lives in worker.py and schedule routes |

---

## 2. REST routes

A representative slice — every category of router is covered, including
the **execution endpoints (ADR-001 semantic conflict)**, audit, DLP,
governance, MCP, cost, auth/SSO/SAML/SCIM/TOTP, secrets, tenancy, RBAC,
connectors, models/router, sandbox, wizard, templates/marketplace,
SentinelScan, lifecycle, A2A, mesh/edge, DocForge, mobile, deployment,
redteam, security proxy, admin, settings, components, websocket, QA,
improvements, agent versions, and versioning.

### 2.1 Execution endpoints (ADR-001 semantic conflict)

| Status | Method + path | Handler | Auth | Tenant | Notes |
| :---: | :-- | :-- | :---: | :---: | :-- |
| ⚠️ | `POST /api/v1/executions` | `executions:create_and_run_execution` | yes | yes | `ExecutionService.run_execution` marks completed without calling a real graph |
| ⚠️ | `POST /api/v1/execute` | `executions:create_execution` | no | no | `dispatch_run` expects a `WorkflowRun` ID; passing `Execution.id` does not run the agent |
| ⚠️ | `POST /api/v1/agents/{agent_id}/execute` | `executions:execute_agent` | no | no | Same ADR-001 conflict |
| ⚠️ | `POST /api/v1/agents/{agent_id}/execute` | `agents:execute_agent` | no | no | Duplicate copy in `agents.py` — ADR-001 unifies |
| ✅ | `GET /api/v1/executions` | `executions:list_executions` | no | no | No tenant filtering — multi-tenant leakage |
| ✅ | `GET /api/v1/executions/{id}` | `executions:get_execution` | no | no | No tenant ownership check |
| ⚠️ | `POST /api/v1/executions/{id}/replay` | `executions:replay_execution` | no | no | Replay reconstructs from row state, not deterministic event log |
| ⚠️ | `POST /api/v1/executions/{id}/cancel` | `executions:cancel_execution` | no | no | Engine-wide cancel-token plumbing partial |
| ✅ | `DELETE /api/v1/executions/{id}` | `executions:delete_execution` | no | no | No tenant ownership check |

### 2.2 Health & metrics

| Status | Method + path | Handler |
| :---: | :-- | :-- |
| ✅ | `GET /health` | `health:health` |
| ✅ | `GET /api/v1/health` | `health:health_v1` |
| ✅ | `GET /ready` | `health:ready` |
| ✅ | `GET /metrics` | `metrics:metrics` |

### 2.3 Workflows

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ✅ | `GET /api/v1/workflows` | — |
| ✅ | `POST /api/v1/workflows` | — |
| ✅ | `GET /api/v1/workflows/{id}` | — |
| ✅ | `PUT /api/v1/workflows/{id}` | — |
| ✅ | `DELETE /api/v1/workflows/{id}` | — |
| ⚠️ | `POST /api/v1/workflows/{id}/execute` | Calls `execute_workflow_dag` inline — does NOT create a `WorkflowRun`; no durable record |
| ✅ | `GET /api/v1/workflows/{id}/runs` | — |
| ✅ | `GET /api/v1/workflows/{id}/runs/{run_id}` | — |
| ⚠️ | `PUT /api/v1/workflows/{id}/schedule` | Drift handling and missed-run policy not specified |
| ⚠️ | `POST /api/v1/workflows/{id}/webhook` | No HMAC verification, no replay protection |

### 2.4 Audit, DLP, Governance

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ✅ | `GET /api/v1/audit-logs` | — |
| ✅ | `GET /api/v1/audit-logs/export` | — |
| ✅ | `GET /api/v1/audit-logs/verify-chain` | SHA-256 chain walker |
| ✅ | `GET /api/v1/dlp/detectors` | — |
| ✅ | `POST /api/v1/dlp/scan` | — |
| ✅ | `POST /api/v1/dlp/redact` | — |
| ⚠️ | `POST /api/v1/dlp/guardrails` | DLP-style guardrails — NOT NeMo Guardrails |
| ✅ | `POST /api/v1/dlp/policies` | — |
| ✅ | `GET /api/v1/dlp/policies` | — |
| ✅ | `GET /api/v1/governance/policies` | — |
| ✅ | `POST /api/v1/governance/policies` | — |
| ⚠️ | `POST /api/v1/governance/compliance/check` | Frameworks referenced but not all evidence-mapped |
| ✅ | `POST /api/v1/governance/audit` | — |
| ✅ | `GET /api/v1/governance/audit` | — |
| ✅ | `GET /api/v1/governance/audit/verified` | — |
| 📐 | `POST /api/v1/governance/policies/opa` | Persists policies; no OPA evaluator at execution time |

### 2.5 MCP

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ⚠️ | `POST /api/v1/mcp/sessions` | mcpToolNode is a stub — sessions wired but no real tool calls |
| ✅ | `GET /api/v1/mcp/sessions` | — |
| ⚠️ | `POST /api/v1/mcp/authorize` | v1_router restored 2026-04-28 (was orphaned) |
| 🚫 | `POST /api/v1/mcp/execute` | Wraps mcpToolNode — same stub gap |
| ⚠️ | `POST /api/v1/mcp/containers` | ToolHive-pattern container management |

### 2.6 Cost

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ✅ | `GET /api/v1/cost/dashboard` | — |
| ✅ | `POST /api/v1/cost/usage` | — |
| ⚠️ | `POST /api/v1/cost/check` | Pairs with costGateNode — same fail-open paths |
| ⚠️ | `GET /api/v1/cost/forecast` | Heuristic forecast; no ML-backed prediction |

### 2.7 Auth, SSO, SAML, SCIM, TOTP

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ✅ | `POST /api/v1/auth/login` | Dev login + JWT issue |
| ✅ | `GET /api/v1/auth/me` | — |
| ✅ | `POST /api/v1/auth/token/refresh` | — |
| ⚠️ | `POST /api/v1/saml/login` | Per-tenant IdP config exists; no automated end-to-end test |
| ⚠️ | `POST /api/v1/saml/acs` | ACS — no automated end-to-end test |
| ⚠️ | `POST /api/v1/sso/test-connection` | — |
| ✅ | `GET /api/v1/scim/v2/Users` | SCIM 2.0 |
| ✅ | `POST /api/v1/scim/v2/Users` | — |
| ✅ | `POST /api/v1/auth/totp/enroll` | — |

### 2.8 Secrets, Tenancy, RBAC, Connectors

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ⚠️ | `POST /api/v1/secrets` | Vault-backed; rotation policy enforcement partial |
| ⚠️ | `POST /api/v1/secrets/{id}/rotate` | Auto-rotation worker not end-to-end proven |
| ✅ | `GET /api/v1/secrets/rotation-dashboard` | — |
| ✅ | `POST /api/v1/tenants` | — |
| ✅ | `GET /api/v1/tenants` | — |
| ⚠️ | `POST /api/v1/tenancy/tenants` | Duplicate surface (legacy `/tenants` prefix) |
| ✅ | `GET /api/v1/rbac/custom-roles` | — |
| ✅ | `POST /api/v1/rbac/custom-roles` | — |
| ✅ | `GET /api/v1/rbac/group-mappings` | — |
| ✅ | `GET /api/v1/rbac/matrix` | — |
| ✅ | `GET /api/v1/connectors` | — |
| ✅ | `POST /api/v1/connectors` | — |
| ⚠️ | `POST /api/v1/connectors/{id}/oauth/start` | Enterprise OAuth flow |
| ⚠️ | `POST /api/v1/connectors/{id}/test` | — |

### 2.9 Models / Router / Sandbox / Wizard

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ✅ | `GET /api/v1/models` | — |
| ⚠️ | `POST /api/v1/router/route` | Tenant residency / latency-based routing partial |
| ✅ | `GET /api/v1/router/providers/health` | — |
| ⚠️ | `POST /api/v1/sandbox/execute` | Sandbox isolation strategy not documented in code |
| ⚠️ | `POST /api/v1/wizard/describe` | — |
| ⚠️ | `POST /api/v1/wizard/generate` | — |

### 2.10 Templates / Marketplace / SentinelScan

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ✅ | `GET /api/v1/templates` | — |
| ⚠️ | `POST /api/v1/templates/{id}/install` | — |
| ✅ | `GET /api/v1/marketplace/listings` | — |
| ⚠️ | `POST /api/v1/marketplace/{id}/install` | — |
| ⚠️ | `POST /api/v1/sentinelscan/scan` | — |
| ⚠️ | `GET /api/v1/sentinelscan/posture/summary` | — |

### 2.11 Lifecycle / A2A / Mesh / Edge / DocForge / Mobile / Deployment / Redteam / Misc

| Status | Method + path | Notes |
| :---: | :-- | :-- |
| ✅ | `POST /api/v1/lifecycle/deployments` | — |
| ⚠️ | `POST /api/v1/lifecycle/deployments/{id}/rollback` | — |
| ⚠️ | `POST /api/v1/lifecycle/{agent_id}/lifecycle/transition` | enterprise_router restored 2026-04-28 |
| ⚠️ | `POST /api/v1/a2a/discover` | Agent-to-agent discovery |
| ⚠️ | `POST /api/v1/a2a/partners` | federation_router |
| ⚠️ | `POST /api/v1/mesh/nodes` | — |
| ⚠️ | `POST /api/v1/edge/devices` | — |
| ⚠️ | `POST /api/v1/edge/sync` | — |
| ⚠️ | `POST /api/v1/docforge/documents/ingest` | — |
| ⚠️ | `POST /api/v1/docforge/documents/search` | — |
| ⚠️ | `POST /api/v1/mobile/devices` | — |
| ⚠️ | `POST /api/v1/deploy` | — |
| ⚠️ | `POST /api/v1/redteam/security/scan` | — |
| ⚠️ | `POST /api/v1/proxy/request` | — |
| ✅ | `GET /api/v1/admin/users` | — |
| ✅ | `GET /api/v1/settings` | — |
| ⚠️ | `POST /api/v1/components/sessions` | — |
| ⚠️ | `WS /ws/executions/{execution_id}` | Frontend depends on WS for live updates; without event-history reconstruction is impossible |

### 2.12 QA / Improvements / Agent Versions / Versioning

| Status | Method + path |
| :---: | :-- |
| ⚠️ | `POST /api/v1/qa/trigger` |
| ⚠️ | `POST /api/v1/improvements/analyze` |
| ⚠️ | `POST /api/v1/tenancy/tenants` |
| ✅ | `GET /api/v1/agent-versions` |
| ✅ | `POST /api/v1/agent-versions` |
| ✅ | `GET /api/v1/agent-versions/latest` |
| ✅ | `GET /api/v1/agent-versions/{version_id}` |
| ✅ | `GET /api/v1/versioning/agents/{agent_id}/versions/list` |
| ✅ | `POST /api/v1/versioning/agents/{agent_id}/versions/{version_id}/rollback` |

---

## 3. Enterprise capabilities

| Status | id | Source | Gap |
| :---: | :-- | :-- | :-- |
| ⚠️ | `rls_postgres` | `models/rls.py` | No end-to-end test verifies cross-tenant denial |
| ✅ | `rbac` | `routes/rbac.py`, `routes/sso_config.py`, `models/rbac.py`, `models/custom_role.py` | Permission enforcement uses `Depends()` inconsistently |
| ✅ | `audit_hash_chain` | `services/audit_service.py`, `middleware/audit_middleware.py`, `routes/audit_logs.py` | — |
| ✅ | `dlp` | `services/dlp_service.py`, `middleware/dlp_middleware.py`, `routes/dlp.py`, `node_executors/dlp_scan.py` | Default action `flag` (fail-open); enterprise must enforce `block` |
| ⚠️ | `cost_gates` | `services/cost_service.py`, `routes/cost.py`, `node_executors/cost_gate.py` | Three fail-open paths in costGateNode |
| ⚠️ | `sso_saml` | `routes/saml.py`, `routes/sso.py`, `routes/sso_config.py`, `services/saml_service.py` | No automated end-to-end SAML test |
| ⚠️ | `secret_rotation` | `routes/secrets.py`, `secrets/manager.py`, `services/secret_access_logger.py` | Auto-rotation worker not end-to-end proven |
| 📐 | `opa` | `routes/governance.py`, `services/governance_service.py`, `services/dlp_service.py`, `models/governance.py` | OPA policies persisted but never enforced |
| ⚠️ | `multi_tenant_isolation` | `middleware/tenant_middleware.py`, `models/rls.py` | TenantMiddleware uses unverified-claim extraction |
| ⚠️ | `fail_closed_checkpointing` | `langgraph/checkpointer.py`, `langgraph/engine.py` | Postgres failure silently degrades to MemorySaver — ADR-005 mandates fatal |
| ⚠️ | `vault_integration` | `secrets/manager.py`, `secrets/config.py`, `routes/secrets.py`, `docker-compose.yml` | No integration test for seal/unseal/rotate |
| ❌ | `idempotency` | — | ADR-004 contract; no implementation in routes |
| ❌ | `signals_resume` | — | humanApprovalNode pauses but no resume bus |

---

## 4. Orchestration primitives

| Status | id | Notes / Gap |
| :---: | :-- | :-- |
| 📐 | `durable_runs` | `WorkflowRun` is closer to a status-tracker than a durable record per ADR-001 |
| ⚠️ | `workflow_run_steps` | Model exists but engine never persists step results |
| ❌ | `event_history` | `WorkflowRunEvent` model not created — Phase 1 deliverable |
| ❌ | `signals_approvals` | No SQLModel, no migration, no decision endpoint |
| ❌ | `durable_timers` | delayNode uses non-durable `asyncio.sleep` |
| ❌ | `retry_policy` | No `attempt` / `retry_count` columns |
| ❌ | `idempotency_unique` | ADR-004 contract not implemented |
| ⚠️ | `cancellation` | Honoured by delay/http only; subAgent/subWorkflow/llm ignore cancel |
| ⚠️ | `replay` | Endpoint exists but non-deterministic without event history |
| ❌ | `leases_heartbeats` | No `lease_owner` / `lease_expires_at` columns |
| ❌ | `worker_registry` | No workers table |
| ❌ | `definition_snapshot` | dispatcher reads live `Workflow` row at run time |

---

## 5. Observability

### 5.1 Metrics actually emitted

| Status | Metric | Type | Labels |
| :---: | :-- | :-- | :-- |
| ✅ | `archon_requests_total` | counter | method, path, status |
| ✅ | `archon_request_duration_seconds` | histogram | method, path |
| ✅ | `archon_executions_total` | counter | (declared, but never incremented — emits zero series) |
| ✅ | `archon_active_agents` | gauge | — |
| ✅ | `archon_vault_status` | gauge | — |
| ✅ | `archon_token_usage_total` | counter | tenant_id, model, kind |
| ✅ | `archon_cost_total` | counter | tenant_id, model |
| ✅ | `archon_workflow_runs_total` | counter | status, tenant_id |
| ✅ | `archon_workflow_run_duration_seconds` | histogram | — |
| ✅ | `archon_dlp_findings_total` | counter | tenant_id, severity, pattern |

### 5.2 Metrics referenced by dashboards but NOT emitted (parity violation)

| Status | Metric | Referenced by |
| :---: | :-- | :-- |
| ❌ | `archon_blocked_requests_total` | `infra/grafana/dashboards/security-dashboard.json` |
| ❌ | `archon_audit_events_total` | `infra/grafana/dashboards/security-dashboard.json` |
| ❌ | `archon_security_alerts` | `infra/grafana/dashboards/security-dashboard.json` |

### 5.3 Dashboards

| Status | Dashboard | Source |
| :---: | :-- | :-- |
| ✅ | `platform-overview` | `infra/grafana/dashboards/platform-overview.json` |
| ✅ | `cost-dashboard` | `infra/grafana/dashboards/cost-dashboard.json` |
| ⚠️ | `security-dashboard` | 3 of 5 panels query metrics that don't exist |

### 5.4 Traces & event history API

| Status | id | Notes |
| :---: | :-- | :-- |
| 📐 | `opentelemetry_traces` | One try/except `import opentelemetry` in `routes/executions.py`; no SDK config / exporter |
| ❌ | `event_history_api` | `GET /api/v1/executions/{id}/events` and `/workflow-runs/{id}/events` not implemented |

---

## 6. Infrastructure services

| Status | id | Source |
| :---: | :-- | :-- |
| ✅ | `docker_postgres` | `docker-compose.yml` |
| ✅ | `docker_redis` | `docker-compose.yml` |
| ✅ | `docker_vault` | `docker-compose.yml` |
| ✅ | `docker_vault_init` | `docker-compose.yml` |
| ✅ | `docker_keycloak` | `docker-compose.yml` |
| ✅ | `docker_backend` | `docker-compose.yml`, `backend/Dockerfile` |
| ✅ | `docker_worker` | `docker-compose.yml`, `backend/app/worker.py` |
| ✅ | `docker_frontend` | `docker-compose.yml` |
| ✅ | `docker_test_compose` | `docker-compose.test.yml` (no Vault/Keycloak — deliberately skinny) |
| ✅ | `makefile_dev_enterprise` | `Makefile` (postgres + redis + vault + keycloak + vault-init) |
| ✅ | `makefile_verify` | `Makefile`, `scripts/verify.sh` — but **NOT** invoked by `.github/workflows/ci.yml` |
| ⚠️ | `helm_archon` | `infra/helm/archon/` |
| ⚠️ | `helm_archon_platform` | `infra/helm/archon-platform/` |
| ⚠️ | `helm_vault` | `infra/helm/vault/` |
| ✅ | `prometheus_config` | `infra/prometheus/prometheus.yml` |
| ⚠️ | `argocd_application` | `infra/argocd/application.yaml` |
| ⚠️ | `gateway_service` | `gateway/` — has its own test suite; not a long-running service in main compose |
| ❌ | `nemo_guardrails` | Documentation references "guardrails"; only impl is `DLPService.check_guardrails` — NOT NeMo |

---

## How to keep this document accurate

1. Edit `docs/feature-matrix.yaml` — never edit this `.md` directly without
   updating the YAML.
2. Run `python3 scripts/check-feature-matrix.py` (use the resolved
   `$PYTHON` if your shell uses isaac `resolve-python.sh`).
3. The validator exits non-zero on hard mismatches:
   - `status_summary` counts disagree with actual entry counts
   - A node executor file is missing from the YAML
   - A registered `@register("...")` node_type is missing from the YAML
4. Soft warnings (e.g., `status=production` with no `test_files`) print to
   stderr but do not fail the run unless `--strict` is passed.
