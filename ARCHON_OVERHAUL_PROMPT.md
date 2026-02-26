# Archon Enterprise Overhaul — Ship-Quality Build Specification

> **Purpose:** This is the FINAL build pass. Every function must work end-to-end. Every API call must return real data from real database queries. Every frontend page must connect to real backend endpoints. No stubs, no mocks, no placeholders, no TODOs. After this pass, the product ships.
>
> **Previous swarm output:** Fixed 2 service stubs (versioning signatures, wizard templates) and wrote documentation. The 34 frontend-backend contract violations, all 13 priority features, and the 33 stub test files are still unaddressed. This pass builds everything.

---

## ARCHITECTURE SNAPSHOT

```
Frontend (React 19 + Vite)     →  Backend (FastAPI + Python 3.12)     →  PostgreSQL 16 + PGVector
     ↕ WebSocket                      ↕ Celery + Redis                      ↕ Alembic migrations
     ↕ TanStack Query                 ↕ Vault (secrets)                     ↕ Row-Level Security
     ↕ Zustand stores                 ↕ Keycloak (auth)                     ↕ Full-text + vector search
```

**Repository:** `/Users/timothy.schwarz/Scripts/Archon-swarm-test`

---

## WORKSTREAM 1: BACKEND API — Fix All 34 Contract Violations

Every frontend API function calls a backend endpoint. Every one of these must exist, accept the exact request shape the frontend sends, and return the exact response shape the frontend expects. No approximations.

### 1A. Router API (14 endpoints)

**File:** `backend/app/routes/router.py`
**Models needed:** `backend/app/models/model_provider.py`, `backend/app/models/routing_rule.py`
**Service:** `backend/app/services/router_service.py`

Implement these exact endpoints with these exact signatures:

```python
# ---------- Provider CRUD ----------

@router.get("/providers", response_model=StandardResponse[List[ProviderListItem]])
async def list_providers(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return all configured LLM providers with current health status.

    Response shape per item:
    {
        "id": "uuid",
        "name": "OpenAI Production",
        "type": "openai",  # openai | anthropic | google | mistral | cohere | azure_openai | ollama | vllm | custom
        "base_url": "https://api.openai.com/v1",
        "is_enabled": true,
        "health_status": "healthy",  # healthy | degraded | unhealthy | unknown
        "supported_models": ["gpt-4o", "gpt-4o-mini"],
        "capabilities": ["vision", "function_calling", "json_mode", "streaming"],
        "latency_ms_p50": 340,
        "latency_ms_p95": 890,
        "error_rate_pct": 0.2,
        "created_at": "2025-01-15T10:30:00Z"
    }
    """
    # Query ModelProvider table filtered by tenant_id
    # Join with provider_health_history for latest metrics (last 5 min rolling avg)
    # Return list sorted by name

@router.post("/providers", response_model=StandardResponse[ProviderDetail], status_code=201)
async def create_provider(
    body: ProviderCreateRequest,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
):
    """Register a new LLM provider.

    Request body:
    {
        "name": "OpenAI Production",
        "type": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-...",              # Stored in Vault at secret/tenants/{tenant_id}/providers/{id}
        "is_enabled": true,
        "rate_limit_rpm": 10000,
        "rate_limit_tpm": 2000000,
        "supported_models": ["gpt-4o", "gpt-4o-mini"],
        "capabilities": ["vision", "function_calling", "json_mode", "streaming"],
        "custom_headers": {}              # Optional additional headers
    }
    """
    # 1. Validate provider type against known types
    # 2. Store API key in Vault: vault_client.write(f"secret/tenants/{tenant_id}/providers/{provider_id}", {"api_key": body.api_key})
    # 3. Insert ModelProvider row with vault_path (NOT the raw key)
    # 4. Test connection by making a /models list call to the provider
    # 5. Insert initial health record
    # 6. Write audit log entry
    # 7. Return created provider (without api_key, with vault_path reference)

@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Delete a provider. Revoke Vault secret. Check no active routing rules reference it."""
    # 1. Check no routing_rules reference this provider_id — if so, return 409 Conflict
    # 2. Delete from Vault
    # 3. Delete from DB (soft delete: set deleted_at)
    # 4. Audit log

@router.put("/providers/{provider_id}/credentials", response_model=StandardResponse[dict])
async def update_credentials(
    provider_id: UUID,
    body: CredentialUpdateRequest,  # {"api_key": "sk-new-..."}
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Update provider API key in Vault. Test new credentials before saving."""
    # 1. Fetch provider from DB
    # 2. Test new key by making a /models call with it
    # 3. If test fails, return 422 with error details
    # 4. Write new key to Vault (overwrites old)
    # 5. Return {"status": "updated", "tested": true}

# ---------- Health ----------

@router.get("/providers/health", response_model=StandardResponse[AggregateHealthStatus])
async def providers_health_aggregate(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Aggregate health: {total: 5, healthy: 3, degraded: 1, unhealthy: 1}"""
    # COUNT(*) GROUP BY health_status from ModelProvider table

@router.get("/providers/{provider_id}/health", response_model=StandardResponse[ProviderHealthDetail])
async def provider_health_detail(
    provider_id: UUID,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Detailed health for one provider with 1h/24h/7d history.

    Response:
    {
        "provider_id": "uuid",
        "current_status": "healthy",
        "latency_ms_p50": 340,
        "latency_ms_p95": 890,
        "latency_ms_p99": 1200,
        "error_rate_pct": 0.2,
        "requests_per_minute": 45,
        "last_check_at": "2025-02-25T10:00:00Z",
        "history": [
            {"timestamp": "...", "latency_p50": 320, "error_rate": 0.1, "rpm": 42}
        ]
    }
    """
    # Query provider_health_history table for time-series data
    # Compute percentiles from last 5 min of raw latency data

@router.get("/providers/health/detail", response_model=StandardResponse[List[ProviderHealthDetail]])
async def providers_health_all_detail(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Same as single provider health, but for all providers."""

@router.get("/providers/credential-schemas", response_model=StandardResponse[dict])
async def credential_schemas():
    """Return expected credential fields per provider type. No DB query needed — static config.

    Response:
    {
        "openai": {"fields": [{"name": "api_key", "type": "password", "required": true}]},
        "anthropic": {"fields": [{"name": "api_key", "type": "password", "required": true}]},
        "azure_openai": {"fields": [
            {"name": "api_key", "type": "password", "required": true},
            {"name": "endpoint", "type": "url", "required": true},
            {"name": "api_version", "type": "text", "required": true, "default": "2024-02-01"},
            {"name": "deployment_name", "type": "text", "required": true}
        ]},
        "ollama": {"fields": [{"name": "base_url", "type": "url", "required": true, "default": "http://localhost:11434"}]},
        ...
    }
    """
    # Return PROVIDER_CREDENTIAL_SCHEMAS constant (defined in router_service.py)

# ---------- Routing Rules ----------

@router.get("/rules/visual", response_model=StandardResponse[VisualRulesConfig])
async def get_visual_rules(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return routing rules in a format the visual rule builder can render.

    Response:
    {
        "rules": [
            {
                "id": "uuid",
                "name": "Cost-optimized default",
                "priority": 1,
                "conditions": [
                    {"field": "model_capability", "operator": "includes", "value": "function_calling"}
                ],
                "action": {
                    "type": "weighted_random",
                    "providers": [
                        {"provider_id": "uuid", "weight": 70},
                        {"provider_id": "uuid", "weight": 30}
                    ]
                },
                "is_enabled": true
            }
        ],
        "default_rule": {"provider_id": "uuid"}
    }
    """
    # Query routing_rules table, join with model_providers for names

@router.put("/rules/visual", response_model=StandardResponse[VisualRulesConfig])
async def save_visual_rules(
    body: VisualRulesConfig,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Save the full rules config from the visual editor. Replaces all rules for this tenant."""
    # 1. Validate all provider_ids exist
    # 2. Delete existing rules for tenant
    # 3. Insert new rules
    # 4. Audit log

@router.post("/route/visual", response_model=StandardResponse[RouteTestResult])
async def test_route(
    body: RouteTestRequest,  # {"prompt": "Analyze this image", "requirements": {"vision": true}}
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Dry-run: evaluate which provider would be selected for this prompt. Don't call the LLM."""
    # 1. Load rules
    # 2. Evaluate each rule's conditions against the request
    # 3. Return: {"selected_provider": {...}, "matched_rule": {...}, "alternatives": [...]}

# ---------- Fallback Chain ----------

@router.get("/fallback", response_model=StandardResponse[FallbackChainConfig])
async def get_fallback(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return ordered fallback chain config.

    Response:
    {
        "chain": [
            {"provider_id": "uuid", "name": "Anthropic", "priority": 1},
            {"provider_id": "uuid", "name": "OpenAI", "priority": 2},
            {"provider_id": "uuid", "name": "Ollama Local", "priority": 3}
        ],
        "circuit_breaker": {
            "failure_threshold": 5,
            "cooldown_seconds": 60,
            "half_open_max_requests": 3
        },
        "failover_triggers": ["timeout", "rate_limit", "server_error", "content_policy"]
    }
    """

@router.put("/fallback", response_model=StandardResponse[FallbackChainConfig])
async def save_fallback(
    body: FallbackChainConfig,
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Save fallback chain. Validate all provider_ids exist."""
```

