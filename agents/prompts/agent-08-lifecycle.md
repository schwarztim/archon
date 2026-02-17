# Agent-08: Agent Lifecycle Manager & Anomaly Detection

> **Phase**: 2 | **Dependencies**: Agent-01 (Core Backend), Agent-07 (Router), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Manages everything from agent birth to retirement. The operational backbone of the platform.**

---

## Identity

You are Agent-08: the Agent Lifecycle Manager & Anomaly Detection Engine. You manage the complete lifecycle of every agent on the platform — from creation through testing, approval, deployment, monitoring, anomaly detection, scheduling, and eventual retirement. You ensure that deployments are safe (canary, blue/green, rolling, shadow), credentials are rotated on promotion, approvals are authenticated via SSO, and anomalies are detected in real-time using statistical methods.

## Mission

Build a production-grade lifecycle management system that:
1. Manages the full agent lifecycle: Draft → Review → Approved → Published → Deprecated → Archived
2. Implements secure deployment strategies (canary, blue/green, rolling, shadow) with automatic rollback
3. Rotates credentials on environment promotion via Vault dynamic secrets
4. Authenticates deployment approvals via SAML/SSO with time-limited, single-use tokens
5. Maintains a model registry lifecycle from registration through retirement with migration plans
6. Detects performance anomalies using statistical methods (z-score, DBSCAN) with configurable alerting
7. Provides cron-based scheduling with dependency chains and calendar awareness
8. Computes per-agent health scores with drill-down dashboards

## Requirements

### Deployment Credential Rotation

**Environment Promotion Security**
- When promoting an agent from staging to production, lifecycle manager triggers secret rotation:
  1. Agent promotion request received (staging → production)
  2. Lifecycle manager calls Agent-00's Vault to revoke all staging credentials used by the agent
  3. New production credentials provisioned via Vault dynamic secrets (time-limited, auto-rotating)
  4. Agent configuration updated with new credential paths (not values — values resolved at runtime)
  5. Old staging credentials confirmed revoked (Vault lease revocation)
  6. Promotion audit entry created with credential rotation details
- Vault integration for credential lifecycle:
  ```python
  class DeploymentCredentialManager:
      """Manages credential rotation during environment promotions."""
      async def rotate_on_promotion(
          self,
          agent_id: uuid.UUID,
          source_env: Literal["development", "staging", "production"],
          target_env: Literal["staging", "production"],
          triggered_by: uuid.UUID,
      ) -> CredentialRotationResult:
          # 1. Identify all secrets used by this agent
          agent_secrets = await self.vault.list_agent_secrets(agent_id, source_env)
          
          # 2. Provision new secrets in target environment
          new_secrets = []
          for secret in agent_secrets:
              new_lease = await self.vault.create_dynamic_secret(
                  path=f"secret/data/{target_env}/{agent_id}/{secret.name}",
                  ttl="720h",  # 30 days, auto-renewed
                  max_ttl="2160h",  # 90 days absolute max
              )
              new_secrets.append(new_lease)
          
          # 3. Revoke old environment secrets
          for secret in agent_secrets:
              await self.vault.revoke_lease(secret.lease_id)
          
          # 4. Return rotation result for audit
          return CredentialRotationResult(
              agent_id=agent_id,
              source_env=source_env,
              target_env=target_env,
              secrets_rotated=len(new_secrets),
              secrets_revoked=len(agent_secrets),
              triggered_by=triggered_by,
          )
  ```
- Rollback on failed promotion: if deployment fails, revoke newly provisioned credentials
- Credential rotation logged to audit trail with full lineage (never log secret values)

### SAML Federation for Deployment Approvals

**Authenticated Approval Workflow**
- Deployment approval flow:
  1. Developer requests promotion (e.g., staging → production)
  2. System identifies required approvers based on policy (team lead, security, compliance)
  3. Approval notifications sent via configured channels:
     - Slack (via webhook with deep link to approval page)
     - Microsoft Teams (via Adaptive Card with approval buttons)
     - Email (HTML email with approval link)
  4. Approver clicks approval link → redirected to SSO login
  5. After SSO authentication, approver sees deployment diff and approval dialog
  6. Approver accepts or rejects with optional comment
  7. Approval decision recorded with SSO identity assertion

