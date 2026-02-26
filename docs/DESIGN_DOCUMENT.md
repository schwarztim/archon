# Archon Platform Repair — Implementation Design Document

> **Status:** Blueprint for WS-0 through WS-8 implementation
> **Produced by:** WS-0 Architect
> **Revision:** 2026-02-26

---

## 0. Decisions Applied

| Decision | Choice | Rationale |
|---|---|---|
| Workflow business logic | Create `services/workflow_service.py`, thin routes | Matches existing service/route separation pattern |
| API key persistence | Use `SettingsAPIKey` + add `rate_limit` column | Already wired to settings routes; avoid table duplication |
| Audit log URL | Change backend prefix to `/audit-logs` | Matches frontend convention, more REST-standard |
| Color replacement strategy | Bulk `sed`/`find` + ThemeProvider wrapper | 1,000+ occurrences; manual is impractical |

---

## WS-0: Health Assessment & Baseline

### Purpose
Read-only diagnostic run. No code changes. Produces `docs/HEALTH_REPORT.md`.

### Acceptance Output
`docs/HEALTH_REPORT.md` containing:
- pytest pass/fail counts with file-level breakdown
- smoke_test.sh and validate_platform.sh output
- Docker build exit codes for backend and frontend
- `ruff check` violation count
- `npm run build` errors and `tsc --noEmit` error count
- Azure OpenAI HTTP status code
- OIDC discovery JSON excerpt

### Risk
None — read-only.

---

## WS-1: Backend Route & URL Fixes

### 1.1 Marketplace Triple-Prefix

**File:** `backend/app/routes/marketplace.py`
**Lines:** 325, 342, 360, 378, 410, 429, 446, 461

**Problem (concrete):**
```
include_router(marketplace_router, prefix="/api/v1")   # main.py:L193
APIRouter(prefix="/marketplace")                        # marketplace.py:L? (router definition)
@router.post("/api/v1/marketplace/publishers")         # marketplace.py:L325
```
Actual resolved path: `/api/v1/marketplace/api/v1/marketplace/publishers`

**Fix:** Strip the `/api/v1/marketplace` prefix from all 8 enterprise route decorators. Replace with relative paths:

| Original | Corrected |
|---|---|
| `@router.post("/api/v1/marketplace/publishers")` | `@router.post("/publishers")` |
| `@router.post("/api/v1/marketplace/packages")` | `@router.post("/packages")` |
| `@router.post("/api/v1/marketplace/packages/{package_id}/install")` | `@router.post("/packages/{package_id}/install")` |
| `@router.get("/api/v1/marketplace/packages/search")` | `@router.get("/packages/search")` |
| `@router.post("/api/v1/marketplace/packages/{package_id}/rate")` | `@router.post("/packages/{package_id}/rate")` |
| `@router.get("/api/v1/marketplace/publishers/analytics")` | `@router.get("/publishers/analytics")` |
| `@router.get("/api/v1/marketplace/packages/{package_id}/verify")` | `@router.get("/packages/{package_id}/verify")` |
| `@router.get("/api/v1/marketplace/categories")` | `@router.get("/categories")` |

**Verify:** `GET /api/v1/marketplace/categories` → 200

---

### 1.2 Sentinel `enterprise_router` Not Registered

**Files:**
- `backend/app/routes/sentinelscan.py` L297 — `enterprise_router = APIRouter(prefix="/sentinel", ...)`
- `backend/app/main.py` L45 — import line omits `enterprise_router`

**Fix in `main.py` L45:**
```python
# Before
from app.routes.sentinelscan import router as sentinelscan_router, scan_router as sentinelscan_scan_router

# After
from app.routes.sentinelscan import (
    router as sentinelscan_router,
    scan_router as sentinelscan_scan_router,
    enterprise_router as sentinelscan_enterprise_router,
)
```

**Add registration in Phase 3 block (after L181):**
```python
application.include_router(sentinelscan_enterprise_router, prefix=settings.API_PREFIX)
```

**Fix duplicate `/posture`:** `sentinelscan.py` has `@router.get("/posture")` at L286 and `scan_router` has another `GET /posture` at L613. Rename the `scan_router` version to `GET /posture/scan` to avoid conflict.

**Verify:** `GET /api/v1/sentinel/discover` → 200; no 404 white screen.

---

### 1.3 Audit Log URL Mismatch

**Files:**
- `backend/app/routes/audit_logs.py` L20 — `router = APIRouter(prefix="/audit/logs", ...)`
- `frontend/src/api/governance.ts` L221 — calls `"/audit-logs/"`

**Fix:** Change backend router prefix only:
```python
# Before (audit_logs.py L20)
router = APIRouter(prefix="/audit/logs", tags=["audit-logs"])

# After
router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])
```

**Smoke test correction** — `scripts/smoke_test.sh` L42 already tests `/api/v1/audit-logs/` (correct after this fix). No change needed there.

**Verify:** Frontend audit log page loads with entries; no 404.

---

### 1.4 System Health Frontend Alignment

**File:** Frontend health API client (locate via `grep -r "health" frontend/src/api/`)

**Check:** Backend correctly serves `/api/v1/health` with DB+Redis+Vault status (already in `health.py`). If the frontend calls `/health` (liveness only), update it to call `/api/v1/health`.