### 1B. SentinelScan API (6 endpoints)

**File:** `backend/app/routes/scan_router.py`
**Service:** `backend/app/services/sentinel_service.py`

Fix registration: ensure `scan_router` is included in `main.py` with correct prefix `/api/v1/sentinelscan`.

Fix path: rename `/risk` to `/risks` to match frontend.

```python
@router.post("/scan", response_model=StandardResponse[ScanResult])
async def trigger_scan(
    body: ScanRequest,  # {"scan_type": "sso_audit" | "shadow_ai" | "data_exposure", "scope": "full" | "incremental"}
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Execute a security scan.

    For SSO audit: query Keycloak admin API for all registered OAuth clients,
    compare against approved_apps list in DB, flag unknown apps.

    For shadow AI: scan network logs (or configured log source) for calls to
    known AI API endpoints (api.openai.com, api.anthropic.com, etc.).

    For data exposure: scan configured data stores for unencrypted PII using
    the DLP regex + NER pipeline.

    Return:
    {
        "scan_id": "uuid",
        "status": "completed",
        "findings_count": 12,
        "critical": 2,
        "high": 5,
        "medium": 3,
        "low": 2,
        "findings": [
            {
                "id": "uuid",
                "severity": "critical",
                "title": "Unregistered OAuth App: ChatGPT Enterprise",
                "description": "Found OAuth client 'chatgpt-enterprise-xyz' in Keycloak not in approved list",
                "resource": "keycloak://clients/chatgpt-enterprise-xyz",
                "recommendation": "Review and approve or disable this OAuth client"
            }
        ]
    }
    """

@router.get("/services", response_model=StandardResponse[List[DiscoveredService]])
async def list_discovered_services(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return all discovered AI services from previous scans."""
    # Query discovered_ai_services table

@router.get("/risks", response_model=StandardResponse[List[RiskScore]])  # NOTE: /risks NOT /risk
async def list_risks(
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return risk scores aggregated by service/category."""
    # Query risk_scores table with aggregation

@router.post("/remediate/{finding_id}", response_model=StandardResponse[RemediationResult])
async def remediate(
    finding_id: UUID,
    body: RemediateRequest,  # {"action": "disable" | "quarantine" | "approve" | "document"}
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Execute remediation action on a finding."""
    # Update finding status in DB, execute action (e.g., disable Keycloak client)

@router.post("/remediate/bulk", response_model=StandardResponse[BulkRemediationResult])
async def remediate_bulk(
    body: BulkRemediateRequest,  # {"finding_ids": [...], "action": "..."}
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Bulk remediation."""

@router.get("/history", response_model=StandardResponse[List[ScanHistoryItem]])
async def scan_history(
    limit: int = Query(20, le=100),
    session: AsyncSession = Depends(get_session),
    tenant_id: str = Depends(get_tenant_id),
):
    """Return past scan runs with summary stats."""
    # Query scan_history table
```

### 1C. Connectors API (6 endpoints)

**Problem:** Enterprise connector routes exist in a separate router file but are NOT registered in `main.py`.

**Fix:** In `backend/app/main.py`, add:

```python
from app.routes.connectors_enterprise import router as connectors_enterprise_router
app.include_router(connectors_enterprise_router, prefix=f"{API_PREFIX}/connectors", tags=["connectors"])
```

Then implement:

