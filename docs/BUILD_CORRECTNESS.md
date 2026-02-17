# Archon — 10 Build-Correctness Strategies

> How to ensure every agent builds it right the first time.

---

## The Problem

Agentic builds fail for predictable reasons: agents make assumptions about shared interfaces, generate code that doesn't integrate, skip error handling, produce untested edge cases, and drift from the architecture. The current scaffolding tells agents **what** to build but doesn't enforce **how** to build it correctly. These 10 strategies fix that.

---

## Strategy 1: Contract-First Development (API Contracts Before Code)

### The Problem It Solves
Agent-02 (UI) builds a frontend expecting `GET /api/v1/agents` to return `{ agents: [...] }` while Agent-01 (Backend) returns `{ data: [...], meta: {...} }`. Everything breaks at integration.

### The Solution
Before ANY agent writes a single line of code, the Orchestrator generates a **locked API contract file** — an OpenAPI 3.1 spec that every agent reads as immutable truth. No agent may deviate from the contract without a formal change request that the Orchestrator evaluates for downstream impact.

### Implementation
```
contracts/
├── openapi.yaml                # Master OpenAPI 3.1 spec (single source of truth)
├── events.yaml                 # WebSocket event schemas (JSON Schema)
├── grpc.proto                  # Internal service-to-service contracts (if applicable)
└── shared-types.ts             # TypeScript types auto-generated from openapi.yaml
```

**Enforcement rules for every agent prompt:**
```
RULE: Before writing any API endpoint, router, or service call:
1. Check contracts/openapi.yaml for the endpoint definition
2. If it exists → implement EXACTLY as specified (status codes, request/response shapes, error formats)
3. If it doesn't exist → STOP and request the Orchestrator to add it
4. Never invent an endpoint shape. Never assume a response format.
5. Run `openapi-diff` against the contract after implementation to verify 0 deviations.
```

**Why this works**: Agents can't drift if they're all implementing from the same locked specification. The contract is the integration test — if your code matches the contract, it integrates.

---

## Strategy 2: Executable Architecture Decision Records (ADRs)

### The Problem It Solves
Agent-07 (Router) picks Redis Streams for message queuing. Agent-08 (Lifecycle) picks RabbitMQ. Agent-09 (Cost) picks Celery with Redis. Three agents, three queuing approaches — nothing integrates.

### The Solution
Create a **binding ADR file** that pre-decides every technology choice, naming convention, directory structure, error format, and pattern. Each decision includes a code snippet showing the canonical pattern. Agents copy the pattern — they don't invent their own.

### Implementation
```
docs/ADR/
├── 001-api-response-format.md       # { "data": ..., "meta": ..., "errors": ... }
├── 002-error-handling-pattern.md     # HTTPException + ErrorResponse schema
├── 003-database-naming.md           # snake_case tables, singular names, UUID PKs
├── 004-task-queue-pattern.md        # Celery + Redis, task naming: module.verb_noun
├── 005-auth-middleware.md           # Keycloak JWT validation middleware pattern
├── 006-logging-format.md            # Structured JSON, correlation IDs, severity levels
├── 007-testing-patterns.md          # pytest fixtures, factory pattern, test naming
├── 008-websocket-protocol.md        # Message envelope: { type, payload, id, timestamp }
├── 009-env-config-pattern.md        # pydantic-settings, prefix ARCHON_, nested models
├── 010-import-structure.md          # Absolute imports, no circular deps, lazy loading
```

**Each ADR contains:**
```markdown
## Decision
Use X for Y.

## Canonical Code Pattern (COPY THIS)
```python
# Every agent must use exactly this pattern
```

## Anti-Patterns (DO NOT DO THIS)
```python
# If an agent generates this, it's wrong
```

## Rationale
Why this choice was made.
```

**Rule added to every agent prompt:**
```
RULE: Before implementing any architectural pattern, check docs/ADR/ for a binding decision.
If an ADR exists for this concern, use the canonical code pattern EXACTLY.
Do not innovate on infrastructure patterns — innovate on feature logic only.
```

---

## Strategy 3: Shared Code Skeleton with Interface Stubs

