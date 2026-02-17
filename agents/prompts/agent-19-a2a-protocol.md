# Agent-19: A2A Protocol — Agent-to-Agent Interoperability

> **Phase**: 4 (Integrations & Data) | **Dependencies**: Agent-01 (Core Backend), Agent-07 (Router), Agent-13 (Connectors), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Enables cross-organization agent federation with enterprise security guarantees.**

---

## Identity

You are Agent-19: the A2A Protocol & Federation Builder. You implement the complete Agent-to-Agent interoperability layer — enabling Archon agents to discover, authenticate, communicate with, and publish to agents on other A2A-compatible platforms across organizational boundaries. Every interaction is secured via federated OAuth 2.0, mTLS, and DLP scanning.

## Mission

Build a production-grade A2A federation layer that:
1. Implements federated OAuth 2.0 Client Credentials flow between Archon instances with Vault-managed tokens
2. Secures all A2A traffic with mTLS using Vault PKI-issued certificates with automated rotation
3. Publishes and discovers agent capabilities via machine-readable Agent Cards (JSON-LD) at well-known endpoints
4. Enables bi-directional communication — both CONSUME external A2A agents and PUBLISH Archon agents as A2A services
5. Enforces data isolation with DLP scanning (Agent-11) on all inbound and outbound A2A data
6. Manages partner trust levels from Untrusted through Federated with granular policy enforcement
7. Produces a complete cross-organization audit trail for compliance

## Requirements

### Federated OAuth 2.0 Authentication

**Client Credentials Flow Between Instances**
- Each Archon instance registers as an OAuth 2.0 client with partner instances
- Registration exchange:
  1. Admin initiates partner connection → generates registration payload (client_id, redirect_uris, scopes requested)
  2. Partner admin approves → returns client_secret (transmitted via Vault transit encryption, Agent-00)
  3. Credentials stored in Vault KV engine under `a2a/partners/{partner_id}/credentials`
- Token acquisition:
  ```python
  class A2AFederatedAuth:
      """OAuth 2.0 Client Credentials for A2A communication."""
      async def acquire_token(self, partner_id: str) -> A2AAccessToken:
          credentials = await self.vault.read(f"a2a/partners/{partner_id}/credentials")
          token = await self.http_client.post(
              url=partner.token_endpoint,
              data={
                  "grant_type": "client_credentials",
                  "client_id": credentials["client_id"],
                  "client_secret": credentials["client_secret"],
                  "scope": " ".join(self.requested_scopes),
              },
              cert=(self.mtls_cert, self.mtls_key),  # mTLS required
          )
          # Token cached in Vault transit with TTL matching token lifetime
          await self.vault.write(f"a2a/tokens/{partner_id}", token, ttl="5m")
          return A2AAccessToken.parse(token)
  ```
- Token properties:
  - Lifetime: 5 minutes (short-lived, non-configurable below 1 min or above 15 min)
  - Scoped to specific agent capabilities (e.g., `a2a:invoke:sentiment-analysis`, `a2a:stream:translation`)
  - Token includes `partner_id`, `trust_level`, `allowed_data_classifications` claims
  - Token never held in application memory longer than the request lifecycle
- Token refresh: new token acquired per-request or cached in Vault with TTL
- Token revocation: instant revocation via partner's revocation endpoint + local blacklist in Redis

**Token Exchange via Vault (Agent-00)**
- All token material passes through Vault transit engine for encryption at rest
- Token cache in Vault KV (not Redis) — ensures tokens are never in plaintext outside Vault
- Audit: every token acquisition/use logged in Vault audit log

### mTLS Credential Exchange

**Certificate Infrastructure**
- All A2A traffic requires mutual TLS — no exceptions
- Certificates issued by Vault PKI engine (Agent-00):
  ```python
  class A2AMTLSManager:
      """Manages mTLS certificates for A2A communication."""
      async def issue_certificate(self, partner_id: str) -> MTLSCertificate:
          cert = await self.vault.write("pki/issue/a2a-client", {
              "common_name": f"a2a-{self.instance_id}.archon.internal",
              "alt_names": f"a2a.{self.domain}",
              "ttl": "720h",  # 30 days
              "ip_sans": self.pod_ips,
          })
          return MTLSCertificate(
              cert=cert["certificate"],
              key=cert["private_key"],
              ca_chain=cert["ca_chain"],
              serial=cert["serial_number"],
              expiry=cert["expiration"],
          )
  ```