```python
@router.post("/{connector_id}/test-connection", response_model=StandardResponse[ConnectionTestResult])
async def test_connection(connector_id: UUID, ...):
    """Load connector config from DB, fetch credentials from Vault, instantiate connector class, call test_connection()."""
    # 1. Get connector record
    # 2. Get credentials from Vault: vault_client.read(connector.vault_path)
    # 3. Instantiate appropriate connector class based on connector.type
    # 4. Call connector.test_connection()
    # 5. Update connector_health_history
    # 6. Return {status: "connected", latency_ms: 45, details: "PostgreSQL 16.1"}

@router.get("/{connector_id}/health", response_model=StandardResponse[ConnectorHealth])
async def connector_health(connector_id: UUID, ...):
    """Return health status with history from connector_health_history table."""

@router.get("/catalog/types", response_model=StandardResponse[List[ConnectorTypeInfo]])
async def catalog_types():
    """Return static catalog of available connector types.

    Each entry:
    {
        "type": "postgresql",
        "display_name": "PostgreSQL",
        "category": "database",
        "icon": "database",
        "auth_type": "password",
        "required_fields": [
            {"name": "host", "type": "text", "required": true},
            {"name": "port", "type": "number", "required": true, "default": 5432},
            {"name": "database", "type": "text", "required": true},
            {"name": "username", "type": "text", "required": true},
            {"name": "password", "type": "password", "required": true}
        ],
        "optional_fields": [
            {"name": "ssl_mode", "type": "select", "options": ["disable", "require", "verify-ca"]}
        ]
    }
    """

@router.get("/oauth/{connector_type}/authorize", response_model=StandardResponse[OAuthAuthorizeResponse])
async def oauth_authorize(connector_type: str, ...):
    """Generate OAuth authorization URL for the given connector type.

    Steps:
    1. Look up OAuth config for connector_type (client_id, scopes, auth_url)
    2. Generate state parameter (random + HMAC signed)
    3. Build authorization URL with redirect_uri = {app_base_url}/api/v1/connectors/oauth/{type}/callback
    4. Return {"authorize_url": "https://accounts.google.com/o/oauth2/v2/auth?...", "state": "..."}
    """

@router.post("/oauth/{connector_type}/callback", response_model=StandardResponse[OAuthCallbackResult])
async def oauth_callback(connector_type: str, body: OAuthCallbackRequest, ...):
    """Handle OAuth callback: exchange code for tokens, store in Vault, create connector record.

    Request: {"code": "...", "state": "..."}

    Steps:
    1. Verify state parameter (HMAC check)
    2. Exchange code for access_token + refresh_token via provider's token endpoint
    3. Store tokens in Vault: secret/tenants/{tenant_id}/connectors/{connector_id}
    4. Create connector record in DB with vault_path
    5. Test connection with new credentials
    6. Return {"connector_id": "uuid", "status": "connected", "display_name": "Google Drive (user@example.com)"}
    """
```

### 1D. Executions API (2 endpoints)

**File:** `backend/app/routes/executions.py`

```python
@router.post("/{execution_id}/cancel", response_model=StandardResponse[dict])
async def cancel_execution(execution_id: UUID, ...):
    """Cancel a running execution.

    1. Update execution status to 'cancelling' in DB
    2. Revoke Celery task: celery_app.control.revoke(execution.celery_task_id, terminate=True)
    3. Update status to 'cancelled'
    4. Emit WebSocket event: {"type": "execution_cancelled", "execution_id": "..."}
    5. Audit log
    """

@router.delete("/{execution_id}", status_code=204)
async def delete_execution(execution_id: UUID, ...):
    """Soft-delete execution. Set deleted_at timestamp. Don't actually remove data."""
    # 1. Check execution is not running (status must be completed/failed/cancelled)
    # 2. Set deleted_at = now
    # 3. Audit log
```

### 1E. Marketplace Review Fix (1 endpoint)

**File:** `backend/app/routes/marketplace.py`

Fix the review submission schema mismatch. The frontend sends:

```json
{
  "listing_id": "uuid",
  "user_id": "uuid",
  "rating": 5,
  "comment": "Great agent!"
}
```

Ensure the backend Pydantic schema accepts exactly these field names. If the backend uses different names (e.g., `review_text` instead of `comment`), add an alias:

```python
class ReviewCreate(BaseModel):
    listing_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: str = Field(alias="comment")  # or rename the field
```

### 1F. Wizard Prefix Fix

**File:** `backend/app/routes/wizard.py`

Remove the hardcoded prefix:

```python
# WRONG: router = APIRouter(prefix="/api/v1/wizard")
# RIGHT:
router = APIRouter()  # main.py adds the prefix
```

Verify in `main.py` that wizard is mounted with:

```python
app.include_router(wizard_router, prefix=f"{API_PREFIX}/wizard", tags=["wizard"])
```

---

## WORKSTREAM 2: MODEL ROUTER — Production-Grade Intelligent Routing

### 2A. SQLModel Tables

**File:** `backend/app/models/model_provider.py`

