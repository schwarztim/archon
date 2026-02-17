# Agent-23: Multi-Tenant Platform, Billing & Enterprise Identity Federation

> **Phase**: 2 | **Dependencies**: Agent-01 (Core Backend), Agent-09 (Cost Engine), Agent-00 (Secrets Vault) | **Priority**: CRITICAL
> **Every tenant boundary must be airtight. Data leaks between tenants are existential.**

---

## Identity

You are Agent-23: the Multi-Tenant Platform, Billing & Enterprise Identity Federation Builder. You build the tenant isolation layer, per-tenant identity provider configuration, SCIM provisioning, usage metering, Stripe billing integration, internal chargeback system, and self-service onboarding that enables Archon to operate as a multi-tenant SaaS platform or as an enterprise internal platform with department-level cost attribution.

## Mission

Build a production-grade multi-tenancy and billing platform that:
1. Isolates tenants at the database, compute, network, and secrets level — zero cross-tenant data leakage
2. Enables each tenant to configure their own Identity Provider(s) (SAML 2.0, OIDC, LDAP) with multi-IdP support and failover
3. Provides SCIM 2.0 inbound provisioning per tenant for automated user/group lifecycle management
4. Gives each tenant an isolated Vault namespace for secrets management
5. Meters usage in real-time (executions, tokens, storage, API calls, connector calls, seats) with per-minute granularity
6. Integrates with Stripe for external SaaS billing (subscriptions, usage records, invoices, tax, Connect for marketplace)
7. Supports internal chargeback mode for enterprises (department cost attribution, budget allocation, ERP integration)
8. Implements self-service onboarding with branded URLs, custom branding, and tier management
9. Enforces tier-based limits with configurable hard/soft quotas and dunning workflows

## Requirements

### Per-Tenant Identity Provider (IdP) Configuration

**Supported IdP Protocols**
- **SAML 2.0**: Okta, Azure AD / Entra ID, OneLogin, PingFederate, ADFS, Google Workspace SAML, custom SAML IdPs
- **OIDC**: Auth0, Amazon Cognito, Keycloak, Okta (OIDC mode), Azure AD (OIDC mode), Google Identity Platform
- **LDAP/Active Directory**: Direct LDAP(S) bind with search-and-bind or direct-bind modes

**Multi-IdP Per Tenant**
- Each tenant can configure multiple IdPs (e.g., corporate employees via Azure AD SAML + contractors via Okta OIDC)
- IdP priority ordering: primary, secondary, tertiary
- IdP failover: if primary IdP is unreachable (health check fails), automatically route to secondary
- User-to-IdP routing: by email domain (e.g., `@acme.com` → Azure AD, `@contractor.io` → Okta)

**IdP Configuration Data Model**
```python
class TenantIdPConfig(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    name: str                                    # "Corporate Azure AD", "Contractor Okta"
    protocol: Literal["saml2", "oidc", "ldap"]
    priority: int = 0                            # Lower = higher priority
    is_active: bool = True
    is_default: bool = False
    email_domains: list[str]                     # ["acme.com", "acme.co.uk"]
    # SAML-specific
    saml_metadata_url: str | None                # Auto-fetch metadata
    saml_metadata_xml: str | None                # Manual metadata upload
    saml_entity_id: str | None
    saml_sso_url: str | None
    saml_slo_url: str | None
    saml_certificate: str | None                 # Stored in Vault, reference here
    saml_signing_algorithm: str = "RSA_SHA256"
    saml_attribute_mapping: dict = Field(default_factory=dict)
    # OIDC-specific
    oidc_discovery_url: str | None               # /.well-known/openid-configuration
    oidc_client_id: str | None
    oidc_client_secret_ref: str | None           # Vault path reference
    oidc_scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email"])
    oidc_claims_mapping: dict = Field(default_factory=dict)
    # LDAP-specific
    ldap_url: str | None                         # ldaps://ldap.acme.com:636
    ldap_bind_dn: str | None
    ldap_bind_password_ref: str | None           # Vault path reference
    ldap_base_dn: str | None
    ldap_user_search_filter: str = "(uid={username})"
    ldap_group_search_filter: str = "(member={dn})"
    ldap_attribute_mapping: dict = Field(default_factory=dict)
    # Health & failover
    health_check_url: str | None
    health_check_interval_seconds: int = 60
    last_health_check_at: datetime | None
    last_health_status: Literal["healthy", "degraded", "unreachable"] | None
    failover_to_idp_id: uuid.UUID | None         # FK to another TenantIdPConfig
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None
    created_by: uuid.UUID | None
```

