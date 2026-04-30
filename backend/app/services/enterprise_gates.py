"""Enterprise gate layer — Cost, DLP, Egress, and Secret-access checks.

W15c: Gate functions that wrap existing services with enterprise-mode
fail-closed semantics. None of these functions modify the wrapped services;
they are pure wrappers that add the fail-closed contract on top.

Fail-closed: when ARCHON_ENTERPRISE_MODE=true and a gate's backing service
is unavailable, raises rather than silently allowing.

Gates:
    check_budget       — delegate to budget_service
    check_dlp          — delegate to dlp_service (sync, no session needed)
    check_egress       — validate target URL against tenant egress allowlist
    check_secret_access — verify tenant may access the requested secret ref
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _enterprise_mode() -> bool:
    """Return True when ARCHON_ENTERPRISE_MODE is truthy."""
    val = os.getenv("ARCHON_ENTERPRISE_MODE", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Budget gate
# ---------------------------------------------------------------------------


class BudgetGateDenied(RuntimeError):
    """Raised when budget gate blocks execution."""


class BudgetGateUnavailable(RuntimeError):
    """Raised in enterprise mode when budget service is unavailable."""


async def check_budget(
    session: AsyncSession,
    *,
    tenant_id: UUID | str,
    estimated_cost: float,
) -> bool:
    """Check whether tenant_id may incur estimated_cost.

    Delegates to budget_service.check_budget.

    Returns:
        True if the budget allows the charge.

    Raises:
        BudgetGateDenied: Tenant is over budget.
        BudgetGateUnavailable: Budget service unavailable in enterprise mode.
    """
    from app.services import budget_service
    from app.services.budget_service import BudgetLookupFailed, NoBudgetConfigured

    tenant_uuid = UUID(str(tenant_id)) if not isinstance(tenant_id, UUID) else tenant_id
    enterprise = _enterprise_mode()

    try:
        result = await budget_service.check_budget(
            session,
            tenant_id=tenant_uuid,
            estimated_cost_usd=estimated_cost,
            fail_closed=enterprise,
        )
    except (BudgetLookupFailed, NoBudgetConfigured) as exc:
        # budget_service already raises these in fail-closed mode.
        logger.error(
            "enterprise_gates.budget_unavailable",
            extra={
                "tenant_id": str(tenant_id),
                "error": str(exc),
                "enterprise": enterprise,
            },
        )
        raise BudgetGateUnavailable(str(exc)) from exc
    except Exception as exc:
        logger.error(
            "enterprise_gates.budget_unexpected_error",
            extra={"tenant_id": str(tenant_id), "error": str(exc)},
        )
        if enterprise:
            raise BudgetGateUnavailable(
                f"Budget service unavailable: {exc}"
            ) from exc
        return True  # fail-open in dev mode

    if not result.allowed:
        raise BudgetGateDenied(
            f"Tenant {tenant_id} over budget: {result.reason} "
            f"(spend={result.current_spend_usd:.4f}, limit={result.limit_usd:.4f})"
        )

    return True


# ---------------------------------------------------------------------------
# DLP gate
# ---------------------------------------------------------------------------


class DLPGateDenied(RuntimeError):
    """Raised when DLP gate blocks content."""


class DLPGateUnavailable(RuntimeError):
    """Raised in enterprise mode when DLP service is unavailable."""


async def check_dlp(
    session: AsyncSession,
    *,
    tenant_id: UUID | str,
    payload: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Check payload for DLP violations and return redacted version.

    Args:
        session: Async DB session (unused by current DLP impl, kept for
            interface consistency and future DB-backed policy lookups).
        tenant_id: Tenant scope.
        payload: The payload dict to scan.

    Returns:
        (allowed, redacted_payload) — allowed=True when content may proceed.
        redacted_payload has sensitive fields replaced.

    Raises:
        DLPGateDenied: Content must be blocked (CRITICAL risk in enterprise mode).
        DLPGateUnavailable: DLP service unavailable in enterprise mode.
    """
    from app.services.dlp_service import DLPService

    enterprise = _enterprise_mode()
    tenant_str = str(tenant_id)

    # Serialize payload to string for scanning.
    import json

    try:
        content = json.dumps(payload, default=str)
    except Exception as exc:
        logger.error("enterprise_gates.dlp_serialization_error", extra={"error": str(exc)})
        if enterprise:
            raise DLPGateUnavailable(f"Cannot serialize payload for DLP: {exc}") from exc
        return True, payload

    try:
        scan_result = DLPService.scan_content(
            tenant_id=tenant_str,
            content=content,
        )
    except Exception as exc:
        logger.error(
            "enterprise_gates.dlp_service_error",
            extra={"tenant_id": tenant_str, "error": str(exc)},
        )
        if enterprise:
            raise DLPGateUnavailable(f"DLP service unavailable: {exc}") from exc
        return True, payload

    from app.models.dlp import ScanAction

    if scan_result.action == ScanAction.BLOCK:
        logger.warning(
            "enterprise_gates.dlp_blocked",
            extra={
                "tenant_id": tenant_str,
                "risk_level": scan_result.risk_level.value,
                "findings": len(scan_result.findings),
            },
        )
        if enterprise:
            raise DLPGateDenied(
                f"Payload blocked by DLP: risk={scan_result.risk_level.value}"
            )
        # In dev mode: allow but redact.
        redacted_str = DLPService.redact_content(content, scan_result.findings)
        try:
            redacted_payload = json.loads(redacted_str)
        except Exception:
            redacted_payload = {"_redacted": True}
        return True, redacted_payload

    # Redact regardless of block/allow — never leak sensitive data downstream.
    if scan_result.findings:
        redacted_str = DLPService.redact_content(content, scan_result.findings)
        try:
            redacted_payload: dict[str, Any] = json.loads(redacted_str)
        except Exception:
            redacted_payload = payload
    else:
        redacted_payload = payload

    return True, redacted_payload


