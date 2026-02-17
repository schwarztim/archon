# Agent-01: Core Backend & Enterprise Identity Platform

> **Phase**: 1 | **Dependencies**: Agent-00 (Secrets Vault) | **Priority**: CRITICAL
> **Every other agent depends on this. It must be bulletproof.**

---

## Identity

You are Agent-01: the Core Backend & Enterprise Identity Builder. You build the foundational FastAPI backend, the complete identity and access management (IAM) system, and the LangGraph execution engine that every other component depends on.

## Mission

Build a production-grade backend that:
1. Serves as the API gateway for the entire platform
2. Implements enterprise-grade authentication (OAuth 2.0, SAML 2.0, OIDC) with full SSO federation
3. Provides complete user management with SCIM 2.0 provisioning
4. Integrates with Agent-00's Secrets Manager for all credential handling
5. Runs LangGraph agent execution with stateful persistence and streaming
6. Is horizontally scalable, fully observable, and compliant from day one

## Requirements

### API Server Foundation

**FastAPI Application**
- Factory pattern (`create_app()`) with environment-aware configuration
- Python 3.12+ with strict type hints, `from __future__ import annotations`
- Modular router registration with versioned prefix (`/api/v1/`)
- Request ID middleware (UUID per request, propagated to all downstream calls)
- Structured JSON logging via `structlog` with correlation IDs (request_id, tenant_id, user_id, trace_id)
- OpenTelemetry instrumentation: traces (Jaeger/Tempo), metrics (Prometheus), logs (OTLP)
- Health endpoints: `/health` (liveness), `/ready` (readiness — checks DB, Redis, Vault, Keycloak), `/startup`
- Graceful shutdown with in-flight request draining (30s timeout)
- Rate limiting via Redis (per-user, per-tenant, per-endpoint configurable)
- CORS configuration: per-environment allowlist (never wildcard in production)
- Request/response compression (gzip, br)
- Maximum request body size: 50MB (configurable)

**Database Layer**
- SQLModel ORM with PostgreSQL 16 (asyncpg driver for async operations)
- Alembic migrations with `--autogenerate` support
- Connection pooling via asyncpg (min=5, max=20 per worker, configurable)
- Read replicas support for query-heavy endpoints
- Row-Level Security (RLS) for tenant isolation:
  ```sql
  ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON agents
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
  ```
- Soft-delete on all models (`deleted_at` timestamp, never hard delete)
- Full-text search via `tsvector` columns on searchable entities
- Database-level audit triggers for critical tables

**Caching Layer**
- Redis 7+ for:
  - Session storage (auth sessions, WebSocket session state)
  - Rate limiting counters
  - Routing decision cache (Agent-07)
  - LangGraph state checkpoints
  - Pub/Sub for real-time WebSocket broadcasts
- Cache invalidation patterns: TTL-based + event-driven
- Redis Sentinel or Cluster mode for HA

### Enterprise Authentication & Authorization

**Keycloak 26 Integration (Primary IdP)**
- Keycloak deployed as a managed service or sidecar in Docker Compose
- Realm configuration: `archon` realm with pre-configured clients, roles, identity providers
- OIDC/OAuth 2.0 flows supported:
  - **Authorization Code + PKCE** (web app, mobile app — primary flow)
  - **Client Credentials** (service-to-service — for internal microservices and SDK)
  - **Device Authorization** (CLI tools, IoT devices)
  - **Refresh Token** (sliding window, configurable lifetime)
- Token configuration:
  - Access token: JWT, 15-minute lifetime, includes `sub`, `email`, `roles`, `tenant_id`, `permissions`
  - Refresh token: opaque, 8-hour lifetime (configurable per tenant), single-use with rotation
  - ID token: JWT, contains user profile claims
- Token validation middleware:
  ```python
  class JWTAuthMiddleware:
      """Validates JWT on every request. Caches JWKS for 1 hour."""
      async def __call__(self, request: Request, call_next):
          token = extract_bearer_token(request)
          claims = await self.validate_jwt(token)  # JWKS validation
          request.state.user = AuthenticatedUser.from_claims(claims)
          request.state.tenant_id = claims["tenant_id"]
          # Set RLS context for database queries
          await set_tenant_context(request.state.tenant_id)
  ```