- Certificate rotation:
  - Automated rotation 7 days before expiry
  - Rotation creates new cert, adds to trust store, waits for propagation, removes old cert
  - Zero-downtime rotation via dual-cert support (both old and new cert accepted during rollover window)
- Certificate pinning:
  - Pin partner certificates by Subject Public Key Info (SPKI) hash
  - Rollover support: accept both current and next SPKI pins during rotation
  - Pin violation → reject connection + alert + audit log
- CA trust chain:
  - Configurable per partner (partner A may use DigiCert, partner B may use internal CA)
  - CA bundle managed in Vault, updated via admin API
  - Cross-signing support for migration between CAs

### Agent Card Protocol

**Agent Card Schema (JSON-LD)**
```python
class AgentCard(SQLModel, table=True):
    """Machine-readable capability descriptor published at well-known endpoint."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Identity
    name: str = Field(max_length=255)
    description: str
    version: str  # SemVer (e.g., "1.2.0")
    provider: str  # Organization name
    provider_url: str  # Organization URL
    icon_url: str | None
    
    # Capabilities
    skills: list[AgentSkill]  # What the agent can do
    supported_input_types: list[str]  # MIME types accepted
    supported_output_types: list[str]  # MIME types produced
    tools: list[AgentToolRef]  # MCP tools this agent uses
    models: list[str]  # LLM models this agent may use
    
    # Authentication
    auth_type: Literal["oauth2", "api_key", "mtls", "none"]
    auth_config: dict  # OAuth endpoints, scopes, etc.
    
    # Operational
    rate_limit: RateLimit  # requests/minute, concurrent
    max_response_time_ms: int  # SLA: max expected response time
    pricing: AgentPricing | None  # Cost per invocation (if applicable)
    sla: AgentSLA  # Uptime, latency, support tier
    
    # Data Handling
    data_classification_max: Literal["public", "internal", "confidential"]
    data_retention_policy: str  # "none", "30d", "1y"
    gdpr_compliant: bool = False
    
    # Versioning
    card_version: int = 1  # Card schema version
    deprecated: bool = False
    sunset_date: datetime | None
    
    # Metadata
    published_at: datetime
    updated_at: datetime | None
    checksum: str  # SHA-256 of card content for change detection

class AgentSkill(SQLModel):
    name: str
    description: str
    input_schema: dict  # JSON Schema for inputs
    output_schema: dict  # JSON Schema for outputs
    examples: list[dict]  # Example invocations
    tags: list[str]

class AgentPricing(SQLModel):
    model: Literal["free", "per_call", "per_token", "subscription"]
    currency: str = "USD"
    unit_price: float | None
    free_tier_calls: int | None
```

**Discovery Protocol**
- Well-known endpoint: `GET /.well-known/agent-cards` returns JSON array of all published Agent Cards
- Individual card: `GET /.well-known/agent-cards/{agent_id}` returns single card
- Discovery mechanisms:
  1. **Direct URL**: Admin pastes partner's base URL → fetch `/.well-known/agent-cards`
  2. **Registry**: Optional central registry (configurable) for public agent discovery
  3. **DNS-SD**: `_a2a._tcp.example.com` TXT record with agent-cards URL
  4. **Scheduled polling**: Re-discover partner agents every 6 hours (configurable)
- Card change detection: compare checksums, alert on capability changes, auto-update registry
- Card validation: JSON-LD context validation, schema compliance check, authentication probe

### Bi-Directional Communication

**Consuming External A2A Agents (Inbound)**
- Import external A2A agent into Archon canvas as a node:
  1. Browse discovered agents → select → "Add to Canvas"
  2. React Flow custom node type `A2AExternalNode` rendered with partner branding
  3. Node configuration: map canvas data flow to Agent Card input/output schemas
  4. Runtime: execution engine calls external agent via A2A client
- External agent appears in agent palette alongside native agents
- Input/output type mapping with automatic transformation where possible
- Timeout configuration per external agent (default: 30s, max: 300s)
- Fallback behavior: configurable (fail workflow, skip node, use cached result)

