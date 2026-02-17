# Agent-21: Cross-Platform Security Proxy Gateway

> **Phase**: 3 (Security & Governance) | **Dependencies**: Agent-01 (Core Backend), Agent-07 (Router), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Standalone deployable proxy that enforces DLP, audit, and cost controls on ANY AI API traffic.**

---

## Identity

You are Agent-21: the Cross-Platform Security Proxy Gateway Builder. You build a standalone reverse-proxy that sits in front of ANY AI endpoint (OpenAI, Anthropic, Azure OpenAI, Bedrock, Gemini, or third-party agents) and applies Archon's full security stack — SAML termination, credential injection, DLP scanning, content classification, cost tracking, and audit logging — regardless of where the AI was built or hosted. Deployable as a standalone container or integrated with the full platform.

## Mission

Build a deployable, standalone security proxy that:
1. Terminates SAML assertions from external IdPs and bridges to OIDC for backend services
2. Injects per-tenant credentials from Vault into outbound LLM API calls transparently
3. Operates as a standalone reverse proxy requiring zero code changes in consuming applications
4. Applies DLP scanning (Agent-11) on every request and response with <50ms added latency
5. Classifies content by topic, sensitivity, and intent with route-level policy enforcement
6. Tracks token usage and cost per user, department, and tenant with budget enforcement
7. Produces complete request/response audit logs compatible with SIEM ingestion
8. Deploys in active-active HA with <10ms p50 added latency and 10k+ concurrent connections

## Requirements

### SAML Termination

**SAML Assertion Processing**
- Proxy terminates SAML assertions from external Identity Providers:
  ```python
  class SAMLTerminator:
      """Terminates SAML assertions at proxy level, translates to internal JWT."""
      
      async def process_assertion(self, saml_response: str) -> ProxySession:
          # 1. Decode and parse SAML Response
          assertion = self.parser.decode(saml_response)
          
          # 2. Validate SAML signature using IdP certificate (from Vault)
          idp_cert = await self.vault.read(f"proxy/idp/{assertion.issuer}/cert")
          if not self.crypto.verify_signature(assertion, idp_cert):
              raise SAMLValidationError("Invalid SAML signature")
          
          # 3. Validate conditions (NotBefore, NotOnOrAfter, audience)
          self.validate_conditions(assertion)
          
          # 4. Extract user attributes from SAML assertion
          user_attrs = self.extract_attributes(assertion, self.attribute_mapping)
          
          # 5. Translate SAML session → internal JWT
          jwt = self.issue_proxy_jwt(
              sub=user_attrs.user_id,
              email=user_attrs.email,
              roles=user_attrs.roles,
              tenant_id=user_attrs.tenant_id,
              department=user_attrs.department,
              session_id=str(uuid.uuid4()),
              exp=datetime.utcnow() + timedelta(hours=8),
          )
          
          return ProxySession(jwt=jwt, user=user_attrs)
  ```

**IdP Certificate Management**
- IdP signing certificates stored in Vault (Agent-00)
- Certificate validation: signature algorithm allowlist (RS256, RS384, RS512 — reject SHA-1)
- Certificate rollover: support multiple active certificates per IdP during rotation
- Certificate expiry monitoring: alert 30 days before IdP certificate expiry

**SAML-to-OIDC Bridging**
- For backend services that only understand OIDC:
  1. Proxy receives SAML assertion from external IdP
  2. Validates and extracts claims
  3. Issues OIDC-compatible JWT with mapped claims
  4. Backend services validate JWT via proxy's JWKS endpoint (`/.well-known/jwks.json`)
- Claim mapping: configurable per IdP (SAML attribute → JWT claim)
- Token endpoint: proxy exposes `/oauth/token` for token refresh

**Supported IdPs**
- Okta, Azure AD / Entra ID, OneLogin, PingFederate, ADFS, Google Workspace
- Generic SAML 2.0 (any IdP with valid metadata)
- SAML metadata auto-import: `POST /api/v1/proxy/idp` with metadata XML URL

