"""TaskQueue REST surface (W1).

Owned by W1 (Queue Data Model + APIs). Closes Wave 1 of the durable
orchestration plan: exposes CRUD + admin (pause/resume) endpoints over
the ``task_queues`` table so platform operators can provision queues,
adjust caps, and freeze drainage without touching the dispatcher.

Endpoints:
  POST   /api/v1/task-queues                 — create (idempotent on tenant+name)
  GET    /api/v1/task-queues                 — list (filter ``paused``)
  GET    /api/v1/task-queues/{queue_id}      — read one
  PATCH  /api/v1/task-queues/{queue_id}      — update mutable fields
  POST   /api/v1/task-queues/{queue_id}/pause   — admin: paused=True
  POST   /api/v1/task-queues/{queue_id}/resume  — admin: paused=False
  DELETE /api/v1/task-queues/{queue_id}      — soft-delete (409 if active tasks)

Auth: every endpoint requires an authenticated user. Tenant scoping is
applied — non-admins only see queues in their own tenant. Admins may
pass ``tenant_id`` to operate cross-tenant. Mismatching cross-tenant
access by non-admins gets a 404 (not 403) so we don't leak existence —
matches the ``approvals`` and ``artifacts`` router patterns.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.models.task_queue import Task, TaskQueue

router = APIRouter(prefix="/task-queues", tags=["task-queues"])
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    """Naive UTC timestamp matching the column type."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build the standard envelope meta block (mirrors approvals router)."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _resolve_tenant_id(user: AuthenticatedUser | None) -> UUID | None:
    """Return the caller's tenant UUID, or ``None`` when missing/invalid."""
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
    """Resolve a writable tenant id or raise 403.

    Writes always require a concrete tenant_id — there is no "global"
    queue in this schema. Admins MAY scope writes to any tenant they
    pass in the request body; non-admins are pinned to their own.
    """
    tenant = _resolve_tenant_id(user)
    if tenant is None:
        raise HTTPException(
            status_code=403,
            detail="tenant_id required to mutate task queues",
        )
    return tenant


def _queue_to_dict(queue: TaskQueue) -> dict[str, Any]:
    """Serialise a TaskQueue row for the REST surface."""
    return {
        "id": str(queue.id),
        "tenant_id": str(queue.tenant_id),
        "name": queue.name,
        "queue_type": queue.queue_type,
        "description": queue.description,
        "max_dispatch_rate": queue.max_dispatch_rate,
        "concurrency_limit": queue.concurrency_limit,
        "retention_days": queue.retention_days,
        "paused": queue.paused,
        "created_at": queue.created_at.isoformat() if queue.created_at else None,
        "updated_at": queue.updated_at.isoformat() if queue.updated_at else None,
    }


async def _load_queue_for_caller(
    session: AsyncSession,
    queue_id: UUID,
    *,
    user: AuthenticatedUser,
) -> TaskQueue:
    """Load a queue or raise 404 — silently scopes non-admins to their tenant."""
    queue = await session.get(TaskQueue, queue_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="Queue not found")
    if not _is_admin(user):
        caller_tenant = _resolve_tenant_id(user)
        if caller_tenant is None or queue.tenant_id != caller_tenant:
            raise HTTPException(status_code=404, detail="Queue not found")
    return queue


# ── request schemas ──────────────────────────────────────────────────


class TaskQueueCreate(BaseModel):
    """Body for ``POST /task-queues``.

    ``tenant_id`` is admin-only; non-admin requests inherit their token's
    tenant. ``retention_days`` defaults to 30 — matches the model column
    default and ADR-008.
    """

    name: str = Field(min_length=1)
    queue_type: str = Field(default="default")
    description: str | None = None
    max_dispatch_rate: int | None = Field(default=None, ge=1)
    concurrency_limit: int | None = Field(default=None, ge=1)
    retention_days: int = Field(default=30, ge=1)
    tenant_id: UUID | None = None  # admin override


class TaskQueueUpdate(BaseModel):
    """Body for ``PATCH /task-queues/{id}`` — only mutable fields."""

    description: str | None = None
    max_dispatch_rate: int | None = Field(default=None, ge=1)
    concurrency_limit: int | None = Field(default=None, ge=1)
    retention_days: int | None = Field(default=None, ge=1)
    paused: bool | None = None


# ── routes ───────────────────────────────────────────────────────────