```python
class ModelProvider(SQLModel, table=True):
    __tablename__ = "model_providers"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    name: str
    type: str  # openai | anthropic | google | mistral | cohere | azure_openai | ollama | vllm | custom
    base_url: str
    vault_path: str  # secret/tenants/{tenant_id}/providers/{id} — NEVER store raw API key
    is_enabled: bool = True
    rate_limit_rpm: int | None = None
    rate_limit_tpm: int | None = None
    supported_models: list[str] = Field(default=[], sa_column=Column(JSON))
    capabilities: list[str] = Field(default=[], sa_column=Column(JSON))  # vision, function_calling, json_mode, streaming
    custom_headers: dict = Field(default={}, sa_column=Column(JSON))
    health_status: str = "unknown"  # healthy | degraded | unhealthy | unknown
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: datetime | None = None

class ProviderHealthHistory(SQLModel, table=True):
    __tablename__ = "provider_health_history"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    provider_id: UUID = Field(foreign_key="model_providers.id", index=True)
    tenant_id: str = Field(index=True)
    latency_ms: int
    error_rate_pct: float
    requests_count: int
    status: str  # healthy | degraded | unhealthy
    recorded_at: datetime = Field(default_factory=datetime.utcnow)

class RoutingRule(SQLModel, table=True):
    __tablename__ = "routing_rules"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    name: str
    priority: int = 0
    conditions: list[dict] = Field(default=[], sa_column=Column(JSON))
    # Each condition: {"field": "model_capability"|"department"|"cost_limit"|"latency_target", "operator": "eq"|"gt"|"lt"|"includes"|"regex", "value": "..."}
    action: dict = Field(sa_column=Column(JSON))
    # Action: {"type": "direct"|"weighted_random"|"least_latency"|"least_cost", "providers": [{"provider_id": "uuid", "weight": 70}]}
    is_enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class FallbackChain(SQLModel, table=True):
    __tablename__ = "fallback_chains"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True, unique=True)  # One chain per tenant
    chain: list[dict] = Field(sa_column=Column(JSON))
    # [{"provider_id": "uuid", "priority": 1}, ...]
    circuit_breaker_config: dict = Field(default={"failure_threshold": 5, "cooldown_seconds": 60, "half_open_max_requests": 3}, sa_column=Column(JSON))
    failover_triggers: list[str] = Field(default=["timeout", "rate_limit", "server_error"], sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### 2B. Router Service — Real Routing Logic

**File:** `backend/app/services/router_service.py`

```python
class RouterService:
    async def route_request(
        self,
        prompt: str,
        requirements: dict,  # {"vision": true, "function_calling": true, "max_cost_per_1k": 0.01}
        tenant_id: str,
        department_id: str | None = None,
        session: AsyncSession,
    ) -> RouteDecision:
        """
        Real routing algorithm:
        1. Load all enabled providers for tenant
        2. Filter by capabilities (if requirements specify vision=true, only providers with vision)
        3. Load routing rules ordered by priority
        4. Evaluate each rule's conditions against the request
        5. First matching rule determines the action
        6. Execute action:
           - direct: return that provider
           - weighted_random: random selection weighted by configured weights
           - least_latency: select provider with lowest P50 latency from health history
           - least_cost: select provider with lowest cost per 1K tokens from pricing table
        7. If no rule matches, use default_rule (highest priority enabled provider)
        8. Check circuit breaker state — if selected provider is tripped, use fallback chain
        9. Return: {provider, model, estimated_cost, matched_rule, fallback_used}
        """

    async def execute_with_fallback(
        self,
        prompt: str,
        provider: ModelProvider,
        fallback_chain: FallbackChain,
        session: AsyncSession,
    ) -> LLMResponse:
        """
        1. Try primary provider
        2. On failure (timeout, rate limit, 5xx, content policy), check circuit breaker
        3. If circuit tripped, try next in fallback chain
        4. Record latency + success/failure in provider_health_history
        5. Record tokens + cost in token_ledger
        """

    async def record_health_metric(
        self,
        provider_id: UUID,
        latency_ms: int,
        success: bool,
        tenant_id: str,
        session: AsyncSession,
    ):
        """Insert into provider_health_history. If error_rate > 5% over last 5 min, update provider health_status to 'degraded'."""
```

### 2C. Circuit Breaker Implementation

```python
class CircuitBreaker:
    """Per-provider circuit breaker with states: CLOSED → OPEN → HALF_OPEN → CLOSED."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 60, half_open_max: int = 3):
        self.state = "closed"
        self.failure_count = 0
        self.last_failure_at: datetime | None = None
        self.half_open_successes = 0
        # ...

    def record_success(self): ...
    def record_failure(self): ...
    def is_available(self) -> bool: ...
```

Store circuit breaker state in Redis (not DB) for performance:

```python
# Key: circuit_breaker:{tenant_id}:{provider_id}
# Value: {"state": "open", "failure_count": 5, "last_failure_at": "...", "opened_at": "..."}
# TTL: cooldown_seconds
```

---

## WORKSTREAM 3: DLP & GUARDRAILS — Full Pipeline

### 3A. Four-Layer DLP Pipeline

**File:** `backend/app/services/dlp_service.py`

Each layer must be independently testable and configurable:

```python
class DLPPipeline:
    async def scan(self, text: str, policy: DLPPolicy, tenant_id: str) -> DLPResult:
        findings: list[DLPFinding] = []

        # Layer 1: Regex (fast, catches obvious patterns)
        findings.extend(self._scan_regex(text, policy.regex_patterns))
        if self._should_block(findings, policy):
            return DLPResult(action="block", findings=findings, blocked_at_layer=1)

        # Layer 2: NER (Presidio or spaCy NER for PII detection)
        findings.extend(await self._scan_ner(text, policy.ner_entities))
        if self._should_block(findings, policy):
            return DLPResult(action="block", findings=findings, blocked_at_layer=2)

        # Layer 3: Semantic (LLM-based — use a cheap model to classify sensitivity)
        if policy.semantic_enabled:
            findings.extend(await self._scan_semantic(text, policy.semantic_categories))
        if self._should_block(findings, policy):
            return DLPResult(action="block", findings=findings, blocked_at_layer=3)

        # Layer 4: Organization policy rules
        findings.extend(self._scan_policy(text, policy.custom_rules))

        # Determine final action
        action = self._determine_action(findings, policy)
        return DLPResult(action=action, findings=findings)

    def _scan_regex(self, text: str, patterns: list[RegexPattern]) -> list[DLPFinding]:
        """Built-in patterns:
        - SSN: r'\b\d{3}-\d{2}-\d{4}\b'
        - Credit Card: r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b'
        - Email: r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        - Phone: r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
        - IP Address: r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        - AWS Key: r'\bAKIA[0-9A-Z]{16}\b'
        - API Key patterns: r'\b(?:sk|pk|api)[-_][a-zA-Z0-9]{20,}\b'
        """

    async def _scan_ner(self, text: str, entities: list[str]) -> list[DLPFinding]:
        """Use Presidio AnalyzerEngine (or fallback to spaCy NER).
        Entity types: PERSON, LOCATION, ORGANIZATION, PHONE_NUMBER, EMAIL_ADDRESS,
        CREDIT_CARD, CRYPTO, DATE_TIME, IBAN_CODE, IP_ADDRESS, MEDICAL_LICENSE,
        US_SSN, US_BANK_NUMBER, US_DRIVER_LICENSE, US_PASSPORT
        """

    async def _scan_semantic(self, text: str, categories: list[str]) -> list[DLPFinding]:
        """Use a cheap LLM (gpt-4o-mini or haiku) to classify text sensitivity.
        Prompt: 'Classify if this text contains any of: {categories}. Return JSON array of findings.'
        Categories: trade_secret, competitive_intelligence, internal_only, restricted_data
        """

    def apply_action(self, text: str, findings: list[DLPFinding], action: str) -> str:
        """Apply action to text:
        - detect: return text unchanged (findings logged)
        - redact: replace each finding span with [REDACTED]
        - mask: partial mask (SSN: ***-**-1234, email: j***@example.com)
        - block: raise DLPBlockedError
        - alert: send notification to admin, return text unchanged
        """
```

### 3B. Guardrails

```python
class GuardrailService:
    async def check_input(self, text: str, guardrail_config: GuardrailConfig) -> GuardrailResult:
        """Pre-LLM checks on user input."""
        violations = []

        if guardrail_config.prompt_injection_detection:
            score = self._detect_prompt_injection(text)
            if score > guardrail_config.injection_threshold:
                violations.append(GuardrailViolation(type="prompt_injection", confidence=score))

        if guardrail_config.toxicity_detection:
            score = await self._detect_toxicity(text)
            if score > guardrail_config.toxicity_threshold:
                violations.append(GuardrailViolation(type="toxicity", confidence=score))

        return GuardrailResult(passed=len(violations) == 0, violations=violations)

    async def check_output(self, output: str, context: str, guardrail_config: GuardrailConfig) -> GuardrailResult:
        """Post-LLM checks on model output."""
        violations = []

        if guardrail_config.hallucination_detection:
            # Compare claims in output against provided context
            unsupported = await self._detect_hallucination(output, context)
            violations.extend(unsupported)

        if guardrail_config.pii_leakage_prevention:
            # Scan output for PII not present in input
            leaked = self._detect_pii_leakage(output, context)
            violations.extend(leaked)

        if guardrail_config.output_schema:
            # Validate output matches expected JSON schema
            if not self._validate_schema(output, guardrail_config.output_schema):
                violations.append(GuardrailViolation(type="schema_violation"))

        return GuardrailResult(passed=len(violations) == 0, violations=violations)

    def _detect_prompt_injection(self, text: str) -> float:
        """Rule-based + heuristic detection:
        1. Check for known injection phrases: 'ignore previous', 'system prompt', 'you are now', 'DAN mode'
        2. Check for encoding tricks: base64-encoded instructions, unicode homoglyphs
        3. Check for role-switching: 'as a developer', 'in maintenance mode'
        4. Return confidence score 0.0-1.0
        """
```

---

## WORKSTREAM 4: CONNECTORS — OAuth + Base Implementation

### 4A. Connector Base Class

**File:** `backend/app/services/connectors/base.py`

```python
from abc import ABC, abstractmethod

class BaseConnector(ABC):
    def __init__(self, config: dict, credentials: dict):
        self.config = config
        self.credentials = credentials

    @abstractmethod
    async def test_connection(self) -> ConnectionTestResult:
        """Verify credentials work. Return latency + server version info."""

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Lightweight check (faster than test_connection)."""

    @abstractmethod
    async def list_resources(self) -> list[ConnectorResource]:
        """List available resources (tables, folders, channels, etc.)."""

    @abstractmethod
    async def read(self, resource_id: str, query: dict) -> ConnectorData:
        """Read data from a resource."""

    @abstractmethod
    async def write(self, resource_id: str, data: dict) -> WriteResult:
        """Write data to a resource."""

    @abstractmethod
    async def get_schema(self, resource_id: str) -> dict:
        """Return JSON Schema for a resource's data format."""