**No backend change needed.** This is a frontend API client correction only.

---

### 1.5 Smoke Test Double-Prefix Fix

**File:** `scripts/smoke_test.sh` L50

```bash
# Before
('GET', '/api/v1/api/v1/dlp/policies', 'exists'),

# After
('GET', '/api/v1/dlp/policies', 'exists'),
```

---

### WS-1 Risk Areas
- Marketplace FK violations on install remain after route fix — FK issue is separate (WS-2 territory); route fix gets endpoints reachable.
- Sentinel duplicate `/posture` rename must not break any existing callers of the old `scan_router` posture URL.

---

## WS-2: In-Memory → Database Migration

### 2.1 Workflow Service → DB

#### New File: `backend/app/services/workflow_service.py`

Move all business logic from `routes/workflows.py`. The route file keeps only HTTP-layer thin wrappers.

#### New File: `backend/app/models/workflow.py`

```python
class Workflow(SQLModel, table=True):
    __tablename__ = "workflows"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    name: str
    description: str = Field(default="", sa_column=Column(SAText))
    definition: dict = Field(sa_column=Column(JSON))  # DAG nodes/edges
    trigger_type: str = Field(default="manual")  # manual|schedule|webhook|event|signal
    trigger_config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default="draft")  # draft|active|paused|archived
    created_by: UUID | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

class WorkflowRun(SQLModel, table=True):
    __tablename__ = "workflow_runs"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_id: UUID = Field(foreign_key="workflows.id", index=True)
    tenant_id: UUID = Field(index=True)
    status: str = Field(default="pending")  # pending|running|completed|failed|cancelled
    trigger_type: str = Field(default="manual")
    trigger_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    input_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    output_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: str | None = Field(default=None, sa_column=Column(SAText))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)

class WorkflowRunStep(SQLModel, table=True):
    __tablename__ = "workflow_run_steps"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(foreign_key="workflow_runs.id", index=True)
    step_id: str  # node ID from DAG definition
    name: str = Field(default="")
    status: str = Field(default="pending")
    model: str | None = Field(default=None)  # per-step model selection
    input_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    output_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: str | None = Field(default=None, sa_column=Column(SAText))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)

class WorkflowSchedule(SQLModel, table=True):
    __tablename__ = "workflow_schedules"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    workflow_id: UUID = Field(foreign_key="workflows.id", index=True)
    tenant_id: UUID = Field(index=True)
    cron_expression: str
    timezone: str = Field(default="UTC")
    enabled: bool = Field(default=True)
    last_run_at: datetime | None = Field(default=None)
    next_run_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
```

#### New Endpoints (add to `routes/workflows.py`)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/workflows/{id}/webhook` | Webhook trigger (auth via `X-API-Key`) |
| `POST` | `/workflows/events` | Event trigger (matches type/source to workflow trigger rules) |
| `POST` | `/workflows/{id}/runs/{run_id}/signal` | Signal a running workflow |
| `GET` | `/workflows/{id}/runs/{run_id}/query/{query_name}` | Query running workflow state |

#### Background Scheduler
- **Package:** `apscheduler>=3.10` (add to `backend/requirements.txt`)
- **Pattern:** AsyncIOScheduler started in `app.on_event("startup")` in `main.py`
- **At startup:** Load all `WorkflowSchedule` rows with `enabled=True` and schedule them
- **On schedule change:** Re-read DB; APScheduler jobs replaced by `workflow_id` as job ID
- **On schedule fire:** Call `workflow_service.execute_workflow(workflow_id, trigger_type="schedule")`

---

### 2.2 API Keys → DB

**File to modify:** `backend/app/routes/settings.py`  
Remove `_api_keys_store` dict. Wire to `SettingsAPIKey` table.

**Migration:** Add `rate_limit` column to `SettingsAPIKey`:

```python
# Add to models/settings.py SettingsAPIKey class
rate_limit: int | None = Field(default=None)  # RPM per key; None = tenant default
```

**Route changes in `routes/settings.py`:**
- `GET /settings/api-keys` → query `SettingsAPIKey` where `tenant_id=user.tenant_id AND revoked=False`
- `POST /settings/api-keys` → INSERT `SettingsAPIKey`, return plain key once (never again)
- `DELETE /settings/api-keys/{id}` → set `revoked=True`, `revoked_at=now()`
- `GET /settings/api-keys/{id}` → return metadata (never key value)

---

### 2.3 RBAC Custom Roles → DB

#### New File: `backend/app/models/rbac.py`

```python
class CustomRole(SQLModel, table=True):
    __tablename__ = "custom_roles"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    name: str = Field(index=True)
    permissions: list[dict] = Field(
        sa_column=Column(JSON)
    )  # [{"resource": "agents", "actions": ["read", "create"]}]
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

class GroupRoleMapping(SQLModel, table=True):
    """Maps Entra ID group OIDs to Archon roles (built-in or custom)."""
    __tablename__ = "group_role_mappings"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    group_oid: str = Field(index=True)   # Entra ID group object ID
    role_name: str                        # built-in role OR custom role name
    created_at: datetime = Field(default_factory=_utcnow)
```