@router.post("")
async def create_queue(
    body: TaskQueueCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new task queue (idempotent on ``(tenant_id, name)``).

    The ``uq_taskqueue_tenant_name`` constraint guarantees one queue per
    name per tenant. A duplicate POST returns ``409 Conflict`` with the
    existing queue's id so callers can recover without a probe.
    """
    # Resolve the effective tenant_id: admins may pass an override,
    # everyone else inherits their own.
    if _is_admin(user) and body.tenant_id is not None:
        effective_tenant = body.tenant_id
    else:
        effective_tenant = _require_tenant_id(user)

    # Idempotency: if a queue already exists for (tenant, name), 409.
    existing_stmt = (
        select(TaskQueue)
        .where(TaskQueue.tenant_id == effective_tenant)
        .where(TaskQueue.name == body.name)
        .limit(1)
    )
    result = await session.execute(existing_stmt)
    existing = result.scalars().first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "QUEUE_ALREADY_EXISTS",
                "message": (
                    f"queue {body.name!r} already exists for this tenant"
                ),
                "queue_id": str(existing.id),
            },
        )

    now = _utcnow()
    queue = TaskQueue(
        tenant_id=effective_tenant,
        name=body.name,
        queue_type=body.queue_type,
        description=body.description,
        max_dispatch_rate=body.max_dispatch_rate,
        concurrency_limit=body.concurrency_limit,
        retention_days=body.retention_days,
        paused=False,
        created_at=now,
        updated_at=now,
    )
    session.add(queue)
    await session.commit()
    await session.refresh(queue)

    logger.info(
        "task_queue.created",
        extra={
            "queue_id": str(queue.id),
            "tenant_id": str(queue.tenant_id),
            "queue_name": queue.name,
        },
    )
    return {
        "data": _queue_to_dict(queue),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.get("")
async def list_queues(
    request: Request,
    paused: bool | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List task queues for the caller's tenant.

    Admins may pass ``tenant_id`` to query any tenant; absent → returns
    queues across all tenants. Non-admins always have the filter forced
    to their own tenant.
    """
    if _is_admin(user):
        effective_tenant = tenant_id
    else:
        effective_tenant = _resolve_tenant_id(user)

    stmt = select(TaskQueue)
    if effective_tenant is not None:
        stmt = stmt.where(TaskQueue.tenant_id == effective_tenant)
    if paused is not None:
        stmt = stmt.where(TaskQueue.paused == paused)
    stmt = stmt.order_by(TaskQueue.created_at.asc()).limit(limit)

    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    return {
        "data": [_queue_to_dict(q) for q in rows],
        "meta": _meta(
            request_id=getattr(request.state, "request_id", None),
            count=len(rows),
        ),
    }


@router.get("/{queue_id}")
async def get_queue(
    queue_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Read a single queue (tenant-scoped)."""
    queue = await _load_queue_for_caller(session, queue_id, user=user)
    return {
        "data": _queue_to_dict(queue),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.patch("/{queue_id}")
async def update_queue(
    queue_id: UUID,
    body: TaskQueueUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Update mutable queue fields."""
    queue = await _load_queue_for_caller(session, queue_id, user=user)

    payload = body.model_dump(exclude_unset=True)
    if not payload:
        # Nothing to do — return current state for idempotency.
        return {
            "data": _queue_to_dict(queue),
            "meta": _meta(
                request_id=getattr(request.state, "request_id", None),
                note="no fields to update",
            ),
        }

    for field, value in payload.items():
        setattr(queue, field, value)
    queue.updated_at = _utcnow()
    session.add(queue)
    await session.commit()
    await session.refresh(queue)

    return {
        "data": _queue_to_dict(queue),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/{queue_id}/pause")
async def pause_queue(
    queue_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Pause queue dispatch — does NOT drop already-claimed tasks."""
    queue = await _load_queue_for_caller(session, queue_id, user=user)
    if not queue.paused:
        queue.paused = True
        queue.updated_at = _utcnow()
        session.add(queue)
        await session.commit()
        await session.refresh(queue)
        logger.info(
            "task_queue.paused",
            extra={
                "queue_id": str(queue.id),
                "tenant_id": str(queue.tenant_id),
                "queue_name": queue.name,
            },
        )
    return {
        "data": _queue_to_dict(queue),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/{queue_id}/resume")
async def resume_queue(
    queue_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Resume queue dispatch."""
    queue = await _load_queue_for_caller(session, queue_id, user=user)
    if queue.paused:
        queue.paused = False
        queue.updated_at = _utcnow()
        session.add(queue)
        await session.commit()
        await session.refresh(queue)
        logger.info(
            "task_queue.resumed",
            extra={
                "queue_id": str(queue.id),
                "tenant_id": str(queue.tenant_id),
                "queue_name": queue.name,
            },
        )
    return {
        "data": _queue_to_dict(queue),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.delete("/{queue_id}")
async def delete_queue(
    queue_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a queue.

    Hard-deletes the row when no in-flight tasks reference the queue.
    ``in-flight`` = tasks in any of (``pending``, ``visible``,
    ``claimed``) — those are the lifecycle states W1.5 manages. Tasks
    in terminal states (``completed``, ``failed``, ``cancelled``) are
    historical record only and do not block deletion.
    """
    queue = await _load_queue_for_caller(session, queue_id, user=user)

    active_stmt = (
        select(func.count(Task.id))
        .where(Task.tenant_id == queue.tenant_id)
        .where(Task.queue_name == queue.name)
        .where(Task.status.in_(("pending", "visible", "claimed")))
    )
    result = await session.execute(active_stmt)
    active_count = int(result.scalar() or 0)
    if active_count > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "QUEUE_HAS_ACTIVE_TASKS",
                "message": (
                    f"cannot delete queue {queue.name!r} — "
                    f"{active_count} active task(s) still reference it"
                ),
                "active_task_count": active_count,
            },
        )

    await session.delete(queue)
    await session.commit()

    logger.info(
        "task_queue.deleted",
        extra={
            "queue_id": str(queue_id),
            "tenant_id": str(queue.tenant_id),
            "queue_name": queue.name,
        },
    )
    return {
        "data": {"id": str(queue_id), "deleted": True},
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


__all__ = ["router"]