### Credential Injection

**Per-Tenant Credential Management**
```python
class CredentialInjector:
    """Injects appropriate credentials into outbound LLM API calls."""
    
    async def inject(self, request: ProxyRequest) -> ProxyRequest:
        tenant_id = request.session.tenant_id
        provider = request.target_provider  # "openai", "anthropic", etc.
        
        # 1. Retrieve credentials from Vault at request time
        creds = await self.vault.read(
            f"proxy/credentials/{tenant_id}/{provider}"
        )
        
        # 2. Inject into request headers
        if provider == "openai":
            request.headers["Authorization"] = f"Bearer {creds['api_key']}"
            if creds.get("org_id"):
                request.headers["OpenAI-Organization"] = creds["org_id"]
        elif provider == "anthropic":
            request.headers["x-api-key"] = creds["api_key"]
            request.headers["anthropic-version"] = creds.get("api_version", "2024-01-01")
        elif provider == "azure_openai":
            request.headers["api-key"] = creds["api_key"]
        # ... other providers
        
        return request
```

**Credential Properties**
- Per-tenant credentials: Tenant A's requests routed with Tenant A's API keys
- Credential caching: cached in memory for 5 minutes (configurable TTL), encrypted at rest in Vault
- Credential rotation: transparent to upstream services — Vault credential rotated, next request uses new key
- Credential health check: periodic validation that stored credentials are still valid
- No credential in logs: credentials redacted from all audit/debug logging

### Standalone Reverse Proxy

**Deployment Model**
- Single Docker container deployment — no external dependencies required (SQLite mode)
- Drop-in replacement for direct API calls:
  ```
  # Before (direct):
  curl https://api.openai.com/v1/chat/completions -H "Authorization: Bearer sk-..."
  
  # After (via proxy — same API, just different base URL):
  curl https://proxy.company.com/v1/chat/completions
  # Proxy handles auth, DLP, audit, cost — transparently
  ```
- No code changes required in consuming applications — configure base URL only
- Supports all API formats: REST, SSE streaming, WebSocket (future)

**Provider Support (Day 1)**
```python
class ProviderRegistry:
    PROVIDERS = {
        "openai": OpenAIProvider,           # /v1/chat/completions, /v1/embeddings, /v1/images, /v1/audio
        "anthropic": AnthropicProvider,      # /v1/messages
        "azure_openai": AzureOpenAIProvider, # /openai/deployments/*/chat/completions
        "google": GoogleProvider,            # /v1beta/models/*/generateContent
        "bedrock": BedrockProvider,          # /model/*/invoke
        "ollama": OllamaProvider,            # /api/generate, /api/chat
        "vllm": VLLMProvider,               # /v1/completions (OpenAI-compatible)
        "tgi": TGIProvider,                  # /generate, /generate_stream
        "generic": GenericRESTProvider,      # Configurable schema matching
    }
```

**Proxy Core Architecture**
```python
class ProxyCore:
    """ASGI reverse proxy with full security pipeline."""
    
    async def handle_request(self, request: Request) -> Response:
        # 1. Authentication (SAML/JWT/API Key)
        session = await self.authenticator.authenticate(request)
        
        # 2. Route identification (which provider, which endpoint)
        route = self.router.resolve(request.path, request.headers)
        
        # 3. Request body parsing (provider-specific)
        parsed = await route.provider.parse_request(request)
        
        # 4. Security pipeline (request)
        await self.pipeline.process_request(parsed, session)
        
        # 5. Credential injection
        proxied_request = await self.credential_injector.inject(parsed)
        
        # 6. Forward to upstream
        if parsed.is_streaming:
            return await self.stream_response(proxied_request, session, route)
        else:
            upstream_response = await self.http_client.forward(proxied_request)
            
            # 7. Security pipeline (response)
            processed = await self.pipeline.process_response(upstream_response, session)
            
            # 8. Audit log
            await self.audit.log(session, parsed, processed)
            
            # 9. Cost tracking
            await self.cost_tracker.record(session, route, processed)
            
            return processed.to_response()
```

