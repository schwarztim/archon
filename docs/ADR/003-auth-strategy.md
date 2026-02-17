# ADR-003: Authentication & Authorization Strategy

> **Status**: ACCEPTED
> **Date**: 2026-02-16
> **Decision**: Delegate all authentication to Keycloak 24 via OIDC/OAuth2. Use JWT Bearer tokens with RBAC. No custom auth implementation.

## Context

Archon is multi-tenant and exposes APIs consumed by frontends, CLI tools, and other services. Building custom authentication (password hashing, token issuance, session management, MFA) is complex and error-prone. The platform needs role-based access control, tenant isolation, and standard protocol support (OIDC, OAuth2) from day one.

## Decision

### Identity Provider: Keycloak 24

- Keycloak handles all authentication: login, registration, password reset, MFA, and social login.
- Archon never stores passwords or issues tokens — Keycloak is the sole token issuer.
- Each Archon tenant maps to a Keycloak realm, providing full isolation of users and roles.

### Token Format: JWT Bearer

- All API requests (except `/health` and `/docs`) require a valid JWT in the `Authorization: Bearer <token>` header.
- Tokens are validated by verifying the signature against Keycloak's JWKS endpoint. Keys are cached locally with a TTL.
- Claims used: `sub` (user ID), `realm_access.roles` (RBAC), `tenant_id` (custom claim for tenant isolation), `exp` (expiry).

### RBAC Roles

| Role        | Permissions                                              |
|-------------|----------------------------------------------------------|
| `admin`     | Full access: manage tenants, users, agents, and settings |
| `developer` | Create/edit/execute agents and workflows                 |
| `viewer`    | Read-only access to agents, workflows, and dashboards    |

Roles are assigned in Keycloak and embedded in the JWT `realm_access.roles` claim. No role data is stored in PostgreSQL.

### Tenant Isolation

- A custom `tenant_id` claim is added to JWTs via a Keycloak protocol mapper.
- Every database query is scoped by `tenant_id` extracted from the token. There is no cross-tenant data access.
- Middleware rejects tokens missing the `tenant_id` claim.

### FastAPI Integration

Auth is enforced via FastAPI dependency injection:

```python
async def get_current_user(token: str = Security(HTTPBearer())) -> TokenPayload:
    """Validate JWT, extract claims, enforce tenant scope."""
    return TokenPayload(**(await verify_jwt(token.credentials)))

def require_role(role: str):
    async def check(user: TokenPayload = Depends(get_current_user)):
        if role not in user.roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return check
```

### Configuration

```
ARCHON_KEYCLOAK_URL=https://auth.archon.dev
ARCHON_KEYCLOAK_REALM=archon
ARCHON_KEYCLOAK_CLIENT_ID=archon-api
```

## Consequences

- No custom auth code to maintain — Keycloak handles the entire identity lifecycle
- Standard OIDC/OAuth2 means any compliant client can integrate
- Tenant isolation is enforced at the middleware level, not just the application level
- RBAC is centralized in Keycloak; role changes take effect on next token refresh
- Adds Keycloak as an infrastructure dependency that must be highly available
- Token validation adds a small latency cost (mitigated by JWKS caching)