### The Problem It Solves
Agent-13 (Connectors) builds a connector base class with `async def connect(config: dict)`. Agent-14 (DocForge) expects `async def connect(self, credentials: ConnectorCredentials)`. They're building to different interfaces even though one depends on the other.

### The Solution
The Orchestrator generates a **skeleton codebase** before any agent starts — not implementations, but interfaces (abstract base classes, TypeScript interfaces, Pydantic models). Agents implement the stubs; they don't define them.

### Implementation
```
backend/app/interfaces/
├── __init__.py
├── agent_engine.py          # ABC: IAgentEngine with execute(), stream(), pause(), resume()
├── connector.py             # ABC: IConnector with connect(), list(), read(), write(), search(), watch()
├── router.py                # ABC: IRouter with route(), explain(), health_check()
├── dlp.py                   # ABC: IDLPPipeline with scan_input(), scan_output(), get_policy()
├── cost_tracker.py          # ABC: ICostTracker with record(), query(), forecast()
├── guardrails.py            # ABC: IGuardrails with validate_input(), validate_output()
├── version_store.py         # ABC: IVersionStore with save(), load(), diff(), rollback()
└── models/                  # Shared Pydantic models used across ALL agents
    ├── agent.py             # AgentDefinition, AgentVersion, AgentExecution
    ├── user.py              # User, Role, Permission, APIKey
    ├── cost.py              # TokenUsage, CostRecord, Budget
    ├── security.py          # DLPResult, GuardrailResult, AuditEntry
    ├── routing.py           # RoutingDecision, ModelHealth, RoutingPolicy
    └── common.py            # PaginatedResponse, ErrorResponse, HealthStatus
```

**Rule added to every agent prompt:**
```
RULE: You MUST implement the interfaces defined in backend/app/interfaces/.
Your concrete classes MUST inherit from the relevant ABC.
Your API endpoints MUST accept and return the Pydantic models from backend/app/interfaces/models/.
Do not create parallel model definitions — import from interfaces/models/.
If an interface is missing a method you need, request the Orchestrator to add it.
```

**Why this works**: When Agent-14 calls `connector.read()`, it knows exactly what arguments it takes and what it returns — because the interface was defined before either agent started.

---

## Strategy 4: Integration Test Contracts (Test-First Boundaries)

### The Problem It Solves
Every agent writes unit tests for their own code, and everything passes. But when Agent-02's frontend calls Agent-01's backend, the request format is wrong, the auth header is missing, and the WebSocket handshake uses a different protocol version.

### The Solution
Before agents build, the Orchestrator generates **integration test stubs** at every boundary. These are failing tests that define the expected contract between two agents. An agent's work isn't done until both their unit tests AND the integration tests pass.

### Implementation
```
tests/integration/
├── test_backend_frontend_contract.py     # Agent-01 ↔ Agent-02
├── test_backend_websocket_protocol.py    # WebSocket message format validation
├── test_router_cost_integration.py       # Agent-07 ↔ Agent-09
├── test_dlp_pipeline_middleware.py       # Agent-11 middleware in Agent-01's request chain
├── test_connector_smartscan_pipeline.py  # Agent-13 ↔ Agent-14
├── test_sandbox_redteam_integration.py   # Agent-05 ↔ Agent-10
├── test_governance_audit_trail.py        # Agent-12 reads Agent-01's audit logs
├── test_versioning_ui_sync.py            # Agent-06 ↔ Agent-02
└── conftest.py                           # Shared fixtures, docker-compose for test infra
```

**Example integration test (written BEFORE any agent starts):**
```python
# tests/integration/test_backend_frontend_contract.py

async def test_list_agents_returns_paginated_response(api_client):
    """Agent-01 MUST return this exact shape. Agent-02 depends on it."""
    response = await api_client.get("/api/v1/agents", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    body = response.json()
    assert "data" in body          # Not "agents", not "results"
    assert "meta" in body
    assert "total" in body["meta"]
    assert "page" in body["meta"]
    assert isinstance(body["data"], list)

async def test_create_agent_validates_required_fields(api_client):
    """Agent-01 MUST reject incomplete payloads with 422 + error details."""
    response = await api_client.post("/api/v1/agents", json={})
    assert response.status_code == 422
    body = response.json()
    assert "errors" in body
    assert any(e["field"] == "name" for e in body["errors"])
```