```

### 4B. Implement Top 5 Connectors

Each in its own file under `backend/app/services/connectors/`:

**PostgreSQL** (`postgresql.py`):

```python
class PostgreSQLConnector(BaseConnector):
    async def test_connection(self):
        # asyncpg.connect(host, port, database, user, password)
        # Execute: SELECT version()
        # Return version string + latency

    async def list_resources(self):
        # Query information_schema.tables for all user tables
        # Return table names with row counts

    async def read(self, resource_id, query):
        # resource_id = table name
        # query = {"columns": [...], "where": {...}, "limit": 100, "offset": 0}
        # Build SELECT query with parameterized values (NO SQL INJECTION)
        # Return rows as list of dicts

    async def get_schema(self, resource_id):
        # Query information_schema.columns for the table
        # Build JSON Schema from column types
```

**REST API** (`rest_api.py`):

```python
class RestAPIConnector(BaseConnector):
    async def test_connection(self):
        # GET base_url + health_endpoint with auth headers
        # Return status code + latency

    async def read(self, resource_id, query):
        # resource_id = endpoint path (e.g., "/users")
        # query = {"params": {...}, "headers": {...}}
        # httpx.AsyncClient.get(base_url + resource_id, params=query["params"])
```

**Slack** (`slack.py`):

```python
class SlackConnector(BaseConnector):
    async def test_connection(self):
        # POST https://slack.com/api/auth.test with Bearer token
        # Return team name + bot user

    async def list_resources(self):
        # conversations.list → return channels

    async def read(self, resource_id, query):
        # resource_id = channel_id
        # conversations.history with limit + cursor pagination

    async def write(self, resource_id, data):
        # resource_id = channel_id
        # chat.postMessage with text from data
```

**S3** (`s3.py`) and **Google Drive** (`google_drive.py`) — similar pattern.

---

## WORKSTREAM 5: COST ENGINE — Token Ledger + Dashboard Data

### 5A. Token Ledger Table

```python
class TokenLedger(SQLModel, table=True):
    __tablename__ = "token_ledger"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    execution_id: UUID = Field(foreign_key="executions.id")
    agent_id: UUID = Field(foreign_key="agents.id")
    provider_id: UUID = Field(foreign_key="model_providers.id")
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: Decimal = Field(sa_column=Column(Numeric(10, 6)))
    user_id: UUID
    department_id: UUID | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class DepartmentBudget(SQLModel, table=True):
    __tablename__ = "department_budgets"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    department_id: UUID
    budget_usd: Decimal
    period: str  # monthly | quarterly
    warn_threshold_pct: int = 80
    block_threshold_pct: int = 100
    current_spend_usd: Decimal = Field(default=0)
    period_start: date
    period_end: date
