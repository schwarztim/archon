"""Worker registry REST surface (W2).

Exposes read and admin endpoints over ``worker_registrations`` so platform
operators can observe live workers and drain misbehaving ones.

Endpoints:
  GET  /api/v1/workers              — list active workers (tenant-scoped)
  GET  /api/v1/workers/{worker_id}  — get worker detail
  POST /api/v1/workers/{worker_id}/drain — set worker to draining (admin)

Auth: every endpoint requires an authenticated user. Non-admins are scoped
to their own tenant. Admins may query any tenant. Missing workers return
404 — existence is not revealed to out-of-scope callers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.models.worker_registry import WorkerRegistration
from app.services import worker_registry_service

router = APIRouter(prefix="/workers", tags=["workers"])
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    """Naive UTC timestamp."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Standard envelope meta block (mirrors task_queues router)."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _resolve_tenant_id(user: AuthenticatedUser | None) -> UUID | None:
    """Return the caller's tenant UUID, or None when missing/invalid."""
    if user is None:
        return None
    if not user.tenant_id:
        return None
    try:
        return UUID(user.tenant_id)
    except (ValueError, TypeError):
        return None


def _is_admin(user: AuthenticatedUser | None) -> bool:
    """True when the caller has the platform-wide admin role."""
    if user is None:
        return False
    roles = getattr(user, "roles", None) or []
    return "admin" in roles


def _require_tenant_id(user: AuthenticatedUser | None) -> UUID:
    """Resolve a concrete tenant_id or raise 403."""
    tenant = _resolve_tenant_id(user)
    if tenant is None:
        raise HTTPException(
            status_code=403,
            detail="tenant_id required to list workers",
        )
    return tenant


def _worker_to_dict(row: WorkerRegistration) -> dict[str, Any]:
    """Serialise a WorkerRegistration row for the REST surface."""
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "worker_name": row.worker_name,
        "worker_version": row.worker_version,
        "environment": row.environment,
        "queue_names": row.queue_names or [],
        "capabilities": row.capabilities or [],
        "max_concurrency": row.max_concurrency,
        "status": row.status,
        "deployment_id": row.deployment_id,
        "current_load": row.current_load,
        "in_flight_task_count": row.in_flight_task_count,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "last_heartbeat_at": (
            row.last_heartbeat_at.isoformat() if row.last_heartbeat_at else None
        ),
    }


async def _load_worker_for_caller(
    session: AsyncSession,
    worker_id: UUID,
    *,
    user: AuthenticatedUser,
) -> WorkerRegistration:
    """Load a WorkerRegistration or raise 404 (tenant-scoped for non-admins)."""
    row = await session.get(WorkerRegistration, worker_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    if not _is_admin(user):
        caller_tenant = _resolve_tenant_id(user)
        if caller_tenant is None or row.tenant_id != caller_tenant:
            raise HTTPException(status_code=404, detail="Worker not found")
    return row


# ── routes ───────────────────────────────────────────────────────────


@router.get("")
async def list_workers(
    request: Request,
    status: str | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List workers for the caller's tenant.

    Admins may pass ``tenant_id`` to query any tenant. Non-admins are
    always pinned to their own tenant. ``status`` filters by worker status
    (``active``, ``draining``, ``stale``).
    """
    if _is_admin(user):
        effective_tenant = tenant_id or _resolve_tenant_id(user)
    else:
        effective_tenant = _require_tenant_id(user)

    if effective_tenant is None:
        raise HTTPException(
            status_code=403,
            detail="tenant_id required to list workers",
        )

    rows = await worker_registry_service.list_workers(
        session,
        tenant_id=effective_tenant,
        status_filter=status,
    )
    # Apply limit in Python (list_workers doesn't page yet).
    rows = rows[:limit]

    return {
        "data": [_worker_to_dict(r) for r in rows],
        "meta": _meta(
            request_id=getattr(request.state, "request_id", None),
            count=len(rows),
        ),
    }


@router.get("/{worker_id}")
async def get_worker(
    worker_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Read a single worker registration (tenant-scoped)."""
    row = await _load_worker_for_caller(session, worker_id, user=user)
    return {
        "data": _worker_to_dict(row),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/{worker_id}/drain")
async def drain_worker(
    worker_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Set a worker to 'draining' status (admin only).

    A draining worker finishes its in-flight tasks but does not accept
    new claims. The transition is idempotent — draining a worker that is
    already draining is a no-op.
    """
    if not _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="admin role required to drain workers",
        )

    row = await _load_worker_for_caller(session, worker_id, user=user)

    if row.status != "draining":
        await worker_registry_service.deregister_worker(
            session, worker_id=worker_id
        )
        # Refresh the row so the response reflects the updated status.
        await session.refresh(row)

    logger.info(
        "worker.drain_requested",
        extra={
            "worker_id": str(worker_id),
            "tenant_id": str(row.tenant_id),
            "worker_name": row.worker_name,
        },
    )
    return {
        "data": _worker_to_dict(row),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


__all__ = ["router"]
