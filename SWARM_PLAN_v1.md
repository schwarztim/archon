# Archon Platform — Comprehensive Swarm Execution Plan

## Objective

Execute ALL of the following in a single swarm run, using the 3-tier hierarchy (L1 Orchestrator -> L2 Managers -> L3 Workers):

1. **Assess Health** — Run existing tests, smoke tests, docker build checks; produce a baseline health report
2. **Harden Existing Archon** — Fix stubs, wire real DB implementations, add frontend test runner, make services production-ready
3. **Build the MCP Host Gateway** — Create the focused Enterprise MCP Host Gateway per the end-state architecture
4. **Converge: Extract Gateway from Archon** — Extract MCP-relevant pieces from Archon into the gateway, reusing proven code
5. **Something Else** — Fix any cross-cutting issues discovered during execution (tech debt, security, CI gaps)

---

## Context: Current State

### Repository
- **Location**: `/Users/timothy.schwarz/archon`
- **14 git commits** on `main`, built by 25 Claude swarm agents in rapid succession
- **Backend**: Python 3.12, FastAPI 0.115+, SQLModel, asyncpg, PostgreSQL 16, Redis 7, Celery, LangGraph, LiteLLM, structlog
- **Frontend**: React 19, Vite 6, TypeScript 5.7, Tailwind, Zustand, TanStack Query, React Flow 12, Recharts
- **Infra**: Docker Compose (9 services), Helm charts, Terraform scaffolds (AWS/Azure/GCP), ArgoCD, Prometheus, Grafana
- **Auth**: Keycloak 26 (dev mode) + HS256 dev bypass; RBAC with 4 roles (admin, operator, viewer, agent_creator)
- **Tests**: ~110+ test files across `backend/tests/` and `tests/`, no frontend test runner
- **CI/CD**: GitHub Actions (lint -> test -> build -> security-scan; CD pushes to GHCR)

### Key Files
- `backend/app/main.py` — FastAPI app factory, 40+ routers, 5 middleware layers
- `backend/app/config.py` — pydantic-settings with `ARCHON_` env prefix
- `backend/app/middleware/auth.py` — JWT validation (HS256 dev / RS256 Keycloak)
- `backend/app/middleware/rbac.py` — Role-based access control
- `backend/app/models/__init__.py` — 60+ SQLModel tables
- `contracts/openapi.yaml` — OpenAPI 3.1 spec
- `docker-compose.yml` — 9 services (postgres, redis, backend, frontend, vault, keycloak, vault-init, prometheus, grafana, worker)
- `scripts/smoke_test.sh` — API smoke tests via TestClient
- `scripts/validate_platform.sh` — Full validation suite (pytest + branding + integration + smoke)

### Known Issues
- Many backend services are sophisticated stubs with in-memory implementations, not fully DB-backed
- Frontend has zero test coverage (no test runner configured)
- Terraform modules are scaffolded but not functional
- Vault/Keycloak integration is dev-mode only
- Worker entrypoint (`app.worker`) exists but may not be functional
- DLP routes have a double-prefix bug: `/api/v1/api/v1/dlp/policies`

---

## Target Architecture: Enterprise MCP Host Gateway

Source: `/Users/timothy.schwarz/Documents/architecture-endstate.drawio` (2-page draw.io diagram)

### Page 1: Infrastructure & Data Flow
Title: "Enterprise MCP Host Gateway — Production Infrastructure & Data Flow"
Subtitle: "End-State Target: Internal-only via Netskope NPA (Zero Trust Network Access)"

**Data flow (numbered):**
1. Client authenticates with **Azure Entra ID** via OAuth2 (MSAL), receives JWT with group OID claims
2. Client connects via **Netskope NPA** tunnel (device posture verified), sends request with Bearer JWT
3. NPA routes to **Azure API Management** (internal); APIM validates JWT, applies rate limit (100/60s), routes to Container App
4-6. **Azure Container Apps** (FastAPI + Uvicorn + Gunicorn): EntraAuthMiddleware extracts identity -> Route matches -> Tool executes (local AI or forwarded) -> Returns result
7. On success, result optionally triggers **Azure Logic Apps** QA workflow for human approval -> Azure DevOps work items (approved) or Sentinel alert (rejected)