**Performance**
- Connection pooling: per-provider connection pools (min=10, max=100 per upstream)
- Keep-alive: HTTP/2 to upstreams where supported
- Compression: gzip/brotli for non-streaming responses
- Target latency: <10ms p50, <50ms p95 added latency
- Throughput: 10k+ concurrent connections per proxy instance

### DLP Scanning on Proxy

**Request/Response DLP Pipeline**
```
Request Flow:
  Client → [Auth] → [Parse] → [DLP Scan] → [Classification] → [Policy] → [Inject Creds] → Upstream

Response Flow:
  Upstream → [Parse] → [DLP Scan] → [Content Filter] → [Policy] → [Cost Track] → [Audit] → Client
```

- Integration with Agent-11's DLP pipeline:
  - PII detection: names, emails, phone numbers, SSNs, credit card numbers
  - PHI detection: medical record numbers, diagnosis codes, patient data
  - Credential detection: API keys, passwords, tokens, connection strings
  - Custom patterns: tenant-configurable regex patterns
- DLP actions:
  - **Block**: reject request/response entirely, return error
  - **Redact**: replace sensitive data with `[REDACTED]` or masked values
  - **Alert**: allow through but trigger alert to security team
  - **Log**: record finding in audit log without blocking
- Scanning latency: <50ms for requests <100KB, linear scaling for larger payloads
- Streaming DLP: scan SSE chunks in real-time, buffer minimal content for pattern matching

### Content Classification

**Request Classification Engine**
```python
class ContentClassifier:
    """Classifies every proxied request by topic, sensitivity, and intent."""
    
    async def classify(self, request: ParsedRequest) -> Classification:
        return Classification(
            sensitivity=self.classify_sensitivity(request),   # public/internal/confidential/restricted
            topic=self.classify_topic(request),                # code, email, legal, financial, medical, general
            intent=self.classify_intent(request),              # generation, analysis, summarization, translation
            department_match=self.match_department_policy(request),
        )
```

**Route-Level Policies**
- Admin configures policies per department/role/user:
  ```yaml
  policies:
    - name: "Sales AI Usage"
      department: "sales"
      allowed_topics: ["email", "general", "summarization"]
      blocked_topics: ["code", "legal", "financial"]
      max_sensitivity: "internal"
      allowed_providers: ["openai", "anthropic"]
      
    - name: "Engineering AI Usage"
      department: "engineering"
      allowed_topics: ["code", "general", "analysis"]
      blocked_topics: ["medical", "legal"]
      max_sensitivity: "confidential"
      allowed_providers: ["openai", "anthropic", "ollama"]
  ```
- Policy evaluation via OPA sidecar for complex rules
- Policy violations: block request + audit log + optional alert

### Cost Tracking on Proxy

**Token Counting & Cost Attribution**
```python
class CostTracker:
    """Tracks token usage and cost for every proxied request."""
    
    async def record(self, session: ProxySession, route: Route, response: ParsedResponse) -> None:
        usage = CostRecord(
            request_id=session.request_id,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            department=session.department,
            
            provider=route.provider.name,
            model=response.model_used,
            
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            
            cost_usd=self.calculate_cost(route.provider, response.model_used, response.usage),
            
            timestamp=datetime.utcnow(),
        )
        await self.store.record(usage)
        
        # Budget enforcement
        budget = await self.budget_service.get_budget(session.tenant_id, session.department)
        if budget and await self.budget_service.is_exceeded(budget):
            await self.budget_service.enforce(budget)  # Block future requests
```

**Budget Enforcement**
- Budget levels: per-user, per-department, per-tenant
- Budget periods: daily, weekly, monthly
- Enforcement: warn at 80%, soft-block at 100% (admin can override), hard-block at 120%
- Real-time cost dashboard (when connected to Archon platform)
- Cost attribution: user → department → project → tenant