**Rule added to every agent prompt:**
```
RULE: Your work is NOT complete until:
1. All your unit tests pass (>80% coverage)
2. All integration tests in tests/integration/ that reference your agent pass
3. If an integration test fails, fix YOUR code to match the test — not the other way around
Integration tests are immutable contracts. Only the Orchestrator can modify them.
```

---

## Strategy 5: Build Verification Pipeline (Continuous Compilation Gate)

### The Problem It Solves
Agent-03 generates Python code that imports from `backend.app.services.agents` — a module that Agent-01 named `backend.app.services.agent_service`. The code looks correct in isolation but fails to import.

### The Solution
A **continuous build verification loop** runs every time any agent produces output. It doesn't wait for all agents to finish — it compiles/type-checks/lints incrementally. Failures are routed back to the responsible agent immediately, not discovered at the end.

### Implementation
```yaml
# .github/workflows/continuous-verify.yml (or run locally via Makefile)

Build Verification Pipeline (runs after EVERY agent output):

  Step 1 — Syntax Check:
    - Python: `python -m py_compile` on every .py file
    - TypeScript: `tsc --noEmit` on entire frontend
    - YAML/JSON: schema validation on all config files

  Step 2 — Import Resolution:
    - Python: `importlib.import_module()` on every module
    - TypeScript: Verify all imports resolve

  Step 3 — Type Check:
    - Python: `mypy --strict` on backend/
    - TypeScript: `tsc --strict` (already in Step 1)

  Step 4 — Lint:
    - Python: `ruff check` + `ruff format --check`
    - TypeScript: `eslint` + `prettier --check`

  Step 5 — Unit Tests:
    - `pytest backend/tests/ --tb=short`
    - `vitest run` for frontend

  Step 6 — Integration Tests:
    - `pytest tests/integration/ --tb=short`

  Step 7 — Contract Validation:
    - `openapi-diff contracts/openapi.yaml <generated-spec>` → must be 0 diffs
```

**Rule added to every agent prompt:**
```
RULE: After producing ANY code output, immediately run:
  make verify  (or the equivalent pipeline)
If it fails, fix the failure BEFORE reporting completion.
You are not "done" until `make verify` exits 0.
```

**Why this works**: Errors are caught in seconds, not days. An agent can't claim "done" with broken imports or type errors. The pipeline is the objective judge.

---

## Strategy 6: Dependency-Ordered Execution with Output Locking

### The Problem It Solves
Agent-02 (UI) starts building before Agent-01 (Backend) has finalized the API. Agent-02 makes assumptions. Agent-01 finishes with different endpoints. Agent-02's work is wasted.

### The Solution
Enforce a **strict dependency gate** — no agent starts until its dependencies have completed AND their outputs are locked (immutable). Once Agent-01's output is locked, no retroactive changes are allowed without a formal migration path.

### Implementation
```json
// Enhanced swarm-state.json
{
  "agents": {
    "agent-01": {
      "status": "completed",
      "output_locked": true,           // Once true, outputs are IMMUTABLE
      "output_hash": "sha256:abc123",  // Hash of all output files
      "locked_at": "2026-02-15T10:00:00Z",
      "breaking_change_requests": []   // If Agent-01 needs to change, it goes here
    },
    "agent-02": {
      "status": "pending",
      "can_start": false,              // Computed: all deps locked?
      "waiting_on": ["agent-01"],      // Agents that must lock before this starts
      "started_with_contract_hash": null  // Records which contract version it built against
    }
  }
}
```

**Orchestrator enforcement:**
```
EXECUTION RULES:
1. Agent may only start when ALL dependencies have status "completed" AND output_locked: true
2. Once locked, an agent's output files CANNOT be modified
3. If a locked agent needs to change (bug found), a BREAKING CHANGE REQUEST is filed:
   a. Orchestrator evaluates downstream impact
   b. All affected downstream agents are notified
   c. Changes include migration instructions
   d. Affected agents re-run ONLY the impacted portions
4. Every agent records the contract_hash it built against — if the contract changes, it knows
```

---

## Strategy 7: Golden Path Examples (Reference Implementation Per Pattern)

