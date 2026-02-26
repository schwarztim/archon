# ⬡ Archon — Blitz Swarm Master Prompt
# Architecture Mapping · Flow Analysis · E2E Testing · Azure Model Wiring

> **Mode**: Swarm → Blitz
> **Project**: `~/Scripts/Archon` — Enterprise AI Orchestration Platform
> **Date Generated**: 2026-02-20

---

## 🎯 MISSION

Execute a **blitz-mode swarm** against the Archon platform to accomplish four objectives in parallel:

1. **Generate a complete architectural diagram** of every component, service, and integration
2. **Map every flow and process** end-to-end (agent execution, model routing, DLP, lifecycle, auth, cost tracking, connectors, mesh, edge, A2A)
3. **Perform exhaustive end-to-end testing** of every function, route, service, and agent
4. **Wire in all Azure OpenAI model deployments** to the Archon model router via the provided endpoint and API key

---

## 📐 OBJECTIVE 1 — ARCHITECTURAL DIAGRAM

Generate a comprehensive architecture diagram covering:

### Platform Layers
```
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND — React 19 · TypeScript · React Flow · shadcn/ui │
│  27 pages, visual agent builder, model router UI, DLP dash  │
├─────────────────────────────────────────────────────────────┤
│  API GATEWAY — FastAPI 0.115+ · 50+ route modules           │
│  Middleware: CORS → RequestID → Metrics → Audit → Tenant    │
│  → DLP → Auth (JWT/Keycloak/SAML) → RBAC/ABAC              │
├─────────────────────────────────────────────────────────────┤
│  SERVICES — 40+ service classes                              │
│  Agent · Router · Cost · DLP · Governance · Lifecycle        │
│  Connector · DocForge · A2A · MCP · Mesh · Edge · Wizard    │
├─────────────────────────────────────────────────────────────┤
│  ORCHESTRATION — LangGraph · LangChain · CrewAI              │
│  StateGraph execution, streaming WebSocket, step events      │
├─────────────────────────────────────────────────────────────┤
│  DATA — PostgreSQL 16 · Redis 7 · PGVector · LlamaIndex     │
├─────────────────────────────────────────────────────────────┤
│  SECURITY — Vault · OPA · Guardrails AI · NeMo Guardrails   │
├─────────────────────────────────────────────────────────────┤
│  INFRA — K8s · Helm · Terraform · ArgoCD · Prometheus        │
│  Grafana · OpenTelemetry · Jaeger · OpenSearch               │
└─────────────────────────────────────────────────────────────┘
```

### What to Map
- Every backend route module (`backend/app/routes/*.py` — 40+ files)
- Every service class (`backend/app/services/*.py` — 40+ files)
- Every database model (`backend/app/models/*.py` — 34 models)
- Every middleware in the stack (auth, audit, DLP, tenant, metrics, CORS)
- Every agent in the swarm (26 agents + Master Validator)
- Frontend page-to-API route mappings (27 pages → backend routes)
- External integrations: Vault, Keycloak, Prometheus, Grafana, Redis, PostgreSQL
- Infrastructure: Docker Compose services, K8s manifests, Helm charts, Terraform modules
- The 7-phase dependency graph from `agents/SWARM_OVERVIEW.md`

### Output Format
Produce:
- Mermaid diagram (system context, container, component levels — C4 model)
- Dependency graph of all 26 agents across 7 phases
- Data flow diagram for each major subsystem
- Integration map showing all external service connections

---

## 🔄 OBJECTIVE 2 — FLOW & PROCESS MAPPING

Map every flow end-to-end. For each flow, document: trigger → steps → services involved → data transformations → output → error paths.

### Critical Flows to Map