**Components:**
- **MCP Clients**: Claude Desktop/Code, Custom MCP App, Browser SPA, curl/httpx (all require Netskope Client + Bearer JWT)
- **Azure Entra ID**: App Registration `MCP-Host-Gateway`, Scopes `api://mcp-host-gateway`, Groups `MCP-Admins`, `MCP-Users-Finance`, Permission `GroupMember.Read.All`
- **Netskope NPA**: ZTNA, device posture, private app connector, mTLS
- **Azure APIM**: Inbound policies: `validate-jwt` (Entra issuer), `rate-limit` (100/60s), `set-backend-service` -> Container App, `diagnostics` -> Log Analytics -> Sentinel
- **Azure Container Apps**: `mcp-host-gateway` (FastAPI + Uvicorn + Gunicorn)
  - **Middleware chain**: CORSMiddleware -> EntraAuthMiddleware (MSAL: validate JWT, extract oid+groups, inject request.state) -> GuardrailsMiddleware (rate limit, input validation, destructive op check, timeout, audit log)
  - **Routes**: `GET /mcp/capabilities` (filter plugins by user_groups), `POST /mcp/tools/{tool_id}/invoke`
  - **Plugin Loader** (`app/plugins/loader.py`): Hot-load `plugins/*.yaml` at startup + watchfiles, validate via Pydantic schemas
  - **Tool Execution Layer**: `builtin_ai.py` (local AI execution) + `forwarder.py` (forward to agent backend), dispatch based on `tool.can_forward` flag
  - **QA Workflow Trigger** (`app/workflows/qa_trigger.py`): On tool success, POST result to Logic Apps trigger URL
  - **Logging**: structlog -> JSON -> stdout -> Container Apps Log Stream
- **Azure OpenAI**: gpt-5.2 (agent tasks), gpt-5.2-codex (improvement pipeline), claude-sonnet (built-in AI tool)
- **Internal Backends**: Revenue API, Inventory API, Agentic Backend (per plugin YAML `backend_url`)
- **Azure Logic Apps**: QA approval workflow — HTTP trigger -> Start Approval (MCP-QA-Approvers) -> Approved (Azure DevOps work item) / Rejected (email + Sentinel alert)
- **Azure Sentinel**: SIEM + anomaly detection with KQL analytics rule (example: flag >10 calls per 5min per user per tool)
- **Redis**: Token cache + rate limit state + improvement pipeline store
- **Azure DevOps / GitHub**: Work items from approved QA results + CI/CD pipeline

**Plugin YAML format** (`plugins/*.yaml`):
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
Title: "Enterprise MCP Host Gateway — Logical Architecture"
Subtitle: "Component relationships, middleware chain, data ownership, and trust boundaries"

