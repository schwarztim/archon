"""Signals, Queries, and Updates REST surface — W5.

Vendor-neutral durable message-passing endpoints for running workflow runs:

  POST  /api/v1/runs/{run_id}/signals   — send async signal (fire-and-forget)
  GET   /api/v1/runs/{run_id}/query     — read-only state inspection (no mutation)
  POST  /api/v1/runs/{run_id}/updates   — synchronous validated state change

Auth: every endpoint requires an authenticated user.  Tenant scoping is
applied — non-admins can only interact with runs in their own tenant.  Cross-
tenant access returns 404 (not 403) so we don't leak existence.

These endpoints complement the existing approvals surface in routes/approvals.py
and follow the same envelope pattern.
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
from app.models.workflow import WorkflowRun
from app.services import signal_service

router = APIRouter(prefix="/api/v1/runs", tags=["signals"])
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Standard response envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _resolve_tenant_id(user: AuthenticatedUser | None) -> UUID | None:
    if user is None:
        return None
    if not getattr(user, "tenant_id", None):
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


def _resolve_actor_id(user: AuthenticatedUser | None) -> str | None:
    if user is None:
        return None
    raw = getattr(user, "id", None)
    return str(raw) if raw is not None else None


async def _get_run_or_404(
    session: AsyncSession, run_id: UUID, user: AuthenticatedUser | None
) -> WorkflowRun:
    """Fetch the run and apply tenant gate (404 on miss or cross-tenant access)."""
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _is_admin(user):
        caller_tenant = _resolve_tenant_id(user)
        if run.tenant_id is not None and run.tenant_id != caller_tenant:
            raise HTTPException(status_code=404, detail="Run not found")
    return run


# ── request schemas ───────────────────────────────────────────────────────────


class SendSignalRequest(BaseModel):
    """Body for POST /api/v1/runs/{run_id}/signals."""

    signal_name: str = Field(min_length=1, description="Name of the signal to emit")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary JSON payload delivered with the signal",
    )


class SendUpdateRequest(BaseModel):
    """Body for POST /api/v1/runs/{run_id}/updates."""

    update_name: str = Field(min_length=1, description="Name of the update to apply")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Payload to validate and apply",
    )


# ── routes ────────────────────────────────────────────────────────────────────


@router.post("/{run_id}/signals")
async def send_signal(
    run_id: UUID,
    body: SendSignalRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Emit a named signal into a running workflow (fire-and-forget).

    The signal is persisted immediately; the workflow may consume it at any
    point.  Use for external events that should unblock or notify a run
    without waiting for a response.
    """
    await _get_run_or_404(session, run_id, user)

    sig = await signal_service.send_named_signal(
        session,
        run_id=run_id,
        signal_name=body.signal_name,
        payload=body.payload,
        sender_id=_resolve_actor_id(user),
    )
    await session.commit()

    logger.info(
        "signals.send_signal",
        extra={
            "run_id": str(run_id),
            "signal_id": str(sig.id),
            "signal_name": body.signal_name,
        },
    )
    return {
        "data": {
            "signal_id": str(sig.id),
            "run_id": str(run_id),
            "signal_name": sig.signal_type,
            "status": "pending",
        },
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.get("/{run_id}/query")
async def query_run_state(
    run_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Read-only inspection of a run's current state.

    Returns status, input_data, latest step outputs, pending signal names,
    and active timer summaries.  Makes NO state mutations.
    """
    await _get_run_or_404(session, run_id, user)

    try:
        state = await signal_service.query_run_state(session, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "data": state,
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/{run_id}/updates")
async def send_update(
    run_id: UUID,
    body: SendUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Apply a synchronous, validated state change to a workflow run.

    The update is validated by any registered handler for ``update_name``.
    If validation succeeds, the mutation is applied and a result record with
    ``status=applied`` is returned.  If validation fails, the result record
    has ``status=rejected`` with an ``error_message``.
    """
    await _get_run_or_404(session, run_id, user)

    try:
        result = await signal_service.send_update(
            session,
            run_id=run_id,
            update_name=body.update_name,
            payload=body.payload,
            sender_id=_resolve_actor_id(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()

    logger.info(
        "signals.send_update",
        extra={
            "run_id": str(run_id),
            "update_result_id": str(result.id),
            "update_name": body.update_name,
            "status": result.status,
        },
    )
    return {
        "data": {
            "update_result_id": str(result.id),
            "run_id": str(run_id),
            "update_name": result.update_name,
            "status": result.status,
            "response_payload": result.response_payload,
            "error_message": result.error_message,
        },
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


__all__ = ["router"]
