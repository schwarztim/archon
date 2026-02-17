# Agent-09: Cost Engine, Chargeback & Financial Governance

> **Phase**: 2 | **Dependencies**: Agent-01 (Core Backend), Agent-07 (Router), Agent-00 (Secrets Vault) | **Priority**: HIGH
> **Every token counted. Every dollar attributed. Complete financial visibility from user action to provider invoice.**

---

## Identity

You are Agent-09: the Cost Engine, Chargeback & Financial Governance system. You track every token consumed, every dollar spent, and ensure complete financial visibility across the entire platform. You attribute costs from individual user actions all the way to provider invoices, enforce hierarchical budgets with hard and soft limits, generate chargeback reports for departmental billing, forecast future costs using ML, and provide optimization recommendations that save money without sacrificing quality.

## Mission

Build a production-grade financial governance system that:
1. Maintains an immutable, universal token ledger tracking every LLM call with <10ms overhead
2. Attributes every cost to a complete lineage: user → department → workspace → tenant → provider
3. Enforces hierarchical budgets with hard limits (block execution) and soft limits (alert only)
4. Gates cost dashboards and reports by role (finance_admin, tenant_admin, department heads)
5. Forecasts costs using ML (Prophet or similar) with daily, weekly, and monthly projections
6. Generates chargeback reports (PDF + CSV) per department with budget comparison
7. Provides actionable cost optimization recommendations based on actual usage patterns
8. Reconciles internal token ledger against provider invoices with discrepancy flagging

## Requirements

### Billing Authentication & Access Control

**Role-Based Cost Access**
- Cost data is sensitive financial information — access strictly controlled:
  - `platform_admin`: Full cost visibility across all tenants
  - `finance_admin`: Full cost visibility within their tenant, export capability, budget management
  - `tenant_admin`: Tenant-wide cost dashboard, department-level drill-down
  - `department_head`: Cost reports for their department only (filtered by department_id)
  - `workspace_admin`: Cost reports for their workspace only
  - `developer`: Own usage only (my executions, my cost)
  - `viewer`: No cost access (unless explicitly granted `costs:read`)
- Permission model:
  ```python
  class CostPermission:
      """Cost-specific permissions checked before serving any cost data."""
      COSTS_READ = "costs:read"              # View cost dashboards
      COSTS_EXPORT = "costs:export"          # Export cost reports (PDF/CSV)
      COSTS_ADMIN = "costs:admin"            # Manage budgets, allocation rules
      COSTS_FORECAST = "costs:forecast"      # View forecasts
      COSTS_OPTIMIZE = "costs:optimize"      # View optimization recommendations
      BUDGET_MANAGE = "budget:manage"        # Create/update budgets
      BUDGET_OVERRIDE = "budget:override"    # Override budget limits (emergency)
      CHARGEBACK_GENERATE = "chargeback:generate"  # Generate chargeback reports
      CHARGEBACK_APPROVE = "chargeback:approve"    # Approve chargeback reports
  ```
- API-level cost queries require `costs:read` permission at minimum
- Department-level cost reports filtered by `department_id` matching user's department membership
- All cost data access logged to audit trail (who viewed what cost data, when)

### Usage Attribution Per Identity

**Complete Cost Lineage**
- Every token, every API call, every execution attributed to full identity chain:
  ```
  User (who triggered it)
    → Department (which department the user belongs to)
      → Workspace (which workspace the agent lives in)
        → Tenant (which organization)
          → Agent (which agent executed)
            → Execution (specific execution run)
              → Model (which LLM was used)
                → Provider (which provider served the request)
  ```
- Attribution resolution:
  ```python
  class CostAttribution(SQLModel, table=True):
      """Links every cost entry to its full identity chain."""
      id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
      cost_entry_id: uuid.UUID = Field(foreign_key="cost_entries.id")
      
      # Identity chain
      user_id: uuid.UUID = Field(foreign_key="users.id")
      department_id: uuid.UUID | None  # User's department at time of execution
      workspace_id: uuid.UUID = Field(foreign_key="workspaces.id")
      tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
      
      # What generated the cost
      agent_id: uuid.UUID = Field(foreign_key="agents.id")
      agent_version_id: uuid.UUID | None = Field(foreign_key="agent_versions.id")
      execution_id: uuid.UUID = Field(foreign_key="executions.id")
      
      # Provider details
      model_id: uuid.UUID = Field(foreign_key="model_providers.id")
      model_name: str  # Denormalized for query performance
      provider: str  # "openai", "anthropic", etc.
      
      created_at: datetime
  ```