### Audit Logging

**Complete Request/Response Logging**
```python
class ProxyAuditLog(SQLModel, table=True):
    """Complete audit record for every proxied request."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Request Identity
    request_id: str  # Correlation ID
    conversation_id: str | None  # Groups related requests
    
    # Actor
    user_id: str
    tenant_id: str
    department: str | None
    auth_method: Literal["saml", "jwt", "api_key"]
    source_ip: str
    user_agent: str
    
    # Request
    provider: str  # openai, anthropic, etc.
    model: str
    endpoint: str  # /v1/chat/completions
    request_summary: str  # First 200 chars (configurable redaction)
    request_sensitivity: Literal["public", "internal", "confidential", "restricted"]
    request_topic: str
    request_intent: str
    
    # Response
    response_status: int  # HTTP status
    response_summary: str | None  # First 200 chars (configurable redaction)
    
    # DLP
    dlp_request_findings: int  # Number of DLP findings in request
    dlp_response_findings: int
    dlp_action: Literal["none", "redacted", "blocked", "alerted"] | None
    
    # Cost
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    
    # Performance
    latency_ms: int  # Total request duration
    proxy_overhead_ms: int  # Latency added by proxy
    upstream_latency_ms: int  # Upstream provider latency
    
    # Result
    result: Literal["success", "blocked_dlp", "blocked_policy", "blocked_budget", "error", "timeout"]
    error_message: str | None
    
    timestamp: datetime
```

**Log Format & SIEM Integration**
- Log formats: JSON (default), CEF (Common Event Format), syslog
- Export targets:
  - Splunk (HEC endpoint)
  - Elastic/OpenSearch (direct index or Logstash)
  - Datadog (webhook)
  - Generic syslog (RFC 5424)
  - S3/Blob storage (batch export)
- Configurable redaction: full request/response logging, summary-only, or headers-only
- Retention: 90 days hot (queryable), 1 year cold (S3/Blob archive)
- Compliance reports: "all AI interactions for User X in the last 30 days"

### High Availability

**Active-Active Deployment**
```yaml
# Kubernetes deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: archon-proxy
spec:
  replicas: 3  # Minimum 3 for HA
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0     # Zero-downtime upgrades
      maxSurge: 1
```

**HA Properties**
- Active-active: all instances serve traffic simultaneously (no primary/secondary)
- Health checks: `/health` (liveness), `/ready` (readiness — checks upstream connectivity)
- Graceful failover: load balancer detects unhealthy instance within 5 seconds
- Zero-downtime upgrades: rolling update with connection draining (30s drain timeout)
- Shared state: Redis for session cache, rate limit counters, budget tracking
- Stateless proxy: any instance can serve any request (session in Redis)

**Performance Targets**
- p50 added latency: <10ms
- p95 added latency: <50ms
- p99 added latency: <100ms
- Concurrent connections: 10k+ per instance
- Throughput: 5k+ requests/second per instance
- CPU: <200m per instance at idle, <2 cores at peak
- Memory: <512MB per instance at steady state

### Infrastructure

**Docker Deployment**
```yaml
# Standalone deployment
services:
  proxy:
    image: archon/security-proxy:latest
    ports: ["8443:8443"]
    volumes: ["./config.yaml:/app/config.yaml"]
    environment:
      PROXY_MODE: standalone
      PROXY_DB: sqlite:///data/proxy.db
      VAULT_ADDR: https://vault.company.com
      VAULT_TOKEN_FILE: /run/secrets/vault-token
  
  # Optional: Redis for HA mode
  redis:
    image: redis:7-alpine
    
# Integrated with Archon platform
services:
  proxy:
    image: archon/security-proxy:latest
    environment:
      PROXY_MODE: integrated
      PROXY_DB: postgresql://...
      ARCHON_API: http://api:8000
```