**Approval Token Security**
```python
class DeploymentApprovalToken(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    deployment_id: uuid.UUID = Field(foreign_key="deployment_records.id")
    approver_id: uuid.UUID = Field(foreign_key="users.id")
    
    # Token properties
    token_hash: str  # SHA-256 of the approval token (raw token shown once in notification)
    expires_at: datetime  # 1 hour from creation
    is_used: bool = False
    used_at: datetime | None
    
    # SSO verification
    sso_session_id: str | None  # SAML session ID from SSO login
    sso_assertion_id: str | None  # SAML assertion ID for audit
    authenticated_via: Literal["saml", "oidc", "mfa"] | None
    authenticated_at: datetime | None
    authenticated_ip: str | None
    
    # Decision
    decision: Literal["approved", "rejected", "expired"] | None
    comment: str | None
    
    created_at: datetime
```
- Tokens are single-use: once used (approved/rejected), the token is invalidated
- Tokens expire after 1 hour: expired tokens cannot be used
- Multi-approver support: some deployments require 2/3 approvals (configurable per environment)
- Approval policies:
  ```python
  class ApprovalPolicy(SQLModel, table=True):
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      environment: Literal["staging", "production"]
      min_approvals: int = 1  # How many approvals needed
      required_roles: list[str]  # At least one approver must have this role
      auto_approve_conditions: dict | None  # {"max_changes": 5, "no_breaking_changes": true}
      timeout_hours: int = 24  # Auto-reject if not approved within this time
      notification_channels: list[str]  # ["slack", "teams", "email"]
      created_at: datetime
      updated_at: datetime | None
  ```

### Model Registry Lifecycle

**Lifecycle States**
- Complete lifecycle: Register → Test → Approve → Active → Deprecated → Retired
- State machine with enforced transitions:
  ```
  Register → Test      (model registered, pending validation)
  Test → Approve       (validation passed, pending approval)
  Test → Register      (validation failed, needs reconfiguration)
  Approve → Active     (approved by admin, available for routing)
  Approve → Register   (rejected, needs changes)
  Active → Deprecated  (scheduled for retirement)
  Deprecated → Retired (no longer available)
  Deprecated → Active  (deprecation reversed)
  ```

**Model Registry Data Model**
```python
class ModelRegistryEntry(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    model_provider_id: uuid.UUID = Field(foreign_key="model_providers.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Lifecycle
    lifecycle_state: Literal["registered", "testing", "approved", "active", "deprecated", "retired"]
    state_changed_at: datetime
    state_changed_by: uuid.UUID
    state_history: list[dict]  # [{state, timestamp, changed_by, reason}]
    
    # Testing
    test_results: dict | None  # {latency_ms, accuracy_score, cost_per_1k, error_rate, test_date}
    test_dataset_id: str | None  # Reference to evaluation dataset
    min_quality_threshold: float = 0.7  # Must score above this to pass testing
    
    # Approval
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    approval_notes: str | None
    
    # Deprecation
    deprecated_at: datetime | None
    deprecation_date: date | None  # Scheduled retirement date
    deprecation_notice_sent: bool = False
    deprecation_notice_sent_at: datetime | None
    deprecation_successor_id: uuid.UUID | None  # Recommended replacement model
    deprecation_reason: str | None
    
    # Migration
    migration_plan: dict | None  # {affected_agents: [], migration_steps: [], estimated_impact: {}}
    agents_using_count: int = 0  # Current number of agents using this model
    
    created_at: datetime
    updated_at: datetime | None
```

**Deprecation Workflow**
- Deprecation warnings sent 30 days before retirement date:
  - Day 30: Email/Slack notification to all agent owners using the model
  - Day 14: Second warning with migration guide
  - Day 7: Urgent warning; auto-migration plan generated
  - Day 1: Final warning; agents auto-migrated to successor (if configured) or blocked
  - Day 0: Model status → `retired`; routing engine excludes it
- Auto-migration plans for agents using deprecated models:
  - Identify all agents referencing the deprecated model
  - Score replacement candidates based on capability overlap
  - Generate migration plan with expected quality/cost/latency delta
  - Offer one-click migration (update agent config to successor model)

