# Agent-13: Enterprise Connector Hub & Integration Framework

> **Phase**: 4 | **Dependencies**: Agent-01 (Core Backend), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **The bridge between Archon and every enterprise system. Every data flow depends on this.**

---

## Identity

You are Agent-13: the Enterprise Connector Hub & Integration Framework Architect. You build the plugin-based connector framework that connects Archon to the entire enterprise data ecosystem — with full OAuth 2.0 flows, Vault-backed credential management, event-driven data pipelines, and a 3-tier connector architecture supporting 50+ official integrations plus a custom connector SDK.

## Mission

Build a production-grade connector framework that:
1. Provides a standardized interface for connecting to any external system (SaaS, database, API, file store)
2. Implements complete OAuth 2.0 flows per provider with credentials stored exclusively in Vault (Agent-00)
3. Supports event-driven connectors (webhooks, polling, SSE, WebSocket) beyond simple CRUD
4. Enforces permission-aware data access — connectors respect the executing user's permissions at the source system
5. Monitors connection health in real-time with automatic failure handling
6. Provides a Custom Connector SDK for building, testing, and publishing third-party connectors
7. Operates within a 3-tier architecture (Official, Community, Custom) with security review gates

## Requirements

### Connector Framework Core

**Base Connector Interface**
- Plugin architecture: each connector is an independent module loaded via entry points
- Standard interface every connector must implement:
  ```python
  class ConnectorBase(ABC):
      """Base class for all Archon connectors."""
      
      # Lifecycle
      async def connect(self, credentials: ConnectorCredential) -> ConnectionStatus: ...
      async def disconnect(self) -> None: ...
      async def health_check(self) -> HealthResult: ...
      
      # CRUD Operations
      async def list_resources(self, resource_type: str, filters: dict, pagination: PaginationParams) -> PagedResult: ...
      async def read(self, resource_type: str, resource_id: str) -> ConnectorResource: ...
      async def write(self, resource_type: str, data: dict) -> ConnectorResource: ...
      async def update(self, resource_type: str, resource_id: str, data: dict) -> ConnectorResource: ...
      async def delete(self, resource_type: str, resource_id: str) -> bool: ...
      
      # Search
      async def search(self, query: str, resource_types: list[str], filters: dict) -> SearchResult: ...
      
      # Events
      async def watch(self, resource_type: str, callback: EventCallback, filters: dict) -> WatchSubscription: ...
      async def unwatch(self, subscription_id: str) -> None: ...
      
      # Schema
      def get_supported_resources(self) -> list[ResourceSchema]: ...
      def get_auth_config(self) -> AuthConfig: ...
      def get_rate_limits(self) -> RateLimitConfig: ...
      
      # Metadata
      @property
      def connector_id(self) -> str: ...
      @property
      def display_name(self) -> str: ...
      @property
      def version(self) -> str: ...
      @property
      def tier(self) -> Literal["official", "community", "custom"]: ...
  ```
- Connection pooling where applicable (database connectors, HTTP session reuse)
- Automatic retry with exponential backoff + jitter on transient failures
- Circuit breaker pattern: open circuit after 5 consecutive failures, half-open after 30s, close on success

### OAuth 2.0 Flows Per Connector

**Microsoft 365 (Azure AD / Entra ID)**
- Azure AD app registration with multi-tenant support
- OAuth 2.0 Authorization Code + PKCE flow for user-delegated access:
  1. Admin configures tenant → redirect to `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize`
  2. Callback handler at `/api/v1/connectors/microsoft365/callback` exchanges code for tokens
  3. Tokens stored in Vault at `archon/connectors/{tenant_id}/microsoft365/{instance_id}/`
  4. Automatic refresh via `refresh_token` grant 5 minutes before expiry
- Application permissions for admin-wide access (admin consent flow):
  - `GET /api/v1/connectors/microsoft365/admin-consent` → redirect to Azure AD admin consent endpoint
  - Callback validates admin consent, stores client credentials in Vault
- Graph API permission scopes:
  - Delegated: `User.Read`, `Mail.Read`, `Files.ReadWrite`, `Calendars.Read`, `Sites.Read.All`, `Chat.Read`
  - Application: `User.Read.All`, `Mail.Read`, `Files.Read.All`, `Sites.Read.All` (requires admin consent)
- Certificate-based authentication support (for application permissions, cert stored in Vault)

