"""Run lifecycle control endpoints (W6) and visibility search endpoints (W13).

Provides operator controls for cancelling, terminating, pausing, and
resuming workflow runs with full audit trails.

Endpoints
---------

POST /api/v1/runs/{run_id}/cancel    — cooperative cancellation
POST /api/v1/runs/{run_id}/terminate — hard stop (admin only)
POST /api/v1/runs/{run_id}/pause     — suspend polling
POST /api/v1/runs/{run_id}/resume    — resume from paused
GET  /api/v1/runs/{run_id}           — run detail with events
GET  /api/v1/runs                    — list runs with filters
GET  /api/v1/runs/search             — search via VisibilityIndex (W13)
GET  /api/v1/runs/{run_id}/timeline  — paginated event stream (W13)
GET  /api/v1/runs/{run_id}/graph     — step dependency graph (W13)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.auth import get_current_user
from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.workflow import WorkflowRun, WorkflowRunEvent
from app.services.run_lifecycle import (
    cancel_run,
    pause_run,
    resume_run,
    terminate_run,
)
from app.services.visibility_service import (
    get_run_graph,
    get_run_timeline,
    search_runs,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])

_DEFAULT_TENANT = UUID("00000000-0000-0000-0000-000000000000")


# ── Request / response schemas ────────────────────────────────────────


class LifecycleRequest(BaseModel):
    """Common payload for lifecycle control actions."""

    reason: str


def _resolve_tenant_id(user: AuthenticatedUser | None) -> UUID:
    if user is not None and getattr(user, "tenant_id", None):
        return UUID(user.tenant_id)
    return _DEFAULT_TENANT


def _resolve_actor_id(user: AuthenticatedUser | None) -> str:
    if user is None:
        return "anonymous"
    return getattr(user, "id", None) or getattr(user, "email", None) or "unknown"


def _run_to_dict(run: WorkflowRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "workflow_id": str(run.workflow_id) if run.workflow_id else None,
        "agent_id": str(run.agent_id) if run.agent_id else None,
        "kind": run.kind,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "triggered_by": run.triggered_by,
        "tenant_id": str(run.tenant_id) if run.tenant_id else None,
        "queued_at": run.queued_at.isoformat() if run.queued_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "paused_at": run.paused_at.isoformat() if run.paused_at else None,
        "resumed_at": run.resumed_at.isoformat() if run.resumed_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "cancel_requested_at": (
            run.cancel_requested_at.isoformat()
            if run.cancel_requested_at
            else None
        ),
        "duration_ms": run.duration_ms,
        "error": run.error,
        "error_code": run.error_code,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _event_to_dict(event: WorkflowRunEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": event.payload,
        "step_id": event.step_id,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


# ── Lifecycle control endpoints ───────────────────────────────────────


@router.post("/{run_id}/cancel")
async def cancel_run_endpoint(
    run_id: UUID,
    body: LifecycleRequest,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Request cooperative cancellation of a run.

    Sets status to ``cancelling`` and stamps ``cancel_requested_at``.
    The dispatcher honours this flag cooperatively before/after each
    activity step, then moves the run to ``cancelled``.
    """
    actor_id = _resolve_actor_id(user)
    try:
        run = await cancel_run(
            session,
            run_id=run_id,
            reason=body.reason,
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run": _run_to_dict(run), "action": "cancel_requested"}


@router.post("/{run_id}/terminate")
async def terminate_run_endpoint(
    run_id: UUID,
    body: LifecycleRequest,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Hard-stop a run immediately, cancelling any in-flight activities.

    Admin-only in production; in dev-mode the synthetic admin bypass applies.
    """
    actor_id = _resolve_actor_id(user)
    try:
        run = await terminate_run(
            session,
            run_id=run_id,
            reason=body.reason,
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run": _run_to_dict(run), "action": "terminated"}


@router.post("/{run_id}/pause")
async def pause_run_endpoint(
    run_id: UUID,
    body: LifecycleRequest,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Suspend a running or queued run.

    The worker polling loop skips paused runs until ``/resume`` is called.
    """
    actor_id = _resolve_actor_id(user)
    try:
        run = await pause_run(
            session,
            run_id=run_id,
            reason=body.reason,
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run": _run_to_dict(run), "action": "paused"}


@router.post("/{run_id}/resume")
async def resume_run_endpoint(
    run_id: UUID,
    body: LifecycleRequest,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Resume a paused run by flipping it back to ``queued``."""
    actor_id = _resolve_actor_id(user)
    try:
        run = await resume_run(
            session,
            run_id=run_id,
            reason=body.reason,
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run": _run_to_dict(run), "action": "resumed"}


# ── Read endpoints ────────────────────────────────────────────────────


@router.get("/{run_id}")
async def get_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get run detail including the hash-chained event log."""
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    # Load events for this run ordered by sequence.
    events_stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .order_by(WorkflowRunEvent.sequence)
    )
    if hasattr(session, "exec"):
        events_result = await session.exec(events_stmt)
        events = list(events_result.all())
    else:
        events_result = await session.execute(events_stmt)
        events = list(events_result.scalars().all())

    return {
        "run": _run_to_dict(run),
        "events": [_event_to_dict(e) for e in events],
    }


@router.get("")
async def list_runs(
    status: str | None = Query(default=None, description="Filter by status"),
    queue: str | None = Query(default=None, description="Filter by queue name (not yet supported)"),
    worker: str | None = Query(default=None, description="Filter by lease_owner worker"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List runs with optional status and worker filters."""
    stmt = select(WorkflowRun)
    if status:
        stmt = stmt.where(WorkflowRun.status == status)
    if worker:
        stmt = stmt.where(WorkflowRun.lease_owner == worker)
    stmt = stmt.order_by(WorkflowRun.created_at.desc()).offset(offset).limit(limit)

    if hasattr(session, "exec"):
        result = await session.exec(stmt)
        runs = list(result.all())
    else:
        result = await session.execute(stmt)
        runs = list(result.scalars().all())

    return {
        "runs": [_run_to_dict(r) for r in runs],
        "limit": limit,
        "offset": offset,
    }


# ── W13 — Visibility search endpoints ────────────────────────────────
# NOTE: /search must be registered BEFORE /{run_id} to avoid the path
# param swallowing the literal "search" segment.


@router.get("/search")
async def search_runs_endpoint(
    status: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
    queue_name: str | None = Query(default=None),
    worker_id: str | None = Query(default=None),
    external_provider: str | None = Query(default=None),
    failure_code: str | None = Query(default=None),
    cost_min: float | None = Query(default=None),
    cost_max: float | None = Query(default=None),
    duration_min_ms: int | None = Query(default=None),
    duration_max_ms: int | None = Query(default=None),
    created_after: str | None = Query(default=None, description="ISO-8601 UTC datetime"),
    created_before: str | None = Query(default=None, description="ISO-8601 UTC datetime"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Search runs via the denormalised VisibilityIndex.

    Supports filtering by status, queue, worker, cost, duration,
    external provider, failure code, and date range.
    """
    tenant_id = _resolve_tenant_id(user)
    filters: dict[str, Any] = {}
    if status:
        filters["status"] = status
    if workflow_id:
        filters["workflow_id"] = workflow_id
    if queue_name:
        filters["queue_name"] = queue_name
    if worker_id:
        filters["worker_id"] = worker_id
    if external_provider:
        filters["external_provider"] = external_provider
    if failure_code:
        filters["failure_code"] = failure_code
    if cost_min is not None:
        filters["cost_min"] = cost_min
    if cost_max is not None:
        filters["cost_max"] = cost_max
    if duration_min_ms is not None:
        filters["duration_min_ms"] = duration_min_ms
    if duration_max_ms is not None:
        filters["duration_max_ms"] = duration_max_ms
    if created_after:
        filters["created_after"] = created_after
    if created_before:
        filters["created_before"] = created_before

    results = await search_runs(
        session,
        tenant_id=tenant_id,
        filters=filters,
        limit=limit,
        offset=offset,
    )
    return {"results": results, "limit": limit, "offset": offset}


@router.get("/{run_id}/timeline")
async def get_run_timeline_endpoint(
    run_id: UUID,
    cursor: int = Query(default=0, ge=0, description="Event sequence cursor"),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return paginated event stream for a run.

    Use ``next_cursor`` from the response as ``cursor`` in the next request.
    Returns ``null`` for ``next_cursor`` when the stream is exhausted.
    """
    return await get_run_timeline(session, run_id=run_id, cursor=cursor, limit=limit)


@router.get("/{run_id}/graph")
async def get_run_graph_endpoint(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return step dependency graph for a run.

    Nodes are live WorkflowRunStep rows. Edges are derived from the
    run's definition_snapshot.graph_definition. Useful for operator
    visualization of execution topology.
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return await get_run_graph(session, run_id=run_id)