#### 2.1 Agent Execution Flow
```
User → POST /api/v1/agents/{id}/execute
  → Auth middleware (JWT/Keycloak validation)
  → Tenant isolation (row-level security)
  → DLP scan on input
  → Create Execution record
  → LangGraph StateGraph compilation from graph_definition
  → Step execution loop:
      → process_node → conditional → respond_node
      → Model Router selects provider (cost/latency/capability scoring)
      → Azure OpenAI API call via LiteLLM
      → Token usage + cost tracking (CostEngine)
      → WebSocket event streaming (step.started, step.completed, llm.response, tool.called)
  → DLP scan on output
  → Audit log entry
  → Return execution result
```

#### 2.2 Model Routing Flow
```
Agent requests model → RoutingRequest
  → RouterService evaluates RoutingRules (multi-factor scoring)
      → weight_cost, weight_latency, weight_capability, weight_sensitivity
  → Circuit breaker check per provider
  → Vault credential retrieval (vault_secret_path)
  → Provider health check (latency, error rate)
  → Fallback chain: primary → secondary → tertiary
  → RoutingDecision with selected provider + DecisionFactors
  → Cost attribution to tenant/user/agent
```

#### 2.3 DLP (Data Loss Prevention) Flow
```
Input/Output → DLP Middleware
  → Pattern matching: PII (SSN, credit card, email, phone), credentials, sensitive keywords
  → Policy lookup: per-tenant, per-sensitivity-level
  → Action: redact | mask | block | alert
  → Detection event logged
  → Audit trail entry
  → Modified content forwarded (or blocked)
```

#### 2.4 Authentication & Authorization Flow
```
Login → JWT (dev mode) or Keycloak OIDC or SAML 2.0
  → Token validation (JWKS-based, <5ms)
  → TenantMiddleware extracts tenant_id
  → RBAC permission check (7 predefined roles + custom)
  → ABAC policy evaluation (OPA)
  → MFA challenge if required (TOTP/WebAuthn/FIDO2)
  → Session creation (Redis-backed, idle/absolute timeout)
  → Audit log: login event
```

#### 2.5 Lifecycle & Deployment Flow
```
Agent version → canary deployment (configurable % traffic)
  → Health monitoring (error rate, latency, cost thresholds)
  → Auto-rollback if metrics exceed threshold
  → Gradual promotion to 100%
  → Vault credential rotation during deployment
  → Signed version commits
```

#### 2.6 Cost Engine Flow
```
LLM API call → token counter
  → CostEngine per-token pricing lookup
  → Cost attribution: per-request, per-agent, per-user, per-tenant
  → Budget threshold check → alert/block if exceeded
  → Chargeback report generation
  → OpenLLMetry integration
```

#### 2.7 Connector Hub Flow
```
User creates connector → OAuth flow (Vault credential storage)
  → Connector framework: 50+ adapters (DB, SaaS, Cloud, API)
  → Connection test → health check
  → Data retrieval/write operations
  → Credential rotation via Vault
```

#### 2.8 A2A (Agent-to-Agent) Protocol Flow
```
Agent A → Agent Card discovery
  → mTLS + OAuth federation
  → Task delegation with context
  → Cross-org boundary handling
  → Result aggregation
  → Cost attribution to originating agent
```

#### 2.9 Agent Mesh Flow
```
Federated agent → mesh registration
  → Cross-org collaboration
  → Vault isolation per org
  → Identity federation
  → Distributed execution
```

#### 2.10 Edge Runtime Flow
```
Edge deployment → offline auth (device-bound)
  → Local secrets store
  → Sync when connected
  → Graceful degradation
```

#### 2.11 Security Proxy Flow
```
Outbound AI call → Security Proxy
  → SAML termination
  → Credential injection from Vault
  → DLP scanning on traffic
  → Audit logging
  → Endpoint allow/block rules
```

#### 2.12 MCP Security Flow
```
MCP tool invocation → OAuth validation
  → Tool-level permission check
  → Sandbox mode enforcement
  → Vault integration for tool credentials
  → Audit trail
```

---

## 🧪 OBJECTIVE 3 — END-TO-END TESTING

### Test Infrastructure
- **Framework**: pytest + pytest-asyncio
- **Existing tests**: 85+ test files, 1100+ tests in `tests/` and `backend/tests/`
- **Categories**: Unit, Integration, E2E, Middleware, Security

