"""Audit chain verification endpoints (Phase 4 / WS13).

Two endpoints:

  GET  /api/v1/audit/verify   — recompute the hash chain and return the verdict.
  GET  /api/v1/audit          — paginated list of audit rows.

Tenant scoping
--------------
* Admins (role=``admin``) may verify or list any tenant's chain.
* Non-admins are silently constrained to their own ``tenant_id`` — supplying
  another tenant's id returns a 403.

Both routes require an authenticated user — there is no anonymous read path
into the audit log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.models import AuditLog
from app.services.audit_chain import verify_audit_chain

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])


# ── Helpers ───────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build the standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _is_admin(user: AuthenticatedUser) -> bool:
    """True when the caller carries the platform-wide admin role."""
    roles = getattr(user, "roles", None) or []
    return "admin" in roles


def _enforce_tenant_scope(
    user: AuthenticatedUser, requested_tenant_id: str | None
) -> str | None:
    """Apply tenant scoping rules.

    Admins may target any tenant (or all when *requested_tenant_id* is None).
    Non-admins are restricted to their own tenant — explicitly requesting a
    different tenant raises 403.

    Returns
    -------
    str | None
        The effective tenant_id to query, or ``None`` for admin "verify all"
        requests.
    """
    if _is_admin(user):
        return requested_tenant_id

    own_tenant = user.tenant_id or ""
    if requested_tenant_id is not None and requested_tenant_id != own_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-tenant audit access is restricted to admins",
        )
    return own_tenant or None


# ── Routes ────────────────────────────────────────────────────────────


@router.get("/verify")
async def verify_chain_endpoint(
    tenant_id: str | None = Query(
        default=None,
        description=(
            "Tenant to verify; admins may omit for fleet-wide verification "
            "(every tenant chain checked independently)."
        ),
    ),
    since: datetime | None = Query(
        default=None,
        description="Inclusive lower bound on created_at.",
    ),
    until: datetime | None = Query(
        default=None,
        description="Inclusive upper bound on created_at.",
    ),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Recompute the audit hash chain and return the verdict."""
    effective_tenant = _enforce_tenant_scope(user, tenant_id)

    try:
        verdict = await verify_audit_chain(
            session,
            tenant_id=effective_tenant,
            since=since,
            until=until,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("audit_verify: verification error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chain verification failed: {exc}",
        ) from exc

    # Coerce UUIDs to strings for JSON serialisation.
    corruption_id = verdict["first_corruption_at_id"]
    return {
        "data": {
            "chain_verified": verdict["chain_verified"],
            "total_events": verdict["total_events"],
            "first_corruption_at_id": (
                str(corruption_id) if corruption_id is not None else None
            ),
            "first_corruption_field": verdict["first_corruption_field"],
            "tenant_id": effective_tenant,
        },
        "meta": _meta(),
    }


@router.get("/")
async def list_audit_rows(
    tenant_id: str | None = Query(default=None),
    action: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(
        default=None,
        description=(
            "Opaque cursor (created_at ISO timestamp + id) for keyset pagination."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a page of audit rows ordered by created_at descending.

    Uses keyset pagination over ``(created_at, id)`` so the page boundary is
    stable under concurrent inserts.
    """
    effective_tenant = _enforce_tenant_scope(user, tenant_id)

    stmt = select(AuditLog)
    if effective_tenant is not None:
        stmt = stmt.where(AuditLog.tenant_id == effective_tenant)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if since is not None:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.created_at <= until)

    # Keyset cursor: "<isoformat>|<uuid>"
    if cursor is not None:
        try:
            ts_part, id_part = cursor.split("|", 1)
            cursor_ts = datetime.fromisoformat(ts_part)
            cursor_id = UUID(id_part)
        except (ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed cursor",
            ) from exc
        # Strict less-than for "next page".
        stmt = stmt.where(
            (AuditLog.created_at < cursor_ts)
            | ((AuditLog.created_at == cursor_ts) & (AuditLog.id < cursor_id))
        )

    stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(
        limit + 1
    )

    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    has_next = len(rows) > limit
    rows = rows[:limit]

    next_cursor: str | None = None
    if has_next and rows:
        last = rows[-1]
        next_cursor = f"{last.created_at.isoformat()}|{last.id}"

    return {
        "data": [
            {
                "id": str(r.id),
                "tenant_id": r.tenant_id,
                "correlation_id": r.correlation_id,
                "actor_id": str(r.actor_id) if r.actor_id else None,
                "action": r.action,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "status_code": r.status_code,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "details": r.details,
                "hash": r.hash,
                "prev_hash": r.prev_hash,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "meta": _meta(
            pagination={"limit": limit, "next_cursor": next_cursor, "has_next": has_next}
        ),
    }


__all__ = ["router"]