**Configuration**
- YAML-based configuration for standalone mode
- PostgreSQL for integrated mode, SQLite for standalone
- All settings via `pydantic-settings` with `ARCHON_PROXY_` prefix
- Feature flags: `proxy_dlp_enabled`, `proxy_cost_tracking`, `proxy_saml_enabled`

## Output Structure

```
security_proxy/
├── __init__.py
├── main.py                    # ASGI application entry point (uvicorn)
├── config.py                  # YAML + env configuration loader
├── proxy_core.py              # HTTP reverse proxy engine
├── auth/
│   ├── __init__.py
│   ├── saml_terminator.py     # SAML assertion termination and validation
│   ├── oidc_bridge.py         # SAML-to-OIDC bridging, JWKS endpoint
│   ├── jwt_validator.py       # Internal JWT validation
│   ├── api_key.py             # API key authentication
│   └── session.py             # Proxy session management
├── credentials/
│   ├── __init__.py
│   ├── injector.py            # Credential injection into outbound requests
│   ├── vault_client.py        # Vault integration for credential retrieval
│   └── cache.py               # Credential caching with TTL
├── providers/
│   ├── __init__.py
│   ├── base.py                # Abstract provider parser
│   ├── openai.py              # OpenAI API format parser
│   ├── anthropic.py           # Anthropic API format parser
│   ├── azure_openai.py        # Azure OpenAI format parser
│   ├── google.py              # Gemini API format parser
│   ├── bedrock.py             # AWS Bedrock format parser
│   ├── ollama.py              # Ollama API format parser
│   ├── vllm.py                # vLLM format parser
│   ├── tgi.py                 # Text Generation Inference parser
│   └── generic.py             # Generic REST API parser (configurable)
├── pipeline/
│   ├── __init__.py
│   ├── dlp_scanner.py         # PII/PHI/credential detection (Agent-11 integration)
│   ├── classifier.py          # Content sensitivity/topic/intent classification
│   ├── policy_engine.py       # OPA-based policy enforcement
│   ├── content_filter.py      # Response content filtering and redaction
│   └── streaming.py           # SSE streaming DLP (real-time chunk scanning)
├── cost/
│   ├── __init__.py
│   ├── token_counter.py       # Provider-aware token counting (tiktoken + provider-specific)
│   ├── calculator.py          # Cost calculation per model/provider
│   ├── budget_enforcer.py     # Budget limit enforcement (user/dept/tenant)
│   └── attribution.py         # Cost attribution to organizational units
├── audit/
│   ├── __init__.py
│   ├── logger.py              # Audit log writer (async, non-blocking)
│   ├── models.py              # ProxyAuditLog data model
│   ├── exporter.py            # SIEM export (Splunk, Elastic, Datadog, syslog)
│   ├── retention.py           # Log retention and archival (hot → cold)
│   └── reports.py             # Compliance report generation
├── ha/
│   ├── __init__.py
│   ├── health.py              # Health/readiness/liveness probes
│   ├── session_store.py       # Redis-backed session store for HA
│   └── metrics.py             # Prometheus metrics endpoint
├── Dockerfile                 # Multi-stage build, <200MB image
├── docker-compose.yml         # Standalone dev/test deployment
├── docker-compose.integrated.yml  # Integrated with Archon platform
├── config.example.yaml        # Example standalone configuration
└── helm/
    ├── Chart.yaml
    ├── values.yaml
    └── templates/
        ├── deployment.yaml
        ├── service.yaml
        ├── configmap.yaml
        ├── hpa.yaml           # Horizontal pod autoscaler
        └── pdb.yaml           # Pod disruption budget

tests/
├── conftest.py                # Proxy test fixtures, mock providers
├── test_proxy_core.py         # Core proxy forwarding
├── test_saml_termination.py   # SAML assertion processing
├── test_oidc_bridge.py        # SAML-to-OIDC bridging
├── test_credential_injection.py  # Per-tenant credential injection
├── test_providers.py          # Provider-specific request/response parsing
├── test_dlp_pipeline.py       # DLP scanning on proxy
├── test_classification.py     # Content classification
├── test_policy_engine.py      # OPA policy enforcement
├── test_cost_tracking.py      # Token counting and cost attribution
├── test_budget_enforcement.py # Budget limit enforcement
├── test_audit_logging.py      # Audit log completeness and SIEM export
├── test_streaming.py          # SSE streaming passthrough with DLP
├── test_standalone_mode.py    # Standalone deployment with SQLite
├── test_ha.py                 # Health checks and session failover
└── test_performance.py        # Latency and throughput benchmarks
```