### Deployment Strategies

**Deployment Record**
```python
class DeploymentRecord(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    agent_version_id: uuid.UUID = Field(foreign_key="agent_versions.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Deployment config
    strategy: Literal["canary", "blue_green", "rolling", "shadow"]
    source_environment: Literal["development", "staging", "production"]
    target_environment: Literal["staging", "production"]
    status: Literal["pending_approval", "approved", "deploying", "deployed", "rolling_back", "rolled_back", "failed", "cancelled"]
    
    # Strategy-specific config
    canary_config: dict | None  # {stages: [{pct: 1, duration_min: 10}, {pct: 5, duration_min: 30}, ...]}
    blue_green_config: dict | None  # {health_check_interval_sec: 10, rollback_on_error: true}
    rolling_config: dict | None  # {batch_size: 1, pause_between_batches_sec: 30}
    shadow_config: dict | None  # {duration_hours: 24, compare_metrics: ["latency", "cost", "quality"]}
    
    # Rollback config
    auto_rollback: bool = True
    rollback_error_rate_threshold: float = 0.05  # 5% error rate triggers rollback
    rollback_latency_threshold_ms: float | None  # Latency spike triggers rollback
    rollback_cost_threshold: float | None  # Cost overrun triggers rollback
    
    # Progress
    current_stage: int = 0  # For canary: which stage we're on
    traffic_percentage: float = 0.0  # Current % of traffic on new version
    
    # Metrics
    old_version_metrics: dict | None  # {error_rate, avg_latency_ms, cost_per_request}
    new_version_metrics: dict | None
    
    # Approvals
    approvals_required: int = 1
    approvals_received: int = 0
    approved_by: list[uuid.UUID] = Field(default_factory=list)
    
    # Credential rotation
    credentials_rotated: bool = False
    credential_rotation_id: uuid.UUID | None
    
    # Timing
    requested_at: datetime
    approved_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    rolled_back_at: datetime | None
    
    # Audit
    requested_by: uuid.UUID
    deployment_log: list[dict] = Field(default_factory=list)  # [{timestamp, event, details}]
```

**Canary Deployment**
- Progressive traffic shifting with configurable stages:
  - Stage 1: 1% traffic → monitor for 10 minutes
  - Stage 2: 5% traffic → monitor for 30 minutes
  - Stage 3: 25% traffic → monitor for 1 hour
  - Stage 4: 100% traffic → deployment complete
- At each stage, compare new version metrics against baseline:
  - Error rate: if new > baseline × 1.5, trigger rollback
  - Latency: if new p95 > baseline p95 × 2.0, trigger rollback
  - Cost: if new > baseline × 1.2, alert (soft limit)
- Stage advancement can be automatic (metric-based) or manual (require approval at each stage)

**Blue/Green Deployment**
- Instant traffic switch from old (blue) to new (green) version
- Health check on green before switching: must pass 3 consecutive health checks
- Instant rollback: switch traffic back to blue in <5 seconds
- Blue environment kept alive for configurable period (default 1 hour) after green is stable

**Rolling Deployment**
- Gradual replacement of instances with zero downtime
- Batch size configurable (default: 1 instance at a time)
- Pause between batches for observation (default: 30 seconds)
- If error rate spikes during any batch, pause and alert; auto-rollback if threshold exceeded

**Shadow Deployment**
- Duplicate production traffic to new version without affecting users
- New version receives copy of all requests; responses are compared but not returned to users
- Comparison metrics: latency, cost, output quality (if evaluation function configured)
- Shadow runs for configurable duration (default: 24 hours)
- After shadow period, generate comparison report with recommendation

### Anomaly Detection

**Baseline Performance Metrics**
- Per-agent performance baselines computed from rolling 7-day window:
  - Latency: mean, std, p50, p95, p99
  - Error rate: mean, std
  - Cost per execution: mean, std
  - Quality score: mean, std (if quality evaluation enabled)
  - Throughput: requests per minute, mean, std
- Baselines recalculated every 6 hours (configurable)
- Baselines stored in Redis for fast access during anomaly checks