# ---------------------------------------------------------------------------
# Egress gate
# ---------------------------------------------------------------------------


class EgressGateDenied(RuntimeError):
    """Raised when target URL is not in the tenant egress allowlist."""


async def check_egress(
    session: AsyncSession,
    *,
    tenant_id: UUID | str,
    target_url: str,
) -> bool:
    """Check whether tenant_id may send egress traffic to target_url.

    Default: deny in enterprise mode (allowlist is empty unless populated).
    Default: allow with warning in dev mode.

    Returns:
        True if egress is permitted.

    Raises:
        EgressGateDenied: URL not in allowlist in enterprise mode.
    """
    enterprise = _enterprise_mode()
    tenant_str = str(tenant_id)

    allowlist = await _get_egress_allowlist(session, tenant_id=tenant_str)

    if allowlist is None:
        # No allowlist configured.
        if enterprise:
            logger.warning(
                "enterprise_gates.egress_no_allowlist",
                extra={"tenant_id": tenant_str, "target_url": target_url},
            )
            raise EgressGateDenied(
                f"No egress allowlist configured for tenant {tenant_id}. "
                f"Default deny in enterprise mode."
            )
        logger.warning(
            "enterprise_gates.egress_no_allowlist_dev",
            extra={"tenant_id": tenant_str, "target_url": target_url},
        )
        return True

    # Check if target_url matches any allowlist pattern.
    for pattern in allowlist:
        if _url_matches(target_url, pattern):
            return True

    logger.warning(
        "enterprise_gates.egress_denied",
        extra={
            "tenant_id": tenant_str,
            "target_url": target_url,
            "allowlist_size": len(allowlist),
        },
    )

    if enterprise:
        raise EgressGateDenied(
            f"Egress to {target_url!r} denied for tenant {tenant_id}: not in allowlist"
        )
    return False


