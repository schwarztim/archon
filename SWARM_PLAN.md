# Archon Platform — Comprehensive Swarm Execution Plan v2

## Mission

Fix every broken feature in Archon, harden all stubs into production-ready DB-backed implementations, build the MCP Host Gateway per the end-state architecture, and **validate everything works end-to-end** using Docker-based subprocess testing with Playwright (frontend) and pytest (backend) against a running stack.

**Constraint:** Do NOT modify the Open Swarm MCP server itself — it is already updated and ready. This plan is the workload.

---

## Context: What Archon Is

Archon is an Enterprise AI Orchestration & Governance Platform. It provides:
- **Agent Builder** — visual drag-and-drop agent construction (React Flow)
- **Model Router** — intelligent multi-model routing with cost/latency/capability scoring
- **Workflow Engine** — DAG-based workflow execution with LangGraph agents
- **Marketplace** — template and agent package distribution
- **Governance** — RBAC, DLP, audit trails, compliance policies
- **Lifecycle Management** — agent deployment, health monitoring, promotion
- **Secrets Management** — HashiCorp Vault integration
- **Multi-tenancy** — tenant isolation across all resources
- **MCP Security** — tool authorization, sandboxing, consent management

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI 0.115+, SQLModel, asyncpg, PostgreSQL 16, Redis 7, Celery, LangGraph, LiteLLM, structlog |
| Frontend | React 19, TypeScript 5.7, Vite 6.2, Tailwind CSS 3, Zustand, TanStack Query, @xyflow/react 12, Recharts |
| Auth | Keycloak 26 (dev mode) + HS256 dev bypass; RBAC with 4 hardcoded roles |
| Infra | Docker Compose (10 services), Helm charts, Terraform scaffolds, ArgoCD, Prometheus, Grafana |
| Tests | ~110 test files (backend only), no frontend test runner, no integration tests against running stack |
| CI/CD | GitHub Actions (lint → test → build → security-scan; CD pushes to GHCR) |

### Repository Layout

```
/Users/timothy.schwarz/archon/
├── backend/
│   └── app/
│       ├── main.py                 # FastAPI app factory, 48 router registrations
│       ├── config.py               # pydantic-settings, ARCHON_ env prefix
│       ├── health.py               # /health, /api/v1/health, /ready
│       ├── middleware/
│       │   ├── auth.py             # JWT validation (HS256 dev / RS256 Keycloak)
│       │   ├── rbac.py             # Role-based access (in-memory only)
│       │   ├── tenant.py           # Tenant extraction from JWT/header
│       │   ├── dlp_middleware.py   # DLP scanning on execution I/O
│       │   ├── audit_middleware.py # Audit log on mutating requests
│       │   └── metrics_middleware.py
│       ├── models/                 # 32 SQLModel/Pydantic model files
│       ├── routes/                 # 30+ route modules
│       ├── services/               # 25+ service modules
│       └── secrets/                # Vault integration (manager.py, rotation.py, pki.py)
├── frontend/
│   └── src/
│       ├── pages/                  # 30 React pages
│       ├── components/             # 25 component directories
│       └── api/                    # 20 API client modules
├── contracts/openapi.yaml          # 3,339-line OpenAPI 3.1 spec
├── docker-compose.yml              # 10 services
├── scripts/                        # smoke_test.sh, validate_platform.sh, seed_templates.py
├── infra/                          # Helm, Terraform, ArgoCD, Prometheus, Grafana
└── tests/                          # 110 test files across 40 directories
```

### Docker Compose Services

| Service | Image | Port | Health Check |
|---------|-------|------|-------------|
| postgres | postgres:16 | 5432 | pg_isready |
| redis | redis:7 | 6379 | redis-cli ping |
| backend | ./backend | 8000 | /health |
| frontend | ./frontend | 3000 | depends on backend |
| vault | hashicorp/vault:1.15 | 8200 | vault status |
| keycloak | keycloak:26.0 | 8180 | depends on nothing |
| vault-init | hashicorp/vault:1.15 | — | one-shot |
| prometheus | prom/prometheus | 9090 | depends on backend |
| grafana | grafana/grafana | 3001 | depends on prometheus |
| worker | ./backend | — | depends on postgres, redis |

---

## Target Architecture

Source: `/Users/timothy.schwarz/Documents/architecture-endstate.drawio` (2-page draw.io)

### Page 1: Infrastructure & Data Flow
"Enterprise MCP Host Gateway — Production Infrastructure & Data Flow"
"End-State Target: Internal-only via Netskope NPA (Zero Trust Network Access)"

**Data flow:**
1. Client authenticates with **Azure Entra ID** via OAuth2 (MSAL), receives JWT with group OID claims
2. Client connects via **Netskope NPA** tunnel (device posture verified), sends request with Bearer JWT
3. NPA routes to **Azure API Management** (internal); APIM validates JWT, applies rate limit (100/60s), routes to Container App
4-6. **Azure Container Apps** (FastAPI): EntraAuthMiddleware → Route match → Tool execute → Return result
7. Success optionally triggers **Azure Logic Apps** QA workflow → Azure DevOps work items (approved) or Sentinel alert (rejected)

**Components:**
- **MCP Clients**: Claude Desktop/Code, Custom MCP App, Browser SPA, curl/httpx — all require Netskope Client + Bearer JWT
- **Azure Entra ID**: App Registration `MCP-Host-Gateway`, Scopes `api://mcp-host-gateway`, Groups `MCP-Admins`, `MCP-Users-Finance`
- **Azure APIM**: validate-jwt → rate-limit (100/60s) → set-backend-service → diagnostics → Log Analytics → Sentinel
- **Azure Container Apps**: `mcp-host-gateway` (FastAPI + Uvicorn + Gunicorn)
  - Middleware: CORSMiddleware → EntraAuthMiddleware → GuardrailsMiddleware
  - Routes: `GET /mcp/capabilities` (filter by user_groups), `POST /mcp/tools/{tool_id}/invoke`
  - Plugin Loader: Hot-load `plugins/*.yaml` + watchfiles + Pydantic validation
  - Dispatch: `can_forward?` → false: built-in AI via Azure OpenAI | true: forward to agent backend
  - QA Workflow Trigger: POST result to Logic Apps trigger URL
- **Azure OpenAI**: gpt-5.2, gpt-5.2-codex, claude-sonnet
- **Azure Sentinel**: SIEM + anomaly detection (KQL: flag >10 calls/5min/user/tool)
- **Redis**: Token cache + rate limit state + improvement pipeline store

