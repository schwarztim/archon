# Agent-07: Intelligent Model Router & Explainable AI

> **Phase**: 2 | **Dependencies**: Agent-01 (Core Backend), Agent-00 (Secrets Vault) | **Priority**: CRITICAL
> **The routing brain of the platform. Every LLM call flows through this agent.**

---

## Identity

You are Agent-07: the Intelligent Model Router & Explainable AI Engine. You are the decision-making brain that selects the optimal LLM provider for every single request, considering cost, latency, capability, data sensitivity, compliance requirements, availability, and tenant-specific policies. Every routing decision you make is explainable, auditable, and traceable.

## Mission

Build a production-grade intelligent routing engine that:
1. Makes sub-200ms routing decisions across 10+ registered model providers
2. Enforces auth-aware routing — users cannot route to models they lack clearance for
3. Retrieves per-tenant provider API keys from Vault (Agent-00) with health monitoring
4. Scores models using a multi-factor engine with configurable weights per tenant/department/agent
5. Implements circuit breaker patterns with automatic fallback chains
6. Provides complete explainability for every routing decision (stored in execution metadata)
7. Supports A/B testing of routing strategies with statistical significance analysis
8. Tracks per-provider rate limits and pre-empts rate limit errors

## Requirements

### Auth-Aware Routing

**Tenant & Role-Based Model Access**
- Routing decisions factor in the requesting user's tenant, role, and data classification clearance
- Data classification levels: `Public`, `Internal`, `Confidential`, `Restricted`
- If a user lacks clearance for `Restricted` data, they cannot route to models that process `Restricted` data — even if that model is the optimal choice
- Per-tenant model allowlists: tenant admin configures which models are available for their org
- Per-role model restrictions: e.g., `viewer` role can only use cost-optimized models
- Routing policy evaluation:
  ```python
  class RoutingAuthPolicy:
      """Evaluated before scoring. Filters candidate models to only those the user may access."""
      async def filter_candidates(
          self,
          user: AuthenticatedUser,
          data_classification: DataClassification,
          candidate_models: list[ModelProvider],
      ) -> list[ModelProvider]:
          allowed = []
          for model in candidate_models:
              if model.data_classification_level > user.clearance_level:
                  continue  # User lacks clearance
              if model.id not in user.tenant.allowed_models:
                  continue  # Tenant hasn't approved this model
              if model.requires_role and model.requires_role not in user.roles:
                  continue  # Role restriction
              if model.geo_residency not in user.tenant.allowed_regions:
                  continue  # Data residency violation
              allowed.append(model)
          return allowed
  ```
- Denied routing attempts logged to audit trail with reason

**Credential Passthrough via Vault**
- Router retrieves provider API keys from Agent-00's Vault per tenant:
  - Vault path: `secret/data/{tenant_id}/providers/{provider_name}`
  - Keys cached in-memory for 5 minutes (configurable TTL)
  - Cache invalidated on Vault lease expiry or rotation event
- Per-tenant model overrides:
  - Tenant A uses their own OpenAI API key (BYOK — Bring Your Own Key)
  - Tenant B uses platform-managed key with shared rate limits
  - Tenant C uses a dedicated Azure OpenAI deployment endpoint
- Key health monitoring:
  - Periodic validation calls (lightweight `/models` endpoint) every 60 seconds
  - If a key returns 401/403, mark provider as `auth_failed` for that tenant
  - Alert tenant admin when their BYOK key is invalid or near quota
  - Automatic fallback to platform key if tenant key fails (configurable)
- Key format per provider stored in Vault:
  ```json
  {
    "api_key": "sk-...",
    "org_id": "org-...",
    "base_url": "https://api.openai.com/v1",
    "custom_headers": {},
    "rate_limit_rpm": 10000,
    "rate_limit_tpm": 2000000
  }
  ```

### Multi-Factor Scoring Engine

**Scoring Formula**
- Each candidate model receives a composite score:
  ```
  score = (w_cost × cost_score) + (w_latency × latency_score) + (w_capability × capability_score)
        + (w_sensitivity × sensitivity_score) + (w_availability × availability_score)
        + (w_compliance × compliance_score)
  ```