### What to Test

#### 3.1 Backend Routes (40+ modules — every endpoint)
| Route Module | File | Key Endpoints |
|---|---|---|
| Agents | `routes/agents.py` | CRUD, execute, list, search |
| Agent Versions | `routes/agent_versions.py` | Create version, diff, rollback |
| Audit Logs | `routes/audit_logs.py` | List, filter, export |
| Auth | `routes/auth_routes.py` | Login, logout, refresh, MFA |
| Connectors | `routes/connectors.py` | CRUD, test connection, sync |
| Cost | `routes/cost.py` | Reports, budgets, alerts |
| Deployment | `routes/deployment.py` | Deploy, rollback, canary |
| DLP | `routes/dlp.py` | Policies, scan, detections |
| DocForge | `routes/docforge.py` | Upload, process, search |
| Edge | `routes/edge.py` | Register, sync, status |
| Executions | `routes/executions.py` | List, detail, cancel, stream |
| Governance | `routes/governance.py` | Policies, reviews, risk |
| Lifecycle | `routes/lifecycle.py` | Stages, promote, rollback |
| Marketplace | `routes/marketplace.py` | Browse, install, publish |
| MCP | `routes/mcp.py` | Servers, tools, invoke |
| MCP Interactive | `routes/mcp_interactive.py` | Live components |
| MCP Security | `routes/mcp_security.py` | Policies, OAuth, audit |
| Mesh | `routes/mesh.py` | Register, discover, invoke |
| Mobile | `routes/mobile.py` | SDK config, push, sync |
| Models | `routes/models.py` | CRUD, test, route, health |
| RedTeam | `routes/redteam.py` | Campaigns, attacks, reports |
| Router | `routes/router.py` | Rules, registry, route, test |
| SAML | `routes/saml.py` | SSO, metadata, assertion |
| Sandbox | `routes/sandbox.py` | Create, execute, teardown |
| SCIM | `routes/scim.py` | Users, groups, provision |
| Secrets | `routes/secrets.py` | Store, retrieve, rotate |
| Security Proxy | `routes/security_proxy.py` | Config, rules, audit |
| SentinelScan | `routes/sentinelscan.py` | Scan, discover, report |
| Settings | `routes/settings.py` | Get, update, validate |
| SSO | `routes/sso.py` | Config, providers, login |
| Templates | `routes/templates.py` | CRUD, import, export |
| Tenancy | `routes/tenancy.py` | Create, config, isolation |
| Tenants | `routes/tenants.py` | CRUD, billing, limits |
| Versioning | `routes/versioning.py` | Create, diff, merge |
| Wizard | `routes/wizard.py` | Start, steps, complete |
| Workflows | `routes/workflows.py` | CRUD, execute, schedule |
| A2A | `routes/a2a.py` | Cards, tasks, federation |
| Admin | `routes/admin.py` | System config, maintenance |
| Health | `health.py` | `/health`, `/api/v1/health` |

#### 3.2 Services (40+ — every public method)
Test every service class in `backend/app/services/` including:
- `agent_service.py` — CRUD, search, clone, export/import
- `router_service.py` — Route selection, fallback, health check, circuit breaker
- `model_service.py` — Provider registration, capability matching
- `cost_service.py` — Token tracking, budget enforcement, chargeback
- `dlp_service.py` — Pattern detection, policy enforcement, redaction
- `execution_service.py` — Create, stream, cancel, retry
- `connector_service.py` — All 50+ connector types
- `workflow_engine.py` — DAG execution, branching, parallel steps
- `a2a_service.py` — Federation, task delegation
- `mesh_service.py` — Discovery, invocation
- `edge_service.py` — Offline sync, degradation
- `mcp_security_service.py` — Tool OAuth, sandbox
- `sentinelscan_service.py` — Shadow AI detection
- `redteam_service.py` — Attack campaigns
- `governance_service.py` — Compliance, risk scoring
- `lifecycle_service.py` — Canary, rollback, promotion
- `wizard_service.py` — NL-to-agent pipeline
- `template_service.py` — Template management
- `marketplace_service.py` — Publishing, installation
- `docforge_service.py` — Document processing pipeline

