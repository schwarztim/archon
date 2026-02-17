# ADR-013: Audit Trail

> **Status**: ACCEPTED
> **Date**: 2026-02-14
> **Decision**: All state-changing operations and security-sensitive events are recorded in an immutable, append-only `AuditLog` table with structured metadata, supporting SOC 2 and HIPAA compliance.

## Context

Archon processes sensitive data across multiple tenants: AI agent configurations, workflow executions, API credentials, and user management actions. Enterprise customers and compliance frameworks (SOC 2 Type II, HIPAA) require a tamper-evident audit trail that records who did what, when, to which resource, and with what outcome. Without centralized audit logging, forensic investigation of security incidents, unauthorized access, or data breaches is impossible.

## Decision

### AuditLog Model

All audit events are stored in a dedicated `audit_logs` table in PostgreSQL 16, scoped by `tenant_id` with RLS enforced (see ADR-012).

```python
class AuditLog(SQLModel, table=True):
    """Immutable audit trail entry. Never updated or deleted by application code."""
    __tablename__ = "audit_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(nullable=False, index=True)
    actor_id: uuid.UUID = Field(nullable=False, index=True)
    actor_type: str  # "user", "service", "system"
    action: str = Field(index=True)  # "agent.created", "secret.accessed", "user.login"
    resource_type: str  # "agent", "workflow", "secret", "user"
    resource_id: str  # UUID of the affected resource
    result: str  # "success", "denied", "error"
    metadata: dict = Field(default_factory=dict, sa_column=Column(JSON))
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str = Field(index=True)  # Correlation with structured logs
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
```

### Events to Log

Every state-changing operation and security-sensitive read produces an audit entry:

| Category | Events | Example `action` |
|---|---|---|
| **Authentication** | Login, logout, MFA challenge, failed auth, token refresh | `auth.login`, `auth.mfa_challenge`, `auth.failed` |
| **User management** | Create, update, delete, role change, SCIM provision/deprovision | `user.created`, `user.role_changed`, `user.deprovisioned` |
| **Resource CRUD** | Create/update/delete agents, workflows, tools, workspaces | `agent.created`, `workflow.updated`, `tool.deleted` |
| **Secrets access** | Read, create, rotate, revoke secrets via SecretsManager | `secret.accessed`, `secret.rotated`, `secret.revoked` |
| **Policy changes** | OPA policy updates, RBAC role modifications, RLS policy changes | `policy.updated`, `role.permissions_changed` |
| **Execution** | Agent runs, workflow executions, approvals, rejections | `execution.started`, `execution.approved`, `execution.failed` |
| **Tenant admin** | Tenant created, billing updated, SSO configured, SCIM endpoint registered | `tenant.created`, `tenant.sso_configured` |

### Immutable Append-Only Pattern

Audit log integrity is enforced at multiple layers:

1. **No UPDATE/DELETE permissions**: The application database role has only `INSERT` and `SELECT` on `audit_logs`. PostgreSQL `REVOKE` prevents mutation.
2. **Database trigger**: A `BEFORE UPDATE OR DELETE` trigger on `audit_logs` raises an exception, preventing any mutation even by privileged application roles.
3. **Hash chain**: Each entry includes a `prev_hash` field (SHA-256 of the previous entry), enabling tamper detection during compliance audits.

```sql
-- Prevent any modification to audit records
REVOKE UPDATE, DELETE ON audit_logs FROM archon_app_role;

CREATE OR REPLACE FUNCTION prevent_audit_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is immutable: % operations are forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
```

### Writing Audit Entries

All audit logging uses the `audit_log()` helper, called after every state-changing operation per AGENT_RULES:

```python
async def audit_log(
    user: AuthenticatedUser,
    action: str,
    resource_type: str,
    resource_id: str,
    metadata: dict | None = None,
    result: str = "success",
) -> None:
    """Append an immutable audit entry. Never call outside a request context."""
    entry = AuditLog(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        actor_type="user",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        result=result,
        metadata=metadata or {},
        request_id=get_request_id(),
        ip_address=get_client_ip(),
    )
    db.add(entry)
    await db.commit()
```

### Retention Policy

| Data Classification | Retention Period | Rationale |
|---|---|---|
| **Security events** (auth, secrets, policy) | 7 years | SOC 2 Type II, HIPAA §164.312(b) |
| **CRUD operations** (agents, workflows) | 3 years | Business continuity, incident investigation |
| **Execution logs** (agent runs) | 1 year | Operational debugging; high volume |

Retention is enforced by a scheduled job that moves expired records to cold storage (S3/GCS with lifecycle policies), not by deletion from PostgreSQL. The cold-storage exports preserve the hash chain for later verification.

### Querying and Access

- Audit logs are queryable via `GET /api/v1/audit-logs` with filters: `action`, `resource_type`, `actor_id`, `date_range`.
- RLS ensures tenants can only query their own audit trail.
- Platform admins (superuser role) can query across tenants for incident response, bypassing RLS via a separate database connection.
- Structured logging with `request_id` and `tenant_id` correlation (per AGENT_RULES) enables joining audit entries with application logs for full request tracing.

### Compliance Mapping

| Requirement | How Addressed |
|---|---|
| **SOC 2 CC6.1** — Logical access controls | Auth events logged with result (success/denied) |
| **SOC 2 CC7.2** — System monitoring | All CRUD and execution events captured |
| **HIPAA §164.312(b)** — Audit controls | Immutable logs, 7-year retention, tamper detection |
| **HIPAA §164.308(a)(5)** — Security awareness | Failed auth attempts logged and alertable |
| **GDPR Art. 30** — Records of processing | Resource CRUD events document data processing activities |

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **Application log files only (ELK/Loki)** | Not queryable per tenant via API; no immutability guarantee; log rotation destroys records. |
| **Separate audit database per tenant** | Same scaling problems as ADR-012; shared table with RLS is simpler and consistent. |
| **Event sourcing (full event store)** | Over-engineered for audit purposes; audit trail is write-heavy, read-seldom — append-only table is sufficient. |
| **Third-party audit SaaS (Drata, Vanta)** | Adds external dependency and data residency concerns; core audit data must stay in-platform. |
| **Blockchain / distributed ledger** | Massive complexity for minimal benefit; hash-chained rows in PostgreSQL provide equivalent tamper evidence. |

## Consequences

- Every state-changing endpoint must call `audit_log()` — enforced by code review and integration tests.
- Audit table grows continuously; partitioning by `created_at` (monthly) is required for query performance.
- Hash chain verification adds a serialization point on writes; throughput is bounded by single-row insert latency (~1ms).
- Cold storage archival must be automated before table size impacts PostgreSQL performance.
- Tenant data deletion requests (GDPR Art. 17) must preserve audit records but anonymize PII fields — deletion of audit entries is never permitted.
