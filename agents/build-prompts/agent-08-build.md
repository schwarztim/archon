# Agent 08 — Model Router + Vault Secrets

## Role

You are a senior full-stack engineer building the Model Router with Vault-backed secret management for the Archon AI orchestration platform. You write production-grade TypeScript (React 19, strict mode) and Python (FastAPI, SQLModel). You follow every constraint listed below without exception.

---

## Platform Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession |
| Frontend | React 19, TypeScript strict, shadcn/ui, Tailwind CSS, React Flow (@xyflow/react) |
| Auth | JWT via Keycloak |
| Secrets | HashiCorp Vault via `backend/app/secrets/manager.py` |

---

## Context

The Model Router is the platform's intelligent LLM routing layer. It manages provider credentials (stored in Vault), provides model selection logic via configurable rules, and exposes health/cost observability. Every agent execution flows through the router to determine which LLM to call. This agent is the security-critical integration point between the platform and external AI providers.

---

## What Already Exists

| File | Lines | Action |
|------|-------|--------|
| `frontend/src/pages/ModelRouterPage.tsx` | 548 | **MODIFY** — Has Providers section (NO API key field), Models section, Rules section (raw JSON conditions). Add API key field, test button, health dashboard, visual rule builder |
| `frontend/src/api/router.ts` | 123 | **MODIFY** — Router API client. Extend with test, health, route endpoints |
| `backend/app/routes/router.py` | 322 | **MODIFY** — Router CRUD. Extend with test connection, health, route with explanation |
| `backend/app/routes/models.py` | 262 | **MODIFY** — Provider/model CRUD. Extend with Vault integration for credentials |
| `backend/app/services/router_service.py` | 620 | **MODIFY** — Router service. Extend with routing logic, health monitoring, test connection |
| `backend/app/models/router.py` | 199 | **MODIFY** — Router models. Extend with visual-friendly rule schema |
| `backend/app/secrets/manager.py` | — | **USE** — VaultSecretsManager with `get()`, `put()`, `delete()`, `list()` operations |

---

## What to Build

### Provider Management with Vault

#### Provider Credential Flow

1. **Frontend**: Provider form includes "API Key" password field (masked by default, toggle to reveal)
2. **On Save**: Frontend sends API key in request body
3. **Backend**: Stores API key in Vault at path `archon/providers/{provider_id}/api_key` using `SecretsManager.put()`
4. **Backend**: Stores only `vault_path` in the provider's database record — never the actual key
5. **On Read**: Backend returns provider WITHOUT the API key. Frontend shows "••••••••" with a "Key saved ✓" indicator
6. **On Update**: If API key field is non-empty, overwrite in Vault. If empty, keep existing Vault value
7. **On Delete**: Delete Vault secret at provider's vault_path, then delete DB record

#### Provider Types and Credential Schemas

Each provider type has a specific credential schema that drives the form fields:

| Provider | Fields |
|----------|--------|
| **OpenAI** | API Key |
| **Anthropic** | API Key |
| **Azure OpenAI** | API Key, Endpoint URL, Deployment Name, API Version |
| **Ollama** | Base URL (no key needed) |
| **HuggingFace** | API Token, Endpoint URL (optional) |
| **Google AI** | API Key, Project ID (optional) |
| **AWS Bedrock** | Access Key ID, Secret Access Key, Region |
| **Custom/OpenAI-Compatible** | API Key, Base URL |

Store all credential fields in Vault under `archon/providers/{provider_id}/credentials` as a JSON object.

#### Test Connection

**`POST /api/v1/models/providers/{id}/test`**

1. Retrieve credentials from Vault
2. Make a lightweight API call to the provider (e.g., list models, simple completion with 1 token)
3. Return result:
```json
{
  "data": {
    "success": true,
    "latency_ms": 234,
    "models_found": 15,
    "message": "Successfully connected to OpenAI. Found 15 models."
  }
}
```
Or on failure:
```json
{
  "data": {
    "success": false,
    "error": "Authentication failed: Invalid API key",
    "message": "Could not connect to OpenAI. Check your API key."
  }
}
```

