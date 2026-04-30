# Archon — Feature Mapping

**Authority:** [`docs/feature-matrix.yaml`](feature-matrix.yaml) is the canonical source. This document is a navigation aid that links every feature to its code, tests, and governing docs.
**Validator:** `python3 scripts/check-feature-matrix.py` enforces source-file existence and registration coverage.
**Status legend:** ✅ `production` · ⚠️ `beta` · 🚫 `stub` (blocked in prod) · 📐 `designed` · ❌ `missing`.

> The previous version of this document was a marketing-parity matrix promising 50+ connectors and 200+ nodes, none of which existed. It has been replaced by an evidence-backed feature → code → tests → docs map. For competitive parity discussion (what Archon does and does not aim to match), see [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md).

## 1. Node executors (28 registered)

All 28 are registered via `@register("nodeType")` in [`backend/app/services/node_executors/`](../backend/app/services/node_executors/). The `feature-matrix.yaml` records each one's status; the dispatcher gates `stub` executors in production / staging via [`_stub_block.py`](../backend/app/services/node_executors/_stub_block.py).

| Status | Node type | Source | Tests | ADR / Doc |
|:---:|---|---|---|---|
| ✅ | `llmNode` | [`llm.py`](../backend/app/services/node_executors/llm.py) | [`test_all_executors.py`](../backend/tests/test_node_executors/test_all_executors.py) | [ADR-001](adr/orchestration/ADR-001-agent-vs-workflow-execution.md) |
| ✅ | `inputNode` | [`input_node.py`](../backend/app/services/node_executors/input_node.py) | yes | — |
| ✅ | `outputNode` | [`output_node.py`](../backend/app/services/node_executors/output_node.py) | yes | — |
| ⚠️ | `conditionNode` | [`condition.py`](../backend/app/services/node_executors/condition.py) | yes | [ADR-003](adr/orchestration/ADR-003-branch-fanin-semantics.md) |
| ⚠️ | `switchNode` | [`switch.py`](../backend/app/services/node_executors/switch.py) | yes | [ADR-003](adr/orchestration/ADR-003-branch-fanin-semantics.md) |
| ⚠️ | `parallelNode` | [`parallel.py`](../backend/app/services/node_executors/parallel.py) | yes | [ADR-003](adr/orchestration/ADR-003-branch-fanin-semantics.md) |
| ⚠️ | `mergeNode` | [`merge.py`](../backend/app/services/node_executors/merge.py) | yes | [ADR-003](adr/orchestration/ADR-003-branch-fanin-semantics.md) |
| ⚠️ | `delayNode` | [`delay.py`](../backend/app/services/node_executors/delay.py) | yes | [ADR-005](adr/orchestration/ADR-005-production-durability-policy.md) |
| ⚠️ | `humanApprovalNode` | [`human_approval.py`](../backend/app/services/node_executors/human_approval.py) | yes | [STATE_MACHINE](STATE_MACHINE.md) |
| ⚠️ | `dlpScanNode` | [`dlp_scan.py`](../backend/app/services/node_executors/dlp_scan.py) | yes | [ADR-013](adr/013-audit-trail.md) |
| ⚠️ | `costGateNode` | [`cost_gate.py`](../backend/app/services/node_executors/cost_gate.py) | yes | [GAP_ANALYSIS](GAP_ANALYSIS.md) |
| ⚠️ | `httpRequestNode` | [`http_request.py`](../backend/app/services/node_executors/http_request.py) | yes | — |
| ⚠️ | `subAgentNode` | [`sub_agent.py`](../backend/app/services/node_executors/sub_agent.py) | — | — |
| ⚠️ | `subWorkflowNode` | [`sub_workflow.py`](../backend/app/services/node_executors/sub_workflow.py) | — | — |
| ⚠️ | `webhookTriggerNode` | [`webhook_trigger.py`](../backend/app/services/node_executors/webhook_trigger.py) | yes | — |
| ⚠️ | `scheduleTriggerNode` | [`schedule_trigger.py`](../backend/app/services/node_executors/schedule_trigger.py) | yes | — |
| 🚫 | `loopNode` | [`loop.py`](../backend/app/services/node_executors/loop.py) | registry-only | [ADR-003](adr/orchestration/ADR-003-branch-fanin-semantics.md) |
| 🚫 | `humanInputNode` | [`human_input.py`](../backend/app/services/node_executors/human_input.py) | — | [STATE_MACHINE](STATE_MACHINE.md) |
| 🚫 | `mcpToolNode` | [`mcp_tool.py`](../backend/app/services/node_executors/mcp_tool.py) | — | — |
| 🚫 | `toolNode` | [`tool.py`](../backend/app/services/node_executors/tool.py) | — | — |
| 🚫 | `databaseQueryNode` | [`database_query.py`](../backend/app/services/node_executors/database_query.py) | — | — |
| 🚫 | `functionCallNode` | [`function_call.py`](../backend/app/services/node_executors/function_call.py) | — | — |
| 🚫 | `embeddingNode` | [`embedding.py`](../backend/app/services/node_executors/embedding.py) | — | — |
| 🚫 | `vectorSearchNode` | [`vector_search.py`](../backend/app/services/node_executors/vector_search.py) | — | — |
| 🚫 | `documentLoaderNode` | [`document_loader.py`](../backend/app/services/node_executors/document_loader.py) | — | — |
| 🚫 | `visionNode` | [`vision.py`](../backend/app/services/node_executors/vision.py) | — | — |
| 🚫 | `structuredOutputNode` | [`structured_output.py`](../backend/app/services/node_executors/structured_output.py) | — | — |
| 🚫 | `streamOutputNode` | [`stream_output.py`](../backend/app/services/node_executors/stream_output.py) | — | — |

