"""API routes for the Archon cost engine — enterprise token ledger, budgets, chargeback, and forecasting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission, require_permission
from app.models.cost import (
    Budget,
    BudgetCheckResult,
    BudgetConfig,
    BudgetResponse,
    ChargebackReport,
    CostAlert,
    CostForecast,
    CostSummary,
    ProviderPricing,
    Recommendation,
    ReconciliationResult,
    TokenLedger,
    TokenLedgerEntry,
    UsageEvent,
)
from app.services.cost import CostEngine
from app.services.cost_service import CostService

router = APIRouter(prefix="/cost", tags=["cost"])


# ── Request / response schemas ──────────────────────────────────────


class RecordUsageRequest(BaseModel):
    """Payload for recording a single LLM call's token usage."""

    provider: str
    model_id: str
    input_tokens: int = PField(ge=0)
    output_tokens: int = PField(ge=0)
    latency_ms: float = PField(default=0.0, ge=0.0)
    execution_id: UUID | None = None
    agent_id: UUID | None = None
    user_id: UUID | None = None
    department_id: UUID | None = None
    workspace_id: UUID | None = None
    cost_usd: float | None = PField(default=None, ge=0.0)
    metadata: dict[str, Any] = PField(default_factory=dict)


class CalculateCostRequest(BaseModel):
    """Payload for estimating cost without recording."""

    provider: str
    model_id: str
    input_tokens: int = PField(ge=0)
    output_tokens: int = PField(ge=0)


class BudgetCreate(BaseModel):
    """Payload for creating a budget."""

    name: str
    scope: str = "department"
    department_id: UUID | None = None
    user_id: UUID | None = None
    agent_id: UUID | None = None
    limit_amount: float = PField(gt=0.0)
    currency: str = "USD"
    period: str = "monthly"
    period_start: datetime | None = None
    period_end: datetime | None = None
    enforcement: str = "soft"
    is_active: bool = True
    alert_thresholds: list[float] = PField(default_factory=lambda: [50.0, 75.0, 90.0, 100.0])
    rollover_enabled: bool = False


class BudgetUpdate(BaseModel):
    """Payload for partial-updating a budget."""

    name: str | None = None
    limit_amount: float | None = PField(default=None, gt=0.0)
    enforcement: str | None = None
    is_active: bool | None = None
    alert_thresholds: list[float] | None = None
    rollover_enabled: bool | None = None
    period_end: datetime | None = None


class PricingCreate(BaseModel):
    """Payload for creating/updating provider pricing."""

    provider: str
    model_id: str
    display_name: str = ""
    cost_per_input_token: float = PField(ge=0.0)
    cost_per_output_token: float = PField(ge=0.0)
    is_active: bool = True
    effective_from: datetime | None = None


class ForecastRequest(BaseModel):
    """Payload for cost forecasting."""

    budget_id: UUID | None = None
    days_ahead: int = PField(default=30, ge=1, le=365)


class BudgetCheckRequest(BaseModel):
    """Payload for pre-execution budget check."""

    estimated_cost: float = PField(gt=0.0)


class ChargebackRequest(BaseModel):
    """Payload for generating a chargeback report."""

    department_id: UUID | None = None
    since: datetime | None = None
    until: datetime | None = None


class ReconcileRequest(BaseModel):
    """Payload for provider invoice reconciliation."""

    provider: str
    invoice_data: dict[str, Any]


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ══════════════════════════════════════════════════════════════════════
# Enterprise endpoints (authenticated, RBAC, tenant-scoped)
# ══════════════════════════════════════════════════════════════════════


