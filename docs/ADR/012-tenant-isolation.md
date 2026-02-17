# ADR-012: Tenant Isolation

> **Status**: ACCEPTED
> **Date**: 2026-02-14
> **Decision**: Multi-tenant isolation uses PostgreSQL 16 Row-Level Security (RLS) on a shared database, per-tenant Vault namespaces, per-tenant Keycloak realms, and per-tenant SCIM provisioning.

## Context

Archon is a multi-tenant platform where each tenant's data — agents, workflows, execution logs, secrets, and user identities — must be strictly isolated. A tenant admin must never see, modify, or infer the existence of another tenant's resources. The isolation model must scale to thousands of tenants without proportional infrastructure cost, while meeting SOC 2 and enterprise customer requirements for data segregation.

## Decision

### Database Isolation: Shared Database + PostgreSQL 16 RLS

All tenants share a single PostgreSQL 16 database. Row-Level Security policies enforce that every query is scoped to the authenticated tenant's `tenant_id`.

```sql
-- Every tenant-scoped table includes tenant_id as a non-nullable column
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE agents FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON agents
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
```

The FastAPI middleware sets the PostgreSQL session variable on every request:

```python
# Middleware sets tenant context from JWT before any query executes
async def set_tenant_context(db: AsyncSession, tenant_id: str) -> None:
    await db.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
```

Every table with tenant-scoped data includes `tenant_id` as a non-nullable UUID foreign key with an index. The ORM layer also applies `Agent.tenant_id == user.tenant_id` filters as defense-in-depth — RLS is the enforcement layer, application filters are the safety net.

### Why Shared Database + RLS Over Separate Databases

| Factor | Shared DB + RLS | Separate DB per Tenant |
|---|---|---|
| **Schema migrations** | Run once, apply everywhere | Run N times, risk drift |
| **Connection pooling** | Single pool, efficient | N pools, connection explosion at scale |
| **Cross-tenant queries (admin)** | Superuser bypasses RLS | Requires cross-database joins or federation |
| **Operational cost** | One database to backup, monitor, tune | N databases; linear ops cost |
| **Tenant provisioning** | Insert row in `tenants` table | Provision entire database + schema |
| **Compliance** | RLS is NIST/SOC 2 recognized isolation | Stronger isolation but rarely required |
| **Scale** | Thousands of tenants, single cluster | Impractical beyond ~100 tenants |

Separate databases are warranted only for regulated tenants requiring physical data isolation (e.g., government). This can be supported as a premium tier without changing the default architecture.

### Vault Isolation: Per-Tenant Namespaces

Each tenant's secrets are stored under a dedicated Vault namespace (see ADR-010):

```
archon/tenants/{tenant_id}/secret/data/*    # KV-v2 static secrets
archon/tenants/{tenant_id}/transit/*          # Encryption keys
```

Vault policies bind to the tenant namespace. A compromised tenant token cannot access another namespace. The `SecretsManager` abstraction enforces this by prepending `tenant_id` to all Vault paths automatically.

### Keycloak Isolation: Per-Tenant Realms

Each tenant maps to a dedicated Keycloak realm (see ADR-011):

- **Realm name**: `archon-{tenant_id}`
- **Realm-scoped users**: Users exist only within their tenant's realm. No cross-realm visibility.
- **Realm-scoped IdP federation**: Each tenant configures their own SAML/OIDC identity providers.
- **Realm-scoped client configs**: OAuth2 client IDs, redirect URIs, and scopes are per-realm.

Tenant admins can manage their realm's users, roles, and IdP settings through Archon's admin UI, which delegates to Keycloak's Admin REST API scoped to their realm.

### SCIM 2.0 Per-Tenant Provisioning

Each tenant has a unique SCIM endpoint:

```
POST /scim/v2/tenants/{tenant_id}/Users
GET  /scim/v2/tenants/{tenant_id}/Users
POST /scim/v2/tenants/{tenant_id}/Groups
```

SCIM requests are authenticated with tenant-scoped Bearer tokens and provision users into the corresponding Keycloak realm. When a user is deprovisioned via SCIM, their access is revoked across all systems (Keycloak disabled, API keys revoked in Vault, sessions invalidated).

### Billing Attribution

All resource consumption is tagged with `tenant_id`:

- **Compute**: Agent execution time logged with `tenant_id` in the `executions` table.
- **Storage**: File uploads and vector embeddings tracked per tenant.
- **API calls**: Request counts aggregated per tenant via structured logging (`tenant_id` in every log entry).
- **Secrets**: Vault audit log entries include the tenant namespace.

Usage metrics are queryable via the admin API for billing integration. RLS ensures tenants can only see their own usage data.

## Alternatives Considered

| Alternative | Why Rejected |
|---|---|
| **Separate database per tenant** | Does not scale beyond ~100 tenants; schema migration complexity grows linearly. |
| **Schema-per-tenant (PostgreSQL schemas)** | Better isolation than RLS but same migration and connection pooling problems as separate databases. |
| **Application-level filtering only (no RLS)** | A single missing `WHERE tenant_id = ...` clause causes a data leak. RLS is the defense-in-depth layer. |
| **Shared Keycloak realm with group-based isolation** | Cross-tenant user visibility; misconfigured group policies could leak data. Per-realm is the Keycloak-recommended multi-tenant pattern. |
| **Single Vault namespace with path-based policies** | Path-based policies are error-prone at scale. Namespaces provide hard isolation boundaries. |

## Consequences

- Tenant provisioning creates entries in PostgreSQL (`tenants` table), Vault (namespace + policies), and Keycloak (realm) — all three must succeed atomically or roll back.
- RLS adds negligible query overhead (< 1ms per query) but requires discipline: every new table must have RLS policies, enforced by CI checks on Alembic migrations.
- Per-tenant Keycloak realms consume memory; Keycloak must be scaled horizontally for large tenant counts.
- Developers must never use a database superuser connection in application code — superusers bypass RLS.
- Tenant deletion requires coordinated cleanup across PostgreSQL (soft delete + data retention), Vault (namespace deletion), and Keycloak (realm deletion).