#### 3.3 Middleware Stack
- Auth middleware (JWT, Keycloak, SAML, API Key)
- Tenant isolation middleware (row-level security)
- DLP middleware (input/output scanning)
- Audit middleware (action logging)
- Metrics middleware (Prometheus counters)
- RBAC middleware (permission checking)
- CORS middleware (origin validation)

#### 3.4 LangGraph Execution Engine
- `backend/app/langgraph/` — StateGraph compilation, node execution, conditional routing
- Agent state management (messages, current_step, output, error)
- WebSocket streaming of execution events
- Error handling and retry logic

#### 3.5 Security & Enterprise
- Vault integration (secret store, retrieve, rotate, PKI)
- Keycloak OIDC flow
- SAML 2.0 SSO
- SCIM 2.0 user provisioning
- MFA (TOTP, WebAuthn)
- Red-team attack scenarios
- DLP pattern coverage
- Guardrails enforcement

#### 3.6 Existing Test Suites to Run
```bash
# Run all existing tests first
cd ~/Scripts/Archon && python -m pytest tests/ backend/tests/ -v --tb=short

# Individual agent tests
python -m pytest tests/test_agent01/ through tests/test_agent25/

# E2E tests
python -m pytest tests/test_e2e/

# Security tests
python -m pytest tests/test_auth/ tests/test_secrets/ tests/test_mcp_security/ tests/test_security_proxy/ tests/test_redteam/ tests/test_sentinelscan/

# Integration tests
python -m pytest tests/integration/ tests/test_a2a/ tests/test_mesh/ tests/test_edge/

# Middleware tests
python -m pytest tests/test_connectors/ tests/test_docforge/ tests/test_mcp/
```

---

## 🔌 OBJECTIVE 4 — AZURE OPENAI MODEL WIRING

### Connection Details

| Parameter | Value |
|---|---|
| **Endpoint** | `https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com` |
| **API Path** | `/openai/deployments/{deployment-name}/chat/completions` |
| **API Version** | `2025-01-01-preview` |
| **API Key** | `REDACTED_API_KEY` |
| **Provider Type** | `azure_openai` (via LiteLLM) |

### Full Model Deployment Registry

Wire **all** of the following deployments into Archon's Model Router (`/api/v1/router/registry` and `/api/v1/models`):

#### Chat / Completion Models (Primary)

| Deployment Name | Model | TPM | TPM Limit | Tier | Capabilities | Priority |
|---|---|---|---|---|---|---|
| `model-router` | model-router 2025-11-18 | 250 | 250,000 | Global Standard | chat, routing | Primary Router |
| `modelrouter` | model-router 2025-11-18 | 100 | 100,000 | Global Standard | chat, routing | Backup Router |
| `gpt-5.2` | gpt-5.2 2025-12-11 | 250 | 250,000 | Global Standard | chat, code, vision, function_calling | Tier 1 — Flagship |
| `gpt-5.2-chat` | gpt-5.2-chat 2025-12-11 | 250 | 250,000 | Global Standard | chat | Tier 1 — Chat |
| `gpt-5-mini` | gpt-5-mini 2025-08-07 | 250 | 250,000 | Global Standard | chat, code, function_calling | Tier 2 — Fast |
| `gpt-5-chat` | gpt-5-chat 2025-08-07 | 250 | 250,000 | Global Standard | chat | Tier 2 — Chat |
| `qrg-gpt-4.1` | gpt-4.1 2025-04-14 | 250 | 250,000 | Global Standard | chat, code, vision, function_calling | Tier 3 |
| `qrg-gpt-4.1-mini` | gpt-4.1-mini 2025-04-14 | 250 | 250,000 | Global Standard | chat, code, function_calling | Tier 3 — Fast |
| `gpt-4` | gpt-4o 2024-11-20 | 6 | 6,000 | Standard | chat, vision, function_calling | Tier 4 — Legacy |
| `gpt-4o-mini` | gpt-4o-mini 2024-07-18 | 5,055 | 5,055,000 | Global Standard | chat, function_calling | Tier 4 — High Volume |