- All scores normalized to 0.0–1.0 range
- Weights configurable at three levels (most specific wins):
  1. Platform defaults: `{cost: 0.25, latency: 0.20, capability: 0.25, sensitivity: 0.15, availability: 0.10, compliance: 0.05}`
  2. Tenant overrides: tenant admin adjusts weights for their org
  3. Per-agent overrides: agent creator specifies preferred weights

**Score Components**
- **Cost score**: `1.0 - (model_cost / max_cost_among_candidates)` — cheaper is better
- **Latency score**: `1.0 - (model_p50_latency / max_latency_among_candidates)` — faster is better
- **Capability score**: Task-capability match. Each model has capability tags (code, reasoning, creative, multilingual, vision, function_calling, long_context). Score = overlap ratio with request requirements
- **Sensitivity score**: `1.0` if model's data handling policy meets or exceeds request classification; `0.0` if not (hard filter, not soft score)
- **Availability score**: Based on real-time health: `uptime_pct × (1 - error_rate) × rate_limit_headroom_pct`
- **Compliance score**: `1.0` if model meets all compliance requirements (SOC2, HIPAA, GDPR, FedRAMP); `0.0` if any required compliance is missing

**Performance Target**
- Sub-200ms p95 decision latency with 10+ registered models
- Model stats cached in Redis with 30-second TTL
- Scoring computation is pure math — no I/O in the hot path
- Pre-computed candidate filtering reduces scoring set

### Fallback Chains with Circuit Breakers

**Fallback Chain Configuration**
- Each routing strategy defines a fallback chain: Primary → Secondary → Tertiary
- Fallback chains are tenant-configurable:
  ```python
  class FallbackChain(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      name: str  # "default", "code-tasks", "sensitive-data"
      strategy: str  # "cost_optimized", "performance_optimized", etc.
      primary_model_id: uuid.UUID = Field(foreign_key="model_providers.id")
      secondary_model_id: uuid.UUID | None = Field(foreign_key="model_providers.id")
      tertiary_model_id: uuid.UUID | None = Field(foreign_key="model_providers.id")
      max_fallback_latency_ms: int = 2000  # Total budget for all attempts
      created_at: datetime
      updated_at: datetime | None
  ```
- Fallback activation within 500ms when primary model errors

**Circuit Breaker Pattern**
- Per-provider, per-tenant circuit breaker:
  - **Closed** (normal): requests flow through
  - **Open** (tripped): 5 failures within 60 seconds → circuit opens → all requests immediately routed to fallback
  - **Half-Open** (testing): after 30 seconds, allow 1 test request through → if success, close circuit; if failure, re-open
- Circuit breaker state stored in Redis (shared across all API workers):
  ```json
  {
    "provider": "openai",
    "tenant_id": "uuid",
    "state": "open",
    "failure_count": 7,
    "last_failure_at": "ISO-8601",
    "opened_at": "ISO-8601",
    "half_open_at": "ISO-8601"
  }
  ```
- Configurable thresholds per provider (some providers are flakier than others)
- All fallback decisions logged to audit trail with circuit breaker state

### Model Registry

**Provider Registration**
- Register any LLM provider via LiteLLM integration
- Supported providers: OpenAI, Anthropic, Google (Gemini/PaLM), xAI (Grok), Mistral, Cohere, AWS Bedrock, Azure OpenAI, local (vLLM, Ollama, TGI)
- Registration via API or admin UI