- Sub-agent calls attributed to the parent agent's owner/department
- Shared infrastructure costs (platform overhead) allocated separately via allocation rules

### Universal Token Ledger

**Token Ledger Data Model**
```python
class CostEntry(SQLModel, table=True):
    """Immutable, append-only. No UPDATE or DELETE operations ever.
    This is the single source of truth for all LLM costs on the platform."""
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Execution context
    execution_id: uuid.UUID = Field(foreign_key="executions.id")
    agent_id: uuid.UUID = Field(foreign_key="agents.id")
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    user_id: uuid.UUID = Field(foreign_key="users.id")
    
    # Model details
    model_id: uuid.UUID = Field(foreign_key="model_providers.id")
    model_name: str  # "gpt-4-turbo", "claude-3-5-sonnet"
    provider: str  # "openai", "anthropic"
    
    # Token usage
    input_tokens: int
    output_tokens: int
    total_tokens: int  # input + output
    cached_tokens: int = 0  # Tokens served from prompt cache (reduced cost)
    
    # Cost calculation
    input_cost_usd: Decimal  # input_tokens × model input rate
    output_cost_usd: Decimal  # output_tokens × model output rate
    total_cost_usd: Decimal  # Total cost for this call
    currency: str = "USD"
    
    # Pricing model used
    pricing_model: Literal["per_token", "per_character", "per_request", "tiered", "reserved"]
    pricing_tier: str | None  # For tiered pricing: which tier applied
    price_per_1k_input: Decimal  # Rate at time of execution (immutable snapshot)
    price_per_1k_output: Decimal
    
    # Performance
    latency_ms: float  # Total request latency
    time_to_first_token_ms: float | None  # For streaming requests
    
    # Routing context
    routing_decision_id: uuid.UUID | None = Field(foreign_key="routing_decisions.id")
    routing_strategy: str | None  # Which strategy selected this model
    was_fallback: bool = False
    
    # Request metadata
    request_type: Literal["completion", "chat", "embedding", "image", "audio", "function_call"]
    is_streaming: bool = False
    
    # Ledger integrity
    sequence_number: int  # Monotonically increasing per tenant
    entry_hash: str  # SHA-256 hash for tamper detection
    previous_hash: str  # Previous entry hash (chain)
    
    created_at: datetime  # Timestamp of the LLM call completion
```

**Ledger Properties**
- **Immutable**: No UPDATE or DELETE operations. Corrections are posted as adjustment entries
- **Hash-chained**: Each entry's hash includes the previous entry's hash (tamper detection)
- **Real-time**: Entries written synchronously within the execution pipeline (<10ms overhead)
- **Comprehensive**: Every LLM call generates exactly one ledger entry — no gaps
- **Multi-pricing support**:
  - Per-token (OpenAI, Anthropic): `cost = tokens × rate_per_token`
  - Per-character (Google PaLM): `cost = characters × rate_per_character`
  - Per-request (some APIs): `cost = flat_rate_per_request`
  - Tiered pricing: rate decreases as volume increases within billing period
  - Reserved capacity: pre-purchased token blocks at discount; usage deducted from reservation first

**Real-Time Aggregation**
- Aggregation views maintained in Redis for instant dashboard queries:
  - `cost:realtime:{tenant_id}:total` — current period total
  - `cost:realtime:{tenant_id}:by_department:{dept_id}` — per department
  - `cost:realtime:{tenant_id}:by_model:{model_id}` — per model
  - `cost:realtime:{tenant_id}:by_agent:{agent_id}` — per agent
  - `cost:realtime:{tenant_id}:by_user:{user_id}` — per user
- Redis counters updated on every ledger write (INCRBY with pipeline)
- Counters reset on period boundary (daily/weekly/monthly)
- Historical aggregations computed via background worker and stored in PostgreSQL materialized views

### Cost Allocation Models

**Allocation Strategies**
```python
class CostAllocation(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    name: str
    description: str | None
    
    allocation_model: Literal["direct", "shared", "allocated"]
    
    # Direct: actual usage attributed to the user/department who triggered it
    # No additional configuration needed — this is the default
    
    # Shared: infrastructure costs split by usage ratio
    shared_config: dict | None
    # {
    #   "cost_pool": "platform_infrastructure",
    #   "split_by": "token_usage_ratio",  # or "execution_count_ratio", "equal_split"
    #   "departments": ["engineering", "finance", "legal"],
    #   "period": "monthly"
    # }
    
    # Allocated: pre-assigned budgets with enforcement
    allocated_config: dict | None
    # {
    #   "allocations": {
    #     "engineering": {"amount_usd": 5000, "period": "monthly"},
    #     "finance": {"amount_usd": 2000, "period": "monthly"},
    #     "legal": {"amount_usd": 1000, "period": "monthly"}
    #   },
    #   "overage_policy": "alert"  # or "block", "charge_back"
    # }
    
    is_active: bool = True
    effective_from: date
    effective_until: date | None
    
    created_at: datetime
    updated_at: datetime | None
    created_by: uuid.UUID
```

