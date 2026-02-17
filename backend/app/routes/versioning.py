"""Versioning endpoints — compare, rollback, and promote agent versions.

Enterprise routes for signed version control, secrets-aware diffs,
and deployment promotion.  All routes are authenticated, RBAC-checked,
and tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.models.versioning import CreateVersionRequest, PromoteVersionRequest
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.agent_version_service import AgentVersionService
from app.services.versioning_service import VersioningService

router = APIRouter(prefix="/agents", tags=["versioning"])


# ── Request / response schemas ──────────────────────────────────────


class RollbackRequest(BaseModel):
    """Payload for a rollback operation."""

    created_by: UUID


class PromoteRequest(BaseModel):
    """Payload for a promotion operation."""

    target_environment: str
    created_by: UUID


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Legacy routes (kept for backward compatibility) ─────────────────


@router.get("/{agent_id}/versions/compare")
async def compare_versions(
    agent_id: UUID,
    v1: UUID = Query(..., description="First version ID"),
    v2: UUID = Query(..., description="Second version ID"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Compare two versions of an agent definition (JSON diff)."""
    try:
        diff = await AgentVersionService.compare(session, v1, v2)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if diff["agent_id"] != str(agent_id):
        raise HTTPException(
            status_code=400,
            detail="Versions do not belong to the specified agent",
        )

    return {"data": diff, "meta": _meta()}


@router.post("/{agent_id}/versions/{version_id}/rollback", status_code=201)
async def rollback_version(
    agent_id: UUID,
    version_id: UUID,
    body: RollbackRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Rollback an agent to a previous version (creates a new version)."""
    try:
        new_version = await AgentVersionService.rollback(
            session,
            agent_id=agent_id,
            target_version_id=version_id,
            created_by=body.created_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"data": new_version.model_dump(mode="json"), "meta": _meta()}


@router.post("/{agent_id}/versions/{version_id}/promote", status_code=201)
async def promote_version(
    agent_id: UUID,
    version_id: UUID,
    body: PromoteRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Promote a version to a target deployment environment."""
    try:
        new_version = await AgentVersionService.promote(
            session,
            version_id=version_id,
            target_environment=body.target_environment,
            created_by=body.created_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"data": new_version.model_dump(mode="json"), "meta": _meta()}


# ── Enterprise routes (authenticated, RBAC, tenant-scoped) ──────────


@router.post("/{agent_id}/versions", status_code=201)
async def create_version(
    agent_id: UUID,
    body: CreateVersionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Create an immutable, signed version snapshot."""
    try:
        version = await VersioningService.create_version(
            tenant_id=user.tenant_id,
            user=user,
            agent_id=agent_id,
            change_reason=body.change_reason,
            session=session,
            secrets=secrets,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"data": version.model_dump(mode="json"), "meta": _meta()}


@router.get("/{agent_id}/versions/export")
async def export_version_history(
    agent_id: UUID,
    fmt: str = Query("json", alias="format", description="Export format: json | pdf"),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Export version history as JSON or PDF."""
    data = await VersioningService.export_history(
        tenant_id=user.tenant_id,
        agent_id=agent_id,
        fmt=fmt,
        session=session,
    )
    media = "application/json" if fmt == "json" else "application/octet-stream"
    return Response(content=data, media_type=media)


@router.get("/{agent_id}/versions/list")
async def list_versions(
    agent_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List paginated version history for an agent."""
    versions = await VersioningService.list_versions(
        tenant_id=user.tenant_id,
        agent_id=agent_id,
        filters={"limit": limit, "offset": offset},
        session=session,
    )
    return {
        "data": [v.model_dump(mode="json") for v in versions],
        "meta": _meta(pagination={"limit": limit, "offset": offset}),
    }


@router.get("/{agent_id}/versions/{version_id}/detail")
async def get_version(
    agent_id: UUID,
    version_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single version by ID."""
    try:
        version = await VersioningService.get_version(
            tenant_id=user.tenant_id,
            version_id=version_id,
            session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"data": version.model_dump(mode="json"), "meta": _meta()}


@router.get("/{agent_id}/versions/{v1}/diff/{v2}")
async def diff_versions(
    agent_id: UUID,
    v1: UUID,
    v2: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Secrets-aware diff between two versions."""
    try:
        diff = await VersioningService.diff_versions(
            tenant_id=user.tenant_id,
            version_a_id=v1,
            version_b_id=v2,
            session=session,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"data": diff.model_dump(mode="json"), "meta": _meta()}


@router.post("/{agent_id}/versions/{version_id}/enterprise-rollback", status_code=201)
async def enterprise_rollback(
    agent_id: UUID,
    version_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Rollback with pre-flight checks (secrets, models, connectors)."""
    try:
        version = await VersioningService.rollback(
            tenant_id=user.tenant_id,
            user=user,
            agent_id=agent_id,
            target_version_id=version_id,
            session=session,
            secrets=secrets,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"data": version.model_dump(mode="json"), "meta": _meta()}


@router.post("/{agent_id}/versions/{version_id}/enterprise-promote", status_code=201)
async def enterprise_promote(
    agent_id: UUID,
    version_id: UUID,
    body: PromoteVersionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Promote version through environments with approval gates."""
    try:
        promotion = await VersioningService.promote(
            tenant_id=user.tenant_id,
            user=user,
            version_id=version_id,
            target_env=body.target_env,
            session=session,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"data": promotion.model_dump(mode="json"), "meta": _meta()}


@router.get("/{agent_id}/versions/{version_id}/verify")
async def verify_version_signature(
    agent_id: UUID,
    version_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Verify cryptographic signature of a version."""
    try:
        result = await VersioningService.verify_signature(
            version_id=version_id,
            session=session,
            secrets=secrets,
            tenant_id=user.tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}
