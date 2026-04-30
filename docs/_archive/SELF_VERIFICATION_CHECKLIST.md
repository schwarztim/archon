# Archon - Self-Verification Checklist

> **MANDATORY**: Every agent MUST complete this checklist with 100% YES before marking work as done.
> Any NO answer blocks the agent from completing. Fix the issue or escalate to the Orchestrator.

---

## Instructions

Copy this checklist into your PR description. Mark each item YES or NO.
If NO, explain why and what you need to fix it.

---

## API Contract Compliance

- [ ] I read `contracts/openapi.yaml` before writing any endpoint
- [ ] Every endpoint I created matches the contract exactly (status codes, request/response shapes, error formats)
- [ ] I ran `openapi-diff` and confirmed 0 deviations from the contract
- [ ] I did NOT invent any endpoint that is not in the contract
- [ ] All WebSocket events match `contracts/events.yaml`

## Architecture Decision Compliance

- [ ] I read ALL relevant `docs/ADR/*.md` files before starting
- [ ] My error handling follows `ADR-002` exactly
- [ ] My database models follow `ADR-003` naming conventions
- [ ] My logging follows `ADR-006` structured JSON format with correlation IDs
- [ ] My tests follow `ADR-007` patterns (fixtures, factories, naming)
- [ ] My environment config uses `ADR-009` pydantic-settings pattern with ARCHON_ prefix
- [ ] My imports follow `ADR-010` (absolute imports, no circular dependencies)

## Interface Compliance

- [ ] I implemented all required abstract base classes from `backend/app/interfaces/`
- [ ] I use shared Pydantic models from `backend/app/interfaces/models/` (not custom duplicates)
- [ ] My service classes match the interface signatures exactly

## Code Quality

- [ ] `make verify` passes with 0 errors
- [ ] Test coverage is >= 80% for all new code
- [ ] No hardcoded secrets, API keys, or credentials anywhere in the code
- [ ] No TODO or FIXME comments left unresolved
- [ ] All functions have type hints
- [ ] All public functions have docstrings

## Security

- [ ] Every API endpoint requires authentication (JWT validation)
- [ ] Authorization checks are present for resource access
- [ ] Input validation is present on all user-provided data
- [ ] No SQL injection vulnerabilities (using parameterized queries / ORM)
- [ ] No XSS vulnerabilities in frontend code
- [ ] Sensitive data is not logged
- [ ] CORS is configured correctly (not wildcard in production)

## API Design

- [ ] All list endpoints support pagination (limit/offset or cursor)
- [ ] All endpoints return consistent error format (ADR-002)
- [ ] All endpoints return appropriate HTTP status codes
- [ ] Rate limiting is configured for public-facing endpoints
- [ ] API versioning is correct (/api/v1/...)

## Testing

- [ ] Unit tests cover all business logic
- [ ] Integration tests cover all API endpoints
- [ ] Edge cases are tested (empty input, max length, invalid types, unauthorized)
- [ ] All pre-written integration test contracts in `tests/integration/` pass
- [ ] My changes do NOT break any existing tests (regression guardian passes)

## Documentation

- [ ] OpenAPI spec is updated if I added/changed endpoints
- [ ] README or relevant docs are updated
- [ ] All public APIs have usage examples
- [ ] Complex logic has inline comments explaining "why" (not "what")

## Frontend (if applicable)

- [ ] Components are accessible (ARIA labels, keyboard navigation)
- [ ] Responsive design works on mobile/tablet/desktop
- [ ] Dark mode and light mode both work
- [ ] Loading states and error states are handled
- [ ] No console errors or warnings in browser

## Performance

- [ ] Database queries are optimized (no N+1 queries, proper indexes)
- [ ] Large lists use pagination (never load unbounded data)
- [ ] Async operations are used where appropriate
- [ ] No blocking calls in the request path

---

## Sign-Off

```
Agent: [AGENT-XX]
Date: [YYYY-MM-DD]
All items: [YES / NO - with count of failures]
Blockers: [none / list]
```