**IdP Configuration UI**
- SAML metadata import: upload XML file or paste metadata URL (auto-fetch and parse)
- OIDC discovery URL: enter URL → auto-discover endpoints, issuer, JWKS URI
- LDAP connection test: verify bind credentials and search filter before saving
- Attribute mapping builder: visual drag-and-drop mapping (IdP attribute → Archon field)
- Test SSO button: initiate test authentication flow, show decoded assertions/claims

### SCIM 2.0 Provisioning Per Tenant

**Inbound SCIM Server (Per Tenant)**
- Each tenant gets a unique SCIM endpoint: `/scim/v2/tenants/{tenant_id}/Users`, `/scim/v2/tenants/{tenant_id}/Groups`
- SCIM bearer token per tenant (stored in Vault, rotatable)
- Full RFC 7644 compliance:
  ```
  GET    /scim/v2/tenants/{tid}/Users                # List/search users
  POST   /scim/v2/tenants/{tid}/Users                # Create user
  GET    /scim/v2/tenants/{tid}/Users/{id}            # Get user
  PUT    /scim/v2/tenants/{tid}/Users/{id}            # Replace user
  PATCH  /scim/v2/tenants/{tid}/Users/{id}            # Update user (JSON Patch)
  DELETE /scim/v2/tenants/{tid}/Users/{id}            # Deactivate user
  GET    /scim/v2/tenants/{tid}/Groups                # List groups
  POST   /scim/v2/tenants/{tid}/Groups                # Create group
  PATCH  /scim/v2/tenants/{tid}/Groups/{id}           # Update group membership
  POST   /scim/v2/tenants/{tid}/Bulk                  # Bulk operations
  GET    /scim/v2/tenants/{tid}/ServiceProviderConfig # SCIM capabilities
  GET    /scim/v2/tenants/{tid}/Schemas               # Schema discovery
  ```

**User/Group Sync Sources**
- Azure AD / Entra ID (enterprise application provisioning)
- Okta (SCIM integration)
- OneLogin (SCIM connector)
- Google Workspace Directory (SCIM + Directory API)

**Mapping Rules**
- IdP groups → Archon roles/workspaces (configurable per tenant):
  ```python
  class SCIMMappingRule(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      idp_config_id: uuid.UUID = Field(foreign_key="tenant_idp_configs.id")
      source_group_name: str          # "Engineering" (from IdP)
      target_role_id: uuid.UUID       # Maps to Archon role
      target_workspace_id: uuid.UUID | None  # Optional workspace scoping
      auto_create_workspace: bool = False
      is_active: bool = True
      created_at: datetime
  ```
- Conflict resolution: IdP is source of truth — local manual changes flagged, overwritten on next sync
- Deprovisioning modes (configurable per tenant):
  - **Immediate**: IdP deletes user → Archon deactivates immediately
  - **Grace period**: IdP deletes user → Archon marks for deactivation → 30 days grace → hard deactivate
  - **Soft deactivate**: Never hard-delete, only suspend (for compliance/audit retention)

### Vault Namespace Per Tenant

**Isolated Secrets Management**
- Each tenant gets an isolated Vault namespace (HashiCorp Vault Enterprise) or path-prefix (OSS Vault):
  ```
  # Enterprise Vault
  vault namespace create tenant/{tenant_id}
  
  # OSS Vault (path-prefix isolation)
  vault secrets enable -path=tenants/{tenant_id}/kv kv-v2
  ```
- Tenant-specific encryption keys (transit engine per tenant):
  ```
  vault write tenants/{tenant_id}/transit/keys/data-encryption type=aes256-gcm96
  ```
- Tenant admin can manage their own secrets via UI (list, create, rotate, delete) but CANNOT:
  - Access platform-level secrets
  - Access other tenant's namespaces
  - Modify Vault policies outside their namespace
- Cross-tenant secret sharing:
  - Explicitly opt-in (both tenants must approve)
  - Logged in both tenants' audit trails
  - Revocable by either party at any time
  - Implemented via shared Vault policies with read-only access

### Database Isolation

**Row-Level Security (RLS) — Default Mode**
- `tenant_id` column on EVERY table (enforced by SQLModel base class):
  ```python
  class TenantScopedModel(SQLModel):
      """Base class for all tenant-scoped models. Ensures tenant_id is always set."""
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True, nullable=False)
  ```
- PostgreSQL RLS policies applied via Alembic migration:
  ```sql
  -- Applied to EVERY tenant-scoped table
  ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON agents
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
  CREATE POLICY tenant_insert ON agents
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id')::uuid);
  ```
- Connection-level tenant context setting (set before every query):
  ```python
  async def set_tenant_context(session: AsyncSession, tenant_id: uuid.UUID):
      await session.execute(text(f"SET app.current_tenant_id = '{tenant_id}'"))
  ```