## API Endpoints (Complete)

```
# Proxy Admin API
GET    /api/v1/proxy/status                        # Proxy health and metrics summary
GET    /api/v1/proxy/config                        # Current proxy configuration
PUT    /api/v1/proxy/config                        # Update proxy configuration (hot-reload)

# IdP Management (SAML)
GET    /api/v1/proxy/idps                          # List configured IdPs
POST   /api/v1/proxy/idps                          # Add IdP (SAML metadata URL or XML)
GET    /api/v1/proxy/idps/{id}                     # Get IdP details
PUT    /api/v1/proxy/idps/{id}                     # Update IdP configuration
DELETE /api/v1/proxy/idps/{id}                     # Remove IdP

# SAML Endpoints
POST   /saml/acs                                   # Assertion Consumer Service
GET    /saml/login                                 # SP-initiated login
GET    /saml/metadata                              # SP metadata
GET    /.well-known/jwks.json                      # JWKS for OIDC bridge

# Credential Management
GET    /api/v1/proxy/credentials                   # List configured provider credentials
POST   /api/v1/proxy/credentials                   # Add provider credentials (stored in Vault)
PUT    /api/v1/proxy/credentials/{provider}         # Rotate credentials
DELETE /api/v1/proxy/credentials/{provider}         # Revoke credentials
GET    /api/v1/proxy/credentials/{provider}/health  # Credential validation check

# Provider Management
GET    /api/v1/proxy/providers                     # List supported providers
GET    /api/v1/proxy/providers/{id}/health          # Provider health check
PUT    /api/v1/proxy/providers/{id}/config          # Provider-specific config

# Policy Management
GET    /api/v1/proxy/policies                      # List content policies
POST   /api/v1/proxy/policies                      # Create policy
PUT    /api/v1/proxy/policies/{id}                 # Update policy
DELETE /api/v1/proxy/policies/{id}                 # Delete policy
POST   /api/v1/proxy/policies/evaluate              # Test policy against sample request

# DLP Configuration
GET    /api/v1/proxy/dlp/config                    # DLP scanning configuration
PUT    /api/v1/proxy/dlp/config                    # Update DLP configuration
GET    /api/v1/proxy/dlp/patterns                  # List custom DLP patterns
POST   /api/v1/proxy/dlp/patterns                  # Add custom DLP pattern

# Cost & Budget
GET    /api/v1/proxy/cost/summary                  # Cost summary (by tenant/dept/user)
GET    /api/v1/proxy/cost/usage                    # Detailed usage records
GET    /api/v1/proxy/budgets                       # List budgets
POST   /api/v1/proxy/budgets                       # Create budget
PUT    /api/v1/proxy/budgets/{id}                  # Update budget
DELETE /api/v1/proxy/budgets/{id}                  # Delete budget

# Audit
GET    /api/v1/proxy/audit                         # Query audit logs (paginated, filtered)
GET    /api/v1/proxy/audit/export                  # Export audit logs (CSV/JSON)
POST   /api/v1/proxy/audit/report                  # Generate compliance report
GET    /api/v1/proxy/audit/siem/config              # SIEM export configuration
PUT    /api/v1/proxy/audit/siem/config              # Update SIEM export configuration

# Health & Metrics
GET    /health                                     # Liveness probe
GET    /ready                                      # Readiness probe
GET    /metrics                                    # Prometheus metrics
```

## Verify Commands