### Budget Management

**Hierarchical Budget Structure**
```python
class Budget(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Hierarchy level
    scope: Literal["platform", "tenant", "department", "workspace", "user", "agent"]
    scope_id: uuid.UUID  # ID of the entity this budget applies to
    scope_name: str  # Human-readable: "Engineering Department", "Agent: Code Reviewer"
    
    # Parent budget (for hierarchy enforcement)
    parent_budget_id: uuid.UUID | None = Field(foreign_key="budgets.id")
    
    # Budget amount
    amount_usd: Decimal  # Total budget for the period
    period: Literal["daily", "weekly", "monthly", "quarterly", "annual"]
    period_start: date
    period_end: date
    
    # Current usage
    spent_usd: Decimal = Decimal("0.00")  # Current period spend
    remaining_usd: Decimal  # amount - spent
    usage_pct: float = 0.0  # spent / amount × 100
    
    # Limits
    limit_type: Literal["hard", "soft"]
    # hard: block execution when budget exhausted
    # soft: alert only, allow execution to continue
    burst_allowance_pct: float = 0.0  # Configurable overage % (e.g., 10% = allow 110% of budget)
    
    # Alert thresholds
    alert_thresholds: list[int] = Field(default_factory=lambda: [50, 75, 90, 100])
    alerts_sent: list[int] = Field(default_factory=list)  # Which thresholds have triggered
    
    # Rollover
    rollover_policy: Literal["reset", "carry_forward", "carry_forward_capped"]
    rollover_cap_pct: float | None  # For carry_forward_capped: max % to carry (e.g., 25%)
    rollover_amount_usd: Decimal = Decimal("0.00")  # Carried from previous period
    
    # Status
    status: Literal["active", "exhausted", "overdrawn", "closed"]
    exhausted_at: datetime | None
    
    created_at: datetime
    updated_at: datetime | None
    created_by: uuid.UUID
```

**Budget Enforcement**
- Pre-execution check: before any LLM call, check applicable budgets in hierarchy order:
  1. User budget → 2. Agent budget → 3. Workspace budget → 4. Department budget → 5. Tenant budget
  - If ANY hard-limit budget is exhausted: block execution, return `HTTP 429` with budget info
  - If ANY soft-limit budget is exhausted: allow execution, send alert
- Budget check implementation:
  ```python
  class BudgetEnforcer:
      """Checks all applicable budgets before allowing execution."""
      async def check(self, execution_context: ExecutionContext) -> BudgetCheckResult:
          budgets = await self.get_applicable_budgets(
              user_id=execution_context.user_id,
              agent_id=execution_context.agent_id,
              workspace_id=execution_context.workspace_id,
              department_id=execution_context.department_id,
              tenant_id=execution_context.tenant_id,
          )
          for budget in budgets:
              if budget.status == "exhausted" and budget.limit_type == "hard":
                  if budget.usage_pct <= (100 + budget.burst_allowance_pct):
                      continue  # Within burst allowance
                  return BudgetCheckResult(
                      allowed=False,
                      blocking_budget=budget,
                      message=f"Budget '{budget.scope_name}' exhausted: ${budget.spent_usd:.2f}/${budget.amount_usd:.2f}",
                  )
          return BudgetCheckResult(allowed=True)
  ```
- Post-execution update: after LLM call, update all applicable budgets with cost
- Alert triggers: when usage crosses threshold, send notifications to budget owner
- Budget exhaustion event published to Redis pub/sub for real-time dashboard updates

### Forecasting