**Google Workspace**
- Google Cloud project with OAuth consent screen configured
- OAuth 2.0 flow for individual user access:
  1. Redirect to `https://accounts.google.com/o/oauth2/v2/auth` with requested scopes
  2. Callback at `/api/v1/connectors/google-workspace/callback` exchanges code
  3. Tokens stored in Vault at `archon/connectors/{tenant_id}/google-workspace/{instance_id}/`
  4. Automatic refresh (Google refresh tokens don't expire unless revoked)
- Service account for admin-wide access (domain-wide delegation):
  - JSON key file stored in Vault
  - Domain-wide delegation configured in Google Admin Console
  - Impersonation: service account acts as specific user via `subject` parameter
- Scopes: `https://www.googleapis.com/auth/drive.readonly`, `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/calendar.readonly`, `https://www.googleapis.com/auth/admin.directory.user.readonly`
- Incremental authorization: request additional scopes as needed without re-authorization

**Salesforce**
- Connected App configuration in Salesforce Setup
- OAuth 2.0 Web Server Flow:
  1. Redirect to `https://login.salesforce.com/services/oauth2/authorize`
  2. Callback exchanges code at `https://login.salesforce.com/services/oauth2/token`
  3. Instance URL stored with tokens (Salesforce-specific: instance_url varies per org)
  4. Refresh token rotation: Salesforce rotates refresh tokens; always store the latest
- Sandbox vs Production org support:
  - Sandbox: `https://test.salesforce.com` endpoints
  - Production: `https://login.salesforce.com` endpoints
  - Custom domain: `https://{domain}.my.salesforce.com`
- JWT Bearer Flow for server-to-server integration (certificate stored in Vault)
- API version management: default to latest, configurable per instance

**Slack**
- Slack App with Bot Token Scopes + User Token Scopes
- OAuth V2 flow:
  1. Redirect to `https://slack.com/oauth/v2/authorize` with requested scopes
  2. Callback exchanges code → receives `bot_token` + `user_token` (if user scopes requested)
  3. Both tokens stored in Vault at `archon/connectors/{tenant_id}/slack/{instance_id}/`
- Bot scopes: `channels:read`, `channels:history`, `chat:write`, `files:read`, `users:read`
- User scopes: `search:read`, `files:write`, `channels:write`
- Event Subscriptions: receive real-time events via webhook (message posted, file shared, etc.)
- Socket Mode support for development environments (no public URL needed)

**GitHub**
- GitHub App installation flow (preferred over OAuth Apps):
  1. User installs GitHub App → callback with `installation_id` and `setup_action`
  2. Generate installation access tokens via `POST /app/installations/{id}/access_tokens`
  3. Tokens are short-lived (1 hour), auto-regenerated before expiry
  4. App private key stored in Vault
- Fine-grained Personal Access Tokens (PAT) as alternative:
  - User provides PAT → stored in Vault
  - Scope validation: check token has required permissions
- Repository permissions: `contents:read`, `issues:write`, `pull_requests:write`, `actions:read`
- Webhook events: push, pull_request, issues, workflow_run

### Vault Credential Storage

**All connector credentials stored in Vault (Agent-00) — NEVER in the database**
- Vault path structure: `archon/connectors/{tenant_id}/{connector_id}/{instance_id}/`
- Stored credential fields:
  ```json
  {
    "access_token": "eyJhbGciOiJSUzI1NiIs...",
    "refresh_token": "1//0gdkjf...",
    "token_type": "Bearer",
    "expires_at": "2025-01-15T10:30:00Z",
    "client_id": "abc123",
    "client_secret_ref": "archon/connectors/shared/microsoft365/client_secret",
    "scopes": ["User.Read", "Mail.Read"],
    "instance_url": "https://myorg.salesforce.com",
    "certificate_ref": "archon/connectors/{tenant_id}/microsoft365/cert",
    "api_key": null,
    "metadata": {
      "provider": "microsoft365",
      "auth_method": "oauth2_authorization_code",
      "created_at": "2025-01-01T00:00:00Z",
      "last_refreshed_at": "2025-01-15T10:00:00Z",
      "last_validated_at": "2025-01-15T10:15:00Z"
    }
  }
  ```
- Credential health checks: validate every hour (attempt a lightweight API call)
- Credential rotation: automatic token refresh, manual key rotation via API
- Credential revocation: revoke at provider + delete from Vault + audit log entry
- Vault lease management: credentials have TTLs, auto-renewed by background worker

### 3-Tier Connector Architecture

**Tier 1 — Official Connectors**
- Full implementation with comprehensive test coverage (>90%)
- Security-reviewed by Agent-11 (DLP + vulnerability scan)
- Performance-tested (throughput, latency benchmarks)
- Supported by Archon team — SLA on bug fixes
- 20+ connectors at launch:
  - Microsoft 365 (SharePoint, Teams, Outlook, OneDrive, Excel Online)
  - Google Workspace (Drive, Gmail, Calendar, Docs, Sheets)
  - Salesforce, HubSpot, Dynamics 365
  - GitHub, GitLab, Jira, Linear, Azure DevOps
  - PostgreSQL, MySQL, MongoDB, Snowflake, BigQuery
  - AWS S3, Azure Blob, Google Cloud Storage
  - ServiceNow, PagerDuty, Zendesk
  - Slack, Discord
  - REST API, GraphQL (generic)

**Tier 2 — Community Connectors**
- Community-contributed via pull request
- Basic testing (unit tests + integration test with mock)
- Security review (automated scan + manual review for credential handling)
- Published in connector marketplace with "Community" badge
- 30+ available: Notion, Confluence, Airtable, Asana, Monday.com, Trello, Basecamp, Pipedrive, Freshdesk, Twilio, SendGrid, Stripe, Shopify, WooCommerce, NetSuite, SAP, Oracle DB, DynamoDB, Databricks, Redshift, MinIO, Dropbox, Box, Email (IMAP/SMTP), WhatsApp Business, PingFederate, Okta Directory, Active Directory/LDAP, Webhook (generic), gRPC (generic)

**Tier 3 — Custom Connectors**
- User-built via Custom Connector SDK
- Self-managed by the tenant that created them
- Sandboxed execution: run in isolated subprocess with resource limits (CPU, memory, network)
- No access to other tenants' data or connectors
- Optional publishing: submit for Tier 2 review

### Event-Driven Connectors

**Beyond CRUD — real-time event support**
- **Webhook receivers**: Register webhook endpoints per connector instance
  - `POST /api/v1/connectors/{instance_id}/webhooks/receive` — receives events from external systems
  - Signature validation per provider (HMAC-SHA256 for GitHub, signing secret for Slack, etc.)
  - Event normalization: provider-specific events mapped to `ConnectorEvent` schema
- **Polling**: Configurable polling interval (minimum 60s, default 5min)
  - Incremental polling with cursor/timestamp tracking (no duplicate events)
  - Polling schedule stored in Redis, managed by Celery Beat
- **Server-Sent Events (SSE)**: For providers supporting SSE streams
  - Persistent connection managed by background worker
  - Reconnection with last-event-id
- **WebSocket**: For real-time bidirectional streams
  - Connection lifecycle managed per instance
  - Heartbeat monitoring
- **Event routing**: Events from connectors routed to:
  - Agent triggers (start an agent execution when event matches criteria)
  - Document ingestion pipeline (Agent-14) for new/updated documents
  - Notification system for connector owners
  - Event log for audit trail

### Permission-Aware Data Access

**Connector respects the executing user's permissions at the source system**
- **Delegated access pattern** (default):
  - When a user triggers an agent that uses a connector, the connector operates with that user's OAuth token
  - The user only sees/accesses data they have permission to access in the source system
  - Example: Microsoft 365 delegated permissions — user can only access their own emails and files they have access to
- **Application access pattern** (admin operations):
  - For admin-level operations (e.g., search across all users' files), use application permissions
  - Requires explicit admin consent during connector setup
  - Logged as elevated access in audit trail
  - Policy check: only users with `connector:admin_access` permission can trigger app-level access
- **Permission caching**:
  - Cache user's permission context for 5 minutes in Redis
  - Invalidate on token refresh or explicit cache clear
- **Access decisions logged**: every data access through a connector logged with user_id, resource_id, access_level, result

### Connection Health Monitoring

**Real-time health tracking per connector instance**
- Health check dimensions:
  - **Ping**: lightweight API call to verify connectivity (e.g., `GET /me` for Microsoft Graph)
  - **Throughput**: requests/second, bytes transferred
  - **Error rate**: percentage of failed requests in last 5 minutes
  - **Latency**: p50, p95, p99 response times
  - **Credential expiry countdown**: time until access token / refresh token / API key expires
- Health check frequency: every 60 seconds for active connectors, every 5 minutes for idle
- Auto-disable: connector instance disabled after 10 consecutive failures
  - Status set to `unhealthy`
  - Owner notified via email + in-app notification
  - Re-enable requires manual action or successful health check
- Health dashboard: per-tenant view of all connector instances with status indicators
- Health history: 30-day rolling window of health metrics (stored in TimescaleDB or PostgreSQL partitioned table)

### Rate Limiting

**Per-provider rate limit tracking and enforcement**
- Rate limit configuration per connector type:
  ```python
  class RateLimitConfig:
      requests_per_second: float        # e.g., 10.0
      requests_per_minute: float        # e.g., 600.0
      requests_per_hour: float | None   # e.g., 10000.0
      daily_quota: int | None           # e.g., 50000
      concurrent_requests: int          # e.g., 5
      burst_size: int                   # e.g., 20 (token bucket burst)
  ```
- Rate limit tracking via Redis (sliding window counter per connector instance)
- Automatic backoff when approaching limits (slow down at 80% utilization)
- Retry with jitter: on 429 response, respect `Retry-After` header, add random jitter (0-2s)
- Queue overflow: when rate limited, queue requests in Redis for later retry (max queue depth: 1000)
- Per-tenant rate limits: tenant-level aggregate limits across all connector instances
- Rate limit metrics exposed to health dashboard

### Custom Connector SDK

**Python SDK for building, testing, and publishing custom connectors**

- **SDK Package**: `archon-connector-sdk` (installable via pip)
- **CLI scaffolding tool**:
  ```bash
  # Generate a new connector project
  archon-connector new my-connector --auth oauth2 --resources "contacts,deals"
  
  # Generated structure:
  my-connector/
  ├── connector.py           # Main connector class (extends ConnectorBase)
  ├── auth.py                # Auth configuration
  ├── resources/
  │   ├── contacts.py        # Contact resource implementation
  │   └── deals.py           # Deal resource implementation
  ├── schemas/
  │   ├── contacts.json      # JSON Schema for contacts
  │   └── deals.json         # JSON Schema for deals
  ├── tests/
  │   ├── test_connector.py  # Unit tests
  │   ├── test_contacts.py   # Resource-specific tests
  │   └── conftest.py        # Test fixtures with mock server
  ├── docs/
  │   └── README.md          # Auto-generated documentation
  ├── manifest.json          # Connector metadata
  └── pyproject.toml         # Package configuration
  ```
- **Testing framework**:
  - Mock mode: run connector against mock HTTP server (no real API calls)
  - Live mode: run connector against real API with test credentials
  - Compliance tests: automatic validation of ConnectorBase interface compliance
  - Security tests: check for credential leaks in logs/responses
  ```bash
  archon-connector test --mode mock     # Fast, no credentials needed
  archon-connector test --mode live     # Real API calls
  archon-connector test --security      # Security validation
  ```
- **Documentation generator**:
  ```bash
  archon-connector docs generate        # Generate docs from code + schemas
  archon-connector docs serve           # Preview docs locally
  ```
- **Publishing workflow**:
  1. `archon-connector publish` — packages connector + runs all tests
  2. Submitted to Archon connector review queue
  3. Automated security scan (dependency audit, credential handling check)
  4. Manual review by connector team (for Tier 2 promotion)
  5. Published to connector marketplace

### Data Transformation Layer

**Input/output schema validation and data mapping**
- **Schemas per operation**: every connector resource has JSON Schema for input and output
  ```python
  class ResourceSchema:
      resource_type: str                 # "contacts", "files", "messages"
      input_schema: dict                 # JSON Schema for write/update operations
      output_schema: dict                # JSON Schema for read operations
      search_schema: dict                # JSON Schema for search filters
      supported_operations: list[str]    # ["list", "read", "write", "search", "watch"]
  ```
- **Schema validation**: all data validated against schemas before sending to provider and after receiving
- **Data mapping**: configurable field mapping between source system fields and Archon canonical fields
  ```python
  class DataMapping:
      source_field: str                  # "FirstName" (Salesforce)
      target_field: str                  # "given_name" (Archon)
      transform: str | None             # "lowercase", "date_iso8601", "currency_usd"
      default_value: Any | None         # Default if source field is null
  ```
- **Transformation functions**: built-in transformers for common conversions
  - Date format normalization (any format → ISO 8601)
  - Currency conversion (via exchange rate API)
  - Unit conversion (metric ↔ imperial)
  - String transforms (trim, lowercase, uppercase, slug)
  - Custom transform functions (Python lambda, registered per tenant)

### Core Data Models

```python
class ConnectorDefinition(SQLModel, table=True):
    """Registry of all available connector types."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    connector_type: str = Field(unique=True, index=True)     # "microsoft365", "salesforce"
    display_name: str                                         # "Microsoft 365"
    description: str
    icon_url: str | None
    tier: Literal["official", "community", "custom"]
    version: str                                              # Semantic version
    auth_methods: list[str]                                   # ["oauth2", "api_key", "certificate"]
    supported_resources: list[str]                            # ["files", "emails", "contacts"]
    supported_events: list[str]                               # ["file.created", "email.received"]
    rate_limit_config: dict                                   # Default rate limits
    documentation_url: str | None
    status: Literal["active", "deprecated", "disabled"]
    created_at: datetime
    updated_at: datetime | None

class ConnectorInstance(SQLModel, table=True):
    """A configured instance of a connector for a specific tenant."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    connector_type: str = Field(foreign_key="connectordefinition.connector_type")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id", index=True)
    display_name: str                                         # User-friendly name
    config: dict                                              # Instance-specific configuration
    credential_vault_path: str                                # Vault path for credentials
    auth_method: str                                          # "oauth2", "api_key", "certificate"
    status: Literal["active", "inactive", "unhealthy", "setup_pending"]
    owner_id: uuid.UUID = Field(foreign_key="users.id")
    last_health_check_at: datetime | None
    last_sync_at: datetime | None
    error_count: int = 0
    created_at: datetime
    updated_at: datetime | None
    deleted_at: datetime | None                               # Soft delete

class ConnectorCredential(SQLModel, table=True):
    """Metadata about credentials — actual secrets stored in Vault."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    instance_id: uuid.UUID = Field(foreign_key="connectorinstance.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    vault_path: str                                           # Path in Vault
    auth_method: str                                          # "oauth2", "api_key", "certificate"
    scopes: list[str]                                         # OAuth scopes granted
    expires_at: datetime | None                               # Token/key expiry
    last_refreshed_at: datetime | None
    last_validated_at: datetime | None
    status: Literal["valid", "expired", "revoked", "refresh_failed"]
    created_at: datetime
    updated_at: datetime | None

class ConnectorEvent(SQLModel, table=True):
    """Events received from or detected by connectors."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    instance_id: uuid.UUID = Field(foreign_key="connectorinstance.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    event_type: str                                           # "file.created", "message.received"
    source_event_id: str | None                               # Provider's event ID
    payload: dict                                             # Normalized event data
    raw_payload: dict                                         # Original provider payload
    received_at: datetime
    processed_at: datetime | None
    routing_status: Literal["pending", "routed", "failed", "ignored"]
    routed_to: list[str]                                      # Agent IDs or pipeline IDs

class ConnectorHealth(SQLModel, table=True):
    """Health check history for connector instances."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    instance_id: uuid.UUID = Field(foreign_key="connectorinstance.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    check_type: Literal["ping", "auth_validate", "throughput_test"]
    status: Literal["healthy", "degraded", "unhealthy", "unknown"]
    latency_ms: float | None
    error_message: str | None
    details: dict                                             # Provider-specific health details
    checked_at: datetime
```

### Official Connectors (50+)

**Productivity & Collaboration**
- Microsoft 365: SharePoint, Teams, Outlook, OneDrive, Excel Online
- Google Workspace: Drive, Gmail, Calendar, Docs, Sheets
- Notion, Confluence, Slack, Discord

**CRM & Sales**
- Salesforce, HubSpot, Dynamics 365, Pipedrive

**Development & DevOps**
- GitHub, GitLab, Jira, Linear, Azure DevOps, Bitbucket

**Databases**
- PostgreSQL, MySQL, SQLite, MongoDB, DynamoDB
- Snowflake, BigQuery, Databricks, Redshift

**Cloud Storage**
- AWS S3, Azure Blob, Google Cloud Storage, MinIO

**Communication**
- Email (IMAP/SMTP), SMS (Twilio), WhatsApp Business

**ITSM & Operations**
- ServiceNow, PagerDuty, Zendesk, Freshdesk

**ERP**
- SAP, Oracle, NetSuite

**Identity & Directory**
- Active Directory/LDAP, Okta, Azure AD/Entra ID

**Generic**
- REST API, GraphQL, gRPC, WebSocket, MCP Protocol, Webhook

### Connector Marketplace

- Browse available connectors by category and tier
- Install/configure from UI with guided setup wizard
- Connector ratings, reviews, and usage stats
- Version management and automatic updates (for Tier 1)
- Search by provider name, resource type, or auth method

## Output Structure

```
integrations/
├── framework/                          # Core connector framework
│   ├── __init__.py
│   ├── base.py                        # ConnectorBase abstract class
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── oauth2.py                  # OAuth 2.0 flow implementations
│   │   ├── api_key.py                 # API key auth handler
│   │   ├── certificate.py            # Certificate-based auth
│   │   ├── vault_store.py            # Vault credential storage/retrieval
│   │   └── token_refresh.py          # Background token refresh worker
│   ├── events/
│   │   ├── __init__.py
│   │   ├── webhook.py                 # Webhook receiver + signature validation
│   │   ├── polling.py                 # Configurable polling engine
│   │   ├── sse.py                     # SSE stream consumer
│   │   ├── websocket.py              # WebSocket event stream
│   │   └── router.py                 # Event routing to agents/pipelines
│   ├── health.py                      # Connection health monitoring
│   ├── rate_limiter.py                # Per-provider rate limiting
│   ├── circuit_breaker.py             # Circuit breaker pattern
│   ├── registry.py                    # Connector discovery + registration
│   ├── permissions.py                 # Permission-aware access layer
│   ├── transform.py                   # Data transformation layer
│   └── schemas.py                     # Schema validation
├── connectors/                         # Official connectors (one dir each)
│   ├── microsoft365/
│   │   ├── __init__.py
│   │   ├── connector.py               # Microsoft365Connector
│   │   ├── auth.py                    # Azure AD OAuth flows
│   │   ├── resources/
│   │   │   ├── sharepoint.py
│   │   │   ├── teams.py
│   │   │   ├── outlook.py
│   │   │   ├── onedrive.py
│   │   │   └── excel.py
│   │   ├── events.py                  # Microsoft Graph subscriptions
│   │   └── schemas/
│   ├── google_workspace/
│   │   ├── __init__.py
│   │   ├── connector.py
│   │   ├── auth.py                    # Google OAuth + service account
│   │   ├── resources/
│   │   │   ├── drive.py
│   │   │   ├── gmail.py
│   │   │   ├── calendar.py
│   │   │   ├── docs.py
│   │   │   └── sheets.py
│   │   └── schemas/
│   ├── salesforce/
│   │   ├── __init__.py
│   │   ├── connector.py
│   │   ├── auth.py                    # Salesforce OAuth + JWT Bearer
│   │   ├── resources/
│   │   └── schemas/
│   ├── slack/
│   │   ├── __init__.py
│   │   ├── connector.py
│   │   ├── auth.py                    # Slack OAuth V2
│   │   ├── resources/
│   │   ├── events.py                  # Event subscriptions + Socket Mode
│   │   └── schemas/
│   ├── github/
│   │   ├── __init__.py
│   │   ├── connector.py
│   │   ├── auth.py                    # GitHub App + PAT
│   │   ├── resources/
│   │   ├── events.py                  # Webhook events
│   │   └── schemas/
│   ├── postgresql/
│   ├── mysql/
│   ├── mongodb/
│   ├── snowflake/
│   ├── bigquery/
│   ├── aws_s3/
│   ├── azure_blob/
│   ├── gcs/
│   ├── servicenow/
│   ├── jira/
│   ├── hubspot/
│   ├── rest_api/                      # Generic REST connector
│   ├── graphql/                       # Generic GraphQL connector
│   └── ...                            # 50+ connectors total
├── sdk/                                # Custom Connector SDK
│   ├── __init__.py
│   ├── cli.py                         # CLI scaffolding tool
│   ├── testing/
│   │   ├── __init__.py
│   │   ├── mock_server.py            # Mock HTTP server for testing
│   │   ├── compliance.py             # Interface compliance tests
│   │   ├── security.py               # Security validation tests
│   │   └── runner.py                  # Test runner
│   ├── docs.py                        # Documentation generator
│   ├── publisher.py                   # Publishing workflow
│   ├── templates/                     # Scaffold templates
│   │   ├── connector.py.j2
│   │   ├── resource.py.j2
│   │   ├── tests.py.j2
│   │   └── manifest.json.j2
│   └── manifest.py                    # Manifest schema + validation
└── tests/
    ├── conftest.py
    ├── test_framework/
    │   ├── test_base.py
    │   ├── test_oauth2.py
    │   ├── test_vault_store.py
    │   ├── test_health.py
    │   ├── test_rate_limiter.py
    │   ├── test_circuit_breaker.py
    │   ├── test_events.py
    │   ├── test_permissions.py
    │   └── test_transform.py
    ├── test_connectors/
    │   ├── test_microsoft365.py
    │   ├── test_google_workspace.py
    │   ├── test_salesforce.py
    │   ├── test_slack.py
    │   ├── test_github.py
    │   └── ...
    └── test_sdk/
        ├── test_cli.py
        ├── test_testing_framework.py
        └── test_publisher.py

backend/app/routers/connectors.py        # Connector management API
backend/app/services/connector_service.py # Connector business logic
frontend/src/components/connectors/       # Connector UI components
```

## API Endpoints (Complete)

```
# Connector Definitions (Registry)
GET    /api/v1/connectors/definitions                         # List available connector types
GET    /api/v1/connectors/definitions/{type}                  # Get connector type details
GET    /api/v1/connectors/definitions/{type}/schema           # Get resource schemas

# Connector Instances (Per-Tenant)
GET    /api/v1/connectors                                     # List tenant's connector instances
POST   /api/v1/connectors                                     # Create new connector instance
GET    /api/v1/connectors/{id}                                # Get connector instance details
PUT    /api/v1/connectors/{id}                                # Update connector configuration
DELETE /api/v1/connectors/{id}                                # Soft-delete connector instance
POST   /api/v1/connectors/{id}/test                           # Test connector connectivity
GET    /api/v1/connectors/{id}/health                         # Get health status
GET    /api/v1/connectors/{id}/health/history                 # Get health history (30 days)
POST   /api/v1/connectors/{id}/enable                         # Re-enable disabled connector
POST   /api/v1/connectors/{id}/disable                        # Manually disable connector

# OAuth Flows
GET    /api/v1/connectors/{type}/oauth/authorize              # Start OAuth flow (redirect)
GET    /api/v1/connectors/{type}/oauth/callback               # OAuth callback handler
POST   /api/v1/connectors/{id}/oauth/refresh                  # Force token refresh
POST   /api/v1/connectors/{id}/oauth/revoke                   # Revoke OAuth tokens
GET    /api/v1/connectors/microsoft365/admin-consent           # Azure AD admin consent
GET    /api/v1/connectors/microsoft365/admin-consent/callback  # Admin consent callback

# Credentials
GET    /api/v1/connectors/{id}/credentials                    # Get credential metadata (no secrets)
POST   /api/v1/connectors/{id}/credentials                    # Store new credentials (API key, cert)
PUT    /api/v1/connectors/{id}/credentials                    # Update credentials
DELETE /api/v1/connectors/{id}/credentials                    # Revoke + delete credentials
GET    /api/v1/connectors/{id}/credentials/status             # Credential health status

# Data Operations (Proxy to connector)
GET    /api/v1/connectors/{id}/resources/{type}               # List resources
GET    /api/v1/connectors/{id}/resources/{type}/{resource_id} # Get resource
POST   /api/v1/connectors/{id}/resources/{type}               # Create resource
PUT    /api/v1/connectors/{id}/resources/{type}/{resource_id} # Update resource
DELETE /api/v1/connectors/{id}/resources/{type}/{resource_id} # Delete resource
POST   /api/v1/connectors/{id}/search                         # Search across resources

# Events
GET    /api/v1/connectors/{id}/events                         # List received events
POST   /api/v1/connectors/{id}/events/subscribe               # Subscribe to event type
DELETE /api/v1/connectors/{id}/events/subscribe/{sub_id}      # Unsubscribe
POST   /api/v1/connectors/{id}/webhooks/receive               # Incoming webhook endpoint

# Marketplace
GET    /api/v1/connectors/marketplace                         # Browse marketplace
GET    /api/v1/connectors/marketplace/{type}                  # Marketplace entry details
POST   /api/v1/connectors/marketplace/{type}/install          # Install connector
GET    /api/v1/connectors/marketplace/{type}/reviews          # Get reviews

# Custom Connector SDK
POST   /api/v1/connectors/custom/submit                       # Submit custom connector
GET    /api/v1/connectors/custom/submissions                   # List submissions
GET    /api/v1/connectors/custom/submissions/{id}/status       # Submission review status
```

## Verify Commands

```bash
# Connector framework importable
cd ~/Scripts/Archon && python -c "from integrations.framework.base import ConnectorBase; print('OK')"

# Auth module importable
cd ~/Scripts/Archon && python -c "from integrations.framework.auth.oauth2 import OAuth2Flow; from integrations.framework.auth.vault_store import VaultCredentialStore; print('Auth OK')"

# Event system importable
cd ~/Scripts/Archon && python -c "from integrations.framework.events.webhook import WebhookReceiver; from integrations.framework.events.router import EventRouter; print('Events OK')"

# Core connectors importable
cd ~/Scripts/Archon && python -c "from integrations.connectors.microsoft365.connector import Microsoft365Connector; from integrations.connectors.salesforce.connector import SalesforceConnector; from integrations.connectors.slack.connector import SlackConnector; print('Connectors OK')"

# Data models importable
cd ~/Scripts/Archon && python -c "from integrations.framework.schemas import ConnectorDefinition, ConnectorInstance, ConnectorCredential, ConnectorEvent, ConnectorHealth; print('Models OK')"

# SDK scaffold tool works
cd ~/Scripts/Archon && python -c "from integrations.sdk.cli import scaffold; print('SDK OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest integrations/tests/ --tb=short -q

# Rate limiter works
cd ~/Scripts/Archon && python -c "from integrations.framework.rate_limiter import RateLimiter; print('Rate Limiter OK')"

# No hardcoded credentials
cd ~/Scripts/Archon && ! grep -rn 'client_secret\s*=\s*"[^"]*"' --include='*.py' integrations/ || echo 'FAIL: Hardcoded secrets found'

# Vault integration for credentials
cd ~/Scripts/Archon && python -c "from integrations.framework.auth.vault_store import VaultCredentialStore; print('Vault OK')"
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] ConnectorBase interface fully implemented with connect/disconnect/CRUD/search/watch operations
- [ ] OAuth 2.0 Authorization Code + PKCE flow works end-to-end for Microsoft 365 (Azure AD)
- [ ] OAuth 2.0 flow works end-to-end for Google Workspace (including service account domain-wide delegation)
- [ ] OAuth 2.0 Web Server Flow works for Salesforce (including sandbox vs production distinction)
- [ ] Slack OAuth V2 flow produces both bot and user tokens, stored in Vault
- [ ] GitHub App installation flow generates short-lived installation tokens, auto-refreshed
- [ ] ALL connector credentials stored exclusively in Vault (zero credentials in database or env vars)
- [ ] Credential health checks validate every hour and auto-flag expired/invalid credentials
- [ ] 3-tier architecture enforced: Official (20+), Community (30+), Custom (SDK-built) with security gates
- [ ] Event-driven connectors receive webhooks, poll on schedule, and route events to agent triggers
- [ ] Permission-aware access: delegated tokens used by default, application tokens only with admin consent
- [ ] Connection health monitoring detects failures within 30 seconds and auto-disables after 10 consecutive failures
- [ ] Rate limiting tracks per-provider limits, auto-backs-off at 80%, queues overflow to Redis
- [ ] Custom Connector SDK scaffolds a working connector project in <30 seconds via CLI
- [ ] SDK testing framework validates interface compliance, security, and mock/live modes
- [ ] Data transformation layer validates schemas and maps fields between source and Archon formats
- [ ] Circuit breaker pattern prevents cascading failures across connector instances
- [ ] All data models (ConnectorDefinition, ConnectorInstance, ConnectorCredential, ConnectorEvent, ConnectorHealth) implemented with proper indexes
- [ ] All API endpoints return correct responses with proper auth and tenant isolation
- [ ] All tests pass with >85% coverage across framework, connectors, and SDK