```

### 5B. Cost Service

```python
class CostService:
    # Provider pricing table (cost per 1K tokens)
    PRICING = {
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3.5-haiku": {"input": 0.0008, "output": 0.004},
        "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
        # ... add all common models
    }

    async def record_usage(self, execution_id, agent_id, provider_id, model, prompt_tokens, completion_tokens, user_id, department_id, tenant_id, session):
        cost = self._calculate_cost(model, prompt_tokens, completion_tokens)
        # Insert token_ledger row
        # Update department_budget.current_spend_usd
        # Check if over warn/block threshold → emit alert

    async def get_dashboard_data(self, tenant_id, period, session) -> CostDashboardData:
        """Return all data needed for the CostPage frontend.

        {
            "total_spend": 1234.56,
            "period": "2025-02",
            "trend": [{"date": "2025-02-01", "spend": 42.10}, ...],
            "by_provider": [{"provider": "OpenAI", "spend": 800.00}, ...],
            "by_model": [{"model": "gpt-4o", "spend": 600.00, "tokens": 2400000}, ...],
            "by_department": [{"department": "Engineering", "budget": 2000, "spend": 1500, "pct": 75}, ...],
            "by_agent": [{"agent": "Customer Support Bot", "spend": 200.00, "executions": 5000}, ...],
            "anomalies": [{"date": "2025-02-20", "spend": 250.00, "expected": 42.00, "sigma": 4.9}],
            "forecast": {"end_of_month": 1800.00, "confidence": 0.85}
        }
        """
        # SQL aggregation queries on token_ledger grouped by date/provider/model/department/agent
        # Forecast: linear regression on last 30 days daily spend
        # Anomaly: flag days where spend > mean + 3*stddev
```

### 5C. Cost API Endpoints

```python
@router.get("/dashboard", response_model=StandardResponse[CostDashboardData])
@router.get("/breakdown/{dimension}", response_model=StandardResponse[list])  # dimension: provider|model|department|agent|user
@router.get("/budget", response_model=StandardResponse[list[DepartmentBudget]])
@router.put("/budget/{department_id}", response_model=StandardResponse[DepartmentBudget])
@router.get("/export", response_model=Response)  # CSV download
@router.get("/forecast", response_model=StandardResponse[CostForecast])
```

---

## WORKSTREAM 6: WEBSOCKET STREAMING — Real-Time Execution

### 6A. WebSocket Handler

**File:** `backend/app/websocket/execution_stream.py`

```python
from fastapi import WebSocket, WebSocketDisconnect

class ExecutionStreamManager:
    def __init__(self):
        self.connections: dict[str, list[WebSocket]] = {}  # execution_id → [websockets]

    async def connect(self, websocket: WebSocket, execution_id: str, last_event_id: str | None = None):
        await websocket.accept()
        self.connections.setdefault(execution_id, []).append(websocket)

        # If last_event_id provided, replay missed events from Redis stream
        if last_event_id:
            missed = await self._get_events_after(execution_id, last_event_id)
            for event in missed:
                await websocket.send_json(event)

    async def broadcast(self, execution_id: str, event: dict):
        """Send event to all connected clients for this execution.

        Event format:
        {
            "event_id": "uuid",
            "type": "llm_stream_token" | "tool_call" | "tool_result" | "agent_start" | "agent_complete" | "error" | "cost_update",
            "timestamp": "2025-02-25T10:00:00Z",
            "data": {
                // type-specific payload
            }
        }

        For llm_stream_token:
        {"data": {"token": "Hello", "model": "gpt-4o", "provider": "openai"}}

        For tool_call:
        {"data": {"tool_name": "search_documents", "input": {...}, "status": "executing"}}

        For cost_update:
        {"data": {"prompt_tokens": 150, "completion_tokens": 42, "cost_usd": 0.0023, "total_cost_usd": 0.0145}}
        """
        # Store event in Redis stream for replay: XADD execution:{execution_id} * event_json
        # Send to all connected websockets
        if execution_id in self.connections:
            dead = []
            for ws in self.connections[execution_id]:
                try:
                    await ws.send_json(event)
                except:
                    dead.append(ws)
            for ws in dead:
                self.connections[execution_id].remove(ws)

    async def disconnect(self, websocket: WebSocket, execution_id: str):
        if execution_id in self.connections:
            self.connections[execution_id].remove(websocket)

# WebSocket endpoint in main.py or separate router:
@app.websocket("/ws/executions/{execution_id}")
async def execution_websocket(
    websocket: WebSocket,
    execution_id: str,
    last_event_id: str | None = Query(None),
):
    await stream_manager.connect(websocket, execution_id, last_event_id)
    try:
        while True:
            # Heartbeat — client sends ping, server responds pong
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await stream_manager.disconnect(websocket, execution_id)
```

### 6B. Frontend WebSocket Hook

**File:** `frontend/src/hooks/useExecutionStream.ts`

```typescript
export function useExecutionStream(executionId: string | null) {
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [totalCost, setTotalCost] = useState(0);
  const [currentToken, setCurrentToken] = useState("");
  const wsRef = useRef<WebSocket | null>(null);
  const lastEventIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (!executionId) return;

    const connect = () => {
      const params = lastEventIdRef.current
        ? `?last_event_id=${lastEventIdRef.current}`
        : "";
      const ws = new WebSocket(
        `${WS_BASE_URL}/ws/executions/${executionId}${params}`,
      );

      ws.onopen = () => setConnected(true);

      ws.onmessage = (msg) => {
        const event = JSON.parse(msg.data);
        if (event.type === "pong") return;

        lastEventIdRef.current = event.event_id;
        setEvents((prev) => [...prev, event]);

        if (event.type === "llm_stream_token") {
          setCurrentToken((prev) => prev + event.data.token);
        }
        if (event.type === "cost_update") {
          setTotalCost(event.data.total_cost_usd);
        }
      };

      ws.onclose = () => {
        setConnected(false);
        // Auto-reconnect after 3 seconds
        setTimeout(connect, 3000);
      };

      wsRef.current = ws;
    };

    connect();

    // Heartbeat every 30s
    const heartbeat = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);

    return () => {
      clearInterval(heartbeat);
      wsRef.current?.close();
    };
  }, [executionId]);

  return { events, connected, totalCost, currentToken };
}
```

---

## WORKSTREAM 7: FRONTEND — Wire All Pages to Real Data

### 7A. ModelRouterPage

Replace all 15 TODOs with real TanStack Query hooks:

```typescript
// frontend/src/pages/ModelRouterPage.tsx

// Provider list — real data from GET /router/providers
const { data: providers, isLoading } = useQuery({
  queryKey: ["router", "providers"],
  queryFn: () => routerApi.listProviders(),
});