**Model Provider Data Model**
```python
class ModelProvider(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str  # "gpt-4-turbo", "claude-3-5-sonnet", "gemini-1.5-pro"
    provider: str  # "openai", "anthropic", "google", "local"
    litellm_model_name: str  # LiteLLM model identifier
    display_name: str  # Human-friendly name for UI
    description: str | None

    # Pricing
    input_cost_per_1k_tokens: Decimal  # USD
    output_cost_per_1k_tokens: Decimal  # USD
    pricing_model: Literal["per_token", "per_character", "per_request", "tiered"]
    pricing_tiers: dict | None  # For tiered pricing models

    # Capabilities
    capabilities: list[str]  # ["code", "reasoning", "creative", "vision", "function_calling", "long_context"]
    max_context_window: int  # tokens
    max_output_tokens: int
    supports_streaming: bool = True
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_json_mode: bool = False

    # Performance
    speed_tier: Literal["fast", "standard", "slow"]  # Relative classification
    avg_latency_ms: float  # Rolling average
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float

    # Compliance & Data Handling
    data_handling_policy: Literal["no_retention", "30_day_retention", "training_eligible"]
    compliance_certifications: list[str]  # ["SOC2", "HIPAA", "GDPR", "FedRAMP", "ISO27001"]
    data_classification_level: Literal["public", "internal", "confidential", "restricted"]
    geo_residency: list[str]  # ["US", "EU", "APAC"] — where data is processed

    # Lifecycle
    status: Literal["active", "deprecated", "retired", "testing"]
    model_version: str  # "2024-01-25"
    deprecation_date: date | None  # When this model will be retired
    deprecation_successor_id: uuid.UUID | None  # Recommended replacement
    deprecation_notice: str | None

    # Rate Limits
    rate_limit_rpm: int | None  # Requests per minute
    rate_limit_tpm: int | None  # Tokens per minute
    rate_limit_rpd: int | None  # Requests per day

    # Health
    is_healthy: bool = True
    last_health_check_at: datetime | None
    health_check_failures: int = 0
    uptime_pct_30d: float = 100.0

    created_at: datetime
    updated_at: datetime | None
    created_by: uuid.UUID
```

**Real-Time Health Monitoring**
- Health check probe every 30 seconds per active provider:
  - Lightweight request (e.g., `GET /models` or minimal completion)
  - Measures latency, checks for errors
  - Updates rolling averages (p50, p95, p99)
- Rate limit headroom tracking:
  - Track current usage vs. known limits per provider
  - Calculate remaining capacity: `headroom_pct = 1 - (current_rpm / max_rpm)`
  - When headroom < 20%, begin routing away from that provider
- Error rate tracking: sliding window of last 100 requests per provider
- Health status transitions: `healthy` → `degraded` (error_rate > 5%) → `unhealthy` (error_rate > 25% or circuit open)

### Routing Strategies

**Built-In Strategies**
- **Cost-optimized**: Select cheapest model meeting minimum capability threshold. Best for batch workloads, background tasks
- **Performance-optimized**: Select fastest model above quality threshold. Best for real-time user interactions
- **Balanced**: Weighted combination — default 60% capability, 25% cost, 15% latency
- **Sensitive**: Hard filter — only models with data handling policy `no_retention` and required compliance certifications. No cost/speed tradeoff allowed
- **Geo-restricted**: Hard filter on `geo_residency`. Data processed only in allowed regions (EU data stays in EU)
- **Budget-aware**: Dynamic cost sensitivity — as department/tenant budget depletes:
  - Budget >75% remaining: use any strategy
  - Budget 50-75%: increase cost weight by 1.5×
  - Budget 25-50%: increase cost weight by 2.5×, alert admin
  - Budget <25%: switch to cheapest model only, alert admin
  - Budget 0%: block execution (if hard limit) or allow with alert (if soft limit)
- **Custom**: User-defined scoring function via Python:
  ```python
  # Custom scoring function (stored in agent config)
  def custom_score(model: ModelProvider, request: RoutingRequest) -> float:
      """User-defined scoring. Must return 0.0-1.0."""
      score = 0.0
      if "code" in model.capabilities and request.task_type == "code":
          score += 0.5
      if model.provider == "anthropic":
          score += 0.3  # Prefer Anthropic for this agent
      score += (1.0 - model.input_cost_per_1k_tokens / 0.03) * 0.2
      return min(max(score, 0.0), 1.0)
  ```

**Strategy Selection**
- Default strategy set per tenant (admin configurable)
- Per-agent strategy override (agent creator specifies)
- Per-request strategy override (API caller specifies in request header `X-Routing-Strategy`)
- Strategy precedence: request > agent > tenant > platform default

### Routing Rules & Overrides

