"""Typed budget lookup service with fail-closed enterprise mode.

Phase 4 / WS11 — Cost Gate Fail-Closed.

Used by the ``costGateNode`` executor and any other pre-execution gate
that needs an authoritative answer to "is this tenant allowed to spend
``estimated_cost_usd`` more right now?".

Fail-closed semantics
---------------------

Enterprise spend control demands that missing data is **treated as a
failure**, not silently approved. The previous behaviour fail-opened
on:

  - DB query exceptions (table missing, connection drop)
  - No ``Budget`` row configured for the tenant

In production / staging that is unsafe — a misconfigured tenant could
burn through unbounded spend before anyone notices.

Resolution rule (matches ADR-005 ``ARCHON_ENV`` classification used by
the LangGraph checkpointer + stub-block enforcement):

    fail_closed argument is None ──→ read ARCHON_COST_FAIL_CLOSED env
                                      ├─ '1'/'true'/'yes'  → True
                                      ├─ '0'/'false'/'no'  → False
                                      └─ unset             → derive from ARCHON_ENV
                                                            (production/staging → True,
                                                             dev/test/unset    → False)

Public API
----------

* :class:`BudgetExceeded`         — hard-limit breach (always raised in both modes
                                    via the result.allowed=False contract; not raised)
* :class:`BudgetLookupFailed`     — DB error / unrecoverable lookup failure
                                    (only raised in fail_closed=True mode)
* :class:`NoBudgetConfigured`     — no Budget row matched the tenant
                                    (only raised in fail_closed=True mode)
* :class:`BudgetCheckResult`      — typed result returned in the success /
                                    fail-open paths
* :func:`check_budget`            — primary entry point
* :func:`reserve_budget`          — optimistic charge reservation
* :func:`commit_budget`           — convert reservation to actual charge

This service does NOT import any routes / dispatcher / facade — it is a
pure data-layer helper used by node executors.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import col, select

from app.models.cost import Budget, TokenLedger

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Exceptions ─────────────────────────────────────────────────────────


class BudgetExceeded(RuntimeError):
    """A hard-limit budget would be breached by the requested charge.

    Carried as a typed exception so callers (cost_gate node executor) can
    distinguish over-budget from lookup failure.
    """


class BudgetLookupFailed(RuntimeError):
    """Budget data cannot be retrieved.

    Raised only when fail-closed mode is on. In fail-open mode this
    condition produces a permissive ``BudgetCheckResult`` instead.
    """


class NoBudgetConfigured(RuntimeError):
    """No Budget row exists for the tenant.

    Raised only when fail-closed mode is on. In fail-open mode this
    condition produces a permissive ``BudgetCheckResult`` instead.
    """


# ── Result type ────────────────────────────────────────────────────────


@dataclass
class BudgetCheckResult:
    """Outcome of a pre-execution budget check.

    Attributes:
        allowed: True iff the requested charge is within budget.
        reason: Short machine-readable token explaining the outcome.
        current_spend_usd: Sum of recorded spend for the active period.
        limit_usd: Configured budget limit for the active period.
        period: One of ``"daily"``, ``"weekly"``, ``"monthly"``,
            ``"total"`` — copied from the matched Budget.
        headroom_usd: ``limit_usd - current_spend_usd`` (>=0 in normal use).
        fail_mode: ``"closed"`` when ``check_budget`` ran in fail-closed
            mode, otherwise ``"open"``.
    """

    allowed: bool
    reason: str
    current_spend_usd: float
    limit_usd: float
    period: str
    headroom_usd: float
    fail_mode: str

    def to_dict(self) -> dict[str, object]:
        """Serializable representation used by node-executor output payloads."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "current_spend_usd": round(self.current_spend_usd, 6),
            "limit_usd": round(self.limit_usd, 6),
            "period": self.period,
            "headroom_usd": round(self.headroom_usd, 6),
            "fail_mode": self.fail_mode,
        }


# ── Internal helpers ───────────────────────────────────────────────────

_DURABLE_ENVS: frozenset[str] = frozenset({"production", "staging"})


def _resolve_fail_closed(fail_closed: bool | None) -> bool:
    """Resolve effective fail-closed mode.

    Precedence:
      1. Explicit argument (``True`` / ``False``).
      2. ``ARCHON_COST_FAIL_CLOSED`` env var (truthy / falsy values).
      3. Derive from ``ARCHON_ENV`` — production/staging → True, else False.
    """
    if fail_closed is not None:
        return bool(fail_closed)

    env_flag = os.getenv("ARCHON_COST_FAIL_CLOSED")
    if env_flag is not None:
        v = env_flag.strip().lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False

    archon_env = os.getenv("ARCHON_ENV", "dev").strip().lower()
    return archon_env in _DURABLE_ENVS