#### Provider Health Dashboard

**`GET /api/v1/models/providers/{id}/health`**

Return health metrics for a provider:
```json
{
  "data": {
    "provider_id": "uuid",
    "status": "healthy",
    "metrics": {
      "avg_latency_ms": 450,
      "p95_latency_ms": 1200,
      "p99_latency_ms": 2500,
      "error_rate_percent": 0.5,
      "requests_last_hour": 1250,
      "total_tokens_last_hour": 450000,
      "total_cost_last_hour": 3.45
    },
    "circuit_breaker": {
      "state": "closed",
      "failure_count": 2,
      "threshold": 10,
      "last_failure_at": "ISO8601"
    }
  }
}
```

**`GET /api/v1/models/providers/health`** — Aggregate health for all providers.

---

### Visual Routing Rule Builder

Replace JSON conditions with a visual rule builder.

#### Rule Schema (Backend)

Update the rule model to store conditions as structured arrays instead of raw JSON:

```python
class RoutingCondition(SQLModel):
    field: str       # capability, max_cost, min_context, sensitivity_level, tenant_tier, time_of_day
    operator: str    # equals, not_equals, contains, greater_than, less_than, in, not_in
    value: Any       # string, number, or list

class RoutingRule(SQLModel):
    id: uuid
    name: str
    conditions: list[RoutingCondition]  # ALL conditions must match (AND logic)
    target_model_id: uuid
    priority: int                        # lower = higher priority
    enabled: bool
    description: str | None
```

#### Rule Builder UI (Frontend)

**Each rule is a visual card:**
```
Rule #1: "Route sensitive content to GPT-4" [priority: 1] [enabled ✓]
┌──────────────────────────────────────────────────────────────┐
│ IF  [sensitivity_level ▼] [equals        ▼] [high        ] │
│ AND [capability         ▼] [equals        ▼] [chat        ] │
│                                              [+ Add Condition]│
│ THEN route to → [gpt-4-turbo ▼]                             │
└──────────────────────────────────────────────────────────────┘
```

**Field dropdown options:**
- `capability` — chat, completion, embedding, vision, function_calling
- `max_cost` — numeric (cost per 1K tokens)
- `min_context` — numeric (minimum context window size)
- `sensitivity_level` — low, medium, high, critical
- `tenant_tier` — free, standard, premium, enterprise
- `time_of_day` — off_peak, peak (or specific hour range)
- `model_preference` — string (user-requested model family)

**Operator dropdown options:**
- equals, not_equals, contains, greater_than, less_than, in, not_in

**Actions:**
- "+ Add Condition" button adds a new condition row to the rule
- "× " button removes a condition row
- Drag handle for priority reordering across rules
- Enable/disable toggle per rule
- Delete rule with confirmation

#### Fallback Chain

Below the rules list, a "Fallback Chain" section:

```
Fallback Order (drag to reorder):
┌─────────────────────────┐
│ 1. gpt-4-turbo     ⠿  │
│ 2. claude-3-sonnet  ⠿  │
│ 3. llama-3-70b      ⠿  │
└─────────────────────────┘
```

- Drag-drop reordering
- When no rule matches, try models in fallback order
- Skip unhealthy providers (circuit breaker open)

---

### Routing Decision Explainability

**`POST /api/v1/router/route`**

Accept a routing request and return the selected model with explanation:

**Request:**
```json
{
  "capability": "chat",
  "sensitivity_level": "high",
  "max_cost": 0.01,
  "tenant_tier": "premium",
  "preferred_model": null
}
```

**Response:**
```json
{
  "data": {
    "model_id": "uuid",
    "model_name": "gpt-4-turbo",
    "provider_id": "uuid",
    "provider_name": "OpenAI",
    "reason": "Matched rule #1 'Route sensitive content to GPT-4': sensitivity_level=high AND capability=chat",
    "alternatives": [
      {
        "model_name": "claude-3-sonnet",
        "reason": "Fallback #1"
      }
    ]
  }
}
```