**Rule Engine**
```python
class RoutingRule(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    name: str
    description: str | None
    priority: int = 100  # Lower = higher priority; evaluated in order
    enabled: bool = True

    # Match conditions (all must match)
    match_department: str | None  # "legal", "engineering", "finance"
    match_agent_id: uuid.UUID | None
    match_agent_tags: list[str] | None  # ["code", "customer-facing"]
    match_data_classification: str | None  # "restricted", "confidential"
    match_time_window: dict | None  # {"start": "09:00", "end": "17:00", "timezone": "US/Eastern", "days": ["mon","tue","wed","thu","fri"]}
    match_user_role: str | None

    # Actions
    action_type: Literal["force_model", "force_strategy", "block", "add_weight", "exclude_model"]
    action_model_id: uuid.UUID | None  # For force_model
    action_strategy: str | None  # For force_strategy
    action_weight_overrides: dict | None  # For add_weight: {"cost": 0.5, "latency": 0.1}
    action_exclude_providers: list[str] | None  # For exclude_model: ["openai", "anthropic"]
    action_reason: str  # "Legal department requires on-prem models only"

    created_at: datetime
    updated_at: datetime | None
    created_by: uuid.UUID
```

**Pre-Built Rule Templates**
- Legal department: force on-prem/local models only
- Off-hours: switch to cheaper models (18:00–08:00 and weekends)
- Code agents: prefer Claude/GPT-4 (high code capability)
- Customer-facing: prefer low-latency models
- HIPAA workloads: only HIPAA-certified models
- EU data residency: only EU-region models

### A/B Testing Framework

**Experiment Configuration**
```python
class RoutingExperiment(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    name: str
    description: str | None
    status: Literal["draft", "running", "paused", "completed", "cancelled"]

    # Variants
    control_strategy: str  # Current production strategy
    treatment_strategy: str  # Strategy being tested
    traffic_split_pct: int = 10  # % of traffic routed to treatment (1-50)

    # Metrics to track
    primary_metric: Literal["cost", "latency", "quality_score", "error_rate"]
    secondary_metrics: list[str]

    # Statistical config
    min_sample_size: int = 1000  # Minimum observations per variant
    confidence_level: float = 0.95  # 95% confidence
    min_detectable_effect: float = 0.05  # 5% MDE

    # Results
    control_observations: int = 0
    treatment_observations: int = 0
    control_metric_mean: float | None
    treatment_metric_mean: float | None
    p_value: float | None
    is_significant: bool = False
    winner: Literal["control", "treatment", "inconclusive"] | None

    # Auto-promote
    auto_promote: bool = False  # Automatically adopt winner
    auto_promote_threshold: float = 0.95  # Confidence threshold for auto-promote

    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    created_by: uuid.UUID
```

- Traffic split via consistent hashing (user_id hash determines variant — same user always gets same variant)
- Metrics collected per request: cost, latency, quality score (if available), error/success
- Statistical significance via two-sample t-test (continuous metrics) or chi-squared (categorical)
- Auto-promote: when treatment wins with sufficient confidence, automatically update tenant's default strategy

### Explainable Routing

**Routing Decision Record**
```python
class RoutingDecision(SQLModel, table=True):
    """Every routing decision is recorded and explainable."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    execution_id: uuid.UUID = Field(foreign_key="executions.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    user_id: uuid.UUID = Field(foreign_key="users.id")
    agent_id: uuid.UUID | None = Field(foreign_key="agents.id")

    # Request context
    request_data_classification: str
    request_task_type: str | None
    request_strategy: str  # Which strategy was used
    request_capabilities_required: list[str]

    # Decision
    selected_model_id: uuid.UUID = Field(foreign_key="model_providers.id")
    selected_model_name: str
    selected_model_provider: str
    was_fallback: bool = False
    fallback_reason: str | None
    fallback_depth: int = 0  # 0=primary, 1=secondary, 2=tertiary

    # Scores
    candidate_count: int  # How many models were considered
    filtered_count: int  # How many passed auth/compliance filters
    scores: dict  # {model_id: {cost: 0.8, latency: 0.9, ...total: 0.85}}

    # Explanation
    explanation: str  # Human-readable: "Selected gpt-4 because: cost=$0.03, latency=200ms, ..."
    explanation_factors: dict  # Structured: {"cost": {"value": 0.03, "score": 0.8, "weight": 0.25}, ...}
    rules_applied: list[str]  # IDs of routing rules that affected this decision

    # Metadata
    decision_latency_ms: float  # How long the routing decision took
    circuit_breaker_states: dict  # Snapshot of circuit breaker states at decision time
    rate_limit_headroom: dict  # {provider: headroom_pct}

    # Experiment
    experiment_id: uuid.UUID | None
    experiment_variant: Literal["control", "treatment"] | None

    created_at: datetime
```

