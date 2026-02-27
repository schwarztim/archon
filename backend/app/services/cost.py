"""Cost engine service — token ledger, budgeting, forecasting, and cost reports."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.utils.time import utcnow as _utcnow
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, col

from app.models.cost import Budget, CostAlert, ProviderPricing, TokenLedger

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


class CostEngine:
    """Tracks token usage, calculates costs, manages budgets, and provides forecasting.

    Designed as an append-only ledger with <10ms recording overhead.
    All methods are async-safe and use static dispatch for statelessness.
    """

    # ── Token Recording ─────────────────────────────────────────────

    @staticmethod
    async def record_usage(
        session: AsyncSession,
        *,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float = 0.0,
        execution_id: UUID | None = None,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        department_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TokenLedger:
        """Record a single LLM call in the token ledger and update budget spend."""
        input_cost, output_cost = await CostEngine._calculate_token_cost(
            session,
            provider=provider,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        total_cost = input_cost + output_cost

        entry = TokenLedger(
            execution_id=execution_id,
            agent_id=agent_id,
            user_id=user_id,
            department_id=department_id,
            provider=provider,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            total_cost=total_cost,
            latency_ms=latency_ms,
            extra_metadata=metadata if metadata is not None else {},
        )
        session.add(entry)
        await session.flush()

        # Update any matching budgets and check thresholds
        await CostEngine._update_budget_spend(
            session,
            total_cost=total_cost,
            agent_id=agent_id,
            user_id=user_id,
            department_id=department_id,
        )

        await session.commit()
        await session.refresh(entry)
        return entry

    @staticmethod
    async def get_ledger_entry(
        session: AsyncSession,
        entry_id: UUID,
    ) -> TokenLedger | None:
        """Return a single ledger entry by ID."""
        return await session.get(TokenLedger, entry_id)

    @staticmethod
    async def list_ledger(
        session: AsyncSession,
        *,
        provider: str | None = None,
        model_id: str | None = None,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        department_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[TokenLedger], int]:
        """Return paginated ledger entries with optional filters and total count."""
        base = select(TokenLedger)
        if provider is not None:
            base = base.where(TokenLedger.provider == provider)
        if model_id is not None:
            base = base.where(TokenLedger.model_id == model_id)
        if agent_id is not None:
            base = base.where(TokenLedger.agent_id == agent_id)
        if user_id is not None:
            base = base.where(TokenLedger.user_id == user_id)
        if department_id is not None:
            base = base.where(TokenLedger.department_id == department_id)
        if since is not None:
            base = base.where(col(TokenLedger.created_at) >= since)
        if until is not None:
            base = base.where(col(TokenLedger.created_at) <= until)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(col(TokenLedger.created_at).desc())
        )
        result = await session.exec(stmt)
        entries = list(result.all())
        return entries, total

    # ── Cost Calculation ────────────────────────────────────────────

    @staticmethod
    async def _calculate_token_cost(
        session: AsyncSession,
        *,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[float, float]:
        """Calculate input/output cost in USD for a given token usage.

        Looks up pricing in the database first, falls back to built-in defaults.
        Returns ``(input_cost, output_cost)`` in USD.
        """
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

        # Prices are per 1M tokens
        input_cost = (input_tokens / 1_000_000) * cost_in
        output_cost = (output_tokens / 1_000_000) * cost_out
        return input_cost, output_cost

    @staticmethod
    async def calculate_cost(
        session: AsyncSession,
        *,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, float]:
        """Public cost estimation without recording. Returns cost breakdown."""
        input_cost, output_cost = await CostEngine._calculate_token_cost(
            session,
            provider=provider,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return {
            "input_cost": round(input_cost, 8),
            "output_cost": round(output_cost, 8),
            "total_cost": round(input_cost + output_cost, 8),
        }

    # ── Cost Reports ────────────────────────────────────────────────

    @staticmethod
    async def generate_cost_report(
        session: AsyncSession,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        group_by: str = "provider",  # provider | model | agent | user | department
        department_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Generate an aggregated cost report over a time range.

        Returns totals and per-group breakdowns.
        """
        if since is None:
            since = _utcnow() - timedelta(days=30)
        if until is None:
            until = _utcnow()

        base = select(TokenLedger).where(
            col(TokenLedger.created_at) >= since,
            col(TokenLedger.created_at) <= until,
        )
        if department_id is not None:
            base = base.where(TokenLedger.department_id == department_id)

        result = await session.exec(base)
        entries = list(result.all())

        # Aggregate
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        groups: dict[str, dict[str, float]] = {}

        for e in entries:
            total_input_tokens += e.input_tokens
            total_output_tokens += e.output_tokens
            total_cost += e.total_cost

            key = str(getattr(e, group_by, "unknown") or "unknown")
            group = groups.setdefault(
                key,
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_cost": 0.0,
                    "call_count": 0,
                },
            )
            group["input_tokens"] += e.input_tokens
            group["output_tokens"] += e.output_tokens
            group["total_cost"] += e.total_cost
            group["call_count"] += 1

        return {
            "period": {
                "since": since.isoformat(),
                "until": until.isoformat(),
            },
            "totals": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_cost": round(total_cost, 6),
                "call_count": len(entries),
            },
            "breakdown": groups,
            "group_by": group_by,
        }

    # ── Forecasting ─────────────────────────────────────────────────

    @staticmethod
    async def forecast(
        session: AsyncSession,
        *,
        budget_id: UUID | None = None,
        days_ahead: int = 30,
    ) -> dict[str, Any]:
        """Simple linear forecast of cost based on recent daily spend.

        Looks at the last 30 days of ledger data and projects forward.
        """
        now = _utcnow()
        lookback_start = now - timedelta(days=30)

        base = select(TokenLedger).where(
            col(TokenLedger.created_at) >= lookback_start,
        )

        # If budget_id is set, scope to budget's target
        budget: Budget | None = None
        if budget_id is not None:
            budget = await session.get(Budget, budget_id)
            if budget:
                if budget.agent_id:
                    base = base.where(TokenLedger.agent_id == budget.agent_id)
                elif budget.user_id:
                    base = base.where(TokenLedger.user_id == budget.user_id)
                elif budget.department_id:
                    base = base.where(TokenLedger.department_id == budget.department_id)

        result = await session.exec(base)
        entries = list(result.all())

        if not entries:
            return {
                "daily_avg_cost": 0.0,
                "projected_cost": 0.0,
                "days_ahead": days_ahead,
                "budget_exhaustion_date": None,
                "confidence": "low",
            }

        # Group by day
        daily: dict[str, float] = {}
        for e in entries:
            day_key = e.created_at.strftime("%Y-%m-%d")
            daily[day_key] = daily.get(day_key, 0.0) + e.total_cost

        num_days = max(len(daily), 1)
        total_historical = sum(daily.values())
        daily_avg = total_historical / num_days

        projected = daily_avg * days_ahead

        # Budget exhaustion estimate
        exhaustion_date: str | None = None
        if budget and budget.limit_amount > 0 and daily_avg > 0:
            remaining = budget.limit_amount - budget.spent_amount
            if remaining > 0:
                days_left = remaining / daily_avg
                exhaustion_dt = now + timedelta(days=days_left)
                exhaustion_date = exhaustion_dt.isoformat()

        confidence = (
            "high" if num_days >= 14 else ("medium" if num_days >= 7 else "low")
        )

        return {
            "daily_avg_cost": round(daily_avg, 6),
            "projected_cost": round(projected, 6),
            "days_ahead": days_ahead,
            "budget_exhaustion_date": exhaustion_date,
            "confidence": confidence,
        }

    # ── Budget Management ───────────────────────────────────────────

    @staticmethod
    async def create_budget(session: AsyncSession, budget: Budget) -> Budget:
        """Create a new budget."""
        session.add(budget)
        await session.commit()
        await session.refresh(budget)
        return budget

    @staticmethod
    async def get_budget(session: AsyncSession, budget_id: UUID) -> Budget | None:
        """Return a single budget by ID."""
        return await session.get(Budget, budget_id)

    @staticmethod
    async def list_budgets(
        session: AsyncSession,
        *,
        scope: str | None = None,
        is_active: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Budget], int]:
        """Return paginated budgets with optional filters."""
        base = select(Budget)
        if scope is not None:
            base = base.where(Budget.scope == scope)
        if is_active is not None:
            base = base.where(Budget.is_active == is_active)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(col(Budget.created_at).desc())
        result = await session.exec(stmt)
        budgets = list(result.all())
        return budgets, total

    @staticmethod
    async def update_budget(
        session: AsyncSession,
        budget_id: UUID,
        data: dict[str, Any],
    ) -> Budget | None:
        """Partial-update a budget. Returns None if not found."""
        budget = await session.get(Budget, budget_id)
        if budget is None:
            return None
        for key, value in data.items():
            if hasattr(budget, key):
                setattr(budget, key, value)
        budget.updated_at = _utcnow()
        session.add(budget)
        await session.commit()
        await session.refresh(budget)
        return budget

    @staticmethod
    async def delete_budget(session: AsyncSession, budget_id: UUID) -> bool:
        """Delete a budget. Returns True if deleted."""
        budget = await session.get(Budget, budget_id)
        if budget is None:
            return False
        await session.delete(budget)
        await session.commit()
        return True

    @staticmethod
    async def check_budget(
        session: AsyncSession,
        *,
        agent_id: UUID | None = None,
        user_id: UUID | None = None,
        department_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Check budget status for a given scope. Returns remaining amount and whether execution is allowed."""
        base = select(Budget).where(Budget.is_active == True)  # noqa: E712

        budgets_to_check: list[Budget] = []
        for scope_field, scope_val in [
            ("agent_id", agent_id),
            ("user_id", user_id),
            ("department_id", department_id),
        ]:
            if scope_val is not None:
                stmt = base.where(getattr(Budget, scope_field) == scope_val)
                result = await session.exec(stmt)
                budgets_to_check.extend(result.all())

        # Also check global budgets
        stmt = base.where(Budget.scope == "global")
        result = await session.exec(stmt)
        budgets_to_check.extend(result.all())

        if not budgets_to_check:
            return {"allowed": True, "budgets": [], "reason": None}

        budget_statuses: list[dict[str, Any]] = []
        blocked = False
        block_reason: str | None = None

        for b in budgets_to_check:
            remaining = b.limit_amount - b.spent_amount
            pct_used = (
                (b.spent_amount / b.limit_amount * 100) if b.limit_amount > 0 else 0.0
            )
            status = {
                "budget_id": str(b.id),
                "name": b.name,
                "scope": b.scope,
                "limit": b.limit_amount,
                "spent": b.spent_amount,
                "remaining": round(remaining, 6),
                "pct_used": round(pct_used, 2),
                "enforcement": b.enforcement,
            }
            budget_statuses.append(status)

            if b.enforcement == "hard" and remaining <= 0:
                blocked = True
                block_reason = f"Budget '{b.name}' exhausted (hard limit)"

        return {
            "allowed": not blocked,
            "budgets": budget_statuses,
            "reason": block_reason,
        }

    # ── Provider Pricing CRUD ───────────────────────────────────────

    @staticmethod
    async def set_pricing(
        session: AsyncSession,
        pricing: ProviderPricing,
    ) -> ProviderPricing:
        """Create or update provider pricing."""
        session.add(pricing)
        await session.commit()
        await session.refresh(pricing)
        return pricing

    @staticmethod
    async def list_pricing(
        session: AsyncSession,
        *,
        provider: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ProviderPricing], int]:
        """Return paginated provider pricing entries."""
        base = select(ProviderPricing).where(
            ProviderPricing.is_active == True  # noqa: E712
        )
        if provider is not None:
            base = base.where(ProviderPricing.provider == provider)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(col(ProviderPricing.provider), col(ProviderPricing.model_id))
        )
        result = await session.exec(stmt)
        entries = list(result.all())
        return entries, total

    # ── Alerts ──────────────────────────────────────────────────────

    @staticmethod
    async def list_alerts(
        session: AsyncSession,
        *,
        budget_id: UUID | None = None,
        is_acknowledged: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[CostAlert], int]:
        """Return paginated cost alerts."""
        base = select(CostAlert)
        if budget_id is not None:
            base = base.where(CostAlert.budget_id == budget_id)
        if is_acknowledged is not None:
            base = base.where(CostAlert.is_acknowledged == is_acknowledged)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset).limit(limit).order_by(col(CostAlert.created_at).desc())
        )
        result = await session.exec(stmt)
        alerts = list(result.all())
        return alerts, total

    @staticmethod
    async def acknowledge_alert(
        session: AsyncSession,
        alert_id: UUID,
        *,
        acknowledged_by: UUID | None = None,
    ) -> CostAlert | None:
        """Acknowledge a cost alert."""
        alert = await session.get(CostAlert, alert_id)
        if alert is None:
            return None
        alert.is_acknowledged = True
        alert.acknowledged_at = _utcnow()
        alert.acknowledged_by = acknowledged_by
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
        return alert

    # ── Internal helpers ────────────────────────────────────────────

    @staticmethod
    async def _update_budget_spend(
        session: AsyncSession,
        *,
        total_cost: float,
        agent_id: UUID | None,
        user_id: UUID | None,
        department_id: UUID | None,
    ) -> None:
        """Increment spent_amount on matching budgets and emit alerts on threshold breaches."""
        base = select(Budget).where(Budget.is_active == True)  # noqa: E712

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

        # Global budgets
        stmt = base.where(Budget.scope == "global")
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

            # Check threshold crossings
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
    "CostEngine",
]