- Middleware enforces tenant context on every request:
  ```python
  class TenantContextMiddleware:
      async def __call__(self, request: Request, call_next):
          tenant_id = request.state.user.tenant_id
          async with get_session() as session:
              await set_tenant_context(session, tenant_id)
              request.state.db_session = session
              response = await call_next(request)
          return response
  ```

**Schema-Per-Tenant Mode (Enterprise Tier)**
- Optional full schema isolation for Enterprise customers:
  ```sql
  CREATE SCHEMA tenant_{tenant_id};
  SET search_path TO tenant_{tenant_id}, public;
  ```
- Dedicated connection pool per tenant schema
- Migration strategy: run Alembic migrations per schema
- Configurable per tenant: `Tenant.isolation_mode = "rls" | "schema"`

### Compute Isolation

**Namespace-Per-Tenant (Enterprise Tier)**
- Kubernetes namespace per Enterprise tenant:
  ```yaml
  apiVersion: v1
  kind: Namespace
  metadata:
    name: tenant-{tenant_id}
    labels:
      archon.io/tenant-id: "{tenant_id}"
      archon.io/tier: "enterprise"
  ```
- Resource quotas per namespace:
  ```yaml
  apiVersion: v1
  kind: ResourceQuota
  metadata:
    name: tenant-quota
    namespace: tenant-{tenant_id}
  spec:
    hard:
      requests.cpu: "4"
      requests.memory: "8Gi"
      limits.cpu: "8"
      limits.memory: "16Gi"
      pods: "20"
  ```
- Network policies: tenant A's pods CANNOT communicate with tenant B's pods:
  ```yaml
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: tenant-isolation
    namespace: tenant-{tenant_id}
  spec:
    podSelector: {}
    policyTypes: ["Ingress", "Egress"]
    ingress:
      - from:
        - namespaceSelector:
            matchLabels:
              archon.io/tenant-id: "{tenant_id}"
        - namespaceSelector:
            matchLabels:
              archon.io/system: "true"
    egress:
      - to:
        - namespaceSelector:
            matchLabels:
              archon.io/tenant-id: "{tenant_id}"
        - namespaceSelector:
            matchLabels:
              archon.io/system: "true"
  ```

**Shared Compute (Default — Free/Starter/Team Tiers)**
- All tenants share API pods; isolation at application layer (RLS + middleware)
- Rate limiting per tenant via Redis
- CPU/memory limits per tenant enforced at request level (timeout + memory cap per execution)

### Self-Service Onboarding

**Sign-Up Flow**
1. User submits email → verify email (token stored in Vault, 24h expiry)
2. Create organization (name, slug, industry)
3. Choose tier (Free, Starter, Team, Enterprise — see below)
4. Configure IdP (optional, required for Team/Enterprise) — or skip for email/password
5. Provision workspace (default workspace created automatically)
6. Invite team members (email invites with role assignment)
7. First agent creation wizard (guided experience)

**Organization Slugs & Branded URLs**
- Org slugs for branded access: `{org-slug}.archon.com`
- Slug validation: lowercase alphanumeric + hyphens, 3-63 characters, unique
- Custom branding per tenant:
  ```python
  class TenantBranding(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id", unique=True)
      logo_url: str | None
      favicon_url: str | None
      primary_color: str = "#0066FF"
      secondary_color: str = "#1A1A2E"
      login_page_title: str | None
      login_page_message: str | None
      email_from_name: str | None          # "Acme AI Platform"
      email_from_address: str | None       # "noreply@acme.com" (verified domain)
      custom_css: str | None               # Injected into login pages
      email_templates: dict = Field(default_factory=dict)  # Custom email templates
  ```

### Tier Management

**Tier Definitions**
```python
class TenantTier(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str                               # "free", "starter", "team", "enterprise"
    display_name: str                       # "Free", "Starter", "Team", "Enterprise"
    # Limits
    max_executions_per_month: int | None    # None = unlimited
    max_agents: int | None
    max_seats: int | None
    max_storage_bytes: int | None
    max_api_calls_per_month: int | None
    max_connectors: int | None
    max_workspaces: int | None
    # Features
    sso_enabled: bool = False
    scim_enabled: bool = False
    custom_idp_enabled: bool = False
    audit_log_export: bool = False
    dedicated_compute: bool = False
    data_residency: bool = False
    sla_enabled: bool = False
    on_prem_option: bool = False
    custom_branding: bool = False
    # Pricing
    base_price_cents: int                   # Monthly base price in cents
    per_execution_price_cents: int = 0      # Overage price per execution
    per_seat_price_cents: int = 0           # Per-seat pricing
    per_token_price_millicents: int = 0     # Per 1K tokens
    stripe_price_id: str | None             # Stripe Price ID for subscription
    stripe_metered_price_ids: dict = Field(default_factory=dict)  # {"executions": "price_xxx"}
    is_active: bool = True
    sort_order: int = 0
```

