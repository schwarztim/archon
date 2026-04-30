"""Artifacts REST surface (Phase 5).

Owned by WS5 / Observability+Artifacts Squad. Pairs with
``artifact_service`` to expose:

  GET    /artifacts?run_id=...&tenant_id=...&limit=...&cursor=...
  GET    /artifacts/{id}                — metadata only
  GET    /artifacts/{id}/content        — binary stream (Content-Type stored)
  DELETE /artifacts/{id}                — tenant-scoped delete

Auth: every endpoint requires an authenticated user. Tenant scoping is
applied so non-admin operators cannot reach across tenants. Cross-tenant
requests get a 404 (not 403) so we don't leak existence — the same
pattern used by the approvals router.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.models.artifact import Artifact
from app.services import artifact_service

router = APIRouter(tags=["artifacts"])
logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────


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


def _effective_tenant_filter(
    user: AuthenticatedUser | None,
    requested: UUID | None,
) -> UUID | None:
    """Return the tenant filter the caller is allowed to use.

    Admins may pass ``tenant_id`` to query any tenant (or absent → all).
    Non-admins always have their own tenant forced; mismatching values
    are silently overridden so we never leak which tenants exist.
    """
    if _is_admin(user):
        return requested
    return _resolve_tenant_id(user)


def _artifact_to_dict(artifact: Artifact) -> dict[str, Any]:
    """Serialise an Artifact row for the REST surface.

    NOTE: the JSON column is named ``meta`` on the model (``metadata`` is
    reserved by SQLAlchemy). The REST surface still uses ``metadata`` so
    callers don't have to know about that internal detail.
    """
    return {
        "id": str(artifact.id),
        "run_id": str(artifact.run_id) if artifact.run_id else None,
        "step_id": artifact.step_id,
        "tenant_id": str(artifact.tenant_id) if artifact.tenant_id else None,
        "content_type": artifact.content_type,
        "content_hash": artifact.content_hash,
        "size_bytes": artifact.size_bytes,
        "storage_backend": artifact.storage_backend,
        "retention_days": artifact.retention_days,
        "expires_at": (
            artifact.expires_at.isoformat() if artifact.expires_at else None
        ),
        "created_at": (
            artifact.created_at.isoformat() if artifact.created_at else None
        ),
        "metadata": artifact.meta or {},
    }


# ── routes ───────────────────────────────────────────────────────────


@router.get("/artifacts")
async def list_artifacts_endpoint(
    request: Request,
    run_id: UUID | None = Query(default=None),
    tenant_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Cursor-paginated listing.

    Tenant scoping rules mirror approvals:
      * Admins may pass ``tenant_id`` to query any tenant (absent → all).
      * Non-admins always have the filter forced to their own tenant.
    """
    effective_tenant = _effective_tenant_filter(user, tenant_id)

    page = await artifact_service.list_artifacts(
        session,
        run_id=run_id,
        tenant_id=effective_tenant,
        limit=limit,
        cursor=cursor,
    )
    return {
        "data": [_artifact_to_dict(a) for a in page["data"]],
        "meta": _meta(
            request_id=getattr(request.state, "request_id", None),
            count=len(page["data"]),
            next_cursor=page["next_cursor"],
        ),
    }


@router.get("/artifacts/{artifact_id}")
async def get_artifact_metadata(
    artifact_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return metadata for a single artifact (tenant-scoped)."""
    # Use session.get directly because the service helper also fetches
    # bytes — for metadata-only we don't need the storage round-trip.
    artifact = await session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if not _is_admin(user):
        caller_tenant = _resolve_tenant_id(user)
        if (
            artifact.tenant_id is None
            or artifact.tenant_id != caller_tenant
        ):
            raise HTTPException(status_code=404, detail="Artifact not found")

    return {
        "data": _artifact_to_dict(artifact),
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


@router.get("/artifacts/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: UUID,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    """Stream the artifact bytes with the stored Content-Type."""
    caller_tenant = None if _is_admin(user) else _resolve_tenant_id(user)

    fetched = await artifact_service.get_artifact(
        session,
        artifact_id,
        tenant_id=caller_tenant,
    )
    if fetched is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact, content = fetched
    return Response(
        content=content,
        media_type=artifact.content_type or "application/octet-stream",
        headers={
            "Content-Length": str(artifact.size_bytes),
            "X-Artifact-Id": str(artifact.id),
            "X-Content-Hash": artifact.content_hash,
        },
    )


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact_endpoint(
    artifact_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete an artifact (row + storage object). Tenant-scoped."""
    caller_tenant = None if _is_admin(user) else _resolve_tenant_id(user)

    deleted = await artifact_service.delete_artifact(
        session,
        artifact_id,
        tenant_id=caller_tenant,
    )
    if not deleted:
        # 404 — never leak that the artifact exists in another tenant.
        raise HTTPException(status_code=404, detail="Artifact not found")

    await session.commit()
    return {
        "data": {"id": str(artifact_id), "deleted": True},
        "meta": _meta(request_id=getattr(request.state, "request_id", None)),
    }


__all__ = ["router"]
