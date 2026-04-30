"""Schedules REST surface — W7 (Schedule Engine).

Endpoints:
  POST   /api/v1/schedules                     — create schedule
  GET    /api/v1/schedules                     — list schedules (tenant-scoped)
  GET    /api/v1/schedules/{id}                — get schedule detail
  POST   /api/v1/schedules/{id}/pause          — pause
  POST   /api/v1/schedules/{id}/resume         — resume
  POST   /api/v1/schedules/{id}/backfill       — body: {start_time, end_time}
  DELETE /api/v1/schedules/{id}                — soft-delete

Auth pattern mirrors ``task_queues`` router: authenticated user required;
non-admins are scoped to their own tenant; 404 for cross-tenant access
(don't leak existence).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.models.schedule import Schedule
from app.services import schedule_service

router = APIRouter(prefix="/schedules", tags=["schedules"])
logger = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _resolve_tenant_id(user: AuthenticatedUser | None) -> UUID | None:
    if user is None:
        return None
    if not user.tenant_id:
        return None
    try:
        return UUID(user.tenant_id)
    except (ValueError, TypeError):
        return None


def _is_admin(user: AuthenticatedUser | None) -> bool:
    if user is None:
        return False
    roles = getattr(user, "roles", None) or []
    return "admin" in roles


def _require_tenant_id(user: AuthenticatedUser | None) -> UUID:
    tenant = _resolve_tenant_id(user)
    if tenant is None:
        raise HTTPException(
            status_code=403,
            detail="tenant_id required to mutate schedules",
        )
    return tenant


def _schedule_to_dict(s: Schedule) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "tenant_id": str(s.tenant_id) if s.tenant_id else None,
        "name": s.name,
        "description": s.description,
        "workflow_id": str(s.workflow_id) if s.workflow_id else None,
        "agent_id": str(s.agent_id) if s.agent_id else None,
        "calendar_spec": s.calendar_spec,
        "spec_kind": s.spec_kind,
        "timezone": s.timezone,
        "jitter_seconds": s.jitter_seconds,
        "start_bound": s.start_bound.isoformat() if s.start_bound else None,
        "end_bound": s.end_bound.isoformat() if s.end_bound else None,
        "overlap_policy": s.overlap_policy,
        "catchup_window_seconds": s.catchup_window_seconds,
        "pause_on_failure": s.pause_on_failure,
        "input_template": s.input_template,
        "paused": s.paused,
        "last_evaluated_at": s.last_evaluated_at.isoformat() if s.last_evaluated_at else None,
        "last_fire_attempted_at": s.last_fire_attempted_at.isoformat() if s.last_fire_attempted_at else None,
        "last_fire_succeeded_at": s.last_fire_succeeded_at.isoformat() if s.last_fire_succeeded_at else None,
        "last_successful_run_id": str(s.last_successful_run_id) if s.last_successful_run_id else None,
        "next_fire_at": s.next_fire_at.isoformat() if s.next_fire_at else None,
        "consecutive_failures": s.consecutive_failures,
        "notes": s.notes,
        "created_by": s.created_by,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


async def _load_schedule_for_caller(
    session: AsyncSession,
    schedule_id: UUID,
    *,
    user: AuthenticatedUser,
) -> Schedule:
    s = await session.get(Schedule, schedule_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    if not _is_admin(user):
        caller_tenant = _resolve_tenant_id(user)
        if caller_tenant is None or s.tenant_id != caller_tenant:
            raise HTTPException(status_code=404, detail="Schedule not found")
    return s


# ── request schemas ───────────────────────────────────────────────────


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    workflow_id: UUID | None = None
    agent_id: UUID | None = None
    calendar_spec: str = Field(min_length=1)
    spec_kind: str = "cron"
    timezone: str = "UTC"
    jitter_seconds: int = Field(default=0, ge=0)
    start_bound: datetime | None = None
    end_bound: datetime | None = None
    overlap_policy: str = "skip"
    catchup_window_seconds: int = Field(default=0, ge=0)
    pause_on_failure: bool = False
    input_template: dict | None = None
    notes: str = ""
    created_by: str = ""
    tenant_id: UUID | None = None  # admin override


class BackfillRequest(BaseModel):
    start_time: datetime
    end_time: datetime


# ── routes ────────────────────────────────────────────────────────────


@router.post("")
async def create_schedule(
    body: ScheduleCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a new schedule."""
    if _is_admin(user) and body.tenant_id is not None:
        effective_tenant = body.tenant_id
    else:
        effective_tenant = _require_tenant_id(user)

    try:
        schedule = await schedule_service.create_schedule(
            session,
            tenant_id=effective_tenant,
            name=body.name,
            description=body.description,
            workflow_id=body.workflow_id,
            agent_id=body.agent_id,
            calendar_spec=body.calendar_spec,
            spec_kind=body.spec_kind,
            timezone=body.timezone,
            jitter_seconds=body.jitter_seconds,
            start_bound=body.start_bound,
            end_bound=body.end_bound,
            overlap_policy=body.overlap_policy,
            catchup_window_seconds=body.catchup_window_seconds,
            pause_on_failure=body.pause_on_failure,
            input_template=body.input_template,
            notes=body.notes,
            created_by=body.created_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "data": _schedule_to_dict(schedule),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.get("")
async def list_schedules(
    request: Request,
    tenant_id: UUID | None = None,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List schedules for the caller's tenant."""
    if _is_admin(user):
        effective_tenant = tenant_id
    else:
        effective_tenant = _resolve_tenant_id(user)

    schedules = await schedule_service.list_schedules(
        session, tenant_id=effective_tenant
    )
    return {
        "data": [_schedule_to_dict(s) for s in schedules],
        "meta": _meta(
            request_id=getattr(request.state, "request_id", None),
            count=len(schedules),
        ),
    }


@router.get("/{schedule_id}")
async def get_schedule(
    schedule_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a single schedule."""
    s = await _load_schedule_for_caller(session, schedule_id, user=user)
    return {
        "data": _schedule_to_dict(s),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/{schedule_id}/pause")
async def pause_schedule(
    schedule_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Pause a schedule — stops evaluation until resumed."""
    await _load_schedule_for_caller(session, schedule_id, user=user)
    s = await schedule_service.pause_schedule(session, schedule_id=schedule_id)
    return {
        "data": _schedule_to_dict(s),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/{schedule_id}/resume")
async def resume_schedule(
    schedule_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Resume a paused schedule (runs catchup if configured)."""
    await _load_schedule_for_caller(session, schedule_id, user=user)
    s = await schedule_service.resume_schedule(session, schedule_id=schedule_id)
    return {
        "data": _schedule_to_dict(s),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/{schedule_id}/backfill")
async def backfill_schedule(
    schedule_id: UUID,
    body: BackfillRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create runs for all missed fires in [start_time, end_time]."""
    await _load_schedule_for_caller(session, schedule_id, user=user)

    try:
        run_ids = await schedule_service.backfill_schedule(
            session,
            schedule_id=schedule_id,
            start_time=body.start_time,
            end_time=body.end_time,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "data": {"run_ids": [str(r) for r in run_ids], "count": len(run_ids)},
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.delete("/{schedule_id}")
async def delete_schedule(
    schedule_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a schedule (hard-delete; runs are not affected)."""
    await _load_schedule_for_caller(session, schedule_id, user=user)
    deleted = await schedule_service.delete_schedule(
        session, schedule_id=schedule_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {
        "data": {"id": str(schedule_id), "deleted": True},
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


__all__ = ["router"]