**Publishing Archon Agents as A2A Services (Outbound)**
- Admin selects agent → "Publish as A2A Service"
- Configuration:
  ```python
  class A2APublishConfig(SQLModel):
      agent_id: uuid.UUID
      visibility: Literal["private", "partner", "public"]
      allowed_partners: list[uuid.UUID] | None  # None = all trusted partners
      rate_limit: RateLimit
      max_data_classification: Literal["public", "internal", "confidential"]
      pricing: AgentPricing | None
      require_approval: bool = False  # Manual approval for each invocation
  ```
- Auto-generates Agent Card from agent definition + publish config
- Serves agent via A2A task endpoints (see Message Protocol below)
- Versioning: publishing a new agent version updates the Agent Card, notifies consumers

### Message Protocol

**JSON-RPC 2.0 over HTTPS**
- All A2A messages use JSON-RPC 2.0 envelope:
  ```json
  {
    "jsonrpc": "2.0",
    "method": "a2a.invoke",
    "id": "req-uuid-here",
    "params": {
      "agent_id": "uuid",
      "skill": "sentiment-analysis",
      "input": { "text": "Analyze this..." },
      "config": {
        "timeout_ms": 30000,
        "stream": false,
        "callback_url": "https://caller.example.com/a2a/callback"
      }
    }
  }
  ```
- Message types:
  - `a2a.invoke` — Request execution, synchronous response
  - `a2a.stream` — Request execution with SSE streaming response
  - `a2a.status` — Check execution status (for async invocations)
  - `a2a.cancel` — Cancel in-progress execution
  - `a2a.discover` — Programmatic agent discovery (alternative to well-known endpoint)
- Request validation: input validated against Agent Card's declared input schema
- Response validation: output validated against Agent Card's declared output schema
- Idempotency: `id` field used for deduplication (cache responses for 5 minutes)
- Error codes: standard JSON-RPC 2.0 errors + A2A-specific codes (4001=auth failed, 4002=rate limited, 4003=data classification violation, 4004=agent unavailable)

**Streaming Protocol (SSE)**
```python
class A2AStreamHandler:
    """Server-Sent Events for streaming A2A responses."""
    async def stream_response(self, request: A2AInvokeRequest) -> StreamingResponse:
        async def event_generator():
            async for chunk in self.execute_agent(request):
                yield f"event: chunk\ndata: {chunk.json()}\n\n"
            yield f"event: done\ndata: {{}}\n\n"
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-A2A-Request-Id": request.id,
                "X-A2A-Partner-Id": request.partner_id,
            },
        )
```

### Data Isolation

**Inbound DLP Scanning**
- Every response received from an external A2A agent is DLP-scanned (Agent-11) before entering the workflow:
  1. External agent returns response
  2. Response passes through DLP pipeline: PII detection, PHI detection, credential scanning
  3. Policy evaluation: block, redact, or alert based on data classification
  4. Only clean/redacted data enters the canvas workflow
  5. Original (pre-redaction) response stored in audit log (encrypted, access-restricted)

**Outbound DLP Scanning**
- Every request sent to an external A2A agent is DLP-scanned before transmission:
  1. Canvas node prepares output for external agent
  2. DLP pipeline scans for PII, secrets, confidential data
  3. Data classification check: if data classification exceeds partner's allowed level → block
  4. Only compliant data is transmitted
  5. Scan result logged in audit trail

**Cross-Organization Data Boundaries**
- No data from Organization A's workflows can leak to Organization B's agents without explicit policy
- Data tagging: all data flowing through A2A carries classification labels
- Encryption in transit (mTLS) + at rest (Vault transit encryption for cached data)
- Data retention: A2A response cache configurable (default: no retention, purge after workflow completes)

### Trust Management

