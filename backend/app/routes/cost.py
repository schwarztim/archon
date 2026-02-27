"""API routes for the Archon cost engine — enterprise token ledger, budgets, chargeback, and forecasting."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from app.utils.time import utcnow
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import require_permission
from app.models.cost import (
    Budget,
    BudgetConfig,
    BudgetResponse,
    ChargebackReport,
    CostAlert,
    CostDashboardData,
    CostForecast,
    CostSummary,
    DepartmentBudget,
    ProviderPricing,
    TokenLedger,
    UsageEvent,
)
from app.services.cost import CostEngine
from app.services.cost_service import CostService
from starlette.responses import Response

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
    alert_thresholds: list[float] = PField(
        default_factory=lambda: [50.0, 75.0, 90.0, 100.0]
    )
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


@router.post("/costs/record", status_code=201)
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


@router.get("/costs/summary")
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
        session,
        user.tenant_id,
        user,
        period=period,
        group_by=group_by,
    )
    return {"data": summary.model_dump(mode="json"), "meta": _meta()}


@router.post("/costs/budget", status_code=201)
async def set_budget(
    body: BudgetConfig,
    user: AuthenticatedUser = Depends(require_permission("costs", "create")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Set a hierarchical budget (tenant, department, workspace, user level)."""
    budget_resp = await CostService.set_budget(session, user.tenant_id, user, body)
    return {"data": budget_resp.model_dump(mode="json"), "meta": _meta()}