```bash
# Security proxy module importable
cd ~/Scripts/Archon && python -c "from security_proxy.main import app; print('OK')"

# SAML terminator importable
cd ~/Scripts/Archon && python -c "from security_proxy.auth.saml_terminator import SAMLTerminator; print('SAML OK')"

# Credential injector importable
cd ~/Scripts/Archon && python -c "from security_proxy.credentials.injector import CredentialInjector; print('Credentials OK')"

# All providers importable
cd ~/Scripts/Archon && python -c "from security_proxy.providers import OpenAIProvider, AnthropicProvider, AzureOpenAIProvider, GoogleProvider, BedrockProvider; print('Providers OK')"

# DLP pipeline importable
cd ~/Scripts/Archon && python -c "from security_proxy.pipeline.dlp_scanner import DLPScanner; from security_proxy.pipeline.classifier import ContentClassifier; print('Pipeline OK')"

# Cost tracking importable
cd ~/Scripts/Archon && python -c "from security_proxy.cost.token_counter import TokenCounter; from security_proxy.cost.budget_enforcer import BudgetEnforcer; print('Cost OK')"

# Audit module importable
cd ~/Scripts/Archon && python -c "from security_proxy.audit.logger import AuditLogger; from security_proxy.audit.exporter import SIEMExporter; print('Audit OK')"

# Tests pass
cd ~/Scripts/Archon && python -m pytest tests/test_security_proxy/ --tb=short -q

# Standalone Docker config exists
test -f ~/Scripts/Archon/security_proxy/Dockerfile && test -f ~/Scripts/Archon/security_proxy/config.example.yaml && echo 'OK'

# Docker build succeeds
cd ~/Scripts/Archon/security_proxy && docker build -t archon-proxy-test . 2>&1 | tail -1

# No hardcoded credentials
cd ~/Scripts/Archon && ! grep -rn 'api_key\s*=\s*"sk-[^"]*"' --include='*.py' security_proxy/ || echo 'FAIL'

# Docker compose is valid
cd ~/Scripts/Archon && docker compose config --quiet
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] SAML termination validates assertions from Okta, Azure AD, and generic SAML IdPs
- [ ] SAML-to-OIDC bridging issues valid JWTs with mapped claims; JWKS endpoint functional
- [ ] IdP certificates stored in Vault with expiry monitoring and rollover support
- [ ] Per-tenant credentials injected from Vault into outbound LLM API calls
- [ ] Credential rotation transparent to consuming applications
- [ ] Proxy intercepts and forwards requests to at least 6 AI providers (OpenAI, Anthropic, Azure, Gemini, Bedrock, Ollama)
- [ ] Drop-in replacement: same API format, just different base URL, zero code changes
- [ ] DLP pipeline detects and redacts PII/PHI in requests and responses
- [ ] Streaming DLP scans SSE chunks in real-time without breaking streaming
- [ ] Content classification categorizes by topic, sensitivity, and intent
- [ ] Route-level policies enforce department-specific AI usage rules
- [ ] OPA policy engine blocks requests based on content classification
- [ ] Token counting and cost attribution working for all supported providers
- [ ] Budget enforcement blocks requests when budget exceeded
- [ ] Full audit logging with correlation IDs and configurable redaction
- [ ] SIEM export functional for Splunk, Elastic, and syslog formats
- [ ] Audit log retention: 90 days hot, 1 year cold (S3/Blob)
- [ ] Active-active deployment with zero-downtime upgrades
- [ ] <10ms p50 added latency verified by benchmark
- [ ] 10k+ concurrent connections sustained without degradation
- [ ] Standalone Docker deployment with YAML config (no Archon platform dependency)
- [ ] Helm chart for Kubernetes deployment with HPA and PDB
- [ ] SSE streaming passthrough working for all providers
- [ ] All admin API endpoints match `contracts/openapi.yaml`
- [ ] 80%+ test coverage
- [ ] Zero plaintext credentials in logs, env vars, or source code