**Stub-block infrastructure:**

| Status | Component | Source | Tests |
|:---:|---|---|---|
| ✅ | `nodeStatusRegistry` | [`status_registry.py`](../backend/app/services/node_executors/status_registry.py) | [`test_node_contract_matrix.py`](../backend/tests/test_node_executors/test_node_contract_matrix.py) |
| ✅ | `nodeStubBlock` | [`_stub_block.py`](../backend/app/services/node_executors/_stub_block.py) | yes |

## 2. Execution lifecycle endpoints

All execution endpoints route through `ExecutionFacade` ([ADR-001](adr/orchestration/ADR-001-agent-vs-workflow-execution.md)). The dispatcher is the only writer of `WorkflowRun.status`.

| Status | Method + path | Handler | Source | Tests |
|:---:|---|---|---|---|
| ⚠️ | `POST /api/v1/executions` | `create_and_run_execution` | [`routes/executions.py`](../backend/app/routes/executions.py) | [`test_executions_real.py`](../backend/tests/test_executions_real.py), [`test_vertical_slice.py`](../tests/integration/test_vertical_slice.py) |
| ⚠️ | `POST /api/v1/execute` | `create_execution` | [`routes/executions.py`](../backend/app/routes/executions.py) | yes |
| ⚠️ | `POST /api/v1/agents/{agent_id}/execute` | `execute_agent` | [`routes/agents.py`](../backend/app/routes/agents.py) | yes |
| ✅ | `GET /api/v1/executions` | `list_executions` | [`routes/executions.py`](../backend/app/routes/executions.py) | yes |
| ✅ | `GET /api/v1/executions/{execution_id}` | `get_execution` | [`routes/executions.py`](../backend/app/routes/executions.py) | yes |
| ⚠️ | `POST /api/v1/executions/{execution_id}/replay` | `replay_execution` | [`routes/executions.py`](../backend/app/routes/executions.py) | yes |
| ⚠️ | `POST /api/v1/executions/{execution_id}/cancel` | `cancel_execution` | [`routes/executions.py`](../backend/app/routes/executions.py) | [`test_cancellation.py`](../backend/tests/test_cancellation.py) |
| ✅ | `DELETE /api/v1/executions/{execution_id}` | `delete_execution` | [`routes/executions.py`](../backend/app/routes/executions.py) | yes |
| ✅ | `GET /api/v1/runs/{run_id}/events` | `list_events` | [`routes/events.py`](../backend/app/routes/events.py) | [`test_events_api.py`](../backend/tests/test_events_api.py) |
| ✅ | `GET /api/v1/runs/{run_id}/events/verify` | `verify_chain` | [`routes/events.py`](../backend/app/routes/events.py) | yes |
| ✅ | WS `/ws/runs/{run_id}` | `events_websocket` | [`websocket/events_manager.py`](../backend/app/websocket/events_manager.py) | [`test_events_websocket.py`](../backend/tests/test_events_websocket.py) |
| ✅ | `POST /api/v1/approvals/{approval_id}/grant` | `grant_approval` | [`routes/approvals.py`](../backend/app/routes/approvals.py) | [`test_approvals.py`](../backend/tests/test_approvals.py) |
| ✅ | `POST /api/v1/approvals/{approval_id}/deny` | `deny_approval` | [`routes/approvals.py`](../backend/app/routes/approvals.py) | yes |

## 3. Agents & workflows

