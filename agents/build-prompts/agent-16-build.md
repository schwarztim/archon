# Agent 16 — SSO + Tenants + Users — Build Prompt

## Context

You are building the **SSO + Tenants + Users** module for the Archon AI orchestration platform. This module provides multi-tenant management, SSO configuration (OIDC, SAML, LDAP), user administration with RBAC, and an RBAC matrix visualization. The backend has extensive auth/tenancy logic already — the **SSO configuration UI has zero implementation** anywhere in the platform.

**Stack:** Backend: Python 3.12, FastAPI, SQLModel, Alembic, AsyncSession. Frontend: React 19, TypeScript strict, shadcn/ui, Tailwind, React Flow. Auth: JWT via Keycloak. Secrets: HashiCorp Vault via `backend/app/secrets/manager.py`.

---

## What Already Exists

| File | Lines | Status |
|------|-------|--------|
| `frontend/src/pages/TenantsPage.tsx` | 231 | New Tenant form (Name, Slug, Owner, Type). **EXTEND with detail page.** |
| `frontend/src/pages/LoginPage.tsx` | 230 | Login form. **KEEP.** |
| `frontend/src/api/tenancy.ts` | 66 | Tenancy API client. **EXTEND.** |
| `backend/app/routes/tenancy.py` | 646 | Tenancy routes. **EXTEND with SSO config.** |
| `backend/app/routes/tenants.py` | 292 | Tenant CRUD. **EXTEND.** |
| `backend/app/routes/auth_routes.py` | 655 | Auth routes with OIDC/SAML. **EXTEND.** |
| `backend/app/routes/saml.py` | 326 | SAML routes. **KEEP.** |
| `backend/app/routes/scim.py` | 389 | SCIM provisioning. **KEEP.** |
| `backend/app/services/tenant_service.py` | 714 | Tenant service. **EXTEND.** |
| `backend/app/services/saml_service.py` | 448 | SAML service. **KEEP.** |
| `backend/app/services/scim_service.py` | 431 | SCIM service. **KEEP.** |
| `backend/app/models/tenancy.py` | 302 | Tenancy models. **KEEP.** |
| **SSO Configuration UI** | 0 | **ZERO exists anywhere in the platform. BUILD from scratch.** |

---

## What to Build

### 1. SSO Configuration Page

New page (or Settings tab) for configuring identity providers per tenant:

#### OIDC Configuration Form
- **Discovery URL** — text input, e.g., `https://keycloak.example.com/realms/archon/.well-known/openid-configuration`
- **Client ID** — text input
- **Client Secret** — password field, stored in Vault via SecretsManager at path `archon/tenants/{tenant_id}/sso/oidc/client_secret`
- **Scopes** — multi-select: `openid`, `profile`, `email`, `groups`, `offline_access`
- **Claim Mappings** — visual mapper (see below)

#### SAML Configuration Form
- **Metadata URL** — text input, OR upload metadata XML file
- **Entity ID** — auto-populated from metadata, editable
- **ACS URL** — read-only, displays Archon's Assertion Consumer Service URL
- **Certificate** — textarea or file upload for IdP signing certificate
- **Attribute Mappings** — visual mapper (same as OIDC)

#### Claim/Attribute Mapper (shared component)
Visual row-based mapper — **not** raw JSON editing:

```
[ IdP Claim Input ] → [ Archon Field Dropdown ]
─────────────────────────────────────────────────
email               → Email
preferred_username  → Username  
given_name          → First Name
family_name         → Last Name
groups              → Groups
tenant_id           → Tenant ID
role                → Role
[+ Add Mapping]
```

Each row: text input for IdP claim name → dropdown for Archon field. Add/remove rows dynamically.

#### LDAP / Active Directory Form
- **Host** — text input
- **Port** — number input (default: 389, 636 for LDAPS)
- **Use TLS** — toggle
- **Base DN** — text input, e.g., `dc=example,dc=com`
- **Bind DN** — text input
- **Bind Password** — password field, stored in Vault at `archon/tenants/{tenant_id}/sso/ldap/bind_password`
- **User Filter** — text input, e.g., `(objectClass=person)`
- **Group Filter** — text input, e.g., `(objectClass=group)`
- **Attribute Mappings** — same visual mapper