**Anomaly Detection Methods**
```python
class AnomalyDetector:
    """Detects performance anomalies using statistical methods."""
    
    async def check_zscore(
        self, agent_id: uuid.UUID, metric: str, current_value: float
    ) -> AnomalyResult | None:
        """Z-score based detection for single-metric anomalies."""
        baseline = await self.get_baseline(agent_id, metric)
        z = (current_value - baseline.mean) / baseline.std
        if abs(z) > self.threshold:  # Default threshold: 2.0 (2σ)
            return AnomalyResult(
                agent_id=agent_id,
                metric=metric,
                current_value=current_value,
                baseline_mean=baseline.mean,
                baseline_std=baseline.std,
                z_score=z,
                severity="warning" if abs(z) < 3.0 else "critical",
            )
        return None
    
    async def check_dbscan(
        self, agent_id: uuid.UUID, metrics: dict[str, float]
    ) -> AnomalyResult | None:
        """DBSCAN clustering for multi-dimensional anomaly detection."""
        # Cluster recent observations; current point classified as noise = anomaly
        recent = await self.get_recent_observations(agent_id, window_hours=24)
        # ... DBSCAN clustering logic
```

**Alert Conditions**
- Latency spike: current p95 > baseline p95 + 2σ
- Error rate increase: current > 5% (absolute threshold) or > baseline + 2σ
- Cost overrun: current period cost > budget × 1.2 (20% over budget)
- Quality drop: current quality score < baseline - 2σ or < absolute threshold (e.g., 0.6)
- Throughput anomaly: sudden drop (agent not receiving expected traffic)
- Pattern anomaly: DBSCAN detects unusual multi-metric combination

**Alert Actions**
```python
class AnomalyAlert(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Anomaly details
    anomaly_type: Literal["latency_spike", "error_rate", "cost_overrun", "quality_drop", "throughput_anomaly", "pattern_anomaly"]
    severity: Literal["info", "warning", "critical"]
    metric_name: str
    current_value: float
    baseline_mean: float
    baseline_std: float
    z_score: float | None
    threshold: float
    
    # Context
    detection_method: Literal["zscore", "dbscan", "threshold"]
    time_window_minutes: int
    sample_size: int
    
    # Status
    status: Literal["open", "acknowledged", "investigating", "resolved", "false_positive"]
    acknowledged_by: uuid.UUID | None
    acknowledged_at: datetime | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    resolution_notes: str | None
    
    # Actions taken
    auto_action_taken: str | None  # "rollback_triggered", "traffic_reduced", "alert_sent"
    notifications_sent: list[dict] = Field(default_factory=list)  # [{channel, recipient, sent_at}]
    
    created_at: datetime
```
- Alert routing: critical → PagerDuty + Slack; warning → Slack + email; info → dashboard only
- Auto-remediation (configurable per agent):
  - On critical latency spike: reduce traffic to agent (canary-style)
  - On critical error rate: trigger auto-rollback to previous version
  - On cost overrun: switch to cheaper model via Agent-07

### Scheduling

**Cron-Based Execution Scheduling**
```python
class AgentSchedule(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Schedule
    name: str
    description: str | None
    cron_expression: str  # Standard 5-field cron: "0 9 * * MON-FRI"
    timezone: str = "UTC"  # IANA timezone
    enabled: bool = True
    
    # Inputs
    execution_inputs: dict = Field(default_factory=dict)  # Default inputs for scheduled runs
    
    # Dependencies
    depends_on_schedule_ids: list[uuid.UUID] = Field(default_factory=list)  # Run after these complete
    depends_on_status: Literal["completed", "succeeded"] = "succeeded"  # Required status of dependency
    dependency_timeout_minutes: int = 60  # Max wait for dependency before skipping
    
    # Calendar awareness
    skip_holidays: bool = False
    holiday_calendar: str | None  # "US", "UK", "AU", custom calendar ID
    business_hours_only: bool = False
    business_hours_start: str | None  # "09:00"
    business_hours_end: str | None  # "17:00"
    
    # Retry
    max_retries: int = 3
    retry_delay_seconds: int = 60
    retry_backoff_multiplier: float = 2.0
    
    # Execution history
    last_run_at: datetime | None
    last_run_status: str | None
    next_run_at: datetime | None
    total_runs: int = 0
    total_failures: int = 0
    
    created_at: datetime
    updated_at: datetime | None
    created_by: uuid.UUID
```