**Plugin YAML format:**
```yaml
name: finance-revenue-mcp
backend_url: https://...
required_groups:
  - MCP-Users-Finance
tools:
  - id: get_revenue
    input_schema: {...}
    model: claude-sonnet
    can_forward: false
```

### Page 2: Logical Architecture
Three trust zones:
1. **MANAGED DEVICES** (Netskope Client required) → Auth via Entra ID
2. **DMZ** (Netskope NPA + APIM) → validate-jwt → rate-limit → set-backend → diagnostics
3. **TRUSTED** (Azure Container Apps VNet) → FastAPI middleware chain → dispatch → tools

**Improvement pipeline** (self-improvement loop):
- Improvement Engine collects gap data from Redis → Azure OpenAI gpt-5.2-codex analysis → proposals stored in Redis → human review via Logic Apps

---

## Credentials & APIs for Testing

### Azure OpenAI (all same API key)

| Purpose | Endpoint | Model |
|---------|----------|-------|
| Primary AI | `https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview` | `gpt-5.2-codex` |
| Mini/test | Same endpoint | Same model (lighter prompts) |
| Embeddings | `https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/deployments/qrg-embedding-experimental/embeddings?api-version=2023-05-15` | `qrg-embedding-experimental` |

**API Key:** `b664331212b54911969792845dee8ba9`

**cURL example:**
```bash
curl -X POST "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer b664331212b54911969792845dee8ba9" \
  -d '{"messages": [{"role": "user", "content": "hello"}], "max_completion_tokens": 100, "model": "gpt-5.2-codex"}'
```

### OIDC / Azure Entra ID

| Field | Value |
|-------|-------|
| Discovery | `https://login.microsoftonline.com/ff3213cc-c3f6-45d4-a104-8f7823656fec/v2.0/.well-known/openid-configuration` |
| Tenant ID | `ff3213cc-c3f6-45d4-a104-8f7823656fec` |
| Client ID | `8adab7b8-a4bc-497b-90b9-53fd89de5900` |
| Client Secret | TBD (may not be needed for public client flow) |

---

## Broken Features — Root Cause Analysis

### 13 Broken Features with Specific Root Causes

| # | Feature | Severity | Root Cause | Files |
|---|---------|----------|-----------|-------|
| 1 | **Templates "create from seed"** | HIGH | Seed script is CLI-only (`backend/scripts/seed_templates.py`), no HTTP trigger. Frontend "create from seed" button has no backend endpoint. | `routes/templates.py`, `scripts/seed_templates.py` |
| 2 | **Agent install** | HIGH | Marketplace enterprise endpoints have TRIPLE prefix: `include_router(prefix="/api/v1")` + `APIRouter(prefix="/marketplace")` + route paths starting with `/api/v1/marketplace/...` = `/api/v1/marketplace/api/v1/marketplace/...`. Also FK violations on install. | `routes/marketplace.py:325-461`, `main.py:L170` |
| 3 | **Secrets "failed to load"** | HIGH | Registration metadata stored in-memory (`_registrations` dict). When Vault is down, fallback is non-persistent. Secrets list from Vault requires Vault running. | `routes/secrets.py`, `secrets/manager.py` |
| 4 | **Audit log page** | MEDIUM | Frontend calls `GET /api/v1/audit-logs/` (dash) but backend serves `GET /api/v1/audit/logs/` (slash). Field name mismatches between frontend types and backend response. | `routes/audit_logs.py:L20`, `frontend/src/api/governance.ts:L221` |
| 5 | **Sentinel scan (white screen)** | HIGH | `enterprise_router` (prefix `/sentinel`) defined at `sentinelscan.py:297` but **never imported/registered** in `main.py`. Frontend navigates to enterprise endpoints that don't exist → 404 → white screen. Also duplicate `GET /posture` conflict between `router` and `scan_router`. | `routes/sentinelscan.py:297`, `main.py:L45` |
| 6 | **System health** | MEDIUM | Frontend (if calling `/health`) gets liveness probe only (returns `{"status": "healthy"}`). Full health at `/api/v1/health` checks DB + Redis + Vault but frontend may not call correct path. | `health.py`, frontend health API client |
| 7 | **Dark/light mode** | HIGH | 100+ hardcoded `bg-[#0f1117]` and `border-[#2a2d37]` across 25+ files. `tailwind.config.ts` has proper CSS custom properties but they're unused. Theme toggle only exists in Builder page, not globally. No `ThemeProvider`. | `frontend/src/**/*.tsx` (25+ files), `tailwind.config.ts` |
| 8 | **RBAC custom roles** | HIGH | Custom roles stored in-memory only (`rbac.py` has 4 hardcoded roles: admin, operator, viewer, agent_creator). No DB table, no custom role CRUD wired to persistence. "Failed to create custom role" because it only writes to a dict that resets on restart. | `middleware/rbac.py`, no DB model |
| 9 | **Workflows** | HIGH | Manual trigger only. Schedule can be stored but **no background scheduler** fires them. Webhook/event/signal/query triggers not implemented. All data in-memory (`_workflows`, `_workflow_runs`, `_workflow_schedules`, `_workflow_run_steps`). | `services/workflow_service.py`, `routes/workflows.py` |
| 10 | **Rate limiting** | HIGH | **No rate-limit middleware exists.** Config has no rate limit settings. `routes/settings.py` returns hardcoded stubs (`rate_limit_rpm: 1000`). Not enforced at any layer. | No `middleware/rate_limit.py`, `config.py` |
| 11 | **API keys** | MEDIUM | In-memory `_api_keys_store` dict in `routes/settings.py`. Not scoped to workflows. Not used for rate limiting. Keys lost on restart. | `routes/settings.py` |
| 12 | **Teams integration** | MEDIUM | Only Slack webhook supported. No Microsoft Teams/Graph API integration. Frontend has SSO config forms but no backend Teams connector. | `routes/settings.py`, `services/connectors/` |
| 13 | **Mail/SMTP** | LOW | SMTP config fields exist in settings but `send_test_notification` for email is a stub — no actual SMTP sending code. | `routes/settings.py` |

### 14 Services with 37 In-Memory Variables (Need DB Migration)