#### Test Connection Button
- For OIDC: Fetches the discovery document and validates it returns expected fields
- For SAML: Validates metadata XML/URL and parses entity info
- For LDAP: Attempts bind with provided credentials
- Shows success (green) or error message (red) with details

#### Multiple IdPs Per Tenant
A tenant can configure multiple identity providers. Listed in a table with: Name, Type (OIDC/SAML/LDAP), Status (Active/Inactive), Default (toggle), Actions (Edit/Delete/Test).

### 2. Tenant Management Enhancement

Tenant detail page with tabbed layout:

| Tab | Content |
|-----|---------|
| **General** | Name, slug, type, owner, created date, status |
| **Identity Providers** | List of configured IdPs with add/edit/delete |
| **Usage & Quotas** | Max agents (slider 1–100), max executions/day (slider), max storage (GB), current usage bars |
| **Members** | Table of users in this tenant: name, email, role, last login, status |
| **Billing** | Plan type, usage this month, cost estimate |

**Usage dashboard widget:** Agents count (bar), executions this month (bar), storage used (bar), each showing current/max.

### 3. RBAC Matrix Visualization

Matrix table showing permissions across the platform:

**Columns:** Roles — `Super Admin`, `Tenant Admin`, `Developer`, `Viewer`, custom roles

**Rows:** Resources — `Agents`, `Executions`, `Models`, `Connectors`, `Secrets`, `Users`, `Settings`, `Governance`, `DLP`, `Cost Management`, `SentinelScan`, `MCP Apps`

**Cells:** Action checkboxes — `Create`, `Read`, `Update`, `Delete` (shown as a 4-checkbox group or as CRUD icons)

**Features:**
- Read-only for built-in roles, editable for custom roles
- **Create custom role:** Button opens form: role name, description, then check permissions in the matrix
- **Role assignment:** From user management, assign role via dropdown
- Color coding: green = permitted, gray = denied

### 4. User Management Enhancement

Extend existing user management:

- **Role detail:** Expandable row showing what each role can access (inline permission summary)
- **Activity log per user:** From audit trail, show recent actions by this user
- **Impersonate button:** For tenant admins — starts session as selected user (with prominent banner: "Impersonating [user]"). All impersonation actions logged in `AuditLog` with `impersonated_by` field.
- **SSO-provisioned indicator:** Badge showing if user was provisioned via SSO/SCIM vs. local account

---

## Patterns to Follow

### Pattern 1: Dify Member Management

**Source:** `dify/web/app/components/header/account-setting/members-page/`

Dify has workspace member management with role assignment (Owner, Admin, Editor, Viewer). Members are invited via email. Member list shows name, email, role, join date.

**Adaptation:**
- Extend with SSO-provisioned users (from IdP) alongside manually invited users
- Add SCIM sync indicator (synced vs. local)
- Richer RBAC matrix instead of simple role dropdown
- Multiple tenants per deployment (Dify has single workspace)

### Pattern 2: Dify Model Provider Credentials

**Source:** Dify stores provider credentials with per-workspace isolation in the database.

**Adaptation:** SSO credentials (Client Secret, LDAP Bind Password) are **never** stored in the database. Instead, stored in HashiCorp Vault at structured paths:
- OIDC: `archon/tenants/{tenant_id}/sso/oidc/client_secret`
- LDAP: `archon/tenants/{tenant_id}/sso/ldap/bind_password`
- SAML certificates: `archon/tenants/{tenant_id}/sso/saml/certificate`

The `SecretsManager` class in `backend/app/secrets/manager.py` handles all Vault interactions. API responses replace secret values with `"********"` masked strings.

---

