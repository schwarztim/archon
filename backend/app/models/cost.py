"""SQLModel database models and Pydantic schemas for the Archon cost engine."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field as PField
from sqlalchemy import Column, Numeric
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


# ── SQLModel ORM tables (existing) ─────────────────────────────────


class TokenLedger(SQLModel, table=True):
    """Immutable append-only ledger entry for a single LLM call's token usage and cost."""

    __tablename__ = "token_ledger"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    execution_id: UUID | None = Field(
        default=None, index=True, foreign_key="executions.id"
    )
    agent_id: UUID | None = Field(default=None, index=True, foreign_key="agents.id")
    user_id: UUID | None = Field(default=None, index=True, foreign_key="users.id")
    department_id: UUID | None = Field(default=None, index=True)
    workspace_id: UUID | None = Field(default=None, index=True)

    # Provider and model
    provider: str = Field(index=True)  # openai | anthropic | google | azure
    model_id: str = Field(index=True)  # e.g. "gpt-4o", "claude-3-5-sonnet"

    # Token counts
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)

    # Cost in USD
    input_cost: float = Field(default=0.0)
    output_cost: float = Field(default=0.0)
    total_cost: float = Field(default=0.0)

    # Performance
    latency_ms: float = Field(default=0.0)

    # Attribution chain stored as JSON
    attribution_chain: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("attribution_chain", JSON, nullable=False),
    )

    # Extra context
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column("metadata", JSON, nullable=False)
    )

    created_at: datetime = Field(default_factory=_utcnow, index=True)


class ProviderPricing(SQLModel, table=True):
    """Pricing configuration for a specific provider model combination.

    Costs are expressed per 1 million tokens in USD.
    """

    __tablename__ = "provider_pricing"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    provider: str = Field(index=True)  # openai | anthropic | google | azure
    model_id: str = Field(index=True)  # e.g. "gpt-4o"
    display_name: str = Field(default="")

    cost_per_input_token: float = Field(default=0.0)  # USD per 1M input tokens
    cost_per_output_token: float = Field(default=0.0)  # USD per 1M output tokens

    is_active: bool = Field(default=True)

    effective_from: datetime = Field(default_factory=_utcnow)
    effective_to: datetime | None = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class Budget(SQLModel, table=True):
    """Spending budget for a department, user, or agent."""

    __tablename__ = "budgets"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    name: str = Field(index=True)
    scope: str = Field(
        default="department"
    )  # tenant | department | workspace | user | agent | global

    # Scope target — exactly one should be set depending on scope
    department_id: UUID | None = Field(default=None, index=True)
    workspace_id: UUID | None = Field(default=None, index=True)
    user_id: UUID | None = Field(default=None, index=True, foreign_key="users.id")
    agent_id: UUID | None = Field(default=None, index=True, foreign_key="agents.id")

    # Budget limits in USD
    limit_amount: float = Field(default=0.0)
    spent_amount: float = Field(default=0.0)
    currency: str = Field(default="USD")

    # Period
    period: str = Field(default="monthly")  # monthly | weekly | daily | total
    period_start: datetime = Field(default_factory=_utcnow)
    period_end: datetime | None = Field(default=None)

    # Enforcement
    enforcement: str = Field(default="soft")  # soft (alert only) | hard (block)
    hard_limit: bool = Field(default=False)
    alert_threshold_pct: float = Field(default=80.0)
    is_active: bool = Field(default=True)

    # Alert thresholds (percentages)
    alert_thresholds: list[float] = Field(
        default_factory=lambda: [50.0, 75.0, 90.0, 100.0],
        sa_column=Column(JSON, nullable=False),
    )

    # Rollover policy
    rollover_enabled: bool = Field(default=False)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class CostAlert(SQLModel, table=True):
    """Alert generated when a budget threshold is breached."""

    __tablename__ = "cost_alerts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    budget_id: UUID = Field(index=True, foreign_key="budgets.id")

    alert_type: str = Field(default="threshold")  # threshold | forecast | anomaly
    severity: str = Field(default="warning")  # info | warning | critical

    threshold_pct: float = Field(default=0.0)  # e.g. 75.0 for 75%
    current_spend: float = Field(default=0.0)
    budget_limit: float = Field(default=0.0)

    message: str = Field(default="", sa_column=Column(SAText, nullable=False))
    is_acknowledged: bool = Field(default=False)
    acknowledged_at: datetime | None = Field(default=None)
    acknowledged_by: UUID | None = Field(default=None, foreign_key="users.id")

    created_at: datetime = Field(default_factory=_utcnow)