**Modify `middleware/rbac.py`:**
- `check_permission()` remains sync for fast-path built-in roles
- Add `async def check_permission_db(user, resource, action, session)` that also loads `CustomRole` rows for the tenant and checks them
- `require_permission` dependency upgrades to use DB session when custom roles may apply

**Keep 4 hardcoded roles** in `_ROLE_ACTIONS` as immutable system defaults; `CustomRole` rows supplement them.

---

### 2.4 SCIM → DB

**File:** `backend/app/services/scim_service.py`
**File:** `backend/app/models/scim.py` — currently Pydantic-only; add SQLModel tables

#### New SQLModel Tables (add to `models/scim.py`):

```python
class SCIMUserRecord(SQLModel, table=True):
    __tablename__ = "scim_users"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    scim_id: str = Field(index=True)        # SCIM external ID
    external_id: str = Field(default="")
    user_name: str = Field(index=True)
    display_name: str = Field(default="")
    given_name: str = Field(default="")
    family_name: str = Field(default="")
    email: str = Field(default="")
    active: bool = Field(default=True)
    groups: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    raw_data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

class SCIMGroupRecord(SQLModel, table=True):
    __tablename__ = "scim_groups"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(index=True)
    scim_id: str = Field(index=True)
    external_id: str = Field(default="")
    display_name: str
    member_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    archon_role: str | None = Field(default=None)  # mapped Archon role
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
```

Remove `self._users` and `self._groups` dicts from `SCIMService.__init__`. All CRUD now uses `async_session_factory`.

---

### 2.5 Secrets Registration → DB

**File:** `backend/app/routes/secrets.py`

- `SecretRegistration` table already exists (`models/secrets.py`) — use it
- Replace any `_registrations` dict with DB INSERT/SELECT
- On Vault unavailable: return metadata from `SecretRegistration` rows; add `vault_status: "unavailable"` to response envelope; never raise 500

---

### 2.6 Secret Access Logger → DB

**File:** `backend/app/services/secret_access_logger.py`

Current: `self._entries: list[dict]`  
Fix: Replace `log_access()` body to INSERT a `SecretAccessLog` row:

```python
async def log_access_db(self, *, session: AsyncSession, **kwargs) -> None:
    """Persist access log entry to DB."""
    entry = SecretAccessLog(
        tenant_id=UUID(kwargs["tenant_id"]),
        secret_path=kwargs["secret_path"],
        user_id=UUID(kwargs["user_id"]) if kwargs.get("user_id") else None,
        user_email=kwargs.get("user_email", ""),
        action=kwargs["action"],
        component=kwargs.get("component", ""),
        ip_address=kwargs.get("ip_address"),
        details=kwargs.get("details"),
    )
    session.add(entry)
    await session.commit()
```

Keep sync `log_access()` for backward compatibility (logs to structlog only); add the async DB variant for all new call sites.

Export `SecretAccessLog` from `models/secrets.py` `__all__` (currently missing).

---

### 2.7 Lifecycle → DB (Top 3 Dicts)

**File:** `backend/app/services/lifecycle_service.py`

Wire these 3 in-memory dicts to existing tables:

| Dict | DB Table | Key Operation |
|---|---|---|
| `_deployments` | `DeploymentRecord` | SELECT/INSERT/UPDATE by `agent_id` + `environment` |
| `_agent_states` | `DeploymentRecord.status` | UPDATE `status` on state change |
| `_deployment_history` | `LifecycleEvent` | INSERT on every state transition |

Remaining 5 dicts (`_scheduled_jobs`, `_metrics_store`, `_approval_gates`, `_environments`, `_health_metrics`) remain in-memory — acceptable ephemeral state.

---

### WS-2 Dependencies
```
apscheduler>=3.10   # backend/requirements.txt
```

### WS-2 Risk Areas
- `create_db_and_tables()` currently does `drop_all` then `create_all` — **catastrophic in production**. Before adding any new tables, change startup to use `create_all` without `drop_all` (migration-safe). Add a note in code.
- APScheduler startup races with DB being available — wrap in retry loop.
- `async_session_factory` is a `sessionmaker` callable; call it as `async_session_factory()` as a context manager (already done in `main.py:on_startup`).

---

## WS-3: Frontend Fixes & Theme System

### 3.1 ThemeProvider

**New file:** `frontend/src/contexts/ThemeContext.tsx`

```typescript
type Theme = "dark" | "light";
interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
}
```

- On mount: read `localStorage.getItem("theme")` or `prefers-color-scheme`
- Toggle: flip `document.documentElement.classList` between `dark` (tailwind class strategy)
- Persist to `localStorage`

**Modify:** `frontend/src/main.tsx` — wrap `<App />` in `<ThemeProvider>`

**Modify:** `frontend/src/components/navigation/TopBar.tsx` — add `<ThemeToggle />` button using `useTheme()` hook

---

### 3.2 Bulk Color Replacement

Exact sed commands (run from `frontend/src/`):

```bash
find . -name "*.tsx" -o -name "*.ts" | xargs sed -i '' \
  -e 's/bg-\[#0f1117\]/bg-background/g' \
  -e 's/bg-\[#1a1d27\]/bg-card/g' \
  -e 's/bg-\[#2a2d37\]/bg-muted/g' \
  -e 's/border-\[#2a2d37\]/border-border/g' \
  -e 's/\btext-white\b/text-foreground/g' \
  -e 's/text-gray-400/text-muted-foreground/g'
```