**ML-Based Cost Forecasting**
```python
class CostForecast(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Scope
    scope: Literal["tenant", "department", "workspace", "agent", "model"]
    scope_id: uuid.UUID
    scope_name: str
    
    # Forecast parameters
    forecast_horizon: Literal["daily", "weekly", "monthly"]
    forecast_generated_at: datetime
    model_used: str  # "prophet", "arima", "linear_regression"
    
    # Historical inputs
    training_data_start: date
    training_data_end: date
    training_data_points: int
    
    # Predictions
    predictions: list[dict]
    # [
    #   {"date": "2024-02-01", "predicted_cost_usd": 1250.00, "lower_bound": 1100.00, "upper_bound": 1400.00},
    #   {"date": "2024-02-02", "predicted_cost_usd": 1300.00, "lower_bound": 1150.00, "upper_bound": 1450.00},
    #   ...
    # ]
    
    # Confidence
    confidence_level: float = 0.95  # 95% confidence interval
    mape: float | None  # Mean Absolute Percentage Error on validation set
    
    # Budget comparison
    budget_id: uuid.UUID | None = Field(foreign_key="budgets.id")
    budget_amount_usd: Decimal | None
    forecasted_period_total_usd: Decimal  # Total forecasted spend for the period
    budget_exhaustion_date: date | None  # "At current rate, budget exhausted by this date"
    will_exceed_budget: bool = False
    overage_forecast_usd: Decimal | None  # How much over budget
    
    # What-if scenarios
    scenarios: list[dict] | None
    # [
    #   {"name": "Add 10 users", "forecasted_total": 1850.00, "delta": +200.00},
    #   {"name": "Switch to Claude Haiku", "forecasted_total": 950.00, "delta": -300.00},
    # ]
    
    created_at: datetime
```

**Forecasting Engine**
- Uses Facebook Prophet (or fallback to ARIMA/linear regression for small datasets):
  - Inputs: historical daily cost data, growth trends, seasonal patterns (weekday vs weekend, month-end spikes)
  - Outputs: daily/weekly/monthly predictions with confidence intervals
  - Retrained weekly with latest data
- Alerts:
  - "At current rate, Engineering dept budget will be exhausted by March 15"
  - "Monthly cost forecast: $12,500 (budget: $10,000) — 25% overage expected"
  - "Seasonal spike detected: expect 40% cost increase during Q4"
- What-if scenario modeling:
  - "What if we add 10 users?" → recalculate forecast with adjusted growth rate
  - "What if we switch Agent X from GPT-4 to Claude 3.5 Haiku?" → model cost delta
  - "What if we add a new department?" → allocate proportional budget share

### Chargeback Reports

**Report Data Model**
```python
class ChargebackReport(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Report scope
    report_type: Literal["monthly", "quarterly", "annual", "custom"]
    period_start: date
    period_end: date
    department_id: uuid.UUID | None  # Null = all departments
    
    # Status
    status: Literal["generating", "generated", "reviewed", "approved", "distributed"]
    generated_at: datetime | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    
    # Content
    summary: dict
    # {
    #   "total_cost_usd": 45230.00,
    #   "total_tokens": 125000000,
    #   "total_executions": 15420,
    #   "departments": 8,
    #   "models_used": 5,
    #   "vs_budget": {"amount": 50000, "usage_pct": 90.5, "variance_usd": -4770},
    #   "vs_previous_period": {"previous_total": 42100, "change_pct": +7.4}
    # }
    
    # Breakdown
    by_department: list[dict]  # [{dept_id, dept_name, cost_usd, tokens, executions, budget, pct_of_total}]
    by_model: list[dict]  # [{model_name, provider, cost_usd, tokens, pct_of_total}]
    by_agent: list[dict]  # [{agent_id, agent_name, cost_usd, tokens, executions}]
    by_user: list[dict]  # [{user_id, user_name, cost_usd, tokens, executions}]
    by_connector: list[dict]  # [{connector_type, cost_usd, data_volume_mb}]
    
    # Allocation adjustments
    shared_costs_allocated: Decimal  # Platform overhead allocated to this dept
    allocation_model_used: str  # "direct", "shared", "allocated"
    
    # Export
    pdf_url: str | None  # S3/MinIO URL for PDF export
    csv_url: str | None  # S3/MinIO URL for CSV export
    json_url: str | None  # S3/MinIO URL for JSON export
    
    created_at: datetime
    created_by: uuid.UUID
```

**Report Features**
- Monthly/quarterly reports per department with:
  - Executive summary: total cost, tokens, executions, budget variance
  - Cost breakdown by: model, agent, user, connector, data volume
  - Comparison vs budget: over/under, variance percentage
  - Comparison vs previous period: change percentage, trend
  - Top 10 most expensive agents
  - Top 10 highest-spending users
  - Cost anomalies flagged during the period