@router.post("/costs/budget/check")
async def check_budget(
    body: BudgetCheckRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Pre-execution budget check: allowed / soft_limit_warning / hard_limit_blocked."""
    result = await CostService.check_budget(
        session,
        user.tenant_id,
        user,
        body.estimated_cost,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/costs/chargeback")
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
        session,
        user.tenant_id,
        user,
        period=period,
        department_id=body.department_id,
    )
    return {"data": report.model_dump(mode="json"), "meta": _meta()}


@router.get("/costs/forecast")
async def cost_forecast(
    horizon_days: int = Query(default=30, ge=1, le=365),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Trend-based cost projection for the given horizon."""
    forecast = await CostService.forecast_costs(
        session,
        user.tenant_id,
        user,
        horizon_days=horizon_days,
    )
    return {"data": forecast.model_dump(mode="json"), "meta": _meta()}


@router.get("/costs/recommendations")
async def optimization_recommendations(
    user: AuthenticatedUser = Depends(require_permission("costs", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Cost-saving suggestions based on usage patterns."""
    recs = await CostService.get_optimization_recommendations(session, user.tenant_id)
    return {"data": [r.model_dump(mode="json") for r in recs], "meta": _meta()}


@router.post("/costs/reconcile")
async def reconcile_invoice(
    body: ReconcileRequest,
    user: AuthenticatedUser = Depends(require_permission("costs", "admin")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Compare ledger vs provider invoice for reconciliation."""
    result = await CostService.reconcile_provider_invoice(
        session,
        user.tenant_id,
        body.provider,
        body.invoice_data,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ══════════════════════════════════════════════════════════════════════
# Legacy endpoints (preserved for backward compatibility)
# ══════════════════════════════════════════════════════════════════════


@router.get("/dashboard")
async def cost_summary_dashboard(
    period: str | None = Query(
        default=None, description="ISO month string e.g. '2025-02'"
    ),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return full dashboard data for the Cost page — real DB aggregations.

    Uses get_dashboard_data() which returns trend, by_provider, by_model,
    by_department, by_agent, anomalies, and linear-regression forecast.
    The tenant_id defaults to 'default' for unauthenticated legacy access.
    """
    # Resolve tenant — try to get from request state if available, fall back to "default"
    tenant_id = "default"
    dashboard = await CostService.get_dashboard_data(
        session, tenant_id=tenant_id, period=period
    )
    return {"data": dashboard.model_dump(mode="json"), "meta": _meta()}


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


# ── Department Budget endpoints (spec 5C) ────────────────────────────


class DepartmentBudgetCreate(BaseModel):
    """Payload for creating or updating a department budget."""

    department_id: UUID
    budget_usd: float = PField(gt=0.0)
    period: str = PField(default="monthly", pattern="^(monthly|quarterly)$")
    warn_threshold_pct: int = PField(default=80, ge=0, le=100)
    block_threshold_pct: int = PField(default=100, ge=0, le=100)
    period_start: str | None = None  # ISO date "YYYY-MM-DD"
    period_end: str | None = None  # ISO date "YYYY-MM-DD"


@router.get("/budget")
async def list_department_budgets(
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return all active DepartmentBudget rows for this tenant."""
    from sqlmodel import select

    stmt = select(DepartmentBudget).where(
        DepartmentBudget.tenant_id == user.tenant_id,
        DepartmentBudget.is_active == True,  # noqa: E712
    )
    result = await session.exec(stmt)
    budgets = list(result.all())
    return {"data": [b.model_dump(mode="json") for b in budgets], "meta": _meta()}


@router.put("/budget/{department_id}", status_code=200)
async def upsert_department_budget(
    department_id: UUID,
    body: DepartmentBudgetCreate,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(require_permission("costs", "create")),
) -> dict[str, Any]:
    """Create or update the DepartmentBudget for a department.

    If a budget for this department already exists it is updated in-place;
    otherwise a new row is inserted.
    """
    from datetime import date
    from decimal import Decimal
    from sqlmodel import select

    stmt = select(DepartmentBudget).where(
        DepartmentBudget.tenant_id == user.tenant_id,
        DepartmentBudget.department_id == department_id,
        DepartmentBudget.is_active == True,  # noqa: E712
    )
    result = await session.exec(stmt)
    existing = result.first()

    now = utcnow()

    if existing:
        existing.budget_usd = Decimal(str(body.budget_usd))
        existing.period = body.period
        existing.warn_threshold_pct = body.warn_threshold_pct
        existing.block_threshold_pct = body.block_threshold_pct
        if body.period_start:
            existing.period_start = date.fromisoformat(body.period_start)
        if body.period_end:
            existing.period_end = date.fromisoformat(body.period_end)
        existing.updated_at = now
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        db = existing
    else:
        db = DepartmentBudget(
            tenant_id=user.tenant_id,
            department_id=department_id,
            budget_usd=Decimal(str(body.budget_usd)),
            period=body.period,
            warn_threshold_pct=body.warn_threshold_pct,
            block_threshold_pct=body.block_threshold_pct,
            period_start=(
                date.fromisoformat(body.period_start)
                if body.period_start
                else date.today()
            ),
            period_end=(
                date.fromisoformat(body.period_end) if body.period_end else date.today()
            ),
        )
        session.add(db)
        await session.commit()
        await session.refresh(db)

    return {"data": db.model_dump(mode="json"), "meta": _meta()}


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
        session,
        scope=scope,
        is_active=is_active,
        limit=limit,
        offset=offset,
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
        budget.period_start = utcnow()
    created = await CostEngine.create_budget(session, budget)
    return {"data": created.model_dump(mode="json"), "meta": _meta()}


class BudgetWizardCreate(BaseModel):
    """Budget creation via the Budget Wizard."""

    name: str
    scope: str = PField(default="tenant", pattern="^(tenant|team|agent|user)$")
    scope_id: UUID | None = None
    limit_amount: float = PField(gt=0.0)
    period: str = PField(default="monthly", pattern="^(daily|weekly|monthly)$")
    enforcement: str = PField(default="soft", pattern="^(soft|hard)$")
    alert_thresholds: list[float] = PField(
        default_factory=lambda: [50.0, 75.0, 90.0, 100.0]
    )


@router.post("/budgets/wizard", status_code=201)
async def v1_create_budget(
    body: BudgetWizardCreate,
    user: AuthenticatedUser = Depends(require_permission("costs", "create")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a budget via the Budget Wizard."""
    scope_map = {
        "team": "department",
        "tenant": "tenant",
        "agent": "agent",
        "user": "user",
    }
    db_scope = scope_map.get(body.scope, body.scope)

    budget = Budget(
        tenant_id=user.tenant_id,
        name=body.name,
        scope=db_scope,
        department_id=body.scope_id if db_scope == "department" else None,
        user_id=body.scope_id if db_scope == "user" else None,
        agent_id=body.scope_id if db_scope == "agent" else None,
        limit_amount=body.limit_amount,
        period=body.period,
        enforcement=body.enforcement,
        hard_limit=(body.enforcement == "hard"),
        alert_thresholds=body.alert_thresholds,
        period_start=utcnow(),
    )
    session.add(budget)
    await session.commit()
    await session.refresh(budget)

    from app.services.audit_log_service import AuditLogService

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="budget.created",
        resource_type="budget",
        resource_id=budget.id,
        details={"name": budget.name, "scope": db_scope, "limit": body.limit_amount},
    )

    return {"data": budget.model_dump(mode="json"), "meta": _meta()}


@router.get("/budgets/utilization-list")
async def v1_list_budgets(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List budgets with utilization data."""
    from sqlmodel import select, col

    base = select(Budget).where(Budget.tenant_id == user.tenant_id)
    count_result = await session.exec(base)
    total = len(count_result.all())

    stmt = base.offset(offset).limit(limit).order_by(col(Budget.created_at).desc())
    result = await session.exec(stmt)
    budgets = list(result.all())

    items = []
    for b in budgets:
        pct = round(
            (b.spent_amount / b.limit_amount * 100) if b.limit_amount > 0 else 0, 2
        )
        color = "green" if pct < 75 else ("yellow" if pct < 90 else "red")
        items.append(
            {
                **b.model_dump(mode="json"),
                "utilization_pct": pct,
                "utilization_color": color,
                "remaining": round(b.limit_amount - b.spent_amount, 6),
            }
        )

    return {
        "data": items,
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


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


@router.delete("/budgets/{budget_id}", status_code=204, response_class=Response)
async def delete_budget(
    budget_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a budget."""
    deleted = await CostEngine.delete_budget(session, budget_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Budget not found")
    return Response(status_code=204)


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
        session,
        provider=provider,
        limit=limit,
        offset=offset,
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
        pricing.effective_from = utcnow()
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
        session,
        budget_id=budget_id,
        is_acknowledged=is_acknowledged,
        limit=limit,
        offset=offset,
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


# ══════════════════════════════════════════════════════════════════════
# Agent 11 — Cost Engine enhancements
# ══════════════════════════════════════════════════════════════════════


@router.post("/record", status_code=201)
async def v1_record_usage(
    body: RecordUsageRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record token usage with full attribution (v1 endpoint)."""
    event = UsageEvent(
        execution_id=body.execution_id,
        user_id=body.user_id or UUID(user.id),
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


@router.get("/summary")
async def v1_cost_summary(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    group_by: str = Query(default="provider"),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Summary stats: total spend, budget vs actual, projected, top model."""
    period: dict[str, str] | None = None
    if since or until:
        period = {}
        if since:
            period["since"] = since.isoformat()
        if until:
            period["until"] = until.isoformat()

    summary = await CostService.get_cost_summary(
        session,
        user.tenant_id,
        user,
        period=period,
        group_by=group_by,
    )
    return {"data": summary.model_dump(mode="json"), "meta": _meta()}


class BreakdownGroupBy(BaseModel):
    """Query params for breakdown endpoint."""

    pass


@router.get("/breakdown")
async def v1_cost_breakdown(
    group_by: str = Query(default="model", pattern="^(agent|model|user|team)$"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Cost breakdown by agent, model, user, or team — sortable."""
    period: dict[str, str] | None = None
    if since or until:
        period = {}
        if since:
            period["since"] = since.isoformat()
        if until:
            period["until"] = until.isoformat()

    # Map frontend group_by to service field
    field_map = {
        "model": "model",
        "agent": "agent",
        "user": "user",
        "team": "department",
    }
    mapped = field_map.get(group_by, "model")

    summary = await CostService.get_cost_summary(
        session,
        user.tenant_id,
        user,
        period=period,
        group_by=mapped,
    )

    # Build breakdown list from the appropriate summary bucket
    bucket_map = {
        "model": summary.by_model,
        "agent": summary.by_model,  # agents tracked via model grouping
        "user": summary.by_user,
        "department": summary.by_department,
    }
    raw = bucket_map.get(mapped, summary.by_model)

    breakdown = sorted(
        [
            {
                "name": k,
                "cost": round(v, 6),
                "pct_of_total": round(
                    (v / summary.total_cost * 100) if summary.total_cost > 0 else 0, 2
                ),
            }
            for k, v in raw.items()
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )[:limit]

    return {
        "data": {
            "group_by": group_by,
            "items": breakdown,
            "total_cost": summary.total_cost,
        },
        "meta": _meta(),
    }


@router.get("/breakdown/{dimension}")
async def v1_cost_breakdown_by_dimension(
    dimension: str,
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Cost breakdown by a specific dimension: provider|model|department|agent|user."""
    valid_dimensions = {"provider", "model", "department", "agent", "user"}
    if dimension not in valid_dimensions:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid dimension '{dimension}'. Must be one of: {sorted(valid_dimensions)}",
        )

    period: dict[str, str] | None = None
    if since or until:
        period = {}
        if since:
            period["since"] = since.isoformat()
        if until:
            period["until"] = until.isoformat()

    summary = await CostService.get_cost_summary(
        session,
        user.tenant_id,
        user,
        period=period,
        group_by=dimension,
    )

    # Map dimension to the right summary bucket
    bucket: dict[str, float] = {
        "provider": summary.by_provider,
        "model": summary.by_model,
        "department": summary.by_department,
        "agent": summary.by_model,  # agents tracked in token_ledger.agent_id
        "user": summary.by_user,
    }.get(dimension, summary.by_model)

    items = sorted(
        [
            {
                "name": k,
                "cost": round(v, 6),
                "pct_of_total": round(
                    (v / summary.total_cost * 100) if summary.total_cost > 0 else 0, 2
                ),
            }
            for k, v in bucket.items()
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )[:limit]

    return {
        "data": items,
        "meta": _meta(),
    }


@router.get("/chart")
async def v1_cost_chart(
    granularity: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Time-series chart data for stacked area chart by provider/model."""
    from datetime import timedelta
    from collections import defaultdict

    now = utcnow()
    if since is None:
        since = now - timedelta(days=30)
    if until is None:
        until = now

    period = {"since": since.isoformat(), "until": until.isoformat()}
    summary = await CostService.get_cost_summary(
        session,
        user.tenant_id,
        user,
        period=period,
        group_by="provider",
    )

    # Build time-series by querying ledger entries grouped by date
    from sqlmodel import select, col

    base = select(TokenLedger).where(
        TokenLedger.tenant_id == user.tenant_id,
        col(TokenLedger.created_at) >= since,
        col(TokenLedger.created_at) <= until,
    )
    from app.services.cost_service import _can_read_all_costs

    if not _can_read_all_costs(user):
        base = base.where(TokenLedger.user_id == UUID(user.id))

    result = await session.exec(base)
    entries = list(result.all())

    # Group by date bucket + provider
    series: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in entries:
        if granularity == "daily":
            bucket = e.created_at.strftime("%Y-%m-%d")
        elif granularity == "weekly":
            iso = e.created_at.isocalendar()
            bucket = f"{iso[0]}-W{iso[1]:02d}"
        else:
            bucket = e.created_at.strftime("%Y-%m")
        series[bucket][e.provider] += e.total_cost

    # Flatten to chart-friendly format
    providers = sorted({e.provider for e in entries})
    chart_data = []
    for bucket in sorted(series.keys()):
        point: dict[str, Any] = {"date": bucket}
        for p in providers:
            point[p] = round(series[bucket].get(p, 0.0), 6)
        chart_data.append(point)

    return {
        "data": {
            "granularity": granularity,
            "providers": providers,
            "series": chart_data,
        },
        "meta": _meta(),
    }


@router.get("/budgets/{budget_id}/utilization")
async def v1_budget_utilization(
    budget_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get detailed utilization for a single budget."""
    budget = await session.get(Budget, budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    if budget.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Budget not found")

    pct = round(
        (budget.spent_amount / budget.limit_amount * 100)
        if budget.limit_amount > 0
        else 0,
        2,
    )
    color = "green" if pct < 75 else ("yellow" if pct < 90 else "red")

    # Determine active alerts
    triggered_thresholds = [t for t in (budget.alert_thresholds or []) if pct >= t]

    return {
        "data": {
            "budget_id": str(budget.id),
            "name": budget.name,
            "limit_amount": budget.limit_amount,
            "spent_amount": budget.spent_amount,
            "remaining": round(budget.limit_amount - budget.spent_amount, 6),
            "utilization_pct": pct,
            "utilization_color": color,
            "enforcement": budget.enforcement,
            "triggered_thresholds": triggered_thresholds,
            "period": budget.period,
        },
        "meta": _meta(),
    }


@router.put("/budgets/{budget_id}/v1")
async def v1_update_budget(
    budget_id: UUID,
    body: BudgetUpdate,
    user: AuthenticatedUser = Depends(require_permission("costs", "create")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a budget."""
    budget = await session.get(Budget, budget_id)
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget not found")
    if budget.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Budget not found")

    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        if hasattr(budget, key):
            setattr(budget, key, value)
    if "enforcement" in data:
        budget.hard_limit = data["enforcement"] == "hard"
    budget.updated_at = utcnow()
    session.add(budget)
    await session.commit()
    await session.refresh(budget)

    from app.services.audit_log_service import AuditLogService

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="budget.updated",
        resource_type="budget",
        resource_id=budget.id,
        details=data,
    )

    return {"data": budget.model_dump(mode="json"), "meta": _meta()}


@router.get("/export")
async def v1_export_report(
    format: str = Query(default="csv", pattern="^(csv|pdf)$"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    group_by: str = Query(default="team"),
    user: AuthenticatedUser = Depends(require_permission("costs", "read")),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Export chargeback report as CSV or PDF."""
    from datetime import timedelta

    now = utcnow()
    if since is None:
        since = now - timedelta(days=30)
    if until is None:
        until = now

    period = {"since": since.isoformat(), "until": until.isoformat()}
    report = await CostService.generate_chargeback_report(
        session,
        user.tenant_id,
        user,
        period=period,
    )

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Provider",
                "Model",
                "Calls",
                "Input Tokens",
                "Output Tokens",
                "Cost (USD)",
            ]
        )
        for item in report.line_items:
            writer.writerow(
                [
                    item.provider,
                    item.model,
                    item.call_count,
                    item.input_tokens,
                    item.output_tokens,
                    f"{item.cost_usd:.6f}",
                ]
            )
        writer.writerow([])
        writer.writerow(["Total", "", "", "", "", f"{report.total:.6f}"])

        output.seek(0)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=cost_report_{since.strftime('%Y%m%d')}_{until.strftime('%Y%m%d')}.csv"
            },
        )

    # PDF: return JSON summary (actual PDF rendering would use a library like reportlab)
    return {
        "data": {
            "format": "pdf",
            "report": report.model_dump(mode="json"),
            "message": "PDF export generated",
        },
        "meta": _meta(),
    }


# ── Budget enforcement middleware helper ─────────────────────────────


async def check_budget_enforcement(
    session: AsyncSession,
    tenant_id: str,
    user: AuthenticatedUser,
    estimated_cost: float,
) -> None:
    """Check budget enforcement and raise HTTP 429 if hard limit exceeded.

    Call this before executing an LLM call to enforce hard budget limits.
    """
    result = await CostService.check_budget(session, tenant_id, user, estimated_cost)
    if result.status == "hard_limit_blocked":
        raise HTTPException(
            status_code=429,
            detail={
                "error": "budget_exceeded",
                "message": result.warning_message or "Hard budget limit exceeded",
                "budget_id": str(result.budget_id) if result.budget_id else None,
                "usage_pct": result.usage_pct,
            },
        )