**Trust boundaries (3 zones):**
1. **MANAGED DEVICES — Corporate Client Zone** (Netskope Client Required): GitHub Copilot, Custom MCP App, Browser SPA -> Auth via Entra ID (OAuth2 + OIDC, JWT with group claims)
2. **DMZ — API Gateway Layer** (Netskope NPA + APIM): NPA tunnel -> APIM inbound policy chain: validate-jwt -> rate-limit -> set-backend -> diagnostics
3. **TRUSTED — Application Zone** (Azure Container Apps VNet):
   - FastAPI Application (`mcp-host-gateway`):
     - Middleware: CORSMiddleware -> EntraAuthMiddleware -> GuardrailsMiddleware
     - Request Router: `GET /mcp/capabilities` (returns tools visible to user's groups), `POST /mcp/tools/{id}/invoke` -> dispatch
     - Dispatch decision diamond: `can_forward?` -> false: Built-in Tool Execution (`app/tools/builtin_ai.py`) -> LLM invoke to Azure OpenAI | true: Agent Forwarder (`app/tools/forwarder.py`) -> Forward task to Agentic Backend
   - External services: Azure OpenAI (gpt-5.2, gpt-5.2-codex, claude-sonnet), Internal API Backends (Revenue, Inventory, Order Mgmt), Agentic Backend
   - Redis: Token cache, rate limit state, gap store
   - QA & Observability Pipeline: Azure Logic Apps (QA Approval) -> Azure DevOps (work items), Azure Sentinel (SIEM), structlog -> Log Analytics

**Improvement pipeline** (self-improvement loop visible in diagram):
- Improvement Engine (`app/improvement/engine.py`) collects gap data from Redis gap store
- Sends to Azure OpenAI gpt-5.2-codex for analysis
- Produces improvement proposals stored back in Redis
- Human review via Logic Apps approval flow

---

## Workstreams

### WS-1: Health Assessment & Baseline (L2 Manager: Testing)
**Priority**: FIRST — must complete before other workstreams begin
**Workers**: worker-tester, worker-debugger

Tasks:
1. Run `PYTHONPATH=backend python3 -m pytest tests/ --no-header -q` from project root and capture full output
2. Run `bash scripts/smoke_test.sh` and capture output
3. Run `bash scripts/validate_platform.sh` and capture output
4. Attempt `docker build -t archon-backend:test ./backend` and `docker build -t archon-frontend:test ./frontend`
5. Run `ruff check backend/` for lint status
6. Check frontend build: `cd frontend && npm install && npm run build`
7. Produce a **health report** listing:
   - Total tests passed/failed/errored
   - Which smoke test endpoints pass/fail
   - Docker build success/failure for both images
   - Lint violations count
   - Frontend build success/failure
   - List of all import errors or missing modules
   - List of all 500-status routes
8. Save report to `docs/HEALTH_REPORT.md`

### WS-2: Harden Existing Archon Backend (L2 Manager: Backend)
**Priority**: HIGH — depends on WS-1 health report
**Workers**: worker-coder, worker-tester, worker-debugger

Tasks:
1. **Fix the DLP double-prefix bug**: The DLP router is registered at `prefix=settings.API_PREFIX` but the router itself already has `/api/v1/dlp` prefix. Fix so it's accessible at `/api/v1/dlp/policies` (not `/api/v1/api/v1/dlp/policies`)
2. **Identify and fix all stub services**: Scan `backend/app/services/` for any service that uses in-memory dicts/lists instead of the database. For each:
   - Wire it to the actual SQLModel/asyncpg database using `async_session_factory`
   - Ensure CRUD operations use proper async sessions
   - Add error handling for not-found, conflict, validation errors
3. **Fix broken imports**: Any import errors found in WS-1, fix them
4. **Fix all routes returning 500**: For each 500-status route found in WS-1, investigate and fix the root cause
5. **Ensure all middleware works together**: Test the full middleware chain (Metrics -> Audit -> Tenant -> DLP -> Request ID -> CORS) end-to-end
6. **Wire the Celery worker**: Ensure `python3 -m app.worker` actually starts and can process tasks
7. **Add missing MSAL/Entra dependencies** to `requirements.txt`: `msal>=1.28.0` (needed for gateway convergence later)
8. Run all tests after changes, fix any regressions
9. Save a summary of all changes to `docs/HARDENING_REPORT.md`

### WS-3: Harden Frontend (L2 Manager: Frontend)
**Priority**: HIGH — depends on WS-1
**Workers**: worker-coder, worker-tester

Tasks:
1. **Configure Vitest**: Add vitest + @testing-library/react to `frontend/package.json`, create `vitest.config.ts`, update the `"test"` script
2. **Add baseline component tests**: Create tests for at least these critical components:
   - `DashboardPage` — renders without crash
   - `AgentBuilderCanvas` — renders React Flow canvas
   - `LoginPage` — renders login form
   - Navigation/Sidebar — renders all nav links
3. **Fix any TypeScript errors**: Run `npx tsc --noEmit` and fix all errors
4. **Verify the build**: `npm run build` must succeed with zero errors
5. Run all new tests, ensure they pass
6. Save summary to `docs/FRONTEND_HARDENING_REPORT.md`

### WS-4: Build MCP Host Gateway (L2 Manager: Architecture)
**Priority**: HIGH — can run in parallel with WS-2/WS-3
**Workers**: worker-coder, worker-architect, worker-security

This is the core deliverable. Create a NEW FastAPI application at `/Users/timothy.schwarz/archon/gateway/` that implements the end-state architecture.

**Directory structure:**
```
gateway/
  app/
    __init__.py
    main.py                    # FastAPI app factory
    config.py                  # pydantic-settings with MCP_GATEWAY_ prefix
    auth/
      __init__.py
      middleware.py            # EntraAuthMiddleware (MSAL JWT validation)
      models.py                # User identity models (oid, groups, etc.)
    guardrails/
      __init__.py
      middleware.py            # GuardrailsMiddleware (rate limit, input validation, destructive op check, timeout, audit)
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
      builtin_ai.py            # Built-in tool execution via Azure OpenAI
      forwarder.py             # Forward to agent backend via backend_url
      dispatch.py              # Dispatch logic: can_forward? -> builtin or forwarder
    workflows/
      __init__.py
      qa_trigger.py            # POST result to Logic Apps trigger URL
    improvement/
      __init__.py
      engine.py                # Improvement pipeline (gap collection -> codex analysis -> proposals)
    logging_config.py          # structlog JSON setup
  plugins/
    _example.yaml              # Example plugin YAML
    finance-revenue-mcp.yaml   # Sample: finance revenue MCP plugin
  tests/
    __init__.py
    conftest.py
    test_auth_middleware.py
    test_capabilities.py
    test_invoke.py
    test_plugin_loader.py
    test_guardrails.py
    test_dispatch.py
    test_qa_trigger.py
  requirements.txt
  Dockerfile
  pyproject.toml               # ruff, pytest config
```

**Implementation details:**

#### `app/config.py`
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_GATEWAY_")
    
    # Entra ID
    ENTRA_TENANT_ID: str
    ENTRA_CLIENT_ID: str
    ENTRA_AUTHORITY: str = ""  # computed from tenant_id
    
    # Azure OpenAI
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-12-01-preview"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Logic Apps
    LOGIC_APPS_TRIGGER_URL: str = ""
    
    # Plugins
    PLUGINS_DIR: str = "plugins"
    
    # Rate limiting
    RATE_LIMIT_CALLS: int = 100
    RATE_LIMIT_PERIOD: int = 60
    
    # Dev mode
    DEV_MODE: bool = False
    
    # Logging
    LOG_LEVEL: str = "INFO"
```

#### `app/auth/middleware.py` (EntraAuthMiddleware)
- Use `msal` library to validate Bearer JWT
- Extract `oid` (user object ID) and `groups` claim from token
- Inject `request.state.user_id` and `request.state.user_groups`
- Return 401 on invalid/expired/missing token
- In dev mode, bypass with synthetic admin user (all groups)
- Cache JWKS keys in Redis with TTL

#### `app/guardrails/middleware.py` (GuardrailsMiddleware)
- App-level rate limiting per user (using Redis INCR + EXPIRE)
- Input validation (max body size, content type check)
- Destructive operation check (flag DELETE/PUT operations for audit)
- Request timeout enforcement
- Audit log emission (structlog JSON)

#### `app/plugins/loader.py`
- On startup, scan `PLUGINS_DIR` for `*.yaml` files
- Parse each with Pydantic model:
  ```python
  class ToolDef(BaseModel):
      id: str
      input_schema: dict
      model: str = "gpt-5.2"
      can_forward: bool = False
  
  class PluginDef(BaseModel):
      name: str
      backend_url: str | None = None
      required_groups: list[str] = []
      tools: list[ToolDef]
  ```
- Use `watchfiles` to hot-reload on YAML changes
- Store in an in-memory registry (dict[str, PluginDef])
- Thread-safe reload with asyncio Lock

#### `app/routes/capabilities.py` — `GET /mcp/capabilities`
- Read `request.state.user_groups` from auth middleware
- Filter plugins where `required_groups` intersects with user's groups (or no groups required)
- Return filtered list of tools with their schemas

#### `app/routes/invoke.py` — `POST /mcp/tools/{tool_id}/invoke`
- Validate tool_id exists in plugin registry
- Check user has required group for this tool's plugin
- Call `dispatch.dispatch_tool(tool, request_body, user_context)`
- On success, optionally trigger QA workflow
- Return tool result

#### `app/tools/dispatch.py`
- Check `tool.can_forward`:
  - `False` -> call `builtin_ai.invoke(tool, input_data)`
  - `True` -> call `forwarder.forward(tool, input_data, plugin.backend_url)`

#### `app/tools/builtin_ai.py`
- Use Azure OpenAI SDK (`openai` library with azure endpoint)
- Send tool input + system prompt to specified model
- Return structured response

#### `app/tools/forwarder.py`
- Use `httpx.AsyncClient` to POST to `plugin.backend_url`
- Include original user context in headers
- Handle timeouts, retries, error responses

#### `app/workflows/qa_trigger.py`
- On tool success with QA-flagged tools, POST result to `LOGIC_APPS_TRIGGER_URL`
- Include: tool_id, user_id, input, output, timestamp
- Fire-and-forget (don't block response)

#### Tests
- Use FastAPI TestClient
- Mock Entra ID JWT validation for auth tests
- Mock Azure OpenAI for builtin_ai tests
- Mock httpx for forwarder tests
- Test plugin loader with temp YAML files
- Test group-based filtering in capabilities
- Test dispatch routing logic

### WS-5: Converge — Wire Archon Components into Gateway (L2 Manager: Integration)
**Priority**: MEDIUM — depends on WS-2 and WS-4
**Workers**: worker-coder, worker-architect

Tasks:
1. **Reuse Archon's structlog setup**: Copy/adapt `backend/app/logging_config.py` into `gateway/app/logging_config.py`
2. **Reuse Archon's metrics**: Adapt `backend/app/middleware/metrics_middleware.py` for gateway (Prometheus endpoint)
3. **Reuse Archon's DLP scanning**: Integrate the DLP middleware concept from Archon into the GuardrailsMiddleware (scan inputs for PII/sensitive data before tool invocation)
4. **Reuse Archon's audit logging**: Adapt `backend/app/middleware/audit_middleware.py` for gateway audit trail
5. **Reuse Archon's Redis patterns**: Use the same Redis connection patterns from Archon for token cache and rate limiting
6. **Create a migration guide**: Document in `gateway/docs/MIGRATION_FROM_ARCHON.md` which Archon components were reused, which were replaced, and why
7. **Update Archon's `docker-compose.yml`**: Add a `gateway` service entry pointing to `gateway/Dockerfile`
8. **Create gateway Helm chart**: `infra/helm/mcp-gateway/` with values for Entra ID, Azure OpenAI, Redis, Logic Apps

### WS-6: Cross-Cutting Fixes (L2 Manager: DevOps/Security)
**Priority**: MEDIUM — can run in parallel with WS-4/WS-5
**Workers**: worker-security, worker-coder

Tasks:
1. **Fix CI pipeline**: Ensure `.github/workflows/ci.yml` also lints and tests the gateway
2. **Fix CD pipeline**: Add gateway Docker image build+push to `.github/workflows/cd.yml`
3. **Security audit**: Run through OWASP Top 10 for both Archon backend and gateway:
   - A01 Broken Access Control — verify RBAC enforcement on all routes
   - A02 Cryptographic Failures — verify JWT validation, no hardcoded secrets in code
   - A03 Injection — verify input validation on all user inputs
   - A07 Auth Failures — verify dev-mode bypass is disabled in production config
4. **Update `ROADMAP.md`**: Add Phase 8 for the MCP Host Gateway with references to the end-state architecture
5. **Update `docs/ARCHITECTURE.md`**: Add section on MCP Host Gateway and how it relates to the broader Archon platform
6. **Create `docs/DEPLOYMENT_GUIDE.md`**: Step-by-step for deploying the gateway to Azure Container Apps with Entra ID, APIM, Netskope NPA
7. Save security audit results to `docs/SECURITY_AUDIT.md`

---

## Execution Order

```
Phase 1 (Assess):
  WS-1: Health Assessment [BLOCKING — all other WS depend on this]

Phase 2 (Parallel):
  WS-2: Harden Backend  [depends on WS-1]
  WS-3: Harden Frontend [depends on WS-1]
  WS-4: Build Gateway   [depends on WS-1, can start immediately]
  WS-6: Cross-Cutting   [depends on WS-1, can start immediately]

Phase 3 (Converge):
  WS-5: Wire Archon into Gateway [depends on WS-2 + WS-4]

Phase 4 (Validate):
  Final validation: run ALL tests (Archon + Gateway), smoke tests, lint, build
  Produce final summary report at docs/FINAL_REPORT.md
```

---

## Acceptance Criteria

1. **Health report** exists at `docs/HEALTH_REPORT.md` with baseline metrics
2. **All existing Archon tests pass** (zero failures, zero errors)
3. **DLP double-prefix bug is fixed** — `/api/v1/dlp/policies` works
4. **All stub services identified** — at least 5 services wired to real DB
5. **Frontend has a working test runner** (vitest) with at least 4 component tests passing
6. **Frontend builds** (`npm run build`) with zero errors
7. **Gateway exists** at `gateway/` with all files listed in the directory structure
8. **Gateway tests pass** — at least 7 test files, all passing
9. **Gateway has working plugin system** — loads YAML, filters by group, dispatches tools
10. **Gateway auth middleware** validates JWT (or bypasses in dev mode)
11. **Gateway Dockerfile builds** successfully
12. **CI pipeline updated** to include gateway lint + test
13. **Security audit report** exists at `docs/SECURITY_AUDIT.md`
14. **All 4 report docs** exist: HEALTH_REPORT, HARDENING_REPORT, FRONTEND_HARDENING_REPORT, SECURITY_AUDIT
15. **Final validation passes**: all tests green, all builds succeed, all smoke tests pass

---

## Swarm Invocation

```
@swarm Execute the comprehensive plan in /Users/timothy.schwarz/archon/SWARM_PLAN.md

The plan has 6 workstreams across 4 phases. Start with WS-1 (Health Assessment) as it blocks everything else. Then run WS-2, WS-3, WS-4, and WS-6 in parallel. Then WS-5 (convergence). End with final validation.

Key constraints:
- DO NOT delete existing working code — only extend and fix
- DO NOT change the existing Archon API contract (contracts/openapi.yaml)
- The gateway is a SEPARATE FastAPI app at gateway/, not a refactor of the backend
- All tests must pass at the end (both Archon and gateway)
- Use the existing tech stack (Python 3.12, FastAPI, SQLModel, Redis, structlog)
- For the gateway, add: msal, openai, watchfiles to requirements.txt
- Follow existing code style and patterns from the Archon backend
- Every workstream must produce a report document in docs/
```