**Explanation Format**
- Every routing decision returns an explanation object:
  ```json
  {
    "selected": "gpt-4-turbo",
    "reason": "Selected gpt-4-turbo because: cost=$0.03/1k tokens (score=0.82), latency=180ms p50 (score=0.91), capability=0.95 (code+reasoning match), sensitivity=OK (SOC2 certified, no-retention policy), availability=99.7% (healthy, 65% rate limit headroom)",
    "candidates_considered": 12,
    "candidates_filtered": 8,
    "filter_reasons": {
      "claude-3-opus": "geo_residency: EU not in tenant allowed regions [US]",
      "local-llama": "capability: missing 'function_calling' required by agent",
      "gpt-4-32k": "auth: user lacks 'restricted' clearance",
      "mistral-large": "circuit_breaker: OPEN (7 failures in last 60s)"
    },
    "strategy": "balanced",
    "rules_applied": ["rule-123: off-hours cost increase"],
    "decision_time_ms": 12.4
  }
  ```
- Explanations stored in `RoutingDecision` table and attached to execution metadata
- Queryable via API for debugging, compliance review, and optimization analysis

### Rate Limit Awareness

**Per-Provider Rate Limit Tracking**
- Track current usage in Redis sliding windows:
  - `router:ratelimit:{tenant_id}:{provider}:rpm` — requests per minute
  - `router:ratelimit:{tenant_id}:{provider}:tpm` — tokens per minute
  - `router:ratelimit:{tenant_id}:{provider}:rpd` — requests per day
- Compare against known limits from model registry
- Pre-emptive routing: when headroom < 20%, reduce routing score for that provider
- Pre-emptive routing: when headroom < 5%, exclude provider from candidates entirely
- Rate limit errors (HTTP 429) handled gracefully:
  1. Log the rate limit hit
  2. Update rate limit tracker
  3. Trip circuit breaker if repeated
  4. Retry with fallback model
  5. Return `Retry-After` header to client if all providers rate-limited

## Output Structure

```
backend/
├── app/
│   ├── models/
│   │   └── routing.py               # RoutingRule, ModelProvider, RoutingDecision,
│   │                                 # RoutingExplanation, FallbackChain, RoutingExperiment
│   ├── routers/
│   │   └── routing.py               # All routing API endpoints
│   ├── services/
│   │   └── router/
│   │       ├── __init__.py           # RoutingEngine export
│   │       ├── engine.py             # Core routing engine (score, select, explain)
│   │       ├── scoring.py            # Multi-factor scoring functions
│   │       ├── strategies.py         # Built-in + custom strategy implementations
│   │       ├── circuit_breaker.py    # Circuit breaker state machine
│   │       ├── fallback.py           # Fallback chain executor
│   │       ├── rate_limiter.py       # Per-provider rate limit tracking
│   │       ├── health_monitor.py     # Provider health check probes
│   │       ├── auth_filter.py        # Auth-aware candidate filtering
│   │       ├── credential_manager.py # Vault credential retrieval + caching
│   │       ├── explainer.py          # Routing decision explanation generator
│   │       ├── ab_testing.py         # A/B experiment management + statistics
│   │       ├── rules_engine.py       # Routing rule evaluation
│   │       └── registry.py           # Model registry CRUD + lifecycle
│   └── middleware/
│       └── routing.py               # Request-level routing context injection
├── tests/
│   └── test_router/
│       ├── __init__.py
│       ├── conftest.py               # Router test fixtures, mock providers
│       ├── test_engine.py            # Core routing logic tests
│       ├── test_scoring.py           # Scoring function unit tests
│       ├── test_strategies.py        # Strategy selection tests
│       ├── test_circuit_breaker.py   # Circuit breaker state transition tests
│       ├── test_fallback.py          # Fallback chain tests
│       ├── test_rate_limiter.py      # Rate limit tracking tests
│       ├── test_auth_filter.py       # Auth-aware filtering tests
│       ├── test_credential_manager.py # Vault credential tests
│       ├── test_explainer.py         # Explanation generation tests
│       ├── test_ab_testing.py        # A/B experiment tests
│       └── test_rules_engine.py      # Rule evaluation tests
ops/
└── router/
    ├── grafana/
    │   ├── routing-dashboard.json    # Routing metrics dashboard
    │   └── model-health-dashboard.json # Provider health dashboard
    ├── prometheus/
    │   └── routing-alerts.yml        # Alerting rules for routing anomalies
    └── config/
        ├── default-strategies.yml    # Default strategy configurations
        └── default-rules.yml         # Default routing rules
frontend/
└── src/
    └── components/
        └── router/
            ├── ModelRegistry.tsx      # Model provider management UI
            ├── RoutingRules.tsx        # Rule configuration interface
            ├── RoutingDashboard.tsx    # Real-time routing metrics
            ├── ABTestManager.tsx       # Experiment management UI
            ├── RoutingExplainer.tsx    # Decision explanation viewer
            └── FallbackChainEditor.tsx # Fallback chain configuration
```