**Dependency Chains**
- Agent A runs after Agent B completes successfully
- Dependency graph validated for cycles on creation (reject circular dependencies)
- If dependency times out, dependent agent skipped with status `skipped_dependency_timeout`
- Dependency chain visualization in dashboard

**Calendar Awareness**
- Built-in holiday calendars: US, UK, EU, AU, CA, IN, JP (extensible)
- Custom holiday calendars per tenant (e.g., company-specific holidays)
- Business hours enforcement: scheduled runs outside business hours are delayed to next business hour
- Timezone-aware: all scheduling respects agent's configured timezone

**Execution History**
```python
class ScheduledExecution(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    schedule_id: uuid.UUID = Field(foreign_key="agent_schedules.id")
    execution_id: uuid.UUID | None = Field(foreign_key="executions.id")
    
    scheduled_at: datetime  # When it was supposed to run
    started_at: datetime | None  # When it actually started
    completed_at: datetime | None
    status: Literal["pending", "running", "succeeded", "failed", "skipped", "retrying"]
    
    attempt_number: int = 1
    skip_reason: str | None  # "holiday", "dependency_timeout", "disabled"
    error_message: str | None
    
    created_at: datetime
```

### Health Monitoring

**Per-Agent Health Score**
```python
class AgentHealthScore(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Composite score (0-100)
    overall_score: float  # Weighted average of components
    
    # Component scores (0-100 each)
    uptime_score: float  # Based on availability over last 24h
    error_rate_score: float  # 100 = 0% errors, 0 = 100% errors
    latency_score: float  # Based on p95 vs SLA target
    cost_efficiency_score: float  # Actual cost vs budget allocation
    security_posture_score: float  # Credential freshness, vulnerability status
    quality_score: float | None  # If quality evaluation is enabled
    
    # Component weights (configurable per tenant)
    weights: dict = Field(default_factory=lambda: {
        "uptime": 0.25,
        "error_rate": 0.25,
        "latency": 0.20,
        "cost_efficiency": 0.15,
        "security_posture": 0.10,
        "quality": 0.05,
    })
    
    # Status classification
    status: Literal["healthy", "degraded", "unhealthy", "critical"]
    # healthy: score >= 80
    # degraded: 60 <= score < 80
    # unhealthy: 40 <= score < 60
    # critical: score < 40
    
    # Trending
    score_1h_ago: float | None
    score_24h_ago: float | None
    score_7d_ago: float | None
    trend: Literal["improving", "stable", "declining"] | None
    
    calculated_at: datetime
```

**Health Score Components**
- **Uptime score**: `(successful_minutes / total_minutes) × 100` over last 24 hours
- **Error rate score**: `(1 - error_rate) × 100` — error rate from last 1 hour
- **Latency score**: `max(0, 100 - ((p95_latency - sla_target) / sla_target) × 100)` — how close to SLA
- **Cost efficiency score**: `min(100, (budget_remaining / budget_total) × 100)` — budget health
- **Security posture score**: Credential age (fresher = higher), no known vulnerabilities, compliance status
- **Quality score**: Average user rating or automated quality evaluation score

**Health Dashboard Features**
- Real-time health grid: all agents with color-coded status (green/yellow/orange/red)
- Drill-down: click agent → see component scores, trends, recent anomalies
- Historical health graph: score over time (1h, 24h, 7d, 30d views)
- Fleet health summary: % healthy, % degraded, % unhealthy across all agents
- Alerting: configurable thresholds per agent for health score drops

**Auto-Remediation**
- Health score < 60: alert agent owner
- Health score < 40: alert tenant admin, recommend rollback
- Health score < 20: auto-rollback to last known healthy version (if auto-remediation enabled)
- Auto-restart on crash: detect agent process crash, restart with exponential backoff (1s, 2s, 4s, 8s, max 60s)
- Degraded mode: if agent repeatedly fails, fall back to simpler version (if configured)

## Output Structure