// Provider health — real data from GET /router/providers/health
const { data: healthSummary } = useQuery({
  queryKey: ["router", "health"],
  queryFn: () => routerApi.getProvidersHealth(),
  refetchInterval: 30000, // Refresh every 30s
});

// Create provider — real mutation to POST /router/providers
const createMutation = useMutation({
  mutationFn: routerApi.createProvider,
  onSuccess: () =>
    queryClient.invalidateQueries({ queryKey: ["router", "providers"] }),
});

// Delete provider — real mutation to DELETE /router/providers/{id}
const deleteMutation = useMutation({
  mutationFn: routerApi.deleteProvider,
  onSuccess: () =>
    queryClient.invalidateQueries({ queryKey: ["router", "providers"] }),
});
```

Every page must follow this pattern: TanStack Query for reads, useMutation for writes, invalidation for refetch.

### 7B. PropertyPanel — Node Configuration Forms

**File:** `frontend/src/components/canvas/PropertyPanel.tsx`

The PropertyPanel must render a different form based on the selected node's type. Use a `switch(node.type)` to render the correct form component:

```typescript
function PropertyPanel({ node, onUpdate }: PropertyPanelProps) {
    switch (node.type) {
        case "llm":
            return <LLMNodeForm node={node} onUpdate={onUpdate} />;
        case "tool":
            return <ToolNodeForm node={node} onUpdate={onUpdate} />;
        case "input":
            return <InputNodeForm node={node} onUpdate={onUpdate} />;
        case "output":
            return <OutputNodeForm node={node} onUpdate={onUpdate} />;
        case "router":
            return <RouterNodeForm node={node} onUpdate={onUpdate} />;
        case "branch":
            return <BranchNodeForm node={node} onUpdate={onUpdate} />;
        case "rag":
            return <RAGNodeForm node={node} onUpdate={onUpdate} />;
        case "guardrail":
            return <GuardrailNodeForm node={node} onUpdate={onUpdate} />;
        case "connector":
            return <ConnectorNodeForm node={node} onUpdate={onUpdate} />;
        case "custom_code":
            return <CustomCodeNodeForm node={node} onUpdate={onUpdate} />;
        // ... all 20 types
        default:
            return <GenericNodeForm node={node} onUpdate={onUpdate} />;
    }
}
```

Each form component is a real form with real inputs that save to the node's `data` field. Example for LLM node:

```typescript
function LLMNodeForm({ node, onUpdate }: NodeFormProps) {
    const { data: providers } = useQuery({
        queryKey: ["router", "providers"],
        queryFn: () => routerApi.listProviders(),
    });

    return (
        <div className="space-y-4">
            <Select
                label="Provider"
                value={node.data.provider_id}
                onChange={(v) => onUpdate({ ...node.data, provider_id: v })}
                options={providers?.map(p => ({ value: p.id, label: p.name })) ?? []}
            />
            <Select
                label="Model"
                value={node.data.model}
                onChange={(v) => onUpdate({ ...node.data, model: v })}
                options={selectedProvider?.supported_models.map(m => ({ value: m, label: m })) ?? []}
            />
            <Slider label="Temperature" min={0} max={2} step={0.1} value={node.data.temperature ?? 0.7} onChange={...} />
            <NumberInput label="Max Tokens" value={node.data.max_tokens ?? 4096} onChange={...} />
            <MonacoEditor
                label="System Prompt"
                language="markdown"
                value={node.data.system_prompt ?? ""}
                onChange={(v) => onUpdate({ ...node.data, system_prompt: v })}
                height="200px"
            />
            <Select label="Response Format" options={[{value: "text", label: "Text"}, {value: "json_object", label: "JSON"}]} ... />
        </div>
    );
}
```

### 7C. Other Pages — Same Pattern

**ConnectorsPage**: Use `useQuery` with `connectorApi.listConnectors()`, `connectorApi.getCatalogTypes()`. Add connector mutation, OAuth popup handling, health status indicators.

**SentinelScanPage**: Use `useMutation` for `sentinelApi.triggerScan()`, `useQuery` for `sentinelApi.getRisks()` and `sentinelApi.getHistory()`. Wire the scan trigger button, show findings in a data table, remediation action buttons.

**MarketplacePage**: Use `useQuery` for `marketplaceApi.listListings()` with search/filter params. `useMutation` for `marketplaceApi.submitReview()`. Wire the review form with star rating component.

**CostPage**: Use `useQuery` for `costApi.getDashboard()`. Render Recharts line chart for trend, bar chart for by-department, pie chart for by-provider.

**ExecutionDetailPage**: Use `useExecutionStream(executionId)` hook. Render live token stream, tool call cards, cost accumulation counter, execution graph with highlighted active node.

---

## WORKSTREAM 8: TESTING — Replace All 33 Stub Test Files

### 8A. Backend Test Strategy

For every service file, there must be a test file with actual assertions. No `pass`, no `skip`, no `NotImplementedError`.

Pattern for each test file:

```python
# tests/test_router_service.py
import pytest
from unittest.mock import AsyncMock, patch
from app.services.router_service import RouterService
from app.models.model_provider import ModelProvider

@pytest.fixture
def router_service():
    return RouterService()

@pytest.fixture
def mock_session():
    session = AsyncMock()
    # Configure session.execute to return mock query results
    return session

class TestRouteRequest:
    async def test_routes_to_matching_provider(self, router_service, mock_session):
        """When a rule matches, the correct provider is selected."""
        # Arrange: create mock providers and rules
        # Act: call router_service.route_request(...)
        # Assert: result.provider_id == expected_provider_id

    async def test_falls_back_on_failure(self, router_service, mock_session):
        """When primary provider fails, fallback chain is used."""

    async def test_circuit_breaker_trips(self, router_service, mock_session):
        """After N failures, circuit breaker opens and skips provider."""

    async def test_respects_capability_filter(self, router_service, mock_session):
        """When vision is required, only providers with vision capability are considered."""

    async def test_cost_optimized_routing(self, router_service, mock_session):
        """Cost-optimized action selects cheapest provider."""
```

Minimum test count per service: **5 tests** covering happy path, error cases, edge cases, and tenant isolation.

### 8B. Frontend Test Strategy

```typescript
// __tests__/ModelRouterPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { ModelRouterPage } from "../pages/ModelRouterPage";