class DepartmentBudget(SQLModel, table=True):
    """Per-department spending budget with warn/block thresholds.

    Tracks monthly or quarterly budget for a department with automatic
    threshold enforcement via warn_threshold_pct and block_threshold_pct.
    """

    __tablename__ = "department_budgets"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    department_id: UUID = Field(index=True)

    budget_usd: Decimal = Field(
        default=Decimal("0"), sa_column=Column(Numeric(10, 6), nullable=False)
    )
    period: str = Field(default="monthly")  # monthly | quarterly

    warn_threshold_pct: int = Field(default=80)
    block_threshold_pct: int = Field(default=100)

    current_spend_usd: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column("current_spend_usd", Numeric(10, 6), nullable=False),
    )

    period_start: date = Field(default_factory=date.today)
    period_end: date = Field(default_factory=date.today)

    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ── Pydantic API schemas ───────────────────────────────────────────


class BudgetScope(str, Enum):
    """Hierarchical budget scope levels."""

    TENANT = "tenant"
    DEPARTMENT = "department"
    WORKSPACE = "workspace"
    USER = "user"


class BudgetPeriod(str, Enum):
    """Budget period options."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    TOTAL = "total"


class UsageEvent(BaseModel):
    """Incoming usage event for a single LLM call."""

    execution_id: UUID | None = None
    user_id: UUID | None = None
    agent_id: UUID | None = None
    department_id: UUID | None = None
    workspace_id: UUID | None = None
    provider: str
    model: str
    input_tokens: int = PField(ge=0)
    output_tokens: int = PField(ge=0)
    cost_usd: float | None = PField(default=None, ge=0.0)
    timestamp: datetime = PField(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = PField(default_factory=dict)


class AttributionChain(BaseModel):
    """Full attribution from user to provider."""

    user_id: str | None = None
    department_id: str | None = None
    workspace_id: str | None = None
    tenant_id: str = ""
    provider: str = ""
    model: str = ""
    agent_id: str | None = None
    execution_id: str | None = None


class TokenLedgerEntry(BaseModel):
    """Immutable ledger entry returned from record_usage."""

    id: UUID
    tenant_id: str
    execution_id: UUID | None = None
    agent_id: UUID | None = None
    user_id: UUID | None = None
    department_id: UUID | None = None
    workspace_id: UUID | None = None
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_cost: float
    output_cost: float
    total_cost: float
    latency_ms: float
    attribution_chain: AttributionChain
    timestamp: datetime

    @classmethod
    def from_orm_entry(cls, entry: TokenLedger) -> TokenLedgerEntry:
        """Build from a TokenLedger ORM instance."""
        chain_data = entry.attribution_chain or {}
        return cls(
            id=entry.id,
            tenant_id=entry.tenant_id,
            execution_id=entry.execution_id,
            agent_id=entry.agent_id,
            user_id=entry.user_id,
            department_id=entry.department_id,
            workspace_id=entry.workspace_id,
            provider=entry.provider,
            model=entry.model_id,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            total_tokens=entry.total_tokens,
            input_cost=entry.input_cost,
            output_cost=entry.output_cost,
            total_cost=entry.total_cost,
            latency_ms=entry.latency_ms,
            attribution_chain=AttributionChain(**chain_data)
            if chain_data
            else AttributionChain(),
            timestamp=entry.created_at,
        )


class CostSummary(BaseModel):
    """Aggregated cost summary for a period."""

    total_cost: float
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    call_count: int = 0
    by_provider: dict[str, float] = PField(default_factory=dict)
    by_model: dict[str, float] = PField(default_factory=dict)
    by_department: dict[str, float] = PField(default_factory=dict)
    by_user: dict[str, float] = PField(default_factory=dict)
    period: dict[str, str] = PField(default_factory=dict)


class BudgetConfig(BaseModel):
    """Configuration for creating/updating a budget."""

    name: str
    scope: BudgetScope = BudgetScope.DEPARTMENT
    department_id: UUID | None = None
    workspace_id: UUID | None = None
    user_id: UUID | None = None
    limit_usd: float = PField(gt=0.0)
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    hard_limit: bool = False
    alert_threshold_pct: float = PField(default=80.0, ge=0.0, le=100.0)


class BudgetResponse(BaseModel):
    """Budget details returned from the API."""

    id: UUID
    tenant_id: str
    config: BudgetConfig
    current_usage: float
    remaining: float
    status: str  # active | exhausted | warning


class BudgetCheckResult(BaseModel):
    """Result of a pre-execution budget check."""

    allowed: bool
    budget_id: UUID | None = None
    usage_pct: float = 0.0
    warning_message: str | None = None
    status: str = "allowed"  # allowed | soft_limit_warning | hard_limit_blocked


class ChargebackLineItem(BaseModel):
    """Single line item in a chargeback report."""

    provider: str
    model: str
    call_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ChargebackReport(BaseModel):
    """Departmental chargeback report."""

    department_id: UUID | None = None
    department_name: str = ""
    period: dict[str, str] = PField(default_factory=dict)
    line_items: list[ChargebackLineItem] = PField(default_factory=list)
    total: float = 0.0
    pdf_url: str | None = None
    csv_url: str | None = None


class DailyProjection(BaseModel):
    """Single day projection for forecasting."""

    date: str
    projected_cost: float
    cumulative_cost: float


class CostForecast(BaseModel):
    """Cost forecast with daily projections."""

    daily_projections: list[DailyProjection] = PField(default_factory=list)
    confidence_interval: dict[str, float] = PField(default_factory=dict)
    trend: str = "stable"  # increasing | decreasing | stable
    daily_avg: float = 0.0
    projected_total: float = 0.0


class Recommendation(BaseModel):
    """Cost optimisation recommendation."""

    type: str  # model_switch | batch_optimization | cache_usage | budget_adjustment
    description: str
    estimated_savings: float
    effort: str = "low"  # low | medium | high
    priority: int = PField(default=3, ge=1, le=5)  # 1=highest


class ReconciliationLineItem(BaseModel):
    """Single line in reconciliation comparison."""

    model: str
    ledger_cost: float
    invoice_cost: float
    difference: float


class ReconciliationResult(BaseModel):
    """Result of comparing ledger vs provider invoice."""

    provider: str
    period: dict[str, str] = PField(default_factory=dict)
    ledger_total: float
    invoice_total: float
    difference: float
    match_pct: float
    line_items: list[ReconciliationLineItem] = PField(default_factory=list)
    status: str = "matched"  # matched | discrepancy | unreconciled


class CostDashboardData(BaseModel):
    """Full dashboard payload returned by get_dashboard_data()."""

    total_spend: float
    period: str = ""
    trend: list[dict[str, Any]] = PField(default_factory=list)
    by_provider: list[dict[str, Any]] = PField(default_factory=list)
    by_model: list[dict[str, Any]] = PField(default_factory=list)
    by_department: list[dict[str, Any]] = PField(default_factory=list)
    by_agent: list[dict[str, Any]] = PField(default_factory=list)
    anomalies: list[dict[str, Any]] = PField(default_factory=list)
    forecast: dict[str, Any] = PField(default_factory=dict)


__all__ = [
    "AttributionChain",
    "Budget",
    "BudgetCheckResult",
    "BudgetConfig",
    "BudgetPeriod",
    "BudgetResponse",
    "BudgetScope",
    "ChargebackLineItem",
    "ChargebackReport",
    "CostAlert",
    "CostDashboardData",
    "CostForecast",
    "CostSummary",
    "DailyProjection",
    "DepartmentBudget",
    "ProviderPricing",
    "Recommendation",
    "ReconciliationLineItem",
    "ReconciliationResult",
    "TokenLedger",
    "TokenLedgerEntry",
    "UsageEvent",
]