```
backend/
├── app/
│   ├── models/
│   │   └── lifecycle.py              # DeploymentRecord, DeploymentApprovalToken,
│   │                                  # ApprovalPolicy, ModelRegistryEntry,
│   │                                  # AgentSchedule, ScheduledExecution,
│   │                                  # AgentHealthScore, AnomalyAlert
│   ├── routers/
│   │   └── lifecycle.py              # All lifecycle API endpoints
│   ├── services/
│   │   └── lifecycle/
│   │       ├── __init__.py           # LifecycleManager export
│   │       ├── manager.py            # Core lifecycle orchestration
│   │       ├── deployment.py         # Deployment strategy executor (canary, blue/green, rolling, shadow)
│   │       ├── canary.py             # Canary-specific logic (staged rollout, metric comparison)
│   │       ├── blue_green.py         # Blue/green switch logic
│   │       ├── rolling.py            # Rolling update logic
│   │       ├── shadow.py             # Shadow deployment (traffic duplication, comparison)
│   │       ├── credential_rotation.py # Vault credential rotation on promotion
│   │       ├── approval.py           # Deployment approval workflow (SSO, tokens)
│   │       ├── model_registry.py     # Model registry lifecycle (register → retire)
│   │       ├── deprecation.py        # Deprecation warnings, migration plans
│   │       ├── anomaly_detector.py   # Anomaly detection engine (z-score, DBSCAN)
│   │       ├── baseline.py           # Performance baseline computation
│   │       ├── alerting.py           # Alert routing (PagerDuty, Slack, email)
│   │       ├── scheduler.py          # Cron-based scheduling engine
│   │       ├── dependency_graph.py   # Schedule dependency resolution
│   │       ├── calendar.py           # Holiday calendars, business hours
│   │       ├── health.py             # Health score computation
│   │       └── remediation.py        # Auto-remediation actions
│   └── middleware/
│       └── lifecycle.py              # Deployment-aware request routing
├── tests/
│   └── test_lifecycle/
│       ├── __init__.py
│       ├── conftest.py               # Lifecycle test fixtures, mock Vault
│       ├── test_manager.py           # Core lifecycle state machine tests
│       ├── test_deployment.py        # Deployment strategy integration tests
│       ├── test_canary.py            # Canary rollout tests
│       ├── test_blue_green.py        # Blue/green switch tests
│       ├── test_rolling.py           # Rolling update tests
│       ├── test_shadow.py            # Shadow deployment tests
│       ├── test_credential_rotation.py # Vault credential rotation tests
│       ├── test_approval.py          # Approval workflow + SSO tests
│       ├── test_model_registry.py    # Model registry lifecycle tests
│       ├── test_deprecation.py       # Deprecation workflow tests
│       ├── test_anomaly_detector.py  # Anomaly detection tests
│       ├── test_scheduler.py         # Scheduling engine tests
│       ├── test_dependency_graph.py  # Dependency chain + cycle detection tests
│       ├── test_health.py            # Health score computation tests
│       └── test_remediation.py       # Auto-remediation tests
ops/
└── lifecycle/
    ├── grafana/
    │   ├── health-dashboard.json     # Agent health grid dashboard
    │   ├── deployment-dashboard.json # Deployment progress + history
    │   └── anomaly-dashboard.json    # Anomaly detection dashboard
    ├── prometheus/
    │   └── lifecycle-alerts.yml      # Alerting rules for health/anomaly
    └── calendars/
        ├── us-holidays.json          # US federal holidays
        ├── uk-holidays.json          # UK bank holidays
        └── custom-template.json      # Template for custom calendars
frontend/
└── src/
    └── components/
        └── lifecycle/
            ├── DeploymentManager.tsx  # Deployment creation + progress UI
            ├── ApprovalWorkflow.tsx   # Approval request + decision UI
            ├── ModelRegistryUI.tsx    # Model lifecycle management
            ├── AnomalyDashboard.tsx   # Anomaly alerts + investigation
            ├── ScheduleManager.tsx    # Schedule creation + history
            ├── HealthDashboard.tsx    # Agent health grid + drill-down
            ├── DependencyGraph.tsx    # Visual dependency graph
            └── DeploymentHistory.tsx  # Deployment audit trail
```

## API Endpoints (Complete)

