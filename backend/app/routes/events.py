"""Event history REST API for workflow runs.

Phase 1 + Phase 5 of the master plan require event history APIs (REST +
WebSocket) so a completed run can be understood without live WebSocket
memory. This module owns the REST surface; the live WebSocket surface
lives in :mod:`app.websocket.events_manager`.

Endpoints
---------

* ``GET /api/v1/workflow-runs/{run_id}/events`` —
  paginated event history with hash-chain verification
* ``GET /api/v1/executions/{run_id}/events`` —
  legacy alias for the above (per ADR-006)
* ``GET /api/v1/workflow-runs/{run_id}/events/verify`` —
  hash-chain integrity probe used by audit dashboards
* ``GET /api/v1/workflow-runs`` —
  paginated run history list (consumed by the Phase 7 frontend)

Schema is bound by ADR-002 — schema changes require a Data Model squad
amendment. This module is read-only against ``workflow_run_events``.

Tenant scoping
~~~~~~~~~~~~~~
Every endpoint is tenant-scoped. A run owned by tenant A is invisible to
tenant B; the API returns ``404`` rather than ``403`` so existence is
not leaked. Admins (``role == "admin"``) may bypass tenant filtering.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.middleware.auth import get_current_user
from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.workflow import WorkflowRun, WorkflowRunEvent
from app.services.event_service import (
    EVENT_TYPES,
    build_envelope,
    compute_hash,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


# ── Constants ──────────────────────────────────────────────────────────


_DEFAULT_EVENT_LIMIT = 100
_MAX_EVENT_LIMIT = 500
_DEFAULT_RUN_LIMIT = 50
_MAX_RUN_LIMIT = 200


# ── Helpers ────────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block, matching executions.py."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _user_tenant_uuid(user: AuthenticatedUser) -> UUID | None:
    """Coerce the user's tenant_id to a UUID. Admins return None.

    Returning ``None`` from this helper means "do not constrain by
    tenant" — the caller decides whether that is an admin bypass or a
    structural absence of tenancy.
    """
    if "admin" in user.roles:
        return None
    if not user.tenant_id:
        return None
    try:
        return UUID(user.tenant_id)
    except (ValueError, TypeError):
        return None


def _run_visible_to(user: AuthenticatedUser, run: WorkflowRun) -> bool:
    """Return True iff *run* is visible to *user* under tenant scoping.

    Admins see everything. Tenant-scoped users see only rows where
    ``run.tenant_id`` matches their tenant. A run with ``tenant_id=None``
    is treated as global and visible to everyone (test-fixture friendly).
    """
    if "admin" in user.roles:
        return True
    user_tenant = _user_tenant_uuid(user)
    if user_tenant is None:
        # Non-admin without a tenant context: only see global rows.
        return run.tenant_id is None
    if run.tenant_id is None:
        return True
    return run.tenant_id == user_tenant


def _serialise_event(event: WorkflowRunEvent) -> dict[str, Any]:
    """Render a row as the wire-format dict used by REST + WS."""
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": event.payload,
        "tenant_id": str(event.tenant_id) if event.tenant_id else None,
        "correlation_id": event.correlation_id,
        "span_id": event.span_id,
        "step_id": event.step_id,
        "prev_hash": event.prev_hash,
        "current_hash": event.current_hash,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _serialise_run(run: WorkflowRun) -> dict[str, Any]:
    """Compact run-list shape for the run history endpoint."""
    return {
        "id": str(run.id),
        "kind": run.kind,
        "workflow_id": str(run.workflow_id) if run.workflow_id else None,
        "agent_id": str(run.agent_id) if run.agent_id else None,
        "tenant_id": str(run.tenant_id) if run.tenant_id else None,
        "status": run.status,
        "trigger_type": run.trigger_type,
        "triggered_by": run.triggered_by,
        "queued_at": run.queued_at.isoformat() if run.queued_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": (
            run.completed_at.isoformat() if run.completed_at else None
        ),
        "duration_ms": run.duration_ms,
        "error_code": run.error_code,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _verify_chain_async(events: list[WorkflowRunEvent]) -> tuple[bool, int | None]:
    """Verify a contiguous chain (sequence-ordered) and locate corruption.

    Returns ``(chain_verified, first_corruption_at_sequence)``. The check
    here mirrors :func:`event_service.verify_hash_chain` but reuses the
    rows already loaded for the response, avoiding a second DB round-trip.
    """
    expected_prev: str | None = None
    expected_sequence = 0 if events and events[0].sequence == 0 else None
    if expected_sequence is None and events:
        # Caller fetched a window mid-chain. Seed expected_prev from the
        # first row's recorded prev_hash so we still validate every link
        # within the window.
        expected_prev = events[0].prev_hash
        expected_sequence = events[0].sequence

    for event in events:
        if expected_sequence is not None and event.sequence != expected_sequence:
            return False, event.sequence
        if event.prev_hash != expected_prev:
            return False, event.sequence
        envelope = build_envelope(
            run_id=event.run_id,
            sequence=event.sequence,
            event_type=event.event_type,
            payload=event.payload,
            step_id=event.step_id,
            tenant_id=event.tenant_id,
            correlation_id=event.correlation_id,
            span_id=event.span_id,
        )
        recomputed = compute_hash(event.prev_hash, envelope)
        if recomputed != event.current_hash:
            return False, event.sequence
        expected_prev = event.current_hash
        if expected_sequence is not None:
            expected_sequence += 1

    return True, None


async def _load_run_or_404(
    session: AsyncSession,
    run_id: UUID,
    user: AuthenticatedUser,
) -> WorkflowRun:
    """Fetch the run, enforce tenant visibility, raise 404 on miss.

    Returning 404 (not 403) when the tenant does not match is intentional:
    we must not leak the existence of cross-tenant runs.
    """
    stmt = select(WorkflowRun).where(WorkflowRun.id == run_id)
    result = await session.exec(stmt)
    run = result.first()
    if run is None or not _run_visible_to(user, run):
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run


# ── GET /workflow-runs/{run_id}/events ─────────────────────────────────


async def _list_events_impl(
    run_id: UUID,
    after_sequence: int,
    limit: int,
    event_types: str | None,
    session: AsyncSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Shared implementation for the canonical and alias routes."""
    if limit < 1:
        limit = 1
    if limit > _MAX_EVENT_LIMIT:
        limit = _MAX_EVENT_LIMIT

    await _load_run_or_404(session, run_id, user)

    # Parse the event_types CSV filter (rejects unknown types so callers
    # discover typos up-front; ADR-002 says unknown types must be rejected
    # at insert, but it costs us nothing to reject at read too).
    requested_types: list[str] = []
    if event_types:
        requested_types = [
            t.strip() for t in event_types.split(",") if t.strip()
        ]
        for t in requested_types:
            if t not in EVENT_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown event_type: {t!r}",
                )

    # Always load the *unfiltered* page for hash-chain verification,
    # then filter by event_type for the response. This prevents a
    # filter from breaking chain verification for the run.
    full_stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .where(WorkflowRunEvent.sequence > after_sequence)
        .order_by(WorkflowRunEvent.sequence.asc())
        .limit(limit + 1)  # +1 so we know if there's a next page
    )
    full_result = await session.exec(full_stmt)
    rows: list[WorkflowRunEvent] = list(full_result.all())

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    chain_verified, _ = _verify_chain_async(rows)

    if requested_types:
        visible = [r for r in rows if r.event_type in requested_types]
    else:
        visible = rows

    next_after = rows[-1].sequence if rows and has_more else None

    return {
        "run_id": str(run_id),
        "events": [_serialise_event(r) for r in visible],
        "next_after_sequence": next_after,
        "chain_verified": chain_verified,
        "meta": _meta(),
    }


