"""API routes for deployment infrastructure management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as PField

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission
from app.models.deployment import (
    ComponentConfig,
    DeploymentConfig,
    EnvironmentType,
    ScalingConfig,
    TLSConfig,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.deployment_service import DeploymentService

router = APIRouter(prefix="/api/v1/deploy", tags=["deployment"])


# ── Request schemas ─────────────────────────────────────────────────


class DeployEnvironmentRequest(BaseModel):
    """Payload for deploying a full environment."""

    environment: EnvironmentType = EnvironmentType.STAGING
    version: str = "0.1.0"
    components: list[ComponentConfig] = PField(default_factory=list)
    scaling: ScalingConfig = PField(default_factory=ScalingConfig)
    tls_enabled: bool = True


class ScaleComponentRequest(BaseModel):
    """Payload for scaling a component."""

    component: str
    replicas: int = PField(ge=0, le=100)


# ── Helpers ─────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _require_infra_admin(user: AuthenticatedUser) -> None:
    """Raise 403 if the user lacks infra_admin or admin role."""
    if not check_permission(user, "infrastructure", "admin"):
        raise HTTPException(status_code=403, detail="Permission denied: infrastructure:admin")


# ── Routes ──────────────────────────────────────────────────────────


@router.post("", status_code=201)
async def deploy_environment(
    body: DeployEnvironmentRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Deploy a full environment (dev/staging/prod)."""
    _require_infra_admin(user)

    config = DeploymentConfig(
        environment=body.environment,
        version=body.version,
        components=body.components,
        scaling=body.scaling,
        tls_config=TLSConfig(enabled=body.tls_enabled),
    )

    try:
        result = await DeploymentService.deploy_environment(
            tenant_id=user.tenant_id,
            user=user,
            config=config,
            secrets_manager=secrets,
        )
    except (ValueError, PermissionError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 400
        raise HTTPException(status_code=code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.get("/{deployment_id}/status")
async def get_deployment_status(
    deployment_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get current deployment status with component health."""
    _require_infra_admin(user)

    try:
        result = await DeploymentService.get_deployment_status(
            tenant_id=user.tenant_id,
            deployment_id=deployment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/{deployment_id}/rollback")
async def rollback_deployment(
    deployment_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Roll back a deployment to the previous version."""
    _require_infra_admin(user)

    try:
        result = await DeploymentService.rollback_deployment(
            tenant_id=user.tenant_id,
            user=user,
            deployment_id=deployment_id,
        )
    except (ValueError, PermissionError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 404
        raise HTTPException(status_code=code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/scale")
async def scale_component(
    body: ScaleComponentRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Horizontally scale a component."""
    _require_infra_admin(user)

    try:
        result = await DeploymentService.scale_component(
            tenant_id=user.tenant_id,
            user=user,
            component=body.component,
            replicas=body.replicas,
        )
    except (ValueError, PermissionError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 400
        raise HTTPException(status_code=code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.get("/health")
async def infrastructure_health(
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Get infrastructure health (Vault, Keycloak, DB, Redis)."""
    _require_infra_admin(user)

    result = await DeploymentService.get_infrastructure_health(
        tenant_id=user.tenant_id,
        secrets_manager=secrets,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/rotate-certs")
async def rotate_tls_certificates(
    user: AuthenticatedUser = Depends(get_current_user),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Rotate TLS certificates via Vault PKI."""
    _require_infra_admin(user)

    try:
        result = await DeploymentService.rotate_tls_certificates(
            tenant_id=user.tenant_id,
            user=user,
            secrets_manager=secrets,
        )
    except (ValueError, PermissionError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 400
        raise HTTPException(status_code=code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/backup")
async def create_backup(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Back up DB, Vault, and configs."""
    _require_infra_admin(user)

    try:
        result = await DeploymentService.backup(
            tenant_id=user.tenant_id,
            user=user,
        )
    except (ValueError, PermissionError) as exc:
        code = 403 if isinstance(exc, PermissionError) else 400
        raise HTTPException(status_code=code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.get("/metrics")
async def platform_metrics(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get aggregated platform metrics."""
    _require_infra_admin(user)

    result = await DeploymentService.get_metrics(
        tenant_id=user.tenant_id,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}