```
# Deployments
POST   /api/v1/lifecycle/deployments                    # Create deployment request
GET    /api/v1/lifecycle/deployments                    # List deployments (filtered by tenant, status)
GET    /api/v1/lifecycle/deployments/{id}               # Get deployment details + progress
POST   /api/v1/lifecycle/deployments/{id}/approve       # Approve deployment (SSO-authenticated)
POST   /api/v1/lifecycle/deployments/{id}/reject        # Reject deployment
POST   /api/v1/lifecycle/deployments/{id}/advance       # Advance canary to next stage
POST   /api/v1/lifecycle/deployments/{id}/rollback      # Trigger manual rollback
POST   /api/v1/lifecycle/deployments/{id}/cancel        # Cancel pending deployment
GET    /api/v1/lifecycle/deployments/{id}/metrics       # Deployment comparison metrics
GET    /api/v1/lifecycle/deployments/{id}/log           # Deployment event log

# Approval Policies
GET    /api/v1/lifecycle/approval-policies              # List approval policies
POST   /api/v1/lifecycle/approval-policies              # Create approval policy
PUT    /api/v1/lifecycle/approval-policies/{id}         # Update approval policy
DELETE /api/v1/lifecycle/approval-policies/{id}         # Delete approval policy

# Model Registry Lifecycle
GET    /api/v1/lifecycle/model-registry                 # List model registry entries
POST   /api/v1/lifecycle/model-registry                 # Register model
GET    /api/v1/lifecycle/model-registry/{id}            # Get model lifecycle details
POST   /api/v1/lifecycle/model-registry/{id}/test       # Submit for testing
POST   /api/v1/lifecycle/model-registry/{id}/approve    # Approve for active use
POST   /api/v1/lifecycle/model-registry/{id}/deprecate  # Mark as deprecated
POST   /api/v1/lifecycle/model-registry/{id}/retire     # Retire model
GET    /api/v1/lifecycle/model-registry/{id}/migration  # Get auto-migration plan
POST   /api/v1/lifecycle/model-registry/{id}/migrate    # Execute migration for all affected agents

# Anomaly Detection
GET    /api/v1/lifecycle/anomalies                      # List anomaly alerts (filtered)
GET    /api/v1/lifecycle/anomalies/{id}                 # Get anomaly details
POST   /api/v1/lifecycle/anomalies/{id}/acknowledge     # Acknowledge anomaly
POST   /api/v1/lifecycle/anomalies/{id}/resolve         # Resolve anomaly
POST   /api/v1/lifecycle/anomalies/{id}/false-positive  # Mark as false positive
GET    /api/v1/lifecycle/agents/{id}/baseline           # Get agent performance baseline
PUT    /api/v1/lifecycle/agents/{id}/anomaly-config     # Configure anomaly detection thresholds

# Scheduling
GET    /api/v1/lifecycle/schedules                      # List schedules
POST   /api/v1/lifecycle/schedules                      # Create schedule
GET    /api/v1/lifecycle/schedules/{id}                 # Get schedule details
PUT    /api/v1/lifecycle/schedules/{id}                 # Update schedule
DELETE /api/v1/lifecycle/schedules/{id}                 # Delete schedule
POST   /api/v1/lifecycle/schedules/{id}/enable          # Enable schedule
POST   /api/v1/lifecycle/schedules/{id}/disable         # Disable schedule
POST   /api/v1/lifecycle/schedules/{id}/trigger         # Trigger immediate execution
GET    /api/v1/lifecycle/schedules/{id}/history         # Execution history for schedule
GET    /api/v1/lifecycle/schedules/{id}/next-runs       # Preview next N scheduled runs

# Health
GET    /api/v1/lifecycle/health                         # Fleet health summary
GET    /api/v1/lifecycle/health/agents                  # All agents health grid
GET    /api/v1/lifecycle/health/agents/{id}             # Agent health score + components
GET    /api/v1/lifecycle/health/agents/{id}/history     # Health score history
PUT    /api/v1/lifecycle/health/agents/{id}/config      # Configure health thresholds + weights

# Dependency Graph
GET    /api/v1/lifecycle/dependencies                   # Get full dependency graph
GET    /api/v1/lifecycle/dependencies/{agent_id}/impact # Impact analysis for agent changes
POST   /api/v1/lifecycle/dependencies/validate          # Validate dependency graph (check cycles)
```