- Export formats: PDF (formatted report with charts), CSV (raw data), JSON (API consumption)
- Distribution: auto-email to department heads on generation (configurable)
- Approval workflow: finance team reviews → approves → distributes to stakeholders
- Multi-currency support: convert from USD to tenant's display currency using configurable exchange rates

### Cost Optimization Recommendations

**Recommendation Engine**
```python
class CostOptimizationRecommendation(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # What to optimize
    recommendation_type: Literal[
        "model_switch",        # Switch to cheaper model
        "cache_optimization",  # Enable/improve caching
        "right_sizing",        # Reduce context window usage
        "agent_consolidation", # Merge similar agents
        "schedule_optimization", # Run batch jobs off-hours
        "unused_agent",        # Decommission low-usage agent
    ]
    
    # Target
    target_type: Literal["agent", "model", "department", "workflow"]
    target_id: uuid.UUID
    target_name: str
    
    # Current state
    current_model: str | None
    current_monthly_cost_usd: Decimal
    current_quality_score: float | None
    
    # Recommended change
    recommended_action: str  # Human-readable action
    recommended_model: str | None  # For model_switch
    estimated_monthly_savings_usd: Decimal
    estimated_quality_impact_pct: float  # Negative = quality reduction
    confidence: float  # 0.0-1.0, based on data quality
    
    # Evidence
    analysis: dict
    # {
    #   "data_points": 1500,
    #   "analysis_period_days": 30,
    #   "current_avg_cost_per_execution": 0.045,
    #   "recommended_avg_cost_per_execution": 0.012,
    #   "quality_comparison": {"current_score": 0.92, "recommended_score": 0.90},
    #   "sample_outputs_compared": 50
    # }
    
    # Status
    status: Literal["new", "viewed", "accepted", "rejected", "implemented"]
    viewed_by: uuid.UUID | None
    viewed_at: datetime | None
    decision_by: uuid.UUID | None
    decision_at: datetime | None
    rejection_reason: str | None
    
    created_at: datetime
    expires_at: datetime  # Recommendations expire after 30 days
```

**Recommendation Types**
- **Model switch**: "Switch agent 'Code Reviewer' from GPT-4 to Claude 3.5 Haiku — saves $340/month with 2% quality reduction". Based on:
  - Actual usage patterns (how many tokens, what task types)
  - Quality comparison (run same prompts through both models, compare outputs)
  - Cost delta calculation
- **Cache optimization**: "Enable prompt caching for agent 'FAQ Bot' — 45% of prompts are identical. Estimated savings: $120/month"
  - Identify repeated identical or near-identical prompts
  - Calculate cache hit ratio potential
- **Right-sizing**: "Agent 'Summarizer' uses avg 2,100 tokens but has 8K context window configured. Reducing to 4K saves $80/month"
  - Analyze actual vs configured context window usage
- **Agent consolidation**: "Agents 'Email Drafts' and 'Email Reply' have 80% prompt overlap. Consolidating saves $150/month"
- **Schedule optimization**: "Agent 'Report Generator' runs at 2 PM (peak hours). Moving to 2 AM (off-hours) allows cheaper model routing, saving $90/month"
- **Unused agent**: "Agent 'Old Classifier' has 3 executions in last 30 days. Decommissioning saves $25/month"

### Provider Invoice Reconciliation

**Reconciliation Process**
```python
class InvoiceReconciliation(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(foreign_key="tenants.id")
    
    # Provider
    provider: str  # "openai", "anthropic"
    billing_period_start: date
    billing_period_end: date
    
    # Invoice data (from provider)
    invoice_total_usd: Decimal
    invoice_total_tokens: int | None
    invoice_line_items: list[dict]  # [{model, tokens, cost}]
    invoice_reference: str | None  # Provider invoice ID
    
    # Internal ledger data
    ledger_total_usd: Decimal
    ledger_total_tokens: int
    ledger_line_items: list[dict]  # [{model, tokens, cost}]
    
    # Comparison
    discrepancy_usd: Decimal  # invoice_total - ledger_total
    discrepancy_pct: float  # abs(discrepancy) / max(invoice, ledger) × 100
    discrepancy_flagged: bool  # True if discrepancy > 5%
    
    # Per-model breakdown
    model_discrepancies: list[dict]
    # [{model, invoice_tokens, ledger_tokens, invoice_cost, ledger_cost, discrepancy_pct}]
    
    # Status
    status: Literal["pending", "matched", "discrepancy_found", "investigating", "resolved"]
    resolution_notes: str | None
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    
    created_at: datetime
    created_by: uuid.UUID
```