## Backend Deliverables

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/tenants/{id}/sso` | Create SSO configuration for tenant |
| `GET` | `/api/v1/tenants/{id}/sso` | List SSO configurations for tenant |
| `GET` | `/api/v1/tenants/{id}/sso/{sso_id}` | Get SSO config detail (secrets masked) |
| `PUT` | `/api/v1/tenants/{id}/sso/{sso_id}` | Update SSO configuration |
| `DELETE` | `/api/v1/tenants/{id}/sso/{sso_id}` | Delete SSO configuration |
| `POST` | `/api/v1/tenants/{id}/sso/{sso_id}/test` | Test SSO connection |
| `GET` | `/api/v1/tenants/{id}/usage` | Tenant usage stats (agents, executions, storage) |
| `GET` | `/api/v1/tenants/{id}/members` | List tenant members with roles |
| `GET` | `/api/v1/rbac/matrix` | RBAC permission matrix (all roles × resources × actions) |
| `POST` | `/api/v1/rbac/roles` | Create custom role with permissions |
| `PUT` | `/api/v1/rbac/roles/{id}` | Update custom role permissions |
| `DELETE` | `/api/v1/rbac/roles/{id}` | Delete custom role |
| `POST` | `/api/v1/users/{id}/impersonate` | Start impersonation session |

All endpoints return envelope format: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`.

All endpoints require JWT auth. All queries scoped to `tenant_id`. All mutations produce `AuditLog` entries. Secret values in responses are masked as `"********"`.

---

## Frontend Deliverables

| File | Action | Description |
|------|--------|-------------|
| `frontend/src/pages/SSOConfigPage.tsx` | **CREATE** | SSO configuration page with OIDC/SAML/LDAP tabs |
| `frontend/src/pages/TenantsPage.tsx` | **MODIFY** | Add tenant detail view with tabbed layout |
| `frontend/src/components/sso/OIDCForm.tsx` | **CREATE** | OIDC configuration form |
| `frontend/src/components/sso/SAMLForm.tsx` | **CREATE** | SAML configuration form with metadata upload |
| `frontend/src/components/sso/LDAPForm.tsx` | **CREATE** | LDAP/AD configuration form |
| `frontend/src/components/sso/ClaimMapper.tsx` | **CREATE** | Visual row-based claim/attribute mapper |
| `frontend/src/components/sso/TestConnectionButton.tsx` | **CREATE** | Test connection with success/error feedback |
| `frontend/src/components/sso/IdPList.tsx` | **CREATE** | Table of configured identity providers |
| `frontend/src/components/tenants/TenantDetail.tsx` | **CREATE** | Tabbed detail page (General, IdP, Usage, Members, Billing) |
| `frontend/src/components/tenants/UsageStats.tsx` | **CREATE** | Usage bars (agents, executions, storage) |
| `frontend/src/components/tenants/MemberTable.tsx` | **CREATE** | Tenant members with roles and activity |
| `frontend/src/components/rbac/RBACMatrix.tsx` | **CREATE** | Permission matrix visualization |
| `frontend/src/components/rbac/CustomRoleForm.tsx` | **CREATE** | Create/edit custom role form |
| `frontend/src/api/tenancy.ts` | **MODIFY** | Add SSO, usage, members, RBAC endpoints |

All components must support dark/light mode via Tailwind classes.

---

## Integration Points

- **Keycloak:** OIDC configuration connects to Keycloak as the primary IdP. The "Test Connection" feature validates against a real Keycloak instance.
- **SAML Service:** `backend/app/services/saml_service.py` handles SAML metadata parsing and assertion validation — reuse for SAML config test.
- **SCIM Service:** `backend/app/services/scim_service.py` handles user provisioning from IdP — SSO config page shows SCIM endpoint URL for each IdP.
- **SecretsManager:** All SSO credentials stored in Vault. Use `SecretsManager.set_secret()` and `SecretsManager.get_secret()` for credential lifecycle.
- **Audit Logs:** SSO configuration changes, impersonation sessions, role changes all produce `AuditLog` entries.
- **Auth Routes:** `backend/app/routes/auth_routes.py` already handles OIDC/SAML login flows — SSO config feeds the parameters used by these routes.
- **Sidebar Navigation:** Add "SSO & Identity" entry under Settings section.

---

## Acceptance Criteria

1. **PASS/FAIL:** SSO configuration page exists and contains an OIDC form with Discovery URL, Client ID, and Client Secret fields.
2. **PASS/FAIL:** SAML configuration form supports metadata URL input or XML file upload, with attribute mapping.
3. **PASS/FAIL:** "Test Connection" button validates IdP configuration and shows success/error result.
4. **PASS/FAIL:** Claim/attribute mapping uses a visual row-based mapper (`[IdP claim] → [Archon field]`), not raw JSON textarea.
5. **PASS/FAIL:** Tenant detail page shows Usage, Members, and IdP Configuration in separate tabs.
6. **PASS/FAIL:** RBAC matrix visualization displays roles (columns) × resources (rows) × actions (CRUD checkboxes).
7. **PASS/FAIL:** Client Secret and LDAP Bind Password are stored in Vault via SecretsManager — never in the database or in plain text API responses.
8. **PASS/FAIL:** At least one SSO flow (Keycloak OIDC) works end-to-end: configure → test → login.