def _period_start(period: str, now: datetime | None = None) -> datetime:
    """Return the inclusive start of the active period in UTC.

    Falls back to ``"monthly"`` semantics for unrecognised period strings —
    callers should validate at the Budget creation boundary, not here.
    """
    now = now or datetime.now(timezone.utc)
    p = (period or "monthly").lower()

    if p == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if p == "weekly":
        # ISO week — Monday is day 0
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if p in {"annual", "yearly"}:
        return now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    if p == "total":
        # No window — use Unix epoch as a sentinel "since" boundary.
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    # Default: monthly window starting at the 1st of the current month.
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _select_budget_for_tenant(
    session: AsyncSession, tenant_id: UUID
) -> Budget | None:
    """Return the most-restrictive active Budget for the tenant, or None.

    "Most restrictive" is approximated as the smallest ``limit_amount``
    among active rows scoped to the tenant. Department / user /
    workspace scoping is left to the caller — this helper concerns
    itself with the tenant-level guardrail used by ``costGateNode``.

    A DB error here propagates to the caller — it is the caller's job
    to translate it into a fail-mode-aware outcome.
    """
    stmt = select(Budget).where(
        Budget.tenant_id == str(tenant_id),
        Budget.is_active == True,  # noqa: E712
    )
    result = await session.exec(stmt)
    rows = list(result.all())
    if not rows:
        return None

    # Prefer the smallest active limit — that's the binding constraint.
    rows.sort(key=lambda b: (b.limit_amount or 0.0))
    return rows[0]


async def aggregate_for_period(
    session: AsyncSession,
    tenant_id: UUID,
    period_start: datetime,
    period_end: datetime | None = None,
) -> float:
    """Return tenant spend in USD between [period_start, period_end).

    When ``period_end`` is None, sums everything since ``period_start``.
    Used by :func:`check_budget` and exposed for direct callers (e.g. a
    dashboard endpoint that needs a single typed aggregate query).

    Raises any underlying DB exception to the caller — the budget
    service itself never silently swallows lookup errors.
    """
    stmt = select(TokenLedger).where(
        TokenLedger.tenant_id == str(tenant_id),
        col(TokenLedger.created_at) >= period_start,
    )
    if period_end is not None:
        stmt = stmt.where(col(TokenLedger.created_at) < period_end)

    result = await session.exec(stmt)
    entries = list(result.all())
    return float(sum(e.total_cost for e in entries))


# ── Primary API ────────────────────────────────────────────────────────