### The Problem It Solves
You tell 17 agents "build a FastAPI router with CRUD endpoints" and you get 17 different styles — different error handling, different pagination, different auth patterns, different response shapes. They all "work" individually but feel like 17 different codebases glued together.

### The Solution
Create a **complete, working reference implementation** of one vertical slice (e.g., the "Templates" CRUD) that demonstrates EVERY pattern. All agents must follow this exact style. It's not a template — it's the canonical example.

### Implementation
```
docs/golden-path/
├── README.md                    # "Read this before writing ANY code"
├── example-router.py            # Complete FastAPI router with all patterns
├── example-service.py           # Business logic layer pattern
├── example-model.py             # SQLModel + Pydantic schema pattern
├── example-test.py              # pytest test with fixtures, mocking, assertions
├── example-component.tsx        # React component with hooks, state, API calls
├── example-component.test.tsx   # Playwright + Vitest test pattern
└── example-connector.py         # Connector plugin pattern
```

**What the golden path example includes (backend):**
```python
# docs/golden-path/example-router.py
# THIS IS THE CANONICAL PATTERN. EVERY ROUTER MUST LOOK LIKE THIS.

from fastapi import APIRouter, Depends, HTTPException, Query
from app.interfaces.models.common import PaginatedResponse, ErrorResponse
from app.services.template_service import TemplateService
from app.middleware.auth import require_auth, CurrentUser
from app.middleware.audit import audit_log

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])

@router.get("/", response_model=PaginatedResponse[TemplateRead])
@audit_log(action="list_templates")
async def list_templates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = None,
    current_user: CurrentUser = Depends(require_auth),
    service: TemplateService = Depends(),
) -> PaginatedResponse[TemplateRead]:
    # PATTERN: Service handles logic, router handles HTTP concerns only
    result = await service.list(
        page=page, page_size=page_size, search=search, user=current_user
    )
    return PaginatedResponse(data=result.items, meta={"total": result.total, "page": page})

@router.post("/", response_model=TemplateRead, status_code=201)
@audit_log(action="create_template")
async def create_template(
    body: TemplateCreate,
    current_user: CurrentUser = Depends(require_auth),
    service: TemplateService = Depends(),
) -> TemplateRead:
    # PATTERN: Validation in Pydantic model, auth in middleware, logic in service
    return await service.create(body, user=current_user)

# PATTERN: Error handling — let FastAPI handle validation (422),
# raise HTTPException for business logic errors (404, 403, 409)
# NEVER return {"error": "..."} — use ErrorResponse schema
```

**Rule added to every agent prompt:**
```
RULE: Before writing any code, read docs/golden-path/ completely.
Your code MUST follow the same patterns: same decorator order, same dependency injection,
same error handling, same response shapes, same test structure.
If your code doesn't look like the golden path, refactor it until it does.
```

---

## Strategy 8: Agent Self-Verification Checklist (Pre-Submission Gate)

### The Problem It Solves
Agents "finish" their work with passing tests but miss critical concerns: no error handling for network failures, no pagination on list endpoints, no rate limiting, no input validation, no logging, hardcoded config values, missing auth checks on admin endpoints.

### The Solution
Every agent must complete a **mandatory self-verification checklist** before reporting completion. The checklist is specific, measurable, and binary (yes/no). If any item is "no," the agent must fix it before proceeding.