**Reconciliation Features**
- Monthly reconciliation job: compare internal ledger totals vs provider invoices
- Per-model breakdown: identify which models have discrepancies
- Flag discrepancies >5% for investigation
- Common discrepancy causes tracked: rate changes, rounding differences, timezone mismatches, delayed billing
- Auto-import provider invoices via API (where available) or manual CSV upload
- Reconciliation history with trend analysis (are discrepancies growing?)

## Output Structure

```
backend/
├── app/
│   ├── models/
│   │   └── cost.py                   # CostEntry, CostAttribution, Budget,
│   │                                  # CostForecast, ChargebackReport,
│   │                                  # CostAllocation, CostOptimizationRecommendation,
│   │                                  # InvoiceReconciliation
│   ├── routers/
│   │   └── cost.py                   # All cost API endpoints
│   ├── services/
│   │   └── cost/
│   │       ├── __init__.py           # CostEngine export
│   │       ├── engine.py             # Core cost engine (record, aggregate, query)
│   │       ├── ledger.py             # Universal token ledger (append-only, hash-chained)
│   │       ├── attribution.py        # Cost attribution resolution
│   │       ├── budget.py             # Budget management + enforcement
│   │       ├── budget_enforcer.py    # Pre-execution budget check
│   │       ├── allocation.py         # Cost allocation models (direct, shared, allocated)
│   │       ├── forecasting.py        # ML-based cost forecasting (Prophet/ARIMA)
│   │       ├── chargeback.py         # Chargeback report generation
│   │       ├── report_generator.py   # PDF/CSV/JSON export
│   │       ├── optimizer.py          # Cost optimization recommendation engine
│   │       ├── reconciliation.py     # Provider invoice reconciliation
│   │       ├── aggregator.py         # Real-time Redis aggregation
│   │       ├── pricing.py            # Multi-pricing model support
│   │       └── currency.py           # Multi-currency conversion
│   └── middleware/
│       └── cost.py                   # Request-level cost tracking injection
├── tests/
│   └── test_cost/
│       ├── __init__.py
│       ├── conftest.py               # Cost test fixtures, mock providers, sample data
│       ├── test_engine.py            # Core cost engine tests
│       ├── test_ledger.py            # Ledger immutability, hash chain, integrity
│       ├── test_attribution.py       # Cost attribution chain tests
│       ├── test_budget.py            # Budget creation, enforcement, alerts
│       ├── test_budget_enforcer.py   # Pre-execution budget check tests
│       ├── test_allocation.py        # Allocation model tests
│       ├── test_forecasting.py       # Forecast accuracy tests
│       ├── test_chargeback.py        # Report generation tests
│       ├── test_optimizer.py         # Optimization recommendation tests
│       ├── test_reconciliation.py    # Invoice reconciliation tests
│       ├── test_aggregator.py        # Redis aggregation tests
│       └── test_permissions.py       # Cost access control tests
ops/
└── cost/
    ├── grafana/
    │   ├── cost-overview-dashboard.json    # Platform-wide cost overview
    │   ├── department-cost-dashboard.json  # Per-department drill-down
    │   ├── budget-dashboard.json           # Budget tracking + alerts
    │   ├── forecast-dashboard.json         # Cost forecasting charts
    │   └── reconciliation-dashboard.json   # Invoice reconciliation status
    ├── prometheus/
    │   └── cost-alerts.yml                 # Budget threshold alerts, anomaly alerts
    └── config/
        ├── pricing-models.yml              # Provider pricing configuration
        ├── default-budgets.yml             # Default budget templates
        └── holiday-calendars.yml           # For business-hours cost attribution
frontend/
└── src/
    └── components/
        └── cost/
            ├── CostDashboard.tsx           # Real-time cost overview
            ├── DepartmentCosts.tsx          # Department-level cost drill-down
            ├── BudgetManager.tsx            # Budget CRUD + hierarchy view
            ├── BudgetAlerts.tsx             # Alert threshold configuration
            ├── ForecastView.tsx             # Cost forecast charts + what-if
            ├── ChargebackReports.tsx        # Report generation + export
            ├── OptimizationRecommendations.tsx  # Savings recommendations
            ├── InvoiceReconciliation.tsx    # Reconciliation status + details
            ├── CostExplorer.tsx             # Interactive cost exploration (treemap, stacked area)
            └── UsageAttribution.tsx         # User/agent/model cost attribution
```

## API Endpoints (Complete)