| # | Service | In-Memory Vars | Lines | DB Table? |
|---|---------|---------------|-------|-----------|
| 1 | `sentinelscan_service.py` | `_findings_store`, `_scan_history_store`, `_remediation_audit` | 1029-1031 | Partial |
| 2 | `security_proxy_service.py` | `_upstream_store`, `_metrics_store` | 46-47 | No |
| 3 | `mcp_security_service.py` | `_tool_registry`, `_consent_store` | 50-51 | Partial |
| 4 | `lifecycle_service.py` | 8 dicts: `_scheduled_jobs`, `_agent_states`, `_deployments`, `_metrics_store`, `_approval_gates`, `_environments`, `_deployment_history`, `_health_metrics` | 53-60 | Partial (3 tables vs 8 dicts) |
| 5 | `mcp_interactive_service.py` | `_sessions`, `_component_types`, `_update_queues` | 25-27 | No |
| 6 | `docforge_service.py` | `_documents`, `_chunks`, `_permissions`, `_collections` | 41-44 | No |
| 7 | `deployment_service.py` | `_deployments`, `_component_replicas` | 35-36 | No |
| 8 | `connectors/oauth.py` | `_pending_states` | 58 | No |
| 9 | `connector_service.py` | `_pending_oauth`, `_connectors` | 96, 116 | Partial |
| 10 | `sandbox_service.py` | `_sessions`, `_sandboxes`, `_executions`, `_benchmark_sets` | 124-127 | No |
| 11 | `scim_service.py` | `_users`, `_groups` | 42-43 | No |
| 12 | `redteam_service.py` | `_scan_store` | 77 | No |
| 13 | `secret_access_logger.py` | `_entries` | 37 | Yes (unused!) |
| 14 | `router_service.py` | `_circuit_breaker` (singleton) | 56-58, 99 | No (acceptable as ephemeral) |

---

## Workstreams

### WS-0: Health Assessment & Baseline

**Manager:** manager-anthropic (Testing focus)
**Workers:** worker-tester, worker-debugger
**Priority:** BLOCKING — must complete before all other workstreams
**Estimated scope:** Read-only, produces report

