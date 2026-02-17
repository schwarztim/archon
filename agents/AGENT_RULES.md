# OpenAiria — Agent Rules (Enterprise Edition)

> Every sub-agent reads this file. It replaces INSTRUCTIONS.md + BUILD_CORRECTNESS.md + SELF_VERIFICATION_CHECKLIST.md.
> Updated for Stage 2: Enterprise Hardening.

## Output Requirements (every task)
1. Working code in the correct directory
2. Tests (pytest for backend, Playwright for frontend)
3. Brief summary of files created/modified

## Code Standards
- Python 3.12, type hints on all functions, docstrings on public functions
- FastAPI routers use dependency injection for auth, DB sessions, secrets
- All responses use the envelope format: `{"data": ..., "meta": {"request_id", "timestamp", "pagination"}}`
- All errors use: `{"errors": [{"code", "message", "field?", "details?"}], "meta": {...}}`
- SQLModel for ORM, Alembic for migrations
- Pydantic-settings with `OPENAIRIA_` env prefix for all config
- Structured JSON logging with correlation IDs (request_id, tenant_id, user_id, trace_id)
- Absolute imports only, no circular dependencies

## API Rules
- All endpoints behind JWT auth (except /health, /docs, /.well-known, /scim/v2/ServiceProviderConfig)
- All lists paginated (limit/offset, max 100)
- All endpoints return correct HTTP status codes (201 for create, 204 for delete, etc.)
- API versioned at /api/v1/
- Match contracts/openapi.yaml exactly — no invented endpoints

## Enterprise Security Rules (MANDATORY — Stage 2)

### Secrets Management
- **ALL credentials via SecretsManager**: `from backend.app.secrets.manager import SecretsManager`
- No hardcoded secrets, no env var secrets, no config file secrets
- API keys, OAuth tokens, DB passwords, encryption keys — ALL from Vault
- Sensitive data encrypted at rest via Vault Transit engine
- Secret values NEVER appear in logs, traces, error messages, or API responses
- Credential rotation: support webhook notification when secrets rotate

### Authentication & Authorization
- **Every endpoint authenticated**: Use `Depends(get_current_user)` FastAPI dependency
- **RBAC check on every mutation**: Use `check_permission(user, action, resource)` before any state change
- **Tenant context on every request**: `request.state.tenant_id` set by middleware, used in all queries
- **RLS enforced**: All database queries scoped to `tenant_id` (via RLS policy or explicit filter)
- **Audit trail**: Every create/update/delete/execute/approve logs to `AuditLog` with actor, action, resource, result

### Patterns
```python
# CORRECT: Endpoint with auth, RBAC, tenant isolation, secrets, audit
@router.post("/api/v1/agents", status_code=201)
async def create_agent(
    body: AgentCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    secrets: SecretsManager = Depends(get_secrets_manager),
):
    check_permission(user, "agents:create", scope="workspace")
    agent = Agent(**body.dict(), tenant_id=user.tenant_id, owner_id=user.id)
    db.add(agent)
    await db.commit()
    await audit_log(user, "agent.created", "agent", str(agent.id), {"name": agent.name})
    return {"data": AgentResponse.from_orm(agent), "meta": {"request_id": get_request_id()}}

# WRONG: Missing auth, no RBAC, no tenant isolation, no audit
@router.post("/api/v1/agents")
async def create_agent(body: AgentCreate, db: AsyncSession = Depends(get_db)):
    agent = Agent(**body.dict())  # No tenant_id!
    db.add(agent)
    await db.commit()
    return agent  # No envelope, no audit
```

### Cross-Tenant Data Access Prevention
```python
# CORRECT: Query scoped to tenant
agents = await db.exec(
    select(Agent).where(Agent.tenant_id == user.tenant_id, Agent.deleted_at.is_(None))
)

# WRONG: No tenant filter — data leak
agents = await db.exec(select(Agent))
```

## Security Rules
- No hardcoded secrets anywhere
- Input validation on all user data (Pydantic models)
- Parameterized queries only (ORM handles this)
- Sensitive data never logged (use structlog processors to strip fields)
- CORS not wildcard in production
- CSRF protection on all state-changing endpoints
- Rate limiting on auth endpoints (5 attempts per minute)

## Testing Rules
- >= 80% coverage for new code
- Test edge cases: empty input, max length, invalid types, unauthorized, wrong tenant
- **Auth tests**: test every endpoint with each role (admin, developer, viewer, unauthenticated)
- **Tenant isolation tests**: verify tenant A cannot read/write tenant B's data
- **Secrets tests**: verify no plaintext secrets in responses, logs, or database
- Use fixtures and factories, not inline setup
- Integration tests must hit actual API endpoints
- All pre-existing tests must still pass after your changes

## Performance Rules
- No N+1 queries — use joinedload or selectinload
- All lists paginated (never unbounded)
- Async where appropriate
- < 200ms p95 for routing decisions
- < 5ms for JWT validation (JWKS cached)

## Frontend Rules (if applicable)
- React 19 + TypeScript strict mode
- shadcn/ui components + Tailwind
- Accessible (ARIA labels, keyboard nav)
- Dark/light mode support
- Loading + error states handled
- **Auth context**: All pages wrapped in AuthProvider
- **Permission gates**: Use `<PermissionGate>` or `usePermission()` for conditional rendering
- **No secrets in frontend**: Never display raw secret values. Masked display only.
- **Session handling**: Token in memory, refresh via httpOnly cookie, timeout warnings

## Before You're Done (Mandatory Verification)

### Step 1: Run Your Verify Command
Every task you receive includes a `VERIFY:` command. Run it. If it exits non-zero, fix and retry (max 3 attempts).

### Step 2: Self-Check
- [ ] Code matches the API contract
- [ ] Tests pass
- [ ] No TODO/FIXME left unresolved
- [ ] No console errors
- [ ] Imports are clean (no unused, no circular)
- [ ] Verify command exits 0
- [ ] **All credentials accessed via SecretsManager (not env vars or hardcoded)**
- [ ] **Every endpoint checks authentication and authorization**
- [ ] **Every query is scoped to tenant_id**
- [ ] **State-changing operations produce AuditLog entries**
- [ ] **No secret values in logs, responses, or error messages**

### Step 3: On Failure (after 3 attempts)
1. Revert uncommitted changes: `git checkout -- .`
2. Write `.sdd/failures/<task-id>.md` with: what was attempted, error output, suspected root cause
3. Stop — do NOT keep trying

## Learnings (Read Before Starting)
Before writing code, check `.sdd/learnings/*.md` for known pitfalls relevant to your task.
These are lessons from previous sessions — following them prevents repeat mistakes.
If you discover a new pitfall or useful pattern during your work, note it in your completion summary so the orchestrator can capture it.