**Pre-condition:** CSS variables must be defined before running sed.

**Modify:** `frontend/src/index.css` — add light mode `:root` block:

```css
:root {
  --background: 0 0% 100%;
  --foreground: 222.2 84% 4.9%;
  --card: 0 0% 100%;
  --card-foreground: 222.2 84% 4.9%;
  --muted: 210 40% 96.1%;
  --muted-foreground: 215.4 16.3% 46.9%;
  --border: 214.3 31.8% 91.4%;
}
.dark {
  --background: 222 47% 7%;      /* was #0f1117 */
  --foreground: 210 40% 98%;
  --card: 225 37% 13%;           /* was #1a1d27 */
  --muted: 223 27% 20%;          /* was #2a2d37 */
  --muted-foreground: 215 20.2% 65.1%;
  --border: 223 27% 20%;         /* was #2a2d37 */
}
```

**Verify `tailwind.config.ts`** already maps `background`, `card`, `muted`, `border` to `hsl(var(--...))` — confirmed from exploration findings.

---

### 3.3 Frontend API URL Fixes

**File:** `frontend/src/api/governance.ts` L221  
Already calls `/audit-logs/` — **no change needed** after WS-1 changes backend prefix to `/audit-logs`.

**File:** Sentinel API client — remove stale TODO comments claiming `scan_router` not registered.

---

### 3.4 Vitest Setup

**Modify:** `frontend/package.json`
```json
"devDependencies": {
  "vitest": "^2.0.0",
  "@testing-library/react": "^16.0.0",
  "@testing-library/jest-dom": "^6.0.0",
  "jsdom": "^25.0.0"
},
"scripts": {
  "test": "vitest run",
  "test:watch": "vitest"
}
```

**New file:** `frontend/vitest.config.ts`
```typescript
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
```

**New file:** `frontend/src/test/setup.ts`
```typescript
import '@testing-library/jest-dom'
```

### 3.5 Baseline Tests

| Test File | Component | Assertion |
|---|---|---|
| `src/test/Dashboard.test.tsx` | `DashboardPage` | renders without crash |
| `src/test/AgentBuilder.test.tsx` | `AgentBuilderCanvas` | renders React Flow wrapper |
| `src/test/Login.test.tsx` | `LoginPage` | renders form with username/password inputs |
| `src/test/Sidebar.test.tsx` | `Sidebar` | renders all nav links |
| `src/test/ThemeToggle.test.tsx` | `ThemeToggle` | clicking toggles `dark` class on `document.documentElement` |
| `src/test/AuditLog.test.tsx` | `AuditLogPage` | renders table, no crash |

### WS-3 Risk Areas
- `text-white` → `text-foreground` bulk replace may affect icon colors or intentional overrides. Review any failures in `npm run build` after replacement.
- React Flow canvas uses internal styles — avoid replacing colors inside `node_modules` or inline styles generated by `@xyflow/react`.

---

## WS-4: Auth, Rate Limiting, Group Management

### 4.1 OIDC / Entra ID Auth

**Add to `backend/app/config.py`:**
```python
OIDC_DISCOVERY_URL: str = ""
OIDC_CLIENT_ID: str = ""
OIDC_CLIENT_SECRET: str = ""
OIDC_TENANT_ID: str = ""
```

**Modify `backend/app/middleware/auth.py`:**

Add a third validation tier after RS256 Keycloak:
1. If `AUTH_DEV_MODE=True` → HS256 (existing)
2. Else if token issuer matches Keycloak URL → RS256 Keycloak (existing)
3. Else if token issuer matches Entra ID → RS256 Entra ID (new)

For Entra ID validation:
- Fetch JWKS from `{OIDC_DISCOVERY_URL}` → parse `jwks_uri`
- Cache JWKS in module-level dict with 1-hour TTL
- Decode JWT, validate `aud=OIDC_CLIENT_ID`, `iss=https://login.microsoftonline.com/{tenant}/v2.0`
- Extract: `oid` (user ID), `preferred_username` (email), `groups` (list of group OIDs)
- Map `groups` OIDs → Archon roles via `GroupRoleMapping` table

**New dependency:** `PyJWT>=2.8` (likely already present), `httpx` (already present for other uses)

**TOTP:**
- New endpoints in `routes/auth_routes.py`:
  - `POST /api/v1/auth/totp/setup` → generate secret, return otpauth URI + QR PNG
  - `POST /api/v1/auth/totp/verify` → validate 6-digit code
- Store TOTP secrets in `Vault` path `totp/users/{user_id}` or DB column (encrypted) if Vault down
- **New package:** `pyotp>=2.9`

---

### 4.2 Rate Limiting Middleware

**New file:** `backend/app/middleware/rate_limit.py`