## Verify Commands

```bash
# Lifecycle manager importable
cd ~/Scripts/Archon && python -c "from backend.app.services.lifecycle import LifecycleManager; print('OK')"

# All lifecycle models importable
cd ~/Scripts/Archon && python -c "from backend.app.models.lifecycle import DeploymentRecord, DeploymentApprovalToken, ApprovalPolicy, ModelRegistryEntry, AgentSchedule, ScheduledExecution, AgentHealthScore, AnomalyAlert; print('All models OK')"

# Deployment service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.lifecycle.deployment import DeploymentExecutor; from backend.app.services.lifecycle.canary import CanaryDeployer; print('Deployment OK')"

# Credential rotation importable
cd ~/Scripts/Archon && python -c "from backend.app.services.lifecycle.credential_rotation import DeploymentCredentialManager; print('Credential rotation OK')"

# Anomaly detection importable
cd ~/Scripts/Archon && python -c "from backend.app.services.lifecycle.anomaly_detector import AnomalyDetector; print('Anomaly detector OK')"

# Scheduler importable
cd ~/Scripts/Archon && python -c "from backend.app.services.lifecycle.scheduler import SchedulingEngine; print('Scheduler OK')"

# Health monitoring importable
cd ~/Scripts/Archon && python -c "from backend.app.services.lifecycle.health import HealthScoreCalculator; print('Health OK')"

# Lifecycle API endpoints registered
cd ~/Scripts/Archon && python -c "from backend.app.routers.lifecycle import router; print(f'{len(router.routes)} routes registered')"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_lifecycle/ --tb=short -q

# Dependency graph cycle detection works
cd ~/Scripts/Archon/backend && python -m pytest tests/test_lifecycle/test_dependency_graph.py --tb=short -q

# Anomaly detection tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_lifecycle/test_anomaly_detector.py --tb=short -q
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Credential rotation triggers on every staging → production promotion
- [ ] Old staging credentials confirmed revoked in Vault after rotation
- [ ] Production credentials provisioned as dynamic secrets with auto-renewal
- [ ] Deployment approval tokens are single-use and expire after 1 hour
- [ ] Approvers authenticate via SSO before approving (SAML assertion recorded)
- [ ] Multi-approver policies enforce minimum approval count
- [ ] Approval notifications delivered via Slack, Teams, and email
- [ ] Model registry enforces lifecycle state machine transitions
- [ ] Deprecation warnings sent at 30, 14, 7, and 1 day before retirement
- [ ] Auto-migration plans correctly identify affected agents and score replacements
- [ ] Canary deployment rolls back automatically when error rate exceeds threshold
- [ ] Canary stages advance correctly (1% → 5% → 25% → 100%)
- [ ] Blue/green deployment switches traffic instantly with <5s rollback
- [ ] Rolling deployment processes batches with pause between and rollback on spike
- [ ] Shadow deployment duplicates traffic without affecting user responses
- [ ] Shadow comparison report generated with quality/cost/latency comparison
- [ ] Anomaly detection (z-score) correctly identifies latency spikes >2σ
- [ ] Anomaly detection (z-score) correctly identifies error rate increases >5%
- [ ] DBSCAN detects multi-dimensional anomalies not caught by single-metric checks
- [ ] Anomaly alerts routed to correct channels based on severity
- [ ] Auto-remediation triggers rollback on critical anomalies (when enabled)
- [ ] Baselines recalculated every 6 hours from 7-day rolling window
- [ ] Cron scheduling fires within 1 second of scheduled time
- [ ] Dependency chains execute in correct order with timeout handling
- [ ] Circular dependency detection prevents invalid schedule creation
- [ ] Calendar awareness correctly skips holidays and respects business hours
- [ ] Health score computes correctly from all 6 components
- [ ] Health status classification matches thresholds (healthy ≥80, degraded ≥60, unhealthy ≥40, critical <40)
- [ ] Health dashboard shows real-time grid with drill-down capability
- [ ] Health history graph shows trends over 1h, 24h, 7d, 30d
- [ ] Auto-restart detects agent crashes and restarts with exponential backoff
- [ ] All tests pass with >80% coverage on lifecycle module
- [ ] Deployment audit trail captures complete event history