#### Tasks
1. Run `PYTHONPATH=backend python3 -m pytest tests/ --no-header -q` from project root — capture full output
2. Run `bash scripts/smoke_test.sh` — capture output
3. Run `bash scripts/validate_platform.sh` — capture output
4. Attempt Docker builds: `docker build -t archon-backend:test ./backend` and `docker build -t archon-frontend:test ./frontend`
5. Run `ruff check backend/` for lint status
6. Run `cd frontend && npm install && npm run build` — capture errors
7. Run `cd frontend && npx tsc --noEmit` — count TypeScript errors
8. Test Azure OpenAI connectivity:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" -X POST \
     "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer b664331212b54911969792845dee8ba9" \
     -d '{"messages":[{"role":"user","content":"ping"}],"max_completion_tokens":5,"model":"gpt-5.2-codex"}'
   ```
9. Test OIDC discovery endpoint: `curl -s "https://login.microsoftonline.com/ff3213cc-c3f6-45d4-a104-8f7823656fec/v2.0/.well-known/openid-configuration" | python3 -m json.tool`

#### Acceptance Criteria
- `docs/HEALTH_REPORT.md` exists with: test pass/fail counts, smoke test results, Docker build status, lint violations, frontend build status, import errors, 500-status routes, Azure OpenAI connectivity, OIDC discovery response
- Report identifies specific files/lines for every failure

#### Output
Save to `docs/HEALTH_REPORT.md`

---

### WS-1: Backend Route & URL Fixes

**Manager:** manager-anthropic (Backend focus)
**Workers:** worker-coder, worker-debugger
**Priority:** HIGH — depends on WS-0
**File scope:** `backend/app/routes/marketplace.py`, `backend/app/routes/sentinelscan.py`, `backend/app/routes/audit_logs.py`, `backend/app/health.py`, `backend/app/main.py`

#### Tasks

**1. Fix marketplace triple-prefix bug**
- File: `backend/app/routes/marketplace.py` lines 325-461
- Problem: Enterprise route decorators include full paths like `@router.post("/api/v1/marketplace/publishers")` but the router already has `prefix="/marketplace"` and is registered with `prefix=settings.API_PREFIX` (`/api/v1`)
- Fix: Strip the `/api/v1/marketplace` prefix from all enterprise route decorators (lines 325, 342, 360, 378, 410, 429, 446, 461), leaving just the relative path (e.g., `@router.post("/publishers")`)
- Verify: `GET /api/v1/marketplace/categories` returns 200, `POST /api/v1/marketplace/packages/{id}/install` returns 200/422 (not 404)

**2. Fix sentinel scan white screen**
- File: `backend/app/routes/sentinelscan.py` line 297 — `enterprise_router = APIRouter(prefix="/sentinel")`
- File: `backend/app/main.py` line 45 — import only imports `router, scan_router`
- Fix: Add `enterprise_router` to the import and register it: `app.include_router(enterprise_router, prefix=settings.API_PREFIX, tags=["sentinel-enterprise"])`
- Also fix duplicate `GET /posture` conflict: rename `scan_router`'s version to `GET /posture/enhanced` or merge the two
- Verify: `GET /api/v1/sentinel/discover` returns 200, `POST /api/v1/sentinel/scan-credentials` returns 200/422, frontend Sentinel page loads without white screen

**3. Fix audit log URL mismatch**
- Backend: `backend/app/routes/audit_logs.py` line 20 — router prefix is `/audit/logs`
- Frontend: `frontend/src/api/governance.ts` line 221 — calls `/audit-logs/` (dash, not slash)
- Fix option A (preferred): Change the backend router prefix from `/audit/logs` to `/audit-logs` to match frontend convention
- Fix option B: Change the frontend API call from `/audit-logs/` to `/audit/logs/`
- Also fix any field name mismatches between frontend TypeScript types and backend response schema
- Verify: Frontend audit log page loads and displays entries

**4. Fix system health endpoint**
- File: `backend/app/health.py` — `GET /health` (liveness), `GET /api/v1/health` (full check with DB+Redis+Vault status)
- Verify both endpoints work. If the frontend health page calls the wrong one, fix the frontend API client to call `/api/v1/health`
- Verify: System health page shows DB, Redis, Vault status

#### Acceptance Criteria
- All 4 route bugs fixed with no regressions
- `ruff check` passes on modified files
- Existing tests still pass
- Each fix verified with curl or TestClient

---

### WS-2: In-Memory → Database Migration (Critical Services)

**Manager:** manager-openai (Backend focus)
**Workers:** worker-coder, worker-tester
**Priority:** HIGH — depends on WS-0
**File scope:** `backend/app/services/`, `backend/app/models/`, `backend/app/routes/settings.py`, `backend/app/middleware/rbac.py`

Focus on the **7 most critical** in-memory services. The remaining 7 (security_proxy, mcp_interactive, docforge, deployment, sandbox, redteam, connector) can be left as stubs for now since they're secondary features.

#### Tasks

**1. Workflow service → DB**
- File: `backend/app/services/workflow_service.py`
- Remove: `_workflows`, `_workflow_runs`, `_workflow_run_steps`, `_workflow_schedules` (4 in-memory dicts)
- Add SQLModel tables if not exist: `Workflow`, `WorkflowRun`, `WorkflowRunStep`, `WorkflowSchedule` in `backend/app/models/workflow.py`
- Wire all CRUD operations to use `async_session_factory`
- Add proper error handling (404 for not found, 409 for conflicts)

**2. Implement Temporal-style workflow invocation**
- Reference: https://github.com/temporalio — the invocation model, not the library
- Add these trigger types (currently only `manual`):
  - **Schedule** — implement a background scheduler (APScheduler or Celery beat) that reads `WorkflowSchedule` from DB and fires workflow executions on cron. Must survive restarts.
  - **Webhook** — add `POST /api/v1/workflows/{workflow_id}/webhook` endpoint that accepts arbitrary JSON payload and triggers the workflow with that data as input. Authenticate via API key in `X-API-Key` header.
  - **Event** — add `POST /api/v1/workflows/events` endpoint that matches events to workflow trigger rules and fires matching workflows. Events have `type`, `source`, `data` fields.
  - **Signal** — add `POST /api/v1/workflows/{workflow_id}/runs/{run_id}/signal` to send data to a running workflow (unblock a waiting step)
  - **Query** — add `GET /api/v1/workflows/{workflow_id}/runs/{run_id}/query/{query_name}` to query state of a running workflow without modifying it
- Each trigger type must be stored in the workflow definition and configurable per-workflow
- Workflows must specify which model to use for each step (tie into model router)

**3. API keys service → DB**
- File: `backend/app/routes/settings.py` — `_api_keys_store` dict
- Add SQLModel table: `APIKey` with fields: `id`, `tenant_id`, `name`, `key_hash`, `prefix`, `scopes` (JSON array), `rate_limit` (per-key), `created_at`, `revoked_at`, `last_used_at`
- Wire CRUD to DB
- API keys must be scoped: `scopes` field defines which workflows/resources the key can access
- Keys must be usable for rate limiting (see WS-4)

**4. RBAC custom roles → DB**
- File: `backend/app/middleware/rbac.py` — hardcoded 4-role dict
- Add SQLModel table: `CustomRole` with fields: `id`, `tenant_id`, `name`, `permissions` (JSON: list of `{resource, actions}` objects), `created_at`, `updated_at`
- Keep the 4 built-in roles as defaults but allow custom roles to be created, edited, deleted
- The RBAC `require_permission()` function must query DB for the user's roles (both built-in and custom) and check permissions
- Fix "failed to create custom role" — ensure the POST endpoint persists to DB

**5. SCIM service → DB**
- File: `backend/app/services/scim_service.py` — `_users`, `_groups` dicts
- Add SQLModel tables: `SCIMUser`, `SCIMGroup` (or wire to existing user/group tables)
- This is the foundation for AD group mapping — SCIM provisions users and groups from Azure AD/Entra ID into Archon
- Groups from SCIM must map to RBAC roles (custom or built-in)

**6. Secrets registration → DB**
- File: `backend/app/routes/secrets.py` — `_registrations` dict for secret metadata
- Wire to existing `SecretAccessLog` table (already defined, never used per audit)
- Secret metadata (path, type, rotation policy, created_by, scoped_to_role) must persist to DB
- When Vault is unavailable, degrade gracefully: show metadata from DB, return clear error for value retrieval ("Vault unavailable — metadata only")
- Never expose secret values in API responses beyond the explicit `GET /secrets/{id}` endpoint

**7. Secret access logger → DB**
- File: `backend/app/services/secret_access_logger.py` — `_entries` list
- The `SecretAccessLog` SQLModel table already exists in `models/secrets.py` — simply wire the logger to INSERT into it via `async_session_factory`
- This is a one-liner fix per method

**8. Lifecycle service → DB (top 3 dicts)**
- File: `backend/app/services/lifecycle_service.py` — 8 in-memory dicts
- Wire `_deployments`, `_agent_states`, `_deployment_history` to existing `DeploymentRecord`, `HealthCheck`, `LifecycleEvent` tables
- The remaining 5 dicts (`_scheduled_jobs`, `_metrics_store`, `_approval_gates`, `_environments`, `_health_metrics`) can stay in-memory for now

#### Acceptance Criteria
- All 7 critical services persist data across backend restarts
- Workflows support 5 trigger types (manual, schedule, webhook, event, signal) + query
- Background scheduler fires scheduled workflows (test with a 1-minute cron)
- API keys persisted, scoped, and retrievable after restart
- Custom roles creatable, editable, deletable — RBAC middleware consults DB
- SCIM provisions users/groups to DB
- Secrets metadata in DB, access log in DB
- All existing tests still pass

---

### WS-3: Frontend Fixes & Theme System

**Manager:** manager-gemini (Frontend focus)
**Workers:** worker-coder, worker-tester
**Priority:** HIGH — depends on WS-0, should wait for WS-1 (route fixes) to align frontend URLs
**File scope:** `frontend/src/**/*.tsx`, `frontend/src/api/*.ts`, `frontend/tailwind.config.ts`, `frontend/package.json`, `frontend/vitest.config.ts` (new)

#### Tasks

**1. Fix dark/light mode (100+ files)**
- Problem: 100+ hardcoded `bg-[#0f1117]` and `border-[#2a2d37]` across 25+ files
- `tailwind.config.ts` already has proper CSS custom properties via `hsl(var(--...))` — they're just not used
- **Fix:**
  - Create `ThemeProvider` context in `frontend/src/contexts/ThemeContext.tsx`:
    - Persists theme preference to `localStorage`
    - Reads `prefers-color-scheme` on first load
    - Toggles `document.documentElement.classList` for `dark` class
    - Provides `useTheme()` hook
  - Add theme toggle to global `navigation/TopBar.tsx` (not just Builder)
  - Replace ALL hardcoded values:
    - `bg-[#0f1117]` → `bg-background`
    - `bg-[#1a1d27]` → `bg-card`
    - `bg-[#2a2d37]` → `bg-muted`
    - `border-[#2a2d37]` → `border-border`
    - `text-white` → `text-foreground`
    - `text-gray-400` → `text-muted-foreground`
  - Define light mode CSS variables in `frontend/src/index.css` (`:root {}` block)
  - Verify dark mode variables in `.dark {}` block
- Test: Toggle theme, verify all pages render correctly in both modes

**2. Fix frontend API URLs to match corrected backend routes**
- After WS-1 fixes backend routes:
  - `frontend/src/api/governance.ts` line 221: change `/audit-logs/` to match backend (whichever option WS-1 chose)
  - Verify all `frontend/src/api/*.ts` files use correct paths
  - Remove stale TODO comments in `frontend/src/api/sentinelscan.ts` claiming `scan_router` not registered

**3. Configure Vitest**
- Add to `frontend/package.json`: `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`
- Create `frontend/vitest.config.ts`
- Update `"test"` script in `package.json`

**4. Add baseline component tests**
- `DashboardPage` — renders without crash
- `AgentBuilderCanvas` — renders React Flow canvas
- `LoginPage` — renders login form
- `Sidebar` / Navigation — renders all nav links
- `ThemeToggle` — toggles theme
- `AuditLogPage` — renders table headers

**5. Fix TypeScript errors**
- Run `npx tsc --noEmit` and fix all errors
- Verify: zero TypeScript errors

**6. Verify build**
- `npm run build` must succeed with zero errors

#### Acceptance Criteria
- Theme toggle in global TopBar
- All pages render correctly in both light and dark mode
- Zero `bg-[#0f1117]` or `border-[#2a2d37]` remaining
- Vitest configured with at least 6 component tests passing
- `npm run build` succeeds
- `npx tsc --noEmit` returns zero errors

---

### WS-4: Auth, Rate Limiting, Group Management & Security

**Manager:** manager-anthropic (Security focus)
**Workers:** worker-security, worker-coder
**Priority:** HIGH — depends on WS-2 (RBAC, SCIM, API keys must be DB-backed first)
**File scope:** `backend/app/middleware/auth.py`, `backend/app/middleware/rbac.py`, `backend/app/middleware/rate_limit.py` (new), `backend/app/middleware/audit_middleware.py`, `backend/app/config.py`

#### Tasks

**1. Add Azure Entra ID / OIDC authentication**
- Add `msal>=1.28.0` to `backend/requirements.txt`
- Add config fields to `backend/app/config.py`:
  ```python
  OIDC_DISCOVERY_URL: str = ""  # https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration
  OIDC_CLIENT_ID: str = ""      # 8adab7b8-a4bc-497b-90b9-53fd89de5900
  OIDC_CLIENT_SECRET: str = ""  # Optional for public client
  OIDC_TENANT_ID: str = ""      # ff3213cc-c3f6-45d4-a104-8f7823656fec
  ```
- Extend `middleware/auth.py` with a third validation tier:
  1. HS256 dev mode (existing)
  2. RS256 Keycloak (existing)
  3. **RS256 Entra ID** — fetch JWKS from Entra OIDC discovery, validate JWT, extract `oid`, `groups` claim, `preferred_username`, `email`
- Map Entra ID `groups` claim (list of group OIDs) to Archon RBAC roles via a mapping table: `GroupRoleMapping(group_oid, role_name)` — admin configurable
- MFA: Entra ID handles MFA via Conditional Access. Extract `amr` (authentication methods reference) claim to verify MFA was used.

**2. Add TOTP support for non-OIDC instances**
- For deployments without OIDC, support TOTP-based MFA:
  - Add `pyotp` to requirements
  - Add endpoints: `POST /api/v1/auth/totp/setup` (returns QR code URI + secret), `POST /api/v1/auth/totp/verify` (validates 6-digit code)
  - Store TOTP secrets encrypted in Vault (or DB if Vault unavailable)
  - After password auth, if TOTP is enabled for user, require TOTP verification before issuing full JWT

**3. Implement rate limiting middleware**
- Create `backend/app/middleware/rate_limit.py`
- Use Redis `INCR` + `EXPIRE` for sliding window rate limiting
- Two tiers:
  - **Global rate limit** — per tenant, configurable in settings (default: 1000 RPM)
  - **Per-API-key rate limit** — configurable per key (from `APIKey.rate_limit` field added in WS-2)
- On limit exceeded: return 429 with `Retry-After` header
- **Automatic retry detection:** If the Azure OpenAI API returns 429, the model router must:
  - Parse `Retry-After` header
  - Exponential backoff with jitter (1s, 2s, 4s, max 30s)
  - Fall back to alternative model/deployment if available
  - Log rate limit events for Sentinel

**4. Group management for least privilege**
- User-to-group assignment: `POST /api/v1/admin/users/{user_id}/groups` — assign user to one or more groups
- Group-to-role mapping: `POST /api/v1/admin/groups/{group_id}/roles` — map a group to RBAC roles
- Multi-group visibility: If a user is in multiple groups, they see resources from ALL their groups (union of permissions)
- AD group mapping: When OIDC token contains `groups` claim, auto-map to Archon groups via `GroupRoleMapping` table
- Invite user flow: `POST /api/v1/admin/invitations` must accept `role` or `group` parameter
- Workflows, secrets, API keys all respect group-based access: user sees only resources scoped to their groups

**5. Audit trail hardening**
- `backend/app/middleware/audit_middleware.py` currently does NOT redact sensitive information
- Add PII/secret scrubbing to audit log entries:
  - Mask API keys: `ak_live_abc123...` → `ak_live_***`
  - Mask bearer tokens: `Bearer eyJ...` → `Bearer ***`
  - Mask email addresses in request paths (if any)
  - Never store request/response bodies in audit log (only action metadata)
- Audit log access must be RBAC-protected: only `admin` role can read audit logs

**6. SIEM integration (Azure Sentinel)**
- Add a structlog processor that formats log events as Azure Sentinel-compatible JSON
- Add config field: `SENTINEL_WORKSPACE_ID`, `SENTINEL_SHARED_KEY`
- Ship security-relevant logs (auth failures, RBAC denials, rate limit hits, DLP blocks) to Azure Log Analytics via the HTTP Data Collector API
- KQL-friendly format: `TimeGenerated`, `SourceIP`, `UserID`, `Action`, `Resource`, `Outcome`, `Details`

#### Acceptance Criteria
- OIDC auth works with the provided Entra ID discovery URL and client ID (or gracefully reports "client secret needed")
- TOTP setup and verify endpoints work
- Rate limiting enforced globally and per-API-key
- Model router retries on 429 with exponential backoff
- Users in multiple groups see union of resources
- AD groups auto-map to Archon roles
- Audit logs redact secrets and PII
- Security events shipped to Sentinel format (even if Sentinel workspace not configured, the format and code path must exist)

---

### WS-5: Model Router Enhancement & Workflow Integration

**Manager:** manager-openai (Backend focus)
**Workers:** worker-coder, worker-tester
**Priority:** MEDIUM — depends on WS-2 (workflows DB-backed)
**File scope:** `backend/app/services/router_service.py`, `backend/app/routes/router.py`, `backend/app/services/workflow_engine.py`

#### Tasks

**1. Register Azure OpenAI models in router**
- Add model registry entries for:
  - `gpt-5.2-codex` at `https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview`
  - `qrg-embedding-experimental` at `https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/deployments/qrg-embedding-experimental/embeddings?api-version=2023-05-15`
- API key: `b664331212b54911969792845dee8ba9` (store in Vault or env var, never hardcode)
- Provider type: `azure_openai`

**2. Load balancing across model deployments**
- The router already scores by cost/latency/capability — extend to support multiple deployments of the same model
- Add `deployment_id` field to `ModelRegistryEntry`
- When multiple deployments exist for the same model, round-robin with health-aware selection
- Circuit breaker already exists — ensure it works per-deployment, not per-model

**3. Automatic retry on rate limit (429)**
- In `router_service.py`, when a model call returns 429:
  - Parse `Retry-After` header
  - If retry within budget (< 30s), wait and retry
  - If retry exceeds budget, fall back to next model in fallback chain
  - If all fallbacks exhausted, return 429 to caller with aggregated `Retry-After`
- Log all retry events for observability

**4. Granular model selection for workflows**
- Workflow step definitions must support a `model` field (e.g., `"model": "gpt-5.2-codex"`)
- When `workflow_engine.py` executes a step, pass the model preference to the router
- If no model specified, use the tenant's default model from router policy
- Embedding steps must be routable to the embeddings endpoint

**5. Embeddings endpoint**
- Add `POST /api/v1/router/embeddings` endpoint
- Routes to the configured embeddings model deployment
- Input: `{"text": "...", "model": "qrg-embedding-experimental"}`
- Output: `{"embedding": [...], "model": "...", "usage": {...}}`

**6. Make router accessible for workflows**
- Expose the router as an injectable dependency in workflow steps
- Workflow steps can call `router.route(prompt, model_preference, data_classification)` directly
- The router handles retries, fallbacks, and circuit breaking transparently

#### Acceptance Criteria
- Azure OpenAI models registered and callable through router
- Multiple deployments load-balanced with health-aware selection
- 429 responses trigger retry with backoff + fallback
- Workflow steps can specify model per-step
- Embeddings endpoint works with the provided Azure endpoint
- All existing router tests still pass

---

### WS-6: MCP Host Gateway

**Manager:** manager-anthropic (Architecture focus)
**Workers:** worker-architect, worker-coder, worker-security
**Priority:** MEDIUM — can start in parallel with WS-2/3/4, depends on WS-0
**File scope:** All new files under `gateway/`

Build the MCP Host Gateway per the end-state architecture at `gateway/`.

#### Directory Structure
```
gateway/
  app/
    __init__.py
    main.py                    # FastAPI app factory
    config.py                  # pydantic-settings, MCP_GATEWAY_ prefix
    auth/
      __init__.py
      middleware.py            # EntraAuthMiddleware (MSAL JWT validation)
      models.py                # User identity (oid, groups, etc.)
    guardrails/
      __init__.py
      middleware.py            # Rate limit, input validation, destructive op check, timeout, audit
    plugins/
      __init__.py
      loader.py                # Hot-load plugins/*.yaml + watchfiles + Pydantic validation
      models.py                # Plugin, Tool Pydantic schemas
    routes/
      __init__.py
      capabilities.py          # GET /mcp/capabilities
      invoke.py                # POST /mcp/tools/{tool_id}/invoke
      health.py                # GET /health, GET /ready
    tools/
      __init__.py
      builtin_ai.py            # Built-in execution via Azure OpenAI
      forwarder.py             # Forward to agent backend
      dispatch.py              # can_forward? → builtin or forwarder
      container.py             # Spin up MCP containers on-demand (ToolHive pattern)
    workflows/
      __init__.py
      qa_trigger.py            # POST result to Logic Apps trigger URL
    improvement/
      __init__.py
      engine.py                # Gap collection → codex analysis → proposals
    logging_config.py          # structlog JSON
  plugins/
    _example.yaml
    finance-revenue-mcp.yaml   # Sample plugin
  tests/
    __init__.py
    conftest.py
    test_auth_middleware.py
    test_capabilities.py
    test_invoke.py
    test_plugin_loader.py
    test_guardrails.py
    test_dispatch.py
    test_container.py
    test_qa_trigger.py
  requirements.txt
  Dockerfile
  pyproject.toml
```

#### Key Implementation Details

**MCP Container Management (`tools/container.py`):**
- ToolHive-inspired pattern: MCP containers spin up only when needed, reducing token utilization
- Each external MCP runs in its own container with:
  - Network isolation (separate Docker network)
  - Resource limits (CPU, memory)
  - Automatic shutdown after idle timeout
  - Health check endpoint
- Container lifecycle: pull image → create → start → health check → proxy requests → idle timeout → stop → remove
- MCPU-compatible: MCP clients connect through the gateway using the MCPU protocol pattern
- Security: containers cannot access host network, secrets injected via environment variables from Vault

**Plugin YAML with container support:**
```yaml
name: finance-revenue-mcp
type: container  # or "builtin" or "forward"
container:
  image: ghcr.io/company/finance-revenue-mcp:latest
  port: 8080
  idle_timeout: 300  # seconds
  resources:
    cpu: "0.5"
    memory: "512Mi"
required_groups:
  - MCP-Users-Finance
tools:
  - id: get_revenue
    input_schema: {...}
```

#### Acceptance Criteria
- Gateway builds and starts (`python -m uvicorn app.main:app`)
- Plugin loader hot-reloads YAML changes
- `GET /mcp/capabilities` filters by user groups
- `POST /mcp/tools/{tool_id}/invoke` dispatches correctly
- Container-type plugins spin up Docker containers on first invoke
- Auth middleware validates Entra ID JWT (or dev bypass)
- Guardrails enforce rate limits
- All gateway tests pass (8+ test files)
- Dockerfile builds successfully

---

### WS-7: Docker-Based Integration Testing

**Manager:** manager-anthropic (Testing focus)
**Workers:** worker-tester, worker-debugger
**Priority:** HIGH — depends on WS-1, WS-2, WS-3, WS-4 completing
**File scope:** `tests/integration/`, `tests/playwright/`, `docker-compose.test.yml` (new)

This is the **test-gen + smoke phase**. A subprocess starts the server, runs tests, stops it.

#### Tasks

**1. Create test Docker compose**
- Create `docker-compose.test.yml` that extends `docker-compose.yml`:
  - postgres, redis, backend, frontend (no vault, keycloak, prometheus, grafana — minimal stack)
  - Backend in test mode: `AUTH_DEV_MODE=true`, `ARCHON_DATABASE_URL=postgresql+asyncpg://archon:archon@postgres:5432/archon_test`
  - All Azure OpenAI env vars set for real API testing
  - Frontend served by Vite preview server

**2. Create test runner script**
- `scripts/run_integration_tests.sh`:
  ```bash
  #!/bin/bash
  set -e
  # Start
  docker compose -f docker-compose.test.yml up -d --build --wait
  # Wait for health
  timeout 120 bash -c 'until curl -sf http://localhost:8000/health; do sleep 2; done'
  timeout 120 bash -c 'until curl -sf http://localhost:3000; do sleep 2; done'
  # Run backend integration tests
  PYTHONPATH=backend python3 -m pytest tests/integration/ -v --tb=short
  # Run Playwright tests
  cd frontend && npx playwright test --reporter=list
  # Stop
  docker compose -f docker-compose.test.yml down -v
  ```

**3. Backend integration tests** (`tests/integration/`)
- Test against RUNNING backend at `http://localhost:8000`:
  ```python
  import httpx
  BASE = "http://localhost:8000"
  ```
- Tests for every broken feature:
  - `test_audit_logs.py` — `GET /api/v1/audit-logs/` returns 200 with list of entries
  - `test_sentinel.py` — `GET /api/v1/sentinel/discover` returns 200, `POST /api/v1/sentinelscan/scan` returns 200
  - `test_marketplace.py` — `GET /api/v1/marketplace/categories` returns 200, `POST /api/v1/marketplace/packages/{id}/install` returns correct status
  - `test_health.py` — `GET /api/v1/health` returns DB/Redis status
  - `test_workflows.py` — create workflow, execute, check run status; test webhook trigger; test schedule preview
  - `test_rbac.py` — create custom role, assign to user, verify permission enforcement
  - `test_secrets.py` — create secret (dev mode), list secrets, get secret metadata
  - `test_api_keys.py` — create key, list keys, revoke key, verify persistence after creation
  - `test_templates.py` — list templates, create template, verify no "seed" failure
  - `test_rate_limit.py` — fire 100+ requests rapidly, verify 429 response
  - `test_model_router.py` — call Azure OpenAI through router, verify response, test retry on simulated 429
  - `test_settings.py` — get/update settings, test SMTP config, test API key management
  - `test_dlp.py` — submit text with PII through DLP scan endpoint, verify detection
  - `test_azure_openai.py` — call the real Azure OpenAI endpoint through the model router, verify response contains generated text
  - `test_embeddings.py` — call embeddings endpoint with sample text, verify vector response

**4. Playwright frontend tests** (`frontend/tests/e2e/`)
- Install Playwright: `npx playwright install chromium`
- Configure: `frontend/playwright.config.ts` with `baseURL: 'http://localhost:3000'`, headless mode
- Tests (all run in background, headless):
  - `dashboard.spec.ts` — navigate to dashboard, verify it loads, check key metrics visible
  - `theme.spec.ts` — toggle dark/light mode, verify background color changes
  - `audit.spec.ts` — navigate to audit log page, verify table renders (not blank)
  - `sentinel.spec.ts` — navigate to sentinel page, verify no white screen, verify scan controls visible
  - `health.spec.ts` — navigate to system health, verify status indicators render
  - `workflows.spec.ts` — navigate to workflows, create a workflow, verify it appears in list
  - `templates.spec.ts` — navigate to templates, verify list loads
  - `marketplace.spec.ts` — navigate to marketplace, verify categories load
  - `secrets.spec.ts` — navigate to secrets page, verify it loads (no "failed to load" error)
  - `rbac.spec.ts` — navigate to RBAC page, attempt to create custom role
  - `settings.spec.ts` — navigate to settings, verify all tabs load
  - `model_router.spec.ts` — navigate to model router page, verify provider list renders

**5. Azure OpenAI smoke test**
- Dedicated test that calls the real Azure OpenAI API:
  ```python
  def test_azure_openai_direct():
      resp = httpx.post(
          "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/responses?api-version=2025-04-01-preview",
          headers={"Authorization": "Bearer b664331212b54911969792845dee8ba9", "Content-Type": "application/json"},
          json={"messages": [{"role": "user", "content": "Say OK"}], "max_completion_tokens": 10, "model": "gpt-5.2-codex"},
          timeout=30
      )
      assert resp.status_code == 200
      assert "choices" in resp.json() or "output" in resp.json()
  ```
- Also test embeddings:
  ```python
  def test_azure_embeddings():
      resp = httpx.post(
          "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/deployments/qrg-embedding-experimental/embeddings?api-version=2023-05-15",
          headers={"Authorization": "Bearer b664331212b54911969792845dee8ba9", "Content-Type": "application/json"},
          json={"input": "test embedding", "model": "qrg-embedding-experimental"},
          timeout=30
      )
      assert resp.status_code == 200
  ```

#### Acceptance Criteria
- `scripts/run_integration_tests.sh` runs end-to-end: starts Docker stack, runs all tests, stops stack
- All backend integration tests pass against running server
- All Playwright tests pass (headless, in background)
- Azure OpenAI direct smoke test passes
- Embeddings smoke test passes
- Test results saved to `docs/INTEGRATION_TEST_REPORT.md`

---

### WS-8: Cross-Cutting (CI/CD, Docs, Mail, Teams)

**Manager:** manager-gemini (DevOps focus)
**Workers:** worker-coder, worker-documenter
**Priority:** MEDIUM — can run in parallel with WS-5/6/7
**File scope:** `.github/workflows/`, `docs/`, `backend/app/routes/settings.py`, `backend/app/services/connectors/`

#### Tasks

**1. Implement real SMTP sending**
- File: `backend/app/routes/settings.py` — `send_test_notification` for email is a stub
- Implement actual SMTP sending using `aiosmtplib`:
  - Add `aiosmtplib` to requirements
  - Read SMTP config from settings (host, port, from, username, password from Vault)
  - `POST /api/v1/settings/notifications/test` with `channel: "email"` must actually send an email
- SMTP config is super-admin only (require `admin` role)

**2. Add Microsoft Teams integration**
- Add `msgraph-sdk` or use `httpx` with MS Graph API
- Teams notification channel alongside Slack:
  - Config: `teams_webhook_url` in settings (Incoming Webhook connector) — simplest approach
  - Or: full Graph API with app registration for posting to channels
- `POST /api/v1/settings/notifications/test` with `channel: "teams"` sends a Teams message
- Add `teams` option to event notification config (alongside `email` and `slack`)

**3. Fix multi-tenancy**
- Review `backend/app/middleware/tenant.py` — ensure tenant isolation is enforced on ALL database queries
- Every service that queries the DB must filter by `tenant_id`
- Verify: creating a resource in tenant A is not visible from tenant B

**4. Update CI pipeline**
- `.github/workflows/ci.yml`: add gateway lint + test
- `.github/workflows/cd.yml`: add gateway Docker image build + push
- Add integration test step (optional, can be manual trigger)

**5. Update documentation**
- `docs/ARCHITECTURE.md` — add MCP Host Gateway section
- `docs/DEPLOYMENT_GUIDE.md` — step-by-step for Azure Container Apps deployment
- `docs/API_REFERENCE.md` — verify OpenAPI docs at `/docs` serve correct spec with all endpoints

**6. Verify OpenAPI docs**
- `GET /docs` must serve Swagger UI with ALL registered endpoints
- `GET /openapi.json` must include every route
- Cross-reference with `contracts/openapi.yaml` — update the contract if endpoints have changed

#### Acceptance Criteria
- Email test notification actually sends an email via SMTP
- Teams webhook notification works
- Tenant isolation verified (resource created in tenant A not visible from tenant B)
- CI pipeline includes gateway
- Documentation updated
- `/docs` serves correct OpenAPI spec

---

## Execution Order

```
Phase 1 — ASSESS (blocking):
  └── WS-0: Health Assessment & Baseline

Phase 2 — FIX (parallel):
  ├── WS-1: Backend Route & URL Fixes
  ├── WS-2: In-Memory → Database Migration
  ├── WS-6: MCP Host Gateway (independent, new code)
  └── WS-8: Cross-Cutting (CI/CD, Mail, Teams, Docs)

Phase 3 — HARDEN (depends on WS-1 + WS-2):
  ├── WS-3: Frontend Fixes & Theme System (needs WS-1 route fixes)
  ├── WS-4: Auth, Rate Limiting, Group Management (needs WS-2 RBAC/API keys)
  └── WS-5: Model Router & Workflow Integration (needs WS-2 workflows)

Phase 4 — VALIDATE (depends on all above):
  └── WS-7: Docker-Based Integration Testing (subprocess: start → test → stop)
```

**Dependency graph:**
```
WS-0 ──┬──→ WS-1 ──→ WS-3
       ├──→ WS-2 ──┬──→ WS-4
       │           └──→ WS-5
       ├──→ WS-6
       └──→ WS-8
                    ALL ──→ WS-7
```

---

## Global Constraints

1. **DO NOT delete existing working code** — only extend and fix
2. **DO NOT change the existing API contract** unless fixing a bug (document all changes)
3. **The gateway is SEPARATE** — it's a new FastAPI app at `gateway/`, not a refactor of `backend/`
4. **All tests must pass** at the end (both Archon and gateway)
5. **Use existing tech stack** — Python 3.12, FastAPI, SQLModel, Redis, structlog
6. **Never hardcode secrets** — use env vars or Vault
7. **Follow existing code style** from the Archon backend
8. **Every workstream must produce a report** in `docs/`
9. **Least privilege everywhere** — users see only what their groups allow
10. **API-first** — `/docs` must serve correct OpenAPI spec, all endpoints must work

## Model Selection for Swarm Agents

- **L2 Managers:** claude-sonnet-4.6 (Anthropic), gpt-5.2-codex (OpenAI), gemini-3-pro-preview (Google)
- **L3 Workers:** Distribute across providers for model diversity
- **Never use:** claude-sonnet-4.5 or claude-opus-4.5 (use 4.6 variants instead)

---

## Swarm Invocation

```
@swarm Execute the comprehensive plan in /Users/timothy.schwarz/archon/SWARM_PLAN.md

The plan has 9 workstreams (WS-0 through WS-8) across 4 phases. Start with WS-0 (Health
Assessment) as it blocks everything else. Then run WS-1, WS-2, WS-6, WS-8 in parallel (Phase 2).
Then WS-3, WS-4, WS-5 in parallel (Phase 3). End with WS-7 (Docker integration testing).

Key constraints:
- DO NOT modify the swarm itself — it is already updated
- DO NOT delete existing working code — only extend and fix
- The gateway is a SEPARATE FastAPI app at gateway/, not a refactor of the backend
- All tests must pass at the end (both Archon backend and gateway)
- Use the existing tech stack (Python 3.12, FastAPI, SQLModel, Redis, structlog)
- For the gateway, add: msal, openai, watchfiles, httpx to requirements.txt
- Follow existing code style and patterns from the Archon backend
- Every workstream must produce a report document in docs/
- The integration test phase (WS-7) must use Docker subprocess: start stack → run tests → stop stack
- Azure OpenAI API key: b664331212b54911969792845dee8ba9 (use as env var, not hardcoded)
- OIDC discovery: https://login.microsoftonline.com/ff3213cc-c3f6-45d4-a104-8f7823656fec/v2.0/.well-known/openid-configuration
- OIDC client ID: 8adab7b8-a4bc-497b-90b9-53fd89de5900
- Playwright tests must run headless (in background)
- Prefer claude-sonnet-4.6, gpt-5.2-codex, gemini-3-pro-preview for agent models
```