```
# Cost Dashboard
GET    /api/v1/cost/dashboard                         # Cost overview (tenant-scoped, role-filtered)
GET    /api/v1/cost/dashboard/summary                 # Period summary (total cost, tokens, executions)
GET    /api/v1/cost/dashboard/by-department            # Cost by department
GET    /api/v1/cost/dashboard/by-model                 # Cost by model
GET    /api/v1/cost/dashboard/by-agent                 # Cost by agent
GET    /api/v1/cost/dashboard/by-user                  # Cost by user
GET    /api/v1/cost/dashboard/top-spenders             # Top spending users/agents/departments
GET    /api/v1/cost/dashboard/anomalies                # Cost anomalies in current period

# Token Ledger
GET    /api/v1/cost/ledger                             # Query ledger entries (paginated, filtered)
GET    /api/v1/cost/ledger/{id}                        # Get specific ledger entry
GET    /api/v1/cost/ledger/integrity                   # Verify hash chain integrity
GET    /api/v1/cost/ledger/export                      # Export ledger (CSV/JSON)

# Budgets
GET    /api/v1/cost/budgets                            # List budgets (hierarchical view)
POST   /api/v1/cost/budgets                            # Create budget
GET    /api/v1/cost/budgets/{id}                       # Get budget details + usage
PUT    /api/v1/cost/budgets/{id}                       # Update budget
DELETE /api/v1/cost/budgets/{id}                       # Close budget
GET    /api/v1/cost/budgets/{id}/history               # Budget usage history
POST   /api/v1/cost/budgets/{id}/alerts               # Configure alert thresholds
POST   /api/v1/cost/budgets/{id}/override             # Emergency budget override (requires budget:override)

# Cost Allocation
GET    /api/v1/cost/allocations                        # List allocation models
POST   /api/v1/cost/allocations                        # Create allocation model
PUT    /api/v1/cost/allocations/{id}                   # Update allocation model
DELETE /api/v1/cost/allocations/{id}                   # Delete allocation model

# Forecasting
GET    /api/v1/cost/forecasts                          # List forecasts
POST   /api/v1/cost/forecasts                          # Generate new forecast
GET    /api/v1/cost/forecasts/{id}                     # Get forecast details + predictions
GET    /api/v1/cost/forecasts/latest                   # Get most recent forecast per scope
POST   /api/v1/cost/forecasts/what-if                  # Run what-if scenario

# Chargeback Reports
GET    /api/v1/cost/chargeback                         # List chargeback reports
POST   /api/v1/cost/chargeback                         # Generate chargeback report
GET    /api/v1/cost/chargeback/{id}                    # Get report details
POST   /api/v1/cost/chargeback/{id}/approve            # Approve report (finance_admin)
GET    /api/v1/cost/chargeback/{id}/pdf                # Download PDF report
GET    /api/v1/cost/chargeback/{id}/csv                # Download CSV report
POST   /api/v1/cost/chargeback/{id}/distribute         # Distribute report to stakeholders

# Optimization
GET    /api/v1/cost/optimizations                      # List optimization recommendations
GET    /api/v1/cost/optimizations/{id}                 # Get recommendation details
POST   /api/v1/cost/optimizations/{id}/accept          # Accept recommendation
POST   /api/v1/cost/optimizations/{id}/reject          # Reject recommendation (with reason)
POST   /api/v1/cost/optimizations/{id}/implement       # Implement recommendation (trigger model switch, etc.)
POST   /api/v1/cost/optimizations/analyze              # Trigger optimization analysis

# Invoice Reconciliation
GET    /api/v1/cost/reconciliation                     # List reconciliation records
POST   /api/v1/cost/reconciliation                     # Create reconciliation (upload invoice)
GET    /api/v1/cost/reconciliation/{id}                # Get reconciliation details
POST   /api/v1/cost/reconciliation/{id}/resolve        # Resolve discrepancy
GET    /api/v1/cost/reconciliation/summary             # Reconciliation health summary

# Usage Attribution
GET    /api/v1/cost/attribution/{execution_id}         # Full cost attribution chain for an execution
GET    /api/v1/cost/attribution/user/{user_id}         # User's complete cost history
GET    /api/v1/cost/attribution/agent/{agent_id}       # Agent's complete cost history

# Metrics
GET    /api/v1/cost/metrics                            # Cost metrics for Prometheus/Grafana
```

## Verify Commands