```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding window rate limiter backed by Redis INCR+EXPIRE."""

    async def dispatch(self, request: Request, call_next):
        tenant_id = getattr(request.state, "tenant_id", "global")
        api_key = request.headers.get("X-API-Key")

        # Per-API-key limit (from SettingsAPIKey.rate_limit)
        if api_key:
            limit = await self._get_key_limit(api_key)
            bucket = f"rate:key:{api_key}"
        else:
            # Per-tenant global limit
            limit = settings.RATE_LIMIT_RPM
            bucket = f"rate:tenant:{tenant_id}"

        count = await redis.incr(bucket)
        if count == 1:
            await redis.expire(bucket, 60)  # 1-minute window

        if count > limit:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "60"},
                content={"errors": [{"code": "RATE_LIMIT_EXCEEDED"}]},
            )
        return await call_next(request)
```

**Add to `config.py`:**
```python
RATE_LIMIT_RPM: int = 1000
REDIS_URL: str = "redis://localhost:6379/0"  # already exists
```

**Register in `main.py`** after `AuditMiddleware`:
```python
from app.middleware.rate_limit import RateLimitMiddleware
application.add_middleware(RateLimitMiddleware)
```

---

### 4.3 Group Management Endpoints

Add to `backend/app/routes/admin.py` (already registered):

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/admin/users/{user_id}/groups` | Assign user to groups |
| `GET` | `/admin/users/{user_id}/groups` | List user's groups |
| `POST` | `/admin/groups/{group_id}/roles` | Map group to RBAC role |
| `GET` | `/admin/groups` | List all groups |
| `POST` | `/admin/invitations` | Invite user with role or group |

Uses `GroupRoleMapping` table from WS-2.

---

### 4.4 Audit Trail PII Scrubbing

**Modify:** `backend/app/middleware/audit_middleware.py`

Add scrubbing utility:
```python
import re

_API_KEY_RE = re.compile(r'(ak_[a-z]+_)[A-Za-z0-9]+')
_BEARER_RE = re.compile(r'(Bearer )[A-Za-z0-9\-._~+/]+=*')
_EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')

def scrub(value: str) -> str:
    value = _API_KEY_RE.sub(r'\1***', value)
    value = _BEARER_RE.sub(r'\1***', value)
    value = _EMAIL_RE.sub('***@***.***', value)
    return value
```

Apply to: path, query string, `Authorization` header before writing audit record.

---

### 4.5 Azure Sentinel Log Shipping

**New file:** `backend/app/services/sentinel_shipper.py`

```python
class SentinelShipper:
    """Ships security events to Azure Log Analytics via HTTP Data Collector API."""
    
    ENDPOINT = "https://{workspace_id}.ods.opinsights.azure.com/api/logs?api-version=2016-04-01"
    
    async def ship(self, events: list[dict]) -> None:
        # HMAC-SHA256 signature per Azure docs
        # POST to Log Analytics endpoint
        # Fields: TimeGenerated, SourceIP, UserID, Action, Resource, Outcome, Details
        ...
```

Add to `config.py`:
```python
SENTINEL_WORKSPACE_ID: str = ""
SENTINEL_SHARED_KEY: str = ""
```

Structured log processor emits `sentinel_event=True` for: auth failures, RBAC denials, 429 hits, DLP blocks.

### WS-4 Dependencies
```
pyotp>=2.9          # backend/requirements.txt
apscheduler>=3.10   # (shared with WS-2)
```

### WS-4 Risk Areas
- Redis connection in `RateLimitMiddleware` must be a singleton (don't create new pool per request). Use module-level `aioredis` client initialized at startup.
- TOTP secrets must never appear in logs — use scrubbing from audit middleware.

---

## WS-5: Model Router Enhancement

### 5.1 Azure OpenAI Registration

**File:** `backend/app/services/router_service.py`

Do NOT hardcode API key. At startup, read from:
1. `ARCHON_AZURE_OPENAI_API_KEY` env var
2. Vault path `azure/openai/api-key`

Register two model entries:
```python
ModelRegistryEntry(
    id="gpt-5.2-codex",
    provider="azure_openai",
    deployment_id="gpt-5.2-codex",
    endpoint="https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/responses",
    api_version="2025-04-01-preview",
    capabilities=["chat", "code"],
    cost_per_1k_input=0.003,
    cost_per_1k_output=0.006,
)
ModelRegistryEntry(
    id="qrg-embedding-experimental",
    provider="azure_openai",
    deployment_id="qrg-embedding-experimental",
    endpoint="https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com/openai/deployments/qrg-embedding-experimental/embeddings",
    api_version="2023-05-15",
    capabilities=["embeddings"],
)
```

### 5.2 429 Retry with Backoff

**Modify:** `router_service.py` model call execution path

```python
RETRY_DELAYS = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]  # max 30s

async def _call_with_retry(self, model_entry, request):
    for attempt, delay in enumerate(RETRY_DELAYS):
        resp = await self._http_client.post(...)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", delay))
            wait = min(retry_after, delay * (1 + random.random() * 0.1))  # jitter
            if attempt < len(RETRY_DELAYS) - 1:
                await asyncio.sleep(wait)
                continue
            # Exhaust retries — try fallback model
            return await self._try_fallback(request)
        return resp