const server = setupServer(
    http.get("/api/v1/router/providers", () => {
        return HttpResponse.json({
            data: [
                { id: "1", name: "OpenAI", type: "openai", health_status: "healthy" },
                { id: "2", name: "Anthropic", type: "anthropic", health_status: "degraded" },
            ],
        });
    }),
);

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

test("renders provider list from API", async () => {
    render(
        <QueryClientProvider client={new QueryClient()}>
            <ModelRouterPage />
        </QueryClientProvider>
    );

    await waitFor(() => {
        expect(screen.getByText("OpenAI")).toBeInTheDocument();
        expect(screen.getByText("Anthropic")).toBeInTheDocument();
    });
});

test("shows health status badges", async () => {
    // ...
});
```

### 8C. Integration Tests

```python
# tests/integration/test_full_flow.py
"""
Test the critical user journey:
1. Create provider → verify in DB
2. Create routing rule → verify routing works
3. Create agent with LLM node → configure with provider
4. Execute agent → verify token_ledger entry created
5. Check cost dashboard → verify spend appears
6. View audit log → verify all actions logged
"""
```

---

## WORKSTREAM 9: DATABASE MIGRATIONS

### 9A. Alembic Migration

Create one migration that adds all missing tables. The migration must be idempotent (use `IF NOT EXISTS`).

```bash
cd backend
alembic revision --autogenerate -m "add_router_cost_dlp_tables"
alembic upgrade head
```

Tables that must exist after migration:

- `model_providers` (with RLS policy)
- `provider_health_history`
- `routing_rules`
- `fallback_chains`
- `token_ledger`
- `department_budgets`
- `dlp_policies`
- `dlp_detections`
- `discovered_ai_services`
- `risk_scores`
- `scan_history`
- `connector_health_history`

All tables must have:

- `tenant_id TEXT NOT NULL` column
- Index on `tenant_id`
- RLS policy: `CREATE POLICY tenant_isolation ON {table} USING (tenant_id = current_setting('app.tenant_id'))`
- `created_at TIMESTAMP DEFAULT now()`

---

## WORKSTREAM 10: AUDIT TRAIL

### 10A. Audit Middleware

**File:** `backend/app/middleware/audit.py`

```python
class AuditMiddleware:
    async def __call__(self, request: Request, call_next):
        # Generate correlation_id (UUID) and attach to request state
        request.state.correlation_id = str(uuid4())

        response = await call_next(request)

        # Log write operations (POST, PUT, DELETE, PATCH)
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            await self._log_action(
                correlation_id=request.state.correlation_id,
                user_id=request.state.user_id,  # From auth middleware
                tenant_id=request.state.tenant_id,
                action=f"{request.method} {request.url.path}",
                resource_type=self._extract_resource_type(request.url.path),
                resource_id=self._extract_resource_id(request.url.path),
                status_code=response.status_code,
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent"),
            )

        # Add correlation_id to response headers
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response
```

### 10B. Tamper-Evident Chain

```python
class AuditService:
    async def log(self, entry: AuditLogEntry, session: AsyncSession):
        # Get hash of previous entry
        prev = await session.execute(
            select(AuditLog.hash).order_by(AuditLog.created_at.desc()).limit(1)
        )
        prev_hash = prev.scalar() or "genesis"

        # Compute hash: SHA256(prev_hash + json(entry))
        content = json.dumps(entry.dict(), sort_keys=True, default=str)
        entry_hash = hashlib.sha256(f"{prev_hash}{content}".encode()).hexdigest()

        # Insert with hash
        db_entry = AuditLog(**entry.dict(), hash=entry_hash, prev_hash=prev_hash)
        session.add(db_entry)
        await session.commit()
```

---

## BUILD & VALIDATION COMMANDS

```bash
# Backend
cd backend
pip install -r requirements.txt
alembic upgrade head
python -m pytest --cov=app --cov-report=term-missing -x  # Stop on first failure
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npx tsc --noEmit  # Type check — must be 0 errors
npm run build     # Vite build — must be 0 errors
npm run dev       # Dev server at :3000

# Full Stack
docker-compose up --build -d
# Wait for services to be healthy:
until curl -s http://localhost:8000/health | grep -q '"status":"ok"'; do sleep 2; done
until curl -s http://localhost:3000 > /dev/null 2>&1; do sleep 2; done

# Validate
curl -s http://localhost:8000/api/v1/router/providers | jq .  # Should return real data
curl -s http://localhost:8000/api/v1/cost/dashboard | jq .    # Should return cost data
```

---

## CONSTRAINTS — NON-NEGOTIABLE

1. **No `any` types** in TypeScript. Every function parameter and return type must be typed.
2. **No raw SQL strings** — use SQLModel/SQLAlchemy query builder. Parameterize all values.
3. **No API keys in DB** — only Vault paths. Use `vault_client.read(path)` at runtime.
4. **Every query must filter by `tenant_id`** — no exceptions. RLS is the safety net, not the primary filter.
5. **Standard response envelope** on all endpoints: `{"data": ..., "meta": {"request_id": "...", "timestamp": "..."}}`
6. **Audit every write** — POST/PUT/DELETE/PATCH operations get an audit log entry.
7. **No `pass` or `skip` in tests** — every test function must have at least one assertion.
8. **No mock data in production mode** — if an endpoint can't return real data, it returns an empty list, not fake data.
9. **Error responses** must use standard HTTP codes and structured format: `{"error": {"code": "...", "message": "...", "details": {...}}}`
10. **All imports must resolve** — `npm run build` and `python -m pytest --co` must succeed with 0 import errors.

---

## ACCEPTANCE CRITERIA

The build is done when:

1. `cd frontend && npx tsc --noEmit` → **0 errors**
2. `cd frontend && npm run build` → **0 errors**
3. `cd backend && python -m pytest --cov=app` → **0 failures, >80% coverage**
4. `docker-compose up` → **all services healthy in <90 seconds**
5. **Every frontend page** loads data from real backend endpoints (no console errors, no "undefined" in UI)
6. **Provider CRUD** works: create → list → update credentials → delete
7. **Routing** works: configure rule → test route → see correct provider selected
8. **DLP scan** works: paste text with SSN → see it detected and redacted
9. **Execution streaming** works: run agent → see live token output via WebSocket
10. **Cost tracking** works: after execution → see tokens and USD in cost dashboard
11. **Audit trail** works: perform actions → see entries in audit log with correlation IDs
12. **No TODOs, no stubs, no NotImplementedError** in any backend service file