If no rules match:
```json
{
  "data": {
    "model_id": "uuid",
    "model_name": "claude-3-sonnet",
    "provider_id": "uuid",
    "provider_name": "Anthropic",
    "reason": "No rules matched. Selected fallback #1: claude-3-sonnet",
    "alternatives": [...]
  }
}
```

---

## OSS Patterns to Follow

### 1. Dify Model Provider Management (`dify/web/app/components/header/account-setting/model-provider-page/`)
Dify shows provider cards with setup/credential forms. Each provider type has its own form layout — OpenAI needs just an API key, Azure needs endpoint + key + deployment name + API version. Credentials are stored encrypted in the database. A "Validate" button tests the credentials. **Adaptation**: Same per-provider form pattern driven by `credential_schema`, but store all credentials in Vault instead of encrypted DB columns. The provider form dynamically renders fields based on the provider type's schema.

### 2. Dify Model Runtime (`dify/api/core/model_runtime/`)
Dify's model_runtime module has a provider/model registry with capability flags (text-generation, embeddings, speech2text, etc.), pricing info, and credential schemas per provider. Each provider is a plugin with a `validate_credentials()` method. **Adaptation**: Each provider type in Archon should have a `credential_schema` (list of field definitions with name, type, required, description) that drives the frontend form. The test connection endpoint calls a provider-specific validation function.

### 3. Coze Studio Model Configuration
Coze allows multiple model providers with per-provider credential forms and a test button. After setup, models appear in a unified model selector across the platform. Health and usage metrics are surfaced per provider. **Adaptation**: Include test connection with latency measurement and health monitoring with circuit breaker status. The unified model list (`GET /api/v1/router/models`) is consumed by Agent 05's model selector and Agent 06's execution engine.

---

## Backend Deliverables

| Endpoint | Method | Description |
|----------|--------|-------------|
| `PUT /api/v1/models/providers/{id}` | PUT | Create/update provider. Store credentials in Vault, return provider without secrets |
| `POST /api/v1/models/providers/{id}/test` | POST | Test connection using Vault-stored credentials. Return success/failure with latency |
| `GET /api/v1/models/providers/{id}/health` | GET | Provider health metrics: latency percentiles, error rate, circuit breaker |
| `GET /api/v1/models/providers/health` | GET | Aggregate health dashboard for all providers |
| `POST /api/v1/router/route` | POST | Route a request to a model. Evaluate rules, return model + explanation |
| `GET /api/v1/router/rules` | GET | List routing rules with structured conditions |
| `PUT /api/v1/router/rules` | PUT | Save routing rules (bulk update with priority ordering) |
| `PUT /api/v1/router/fallback` | PUT | Save fallback chain ordering |

**Service changes:**
- `router_service.py` — Add `route_request()` with rule evaluation and explanation
- `router_service.py` — Add `test_connection()` with provider-specific API calls
- `router_service.py` — Add `get_health()` with metrics aggregation and circuit breaker
- Provider credential flow: Vault put on save, Vault get on test/use, Vault delete on provider delete
- Credential schema registry: per-provider-type field definitions

---