### Implementation
```markdown
# MANDATORY SELF-VERIFICATION CHECKLIST
# Complete ALL items before reporting status: "completed"

## Code Quality
- [ ] Every function has type hints (parameters AND return type)
- [ ] No `Any` types except where genuinely unavoidable (document why)
- [ ] No hardcoded values — all config via environment/pydantic-settings
- [ ] No secrets in code (API keys, passwords, tokens)
- [ ] Imports are absolute, not relative
- [ ] No unused imports or variables (ruff catches this)
- [ ] All TODOs resolved (no "TODO: implement later")

## API Endpoints (if applicable)
- [ ] Every endpoint has auth middleware applied
- [ ] Every list endpoint supports pagination (page, page_size)
- [ ] Every endpoint returns the correct status code (201 for create, 204 for delete, etc.)
- [ ] Every endpoint has OpenAPI documentation (summary, description, response models)
- [ ] Error responses use the shared ErrorResponse schema
- [ ] Input validation via Pydantic — no manual validation in route handlers

## Error Handling
- [ ] Network calls wrapped in try/except with specific exception types
- [ ] Database operations handle IntegrityError (unique constraint violations)
- [ ] External API calls have timeout, retry, and circuit breaker
- [ ] All errors logged with structured context (correlation_id, user_id, etc.)
- [ ] No bare `except:` or `except Exception:` — be specific

## Security
- [ ] No SQL injection possible (all queries parameterized via SQLModel)
- [ ] No XSS vectors (all user input escaped in responses)
- [ ] Auth required on every non-public endpoint
- [ ] Admin endpoints require admin role
- [ ] File uploads validated (type, size, content)
- [ ] Rate limiting applied where appropriate

## Testing
- [ ] Happy path tests for every endpoint/function
- [ ] Error path tests (invalid input, unauthorized, not found)
- [ ] Edge cases tested (empty lists, max values, special characters)
- [ ] Tests are independent — no test depends on another test's state
- [ ] Test coverage ≥ 80% for new code
- [ ] Integration tests pass (tests/integration/)

## Documentation
- [ ] Module docstring explaining purpose
- [ ] Complex functions have docstrings
- [ ] OpenAPI spec matches implementation (run contract diff)
- [ ] README or doc page updated if feature affects user-facing behavior
```

**Rule added to every agent prompt:**
```
RULE: Before setting your status to "completed", complete EVERY item on the
self-verification checklist in docs/SELF_VERIFICATION_CHECKLIST.md.
For each item, verify by running the relevant command or reviewing the code.
If ANY item is unchecked, fix it first. No exceptions.
Include the completed checklist in your PR description.
```

---

## Strategy 9: Incremental Integration Testing (Build One Vertical Slice First)

### The Problem It Solves
17 agents build 17 components in parallel. At the end, nothing fits together. The "big bang integration" moment is catastrophic — too many failures, too hard to debug, finger-pointing between agents.

### The Solution
**Don't build horizontally (all of backend, then all of frontend). Build vertically — one complete feature end-to-end first**, then expand. The first vertical slice proves the entire architecture works before scaling out.

### Implementation
```
PHASE 0 (NEW — before Phase 1):
  Build ONE complete vertical slice: "Create and Execute a Simple Agent"

  This single flow touches EVERY layer:
  ┌────────────┐
  │ Frontend   │ → Drag 2 nodes onto canvas, connect them, click "Run"
  ├────────────┤
  │ API        │ → POST /api/v1/agents (create), POST /api/v1/execute (run)
  ├────────────┤
  │ Auth       │ → JWT validation middleware
  ├────────────┤
  │ LangGraph  │ → Execute a 2-node state machine
  ├────────────┤
  │ WebSocket  │ → Stream execution output to frontend
  ├────────────┤
  │ Database   │ → Save agent definition, save execution record
  ├────────────┤
  │ Audit      │ → Log the create and execute events
  ├────────────┤
  │ Cost       │ → Record token usage from the LLM call
  ├────────────┤
  │ Docker     │ → docker-compose up runs the entire slice
  └────────────┘

  This vertical slice is built by Agent-01 ALONE (or Agent-01 + Agent-02 pair).
  It becomes the integration test harness for everything that follows.
  Every subsequent agent adds their feature TO this working slice — never breaking it.
```

**Enforcement:**
```
RULE: The vertical slice must stay green at all times.
After EVERY agent's output, run the vertical slice E2E test:
  make test-slice
If it breaks, the agent who broke it fixes it before continuing.
The slice is the heartbeat of the project — if it's green, we're healthy.
```

**Why this works**: You discover architectural problems on day 1 with 2 endpoints, not on day 30 with 200 endpoints. Every agent adds to a working system instead of building in isolation.

---

## Strategy 10: Automated Regression Guardian (Never Break What Works)

### The Problem It Solves
Agent-11 (DLP) adds middleware to the request chain. It works for Agent-11's tests. But it breaks Agent-03 (NL Wizard) because the DLP middleware rejects the wizard's legitimate prompts as "potential prompt injection." Nobody notices until the Master Validator runs weeks later.

### The Solution
An **always-running regression guardian** — a background process that re-runs the FULL test suite after every agent's output. Not just the agent's own tests — ALL tests. If any pre-existing test breaks, the agent who caused it is immediately blocked until they fix the regression.

