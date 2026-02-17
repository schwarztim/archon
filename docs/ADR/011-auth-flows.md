# ADR-011: Authentication Flows

> **Status**: ACCEPTED
> **Date**: 2026-02-14
> **Decision**: Keycloak 26 serves as the identity provider. OAuth2/OIDC handles API authentication, SAML 2.0 supports enterprise SSO, and SCIM 2.0 automates user provisioning.

## Context

Archon must authenticate human users (developers, admins, viewers), external IdPs (enterprise customers using Okta, Azure AD, PingFederate), and service-to-service calls (internal microservices, agent executors). The platform needs a unified auth architecture that supports MFA, role-based access, tenant isolation, and compliance-grade session management without building a custom identity system.

## Decision

### Keycloak 26 as Identity Provider

Keycloak manages all user identities, federation, and token issuance. Each tenant gets a dedicated Keycloak realm (see ADR-012) providing complete configuration isolation. Keycloak stores no application data — it issues tokens consumed by the API layer.

### Authentication Methods

| Flow | Use Case | Protocol |
|---|---|---|
| **Browser login** | Web UI users | OAuth2 Authorization Code + PKCE |
| **Enterprise SSO** | Corporate IdP federation (Okta, Azure AD) | SAML 2.0 via Keycloak identity brokering |
| **API access** | CLI tools, third-party integrations | OAuth2 Client Credentials |
| **Service-to-service** | Internal microservices, agent executors | API key (HMAC-SHA256 signed, stored in Vault) |
| **SCIM provisioning** | Automated user sync from enterprise IdPs | SCIM 2.0 endpoints with Bearer token auth |

### JWT Token Format

All access tokens are signed JWTs (RS256) issued by Keycloak. The API validates tokens using cached JWKS (refreshed every 5 minutes, validated in < 5ms per AGENT_RULES).

```json
{
  "sub": "user-uuid",
  "iss": "https://auth.archon.dev/realms/{tenant-realm}",
  "aud": "archon-api",
  "tenant_id": "tenant-uuid",
  "roles": ["developer"],
  "permissions": ["agents:create", "agents:read", "workflows:execute"],
  "exp": 1708990800,
  "iat": 1708987200,
  "jti": "token-uuid"
}
```

The `get_current_user` FastAPI dependency extracts and validates this token on every request:

```python
# Middleware sets tenant context from JWT
async def get_current_user(token: str = Depends(oauth2_scheme)) -> AuthenticatedUser:
    payload = await validate_jwt(token)  # JWKS-cached validation < 5ms
    return AuthenticatedUser(
        id=payload["sub"],
        tenant_id=payload["tenant_id"],
        roles=payload["roles"],
        permissions=payload["permissions"],
    )
```

### MFA Requirements

MFA is mandatory for all human users. Supported factors:

- **TOTP** (Google Authenticator, Authy) — required as baseline.
- **WebAuthn / FIDO2** (hardware keys, biometrics) — supported as primary or secondary factor.
- **Recovery codes** — single-use, generated at MFA enrollment, stored encrypted in Keycloak.

Service accounts (API keys, Client Credentials) are exempt from MFA but require IP allowlisting.

### Session Management

| Parameter | Value | Rationale |
|---|---|---|
| Access token TTL | 15 minutes | Limits blast radius of token theft |
| Refresh token TTL | 8 hours | Matches a working day; avoids mid-task re-auth |
| Refresh token rotation | Enabled | Each refresh issues a new refresh token; old one is invalidated |
| Idle session timeout | 30 minutes | Triggers re-authentication after inactivity |
| Absolute session timeout | 12 hours | Forces daily re-auth regardless of activity |
| Token storage (browser) | Access token in memory; refresh token in httpOnly cookie | Prevents XSS access to refresh tokens |

### API Key Authentication (Service-to-Service)

For internal services and agent executors that cannot perform OAuth2 flows:

1. API keys are generated as HMAC-SHA256 hashes, stored in Vault KV-v2 (see ADR-010).
2. Only the hash is stored in PostgreSQL; the plaintext key is shown once at creation.
3. Keys are scoped to a tenant and a set of permissions — no cross-tenant access.
4. Rate limited to 5 auth attempts per minute per source IP.
5. Keys expire after 90 days; rotation is enforced via `SecretsManager` webhook notifications.

### RBAC and OPA Integration

After JWT validation, authorization checks use `check_permission(user, action, resource)` which evaluates OPA (Open Policy Agent) policies. Roles (admin, developer, viewer) map to permission sets defined in OPA Rego policies, enabling fine-grained and externalized authorization logic.

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **Auth0** | SaaS dependency; per-MAU pricing incompatible with open-source model. |
| **Custom JWT issuer** | Massive engineering effort for IdP federation, MFA, session management. Keycloak provides all of this. |
| **Firebase Auth** | Google Cloud lock-in; limited SAML/SCIM support; no self-hosted option. |
| **Passport.js / custom middleware** | No centralized identity management; each service implements auth differently. |
| **mTLS only (no JWT)** | Complex certificate distribution; no user identity or RBAC in the protocol. |

## Consequences

- Every API endpoint is protected by JWT validation via `Depends(get_current_user)` — no exceptions except `/health`, `/docs`, `/.well-known`, and `/scim/v2/ServiceProviderConfig`.
- Enterprise customers can federate their existing IdP in minutes via Keycloak's SAML brokering.
- SCIM 2.0 eliminates manual user provisioning — identity lifecycle is automated.
- Keycloak becomes critical infrastructure: downtime blocks all authentication.
- JWT validation adds < 5ms per request (JWKS cached locally).
- MFA enrollment must be part of the onboarding UX — impacts first-time user experience.