## Frontend Deliverables

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/ModelRouterPage.tsx` | **MODIFY** | Add API key field to provider form, test connection button, health dashboard section, replace JSON rules with visual builder |
| `frontend/src/components/router/ProviderForm.tsx` | **CREATE** | Dynamic per-provider credential form driven by credential_schema. Password fields masked. "Key saved ✓" indicator |
| `frontend/src/components/router/TestConnectionButton.tsx` | **CREATE** | Button with loading state → success (green check + latency) or failure (red X + error message) |
| `frontend/src/components/router/HealthDashboard.tsx` | **CREATE** | Provider health cards: latency gauge, error rate bar, circuit breaker status indicator, cost/hour |
| `frontend/src/components/router/RuleBuilder.tsx` | **CREATE** | Visual condition rows: IF [field] [operator] [value] THEN [model]. Add/remove conditions, drag priority |
| `frontend/src/components/router/FallbackChain.tsx` | **CREATE** | Drag-drop ordered list of fallback models with provider badges |
| `frontend/src/api/router.ts` | **MODIFY** | Add `testConnection()`, `getHealth()`, `routeRequest()`, `saveRules()`, `saveFallback()` |

---

## Integration Points

| Agent | Integration |
|-------|------------|
| Agent 01 | Agent model — agents store `llm_config` referencing router models |
| Agent 05 | Model selector — Step 2 of wizard uses `GET /api/v1/router/models` to populate dropdown |
| Agent 06 | Execution — execution engine calls `POST /api/v1/router/route` to select model for each LLM step |
| Agent 12 | Security — sensitivity_level routing field integrates with DLP classification |
| Agent 17 | Secrets — all provider credentials flow through Vault via SecretsManager |

---

## Acceptance Criteria

1. Provider form has credential fields (API Key, Endpoint, etc.) appropriate to provider type — values stored in Vault, not in the database
2. "Test Connection" validates provider credentials, shows success with latency or failure with error message
3. Health dashboard shows live provider latency (avg, p95, p99), error rate, and circuit breaker status
4. Routing rules use visual builder rows (IF [field] [operator] [value] THEN [model]), not JSON textarea
5. Conditions within a rule support AND logic with add/remove condition rows
6. Fallback chain is configurable via drag-drop model ordering
7. `POST /api/v1/router/route` returns selected model with human-readable explanation of which rule matched
8. No API keys or credentials are visible in any API response or database record — only `vault_path` stored in DB
9. Multiple provider types supported with type-specific credential forms: OpenAI, Anthropic, Azure OpenAI, Ollama, HuggingFace, Google AI, AWS Bedrock, Custom
10. Provider deletion cleans up the corresponding Vault secret
11. Rule priority reordering via drag-drop persists correctly
12. Health metrics update in real-time (polling every 30 seconds)

---

## Constraints

1. **Response Envelope** — Every API response uses the standard envelope: `{ "data": T, "meta": { "request_id", "timestamp" } }`. Errors: `{ "error": { "code", "message", "details" } }`.
2. **JWT Auth** — Every endpoint requires a valid JWT Bearer token. Use `get_current_user` dependency. No anonymous access.
3. **Vault Secrets** — All credentials (API keys, OAuth tokens) are stored and retrieved via `SecretsManager` (`backend/app/secrets/manager.py`). Never store secrets in the database or environment variables at runtime. This agent is the PRIMARY consumer of Vault — ensure all credential CRUD flows through Vault.
4. **Tenant Scoping** — All database queries must be scoped to `tenant_id` from the JWT. Users must never see or modify another tenant's data. Provider credentials are scoped: `archon/tenants/{tenant_id}/providers/{provider_id}/credentials`.
5. **Audit Logging** — All create, update, and delete operations must produce an `AuditLog` entry with: actor, action, resource_type, resource_id, before/after diff, timestamp. Credential changes log "credentials_updated" without logging the actual secret values.
6. **Test Coverage** — Minimum 80% line coverage for all new code. Write unit tests for services, integration tests for API routes, and component tests for React components. Mock Vault calls in tests.
7. **Dark/Light Mode** — All UI components must render correctly in both dark and light themes. Use Tailwind's `dark:` variants. Never hardcode colors.
8. **Accessibility** — All interactive elements must have ARIA labels. All forms must be keyboard-navigable. Color is never the sole indicator of state.
9. **TypeScript Strict** — `strict: true` in tsconfig. No `any` types. No `@ts-ignore`. All props interfaces explicitly defined.
10. **SQLModel + Alembic** — All schema changes require an Alembic migration. Use `AsyncSession` for all database operations. No raw SQL unless absolutely necessary.
11. **Error Handling** — Backend: raise `HTTPException` with appropriate status codes. Frontend: try/catch with toast notifications for user-facing errors. Never swallow errors silently. Vault connection failures must surface clearly.
12. **No Placeholder Code** — Every function must be fully implemented. No `TODO`, `FIXME`, `pass`, or `...` in delivered code. Stub integrations with realistic mock data if the dependency doesn't exist yet.