**SAML 2.0 Federation**
- SP-initiated SSO flow:
  1. User hits Archon login → redirected to tenant's IdP (Okta, Azure AD, OneLogin, PingFederate)
  2. IdP authenticates → POST SAMLResponse to Archon ACS endpoint
  3. Archon validates signature, extracts assertions, creates/updates user, issues session
- IdP-initiated SSO: Accept unsolicited SAMLResponse from configured IdPs
- SAML metadata endpoint: `/.well-known/saml-metadata.xml` (auto-generated per tenant)
- Attribute mapping: configurable per IdP (map `urn:oid:0.9.2342.19200300.100.1.1` → `username`, etc.)
- SAML logout: Single Logout (SLO) via redirect and POST bindings
- Certificate management: signing + encryption certificates stored in Vault (Agent-00), auto-rotated
- Implementation: `python3-saml` (OneLogin) or Keycloak's built-in SAML broker

**Multi-Factor Authentication (MFA)**
- Keycloak-managed MFA with support for:
  - TOTP (Google Authenticator, Authy, 1Password) — via Vault TOTP engine for backup
  - WebAuthn/FIDO2 (hardware security keys, biometric — YubiKey, Touch ID)
  - SMS OTP (via Twilio integration, configurable per tenant)
  - Email OTP (fallback)
- MFA enforcement policies:
  - Per-tenant: require MFA for all users
  - Per-role: require MFA for admin roles only
  - Conditional: require MFA for sensitive operations (delete agent, rotate secrets, access admin panel)
  - Risk-based: require MFA for new devices, new locations, impossible travel

**API Key Authentication**
- For SDK/CLI/programmatic access (alternative to OAuth for automation)
- API key format: `oai_live_<32-char-random>` (prefixed for easy identification in secret scanning)
- API keys stored as bcrypt hashes in database, raw value shown once at creation
- Per-key scoping: which endpoints, which tenants, which agents
- Per-key rate limits (separate from user rate limits)
- Key rotation: create new → grace period (old key still works) → revoke old
- Last-used tracking: IP, timestamp, user-agent

### User Management & SCIM 2.0

**User Model**
```python
class User(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    external_id: str | None  # IdP's user ID (for SCIM sync)
    email: str = Field(unique=True, index=True)
    email_verified: bool = False
    display_name: str
    given_name: str | None
    family_name: str | None
    avatar_url: str | None
    phone: str | None
    locale: str = "en"
    timezone: str = "UTC"
    status: Literal["active", "invited", "suspended", "deactivated"] = "active"
    mfa_enabled: bool = False
    mfa_methods: list[str] = Field(default_factory=list)  # ["totp", "webauthn"]
    last_login_at: datetime | None
    last_login_ip: str | None
    failed_login_count: int = 0
    locked_until: datetime | None
    password_changed_at: datetime | None
    must_change_password: bool = False
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None
    deleted_at: datetime | None  # Soft delete
    created_by: uuid.UUID | None
    metadata: dict = Field(default_factory=dict)  # Extensible attributes
```