| Tier | Exec/Mo | Agents | Seats | Storage | SSO | SCIM | Dedicated | SLA | Price |
|------|---------|--------|-------|---------|-----|------|-----------|-----|-------|
| Free | 100 | 5 | 3 | 100MB | ❌ | ❌ | ❌ | ❌ | $0 |
| Starter | 1,000 | 25 | 10 | 1GB | ❌ | ❌ | ❌ | ❌ | $49/mo |
| Team | 10,000 | 100 | 50 | 10GB | ✅ | ✅ | ❌ | ❌ | $199/mo |
| Enterprise | Custom | Custom | Custom | Custom | ✅ | ✅ | ✅ | ✅ | Custom |

- **Tier upgrade**: takes effect immediately, prorated billing
- **Tier downgrade**: takes effect at end of current billing period, data retained within new limits (excess data archived, accessible for 90 days)

### Usage Metering

**Real-Time Counters**
- Metered dimensions:
  - Executions (agent runs, sub-agent invocations)
  - Tokens (input + output, by model: GPT-4, Claude, Llama, etc.)
  - Storage (documents bytes, embedding vectors count, conversation history bytes)
  - API calls (per connector: Salesforce, Jira, Slack, etc.)
  - Connector calls (external tool invocations)
  - Seats (active users in billing period)

**Usage Record Data Model**
```python
class UsageRecord(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    dimension: Literal[
        "execution", "token_input", "token_output", "storage_bytes",
        "api_call", "connector_call", "seat"
    ]
    quantity: int
    model_id: str | None               # "gpt-4", "claude-3-opus" — for token metering
    connector_id: str | None            # "salesforce", "jira" — for connector metering
    agent_id: uuid.UUID | None
    execution_id: uuid.UUID | None
    user_id: uuid.UUID | None
    workspace_id: uuid.UUID | None
    recorded_at: datetime = Field(default_factory=datetime.utcnow)
    billing_period: str                 # "2025-01" (YYYY-MM)
    reported_to_stripe: bool = False
    stripe_usage_record_id: str | None
```

**Time-Series Storage**
- Per-minute granularity stored in TimescaleDB hypertable (or PostgreSQL with partitioning fallback)
- Automatic aggregation: minute → hour → day → month
- Retention: raw (90 days), hourly (1 year), daily (3 years), monthly (forever)
- Query API for analytics dashboards: time-range, group-by dimension, tenant, workspace, agent

### Billing (Stripe Integration)

**Stripe Billing**
- Stripe Customer created per tenant on sign-up
- Stripe Subscription for base tier pricing
- Stripe Usage Records for metered billing (reported hourly):
  ```python
  async def report_usage_to_stripe(tenant: Tenant, period: str):
      usage = await aggregate_usage(tenant.id, period)
      for dimension, quantity in usage.items():
          stripe.SubscriptionItem.create_usage_record(
              tenant.stripe_subscription_item_ids[dimension],
              quantity=quantity,
              timestamp=int(datetime.utcnow().timestamp()),
              action="set"  # Idempotent — set absolute value
          )
  ```
- Stripe Invoices for Enterprise custom invoicing
- Stripe Tax for automatic tax calculation (VAT, sales tax by jurisdiction)
- Stripe Connect for marketplace payouts (Agent-22 marketplace sellers receive payouts)

**Webhook Handler**
```python
STRIPE_WEBHOOK_EVENTS = [
    "payment_intent.succeeded",
    "payment_intent.payment_failed",
    "invoice.payment_failed",
    "invoice.paid",
    "invoice.finalized",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.trial_will_end",
    "customer.updated",
    "charge.refunded",
    "charge.dispute.created",
    "checkout.session.completed",
]
```

**Dunning (Failed Payment Recovery)**
1. Payment fails → send email notification to billing contact
2. Retry #1: 3 days later (automatic Stripe Smart Retries)
3. Retry #2: 7 days later
4. Retry #3: 14 days later
5. Grace period: 7 days after last retry — tenant sees "billing issue" banner, features still active
6. Suspension: tenant suspended (read-only access, no new executions)
7. Data retention: 90 days in suspended state
8. Deletion: after 90 days, data purged (with 30-day advance notice email)

### Internal Chargeback Mode

**For Enterprises Using Archon Internally (No Stripe)**
- No external payment processing — costs attributed to internal departments/cost centers
- Department-level cost attribution:
  ```python
  class ChargebackEntry(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      department_id: str                    # "engineering", "marketing", "finance"
      cost_center: str                      # "CC-4501"
      billing_period: str                   # "2025-01"
      dimension: str                        # "executions", "tokens", "storage"
      quantity: int
      unit_cost_cents: int                  # Internal transfer price
      total_cost_cents: int
      currency: str = "USD"
      approved_by: uuid.UUID | None
      approved_at: datetime | None
      exported_at: datetime | None
      erp_reference: str | None             # SAP/Oracle posting reference
      created_at: datetime
  ```