| Status | Method + path | Handler | Source |
|:---:|---|---|---|
| ✅ | `GET /api/v1/agents` | `list_agents` | [`routes/agents.py`](../backend/app/routes/agents.py) |
| ✅ | `POST /api/v1/agents` | `create_agent` | [`routes/agents.py`](../backend/app/routes/agents.py) |
| ✅ | `GET /api/v1/agents/{agent_id}` | `get_agent` | [`routes/agents.py`](../backend/app/routes/agents.py) |
| ✅ | `PUT /api/v1/agents/{agent_id}` | `update_agent` | [`routes/agents.py`](../backend/app/routes/agents.py) |
| ✅ | `DELETE /api/v1/agents/{agent_id}` | `delete_agent` | [`routes/agents.py`](../backend/app/routes/agents.py) |
| ✅ | `GET /api/v1/workflows` | `list_workflows` | [`routes/workflows.py`](../backend/app/routes/workflows.py) |
| ✅ | `POST /api/v1/workflows` | `create_workflow` | [`routes/workflows.py`](../backend/app/routes/workflows.py) |

## 4. Health & operations

| Status | Endpoint | Source |
|:---:|---|---|
| ✅ | `GET /health` | [`backend/app/health.py`](../backend/app/health.py) |
| ✅ | `GET /api/v1/health` | same |
| ✅ | `GET /ready` | same |
| ✅ | `GET /metrics` | [`middleware/metrics_middleware.py`](../backend/app/middleware/metrics_middleware.py) |

## 5. Cross-cutting subsystems

| Status | Subsystem | Source | ADR / Doc |
|:---:|---|---|---|
| ✅ | LangGraph Postgres checkpointer (fail-closed in production) | [`langgraph/checkpointer.py`](../backend/app/langgraph/checkpointer.py) | [ADR-005](adr/orchestration/ADR-005-production-durability-policy.md) |
| ✅ | Run dispatcher (claim → persist → emit → terminal) | [`services/run_dispatcher.py`](../backend/app/services/run_dispatcher.py) | [ADR-001](adr/orchestration/ADR-001-agent-vs-workflow-execution.md) |
| ✅ | Event service (sha256 hash chain) | [`services/event_service.py`](../backend/app/services/event_service.py) | [ADR-002](adr/orchestration/ADR-002-event-ownership.md) |
| ✅ | Idempotency service (200/201/409) | [`services/idempotency_service.py`](../backend/app/services/idempotency_service.py) | [ADR-004](adr/orchestration/ADR-004-idempotency-contract.md) |
| ✅ | Worker leases + reclaim | [`services/run_lifecycle.py`](../backend/app/services/run_lifecycle.py), [`services/worker_registry.py`](../backend/app/services/worker_registry.py) | [STATE_MACHINE §4](STATE_MACHINE.md) |
| ✅ | Durable timers | [`services/timer_service.py`](../backend/app/services/timer_service.py) | [ADR-005](adr/orchestration/ADR-005-production-durability-policy.md) |
| ✅ | Retry policy | [`services/retry_policy.py`](../backend/app/services/retry_policy.py) | [STATE_MACHINE §6](STATE_MACHINE.md) |
| ✅ | Approval & signal substrate | [`services/approval_service.py`](../backend/app/services/approval_service.py), [`services/signal_service.py`](../backend/app/services/signal_service.py) | [STATE_MACHINE §3](STATE_MACHINE.md) |
| ✅ | Startup checks (production gates) | [`startup_checks.py`](../backend/app/startup_checks.py) | [ADR-005](adr/orchestration/ADR-005-production-durability-policy.md), [PRODUCTION_CONFIG §3](PRODUCTION_CONFIG.md) |
| ✅ | Vault secrets manager | [`secrets/manager.py`](../backend/app/secrets/manager.py) | [ADR-010](adr/010-secrets-management.md) |
| ✅ | 3-tier JWT auth (HS256 / Keycloak / Entra) | [`middleware/auth.py`](../backend/app/middleware/auth.py) | [ADR-011](adr/011-auth-flows.md) |
| ✅ | RBAC (4 built-in roles + custom) | [`middleware/rbac.py`](../backend/app/middleware/rbac.py) | — |
| ✅ | Tenant context (strict in production) | [`middleware/tenant.py`](../backend/app/middleware/tenant.py) | [ADR-012](adr/012-tenant-isolation.md) |
| ✅ | DLP (Presidio + regex fallback) | [`services/dlp_service.py`](../backend/app/services/dlp_service.py) | — |
| ✅ | Audit hash chain | [`services/audit_chain.py`](../backend/app/services/audit_chain.py) | [ADR-013](adr/013-audit-trail.md) |
| ✅ | Cost service (real LiteLLM token + rate card) | [`services/cost_service.py`](../backend/app/services/cost_service.py) | — |
| ✅ | Router scoring engine (DB-backed model registry) | [`services/router_service.py`](../backend/app/services/router_service.py) | — |
| ✅ | Metrics middleware (canonical metric set) | [`middleware/metrics_middleware.py`](../backend/app/middleware/metrics_middleware.py) | [`metrics-catalog.md`](metrics-catalog.md) |
| ✅ | WebSocket execution stream + replay | [`websocket/events_manager.py`](../backend/app/websocket/events_manager.py), [`websocket/manager.py`](../backend/app/websocket/manager.py) | — |