```

### 5.3 Embeddings Endpoint

**New endpoint in `routes/router.py`:**

```
POST /api/v1/router/embeddings
Body: {"text": "...", "model": "qrg-embedding-experimental"}
Response: {"embedding": [...], "model": "...", "usage": {...}}
```

### 5.4 Per-Step Model in Workflows

**Modify:** `models/workflow.py` — `WorkflowRunStep` already has `model: str | None`

**Modify:** `services/workflow_engine.py` — when executing a step, pass `step.model` to `router_service.route()`. If `None`, use tenant default model from router policy.

### WS-5 Risk Areas
- `_circuit_breaker` singleton in `router_service.py` is acceptable as ephemeral state — do NOT migrate to DB.
- Avoid breaking existing router tests by keeping the existing `route()` signature; add `model_preference` as optional kwarg.

---

## WS-6: MCP Host Gateway

### Directory Structure (verbatim from SWARM_PLAN.md)
```
gateway/
  app/
    main.py          config.py        logging_config.py
    auth/            middleware.py    models.py
    guardrails/      middleware.py
    plugins/         loader.py        models.py
    routes/          capabilities.py  invoke.py    health.py
    tools/           builtin_ai.py    forwarder.py dispatch.py  container.py
    workflows/       qa_trigger.py
    improvement/     engine.py
  plugins/
    _example.yaml
    finance-revenue-mcp.yaml
  tests/             (8 test files)
  requirements.txt   Dockerfile       pyproject.toml
```

### Plugin Schema (`plugins/models.py`)

```python
class PluginTool(BaseModel):
    id: str
    input_schema: dict
    model: str = "gpt-5.2-codex"
    can_forward: bool = False

class PluginContainer(BaseModel):
    image: str
    port: int = 8080
    idle_timeout: int = 300
    resources: dict = Field(default_factory=lambda: {"cpu": "0.5", "memory": "512Mi"})

class Plugin(BaseModel):
    name: str
    type: Literal["builtin", "forward", "container"] = "builtin"
    backend_url: str = ""
    container: PluginContainer | None = None
    required_groups: list[str] = Field(default_factory=list)
    tools: list[PluginTool] = Field(default_factory=list)
```

### Auth Middleware (`auth/middleware.py`)
- Validates Entra ID JWT (RS256, JWKS from discovery)
- Dev bypass: `MCP_GATEWAY_DEV_MODE=true` → accept any token, inject mock identity
- Extracts `oid`, `groups`, `preferred_username`
- Injects `request.state.user = MCPUser(...)`

### Guardrails Middleware (`guardrails/middleware.py`)
- Rate limit: Redis-backed per-user (100 req/60s per APIM spec)
- Input validation: max payload size, content type check
- Destructive op check: flag `DELETE`-equivalent tool calls for audit
- Timeout: 30s default, configurable per plugin
- Audit: every invocation logged with `TimeGenerated`, `UserID`, `tool_id`, `outcome`

### Container Management (`tools/container.py`)

ToolHive-inspired container lifecycle:
```
invoke request
  → check running containers map
  → if not running: docker pull + create + start + health check
  → proxy request to container:port via httpx
  → reset idle timer
  → idle timeout: docker stop + remove