- Budget allocation by IT finance:
  ```python
  class DepartmentBudget(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      department_id: str
      cost_center: str
      fiscal_year: int
      fiscal_quarter: int | None            # Null = annual budget
      budget_cents: int
      spent_cents: int = 0
      alert_threshold_pct: int = 80         # Alert at 80% spend
      hard_cap: bool = False                # Block executions at 100%
      created_at: datetime
      updated_at: datetime | None
  ```
- Monthly chargeback reports:
  - PDF report with executive summary, per-department breakdown, trend charts
  - CSV export for finance systems
  - Scheduled delivery (email to finance distribution list on 3rd business day of month)
- ERP integration:
  - SAP: RFC/BAPI integration for cost center posting (IDoc format)
  - Oracle ERP Cloud: REST API integration for journal entries
  - Generic: CSV/API webhook for custom ERP systems

### Core Data Models

**Tenant Model**
```python
class Tenant(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255)
    slug: str = Field(unique=True, index=True, max_length=63)
    display_name: str
    industry: str | None
    tier_id: uuid.UUID = Field(foreign_key="tenant_tiers.id")
    status: Literal["trial", "active", "suspended", "cancelled", "deleted"] = "trial"
    billing_mode: Literal["stripe", "chargeback", "free"] = "free"
    isolation_mode: Literal["rls", "schema"] = "rls"
    # Stripe references
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_subscription_item_ids: dict = Field(default_factory=dict)
    # Vault
    vault_namespace: str | None             # "tenants/{tenant_id}"
    vault_transit_key: str | None           # Encryption key name
    # Compute
    k8s_namespace: str | None               # For Enterprise tier
    # Branding
    custom_domain: str | None               # "ai.acme.com" (verified via DNS)
    # Limits (overrides tier defaults)
    custom_limits: dict = Field(default_factory=dict)
    # Metadata
    trial_ends_at: datetime | None
    billing_email: str | None
    technical_contact_email: str | None
    data_residency_region: str | None       # "us-east-1", "eu-west-1"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime | None
    deleted_at: datetime | None
    created_by: uuid.UUID | None
    metadata: dict = Field(default_factory=dict)
```

**Subscription Model**
```python
class Subscription(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    tier_id: uuid.UUID = Field(foreign_key="tenant_tiers.id")
    status: Literal["trialing", "active", "past_due", "suspended", "cancelled"] = "trialing"
    current_period_start: datetime
    current_period_end: datetime
    trial_end: datetime | None
    cancel_at_period_end: bool = False
    cancelled_at: datetime | None
    stripe_subscription_id: str | None
    # Billing
    billing_interval: Literal["monthly", "annual"] = "monthly"
    base_amount_cents: int
    discount_pct: int = 0
    # Dunning
    failed_payment_count: int = 0
    last_payment_attempt_at: datetime | None
    grace_period_ends_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
```

**Invoice Model**
```python
class Invoice(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    subscription_id: uuid.UUID = Field(foreign_key="subscriptions.id")
    invoice_number: str = Field(unique=True)   # "INV-2025-000001"
    status: Literal["draft", "finalized", "paid", "void", "uncollectible"] = "draft"
    billing_period: str                         # "2025-01"
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    currency: str = "USD"
    stripe_invoice_id: str | None
    stripe_invoice_url: str | None
    pdf_url: str | None
    line_items: list[dict] = Field(default_factory=list)
    due_date: datetime
    paid_at: datetime | None
    created_at: datetime
```

## Output Structure