## 6. Frontend

| Status | Surface | Source | Tests |
|:---:|---|---|---|
| ✅ | Visual builder canvas (28 node types) | [`frontend/src/components/builder/`](../frontend/src/components/builder/) | yes |
| ✅ | Test Run live stream | [`TestRunPanel.tsx`](../frontend/src/components/builder/TestRunPanel.tsx) | [`TestRunPanel.test.tsx`](../frontend/src/tests/TestRunPanel.test.tsx) |
| ✅ | Executions detail (event replay) | [`ExecutionDetailPage.tsx`](../frontend/src/pages/ExecutionDetailPage.tsx), [`ExecutionsPage.tsx`](../frontend/src/pages/ExecutionsPage.tsx), [`RunHistoryPage.tsx`](../frontend/src/pages/RunHistoryPage.tsx) | yes |
| ✅ | DLP UI (Dashboard, Policies, Test, Detections) | [`DLPPage.tsx`](../frontend/src/pages/DLPPage.tsx) | yes |
| ✅ | Operations dashboard | [`DashboardPage.tsx`](../frontend/src/pages/DashboardPage.tsx) | yes |
| ✅ | API clients (`runs`, `events`) | [`frontend/src/api/`](../frontend/src/api/) | yes |
| ✅ | Backend type parity check | [`scripts/check-frontend-backend-parity.py`](../scripts/check-frontend-backend-parity.py) | CI gate `verify-contracts` |

## 7. Connectors (5 reference)

| Status | Connector | Source |
|:---:|---|---|
| ✅ | Postgres | [`integrations/connectors/postgres/`](../integrations/connectors) |
| ✅ | S3 | [`integrations/connectors/s3/`](../integrations/connectors) |
| ✅ | Slack | [`integrations/connectors/slack/`](../integrations/connectors) |
| ✅ | REST | [`integrations/connectors/rest/`](../integrations/connectors) |
| ✅ | Google Drive | [`integrations/connectors/google_drive/`](../integrations/connectors) |

Five connectors is the deliberate 1.0 surface. Additional connectors are deferred to Phase I — see [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md).

## 8. Verification gates

| Status | Gate | Script | CI job |
|:---:|---|---|---|
| ✅ | Unit (backend + gateway) | [`scripts/verify-unit.sh`](../scripts/verify-unit.sh) | `verify-unit` |
| ✅ | Integration | [`scripts/verify-integration.sh`](../scripts/verify-integration.sh) | `verify-integration` |
| ✅ | Frontend (typecheck + Vitest) | [`scripts/verify-frontend.sh`](../scripts/verify-frontend.sh) | `verify-frontend` |
| ✅ | Contracts (feature matrix + OpenAPI + parity) | [`scripts/verify-contracts.sh`](../scripts/verify-contracts.sh) | `verify-contracts` |
| ✅ | Vertical-slice REST canary | [`scripts/verify-slice.sh`](../scripts/verify-slice.sh), [`scripts/test-slice.sh`](../scripts/test-slice.sh) | `verify-slice` |
| ✅ | Feature-matrix validator | [`scripts/check-feature-matrix.py`](../scripts/check-feature-matrix.py) | `feature-matrix-validate` |
| ✅ | Grafana ↔ metrics parity | [`scripts/check-grafana-metric-parity.py`](../scripts/check-grafana-metric-parity.py) | called by `verify-contracts` |
| ✅ | Frontend ↔ backend type parity | [`scripts/check-frontend-backend-parity.py`](../scripts/check-frontend-backend-parity.py) | called by `verify-contracts` |
| ✅ | Load-test profiles | [`scripts/run-load-tests.sh`](../scripts/run-load-tests.sh) | nightly |
| ✅ | Chaos-test scenarios | [`scripts/run-chaos-tests.sh`](../scripts/run-chaos-tests.sh) | weekly |

## 9. Cross-references

- [`docs/feature-matrix.yaml`](feature-matrix.yaml) — canonical 206-entry inventory.
- [`docs/FEATURE_MATRIX.md`](FEATURE_MATRIX.md) — human-readable rendering, full list with caveats.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) — bounded contexts.
- [`docs/STATE_MACHINE.md`](STATE_MACHINE.md) — `WorkflowRun` lifecycle.
- [`docs/GAP_ANALYSIS.md`](GAP_ANALYSIS.md) — what's still missing and what's deferred.
- [`docs/PRODUCTION_CONFIG.md`](PRODUCTION_CONFIG.md) — env vars + startup gates.