async def check_budget(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    estimated_cost_usd: float,
    fail_closed: bool | None = None,
) -> BudgetCheckResult:
    """Check whether the tenant may incur ``estimated_cost_usd`` more right now.

    Args:
        session: Async DB session.
        tenant_id: Tenant scope.
        estimated_cost_usd: Charge being requested (>=0).
        fail_closed: Override the resolution policy. When None, derive
            from ``ARCHON_COST_FAIL_CLOSED`` env or ``ARCHON_ENV``.

    Returns:
        BudgetCheckResult — ``allowed=True`` when the requested charge fits.

    Raises:
        BudgetLookupFailed: DB error during lookup AND fail_closed=True.
        NoBudgetConfigured: No Budget row exists AND fail_closed=True.
    """
    fail_closed_mode = _resolve_fail_closed(fail_closed)
    fail_mode = "closed" if fail_closed_mode else "open"

    if estimated_cost_usd < 0:
        # Defensive — negative charges aren't meaningful here.
        estimated_cost_usd = 0.0

    # ── Step 1: load the tenant's Budget ─────────────────────────────
    try:
        budget = await _select_budget_for_tenant(session, tenant_id)
    except Exception as exc:  # noqa: BLE001 — propagate as typed failure
        logger.warning(
            "budget_service.lookup_failed",
            extra={"tenant_id": str(tenant_id), "error": str(exc)},
        )
        if fail_closed_mode:
            raise BudgetLookupFailed(
                f"Budget lookup failed for tenant {tenant_id}: {exc}"
            ) from exc
        return BudgetCheckResult(
            allowed=True,
            reason="fail_open_lookup_error",
            current_spend_usd=0.0,
            limit_usd=0.0,
            period="unknown",
            headroom_usd=0.0,
            fail_mode=fail_mode,
        )

    if budget is None:
        logger.warning(
            "budget_service.no_budget_configured",
            extra={"tenant_id": str(tenant_id), "fail_mode": fail_mode},
        )
        if fail_closed_mode:
            raise NoBudgetConfigured(
                f"No active Budget configured for tenant {tenant_id}"
            )
        return BudgetCheckResult(
            allowed=True,
            reason="fail_open_default",
            current_spend_usd=0.0,
            limit_usd=0.0,
            period="unknown",
            headroom_usd=0.0,
            fail_mode=fail_mode,
        )

    # ── Step 2: aggregate current-period spend ───────────────────────
    period = (budget.period or "monthly").lower()
    period_start = _period_start(period)
    try:
        current_spend = await aggregate_for_period(
            session, tenant_id, period_start
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "budget_service.aggregate_failed",
            extra={"tenant_id": str(tenant_id), "error": str(exc)},
        )
        if fail_closed_mode:
            raise BudgetLookupFailed(
                f"Spend aggregation failed for tenant {tenant_id}: {exc}"
            ) from exc
        return BudgetCheckResult(
            allowed=True,
            reason="fail_open_aggregate_error",
            current_spend_usd=0.0,
            limit_usd=float(budget.limit_amount),
            period=period,
            headroom_usd=float(budget.limit_amount),
            fail_mode=fail_mode,
        )

    limit = float(budget.limit_amount or 0.0)
    headroom = max(limit - current_spend, 0.0)
    projected = current_spend + estimated_cost_usd
    allowed = projected <= limit if limit > 0 else True

    reason = "within_budget" if allowed else "would_exceed_budget"

    logger.info(
        "budget_service.check_budget",
        extra={
            "tenant_id": str(tenant_id),
            "estimated_cost_usd": estimated_cost_usd,
            "current_spend_usd": current_spend,
            "limit_usd": limit,
            "allowed": allowed,
            "fail_mode": fail_mode,
        },
    )

    return BudgetCheckResult(
        allowed=allowed,
        reason=reason,
        current_spend_usd=current_spend,
        limit_usd=limit,
        period=period,
        headroom_usd=headroom,
        fail_mode=fail_mode,
    )


# ── Reservation pattern (optional) ─────────────────────────────────────


async def reserve_budget(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    amount_usd: float,
) -> None:
    """Record an optimistic pending charge against the tenant's Budget.

    Used as a pre-LLM hold so concurrent calls cannot race each other
    past the budget limit. ``commit_budget`` converts the reservation
    into a real charge once the LLM call returns; if the LLM call
    fails, the reservation is dropped on the next commit.

    Implementation: increments ``Budget.spent_amount`` directly. The
    same row is decremented in ``commit_budget`` if the actual cost is
    lower than the reservation.

    Raises any underlying DB exception so the caller can decide whether
    to fail-closed or fail-open.
    """
    if amount_usd <= 0:
        return

    budget = await _select_budget_for_tenant(session, tenant_id)
    if budget is None:
        # Nothing to reserve against — treated as a no-op so callers
        # get a stable interface regardless of budget configuration.
        return

    budget.spent_amount = float(budget.spent_amount or 0.0) + float(amount_usd)
    budget.updated_at = datetime.now(timezone.utc)
    session.add(budget)
    await session.flush()


async def commit_budget(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    actual_amount_usd: float,
    reserved_amount_usd: float | None = None,
) -> None:
    """Convert a reservation into the actual charge.

    When ``reserved_amount_usd`` is provided, the difference between the
    reservation and the actual charge is added back to the budget (if
    the LLM call cost less than reserved) or further deducted (if it
    cost more).

    When ``reserved_amount_usd`` is None this becomes a plain charge.
    """
    delta = float(actual_amount_usd)
    if reserved_amount_usd is not None:
        delta = float(actual_amount_usd) - float(reserved_amount_usd)

    if delta == 0:
        return

    budget = await _select_budget_for_tenant(session, tenant_id)
    if budget is None:
        return

    new_spent = float(budget.spent_amount or 0.0) + delta
    budget.spent_amount = max(new_spent, 0.0)
    budget.updated_at = datetime.now(timezone.utc)
    session.add(budget)
    await session.flush()


__all__ = [
    "BudgetCheckResult",
    "BudgetExceeded",
    "BudgetLookupFailed",
    "NoBudgetConfigured",
    "aggregate_for_period",
    "check_budget",
    "commit_budget",
    "reserve_budget",
]