```
backend/app/tenants/
├── __init__.py
├── router.py                  # Tenant management API endpoints
├── models.py                  # Tenant, TenantIdPConfig, TenantBranding, TenantTier
├── service.py                 # Tenant CRUD, lifecycle, provisioning
├── middleware.py               # Tenant context injection, RLS setup
├── isolation.py               # Database isolation (RLS + schema modes)
├── compute_isolation.py       # K8s namespace provisioning, resource quotas
├── onboarding.py              # Self-service signup flow
├── idp_config.py              # Per-tenant IdP configuration service
├── idp_health.py              # IdP health checking and failover
├── scim_per_tenant.py         # Per-tenant SCIM 2.0 provisioning
├── scim_mapping.py            # SCIM group-to-role mapping rules
├── vault_namespace.py         # Per-tenant Vault namespace management
├── branding.py                # Custom branding service
└── tier_service.py            # Tier management, upgrade/downgrade

backend/app/billing/
├── __init__.py
├── router.py                  # Billing API endpoints
├── models.py                  # Subscription, Invoice, UsageRecord, ChargebackEntry
├── metering.py                # Real-time usage metering and aggregation
├── metering_timeseries.py     # TimescaleDB hypertable management
├── stripe_integration.py      # Stripe Billing, Usage Records, Connect
├── stripe_webhooks.py         # Stripe webhook handler (all events)
├── stripe_tax.py              # Stripe Tax integration
├── dunning.py                 # Failed payment recovery workflow
├── chargeback.py              # Internal chargeback mode
├── chargeback_reports.py      # PDF + CSV report generation
├── erp_integration.py         # SAP/Oracle ERP cost posting
├── quota_enforcer.py          # Tier limit enforcement (hard/soft)
├── budget_manager.py          # Department budget allocation
└── invoice_service.py         # Invoice generation and management

frontend/src/pages/tenant/
├── TenantOnboarding.tsx        # Multi-step signup wizard
├── TenantDashboard.tsx         # Tenant admin overview
├── IdPConfiguration.tsx        # IdP setup UI (SAML metadata import, OIDC discovery)
├── SCIMConfiguration.tsx       # SCIM provisioning setup per tenant
├── UsageOverview.tsx           # Real-time usage dashboard
├── UsageAnalytics.tsx          # Historical usage charts and trends
├── BillingSettings.tsx         # Payment methods, invoices, subscription
├── TierManagement.tsx          # Tier selection, upgrade/downgrade
├── BrandingSettings.tsx        # Custom logo, colors, email templates
├── ChargebackReports.tsx       # Internal chargeback dashboard
├── BudgetAllocation.tsx        # Department budget management
├── QuotaDashboard.tsx          # Real-time quota usage and alerts
└── VaultSecrets.tsx            # Tenant-scoped secrets management UI

tests/
├── test_tenant_isolation_rls.py    # RLS enforcement tests
├── test_tenant_isolation_schema.py # Schema-per-tenant tests
├── test_compute_isolation.py       # K8s namespace isolation tests
├── test_idp_saml.py                # SAML IdP configuration tests
├── test_idp_oidc.py                # OIDC IdP configuration tests
├── test_idp_ldap.py                # LDAP IdP configuration tests
├── test_idp_failover.py            # Multi-IdP failover tests
├── test_scim_per_tenant.py         # Per-tenant SCIM provisioning
├── test_scim_mapping.py            # Group-to-role mapping tests
├── test_vault_namespace.py         # Vault isolation tests
├── test_onboarding.py              # Self-service signup flow
├── test_tier_management.py         # Tier upgrade/downgrade
├── test_metering.py                # Usage metering accuracy
├── test_stripe_billing.py          # Stripe integration tests
├── test_stripe_webhooks.py         # Webhook handler tests
├── test_dunning.py                 # Failed payment recovery
├── test_chargeback.py              # Internal chargeback mode
├── test_erp_integration.py         # ERP cost posting tests
├── test_quota_enforcement.py       # Hard/soft limit enforcement
├── test_budget_allocation.py       # Department budget tests
└── test_branding.py                # Custom branding tests
```

## API Endpoints (Complete)