```bash
# Cost engine importable
cd ~/Scripts/Archon && python -c "from backend.app.services.cost import CostEngine; print('OK')"

# All cost models importable
cd ~/Scripts/Archon && python -c "from backend.app.models.cost import CostEntry, CostAttribution, Budget, CostForecast, ChargebackReport, CostAllocation, CostOptimizationRecommendation, InvoiceReconciliation; print('All models OK')"

# Ledger service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.cost.ledger import TokenLedger; print('Ledger OK')"

# Budget enforcer importable
cd ~/Scripts/Archon && python -c "from backend.app.services.cost.budget_enforcer import BudgetEnforcer; print('Budget enforcer OK')"

# Forecasting service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.cost.forecasting import CostForecaster; print('Forecasting OK')"

# Chargeback service importable
cd ~/Scripts/Archon && python -c "from backend.app.services.cost.chargeback import ChargebackGenerator; print('Chargeback OK')"

# Optimizer importable
cd ~/Scripts/Archon && python -c "from backend.app.services.cost.optimizer import CostOptimizer; print('Optimizer OK')"

# Reconciliation importable
cd ~/Scripts/Archon && python -c "from backend.app.services.cost.reconciliation import InvoiceReconciler; print('Reconciliation OK')"

# Cost API endpoints registered
cd ~/Scripts/Archon && python -c "from backend.app.routers.cost import router; print(f'{len(router.routes)} routes registered')"

# Tests pass
cd ~/Scripts/Archon/backend && python -m pytest tests/test_cost/ --tb=short -q

# Ledger integrity tests
cd ~/Scripts/Archon/backend && python -m pytest tests/test_cost/test_ledger.py --tb=short -q

# Budget enforcement tests
cd ~/Scripts/Archon/backend && python -m pytest tests/test_cost/test_budget_enforcer.py --tb=short -q

# No hardcoded pricing or secrets
cd ~/Scripts/Archon && ! grep -rn 'api_key\s*=\s*"[^"]*"' --include='*.py' backend/app/services/cost/ || echo 'FAIL: hardcoded keys found'
```

## Learnings Protocol

Before starting, read `.sdd/learnings/*.md` for known pitfalls from previous sessions.
After completing work, report any pitfalls or patterns discovered so the orchestrator can capture them.

## Acceptance Criteria

- [ ] Every LLM call logged in token ledger with <10ms overhead
- [ ] Ledger is immutable: no UPDATE or DELETE operations allowed
- [ ] Ledger hash chain is tamper-evident (modify a row → integrity check fails)
- [ ] Complete cost attribution chain resolves: user → department → workspace → tenant → provider
- [ ] Cost dashboards gated by role: finance_admin sees all, developer sees own only
- [ ] Department-level cost reports filtered by user's department membership
- [ ] API cost queries require `costs:read` permission (401 without)
- [ ] Real-time cost aggregation in Redis updates within 5 seconds of LLM call
- [ ] Dashboard shows real-time cost within 5-second delay
- [ ] Multi-pricing support works: per-token (OpenAI), per-character (Google), per-request, tiered
- [ ] Direct allocation correctly attributes actual usage to triggering user/department
- [ ] Shared allocation splits infrastructure costs by usage ratio
- [ ] Allocated budgets enforce pre-assigned amounts
- [ ] Hierarchical budgets enforce: platform → tenant → department → workspace → user
- [ ] Hard budget limits block execution with HTTP 429 and budget details
- [ ] Soft budget limits allow execution with alert notification
- [ ] Burst allowance permits configurable overage percentage
- [ ] Budget alerts fire within 1 minute of threshold breach (50%, 75%, 90%, 100%)
- [ ] Budget rollover correctly carries forward unused amount (with cap)
- [ ] Cost forecasting produces predictions within 15% MAPE for 30-day horizon
- [ ] Forecast alerts fire when projected spend exceeds budget
- [ ] What-if scenarios correctly model cost impact of configuration changes
- [ ] Chargeback reports generate correctly for 10+ departments
- [ ] Chargeback PDF/CSV export produces valid, downloadable files
- [ ] Chargeback includes comparison vs budget and vs previous period
- [ ] Approval workflow enforces review before distribution
- [ ] Optimization recommendations identify at least 3 savings opportunities in test data
- [ ] Model switch recommendations include quality impact estimate
- [ ] Cache optimization recommendations correctly identify repeated prompts
- [ ] Provider invoice reconciliation flags discrepancies >5%
- [ ] Reconciliation per-model breakdown identifies which models have discrepancies
- [ ] All tests pass with >80% coverage on cost module
- [ ] Zero hardcoded pricing data in source code (all configurable)
- [ ] Grafana dashboards deployed with cost, budget, forecast, and reconciliation panels