@router.post("/api/v1/costs/record", status_code=201)
async def record_cost_usage(
    body: RecordUsageRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record token usage — internal/service-to-service with full attribution."""
    event = UsageEvent(
        execution_id=body.execution_id,
        user_id=body.user_id,
        agent_id=body.agent_id,
        department_id=body.department_id,
        workspace_id=body.workspace_id,
        provider=body.provider,
        model=body.model_id,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        cost_usd=body.cost_usd,
        metadata=body.metadata,
    )
    entry = await CostService.record_usage(session, user.tenant_id, event)
    return {"data": entry.model_dump(mode="json"), "meta": _meta()}


@router.get("/api/v1/costs/summary")
async def cost_summary(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    group_by: str = Query(default="provider"),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Cost summary with RBAC filtering — finance sees all, dev sees own."""
    period: dict[str, str] | None = None
    if since or until:
        period = {}
        if since:
            period["since"] = since.isoformat()
        if until:
            period["until"] = until.isoformat()

    summary = await CostService.get_cost_summary(
        session, user.tenant_id, user, period=period, group_by=group_by,
    )
    return {"data": summary.model_dump(mode="json"), "meta": _meta()}


@router.post("/api/v1/costs/budget", status_code=201)
async def set_budget(
    body: BudgetConfig,
    user: AuthenticatedUser = Depends(require_permission("costs", "create")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Set a hierarchical budget (tenant, department, workspace, user level)."""
    budget_resp = await CostService.set_budget(session, user.tenant_id, user, body)
    return {"data": budget_resp.model_dump(mode="json"), "meta": _meta()}


@router.post("/api/v1/costs/budget/check")
async def check_budget(
    body: BudgetCheckRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Pre-execution budget check: allowed / soft_limit_warning / hard_limit_blocked."""
    result = await CostService.check_budget(
        session, user.tenant_id, user, body.estimated_cost,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/api/v1/costs/chargeback")
async def generate_chargeback(
    body: ChargebackRequest,
    user: AuthenticatedUser = Depends(require_permission("costs", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Generate chargeback report with cost breakdown per department."""
    period: dict[str, str] | None = None
    if body.since or body.until:
        period = {}
        if body.since:
            period["since"] = body.since.isoformat()
        if body.until:
            period["until"] = body.until.isoformat()

    report = await CostService.generate_chargeback_report(
        session, user.tenant_id, user, period=period, department_id=body.department_id,
    )
    return {"data": report.model_dump(mode="json"), "meta": _meta()}


@router.get("/api/v1/costs/forecast")
async def cost_forecast(
    horizon_days: int = Query(default=30, ge=1, le=365),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Trend-based cost projection for the given horizon."""
    forecast = await CostService.forecast_costs(
        session, user.tenant_id, user, horizon_days=horizon_days,
    )
    return {"data": forecast.model_dump(mode="json"), "meta": _meta()}


@router.get("/api/v1/costs/recommendations")
async def optimization_recommendations(
    user: AuthenticatedUser = Depends(require_permission("costs", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Cost-saving suggestions based on usage patterns."""
    recs = await CostService.get_optimization_recommendations(session, user.tenant_id)
    return {"data": [r.model_dump(mode="json") for r in recs], "meta": _meta()}


@router.post("/api/v1/costs/reconcile")
async def reconcile_invoice(
    body: ReconcileRequest,
    user: AuthenticatedUser = Depends(require_permission("costs", "admin")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Compare ledger vs provider invoice for reconciliation."""
    result = await CostService.reconcile_provider_invoice(
        session, user.tenant_id, body.provider, body.invoice_data,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ══════════════════════════════════════════════════════════════════════
# Legacy endpoints (preserved for backward compatibility)
# ══════════════════════════════════════════════════════════════════════


@router.post("/usage", status_code=201)
async def record_usage(
    body: RecordUsageRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record token usage for a single LLM call."""
    entry = await CostEngine.record_usage(
        session,
        provider=body.provider,
        model_id=body.model_id,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
        latency_ms=body.latency_ms,
        execution_id=body.execution_id,
        agent_id=body.agent_id,
        user_id=body.user_id,
        department_id=body.department_id,
        metadata=body.metadata,
    )
    return {"data": entry.model_dump(mode="json"), "meta": _meta()}


@router.get("/usage")
async def list_usage(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    provider: str | None = Query(default=None),
    model_id: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List token ledger entries with optional filters."""
    entries, total = await CostEngine.list_ledger(
        session,
        provider=provider,
        model_id=model_id,
        agent_id=agent_id,
        user_id=user_id,
        department_id=department_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in entries],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/usage/{entry_id}")
async def get_usage(
    entry_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single ledger entry by ID."""
    entry = await CostEngine.get_ledger_entry(session, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Ledger entry not found")
    return {"data": entry.model_dump(mode="json"), "meta": _meta()}


# ── Cost Calculation ────────────────────────────────────────────────


@router.post("/calculate")
async def calculate_cost(
    body: CalculateCostRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Estimate cost for a given token usage without recording."""
    result = await CostEngine.calculate_cost(
        session,
        provider=body.provider,
        model_id=body.model_id,
        input_tokens=body.input_tokens,
        output_tokens=body.output_tokens,
    )
    return {"data": result, "meta": _meta()}


# ── Cost Reports ────────────────────────────────────────────────────


@router.get("/report")
async def cost_report(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    group_by: str = Query(default="provider"),
    department_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Generate an aggregated cost report."""
    report = await CostEngine.generate_cost_report(
        session,
        since=since,
        until=until,
        group_by=group_by,
        department_id=department_id,
    )
    return {"data": report, "meta": _meta()}


# ── Forecasting ─────────────────────────────────────────────────────


@router.post("/forecast")
async def forecast(
    body: ForecastRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Generate a cost forecast based on historical spend."""
    result = await CostEngine.forecast(
        session,
        budget_id=body.budget_id,
        days_ahead=body.days_ahead,
    )
    return {"data": result, "meta": _meta()}


# ── Budget Check ────────────────────────────────────────────────────


@router.get("/check")
async def check_budget_legacy(
    agent_id: UUID | None = Query(default=None),
    user_id: UUID | None = Query(default=None),
    department_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Check budget status and whether execution is allowed."""
    result = await CostEngine.check_budget(
        session,
        agent_id=agent_id,
        user_id=user_id,
        department_id=department_id,
    )
    return {"data": result, "meta": _meta()}


# ── Budgets CRUD ────────────────────────────────────────────────────


@router.get("/budgets")
async def list_budgets(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    scope: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List budgets with pagination."""
    budgets, total = await CostEngine.list_budgets(
        session, scope=scope, is_active=is_active, limit=limit, offset=offset,
    )
    return {
        "data": [b.model_dump(mode="json") for b in budgets],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/budgets", status_code=201)
async def create_budget(
    body: BudgetCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new budget."""
    budget = Budget(**body.model_dump(exclude_none=False))
    if budget.period_start is None:
        budget.period_start = datetime.now(tz=timezone.utc)
    created = await CostEngine.create_budget(session, budget)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


@router.get("/budgets/{budget_id}")
async def get_budget(
    budget_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a budget by ID."""
    budget = await CostEngine.get_budget(session, budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    return {"data": budget.model_dump(mode="json"), "meta": _meta()}


@router.put("/budgets/{budget_id}")
async def update_budget(
    budget_id: UUID,
    body: BudgetUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a budget."""
    data = body.model_dump(exclude_unset=True)
    budget = await CostEngine.update_budget(session, budget_id, data)
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    return {"data": budget.model_dump(mode="json"), "meta": _meta()}


@router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a budget."""
    deleted = await CostEngine.delete_budget(session, budget_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Budget not found")


# ── Provider Pricing ────────────────────────────────────────────────


@router.get("/pricing")
async def list_pricing(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    provider: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List provider pricing entries."""
    entries, total = await CostEngine.list_pricing(
        session, provider=provider, limit=limit, offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in entries],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/pricing", status_code=201)
async def set_pricing(
    body: PricingCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create or update provider pricing."""
    pricing = ProviderPricing(**body.model_dump(exclude_none=False))
    if pricing.effective_from is None:
        pricing.effective_from = datetime.now(tz=timezone.utc)
    created = await CostEngine.set_pricing(session, pricing)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


# ── Cost Alerts ─────────────────────────────────────────────────────


@router.get("/alerts")
async def list_alerts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    budget_id: UUID | None = Query(default=None),
    is_acknowledged: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List cost alerts with pagination."""
    alerts, total = await CostEngine.list_alerts(
        session, budget_id=budget_id, is_acknowledged=is_acknowledged,
        limit=limit, offset=offset,
    )
    return {
        "data": [a.model_dump(mode="json") for a in alerts],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Acknowledge a cost alert."""
    alert = await CostEngine.acknowledge_alert(session, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"data": alert.model_dump(mode="json"), "meta": _meta()}