---

## Files to Read Before Starting

- `backend/app/routes/tenancy.py` — Existing tenancy route structure
- `backend/app/routes/tenants.py` — Existing tenant CRUD
- `backend/app/routes/auth_routes.py` — Existing OIDC/SAML auth flows
- `backend/app/routes/saml.py` — SAML endpoint implementation
- `backend/app/routes/scim.py` — SCIM provisioning endpoints
- `backend/app/services/tenant_service.py` — Existing tenant business logic
- `backend/app/services/saml_service.py` — SAML metadata parsing
- `backend/app/models/tenancy.py` — Existing tenancy models
- `frontend/src/pages/TenantsPage.tsx` — Current tenant UI to extend
- `frontend/src/pages/LoginPage.tsx` — Current login flow
- `frontend/src/api/tenancy.ts` — Current API client
- `backend/app/secrets/manager.py` — SecretsManager for Vault integration

---

## Files to Create / Modify

| File | Action | Notes |
|------|--------|-------|
| `backend/app/routes/tenancy.py` | MODIFY | Add SSO config CRUD, test connection, usage endpoints |
| `backend/app/services/tenant_service.py` | MODIFY | Add SSO config logic, usage stats, RBAC matrix |
| `frontend/src/pages/SSOConfigPage.tsx` | CREATE | SSO configuration with OIDC/SAML/LDAP forms |
| `frontend/src/pages/TenantsPage.tsx` | MODIFY | Add tenant detail with tabbed layout |
| `frontend/src/api/tenancy.ts` | MODIFY | Add SSO, usage, RBAC API methods |
| `frontend/src/components/sso/OIDCForm.tsx` | CREATE | OIDC config form |
| `frontend/src/components/sso/SAMLForm.tsx` | CREATE | SAML config form |
| `frontend/src/components/sso/LDAPForm.tsx` | CREATE | LDAP config form |
| `frontend/src/components/sso/ClaimMapper.tsx` | CREATE | Visual claim mapper |
| `frontend/src/components/sso/TestConnectionButton.tsx` | CREATE | Test connection UI |
| `frontend/src/components/sso/IdPList.tsx` | CREATE | IdP list table |
| `frontend/src/components/tenants/TenantDetail.tsx` | CREATE | Tabbed tenant detail |
| `frontend/src/components/tenants/UsageStats.tsx` | CREATE | Usage dashboard |
| `frontend/src/components/tenants/MemberTable.tsx` | CREATE | Members table |
| `frontend/src/components/rbac/RBACMatrix.tsx` | CREATE | Permission matrix |
| `frontend/src/components/rbac/CustomRoleForm.tsx` | CREATE | Custom role creation |
| `frontend/src/App.tsx` or router config | MODIFY | Add SSO config route |
| `frontend/src/components/layout/Sidebar.tsx` | MODIFY | Add SSO & Identity nav link |

---

## Testing

```bash
# Run all tests
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q

# Run tenancy/auth-specific tests
cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ -k "tenant or auth or sso" --no-header -q

# Frontend type check
cd ~/Scripts/Archon/frontend && npx tsc --noEmit
```

Target: ≥80% test coverage for new code.

---

## Constraints

- Python 3.12, type hints, docstrings. Use `python3` not `python`.
- Always `PYTHONPATH=backend` for pytest.
- API envelope: `{"data": ..., "meta": {"request_id", "timestamp"}}`
- No raw JSON fields on any user-facing form.
- All credentials via SecretsManager, never in DB.
- Never use `password=value` directly — use dict unpacking.
- Do NOT read ROADMAP.md, INSTRUCTIONS.md, ARCHITECTURE.md.
- Tests must pass: `cd ~/Scripts/Archon && PYTHONPATH=backend python3 -m pytest tests/ --no-header -q`