## API Endpoints (Complete)

```
# Model Registry
GET    /api/v1/routing/models                     # List registered models (filtered by tenant access)
POST   /api/v1/routing/models                     # Register new model provider
GET    /api/v1/routing/models/{id}                # Get model details
PUT    /api/v1/routing/models/{id}                # Update model configuration
DELETE /api/v1/routing/models/{id}                # Deactivate model
GET    /api/v1/routing/models/{id}/health         # Get model health status
POST   /api/v1/routing/models/{id}/health-check   # Trigger manual health check

# Routing Configuration
GET    /api/v1/routing/strategies                  # List available strategies
GET    /api/v1/routing/strategies/{name}           # Get strategy details + weights
PUT    /api/v1/routing/strategies/{name}/weights   # Update strategy weights (tenant-scoped)

# Routing Rules
GET    /api/v1/routing/rules                       # List routing rules
POST   /api/v1/routing/rules                       # Create routing rule
GET    /api/v1/routing/rules/{id}                  # Get rule details
PUT    /api/v1/routing/rules/{id}                  # Update rule
DELETE /api/v1/routing/rules/{id}                  # Delete rule
POST   /api/v1/routing/rules/reorder               # Reorder rule priorities

# Fallback Chains
GET    /api/v1/routing/fallback-chains             # List fallback chains
POST   /api/v1/routing/fallback-chains             # Create fallback chain
PUT    /api/v1/routing/fallback-chains/{id}        # Update fallback chain
DELETE /api/v1/routing/fallback-chains/{id}        # Delete fallback chain

# Routing Decisions (read-only, audit)
GET    /api/v1/routing/decisions                   # Query routing decisions (paginated, filtered)
GET    /api/v1/routing/decisions/{id}              # Get specific decision with explanation
GET    /api/v1/routing/decisions/{id}/explanation  # Get detailed explanation

# A/B Experiments
GET    /api/v1/routing/experiments                 # List experiments
POST   /api/v1/routing/experiments                 # Create experiment
GET    /api/v1/routing/experiments/{id}            # Get experiment details + results
PUT    /api/v1/routing/experiments/{id}            # Update experiment config
POST   /api/v1/routing/experiments/{id}/start      # Start experiment
POST   /api/v1/routing/experiments/{id}/pause      # Pause experiment
POST   /api/v1/routing/experiments/{id}/complete   # Complete experiment + declare winner
POST   /api/v1/routing/experiments/{id}/promote    # Promote winner to production

# Circuit Breakers (operational)
GET    /api/v1/routing/circuit-breakers            # List circuit breaker states
POST   /api/v1/routing/circuit-breakers/{provider}/reset  # Manually reset circuit breaker

# Rate Limits (operational)
GET    /api/v1/routing/rate-limits                 # Current rate limit headroom per provider

# Credentials (admin)
GET    /api/v1/routing/credentials                 # List configured provider credentials (masked)
POST   /api/v1/routing/credentials                 # Store provider credentials in Vault
PUT    /api/v1/routing/credentials/{provider}      # Update provider credentials
DELETE /api/v1/routing/credentials/{provider}      # Remove provider credentials
GET    /api/v1/routing/credentials/{provider}/health  # Test credential validity

# Routing Simulation (debugging)
POST   /api/v1/routing/simulate                    # Dry-run routing decision (returns explanation without executing)

# Metrics
GET    /api/v1/routing/metrics                     # Routing metrics summary (cost, latency, model distribution)
GET    /api/v1/routing/metrics/models              # Per-model usage and performance metrics
```