```

Uses Docker SDK (`docker>=7.0`). Container map: `dict[plugin_name, ContainerInfo]` (in-memory, ephemeral).

### Hot-Reload Plugin Loader (`plugins/loader.py`)
- On startup: load all `plugins/*.yaml` files
- `watchfiles.awatch()` background task monitors directory
- On change: re-validate with Pydantic, reload plugin registry
- Invalid YAML: log error, keep old version

### Routes

`GET /mcp/capabilities`:
- Filter `Plugin` list: `any(g in user.groups for g in plugin.required_groups)`
- Return filtered tool list without `backend_url` or container details

`POST /mcp/tools/{tool_id}/invoke`:
1. Lookup tool → plugin
2. Check user group membership
3. GuardrailsMiddleware pre-checks
4. Dispatch: `can_forward? → forwarder.forward() : builtin_ai.execute()`
5. If `type=container`: `container.invoke()`
6. Optionally trigger `qa_trigger.post_to_logic_apps(result)`
7. Return result

### Gateway `config.py`
```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_GATEWAY_")
    
    DEV_MODE: bool = True
    ENTRA_TENANT_ID: str = "ff3213cc-c3f6-45d4-a104-8f7823656fec"
    ENTRA_CLIENT_ID: str = "8adab7b8-a4bc-497b-90b9-53fd89de5900"
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_MODEL: str = "gpt-5.2-codex"
    REDIS_URL: str = "redis://localhost:6379/1"
    LOGIC_APPS_TRIGGER_URL: str = ""
    PLUGINS_DIR: str = "plugins"
    RATE_LIMIT_RPM: int = 100
```

### Gateway `requirements.txt`
```
fastapi>=0.115
uvicorn[standard]
pydantic-settings
httpx
msal>=1.28
openai>=1.30      # Azure OpenAI SDK
watchfiles
docker>=7.0
redis[asyncio]
structlog
pyotp
PyJWT>=2.8
pytest
pytest-asyncio
httpx[pytest]
```

### Gateway `Dockerfile`
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

### WS-6 Risk Areas
- Docker-in-Docker: container.py needs Docker socket mounted in gateway container. Add `volumes: ["/var/run/docker.sock:/var/run/docker.sock"]` to gateway service in `docker-compose.yml`.
- Plugin hot-reload: `watchfiles.awatch` is async; must run as background task, not blocking the request loop.
- `finance-revenue-mcp.yaml` references an image that may not exist — use `_example.yaml` with a placeholder image for tests.

---

## WS-7: Docker Integration Testing

### `docker-compose.test.yml`

Extends `docker-compose.yml`, overrides services:
```yaml
services:
  postgres:
    environment:
      POSTGRES_DB: archon_test
  backend:
    environment:
      AUTH_DEV_MODE: "true"
      ARCHON_DATABASE_URL: "postgresql+asyncpg://archon:archon@postgres:5432/archon_test"
      ARCHON_AZURE_OPENAI_API_KEY: "${AZURE_OPENAI_API_KEY}"
      ARCHON_AZURE_OPENAI_ENDPOINT: "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
  # Exclude: vault, keycloak, prometheus, grafana
```

### Test Files (`tests/integration/`)

15 test files as specified in SWARM_PLAN.md §WS-7. All use `httpx` against `http://localhost:8000`.

Key fixture pattern:
```python
@pytest.fixture(scope="session")
def auth_headers():
    """Get dev-mode JWT for test requests."""
    resp = httpx.post("http://localhost:8000/api/v1/auth/login",
                      json={"email": "system@archon.local", "password": "dev"})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

### Playwright Config (`frontend/playwright.config.ts`)

```typescript
export default defineConfig({
  testDir: './tests/e2e',
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
  },
  webServer: {
    command: 'npm run preview',
    url: 'http://localhost:3000',
    reuseExistingServer: true,
  },
})
```

### `scripts/run_integration_tests.sh`

As specified in SWARM_PLAN.md §WS-7. Sequence:
1. `docker compose -f docker-compose.test.yml up -d --build --wait`
2. Health poll loop (120s timeout)
3. `pytest tests/integration/ -v`
4. `npx playwright test`
5. `docker compose -f docker-compose.test.yml down -v`
6. Write `docs/INTEGRATION_TEST_REPORT.md`

### WS-7 Risk Areas
- `create_db_and_tables()` drops all tables on startup — test DB will be recreated fresh each run. This is acceptable for integration tests but MUST be changed before production deployment.
- Azure OpenAI key must be available as env var in CI secrets.

---

## WS-8: Cross-Cutting

### 8.1 SMTP via `aiosmtplib`

**File:** `backend/app/routes/settings.py` — `send_test_notification` endpoint

```python
import aiosmtplib
from email.mime.text import MIMEText

async def _send_email(smtp_config: dict, to: str, subject: str, body: str) -> None:
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_config["smtp_from"]
    msg["To"] = to
    async with aiosmtplib.SMTP(
        hostname=smtp_config["smtp_host"],
        port=smtp_config["smtp_port"],
        username=smtp_config.get("smtp_username"),
        password=smtp_config.get("smtp_password"),
        use_tls=smtp_config.get("smtp_port") == 465,
        start_tls=smtp_config.get("smtp_port") == 587,
    ) as smtp:
        await smtp.send_message(msg)
```

**New package:** `aiosmtplib>=3.0`

---

### 8.2 Teams Webhook Integration

**File:** `backend/app/routes/settings.py`

Teams incoming webhook — simplest approach (no Graph API needed):
```python
async def _send_teams(webhook_url: str, title: str, text: str) -> None:
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": "8b5cf6",
        "summary": title,
        "sections": [{"activityTitle": title, "activityText": text}],
    }
    async with httpx.AsyncClient() as client:
        await client.post(webhook_url, json=payload, timeout=10)
```

Add `teams_webhook_url` to `notifications` settings section.

---

### 8.3 Multi-Tenancy Review

**File:** `backend/app/middleware/tenant_middleware.py`

Verify every service query uses `where(Model.tenant_id == tenant_id)`. Create a checklist in `docs/TENANCY_AUDIT.md`.

---

### 8.4 CI/CD Updates

**File:** `.github/workflows/ci.yml`

Add job after existing backend test:
```yaml
gateway-test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: {python-version: "3.12"}
    - run: cd gateway && pip install -r requirements.txt
    - run: cd gateway && python -m pytest tests/ -v
```

**File:** `.github/workflows/cd.yml`

Add step to build and push gateway image:
```yaml
- name: Build gateway image
  run: docker build -t ghcr.io/${{ github.repository }}/archon-gateway:${{ github.sha }} gateway/
```

---

### 8.5 OpenAPI Verification

After all route fixes, run:
```bash
PYTHONPATH=backend python3 -c "
from app.main import create_app
import json
app = create_app()
print(json.dumps(app.openapi(), indent=2))
" > contracts/openapi.generated.json
diff contracts/openapi.yaml contracts/openapi.generated.json
```

Document all route additions/changes in `docs/API_CHANGES.md`.

### WS-8 Dependencies
```
aiosmtplib>=3.0    # backend/requirements.txt
```

---

## Summary: All New/Modified Files

### New Files (backend)
| File | Purpose |
|---|---|
| `backend/app/models/workflow.py` | Workflow, WorkflowRun, WorkflowRunStep, WorkflowSchedule tables |
| `backend/app/models/rbac.py` | CustomRole, GroupRoleMapping tables |
| `backend/app/services/workflow_service.py` | Workflow business logic (moved from routes) |
| `backend/app/middleware/rate_limit.py` | Redis-backed rate limiting |
| `backend/app/services/sentinel_shipper.py` | Azure Sentinel log shipping |

### Modified Files (backend)
| File | Change |
|---|---|
| `backend/app/main.py` | Add enterprise_router import+registration; add RateLimitMiddleware; APScheduler startup |
| `backend/app/routes/marketplace.py` | Strip 8 route decorator prefixes |
| `backend/app/routes/sentinelscan.py` | Rename duplicate `/posture` in scan_router |
| `backend/app/routes/audit_logs.py` | Change prefix from `/audit/logs` to `/audit-logs` |
| `backend/app/routes/workflows.py` | Add 4 new trigger endpoints; remove in-memory dicts |
| `backend/app/routes/settings.py` | Remove `_api_keys_store`; wire to `SettingsAPIKey`; add SMTP + Teams |
| `backend/app/models/settings.py` | Add `rate_limit` column to `SettingsAPIKey` |
| `backend/app/models/scim.py` | Add `SCIMUserRecord`, `SCIMGroupRecord` SQLModel tables |
| `backend/app/models/secrets.py` | Export `SecretAccessLog` in `__all__` |
| `backend/app/middleware/rbac.py` | Add DB-backed custom role check |
| `backend/app/middleware/auth.py` | Add Entra ID OIDC tier; TOTP endpoints |
| `backend/app/middleware/audit_middleware.py` | Add PII/secret scrubbing |
| `backend/app/services/scim_service.py` | Replace in-memory dicts with DB |
| `backend/app/services/secret_access_logger.py` | Add async DB variant of `log_access` |
| `backend/app/services/lifecycle_service.py` | Wire top-3 dicts to existing DB tables |
| `backend/app/config.py` | Add OIDC fields, RATE_LIMIT_RPM, SENTINEL fields, AZURE_OPENAI fields |
| `backend/app/database.py` | Change `create_db_and_tables` to not `drop_all` |
| `backend/requirements.txt` | Add: apscheduler, pyotp, aiosmtplib |
| `scripts/smoke_test.sh` | Fix double-prefix DLP path at L50 |

### New Files (frontend)
| File | Purpose |
|---|---|
| `frontend/src/contexts/ThemeContext.tsx` | ThemeProvider + useTheme hook |
| `frontend/src/test/setup.ts` | Vitest setup |
| `frontend/src/test/*.test.tsx` | 6 baseline component tests |
| `frontend/vitest.config.ts` | Vitest configuration |
| `frontend/tests/e2e/*.spec.ts` | 12 Playwright E2E tests |
| `frontend/playwright.config.ts` | Playwright configuration |

### Modified Files (frontend)
| File | Change |
|---|---|
| `frontend/src/index.css` | Add `:root` (light) and `.dark` (dark) CSS variable blocks |
| `frontend/src/main.tsx` | Wrap in ThemeProvider |
| `frontend/src/components/navigation/TopBar.tsx` | Add ThemeToggle button |
| `frontend/src/api/governance.ts` | No change needed (already correct URL) |
| `frontend/package.json` | Add vitest + testing-library deps; fix test script |
| `frontend/src/**/*.tsx` (bulk) | Replace hardcoded color values |

### New Files (gateway)
All files under `gateway/` as specified in §WS-6 directory structure.

### New Files (infra/testing)
| File | Purpose |
|---|---|
| `docker-compose.test.yml` | Minimal test stack |
| `scripts/run_integration_tests.sh` | Integration test runner |
| `tests/integration/*.py` | 15 backend integration tests |
| `docs/HEALTH_REPORT.md` | WS-0 output |
| `docs/INTEGRATION_TEST_REPORT.md` | WS-7 output |
| `docs/TENANCY_AUDIT.md` | WS-8 tenancy review |
| `docs/API_CHANGES.md` | Route change log |
| `docs/ARCHITECTURE.md` | MCP Host Gateway section |

---

## Execution Order (Confirmed)

```
Phase 1 — BLOCKING
  WS-0: Health Assessment → docs/HEALTH_REPORT.md

Phase 2 — PARALLEL (no inter-dependencies)
  WS-1: Route fixes (marketplace, sentinel, audit, smoke test)
  WS-2: DB migration (workflows, API keys, RBAC, SCIM, secrets, lifecycle)
  WS-6: MCP Host Gateway (all new code, independent)
  WS-8: CI/CD, SMTP, Teams, docs

Phase 3 — PARALLEL (depend on Phase 2)
  WS-3: Frontend theme + API URLs (needs WS-1 audit-logs fix)
  WS-4: Auth + rate limiting (needs WS-2 RBAC/API keys)
  WS-5: Model router (needs WS-2 workflow DB)

Phase 4 — SEQUENTIAL (depends on all above)
  WS-7: Docker integration testing
```

---

## Global Constraints (Carried Forward)

1. `create_db_and_tables()` — change to `create_all` only (no `drop_all`) before any new table additions
2. Never hardcode `b664331212b54911969792845dee8ba9` — always `ARCHON_AZURE_OPENAI_API_KEY` env var
3. Gateway is `gateway/` — completely separate FastAPI app; do NOT import from `backend/`
4. All new routes must appear in `/openapi.json`
5. Every workstream outputs a report document in `docs/`