#### Codex Models (Code Generation)

| Deployment Name | Model | TPM | TPM Limit | Tier | Capabilities | Priority |
|---|---|---|---|---|---|---|
| `gpt-5.2-codex` | gpt-5.2-codex 2026-01-14 | 10,000 | 10,000,000 | Global Standard | code, chat, function_calling | Codex Tier 1 |
| `gpt-5.1-codex-max` | gpt-5.1-codex-max 2025-12-04 | 10,000 | 10,000,000 | Global Standard | code, chat, function_calling | Codex Tier 2 |
| `gpt-5.1-codex-mini` | gpt-5.1-codex-mini 2025-11-13 | 10,000 | 10,000,000 | Global Standard | code, chat | Codex Tier 3 — Fast |

#### Reasoning Models

| Deployment Name | Model | TPM | TPM Limit | Tier | Capabilities | Priority |
|---|---|---|---|---|---|---|
| `o1-experiment` | o1 2024-12-17 | 250 | 1,500,000 | Global Standard | reasoning, chat | Reasoning Tier 1 |
| `qrg-o3-mini` | o3-mini 2025-01-31 | 250 | 2,500,000 | Global Standard | reasoning, chat | Reasoning Tier 2 |
| `o1-mini` | o4-mini 2025-04-16 | 250 | 250,000 | Global Standard | reasoning, chat | Reasoning Tier 3 |

#### Embedding Models

| Deployment Name | Model | TPM | TPM Limit | Tier | Capabilities |
|---|---|---|---|---|---|
| `text-embedding-3-small-sandbox` | text-embedding-3-small v1 | 120 | 120,000 | Standard | embedding |
| `text-embeddings-3-large-sandbox` | text-embedding-3-large v1 | 120 | 120,000 | Standard | embedding |
| `qrg-embedding-experimental` | text-embedding-ada-002 v2 | 120 | 120,000 | Standard | embedding (legacy) |

#### Specialty Models

| Deployment Name | Model | TPM | TPM Limit | Tier | Capabilities |
|---|---|---|---|---|---|
| `gpt-realtime` | gpt-realtime 2025-08-28 | 10 | 100,000 | Global Standard | realtime, streaming |
| `gpt-4o-mini-realtime-preview` | gpt-4o-mini-realtime-preview 2024-12-17 | 6 | 6,000 | Global Standard | realtime, streaming |
| `whisper-sandbox` | whisper 001 | 3 | N/A | Standard | speech-to-text |

#### Legacy / Experimental Aliases

| Deployment Name | Actual Model | TPM | Notes |
|---|---|---|---|
| `qrg-gpt35turbo16k-experimental` | gpt-4.1-mini | 120 | Legacy alias — routes to 4.1-mini |
| `qrg-gpt35turbo4k-experimental` | gpt-4.1-mini | 120 | Legacy alias — routes to 4.1-mini |
| `qrq-gpt4turbo-experimental` | gpt-4.1 | 80 | Legacy alias — routes to 4.1 |
| `qrg-gpt4o-experimental` | gpt-4o 2024-05-13 | 1,000 | Legacy alias — routes to 4o |

### Wiring Instructions

#### Step 1 — Environment Configuration
Add to `.env`:
```bash
# Azure OpenAI — QRG Sandbox
AZURE_OPENAI_ENDPOINT=https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com
AZURE_OPENAI_API_KEY=REDACTED_API_KEY
AZURE_OPENAI_API_VERSION=2025-01-01-preview
```