```
# Tenant Management
POST   /api/v1/tenants                              # Create tenant (signup)
GET    /api/v1/tenants                              # List tenants (platform admin)
GET    /api/v1/tenants/{id}                         # Get tenant details
PUT    /api/v1/tenants/{id}                         # Update tenant
PATCH  /api/v1/tenants/{id}/status                  # Activate/suspend/cancel
DELETE /api/v1/tenants/{id}                         # Soft-delete tenant
GET    /api/v1/tenants/{id}/settings                # Get tenant settings
PUT    /api/v1/tenants/{id}/settings                # Update tenant settings

# Onboarding
POST   /api/v1/onboarding/signup                    # Start signup flow
POST   /api/v1/onboarding/verify-email              # Verify email token
POST   /api/v1/onboarding/create-org                # Create organization
POST   /api/v1/onboarding/select-tier               # Select tier
POST   /api/v1/onboarding/configure-idp             # Configure IdP (optional)
POST   /api/v1/onboarding/provision                 # Provision workspace
POST   /api/v1/onboarding/invite-team               # Invite team members

# IdP Configuration
GET    /api/v1/tenants/{id}/idps                    # List tenant IdPs
POST   /api/v1/tenants/{id}/idps                    # Add IdP configuration
GET    /api/v1/tenants/{id}/idps/{idp_id}           # Get IdP config
PUT    /api/v1/tenants/{id}/idps/{idp_id}           # Update IdP config
DELETE /api/v1/tenants/{id}/idps/{idp_id}           # Remove IdP config
POST   /api/v1/tenants/{id}/idps/{idp_id}/test      # Test IdP connection
GET    /api/v1/tenants/{id}/idps/{idp_id}/health    # Check IdP health
POST   /api/v1/tenants/{id}/idps/import-saml        # Import SAML metadata
POST   /api/v1/tenants/{id}/idps/discover-oidc      # OIDC discovery from URL

# SCIM Per Tenant
GET    /scim/v2/tenants/{tid}/Users                 # List/search users
POST   /scim/v2/tenants/{tid}/Users                 # Create user
GET    /scim/v2/tenants/{tid}/Users/{uid}            # Get user
PUT    /scim/v2/tenants/{tid}/Users/{uid}            # Replace user
PATCH  /scim/v2/tenants/{tid}/Users/{uid}            # Update user
DELETE /scim/v2/tenants/{tid}/Users/{uid}            # Deactivate user
GET    /scim/v2/tenants/{tid}/Groups                # List groups
POST   /scim/v2/tenants/{tid}/Groups                # Create group
PATCH  /scim/v2/tenants/{tid}/Groups/{gid}           # Update group
POST   /scim/v2/tenants/{tid}/Bulk                  # Bulk operations
GET    /scim/v2/tenants/{tid}/ServiceProviderConfig  # SCIM capabilities
GET    /scim/v2/tenants/{tid}/Schemas               # Schema discovery

# SCIM Mapping Rules
GET    /api/v1/tenants/{id}/scim-mappings            # List mapping rules
POST   /api/v1/tenants/{id}/scim-mappings            # Create mapping rule
PUT    /api/v1/tenants/{id}/scim-mappings/{mid}       # Update mapping rule
DELETE /api/v1/tenants/{id}/scim-mappings/{mid}       # Delete mapping rule
POST   /api/v1/tenants/{id}/scim-mappings/sync       # Force sync from IdP

# Vault (Per Tenant)
GET    /api/v1/tenants/{id}/secrets                  # List tenant secrets
POST   /api/v1/tenants/{id}/secrets                  # Create tenant secret
GET    /api/v1/tenants/{id}/secrets/{sid}             # Get secret metadata
PUT    /api/v1/tenants/{id}/secrets/{sid}             # Update secret
DELETE /api/v1/tenants/{id}/secrets/{sid}             # Delete secret
POST   /api/v1/tenants/{id}/secrets/{sid}/rotate      # Rotate secret

# Branding
GET    /api/v1/tenants/{id}/branding                 # Get branding config
PUT    /api/v1/tenants/{id}/branding                 # Update branding
POST   /api/v1/tenants/{id}/branding/logo            # Upload logo
POST   /api/v1/tenants/{id}/branding/preview         # Preview branding

# Tier Management
GET    /api/v1/tiers                                 # List available tiers
GET    /api/v1/tiers/{id}                            # Get tier details
POST   /api/v1/tenants/{id}/upgrade                  # Upgrade tier
POST   /api/v1/tenants/{id}/downgrade                # Downgrade tier (end of period)

# Usage Metering
GET    /api/v1/tenants/{id}/usage                    # Get current period usage
GET    /api/v1/tenants/{id}/usage/history             # Historical usage data
GET    /api/v1/tenants/{id}/usage/breakdown           # Usage by dimension/agent/user
GET    /api/v1/tenants/{id}/usage/realtime            # Real-time usage counters
GET    /api/v1/tenants/{id}/quotas                   # Current quota status

# Billing (Stripe Mode)
GET    /api/v1/tenants/{id}/billing                  # Billing overview
POST   /api/v1/tenants/{id}/billing/payment-method    # Add payment method
GET    /api/v1/tenants/{id}/billing/invoices          # List invoices
GET    /api/v1/tenants/{id}/billing/invoices/{iid}     # Get invoice details
GET    /api/v1/tenants/{id}/billing/invoices/{iid}/pdf  # Download invoice PDF
POST   /api/v1/tenants/{id}/billing/portal            # Create Stripe billing portal session
POST   /api/v1/webhooks/stripe                       # Stripe webhook handler

# Chargeback (Internal Mode)
GET    /api/v1/tenants/{id}/chargeback                # Chargeback overview
GET    /api/v1/tenants/{id}/chargeback/reports         # List chargeback reports
GET    /api/v1/tenants/{id}/chargeback/reports/{rid}    # Get report details
GET    /api/v1/tenants/{id}/chargeback/reports/{rid}/pdf  # Download PDF
GET    /api/v1/tenants/{id}/chargeback/reports/{rid}/csv  # Download CSV
POST   /api/v1/tenants/{id}/chargeback/export-erp      # Export to ERP

# Budget Management (Chargeback Mode)
GET    /api/v1/tenants/{id}/budgets                   # List department budgets
POST   /api/v1/tenants/{id}/budgets                   # Create budget allocation
PUT    /api/v1/tenants/{id}/budgets/{bid}              # Update budget
GET    /api/v1/tenants/{id}/budgets/{bid}/status       # Budget spend status

# Health
GET    /health                                        # Liveness probe
GET    /ready                                         # Readiness probe (checks DB, Redis, Vault, Stripe)
```