## Verify Commands

```bash
# Router engine importable
cd ~/Scripts/Archon && python -c "from backend.app.services.router import RoutingEngine; print('OK')"

# All router models importable
cd ~/Scripts/Archon && python -c "from backend.app.models.routing import RoutingRule, ModelProvider, RoutingDecision, RoutingExperiment, FallbackChain; print('All models OK')"

# Router services importable
cd ~/Scripts/Archon && python -c "from backend.app.services.router.scoring import MultiFactorScorer; from backend.app.services.router.circuit_breaker import CircuitBreaker; from backend.app.services.router.explainer import RoutingExplainer; print('Services OK')"

# Auth filter importable
cd ~/Scripts/Archon && python -c "from backend.app.services.router.auth_filter import RoutingAuthPolicy; print('Auth filter OK')"

# Credential manager importable
cd ~/Scripts/Archon && python -c "from backend.app.services.router.credential_manager import CredentialManager; print('Credential manager OK')"

# Router API endpoints registered
cd ~/Scripts/Archon && python -c "from backend.app.routers.routing import router; print(f'{len(router.routes)} routes registered')"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_router/ --tb=short -q

# No hardcoded API keys
cd ~/Scripts/Archon && ! grep -rn 'sk-[a-zA-Z0-9]' --include='*.py' backend/app/services/router/ || echo 'FAIL: hardcoded keys found'

# Circuit breaker tests
cd ~/Scripts/Archon/backend && python -m pytest tests/test_router/test_circuit_breaker.py --tb=short -q

# Scoring tests
cd ~/Scripts/Archon/backend && python -m pytest tests/test_router/test_scoring.py --tb=short -q
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Routing decision completes in <200ms (p95) with 10+ registered models
- [ ] Auth-aware filtering correctly blocks users without clearance from accessing restricted models
- [ ] Per-tenant Vault credential retrieval works with BYOK and platform key modes
- [ ] Credential health monitoring detects invalid API keys within 60 seconds
- [ ] Multi-factor scoring produces correct rankings across all 6 score components
- [ ] Configurable weights at platform, tenant, and agent levels override correctly (most specific wins)
- [ ] Fallback chain activates within 500ms when primary model errors
- [ ] Circuit breaker opens after 5 failures in 60s, half-opens after 30s, closes on success
- [ ] Circuit breaker state is shared across all API workers via Redis
- [ ] Model registry supports all 9+ providers with correct metadata
- [ ] Cost-optimized strategy measurably reduces spend vs. static model selection
- [ ] Sensitivity routing hard-blocks non-compliant models for classified data
- [ ] Geo-restricted routing ensures data residency compliance
- [ ] Budget-aware routing progressively shifts to cheaper models as budget depletes
- [ ] Custom scoring functions execute safely in sandboxed environment
- [ ] Routing rules evaluated in priority order with correct match conditions
- [ ] A/B testing splits traffic consistently (same user → same variant)
- [ ] A/B statistical analysis produces valid p-values with correct sample sizes
- [ ] Auto-promote correctly adopts winning strategy at configured confidence threshold
- [ ] Every routing decision has a complete, human-readable explanation stored in the database
- [ ] Explanation includes all candidate scores, filter reasons, and applied rules
- [ ] Rate limit tracking pre-emptively routes away from providers at <20% headroom
- [ ] Rate limit errors (429) trigger fallback without user-visible error
- [ ] Routing simulation endpoint returns explanation without executing
- [ ] Router dashboard shows real-time model performance metrics
- [ ] Grafana dashboards deployed with routing and model health panels
- [ ] All tests pass with >80% coverage on routing module
- [ ] Zero hardcoded API keys, secrets, or credentials in source code