#### Step 2 — Register Provider in Model Router
Register Azure OpenAI as a provider via the router service:
```python
# Provider registration payload
{
    "provider_id": "azure-qrg-sandbox",
    "provider_type": "azure_openai",
    "display_name": "Azure OpenAI — QRG Sandbox Experiment",
    "endpoint": "https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com",
    "api_version": "2025-01-01-preview",
    "vault_secret_path": "secret/providers/azure-qrg-sandbox",
    "health_check_interval_s": 30,
    "is_active": true,
    "capabilities": ["chat", "code", "embedding", "reasoning", "realtime", "speech-to-text"],
    "config": {
        "max_retries": 3,
        "timeout_s": 120,
        "rate_limit_rpm": 250
    }
}
```

#### Step 3 — Register Each Model in Registry
For each deployment, register in the model registry. Example for the flagship model:
```python
# POST /api/v1/router/registry
{
    "model_id": "gpt-5.2",
    "deployment_name": "gpt-5.2",
    "provider_id": "azure-qrg-sandbox",
    "display_name": "GPT-5.2 (Azure QRG Sandbox)",
    "capabilities": ["chat", "code", "vision", "function_calling"],
    "cost_per_1k_input_tokens": 0.005,
    "cost_per_1k_output_tokens": 0.015,
    "max_tokens": 128000,
    "tpm_limit": 250000,
    "tier": "global_standard",
    "is_active": true,
    "config": {
        "azure_deployment": "gpt-5.2",
        "api_version": "2025-01-01-preview"
    }
}
```

#### Step 4 — Configure Routing Rules
```python
# Routing rule: Cost-optimized (default)
{
    "name": "cost-optimized-default",
    "strategy": "balanced",
    "weight_cost": 0.4,
    "weight_latency": 0.3,
    "weight_capability": 0.2,
    "weight_sensitivity": 0.1,
    "fallback_chain": ["gpt-5.2", "gpt-5-mini", "gpt-4o-mini"],
    "is_active": true
}

# Routing rule: Code generation
{
    "name": "code-generation",
    "strategy": "capability_first",
    "weight_capability": 0.6,
    "weight_latency": 0.2,
    "weight_cost": 0.1,
    "weight_sensitivity": 0.1,
    "conditions": {"capability_required": "code"},
    "fallback_chain": ["gpt-5.2-codex", "gpt-5.1-codex-max", "gpt-5.1-codex-mini"],
    "is_active": true
}

# Routing rule: Reasoning tasks
{
    "name": "reasoning-tasks",
    "strategy": "capability_first",
    "weight_capability": 0.7,
    "weight_latency": 0.1,
    "weight_cost": 0.1,
    "weight_sensitivity": 0.1,
    "conditions": {"capability_required": "reasoning"},
    "fallback_chain": ["o1-experiment", "qrg-o3-mini", "o1-mini"],
    "is_active": true
}

# Routing rule: Embedding
{
    "name": "embedding-pipeline",
    "strategy": "cost_optimized",
    "conditions": {"capability_required": "embedding"},
    "fallback_chain": ["text-embedding-3-small-sandbox", "text-embeddings-3-large-sandbox", "qrg-embedding-experimental"],
    "is_active": true
}

# Routing rule: High-volume (use highest TPM)
{
    "name": "high-volume",
    "strategy": "throughput_first",
    "conditions": {"min_tpm": 1000},
    "fallback_chain": ["gpt-4o-mini", "qrg-gpt4o-experimental", "gpt-5.2-codex"],
    "is_active": true
}
```

#### Step 5 — Validation Test
```bash
# Direct API test — verify endpoint connectivity
curl -X POST \
  "https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com/openai/deployments/model-router/chat/completions?api-version=2025-01-01-preview" \
  -H "Content-Type: application/json" \
  -H "api-key: REDACTED_API_KEY" \
  -d '{
    "messages": [{"role": "user", "content": "Hello, confirm you are operational. Respond with: ARCHON_READY"}],
    "max_tokens": 50,
    "temperature": 0
  }'

# Test each deployment via Archon router
# POST /api/v1/router/route
{
    "capability": "chat",
    "input_text": "Test routing — which model am I?",
    "data_classification": "general",
    "latency_tier": "fast",
    "tenant_id": "default"
}
```

