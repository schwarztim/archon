"""Policy gate service — evaluate action-level authorisation policies.

W15b: Every orchestration action passes through evaluate_policy().
Policies are tenant-scoped. In enterprise mode (ARCHON_ENTERPRISE_MODE=true)
a missing policy is a DENY. In dev mode a missing policy is an ALLOW with
a warning logged.

Every deny appends a tamper-evident audit event through the existing
audit_chain hash-chain mechanism.

Actions:
    run_start, task_claim, activity_execute, signal_send,
    update_send, callback_send, schedule_create
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sentinel / config
# ---------------------------------------------------------------------------

_VALID_ACTIONS: frozenset[str] = frozenset(
    {
        "run_start",
        "task_claim",
        "activity_execute",
        "signal_send",
        "update_send",
        "callback_send",
        "schedule_create",
    }
)


def _enterprise_mode() -> bool:
    """Return True when ARCHON_ENTERPRISE_MODE is set to a truthy value."""
    val = os.getenv("ARCHON_ENTERPRISE_MODE", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class PolicyDecision:
    """Result of a single policy evaluation.

    Attributes:
        allowed: True iff the action is permitted.
        reason: Short human-readable explanation of the decision.
        audit_event_id: UUID of the persisted audit entry (for denies) or
            None when the action was allowed without an audit write.
    """

    allowed: bool
    reason: str
    audit_event_id: UUID | None = field(default=None)


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------


async def evaluate_policy(
    session: AsyncSession,
    *,
    tenant_id: UUID | str,
    action: str,
    resource: str | None = None,
    context: dict[str, Any] | None = None,
) -> PolicyDecision:
    """Evaluate whether tenant_id may perform action on resource.

    Args:
        session: Async DB session.
        tenant_id: Requesting tenant.
        action: One of the registered action names.
        resource: Optional resource type/id string (e.g. "run:abc123").
        context: Optional key/value context (user_id, ip, etc.)

    Returns:
        PolicyDecision — always returned (never raises). Callers should
        check .allowed and raise/reject as appropriate.

    In enterprise mode:
        - Unknown action → DENY (fail-closed).
        - Missing policy for a known action → DENY with audit log.
        - Explicit policy found → honour its verdict.

    In dev mode:
        - Unknown action → ALLOW with warning.
        - Missing policy → ALLOW with warning.
    """
    tenant_str = str(tenant_id)
    enterprise = _enterprise_mode()
    ctx = context or {}

    # --- Validate action --------------------------------------------------
    if action not in _VALID_ACTIONS:
        msg = f"Unknown policy action: {action!r}"
        logger.warning(
            "policy_service.unknown_action",
            extra={"tenant_id": tenant_str, "action": action, "enterprise": enterprise},
        )
        if enterprise:
            audit_id = await _record_deny_audit(
                session,
                tenant_id=tenant_str,
                action=action,
                resource=resource,
                reason=msg,
                context=ctx,
            )
            return PolicyDecision(allowed=False, reason=msg, audit_event_id=audit_id)
        return PolicyDecision(allowed=True, reason=f"dev_mode_unknown_action:{action}")

    # --- Look up tenant policy --------------------------------------------
    policy = await _lookup_policy(session, tenant_id=tenant_str, action=action)

    if policy is None:
        if enterprise:
            reason = f"enterprise_mode_missing_policy:{action}"
            logger.warning(
                "policy_service.missing_policy_denied",
                extra={"tenant_id": tenant_str, "action": action},
            )
            audit_id = await _record_deny_audit(
                session,
                tenant_id=tenant_str,
                action=action,
                resource=resource,
                reason=reason,
                context=ctx,
            )
            return PolicyDecision(allowed=False, reason=reason, audit_event_id=audit_id)
        else:
            reason = f"dev_mode_missing_policy:{action}"
            logger.warning(
                "policy_service.missing_policy_allowed_dev",
                extra={"tenant_id": tenant_str, "action": action},
            )
            return PolicyDecision(allowed=True, reason=reason)

    # --- Evaluate found policy --------------------------------------------
    allowed = bool(policy.get("allow", True))
    policy_reason = policy.get("reason", "policy_match")

    if not allowed:
        logger.warning(
            "policy_service.deny",
            extra={
                "tenant_id": tenant_str,
                "action": action,
                "resource": resource,
                "policy_reason": policy_reason,
            },
        )
        audit_id = await _record_deny_audit(
            session,
            tenant_id=tenant_str,
            action=action,
            resource=resource,
            reason=policy_reason,
            context=ctx,
        )
        return PolicyDecision(
            allowed=False, reason=policy_reason, audit_event_id=audit_id
        )

    logger.debug(
        "policy_service.allow",
        extra={"tenant_id": tenant_str, "action": action},
    )
    return PolicyDecision(allowed=True, reason=policy_reason)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _lookup_policy(
    session: AsyncSession,
    *,
    tenant_id: str,
    action: str,
) -> dict[str, Any] | None:
    """Return a policy dict for (tenant_id, action), or None if absent.

    In a full implementation this would query a `policies` table. For
    now we use a lightweight in-memory default that returns None (no
    policy configured), which triggers the enterprise/dev-mode branching
    in the caller. A real deployment would upsert rows into a policies
    table through an admin API.
    """
    # Try to import and query a TenantPolicy model if it exists.
    try:
        from app.models.tenant_policy import TenantPolicy  # type: ignore[import]
        from sqlmodel import select as _select

        stmt = _select(TenantPolicy).where(
            TenantPolicy.tenant_id == tenant_id,
            TenantPolicy.action == action,
            TenantPolicy.is_active == True,  # noqa: E712
        )
        result = await session.exec(stmt)
        row = result.first()
        if row is not None:
            return {"allow": row.allow, "reason": row.reason or "policy_match"}
    except (ImportError, AttributeError, Exception):
        # Model doesn't exist yet — fall through to None (no policy).
        pass

    return None


async def _record_deny_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    action: str,
    resource: str | None,
    reason: str,
    context: dict[str, Any],
) -> UUID:
    """Append a tamper-evident audit event for a policy denial.

    Delegates to audit_chain.append_audit_log to maintain hash integrity.
    Returns the UUID of the created audit log entry.
    """
    from app.services.audit_chain import append_audit_log

    entry = await append_audit_log(
        session,
        tenant_id=tenant_id,
        actor_id=None,
        action=f"policy.deny.{action}",
        resource_type="policy",
        resource_id=resource,
        status_code=403,
        details={"reason": reason, "context": context},
    )
    return entry.id


__all__ = [
    "PolicyDecision",
    "evaluate_policy",
]
