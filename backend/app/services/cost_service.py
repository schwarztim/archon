"""Enterprise Cost Engine — token ledger, budgets, chargeback, and forecasting.

Provides RBAC-gated, tenant-scoped cost operations with immutable ledger
entries and full attribution chains.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import check_permission
from app.models.cost import (
    Budget,
    BudgetCheckResult,
    BudgetConfig,
    BudgetResponse,
    ChargebackLineItem,
    ChargebackReport,
    CostAlert,
    CostDashboardData,
    CostForecast,
    CostSummary,
    DailyProjection,
    DepartmentBudget,
    ProviderPricing,
    Recommendation,
    ReconciliationLineItem,
    ReconciliationResult,
    TokenLedger,
    TokenLedgerEntry,
    UsageEvent,
)
from app.services.audit_log_service import AuditLogService

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


# ── Default provider pricing (per 1M tokens, USD) ───────────────────

_DEFAULT_PRICING: dict[str, dict[str, tuple[float, float]]] = {
    "openai": {
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4-turbo": (10.00, 30.00),
        "gpt-3.5-turbo": (0.50, 1.50),
        "o1": (15.00, 60.00),
        "o1-mini": (3.00, 12.00),
    },
    "anthropic": {
        "claude-3-5-sonnet": (3.00, 15.00),
        "claude-3-5-haiku": (0.80, 4.00),
        "claude-3-opus": (15.00, 75.00),
        "claude-3-sonnet": (3.00, 15.00),
        "claude-3-haiku": (0.25, 1.25),
    },
    "google": {
        "gemini-1.5-pro": (3.50, 10.50),
        "gemini-1.5-flash": (0.075, 0.30),
        "gemini-2.0-flash": (0.10, 0.40),
        "gemini-1.0-pro": (0.50, 1.50),
    },
    "azure": {
        "gpt-4o": (2.50, 10.00),
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4-turbo": (10.00, 30.00),
        "gpt-35-turbo": (0.50, 1.50),
    },
}

_FINANCE_ROLES = {"admin", "finance_admin"}
_COST_READ_ROLES = {"admin", "finance_admin", "operator"}


def _is_finance(user: AuthenticatedUser) -> bool:
    """Return True if user has finance or admin role."""
    return bool(set(user.roles) & _FINANCE_ROLES)


def _can_read_all_costs(user: AuthenticatedUser) -> bool:
    """Return True if user can read all cost data."""
    return bool(set(user.roles) & _COST_READ_ROLES) or check_permission(
        user, "costs", "read"
    )


class CostService:
    """Enterprise cost engine with RBAC, tenant isolation, and audit logging.

    All methods are static, async-safe, and require an authenticated user
    context for RBAC enforcement.
    """

    # Provider pricing per 1K tokens in USD (matches spec 5B)
    PRICING: dict[str, dict[str, float]] = {
        "gpt-4o": {"input": 0.0025, "output": 0.01},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "claude-3.5-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
        "claude-3.5-haiku": {"input": 0.0008, "output": 0.004},
        "claude-3-5-haiku": {"input": 0.0008, "output": 0.004},
        "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
    }

    # ── Token Ledger ────────────────────────────────────────────────

    @staticmethod
    async def record_usage(
        session: AsyncSession,
        tenant_id: str,
        event: UsageEvent,
    ) -> TokenLedgerEntry:
        """Record an immutable token ledger entry with full attribution chain.

        Args:
            session: Async database session.
            tenant_id: Tenant scope for the entry.
            event: The usage event to record.

        Returns:
            TokenLedgerEntry with attribution chain.
        """
        input_cost, output_cost = await CostService._calculate_token_cost(
            session,
            provider=event.provider,
            model_id=event.model,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
        )
        if event.cost_usd is not None:
            total_cost = event.cost_usd
        else:
            total_cost = input_cost + output_cost

        attribution = {
            "user_id": str(event.user_id) if event.user_id else None,
            "department_id": str(event.department_id) if event.department_id else None,
            "workspace_id": str(event.workspace_id) if event.workspace_id else None,
            "tenant_id": tenant_id,
            "provider": event.provider,
            "model": event.model,
            "agent_id": str(event.agent_id) if event.agent_id else None,
            "execution_id": str(event.execution_id) if event.execution_id else None,
        }

        entry = TokenLedger(
            tenant_id=tenant_id,
            execution_id=event.execution_id,
            agent_id=event.agent_id,
            user_id=event.user_id,
            department_id=event.department_id,
            workspace_id=event.workspace_id,
            provider=event.provider,
            model_id=event.model,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            total_tokens=event.input_tokens + event.output_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
            attribution_chain=attribution,
            extra_metadata=event.metadata,
        )
        session.add(entry)
        await session.flush()

        # Update matching budgets
        await CostService._update_budget_spend(
            session,
            tenant_id=tenant_id,
            total_cost=total_cost,
            agent_id=event.agent_id,
            user_id=event.user_id,
            department_id=event.department_id,
        )

        await session.commit()
        await session.refresh(entry)

        logger.info(
            "Usage recorded",
            extra={
                "tenant_id": tenant_id,
                "ledger_id": str(entry.id),
                "provider": event.provider,
                "model": event.model,
                "total_cost": total_cost,
            },
        )

        return TokenLedgerEntry.from_orm_entry(entry)

    # ── Cost Summary ────────────────────────────────────────────────

    @staticmethod
    async def get_cost_summary(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
        period: dict[str, str] | None = None,
        group_by: str = "provider",
    ) -> CostSummary:
        """Get aggregated cost summary with RBAC filtering.

        Finance/admin sees all costs; developers see only their own.
        """
        since = _utcnow() - timedelta(days=30)
        until = _utcnow()
        if period:
            if "since" in period:
                since = datetime.fromisoformat(period["since"])
            if "until" in period:
                until = datetime.fromisoformat(period["until"])

        base = select(TokenLedger).where(
            TokenLedger.tenant_id == tenant_id,
            col(TokenLedger.created_at) >= since,
            col(TokenLedger.created_at) <= until,
        )

        # RBAC: non-finance users can only see their own costs
        if not _can_read_all_costs(user):
            base = base.where(TokenLedger.user_id == UUID(user.id))

        result = await session.exec(base)
        entries = list(result.all())

        total_cost = 0.0
        total_input = 0
        total_output = 0
        by_provider: dict[str, float] = {}
        by_model: dict[str, float] = {}
        by_department: dict[str, float] = {}
        by_user: dict[str, float] = {}

        for e in entries:
            total_cost += e.total_cost
            total_input += e.input_tokens
            total_output += e.output_tokens
            by_provider[e.provider] = by_provider.get(e.provider, 0.0) + e.total_cost
            by_model[e.model_id] = by_model.get(e.model_id, 0.0) + e.total_cost
            dept_key = str(e.department_id) if e.department_id else "unassigned"
            by_department[dept_key] = by_department.get(dept_key, 0.0) + e.total_cost
            user_key = str(e.user_id) if e.user_id else "system"
            by_user[user_key] = by_user.get(user_key, 0.0) + e.total_cost

        return CostSummary(
            total_cost=round(total_cost, 6),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            call_count=len(entries),
            by_provider=by_provider,
            by_model=by_model,
            by_department=by_department,
            by_user=by_user,
            period={"since": since.isoformat(), "until": until.isoformat()},
        )

    # ── Budget Management ───────────────────────────────────────────

    @staticmethod
    async def set_budget(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
        budget_config: BudgetConfig,
    ) -> BudgetResponse:
        """Create or update a hierarchical budget. Requires costs:create permission."""
        check_permission(user, "costs", "create")

        budget = Budget(
            tenant_id=tenant_id,
            name=budget_config.name,
            scope=budget_config.scope.value,
            department_id=budget_config.department_id,
            workspace_id=budget_config.workspace_id,
            user_id=budget_config.user_id,
            limit_amount=budget_config.limit_usd,
            period=budget_config.period.value,
            hard_limit=budget_config.hard_limit,
            enforcement="hard" if budget_config.hard_limit else "soft",
            alert_threshold_pct=budget_config.alert_threshold_pct,
            alert_thresholds=[50.0, budget_config.alert_threshold_pct, 90.0, 100.0],
            period_start=_utcnow(),
        )
        session.add(budget)
        await session.commit()
        await session.refresh(budget)

        # Audit log
        await AuditLogService.create(
            session,
            actor_id=UUID(user.id),
            action="budget.created",
            resource_type="budget",
            resource_id=budget.id,
            details={
                "name": budget.name,
                "scope": budget.scope,
                "limit_usd": budget.limit_amount,
            },
        )

        logger.info(
            "Budget created",
            extra={
                "tenant_id": tenant_id,
                "budget_id": str(budget.id),
                "scope": budget.scope,
            },
        )

        return BudgetResponse(
            id=budget.id,
            tenant_id=tenant_id,
            config=budget_config,
            current_usage=budget.spent_amount,
            remaining=budget.limit_amount - budget.spent_amount,
            status="active",
        )

    # ── Budget Check ────────────────────────────────────────────────

    @staticmethod
    async def check_budget(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
        estimated_cost: float,
    ) -> BudgetCheckResult:
        """Pre-execution budget check: allowed / soft_limit_warning / hard_limit_blocked."""
        base = select(Budget).where(
            Budget.tenant_id == tenant_id,
            Budget.is_active == True,  # noqa: E712
        )
        result = await session.exec(base)
        budgets = list(result.all())

        if not budgets:
            return BudgetCheckResult(allowed=True, status="allowed")

        # Find the most restrictive applicable budget
        for b in budgets:
            # Check if this budget applies to the user
            if b.scope == "user" and b.user_id and str(b.user_id) != user.id:
                continue

            remaining = b.limit_amount - b.spent_amount
            projected = b.spent_amount + estimated_cost
            usage_pct = (
                (projected / b.limit_amount * 100) if b.limit_amount > 0 else 0.0
            )

            if b.hard_limit and remaining < estimated_cost:
                return BudgetCheckResult(
                    allowed=False,
                    budget_id=b.id,
                    usage_pct=round(usage_pct, 2),
                    warning_message=f"Hard budget limit reached: ${remaining:.2f} remaining, ${estimated_cost:.2f} requested",
                    status="hard_limit_blocked",
                )

            if usage_pct >= b.alert_threshold_pct:
                return BudgetCheckResult(
                    allowed=True,
                    budget_id=b.id,
                    usage_pct=round(usage_pct, 2),
                    warning_message=f"Budget warning: {usage_pct:.1f}% of ${b.limit_amount:.2f} used",
                    status="soft_limit_warning",
                )

        return BudgetCheckResult(allowed=True, status="allowed")

    # ── Chargeback Report ───────────────────────────────────────────

    @staticmethod
    async def generate_chargeback_report(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
        period: dict[str, str] | None = None,
        department_id: UUID | None = None,
    ) -> ChargebackReport:
        """Generate a departmental chargeback report with cost breakdown.

        Requires finance or admin role.
        """
        since = _utcnow() - timedelta(days=30)
        until = _utcnow()
        if period:
            if "since" in period:
                since = datetime.fromisoformat(period["since"])
            if "until" in period:
                until = datetime.fromisoformat(period["until"])

        base = select(TokenLedger).where(
            TokenLedger.tenant_id == tenant_id,
            col(TokenLedger.created_at) >= since,
            col(TokenLedger.created_at) <= until,
        )

        if department_id is not None:
            base = base.where(TokenLedger.department_id == department_id)

        result = await session.exec(base)
        entries = list(result.all())

        # Build line items grouped by provider+model
        groups: dict[str, dict[str, Any]] = {}
        total = 0.0
        for e in entries:
            key = f"{e.provider}:{e.model_id}"
            g = groups.setdefault(
                key,
                {
                    "provider": e.provider,
                    "model": e.model_id,
                    "call_count": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                },
            )
            g["call_count"] += 1
            g["input_tokens"] += e.input_tokens
            g["output_tokens"] += e.output_tokens
            g["cost_usd"] += e.total_cost
            total += e.total_cost

        line_items = [ChargebackLineItem(**g) for g in groups.values()]

        # Audit log the report generation
        await AuditLogService.create(
            session,
            actor_id=UUID(user.id),
            action="chargeback.generated",
            resource_type="chargeback_report",
            resource_id=department_id or UUID(int=0),
            details={
                "period_since": since.isoformat(),
                "period_until": until.isoformat(),
                "total": total,
            },
        )

        return ChargebackReport(
            department_id=department_id,
            period={"since": since.isoformat(), "until": until.isoformat()},
            line_items=line_items,
            total=round(total, 6),
        )

    # ── Forecasting ─────────────────────────────────────────────────

    @staticmethod
    async def forecast_costs(
        session: AsyncSession,
        tenant_id: str,
        user: AuthenticatedUser,
        horizon_days: int = 30,
    ) -> CostForecast:
        """Linear-regression cost projection from last 30 days daily spend.

        Uses ordinary least squares (OLS) on daily spend to compute slope and
        intercept for the forecast. Falls back to daily average when < 2 data
        points are available.
        """
        now = _utcnow()
        lookback = now - timedelta(days=30)

        base = select(TokenLedger).where(
            TokenLedger.tenant_id == tenant_id,
            col(TokenLedger.created_at) >= lookback,
        )

        # Non-finance users only see their own projection
        if not _can_read_all_costs(user):
            base = base.where(TokenLedger.user_id == UUID(user.id))

        result = await session.exec(base)
        entries = list(result.all())

        if not entries:
            return CostForecast(trend="stable", daily_avg=0.0, projected_total=0.0)

        # Group by day
        daily: dict[str, float] = {}
        for e in entries:
            day = e.created_at.strftime("%Y-%m-%d")
            daily[day] = daily.get(day, 0.0) + e.total_cost

        days_sorted = sorted(daily.keys())
        values = [daily[d] for d in days_sorted]
        n = len(values)
        daily_avg = sum(values) / max(n, 1)

        # Linear regression (OLS): y = slope * x + intercept
        if n >= 2:
            xs = list(range(n))
            x_mean = sum(xs) / n
            y_mean = daily_avg
            num = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
            den = sum((xs[i] - x_mean) ** 2 for i in range(n))
            slope = num / den if den != 0 else 0.0
            intercept = y_mean - slope * x_mean
        else:
            slope = 0.0
            intercept = daily_avg

        # Trend detection from slope
        if slope > daily_avg * 0.01:
            trend = "increasing"
        elif slope < -daily_avg * 0.01:
            trend = "decreasing"
        else:
            trend = "stable"

        # Build projections using linear model
        projections: list[DailyProjection] = []
        cumulative = 0.0
        for i in range(horizon_days):
            x_future = n + i
            projected_day = max(slope * x_future + intercept, 0.0)
            cumulative += projected_day
            day_date = now + timedelta(days=i + 1)
            projections.append(
                DailyProjection(
                    date=day_date.strftime("%Y-%m-%d"),
                    projected_cost=round(projected_day, 6),
                    cumulative_cost=round(cumulative, 6),
                )
            )

        # Standard deviation for confidence interval
        mean = daily_avg
        std_dev = (sum((v - mean) ** 2 for v in values) / n) ** 0.5 if n > 1 else 0.0

        return CostForecast(
            daily_projections=projections,
            confidence_interval={
                "lower": round(max(mean - std_dev, 0.0) * horizon_days, 6),
                "upper": round((mean + std_dev) * horizon_days, 6),
            },
            trend=trend,
            daily_avg=round(daily_avg, 6),
            projected_total=round(sum(p.projected_cost for p in projections), 6),
        )

        # Non-finance users only see their own projection
        if not _can_read_all_costs(user):
            base = base.where(TokenLedger.user_id == UUID(user.id))

        result = await session.exec(base)
        entries = list(result.all())

        if not entries:
            return CostForecast(trend="stable", daily_avg=0.0, projected_total=0.0)

        # Group by day
        daily: dict[str, float] = {}
        for e in entries:
            day = e.created_at.strftime("%Y-%m-%d")
            daily[day] = daily.get(day, 0.0) + e.total_cost

        days_sorted = sorted(daily.keys())
        values = [daily[d] for d in days_sorted]
        num_days = max(len(values), 1)
        daily_avg = sum(values) / num_days

        # Trend detection
        if len(values) >= 7:
            first_half = sum(values[: len(values) // 2]) / max(len(values) // 2, 1)
            second_half = sum(values[len(values) // 2 :]) / max(
                len(values) - len(values) // 2, 1
            )
            if second_half > first_half * 1.1:
                trend = "increasing"
            elif second_half < first_half * 0.9:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"

        # Daily projections
        projections: list[DailyProjection] = []
        cumulative = 0.0
        for i in range(horizon_days):
            day_date = now + timedelta(days=i + 1)
            cumulative += daily_avg
            projections.append(
                DailyProjection(
                    date=day_date.strftime("%Y-%m-%d"),
                    projected_cost=round(daily_avg, 6),
                    cumulative_cost=round(cumulative, 6),
                )
            )

        std_dev = (
            (sum((v - daily_avg) ** 2 for v in values) / num_days) ** 0.5
            if num_days > 1
            else 0.0
        )

        return CostForecast(
            daily_projections=projections,
            confidence_interval={
                "lower": round(max(daily_avg - std_dev, 0.0) * horizon_days, 6),
                "upper": round((daily_avg + std_dev) * horizon_days, 6),
            },
            trend=trend,
            daily_avg=round(daily_avg, 6),
            projected_total=round(daily_avg * horizon_days, 6),
        )

    # ── Dashboard ───────────────────────────────────────────────────

    @staticmethod
    async def get_dashboard_data(
        session: AsyncSession,
        tenant_id: str,
        period: str | None = None,
    ) -> CostDashboardData:
        """Return all aggregated data needed for the CostPage frontend.

        Includes trend, by_provider, by_model, by_department, by_agent,
        anomaly detection (spend > mean + 3*stddev), and linear-regression
        end-of-period forecast.

        Args:
            session: Async database session.
            tenant_id: Tenant scope for all queries.
            period: ISO month string like "2025-02". Defaults to current month.

        Returns:
            CostDashboardData with all dashboard sections populated.
        """
        now = _utcnow()
        if period:
            # Parse "YYYY-MM" to get period window
            try:
                year, month = int(period[:4]), int(period[5:7])
                period_start = datetime(year, month, 1, tzinfo=timezone.utc)
                # First day of next month
                if month == 12:
                    period_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                else:
                    period_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
            except (ValueError, IndexError):
                period_start = now.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                period_end = now
        else:
            period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            period_end = now
            period = now.strftime("%Y-%m")

        # Fetch all ledger entries for the period
        stmt = select(TokenLedger).where(
            TokenLedger.tenant_id == tenant_id,
            col(TokenLedger.created_at) >= period_start,
            col(TokenLedger.created_at) < period_end,
        )
        result = await session.exec(stmt)
        entries = list(result.all())

        total_spend = sum(e.total_cost for e in entries)

        # ── Trend: daily spend series ────────────────────────────
        daily_spend: dict[str, float] = {}
        for e in entries:
            day = e.created_at.strftime("%Y-%m-%d")
            daily_spend[day] = daily_spend.get(day, 0.0) + e.total_cost
        trend = [
            {"date": d, "spend": round(daily_spend[d], 6)}
            for d in sorted(daily_spend.keys())
        ]

        # ── By provider ──────────────────────────────────────────
        provider_spend: dict[str, float] = {}
        for e in entries:
            provider_spend[e.provider] = (
                provider_spend.get(e.provider, 0.0) + e.total_cost
            )
        by_provider = [
            {"provider": p, "spend": round(v, 6)}
            for p, v in sorted(provider_spend.items(), key=lambda x: x[1], reverse=True)
        ]

        # ── By model ─────────────────────────────────────────────
        model_spend: dict[str, float] = {}
        model_tokens: dict[str, int] = {}
        for e in entries:
            model_spend[e.model_id] = model_spend.get(e.model_id, 0.0) + e.total_cost
            model_tokens[e.model_id] = model_tokens.get(e.model_id, 0) + e.total_tokens
        by_model = [
            {"model": m, "spend": round(model_spend[m], 6), "tokens": model_tokens[m]}
            for m in sorted(model_spend, key=lambda x: model_spend[x], reverse=True)
        ]

        # ── By department ─────────────────────────────────────────
        dept_spend: dict[str, float] = {}
        for e in entries:
            dept_key = str(e.department_id) if e.department_id else "unassigned"
            dept_spend[dept_key] = dept_spend.get(dept_key, 0.0) + e.total_cost

        # Enrich with budget data from DepartmentBudget
        dept_budgets: dict[str, float] = {}
        if dept_spend:
            dept_stmt = select(DepartmentBudget).where(
                DepartmentBudget.tenant_id == tenant_id,
                DepartmentBudget.is_active == True,  # noqa: E712
            )
            dept_result = await session.exec(dept_stmt)
            for db in dept_result.all():
                dept_budgets[str(db.department_id)] = float(db.budget_usd)

        by_department = [
            {
                "department": dept,
                "budget": dept_budgets.get(dept, 0.0),
                "spend": round(spend, 6),
                "pct": round(
                    (spend / dept_budgets[dept] * 100)
                    if dept_budgets.get(dept)
                    else 0.0,
                    2,
                ),
            }
            for dept, spend in sorted(
                dept_spend.items(), key=lambda x: x[1], reverse=True
            )
        ]

        # ── By agent ─────────────────────────────────────────────
        agent_spend: dict[str, float] = {}
        agent_execs: dict[str, set[str]] = {}
        for e in entries:
            if e.agent_id is not None:
                ak = str(e.agent_id)
                agent_spend[ak] = agent_spend.get(ak, 0.0) + e.total_cost
                if e.execution_id is not None:
                    agent_execs.setdefault(ak, set()).add(str(e.execution_id))
        by_agent = [
            {
                "agent": ak,
                "spend": round(agent_spend[ak], 6),
                "executions": len(agent_execs.get(ak, set())),
            }
            for ak in sorted(agent_spend, key=lambda x: agent_spend[x], reverse=True)
        ]

        # ── Anomaly detection: days > mean + 3*stddev ────────────
        anomalies: list[dict[str, Any]] = []
        if daily_spend:
            day_values = list(daily_spend.values())
            mean_spend = sum(day_values) / len(day_values)
            variance = sum((v - mean_spend) ** 2 for v in day_values) / len(day_values)
            std_dev = variance**0.5
            threshold = mean_spend + 3 * std_dev
            for day, spend in daily_spend.items():
                if spend > threshold and std_dev > 0:
                    sigma = (spend - mean_spend) / std_dev
                    anomalies.append(
                        {
                            "date": day,
                            "spend": round(spend, 6),
                            "expected": round(mean_spend, 6),
                            "sigma": round(sigma, 2),
                        }
                    )

        # ── Forecast: linear regression on daily spend ───────────
        day_values_sorted = [daily_spend[d] for d in sorted(daily_spend.keys())]
        n = len(day_values_sorted)
        if n >= 2:
            xs = list(range(n))
            x_mean = (n - 1) / 2.0
            y_mean = sum(day_values_sorted) / n
            num_lr = sum(
                (xs[i] - x_mean) * (day_values_sorted[i] - y_mean) for i in range(n)
            )
            den_lr = sum((xs[i] - x_mean) ** 2 for i in range(n))
            slope = num_lr / den_lr if den_lr != 0 else 0.0
            intercept = y_mean - slope * x_mean
        elif n == 1:
            slope = 0.0
            intercept = day_values_sorted[0]
        else:
            slope = 0.0
            intercept = 0.0

        # Days remaining in the period
        days_in_period = max((period_end - period_start).days, 1)
        days_elapsed = max((now - period_start).days, 0)
        days_remaining = max(days_in_period - days_elapsed, 0)

        eom_forecast = total_spend + sum(
            max(slope * (n + i) + intercept, 0.0) for i in range(days_remaining)
        )
        confidence = 0.85 if n >= 14 else (0.70 if n >= 7 else 0.50)

        forecast: dict[str, Any] = {
            "end_of_month": round(eom_forecast, 6),
            "confidence": confidence,
        }

        return CostDashboardData(
            total_spend=round(total_spend, 6),
            period=period,
            trend=trend,
            by_provider=by_provider,
            by_model=by_model,
            by_department=by_department,
            by_agent=by_agent,
            anomalies=anomalies,
            forecast=forecast,
        )

    # ── Optimization Recommendations ────────────────────────────────

    @staticmethod
    async def get_optimization_recommendations(
        session: AsyncSession,
        tenant_id: str,
    ) -> list[Recommendation]:
        """Generate cost-saving recommendations based on usage patterns."""
        lookback = _utcnow() - timedelta(days=30)

        base = select(TokenLedger).where(
            TokenLedger.tenant_id == tenant_id,
            col(TokenLedger.created_at) >= lookback,
        )
        result = await session.exec(base)
        entries = list(result.all())

        recommendations: list[Recommendation] = []

        if not entries:
            return recommendations

        # Analyze model usage patterns
        model_costs: dict[str, float] = {}
        model_counts: dict[str, int] = {}
        for e in entries:
            model_costs[e.model_id] = model_costs.get(e.model_id, 0.0) + e.total_cost
            model_counts[e.model_id] = model_counts.get(e.model_id, 0) + 1

        total_cost = sum(model_costs.values())

        # Check for expensive model usage that could be cheaper
        expensive_models = {
            "gpt-4o",
            "gpt-4-turbo",
            "claude-3-opus",
            "claude-3-5-sonnet",
        }
        cheap_alternatives = {
            "gpt-4o-mini",
            "gpt-3.5-turbo",
            "claude-3-haiku",
            "gemini-1.5-flash",
        }

        for model, cost in model_costs.items():
            if model in expensive_models and cost > total_cost * 0.3:
                savings = cost * 0.6  # estimate 60% savings from downgrade
                recommendations.append(
                    Recommendation(
                        type="model_switch",
                        description=(
                            f"Consider using a cheaper model for some {model} workloads. "
                            f"{model_counts.get(model, 0)} calls costing ${cost:.2f}. "
                            f"Alternatives: {', '.join(cheap_alternatives)}"
                        ),
                        estimated_savings=round(savings, 2),
                        effort="medium",
                        priority=2,
                    )
                )

        # Check for high-volume, low-cost calls that might benefit from caching
        for model, count in model_counts.items():
            if count > 100:
                per_call = model_costs.get(model, 0.0) / count
                recommendations.append(
                    Recommendation(
                        type="cache_usage",
                        description=(
                            f"High call volume detected for {model} ({count} calls). "
                            f"Consider implementing response caching for repeated queries."
                        ),
                        estimated_savings=round(model_costs.get(model, 0.0) * 0.2, 2),
                        effort="low",
                        priority=1,
                    )
                )

        # Check budget utilization
        budget_stmt = select(Budget).where(
            Budget.tenant_id == tenant_id,
            Budget.is_active == True,  # noqa: E712
        )
        budget_result = await session.exec(budget_stmt)
        budgets = list(budget_result.all())

        for b in budgets:
            if b.limit_amount > 0:
                usage_pct = (b.spent_amount / b.limit_amount) * 100
                if usage_pct > 90:
                    recommendations.append(
                        Recommendation(
                            type="budget_adjustment",
                            description=(
                                f"Budget '{b.name}' is at {usage_pct:.0f}% utilization. "
                                f"Consider increasing the limit or reviewing usage."
                            ),
                            estimated_savings=0.0,
                            effort="low",
                            priority=1,
                        )
                    )
                elif usage_pct < 20 and b.spent_amount > 0:
                    recommendations.append(
                        Recommendation(
                            type="budget_adjustment",
                            description=(
                                f"Budget '{b.name}' is only at {usage_pct:.0f}% utilization. "
                                f"Consider reducing the limit to free up allocation."
                            ),
                            estimated_savings=round(b.limit_amount * 0.5, 2),
                            effort="low",
                            priority=4,
                        )
                    )

        # Sort by priority (lower number = higher priority)
        recommendations.sort(key=lambda r: r.priority)
        return recommendations

    # ── Invoice Reconciliation ──────────────────────────────────────

    @staticmethod
    async def reconcile_provider_invoice(
        session: AsyncSession,
        tenant_id: str,
        provider: str,
        invoice_data: dict[str, Any],
    ) -> ReconciliationResult:
        """Compare ledger totals vs provider invoice data.

        Args:
            session: Async database session.
            tenant_id: Tenant scope.
            provider: Provider name (openai, anthropic, etc.).
            invoice_data: Dict with 'period', 'total', and optional 'by_model' breakdown.

        Returns:
            ReconciliationResult with match status.
        """
        period = invoice_data.get("period", {})
        since_str = period.get("since", (_utcnow() - timedelta(days=30)).isoformat())
        until_str = period.get("until", _utcnow().isoformat())
        since = datetime.fromisoformat(since_str)
        until = datetime.fromisoformat(until_str)

        base = select(TokenLedger).where(
            TokenLedger.tenant_id == tenant_id,
            TokenLedger.provider == provider,
            col(TokenLedger.created_at) >= since,
            col(TokenLedger.created_at) <= until,
        )
        result = await session.exec(base)
        entries = list(result.all())

        # Aggregate ledger by model
        ledger_by_model: dict[str, float] = {}
        ledger_total = 0.0
        for e in entries:
            ledger_by_model[e.model_id] = (
                ledger_by_model.get(e.model_id, 0.0) + e.total_cost
            )
            ledger_total += e.total_cost

        invoice_total = float(invoice_data.get("total", 0.0))
        invoice_by_model: dict[str, float] = invoice_data.get("by_model", {})

        # Build line items
        all_models = set(ledger_by_model.keys()) | set(invoice_by_model.keys())
        line_items: list[ReconciliationLineItem] = []
        for model in sorted(all_models):
            l_cost = ledger_by_model.get(model, 0.0)
            i_cost = float(invoice_by_model.get(model, 0.0))
            line_items.append(
                ReconciliationLineItem(
                    model=model,
                    ledger_cost=round(l_cost, 6),
                    invoice_cost=round(i_cost, 6),
                    difference=round(l_cost - i_cost, 6),
                )
            )

        difference = ledger_total - invoice_total
        match_pct = (
            (1 - abs(difference) / max(invoice_total, 0.01)) * 100
            if invoice_total > 0
            else (100.0 if ledger_total == 0 else 0.0)
        )

        if match_pct >= 99.0:
            recon_status = "matched"
        elif match_pct >= 90.0:
            recon_status = "discrepancy"
        else:
            recon_status = "unreconciled"

        return ReconciliationResult(
            provider=provider,
            period={"since": since_str, "until": until_str},
            ledger_total=round(ledger_total, 6),
            invoice_total=round(invoice_total, 6),
            difference=round(difference, 6),
            match_pct=round(match_pct, 2),
            line_items=line_items,
            status=recon_status,
        )

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    async def _calculate_token_cost(
        session: AsyncSession,
        *,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[float, float]:
        """Calculate input/output cost in USD for given token counts."""
        stmt = (
            select(ProviderPricing)
            .where(ProviderPricing.provider == provider)
            .where(ProviderPricing.model_id == model_id)
            .where(ProviderPricing.is_active == True)  # noqa: E712
            .order_by(col(ProviderPricing.effective_from).desc())
            .limit(1)
        )
        result = await session.exec(stmt)
        pricing = result.first()

        if pricing:
            cost_in = pricing.cost_per_input_token
            cost_out = pricing.cost_per_output_token
        else:
            provider_prices = _DEFAULT_PRICING.get(provider, {})
            cost_in, cost_out = provider_prices.get(model_id, (0.0, 0.0))

        input_cost = (input_tokens / 1_000_000) * cost_in
        output_cost = (output_tokens / 1_000_000) * cost_out
        return input_cost, output_cost

    @staticmethod
    async def _update_budget_spend(
        session: AsyncSession,
        *,
        tenant_id: str,
        total_cost: float,
        agent_id: UUID | None,
        user_id: UUID | None,
        department_id: UUID | None,
    ) -> None:
        """Increment spent_amount on matching budgets and emit threshold alerts."""
        base = select(Budget).where(
            Budget.tenant_id == tenant_id,
            Budget.is_active == True,  # noqa: E712
        )

        budgets: list[Budget] = []
        for scope_field, scope_val in [
            ("agent_id", agent_id),
            ("user_id", user_id),
            ("department_id", department_id),
        ]:
            if scope_val is not None:
                stmt = base.where(getattr(Budget, scope_field) == scope_val)
                result = await session.exec(stmt)
                budgets.extend(result.all())

        # Tenant-level budgets
        stmt = base.where(Budget.scope == "tenant")
        result = await session.exec(stmt)
        budgets.extend(result.all())

        seen: set[UUID] = set()
        for b in budgets:
            if b.id in seen:
                continue
            seen.add(b.id)

            old_pct = (
                (b.spent_amount / b.limit_amount * 100) if b.limit_amount > 0 else 0.0
            )
            b.spent_amount += total_cost
            new_pct = (
                (b.spent_amount / b.limit_amount * 100) if b.limit_amount > 0 else 0.0
            )
            b.updated_at = _utcnow()
            session.add(b)

            for threshold in b.alert_thresholds or []:
                if old_pct < threshold <= new_pct:
                    severity = (
                        "critical"
                        if threshold >= 100
                        else ("warning" if threshold >= 75 else "info")
                    )
                    alert = CostAlert(
                        budget_id=b.id,
                        alert_type="threshold",
                        severity=severity,
                        threshold_pct=threshold,
                        current_spend=b.spent_amount,
                        budget_limit=b.limit_amount,
                        message=(
                            f"Budget '{b.name}' has reached {threshold}% "
                            f"(${b.spent_amount:.2f} of ${b.limit_amount:.2f})"
                        ),
                    )
                    session.add(alert)


__all__ = [
    "CostService",
]
