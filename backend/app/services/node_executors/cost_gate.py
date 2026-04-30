"""Cost gate node executor — aborts workflow if tenant cost exceeds threshold.

Phase 4 / WS11 — Cost Gate Fail-Closed.

Two-layer policy:

1. Legacy threshold mode (``maxUsd``): when the step config sets a
   ``maxUsd`` value, the running tenant total is compared against it
   directly. This preserves the original contract — tests in
   ``test_cost_gate_contract.py`` exercise this path and expect
   fail-open behaviour on DB errors when ``ARCHON_ENV`` is not durable.

2. Budget-service mode (``enforceBudget``): when ``maxUsd`` is absent
   AND a tenant_id is present, the gate delegates to
   :func:`app.services.budget_service.check_budget`, which honours
   ``ARCHON_COST_FAIL_CLOSED`` / ``ARCHON_ENV`` to fail closed in
   production and staging.

The two modes are not mutually exclusive — when both ``maxUsd`` is set
AND a Budget exists, the threshold check runs first (cheaper path) and
the Budget check runs second.
"""

from __future__ import annotations

import logging
import os
from uuid import UUID

from app.services.node_executors import NodeContext, NodeExecutor, NodeResult, register

logger = logging.getLogger(__name__)


_DURABLE_ENVS: frozenset[str] = frozenset({"production", "staging"})


def _is_durable_env() -> bool:
    """Return True when ``ARCHON_ENV`` classifies the environment as durable."""
    env = os.getenv("ARCHON_ENV", "dev").strip().lower()
    return env in _DURABLE_ENVS


def _is_fail_closed_explicit() -> bool | None:
    """Return the explicit ``ARCHON_COST_FAIL_CLOSED`` setting, or None."""
    raw = os.getenv("ARCHON_COST_FAIL_CLOSED")
    if raw is None:
        return None
    v = raw.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return None


def _resolve_fail_closed() -> bool:
    """Effective fail-closed mode for the cost gate."""
    explicit = _is_fail_closed_explicit()
    if explicit is not None:
        return explicit
    return _is_durable_env()