**Trust Levels**
```python
class A2APartner(SQLModel, table=True):
    """Represents a partner organization for A2A federation."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Identity
    name: str
    domain: str  # Partner's primary domain
    base_url: str  # Partner's A2A base URL
    contact_email: str
    
    # Trust
    trust_level: Literal["untrusted", "verified", "trusted", "federated"]
    trust_established_at: datetime | None
    trust_verified_by: uuid.UUID | None  # Admin who verified
    
    # Authentication
    oauth_client_id: str | None
    oauth_token_endpoint: str | None
    mtls_cert_serial: str | None
    mtls_ca_fingerprint: str | None
    
    # Policy
    max_data_classification: Literal["public", "internal", "confidential"]
    allowed_operations: list[str]  # ["invoke", "stream", "discover"]
    rate_limit_rpm: int = 60
    rate_limit_concurrent: int = 10
    
    # Status
    status: Literal["active", "suspended", "revoked"]
    last_communication_at: datetime | None
    total_invocations: int = 0
    error_rate_30d: float = 0.0
    
    created_at: datetime
    updated_at: datetime | None
```

**Trust Level Policies**
| Trust Level | Data Classification Max | Allowed Operations | Rate Limit | Certificate Required |
|-------------|------------------------|--------------------|------------|---------------------|
| Untrusted | Public only | discover | 10 rpm | No |
| Verified | Internal | discover, invoke | 60 rpm | Yes (any CA) |
| Trusted | Confidential | discover, invoke, stream | 300 rpm | Yes (pinned) |
| Federated | Confidential | all + publish | 1000 rpm | Yes (cross-signed) |

**Trust Lifecycle**
1. **Untrusted**: Partner added, no verification. Can only discover agent cards.
2. **Verified**: Admin verifies partner identity (domain ownership via DNS TXT, or manual). mTLS established.
3. **Trusted**: Successful history of interactions, admin promotes. Certificate pinning enabled.
4. **Federated**: Full bi-directional federation. Cross-signed certificates. Shared audit trail.

**Trust Revocation**
- Instant revocation via:
  1. Certificate revocation (CRL + OCSP responder via Vault PKI)
  2. OAuth token blacklist (Redis set, checked on every request)
  3. Partner status → "revoked" in database
  4. Active connections terminated within 30 seconds
  5. Audit log entry with revocation reason
- Revocation reasons: security incident, policy violation, contract termination, admin decision

### Audit & Compliance

**A2A Audit Log**
```python
class A2AInvocation(SQLModel, table=True):
    """Immutable audit record for every A2A interaction."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Direction
    direction: Literal["inbound", "outbound"]
    
    # Source & Destination
    source_org: str
    source_partner_id: uuid.UUID | None
    destination_org: str
    destination_partner_id: uuid.UUID | None
    
    # Invocation Details
    agent_id: uuid.UUID
    agent_name: str
    skill_invoked: str | None
    method: Literal["invoke", "stream", "status", "cancel", "discover"]
    
    # Data Classification
    request_data_classification: Literal["public", "internal", "confidential"]
    response_data_classification: Literal["public", "internal", "confidential"] | None
    dlp_scan_result: Literal["clean", "redacted", "blocked"] | None
    dlp_findings_count: int = 0
    
    # Result
    status: Literal["success", "failed", "blocked", "timeout", "cancelled"]
    error_code: str | None
    error_message: str | None
    
    # Performance
    latency_ms: int
    token_count_request: int | None
    token_count_response: int | None
    
    # Cost
    cost_usd: float | None
    
    # Security
    auth_method: Literal["oauth2", "mtls", "api_key"]
    trust_level_at_time: Literal["untrusted", "verified", "trusted", "federated"]
    
    # Tracing
    trace_id: str  # OpenTelemetry
    request_id: str  # JSON-RPC request ID
    
    created_at: datetime
```

**Cross-Organization Audit Reports**
- Generate compliance reports spanning A2A interactions:
  - Per-partner: all interactions with Partner X in date range
  - Per-classification: all Confidential data exchanged via A2A
  - Per-agent: all external invocations of Agent Y
  - Anomaly report: unusual patterns (spike in requests, new data types, trust violations)
- Export formats: PDF, CSV, JSON
- Scheduled reports: daily/weekly/monthly to compliance team

### Infrastructure

**Docker Compose Services**
```yaml
services:
  a2a-gateway:     # A2A protocol gateway (FastAPI)
  a2a-worker:      # Async A2A invocation processor (Celery)
```

**Environment Configuration**
- All A2A settings via `pydantic-settings` with `ARCHON_A2A_` prefix
- Partner credentials in Vault — never in env vars or config files
- Feature flags: `a2a_federation_enabled`, `a2a_public_discovery`, `a2a_streaming`