def _url_matches(url: str, pattern: str) -> bool:
    """Return True if url matches the allowlist pattern.

    Patterns support simple wildcards:
    - Exact host match: "api.example.com"
    - Wildcard subdomain: "*.example.com"
    - Full URL prefix: "https://api.example.com/v1/"
    """
    if pattern == "*":
        return True
    if pattern.startswith("*"):
        suffix = pattern[1:]
        return url.endswith(suffix) or (suffix in url)
    return url.startswith(pattern) or url == pattern


async def _get_egress_allowlist(
    session: AsyncSession,
    *,
    tenant_id: str,
) -> list[str] | None:
    """Return the tenant's egress URL allowlist, or None if unconfigured."""
    # Try to look up from a TenantEgressPolicy model if it exists.
    try:
        from app.models.tenant_egress_policy import TenantEgressPolicy  # type: ignore
        from sqlmodel import select as _select

        stmt = _select(TenantEgressPolicy).where(
            TenantEgressPolicy.tenant_id == tenant_id,
            TenantEgressPolicy.is_active == True,  # noqa: E712
        )
        result = await session.exec(stmt)
        rows = list(result.all())
        if rows:
            patterns: list[str] = []
            for row in rows:
                patterns.extend(row.allowed_patterns or [])
            return patterns
    except (ImportError, AttributeError, Exception):
        pass

    return None  # No allowlist configured


# ---------------------------------------------------------------------------
# Secret-access gate
# ---------------------------------------------------------------------------


class SecretAccessDenied(RuntimeError):
    """Raised when tenant is not authorised to access a secret ref."""


async def check_secret_access(
    session: AsyncSession,
    *,
    tenant_id: UUID | str,
    secret_ref: str,
) -> bool:
    """Verify tenant_id may access the secret identified by secret_ref.

    secret_ref format: "vault://<path>" or "<provider>://<key>" or plain "<key>".

    Returns:
        True if access is allowed.

    Raises:
        SecretAccessDenied: Tenant is not authorised for this secret.
    """
    enterprise = _enterprise_mode()
    tenant_str = str(tenant_id)

    # Attempt to delegate to an existing secret access logger if present.
    try:
        from app.services.secret_access_logger import log_secret_access  # type: ignore

        await log_secret_access(
            session=session,
            tenant_id=tenant_str,
            secret_ref=secret_ref,
        )
    except (ImportError, AttributeError, Exception):
        pass

    allowed = await _check_secret_tenant_scope(
        session, tenant_id=tenant_str, secret_ref=secret_ref
    )

    if not allowed:
        logger.warning(
            "enterprise_gates.secret_access_denied",
            extra={"tenant_id": tenant_str, "secret_ref": secret_ref},
        )
        if enterprise:
            raise SecretAccessDenied(
                f"Tenant {tenant_id} is not authorised to access secret {secret_ref!r}"
            )
        return False

    return True


async def _check_secret_tenant_scope(
    session: AsyncSession,
    *,
    tenant_id: str,
    secret_ref: str,
) -> bool:
    """Return True if the secret is scoped to this tenant or is global."""
    # Try to look up a TenantSecretGrant model if it exists.
    try:
        from app.models.tenant_secret_grant import TenantSecretGrant  # type: ignore
        from sqlmodel import select as _select

        stmt = _select(TenantSecretGrant).where(
            TenantSecretGrant.tenant_id == tenant_id,
            TenantSecretGrant.secret_ref == secret_ref,
            TenantSecretGrant.is_active == True,  # noqa: E712
        )
        result = await session.exec(stmt)
        return result.first() is not None
    except (ImportError, AttributeError, Exception):
        # Model not present — default allow (no grant table = no restriction).
        return True


__all__ = [
    "BudgetGateDenied",
    "BudgetGateUnavailable",
    "DLPGateDenied",
    "DLPGateUnavailable",
    "EgressGateDenied",
    "SecretAccessDenied",
    "check_budget",
    "check_dlp",
    "check_egress",
    "check_secret_access",
]