**Role-Based Access Control (RBAC)**
- Predefined roles (hierarchical):
  - `platform_admin` — full platform access (Archon operators)
  - `tenant_admin` — full tenant access (customer's IT admin)
  - `workspace_admin` — manage agents, users within a workspace
  - `developer` — create/edit/deploy agents
  - `operator` — monitor, approve deployments, view dashboards
  - `viewer` — read-only access
  - `api_consumer` — API-only access (SDK/CLI users)
- Custom roles: tenant admins can create custom roles with granular permissions
- Permission model:
  ```python
  class Permission(SQLModel, table=True):
      id: uuid.UUID
      resource: str        # "agents", "secrets", "connectors", "governance"
      action: str          # "create", "read", "update", "delete", "execute", "approve"
      scope: str           # "own", "workspace", "tenant", "platform"
      conditions: dict     # {"max_cost_per_execution": 1.0, "allowed_models": ["gpt-4"]}
  
  class RolePermission(SQLModel, table=True):
      role_id: uuid.UUID
      permission_id: uuid.UUID
  
  class UserRole(SQLModel, table=True):
      user_id: uuid.UUID
      role_id: uuid.UUID
      workspace_id: uuid.UUID | None  # Null = tenant-wide role
      granted_by: uuid.UUID
      granted_at: datetime
      expires_at: datetime | None
  ```

**Attribute-Based Access Control (ABAC) via OPA**
- OPA sidecar evaluates complex access decisions:
  ```rego
  package archon.authz
  
  default allow = false
  
  allow {
      input.user.roles[_] == "developer"
      input.action == "execute"
      input.resource.type == "agent"
      input.resource.tenant_id == input.user.tenant_id
      input.resource.cost_estimate < input.user.max_execution_cost
  }
  ```
- Policy inputs: user attributes, resource attributes, environmental context (time, IP, device)
- Decision caching: 5-minute TTL in Redis
- Decision logging: every allow/deny decision logged for audit

**SCIM 2.0 Provisioning**
- Full SCIM 2.0 server implementation (RFC 7644):
  ```
  GET    /scim/v2/Users                    # List/search users
  POST   /scim/v2/Users                    # Create user
  GET    /scim/v2/Users/{id}               # Get user
  PUT    /scim/v2/Users/{id}               # Replace user
  PATCH  /scim/v2/Users/{id}               # Update user (JSON Patch)
  DELETE /scim/v2/Users/{id}               # Deactivate user
  GET    /scim/v2/Groups                   # List groups
  POST   /scim/v2/Groups                   # Create group
  PATCH  /scim/v2/Groups/{id}              # Update group membership
  GET    /scim/v2/ServiceProviderConfig    # SCIM capabilities
  GET    /scim/v2/Schemas                  # Schema discovery
  GET    /scim/v2/ResourceTypes            # Resource type discovery
  POST   /scim/v2/Bulk                     # Bulk operations
  ```
- SCIM client support for syncing FROM external directories:
  - Azure AD / Entra ID (automatic provisioning)
  - Okta (SCIM connector)
  - OneLogin
  - Google Workspace Directory
  - Generic SCIM 2.0 endpoints
- User lifecycle: Create → Activate → Suspend → Reactivate → Deactivate → Delete
- Group sync: IdP groups map to Archon roles/workspaces
- Conflict resolution: IdP is source of truth; local changes flagged

**Self-Service User Management**
- User registration (email + password, or SSO only — configurable per tenant)
- Email verification flow (token in Vault, 24h expiry)
- Password policy (configurable per tenant):
  - Minimum length: 12 characters
  - Complexity: upper, lower, digit, special
  - History: no reuse of last 10 passwords
  - Expiry: configurable (90 days default, optional)
  - Breached password check (HaveIBeenPwned API via k-anonymity)
- Account lockout: 5 failed attempts → 15-minute lockout → progressive backoff
- Password reset: email link (token in Vault, 1h expiry)
- Profile management: display name, avatar, timezone, locale, notification preferences
- Session management: view active sessions, revoke any session, "sign out everywhere"

**User Invitations**
- Invite by email: admin sends invite → user receives link → sets password / SSO → activated
- Invite by link: generate shareable link (with expiry, max uses, pre-assigned role)
- Bulk invite: CSV upload (email, role, workspace)
- Invitation tracking: pending, accepted, expired, revoked

### Session Management

**Session Architecture**
- Sessions stored in Redis with TTL
- Session data:
  ```json
  {
    "session_id": "uuid",
    "user_id": "uuid",
    "tenant_id": "uuid",
    "created_at": "ISO-8601",
    "last_activity": "ISO-8601",
    "ip_address": "1.2.3.4",
    "user_agent": "Mozilla/5.0...",
    "device_fingerprint": "sha256:...",
    "auth_method": "oidc|saml|api_key|password",
    "mfa_verified": true,
    "permissions_snapshot": ["agents:read", "agents:execute"],
    "active": true
  }
  ```
- Idle timeout: 30 minutes (configurable per tenant)
- Absolute timeout: 12 hours (configurable)
- Concurrent session limit: configurable (default: 5 per user)
- Session fixation protection: regenerate session ID after authentication
- Secure cookie attributes: `HttpOnly`, `Secure`, `SameSite=Strict`, `__Host-` prefix

### Core Data Models

**Agent Model**
```python
class Agent(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255)
    slug: str = Field(unique=True, index=True)
    description: str | None
    agent_type: Literal["workflow", "conversational", "autonomous", "hybrid"]
    status: Literal["draft", "review", "approved", "published", "deprecated", "archived"]
    visibility: Literal["private", "workspace", "tenant", "public"]
    graph_definition: dict  # LangGraph JSON definition
    config: AgentConfig  # Runtime configuration
    owner_id: uuid.UUID = Field(foreign_key="users.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    workspace_id: uuid.UUID = Field(foreign_key="workspaces.id")
    approval_status: Literal["pending", "approved", "rejected"] = "pending"
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None
    deleted_at: datetime | None
    version: int = 1  # Optimistic locking
```

**Execution Model**
```python
class Execution(SQLModel, table=True):
    id: uuid.UUID
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    agent_version_id: uuid.UUID = Field(foreign_key="agent_versions.id")
    triggered_by: uuid.UUID = Field(foreign_key="users.id")
    tenant_id: uuid.UUID
    status: Literal["queued", "running", "paused", "completed", "failed", "cancelled", "timed_out"]
    inputs: dict
    outputs: dict | None
    error: ExecutionError | None
    metrics: ExecutionMetrics  # duration, token counts, cost, model used
    trace_id: str  # OpenTelemetry trace ID
    parent_execution_id: uuid.UUID | None  # For sub-agent calls
    approval_gates: list[ApprovalGate]  # Human-in-loop approvals
    started_at: datetime | None
    completed_at: datetime | None
    timeout_seconds: int = 300
    created_at: datetime
```

**AuditLog Model**
```python
class AuditLog(SQLModel, table=True):
    """Immutable, append-only. No UPDATE or DELETE operations. Hash-chained for tamper detection."""
    id: uuid.UUID
    timestamp: datetime
    actor_id: uuid.UUID | None  # Null for system events
    actor_type: Literal["user", "service", "system", "scim"]
    tenant_id: uuid.UUID
    action: str  # "agent.created", "user.login", "secret.rotated", "policy.violated"
    resource_type: str  # "agent", "user", "secret", "connector"
    resource_id: str
    details: dict  # Action-specific payload (NEVER contains secrets/PII values)
    source_ip: str | None
    user_agent: str | None
    result: Literal["success", "failure", "denied"]
    risk_score: float | None  # 0.0-1.0, set by risk engine
    previous_hash: str  # SHA-256 of previous entry (tamper detection)
    entry_hash: str  # SHA-256 of this entry
```

### LangGraph Execution Engine

- Agent graphs defined as JSON (exported from React Flow builder)
- Node types: `LLMCall`, `ToolInvocation`, `Conditional`, `HumanApproval`, `Parallel`, `SubAgent`, `DataTransform`, `Output`
- State persistence via PostgreSQL (checkpointer)
- Token-by-token streaming via WebSocket (with backpressure)
- Interrupt/resume for human approval gates:
  1. Execution hits HumanApproval node → status = "paused"
  2. WebSocket notifies approvers → UI shows approval dialog
  3. Approver accepts/rejects → execution resumes/aborts
  4. Approval decision logged in audit trail
- Execution timeout enforcement (configurable per agent, max 1 hour)
- Cost budget enforcement: execution aborted if estimated cost exceeds agent's budget
- Secrets injection: execution context receives scoped secrets from Agent-00's SecretsManager
- Execution isolation: each execution gets its own LangGraph instance (no shared state between runs)

### Infrastructure

**Docker Compose (Local Development)**
```yaml
services:
  api:          # FastAPI backend (uvicorn, hot-reload)
  postgres:     # PostgreSQL 16 with pgvector extension
  redis:        # Redis 7 for sessions, cache, pub/sub
  keycloak:     # Keycloak 26 with pre-configured realm
  vault:        # HashiCorp Vault (dev mode for local)
  minio:        # S3-compatible object storage
  neo4j:        # Graph database for lineage
  mailhog:      # Email testing (SMTP sink)
  otel:         # OpenTelemetry Collector
  jaeger:       # Trace viewer
  prometheus:   # Metrics collection
  grafana:      # Dashboards
```

**Environment Configuration**
- All settings via `pydantic-settings` with `ARCHON_` env prefix
- Secret values NEVER in env vars — fetched from Vault at startup
- Configuration hierarchy: defaults → env vars → config file → Vault
- Feature flags: per-tenant feature toggles (stored in Redis, UI-configurable)

## Output Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory
│   ├── config.py                  # Settings (pydantic-settings)
│   ├── database.py                # SQLModel engine, session, RLS
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py                # User, Role, Permission, UserRole
│   │   ├── agent.py               # Agent, AgentVersion, AgentConfig
│   │   ├── execution.py           # Execution, ExecutionMetrics
│   │   ├── audit.py               # AuditLog (hash-chained)
│   │   ├── session.py             # Session model
│   │   ├── api_key.py             # APIKey model
│   │   ├── invitation.py          # UserInvitation model
│   │   └── workspace.py           # Workspace model
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── agents.py              # Agent CRUD + execution trigger
│   │   ├── executions.py          # Execution history, status, cancel
│   │   ├── users.py               # User management (admin)
│   │   ├── auth.py                # Login, logout, token refresh, MFA
│   │   ├── saml.py                # SAML SSO endpoints (ACS, SLO, metadata)
│   │   ├── scim.py                # SCIM 2.0 provisioning endpoints
│   │   ├── api_keys.py            # API key management
│   │   ├── sessions.py            # Session listing, revocation
│   │   ├── invitations.py         # User invitation management
│   │   ├── workspaces.py          # Workspace CRUD
│   │   ├── health.py              # Health, readiness, startup probes
│   │   └── models.py              # LLM model registry
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py        # Authentication logic
│   │   ├── user_service.py        # User CRUD + lifecycle
│   │   ├── scim_service.py        # SCIM provisioning logic
│   │   ├── agent_service.py       # Agent CRUD + approval workflow
│   │   ├── execution_service.py   # Execution orchestration
│   │   ├── session_service.py     # Session management
│   │   ├── invitation_service.py  # Invite flow
│   │   └── audit_service.py       # Audit logging + hash chain
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── jwt.py                 # JWT validation (JWKS cache)
│   │   ├── saml.py                # SAML 2.0 SP implementation
│   │   ├── oidc.py                # OIDC client
│   │   ├── api_key.py             # API key validation
│   │   ├── mfa.py                 # MFA verification helpers
│   │   ├── password.py            # Password policy + hashing
│   │   └── rbac.py                # Permission checking + OPA integration
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth.py                # JWT/SAML/API key extraction
│   │   ├── tenant.py              # Tenant context + RLS setup
│   │   ├── cors.py                # CORS configuration
│   │   ├── logging.py             # Request/response structured logging
│   │   ├── telemetry.py           # OpenTelemetry span management
│   │   ├── rate_limit.py          # Redis-backed rate limiting
│   │   └── request_id.py          # UUID request ID injection
│   ├── websocket/
│   │   ├── __init__.py
│   │   ├── manager.py             # Connection manager
│   │   ├── handlers.py            # Execution streaming, builder sync
│   │   └── auth.py                # WebSocket authentication (ticket-based)
│   ├── langgraph/
│   │   ├── __init__.py
│   │   ├── engine.py              # Execution engine
│   │   ├── nodes.py               # Node type implementations
│   │   ├── checkpointer.py        # PostgreSQL state persistence
│   │   └── streaming.py           # Token streaming adapter
│   ├── secrets/                   # Agent-00 SDK integration
│   │   ├── __init__.py
│   │   ├── manager.py             # SecretsManager instance
│   │   ├── dependencies.py        # FastAPI Depends() for secrets
│   │   └── middleware.py          # Request-scoped secret context
│   └── utils/
│       ├── __init__.py
│       ├── pagination.py          # Cursor + offset pagination
│       ├── validators.py          # Common validators
│       ├── hashing.py             # Argon2 password hashing
│       └── email.py               # Email sending (invites, MFA, alerts)
├── alembic/
│   ├── env.py
│   ├── versions/
│   └── alembic.ini
├── tests/
│   ├── conftest.py                # Fixtures, factories, test DB
│   ├── test_auth.py               # OAuth, SAML, API key, MFA tests
│   ├── test_users.py              # User CRUD, RBAC, lifecycle
│   ├── test_scim.py               # SCIM provisioning tests
│   ├── test_agents.py             # Agent CRUD, approval workflow
│   ├── test_executions.py         # Execution lifecycle, streaming
│   ├── test_sessions.py           # Session management tests
│   ├── test_audit.py              # Audit log integrity tests
│   ├── test_rls.py                # Row-level security isolation
│   └── test_websocket.py          # WebSocket auth + streaming
├── Dockerfile
├── requirements.txt
└── pyproject.toml

docker-compose.yml                  # Full local dev stack (14 services)
Makefile                            # Dev commands
```

## API Endpoints (Complete)

```
# Authentication
POST   /api/v1/auth/login              # Email + password login
POST   /api/v1/auth/logout             # Logout (revoke session)
POST   /api/v1/auth/token/refresh      # Refresh access token
GET    /api/v1/auth/oidc/authorize     # OIDC authorization redirect
GET    /api/v1/auth/oidc/callback      # OIDC callback
POST   /api/v1/auth/saml/acs           # SAML Assertion Consumer Service
GET    /api/v1/auth/saml/login         # SP-initiated SAML login
GET    /api/v1/auth/saml/logout        # SAML Single Logout
GET    /api/v1/auth/saml/metadata      # SAML SP metadata
POST   /api/v1/auth/mfa/verify         # Verify MFA code
POST   /api/v1/auth/mfa/enroll         # Enroll MFA method
GET    /api/v1/auth/sessions           # List active sessions
DELETE /api/v1/auth/sessions/{id}      # Revoke specific session
DELETE /api/v1/auth/sessions           # Revoke all sessions

# API Keys
POST   /api/v1/api-keys               # Create API key
GET    /api/v1/api-keys               # List API keys
DELETE /api/v1/api-keys/{id}          # Revoke API key
POST   /api/v1/api-keys/{id}/rotate   # Rotate API key

# Users
GET    /api/v1/users                   # List users (admin)
POST   /api/v1/users                   # Create user (admin)
GET    /api/v1/users/{id}              # Get user
PUT    /api/v1/users/{id}              # Update user
PATCH  /api/v1/users/{id}/status       # Activate/suspend/deactivate
DELETE /api/v1/users/{id}              # Soft-delete user
GET    /api/v1/users/me                # Current user profile
PUT    /api/v1/users/me                # Update own profile
PUT    /api/v1/users/me/password       # Change own password
POST   /api/v1/users/password-reset    # Request password reset
POST   /api/v1/users/password-reset/confirm  # Confirm password reset

# SCIM 2.0
GET    /scim/v2/Users
POST   /scim/v2/Users
GET    /scim/v2/Users/{id}
PUT    /scim/v2/Users/{id}
PATCH  /scim/v2/Users/{id}
DELETE /scim/v2/Users/{id}
GET    /scim/v2/Groups
POST   /scim/v2/Groups
PATCH  /scim/v2/Groups/{id}
GET    /scim/v2/ServiceProviderConfig
GET    /scim/v2/Schemas
GET    /scim/v2/ResourceTypes
POST   /scim/v2/Bulk

# Invitations
POST   /api/v1/invitations             # Send invitation
GET    /api/v1/invitations             # List invitations
DELETE /api/v1/invitations/{id}        # Revoke invitation
POST   /api/v1/invitations/{token}/accept  # Accept invitation

# Roles & Permissions
GET    /api/v1/roles                   # List roles
POST   /api/v1/roles                   # Create custom role
PUT    /api/v1/roles/{id}              # Update role
DELETE /api/v1/roles/{id}              # Delete custom role
GET    /api/v1/permissions             # List all permissions
POST   /api/v1/users/{id}/roles        # Assign role to user
DELETE /api/v1/users/{id}/roles/{role_id}  # Remove role from user

# Workspaces
GET    /api/v1/workspaces              # List workspaces
POST   /api/v1/workspaces              # Create workspace
GET    /api/v1/workspaces/{id}         # Get workspace
PUT    /api/v1/workspaces/{id}         # Update workspace
DELETE /api/v1/workspaces/{id}         # Delete workspace
POST   /api/v1/workspaces/{id}/members # Add member

# Agents
GET    /api/v1/agents                  # List agents (filtered by permissions)
POST   /api/v1/agents                  # Create agent
GET    /api/v1/agents/{id}             # Get agent
PUT    /api/v1/agents/{id}             # Update agent
DELETE /api/v1/agents/{id}             # Soft-delete agent
POST   /api/v1/agents/{id}/execute     # Trigger execution
POST   /api/v1/agents/{id}/approve     # Approve agent for publishing
GET    /api/v1/agents/{id}/versions    # List versions
POST   /api/v1/agents/{id}/clone       # Clone agent

# Executions
GET    /api/v1/executions              # List executions
GET    /api/v1/executions/{id}         # Get execution details
POST   /api/v1/executions/{id}/cancel  # Cancel running execution
POST   /api/v1/executions/{id}/approve-gate  # Approve human-in-loop gate
GET    /api/v1/executions/{id}/trace   # Get OpenTelemetry trace

# Models (LLM Registry)
GET    /api/v1/models                  # List registered models
POST   /api/v1/models                  # Register model
PUT    /api/v1/models/{id}             # Update model config
DELETE /api/v1/models/{id}             # Remove model
GET    /api/v1/models/{id}/health      # Model health check

# Audit
GET    /api/v1/audit                   # Query audit logs (paginated, filtered)
GET    /api/v1/audit/export            # Export audit logs (CSV/JSON)
GET    /api/v1/audit/integrity         # Verify hash chain integrity

# Health
GET    /health                          # Liveness probe
GET    /ready                           # Readiness probe
GET    /startup                         # Startup probe
```

## Verify Commands

```bash
# Backend starts without errors
cd ~/Scripts/Archon && python -c "from backend.app.main import app; print('OK')"

# All models importable
cd ~/Scripts/Archon && python -c "from backend.app.models.user import User, Role, Permission; from backend.app.models.agent import Agent; from backend.app.models.execution import Execution; from backend.app.models.audit import AuditLog; print('All models OK')"

# Auth module importable
cd ~/Scripts/Archon && python -c "from backend.app.auth.jwt import validate_jwt; from backend.app.auth.saml import SAMLServiceProvider; from backend.app.auth.rbac import check_permission; print('Auth OK')"

# SCIM endpoints importable
cd ~/Scripts/Archon && python -c "from backend.app.routers.scim import router; print('SCIM OK')"

# Secrets integration
cd ~/Scripts/Archon && python -c "from backend.app.secrets.manager import SecretsManager; print('Secrets OK')"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest --tb=short -q

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet

# Migrations run cleanly
cd ~/Scripts/Archon/backend && alembic check 2>&1 | grep -qv 'ERROR'

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'password\s*=\s*"[^"]*"' --include='*.py' backend/ || echo 'FAIL'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] OAuth 2.0 Authorization Code + PKCE flow works end-to-end
- [ ] SAML 2.0 SP-initiated SSO works with at least Okta and Azure AD test configs
- [ ] SCIM 2.0 provisioning creates/updates/deactivates users from IdP
- [ ] API key authentication works for SDK access with per-key scoping
- [ ] MFA enforcement (TOTP) blocks access until verified
- [ ] RBAC correctly restricts endpoints per role (test all 7 predefined roles)
- [ ] RLS prevents cross-tenant data access at the database level
- [ ] Session management: concurrent limit, idle timeout, "sign out everywhere" all work
- [ ] Password policy enforces complexity, history, breach-check
- [ ] Account lockout activates after 5 failed attempts
- [ ] Audit log hash chain is tamper-evident (modify a row → integrity check fails)
- [ ] All CRUD endpoints for agents, versions, users return correct responses
- [ ] WebSocket streams agent execution tokens with auth verification
- [ ] LangGraph executes multi-step flows with human approval gates
- [ ] Secrets retrieved from Vault via SecretsManager (never hardcoded)
- [ ] Docker Compose brings up full 14-service dev stack
- [ ] OpenTelemetry traces propagate through all service calls
- [ ] All tests pass with >80% coverage
- [ ] Zero plaintext secrets in logs, env vars, or source code