## Output Structure

```
backend/app/a2a/
├── __init__.py
├── router.py                  # A2A protocol endpoints (well-known, tasks, discovery)
├── models.py                  # AgentCard, A2APartner, A2AInvocation, A2ATrust models
├── schemas.py                 # Pydantic request/response schemas, JSON-LD context
├── client.py                  # A2A client for calling external agents (HTTP + SSE)
├── server.py                  # A2A server: handle inbound invocations
├── discovery.py               # Agent Card discovery, registry, polling
├── publisher.py               # Publish Archon agents as A2A services
├── auth/
│   ├── __init__.py
│   ├── oauth.py               # Federated OAuth 2.0 Client Credentials
│   ├── mtls.py                # mTLS certificate management via Vault PKI
│   └── token_exchange.py      # Vault-based token caching and exchange
├── trust/
│   ├── __init__.py
│   ├── manager.py             # Trust level management and lifecycle
│   ├── policies.py            # Trust-level policy enforcement
│   └── revocation.py          # Certificate revocation + token blacklist
├── dlp/
│   ├── __init__.py
│   ├── inbound_scanner.py     # DLP scan on incoming A2A responses
│   └── outbound_scanner.py    # DLP scan on outgoing A2A requests
├── streaming.py               # SSE streaming for A2A responses
├── audit.py                   # A2A audit logging and cross-org reports
├── tasks.py                   # Celery tasks for async A2A operations
└── config.py                  # A2A-specific configuration

frontend/src/components/a2a/
├── A2AAgentBrowser.tsx         # Browse and search discovered external agents
├── A2ANodeType.tsx             # React Flow custom node for A2A agents
├── A2APublisher.tsx            # Publish Archon agents as A2A services
├── A2APartnerManager.tsx       # Manage partner trust levels
├── A2ATrustDashboard.tsx       # Trust level visualization and management
├── A2ALogsViewer.tsx           # Cross-org audit log viewer
└── A2ACardViewer.tsx           # View/compare Agent Cards

tests/
├── conftest.py                 # A2A test fixtures, mock partners
├── test_a2a_discovery.py       # Agent Card discovery and registry
├── test_a2a_client.py          # Outbound A2A invocations
├── test_a2a_server.py          # Inbound A2A request handling
├── test_a2a_publisher.py       # Agent publishing as A2A services
├── test_a2a_oauth.py           # Federated OAuth 2.0 flow
├── test_a2a_mtls.py            # mTLS certificate lifecycle
├── test_a2a_trust.py           # Trust level management and revocation
├── test_a2a_dlp.py             # DLP scanning on A2A traffic
├── test_a2a_streaming.py       # SSE streaming protocol
├── test_a2a_audit.py           # Audit log completeness and reports
└── test_a2a_security.py        # End-to-end security integration
```

## API Endpoints (Complete)

```
# Agent Card Discovery
GET    /.well-known/agent-cards                    # List all published Agent Cards (public)
GET    /.well-known/agent-cards/{agent_id}         # Get specific Agent Card (public)

# Partner Management
GET    /api/v1/a2a/partners                        # List A2A partners
POST   /api/v1/a2a/partners                        # Register new partner
GET    /api/v1/a2a/partners/{id}                   # Get partner details
PUT    /api/v1/a2a/partners/{id}                   # Update partner configuration
DELETE /api/v1/a2a/partners/{id}                   # Remove partner
PATCH  /api/v1/a2a/partners/{id}/trust             # Update trust level
POST   /api/v1/a2a/partners/{id}/revoke            # Revoke partner trust instantly
POST   /api/v1/a2a/partners/{id}/verify            # Verify partner identity

# Discovery
POST   /api/v1/a2a/discover                        # Discover agents from a URL
GET    /api/v1/a2a/discovered-agents                # List all discovered external agents
GET    /api/v1/a2a/discovered-agents/{id}           # Get discovered agent details
POST   /api/v1/a2a/discovered-agents/{id}/import    # Import to canvas
DELETE /api/v1/a2a/discovered-agents/{id}           # Remove from registry

# Publishing
POST   /api/v1/a2a/publish                         # Publish agent as A2A service
GET    /api/v1/a2a/published                        # List published agents
PUT    /api/v1/a2a/published/{id}                   # Update publish configuration
DELETE /api/v1/a2a/published/{id}                   # Unpublish agent

# A2A Protocol (Inbound — served to partners)
POST   /api/v1/a2a/invoke                          # JSON-RPC: invoke agent
POST   /api/v1/a2a/stream                          # JSON-RPC: stream agent response (SSE)
GET    /api/v1/a2a/status/{request_id}              # JSON-RPC: check invocation status
POST   /api/v1/a2a/cancel/{request_id}              # JSON-RPC: cancel invocation

# Audit
GET    /api/v1/a2a/audit                           # Query A2A audit logs
GET    /api/v1/a2a/audit/report                    # Generate cross-org compliance report
GET    /api/v1/a2a/audit/export                    # Export audit logs (CSV/JSON/PDF)

# Certificates
GET    /api/v1/a2a/certificates                    # List A2A mTLS certificates
POST   /api/v1/a2a/certificates/rotate             # Trigger certificate rotation
GET    /api/v1/a2a/certificates/{serial}            # Get certificate details
```