## Verify Commands

```bash
# Tenant models importable
cd ~/Scripts/Archon && python -c "from backend.app.tenants.models import Tenant, TenantIdPConfig, TenantTier, TenantBranding; print('Tenant models OK')"

# Billing models importable
cd ~/Scripts/Archon && python -c "from backend.app.billing.models import Subscription, UsageRecord, Invoice, ChargebackEntry, DepartmentBudget; print('Billing models OK')"

# SCIM per-tenant module importable
cd ~/Scripts/Archon && python -c "from backend.app.tenants.scim_per_tenant import TenantSCIMService; print('SCIM OK')"

# IdP configuration service importable
cd ~/Scripts/Archon && python -c "from backend.app.tenants.idp_config import IdPConfigService; print('IdP OK')"

# Vault namespace service importable
cd ~/Scripts/Archon && python -c "from backend.app.tenants.vault_namespace import TenantVaultManager; print('Vault namespace OK')"

# Stripe integration importable
cd ~/Scripts/Archon && python -c "from backend.app.billing.stripe_integration import StripeClient; from backend.app.billing.stripe_webhooks import handle_stripe_webhook; print('Stripe OK')"

# Chargeback service importable
cd ~/Scripts/Archon && python -c "from backend.app.billing.chargeback import ChargebackService; from backend.app.billing.erp_integration import ERPExporter; print('Chargeback OK')"

# Metering service importable
cd ~/Scripts/Archon && python -c "from backend.app.billing.metering import UsageMeter; from backend.app.billing.quota_enforcer import QuotaEnforcer; print('Metering OK')"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_multi_tenant/ tests/test_billing/ --tb=short -q

# RLS isolation verified
cd ~/Scripts/Archon && python -c "from backend.app.tenants.isolation import RLSManager; print('RLS OK')"

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'stripe_key\s*=\s*"sk_' --include='*.py' backend/ || echo 'FAIL: hardcoded Stripe keys found'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Tenant isolation via RLS on every table with `tenant_id` column enforced by base model
- [ ] Schema-per-tenant mode available for Enterprise tier tenants
- [ ] Compute isolation: K8s namespace per Enterprise tenant with resource quotas and network policies
- [ ] Per-tenant IdP configuration: SAML 2.0, OIDC, LDAP all functional
- [ ] Multi-IdP per tenant with email-domain routing and failover
- [ ] IdP health checking with automatic failover to secondary IdP
- [ ] SAML metadata import and OIDC discovery URL auto-configuration working
- [ ] Per-tenant SCIM 2.0 provisioning endpoints functional
- [ ] SCIM group-to-role mapping rules configurable and applied on sync
- [ ] SCIM deprovisioning modes (immediate, grace period, soft) all working
- [ ] Per-tenant Vault namespace with isolated encryption keys
- [ ] Cross-tenant secret sharing opt-in, logged, and revocable
- [ ] Self-service onboarding flow (signup → verify → org → tier → IdP → workspace → invite)
- [ ] Org slugs and branded URLs working (`{slug}.archon.com`)
- [ ] Custom branding (logo, colors, email templates) applied per tenant
- [ ] All four tiers (Free, Starter, Team, Enterprise) enforced correctly
- [ ] Tier upgrade (immediate, prorated) and downgrade (end of period) working
- [ ] Real-time usage metering for all dimensions (executions, tokens, storage, API, connector, seats)
- [ ] Time-series storage with per-minute granularity and automatic aggregation
- [ ] Stripe Billing integration (subscriptions + usage records + invoices + tax)
- [ ] Stripe webhook handler processes all listed events correctly
- [ ] Stripe Connect marketplace payouts functional
- [ ] Dunning workflow (retry → grace period → suspension → data retention → deletion)
- [ ] Internal chargeback mode with department-level cost attribution
- [ ] Budget allocation and enforcement (soft alerts + optional hard cap)
- [ ] Monthly chargeback reports (PDF + CSV) generated and delivered
- [ ] ERP integration (SAP/Oracle) for cost center posting
- [ ] Quota enforcement with configurable hard/soft limits
- [ ] All API endpoints match `contracts/openapi.yaml`
- [ ] All tests pass with >80% coverage
- [ ] Zero plaintext secrets in logs, env vars, or source code
