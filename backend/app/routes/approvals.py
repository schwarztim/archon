"""Approvals + signals REST surface.

Owned by WS8. Phase 2 of master plan — pairs with ``approval_service``
and ``signal_service`` to provide:

  GET  /approvals?status=pending&tenant_id=...
  GET  /approvals/{id}
  POST /approvals/{id}/approve   body: {"reason": "..."}
  POST /approvals/{id}/reject    body: {"reason": "..."}
  POST /executions/{run_id}/resume
  POST /executions/{run_id}/signals  body: {"signal_type": "...", "payload": {...}}

Auth: every endpoint requires an authenticated user. Tenant scoping is
applied on the GET and approve/reject endpoints — operators can only
see / decide approvals in their own tenant. Cross-tenant requests get
a 404 (not 403) so we don't leak existence.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.models.approval import Approval
from app.models.workflow import WorkflowRun
from app.services import approval_service, signal_service

router = APIRouter(tags=["approvals"])
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build the standard envelope meta block (mirrors executions router)."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _resolve_tenant_id(user: AuthenticatedUser | None) -> UUID | None:
    """Return the caller's tenant UUID, or None when unauthenticated/dev."""
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


def _resolve_actor_id(user: AuthenticatedUser | None) -> UUID | None:
    """Best-effort coercion of the authenticated user id to a UUID."""
    if user is None:
        return None
    raw = getattr(user, "id", None)
    if raw is None:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


def _approval_to_dict(approval: Approval) -> dict[str, Any]:
    """Serialise an Approval row for the REST surface."""
    return {
        "id": str(approval.id),
        "run_id": str(approval.run_id),
        "step_id": approval.step_id,
        "tenant_id": str(approval.tenant_id) if approval.tenant_id else None,
        "requester_id": str(approval.requester_id) if approval.requester_id else None,
        "approver_id": str(approval.approver_id) if approval.approver_id else None,
        "status": approval.status,
        "decision_reason": approval.decision_reason,
        "requested_at": (
            approval.requested_at.isoformat() if approval.requested_at else None
        ),
        "decided_at": (
            approval.decided_at.isoformat() if approval.decided_at else None
        ),
        "expires_at": (
            approval.expires_at.isoformat() if approval.expires_at else None
        ),
        "payload": approval.payload or {},
    }


def _check_tenant_visibility(
    approval: Approval, *, user: AuthenticatedUser | None
) -> None:
    """Raise 404 if the approval is not visible to the caller.

    Admins see everything. Other users see only approvals carrying their
    tenant_id. Approvals with no tenant_id are admin-only.
    """
    if _is_admin(user):
        return
    caller_tenant = _resolve_tenant_id(user)
    if approval.tenant_id is None or approval.tenant_id != caller_tenant:
        raise HTTPException(status_code=404, detail="Approval not found")


# ── request schemas ──────────────────────────────────────────────────


class DecisionRequest(BaseModel):
    """Body for POST /approvals/{id}/approve|reject."""

    reason: str | None = None


class SignalInjectRequest(BaseModel):
    """Body for POST /executions/{run_id}/signals."""

    signal_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = None


# ── routes ───────────────────────────────────────────────────────────


@router.get("/approvals")
async def list_approvals(
    request: Request,
    status: str = Query(default="pending"),
    tenant_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List approvals filtered by status (default ``pending``).

    Tenant scoping rules:
      * Admins may pass ``tenant_id`` to query any tenant; absent →
        returns approvals across all tenants.
      * Non-admins always have the filter forced to their own tenant.
        A mismatching ``tenant_id`` is silently overridden — we do not
        leak which tenants exist.
    """
    if status != "pending":
        # The current shape supports pending-only listing per the
        # master plan. Return an empty list with a meta note rather
        # than 422 — the callers may pass-through ``status``.
        return {
            "data": [],
            "meta": _meta(
                request_id=getattr(request.state, "request_id", None),
                note=f"only status=pending is supported, got {status!r}",
            ),
        }

    effective_tenant: UUID | None = tenant_id
    if not _is_admin(user):
        effective_tenant = _resolve_tenant_id(user)

    rows = await approval_service.list_pending(
        session,
        tenant_id=effective_tenant,
        limit=limit,
    )
    return {
        "data": [_approval_to_dict(a) for a in rows],
        "meta": _meta(
            request_id=getattr(request.state, "request_id", None),
            count=len(rows),
        ),
    }


@router.get("/approvals/{approval_id}")
async def get_approval(
    approval_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch a single approval by id (tenant-scoped)."""
    approval = await approval_service.get_approval(session, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    _check_tenant_visibility(approval, user=user)
    return {
        "data": _approval_to_dict(approval),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/approvals/{approval_id}/approve")
async def approve_approval(
    approval_id: UUID,
    body: DecisionRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Grant an approval. Emits ``approval.granted`` + ``run.resumed``."""
    approval = await approval_service.get_approval(session, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    _check_tenant_visibility(approval, user=user)

    try:
        approval, sig = await approval_service.grant_approval(
            session,
            approval_id=approval_id,
            approver_id=_resolve_actor_id(user),
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()

    return {
        "data": {
            "approval": _approval_to_dict(approval),
            "signal_id": str(sig.id),
        },
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/approvals/{approval_id}/reject")
async def reject_approval(
    approval_id: UUID,
    body: DecisionRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Reject an approval. Emits ``approval.rejected``. Run remains paused."""
    approval = await approval_service.get_approval(session, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    _check_tenant_visibility(approval, user=user)

    try:
        approval, sig = await approval_service.reject_approval(
            session,
            approval_id=approval_id,
            approver_id=_resolve_actor_id(user),
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()

    return {
        "data": {
            "approval": _approval_to_dict(approval),
            "signal_id": str(sig.id),
        },
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/executions/{run_id}/resume")
async def resume_run(
    run_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Generic resume — re-checks pending signals; dispatcher does the work.

    This endpoint exists so an operator can manually nudge the dispatcher
    when a run is paused and a signal already exists. Returns the count
    of pending signals visible for the run; the dispatcher (W2.4) is
    responsible for the actual resume.
    """
    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Tenant gate (admins exempt).
    if not _is_admin(user):
        caller_tenant = _resolve_tenant_id(user)
        if run.tenant_id is not None and run.tenant_id != caller_tenant:
            raise HTTPException(status_code=404, detail="Run not found")

    pending = await signal_service.peek_pending_signals(
        session, run_id=run_id
    )
    return {
        "data": {
            "run_id": str(run_id),
            "status": run.status,
            "pending_signal_count": len(pending),
            "pending_signal_types": sorted({s.signal_type for s in pending}),
        },
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.post("/executions/{run_id}/signals")
async def inject_signal(
    run_id: UUID,
    body: SignalInjectRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Operator-injected signal. Admin-only.

    Used by support to deliver e.g. ``input.provided`` for a paused
    ``humanInputNode`` or to ``cancel`` a paused run out-of-band.
    """
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin role required")

    run: WorkflowRun | None = await session.get(WorkflowRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    sig = await signal_service.send_signal(
        session,
        run_id=run_id,
        step_id=body.step_id,
        signal_type=body.signal_type,
        payload=body.payload or {},
    )
    await session.commit()

    return {
        "data": {
            "signal_id": str(sig.id),
            "run_id": str(run_id),
            "signal_type": sig.signal_type,
        },
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


__all__ = ["router"]