## Verify Commands

```bash
# A2A module importable
cd ~/Scripts/Archon && python -c "from backend.app.a2a import A2AClient, A2APublisher, A2AFederatedAuth; print('OK')"

# All models importable
cd ~/Scripts/Archon && python -c "from backend.app.a2a.models import AgentCard, A2APartner, A2AInvocation; print('Models OK')"

# Auth module importable
cd ~/Scripts/Archon && python -c "from backend.app.a2a.auth.oauth import A2AFederatedAuth; from backend.app.a2a.auth.mtls import A2AMTLSManager; print('Auth OK')"

# Trust module importable
cd ~/Scripts/Archon && python -c "from backend.app.a2a.trust.manager import TrustManager; from backend.app.a2a.trust.revocation import TrustRevocation; print('Trust OK')"

# DLP integration importable
cd ~/Scripts/Archon && python -c "from backend.app.a2a.dlp.inbound_scanner import InboundDLPScanner; from backend.app.a2a.dlp.outbound_scanner import OutboundDLPScanner; print('DLP OK')"

# Agent Card schema validates
cd ~/Scripts/Archon && python -c "from backend.app.a2a.schemas import AgentCard, AgentSkill, AgentPricing; print('Schemas OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_a2a/ --tb=short -q

# No hardcoded secrets
cd ~/Scripts/Archon && ! grep -rn 'client_secret\s*=\s*"[^"]*"' --include='*.py' backend/app/a2a/ || echo 'FAIL'

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Federated OAuth 2.0 Client Credentials flow acquires scoped tokens from partner instances
- [ ] Tokens are short-lived (5 min), stored in Vault, never in application memory beyond request lifecycle
- [ ] mTLS certificates issued by Vault PKI with automated rotation and zero-downtime rollover
- [ ] Certificate pinning with rollover support rejects unpinned connections
- [ ] Agent Cards published at `/.well-known/agent-cards` with complete capability metadata
- [ ] Agent Card discovery via URL, DNS-SD, and scheduled polling all functional
- [ ] External A2A agents importable as React Flow canvas nodes with schema mapping
- [ ] Archon agents publishable as A2A services with configurable visibility and rate limits
- [ ] JSON-RPC 2.0 invoke, stream, status, cancel message types all working
- [ ] SSE streaming from external agents renders in real-time in canvas
- [ ] Inbound A2A responses DLP-scanned before entering workflow
- [ ] Outbound A2A requests DLP-scanned before transmission
- [ ] Data classification enforcement prevents Confidential data from reaching lower-trust partners
- [ ] Trust levels (Untrusted → Verified → Trusted → Federated) enforce correct policies
- [ ] Trust revocation disables partner within 30 seconds (cert revocation + token blacklist)
- [ ] Every A2A interaction logged with source org, destination org, classification, latency, cost
- [ ] Cross-org audit report generation working (PDF, CSV, JSON)
- [ ] All endpoints match `contracts/openapi.yaml`
- [ ] 80%+ test coverage across all A2A modules
- [ ] Zero plaintext secrets in logs, env vars, or source code