#### Step 6 — LiteLLM Configuration
Update LiteLLM config for Azure OpenAI proxy:
```python
# In backend/app/services/router_service.py or litellm config
import litellm

litellm.api_key = "REDACTED_API_KEY"
litellm.api_base = "https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com"
litellm.api_version = "2025-01-01-preview"

# Call via LiteLLM with azure/ prefix
response = litellm.completion(
    model="azure/gpt-5.2",  # deployment name
    messages=[{"role": "user", "content": "Hello"}],
    api_key="REDACTED_API_KEY",
    api_base="https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com",
    api_version="2025-01-01-preview"
)
```

---

## ⚡ SWARM EXECUTION — BLITZ MODE

### Blitz Configuration
```
Mode: blitz
Parallel workstreams: 4
Timeout per phase: aggressive
Quality gate: 7/10 minimum
```

### Workstream Allocation

| Workstream | Agent Focus | Objective |
|---|---|---|
| **WS-0** | Architecture Mapper | Objective 1 — Diagrams & component mapping |
| **WS-1** | Flow Analyzer | Objective 2 — End-to-end flow documentation |
| **WS-2** | Test Engineer | Objective 3 — E2E test execution & gap analysis |
| **WS-3** | Integration Engineer | Objective 4 — Azure model wiring & validation |

### Phase Execution

#### Phase 1 — Discovery (All workstreams parallel)
- WS-0: Scan all source files, build component inventory
- WS-1: Trace all route → service → model → DB paths
- WS-2: Run existing test suite, identify gaps
- WS-3: Verify Azure endpoint connectivity, enumerate deployments

#### Phase 2 — Build (All workstreams parallel)
- WS-0: Generate Mermaid architecture diagrams (C4: context, container, component)
- WS-1: Document all 12+ flows with step-by-step breakdowns
- WS-2: Write missing tests, run full E2E suite
- WS-3: Register all 26 model deployments in router, configure rules

#### Phase 3 — Validate (Quality gate)
- WS-0: Verify diagram completeness against codebase
- WS-1: Cross-reference flows against actual code paths
- WS-2: All tests passing, coverage report
- WS-3: Route test calls through each model, verify responses

#### Phase 4 — Merge & Report
- Combine all outputs into unified report
- Architecture diagrams + flow maps + test results + model status
- Identify any remaining gaps or issues

---

## 📊 SUCCESS CRITERIA

| Criteria | Target |
|---|---|
| Architecture diagram covers all 40+ routes | ✅ 100% |
| Architecture diagram covers all 40+ services | ✅ 100% |
| Architecture diagram covers all 34 models | ✅ 100% |
| All 12+ major flows documented | ✅ 100% |
| Existing test suite passes | ✅ 1100+ tests |
| New E2E tests for model router wiring | ✅ Created |
| All 26 Azure deployments registered | ✅ 26/26 |
| Routing rules configured (5+ rules) | ✅ 5+ |
| Direct API connectivity verified | ✅ curl test passes |
| LiteLLM integration functional | ✅ Completion call succeeds |
| Fallback chains tested | ✅ All chains validated |
| Cost tracking wired for Azure models | ✅ Token tracking active |

---

## 🚀 LAUNCH COMMAND

```
Use swarm with blitz mode on ~/Scripts/Archon:
1. Map the complete architecture with Mermaid C4 diagrams
2. Document every flow and process end-to-end
3. Run and extend the full E2E test suite
4. Wire all 26 Azure OpenAI deployments into the model router using:
   - Endpoint: https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com
   - API Key: REDACTED_API_KEY
   - API Version: 2025-01-01-preview
   - Use LiteLLM azure/ prefix for all model calls
   - Configure routing rules: cost-optimized, code-generation, reasoning, embedding, high-volume
   - Validate every deployment with a test completion call
```