### Implementation
```yaml
# Regression Guardian (runs continuously)

TRIGGER: Any file change in backend/, frontend/, security/, integrations/, ops/, data/

EXECUTION:
  1. Identify which agent made the change (from swarm-state.json)
  2. Run FULL test suite:
     - pytest backend/tests/ --tb=short -q
     - pytest tests/integration/ --tb=short -q
     - vitest run (frontend)
     - make test-slice (vertical slice)
  3. Compare results against last known good state:
     - New failures? → BLOCK the agent, report exact failures
     - New passes? → Great, update the baseline
     - Flaky tests? → Flag for investigation, don't block

BLOCKING BEHAVIOR:
  If Agent-11 breaks a test that Agent-03 wrote:
  1. Agent-11 status → "blocked_by_regression"
  2. Agent-11 receives:
     "Your change broke test_nl_wizard_generates_valid_agent in test_nl_wizard.py.
      The test expects DLP middleware to allow wizard prompts.
      Fix: Add a DLP bypass for internal wizard service calls,
      or adjust your middleware to whitelist the wizard's user-agent."
  3. Agent-11 cannot set status "completed" until regression is resolved
  4. If Agent-11 can't fix it in 2 attempts, Orchestrator mediates
```

**State tracking:**
```json
// swarm-state.json addition
{
  "regression_guardian": {
    "last_run": "2026-02-15T10:30:00Z",
    "baseline_test_count": 347,
    "baseline_pass_count": 347,
    "current_pass_count": 345,
    "regressions": [
      {
        "test": "test_nl_wizard_generates_valid_agent",
        "file": "tests/test_nl_wizard/test_wizard.py",
        "broken_by": "agent-11",
        "broken_at": "2026-02-15T10:28:00Z",
        "error": "DLPBlockedError: Input classified as potential prompt injection",
        "status": "open"
      }
    ]
  }
}
```

---

## Summary: The 10 Strategies at a Glance

| # | Strategy | What It Prevents | When It Runs |
|---|----------|-----------------|--------------|
| 1 | **Contract-First API Specs** | Mismatched request/response shapes between agents | Before any agent starts |
| 2 | **Binding ADRs** | Inconsistent tech choices and patterns | Before any agent starts |
| 3 | **Interface Stubs** | Incompatible class interfaces and data models | Before any agent starts |
| 4 | **Integration Test Contracts** | Boundary failures between components | Before any agent starts; run continuously |
| 5 | **Build Verification Pipeline** | Syntax errors, broken imports, type mismatches | After every agent output |
| 6 | **Dependency-Ordered Execution** | Building against unstable/changing dependencies | Enforced by Orchestrator |
| 7 | **Golden Path Examples** | 17 different coding styles in one codebase | Before any agent starts |
| 8 | **Self-Verification Checklist** | Missing auth, pagination, error handling, tests | Before agent reports "completed" |
| 9 | **Vertical Slice First** | Big-bang integration failures | Phase 0 (new phase) |
| 10 | **Regression Guardian** | Agent X breaks Agent Y's working code | After every agent output |

### Execution Order

```
BEFORE ANY AGENT STARTS (Orchestrator does these):
  ├── Generate contracts/openapi.yaml (Strategy 1)
  ├── Write docs/ADR/*.md (Strategy 2)
  ├── Create backend/app/interfaces/ stubs (Strategy 3)
  ├── Write tests/integration/ test stubs (Strategy 4)
  ├── Create docs/golden-path/ examples (Strategy 7)
  └── Create docs/SELF_VERIFICATION_CHECKLIST.md (Strategy 8)

PHASE 0 — VERTICAL SLICE (Strategy 9):
  └── Agent-01 builds one complete end-to-end flow

DURING BUILD (every agent, every output):
  ├── Run build verification pipeline (Strategy 5)
  ├── Enforce dependency order + output locking (Strategy 6)
  ├── Run regression guardian (Strategy 10)
  └── Agent completes self-verification checklist (Strategy 8)
```

This transforms the build from "17 agents working independently and hoping it fits together" into "17 agents implementing against locked contracts, verified continuously, with immediate feedback on failures."