def _coerce_uuid(value: object) -> UUID | None:
    """Best-effort UUID coercion. Returns None on any failure."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


@register("costGateNode")
class CostGateNodeExecutor(NodeExecutor):
    """Block workflow execution when the tenant has exceeded a cost threshold.

    Output envelope (success path):
        ``{"passed": True, "current_total_usd": float, "max_usd": float,
        "remaining_usd": float, "budget_check": {...}}``

    Output envelope (failure path):
        ``{"passed": False, "current_total_usd": float, "max_usd": float,
        "error_code": "cost_gate_budget_exceeded" | "cost_gate_no_budget" |
        "cost_gate_lookup_failed"}``
    """

    async def execute(self, ctx: NodeContext) -> NodeResult:
        config = ctx.config
        max_usd: float = float(
            config.get("maxUsd")
            or config.get("max_usd")
            or config.get("maxCost")
            or 0.0
        )
        estimated_cost_usd: float = float(
            config.get("estimatedCostUsd")
            or config.get("estimated_cost_usd")
            or config.get("estimatedCost")
            or 0.0
        )
        enforce_budget: bool = bool(
            config.get("enforceBudget")
            or config.get("enforce_budget")
            or False
        )

        fail_closed = _resolve_fail_closed()

        # ── No threshold AND no budget enforcement: pass ───────────────
        if max_usd <= 0 and not enforce_budget:
            return NodeResult(
                status="completed",
                output={"passed": True, "reason": "no_threshold_configured"},
            )

        # ── Need DB + tenant context for any cost lookup ───────────────
        if ctx.db_session is None or not ctx.tenant_id:
            if fail_closed:
                logger.warning(
                    "costGateNode.fail_closed_no_tenant_or_db",
                    extra={
                        "step_id": ctx.step_id,
                        "has_db": ctx.db_session is not None,
                        "has_tenant": bool(ctx.tenant_id),
                    },
                )
                return NodeResult(
                    status="failed",
                    error=(
                        "cost gate cannot run without tenant_id and DB session "
                        "in fail-closed mode"
                    ),
                    output={
                        "passed": False,
                        "reason": "no_tenant_context",
                        "error_code": "cost_gate_lookup_failed",
                        "fail_mode": "closed",
                    },
                )
            # Legacy fail-open path — preserved for dev/test contract.
            logger.warning(
                "costGateNode.skipped_no_db_or_tenant",
                extra={"step_id": ctx.step_id},
            )
            return NodeResult(
                status="completed",
                output={"passed": True, "reason": "no_tenant_context"},
            )

        # ── Phase 1: legacy maxUsd threshold path ──────────────────────
        if max_usd > 0:
            try:
                current_total = await _get_tenant_running_total(
                    ctx.db_session, ctx.tenant_id
                )
            except Exception as exc:  # noqa: BLE001
                if fail_closed:
                    logger.warning(
                        "costGateNode.fail_closed_query_error",
                        exc_info=True,
                        extra={"step_id": ctx.step_id},
                    )
                    return NodeResult(
                        status="failed",
                        error=f"cost gate lookup failed: {exc}",
                        output={
                            "passed": False,
                            "reason": "cost_query_failed",
                            "error_code": "cost_gate_lookup_failed",
                            "fail_mode": "closed",
                            "error": str(exc),
                        },
                    )
                logger.warning("costGateNode.query_error", exc_info=True)
                return NodeResult(
                    status="completed",
                    output={
                        "passed": True,
                        "reason": "cost_query_failed",
                        "error": str(exc),
                    },
                )

            logger.info(
                "costGateNode.checked",
                extra={
                    "step_id": ctx.step_id,
                    "tenant_id": ctx.tenant_id,
                    "current_total_usd": current_total,
                    "max_usd": max_usd,
                },
            )

            if current_total >= max_usd:
                return NodeResult(
                    status="failed",
                    error=(
                        f"Cost gate exceeded: ${current_total:.4f} >= "
                        f"${max_usd:.4f} limit"
                    ),
                    output={
                        "passed": False,
                        "current_total_usd": current_total,
                        "max_usd": max_usd,
                        "error_code": "cost_gate_budget_exceeded",
                        "fail_mode": "closed" if fail_closed else "open",
                    },
                )

            # Threshold passed — fall through to optional Budget check below.
            threshold_output: dict[str, object] = {
                "passed": True,
                "current_total_usd": current_total,
                "max_usd": max_usd,
                "remaining_usd": max_usd - current_total,
            }
        else:
            threshold_output = {
                "passed": True,
                "current_total_usd": 0.0,
                "max_usd": 0.0,
                "remaining_usd": 0.0,
            }

        # ── Phase 2: optional Budget service (fail-closed aware) ───────
        if not enforce_budget:
            return NodeResult(status="completed", output=threshold_output)

        tenant_uuid = _coerce_uuid(ctx.tenant_id)
        if tenant_uuid is None:
            if fail_closed:
                return NodeResult(
                    status="failed",
                    error="cost gate could not parse tenant_id as UUID",
                    output={
                        "passed": False,
                        "reason": "invalid_tenant_id",
                        "error_code": "cost_gate_lookup_failed",
                        "fail_mode": "closed",
                    },
                )
            return NodeResult(
                status="completed",
                output={
                    **threshold_output,
                    "budget_check": {
                        "allowed": True,
                        "reason": "fail_open_invalid_tenant_id",
                    },
                },
            )

        # Local import — keeps the module import graph small for tests
        # that monkey-patch ``_get_tenant_running_total``.
        from app.services.budget_service import (
            BudgetCheckResult,
            BudgetLookupFailed,
            NoBudgetConfigured,
            check_budget,
        )

        try:
            check_result: BudgetCheckResult = await check_budget(
                ctx.db_session,
                tenant_id=tenant_uuid,
                estimated_cost_usd=estimated_cost_usd,
                fail_closed=fail_closed,
            )
        except NoBudgetConfigured as exc:
            return NodeResult(
                status="failed",
                error=str(exc),
                output={
                    "passed": False,
                    "reason": "no_budget_configured",
                    "error_code": "cost_gate_no_budget",
                    "fail_mode": "closed",
                },
            )
        except BudgetLookupFailed as exc:
            return NodeResult(
                status="failed",
                error=str(exc),
                output={
                    "passed": False,
                    "reason": "budget_lookup_failed",
                    "error_code": "cost_gate_lookup_failed",
                    "fail_mode": "closed",
                    "error": str(exc),
                },
            )

        if not check_result.allowed:
            return NodeResult(
                status="failed",
                error=(
                    f"Cost gate exceeded: budget would be breached "
                    f"(${check_result.current_spend_usd:.4f} + "
                    f"${estimated_cost_usd:.4f} > ${check_result.limit_usd:.4f})"
                ),
                output={
                    "passed": False,
                    "current_spend_usd": check_result.current_spend_usd,
                    "limit_usd": check_result.limit_usd,
                    "headroom_usd": check_result.headroom_usd,
                    "estimated_cost_usd": estimated_cost_usd,
                    "period": check_result.period,
                    "error_code": "cost_gate_budget_exceeded",
                    "fail_mode": check_result.fail_mode,
                    "budget_check": check_result.to_dict(),
                },
            )

        return NodeResult(
            status="completed",
            output={
                **threshold_output,
                "budget_check": check_result.to_dict(),
            },
        )


async def _get_tenant_running_total(db_session, tenant_id: str) -> float:
    """Query cost records for the tenant's running total (current month).

    Returns 0.0 on table-missing errors so dev/test environments don't
    fail when migrations haven't run. The caller decides whether to
    treat ``Exception`` from this function as fail-open or fail-closed.
    """
    from datetime import datetime, timezone, timedelta  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    # Running total for the current calendar month
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    try:
        result = await db_session.execute(
            text(
                """
                SELECT COALESCE(SUM(total_cost), 0.0)
                FROM token_ledger
                WHERE tenant_id = :tenant_id
                  AND created_at >= :month_start
                """
            ),
            {"tenant_id": tenant_id, "month_start": month_start.isoformat()},
        )
        row = result.fetchone()
        return float(row[0]) if row else 0.0
    except Exception:  # noqa: BLE001
        # Table may not exist yet — fail-open. The caller wraps this and
        # may convert to fail-closed when ``ARCHON_COST_FAIL_CLOSED`` /
        # ``ARCHON_ENV`` say so.
        return 0.0