@router.get("/workflow-runs/{run_id}/events")
async def list_run_events(
    run_id: UUID,
    after_sequence: int = Query(default=-1, ge=-1),
    limit: int = Query(default=_DEFAULT_EVENT_LIMIT, ge=1, le=_MAX_EVENT_LIMIT),
    event_types: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a chronological page of events for *run_id*.

    Hash-chain verification runs over the (unfiltered) page so a
    payload-tamper test still trips ``chain_verified=false`` even when
    the response was filtered by ``event_types``.
    """
    return await _list_events_impl(
        run_id, after_sequence, limit, event_types, session, user
    )


@router.get("/executions/{run_id}/events")
async def list_execution_events_alias(
    run_id: UUID,
    after_sequence: int = Query(default=-1, ge=-1),
    limit: int = Query(default=_DEFAULT_EVENT_LIMIT, ge=1, le=_MAX_EVENT_LIMIT),
    event_types: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Alias for :func:`list_run_events` — see ADR-006 for the migration."""
    return await _list_events_impl(
        run_id, after_sequence, limit, event_types, session, user
    )


# ── GET /workflow-runs/{run_id}/events/verify ──────────────────────────


@router.get("/workflow-runs/{run_id}/events/verify")
async def verify_run_events_chain(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Hash-chain integrity probe — used by audit dashboards.

    Returns ``{chain_verified, first_corruption_at_sequence}``. A non-null
    ``first_corruption_at_sequence`` indicates the earliest event whose
    recorded ``current_hash`` no longer matches the canonical envelope —
    evidence that the row was mutated after insert.
    """
    await _load_run_or_404(session, run_id, user)

    stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run_id)
        .order_by(WorkflowRunEvent.sequence.asc())
    )
    result = await session.exec(stmt)
    rows = list(result.all())

    chain_verified, first_corruption = _verify_chain_async(rows)
    return {
        "run_id": str(run_id),
        "chain_verified": chain_verified,
        "first_corruption_at_sequence": first_corruption,
        "event_count": len(rows),
        "meta": _meta(),
    }


# ── GET /workflow-runs (run history list) ──────────────────────────────


@router.get("/workflow-runs")
async def list_workflow_runs(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    workflow_id: UUID | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_RUN_LIMIT, ge=1, le=_MAX_RUN_LIMIT),
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Paginated run history list. Consumed by the Phase 7 frontend.

    The cursor is the ``created_at`` timestamp of the oldest item on the
    previous page (ISO-8601 with timezone). When supplied, the next page
    begins strictly before that timestamp. ``cursor`` is opaque to
    callers — they should round-trip whatever the server hands back.
    """
    is_admin = "admin" in user.roles
    if tenant_id is not None and not is_admin:
        # Non-admin attempted to scope to a tenant — only allow self.
        own = _user_tenant_uuid(user)
        if own is None or own != tenant_id:
            raise HTTPException(
                status_code=403,
                detail="cannot list runs outside your tenant",
            )

    stmt = select(WorkflowRun)

    # Tenant scoping. Admins can request any tenant (or all). Non-admins
    # are pinned to their own.
    if is_admin and tenant_id is not None:
        stmt = stmt.where(WorkflowRun.tenant_id == tenant_id)
    elif not is_admin:
        own = _user_tenant_uuid(user)
        if own is not None:
            stmt = stmt.where(
                (WorkflowRun.tenant_id == own) | (WorkflowRun.tenant_id.is_(None))
            )

    if status is not None:
        stmt = stmt.where(WorkflowRun.status == status)
    if kind is not None:
        stmt = stmt.where(WorkflowRun.kind == kind)
    if agent_id is not None:
        stmt = stmt.where(WorkflowRun.agent_id == agent_id)
    if workflow_id is not None:
        stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
    if since is not None:
        stmt = stmt.where(WorkflowRun.created_at >= _strip_tz(since))

    if cursor is not None:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="invalid cursor"
            ) from exc
        stmt = stmt.where(WorkflowRun.created_at < _strip_tz(cursor_dt))

    stmt = stmt.order_by(WorkflowRun.created_at.desc()).limit(limit + 1)

    result = await session.exec(stmt)
    rows = list(result.all())

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        if last.created_at is not None:
            next_cursor = last.created_at.isoformat()

    return {
        "items": [_serialise_run(r) for r in rows],
        "next_cursor": next_cursor,
        "meta": _meta(pagination={"limit": limit, "returned": len(rows)}),
    }


def _strip_tz(value: datetime) -> datetime:
    """Coerce an aware datetime to naive UTC.

    ``WorkflowRun.created_at`` is a naive ``TIMESTAMP WITHOUT TIME ZONE``
    column (see ``app/models/workflow.py``). Comparing aware datetimes
    against it raises ``TypeError`` on PostgreSQL and silently breaks
    ordering on SQLite. Strip the tzinfo after converting to UTC so the
    comparison is well-defined either way.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


__all__ = ["router"]
