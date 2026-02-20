"""API routes for Archon edge runtime management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission
from app.models.edge import (
    DeviceRegistration,
    OTAUpdate,
    OfflineTokenConfig,
    RemoteCommand,
    SecretsManifest,
    SyncPayload,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.edge import EdgeRuntime
from app.services.edge_service import EdgeService
from starlette.responses import Response

router = APIRouter(prefix="/edge", tags=["edge"])


# ── Request / response schemas ──────────────────────────────────────


class RegisterDeviceRequest(BaseModel):
    """Payload for registering an edge device."""

    name: str
    device_type: str = "generic"
    architecture: str = "x86_64"
    cpu_cores: int = PField(default=4, ge=1)
    memory_mb: int = PField(default=8192, ge=512)
    disk_mb: int = PField(default=51200, ge=1024)
    has_gpu: bool = False
    gpu_model: str | None = None
    ip_address: str | None = None
    location: str | None = None
    region: str | None = None
    device_fingerprint: str | None = None
    certificate_thumbprint: str | None = None
    fleet_id: UUID | None = None
    extra_metadata: dict[str, Any] = PField(default_factory=dict)
    registered_by: UUID | None = None


class UpdateDeviceRequest(BaseModel):
    """Payload for updating an edge device."""

    name: str | None = None
    status: str | None = None
    ip_address: str | None = None
    location: str | None = None
    region: str | None = None
    fleet_id: UUID | None = None
    extra_metadata: dict[str, Any] | None = None


class HeartbeatRequest(BaseModel):
    """Payload for device heartbeat."""

    extra_metadata: dict[str, Any] | None = None


class DeployModelRequest(BaseModel):
    """Payload for deploying a model to an edge device."""

    device_id: UUID
    model_name: str
    model_version: str = "latest"
    inference_backend: str = "ollama"
    quantization: str | None = None
    size_mb: int = PField(default=0, ge=0)
    config: dict[str, Any] = PField(default_factory=dict)
    deployed_by: UUID | None = None


class UpdateModelDeploymentStatusRequest(BaseModel):
    """Payload for updating model deployment status."""

    status: str
    download_progress: float | None = PField(default=None, ge=0.0, le=1.0)


class SyncRequest(BaseModel):
    """Payload for initiating a sync operation."""

    device_id: UUID
    direction: str = "bidirectional"
    sync_type: str = "delta"
    conflict_strategy: str = "last_write_wins"
    last_sync_cursor: str | None = None
    details: dict[str, Any] = PField(default_factory=dict)


class CompleteSyncRequest(BaseModel):
    """Payload for completing a sync operation."""

    status: str = "completed"
    records_sent: int = PField(default=0, ge=0)
    records_received: int = PField(default=0, ge=0)
    bytes_transferred: int = PField(default=0, ge=0)
    conflicts_detected: int = PField(default=0, ge=0)
    conflicts_resolved: int = PField(default=0, ge=0)
    last_sync_cursor: str | None = None
    error_message: str | None = None


class CreateFleetConfigRequest(BaseModel):
    """Payload for creating a fleet configuration."""

    name: str
    description: str | None = None
    target_device_type: str = "generic"
    sync_schedule: str = "periodic"
    sync_interval_seconds: int = PField(default=300, ge=10)
    conflict_strategy: str = "last_write_wins"
    default_inference_backend: str = "ollama"
    default_quantization: str | None = None
    max_offline_hours: int = PField(default=72, ge=1)
    auto_decommission: bool = False
    config: dict[str, Any] = PField(default_factory=dict)
    created_by: UUID | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Devices ─────────────────────────────────────────────────────────


@router.post("/devices", status_code=201)
async def register_device(
    body: RegisterDeviceRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Register a new edge device."""
    device = await EdgeRuntime.register_device(
        session,
        name=body.name,
        device_type=body.device_type,
        architecture=body.architecture,
        cpu_cores=body.cpu_cores,
        memory_mb=body.memory_mb,
        disk_mb=body.disk_mb,
        has_gpu=body.has_gpu,
        gpu_model=body.gpu_model,
        ip_address=body.ip_address,
        location=body.location,
        region=body.region,
        device_fingerprint=body.device_fingerprint,
        certificate_thumbprint=body.certificate_thumbprint,
        fleet_id=body.fleet_id,
        extra_metadata=body.extra_metadata,
        registered_by=body.registered_by,
    )
    return {"data": device.model_dump(mode="json"), "meta": _meta()}


@router.get("/devices")
async def list_devices(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    device_type: str | None = Query(default=None),
    region: str | None = Query(default=None),
    fleet_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List edge devices with optional filters and pagination."""
    devices, total = await EdgeRuntime.list_devices(
        session,
        status=status,
        device_type=device_type,
        region=region,
        fleet_id=fleet_id,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [d.model_dump(mode="json") for d in devices],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/devices/{device_id}")
async def get_device(
    device_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single edge device by ID."""
    device = await EdgeRuntime.get_device(session, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Edge device not found")
    return {"data": device.model_dump(mode="json"), "meta": _meta()}


@router.patch("/devices/{device_id}")
async def update_device(
    device_id: UUID,
    body: UpdateDeviceRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an edge device."""
    device = await EdgeRuntime.update_device(
        session,
        device_id,
        name=body.name,
        status=body.status,
        ip_address=body.ip_address,
        location=body.location,
        region=body.region,
        fleet_id=body.fleet_id,
        extra_metadata=body.extra_metadata,
    )
    if device is None:
        raise HTTPException(status_code=404, detail="Edge device not found")
    return {"data": device.model_dump(mode="json"), "meta": _meta()}


@router.post("/devices/{device_id}/heartbeat")
async def device_heartbeat(
    device_id: UUID,
    body: HeartbeatRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record a heartbeat from an edge device."""
    device = await EdgeRuntime.heartbeat(
        session, device_id, extra_metadata=body.extra_metadata,
    )
    if device is None:
        raise HTTPException(status_code=404, detail="Edge device not found")
    return {"data": device.model_dump(mode="json"), "meta": _meta()}


# ── Model Deployments ───────────────────────────────────────────────


@router.post("/models", status_code=201)
async def deploy_model(
    body: DeployModelRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Deploy a model to an edge device."""
    deployment = await EdgeRuntime.deploy_model(
        session,
        device_id=body.device_id,
        model_name=body.model_name,
        model_version=body.model_version,
        inference_backend=body.inference_backend,
        quantization=body.quantization,
        size_mb=body.size_mb,
        config=body.config,
        deployed_by=body.deployed_by,
    )
    if deployment is None:
        raise HTTPException(status_code=404, detail="Edge device not found")
    return {"data": deployment.model_dump(mode="json"), "meta": _meta()}


@router.get("/models")
async def list_model_deployments(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    device_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List model deployments with optional filters and pagination."""
    deployments, total = await EdgeRuntime.list_model_deployments(
        session, device_id=device_id, status=status, limit=limit, offset=offset,
    )
    return {
        "data": [d.model_dump(mode="json") for d in deployments],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/models/{deployment_id}")
async def get_model_deployment(
    deployment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single model deployment by ID."""
    deployment = await EdgeRuntime.get_model_deployment(session, deployment_id)
    if deployment is None:
        raise HTTPException(status_code=404, detail="Model deployment not found")
    return {"data": deployment.model_dump(mode="json"), "meta": _meta()}


@router.patch("/models/{deployment_id}/status")
async def update_model_deployment_status(
    deployment_id: UUID,
    body: UpdateModelDeploymentStatusRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update the status of a model deployment."""
    deployment = await EdgeRuntime.update_model_deployment_status(
        session, deployment_id, status=body.status, download_progress=body.download_progress,
    )
    if deployment is None:
        raise HTTPException(status_code=404, detail="Model deployment not found")
    return {"data": deployment.model_dump(mode="json"), "meta": _meta()}


# ── Sync ────────────────────────────────────────────────────────────


@router.post("/sync", status_code=201)
async def initiate_sync(
    body: SyncRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Initiate a sync operation for an edge device."""
    record = await EdgeRuntime.sync(
        session,
        device_id=body.device_id,
        direction=body.direction,
        sync_type=body.sync_type,
        conflict_strategy=body.conflict_strategy,
        last_sync_cursor=body.last_sync_cursor,
        details=body.details,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Edge device not found")
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


@router.post("/sync/{sync_id}/complete")
async def complete_sync(
    sync_id: UUID,
    body: CompleteSyncRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Mark a sync operation as completed."""
    record = await EdgeRuntime.complete_sync(
        session,
        sync_id,
        status=body.status,
        records_sent=body.records_sent,
        records_received=body.records_received,
        bytes_transferred=body.bytes_transferred,
        conflicts_detected=body.conflicts_detected,
        conflicts_resolved=body.conflicts_resolved,
        last_sync_cursor=body.last_sync_cursor,
        error_message=body.error_message,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Sync record not found")
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


@router.get("/sync")
async def list_sync_records(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    device_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List sync records with optional filters and pagination."""
    records, total = await EdgeRuntime.list_sync_records(
        session, device_id=device_id, status=status, limit=limit, offset=offset,
    )
    return {
        "data": [r.model_dump(mode="json") for r in records],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


# ── Fleet ───────────────────────────────────────────────────────────


@router.get("/fleet/status")
async def get_fleet_status(
    fleet_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get aggregate fleet status summary."""
    status = await EdgeRuntime.get_fleet_status(session, fleet_id=fleet_id)
    return {"data": status, "meta": _meta()}


@router.post("/fleet/configs", status_code=201)
async def create_fleet_config(
    body: CreateFleetConfigRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a fleet configuration profile."""
    config = await EdgeRuntime.create_fleet_config(
        session,
        name=body.name,
        description=body.description,
        target_device_type=body.target_device_type,
        sync_schedule=body.sync_schedule,
        sync_interval_seconds=body.sync_interval_seconds,
        conflict_strategy=body.conflict_strategy,
        default_inference_backend=body.default_inference_backend,
        default_quantization=body.default_quantization,
        max_offline_hours=body.max_offline_hours,
        auto_decommission=body.auto_decommission,
        config=body.config,
        created_by=body.created_by,
    )
    return {"data": config.model_dump(mode="json"), "meta": _meta()}


@router.get("/fleet/configs")
async def list_fleet_configs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List fleet configurations with pagination."""
    configs, total = await EdgeRuntime.list_fleet_configs(
        session, limit=limit, offset=offset,
    )
    return {
        "data": [c.model_dump(mode="json") for c in configs],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/fleet/configs/{fleet_config_id}")
async def get_fleet_config(
    fleet_config_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single fleet configuration by ID."""
    config = await EdgeRuntime.get_fleet_config(session, fleet_config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Fleet config not found")
    return {"data": config.model_dump(mode="json"), "meta": _meta()}


# ── Enterprise Edge Routes (Auth + RBAC + Tenant-scoped) ────────────


class OTAPushRequest(BaseModel):
    """Payload for pushing OTA update to multiple devices."""

    device_ids: list[UUID]
    version: str
    binary_url: str
    checksum: str
    release_notes: str = ""
    rollout_strategy: str = "canary"


@router.post("/devices", status_code=201)
async def enterprise_register_device(
    body: DeviceRegistration,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Register an edge device (enterprise, authenticated)."""
    if not check_permission(user, "edge", "create"):
        raise HTTPException(status_code=403, detail="Permission denied")

    device = await EdgeService.register_device(
        user.tenant_id, user, body, session=session, secrets_manager=secrets,
    )
    return {"data": device.model_dump(mode="json"), "meta": _meta()}


@router.post("/devices/{device_id}/token", status_code=201)
async def enterprise_provision_token(
    device_id: UUID,
    body: OfflineTokenConfig,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Provision an offline token for a device (enterprise, authenticated)."""
    if not check_permission(user, "edge", "create"):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        token = await EdgeService.provision_offline_token(
            user.tenant_id, user, device_id, body, session=session, secrets_manager=secrets,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": token.model_dump(mode="json"), "meta": _meta()}


@router.post("/devices/{device_id}/secrets", status_code=201)
async def enterprise_provision_secrets(
    device_id: UUID,
    body: SecretsManifest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> dict[str, Any]:
    """Provision local secrets bundle for a device (enterprise, authenticated)."""
    if not check_permission(user, "edge", "create"):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        bundle = await EdgeService.provision_local_secrets(
            user.tenant_id, device_id, body,
            session=session, secrets_manager=secrets, user=user,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": bundle.model_dump(mode="json"), "meta": _meta()}


@router.post("/devices/{device_id}/sync")
async def enterprise_sync_device(
    device_id: UUID,
    body: SyncPayload,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Bi-directional delta sync for a device (enterprise, authenticated)."""
    if not check_permission(user, "edge", "update"):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        result = await EdgeService.sync_device(
            user.tenant_id, device_id, body, session=session,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.get("/devices/{device_id}/status")
async def enterprise_device_status(
    device_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get device health, last sync, and storage usage (enterprise, authenticated)."""
    if not check_permission(user, "edge", "read"):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        status = await EdgeService.get_device_status(
            user.tenant_id, device_id, session=session,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": status.model_dump(mode="json"), "meta": _meta()}


@router.get("/fleet")
async def enterprise_list_fleet(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all devices in the tenant fleet (enterprise, authenticated)."""
    if not check_permission(user, "edge", "read"):
        raise HTTPException(status_code=403, detail="Permission denied")

    devices = await EdgeService.list_fleet(
        user.tenant_id, session=session, limit=limit, offset=offset,
    )
    return {
        "data": [d.model_dump(mode="json") for d in devices],
        "meta": _meta(pagination={"total": len(devices), "limit": limit, "offset": offset}),
    }


@router.post("/devices/{device_id}/command", status_code=201)
async def enterprise_remote_command(
    device_id: UUID,
    body: RemoteCommand,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Send a remote command to a device (enterprise, authenticated)."""
    if not check_permission(user, "edge", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        result = await EdgeService.send_remote_command(
            user.tenant_id, user, device_id, body.command,
            session=session, args=body.args,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/ota", status_code=201)
async def enterprise_push_ota(
    body: OTAPushRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Push OTA update to devices (enterprise, authenticated)."""
    if not check_permission(user, "edge", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied")

    update = OTAUpdate(
        version=body.version,
        binary_url=body.binary_url,
        checksum=body.checksum,
        release_notes=body.release_notes,
        rollout_strategy=body.rollout_strategy,
    )
    try:
        rollout = await EdgeService.push_ota_update(
            user.tenant_id, user, body.device_ids, update, session=session,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": rollout.model_dump(mode="json"), "meta": _meta()}


@router.delete("/devices/{device_id}", status_code=204, response_class=Response)
async def enterprise_revoke_device(
    device_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Revoke all tokens and secrets for a device (enterprise, authenticated)."""
    if not check_permission(user, "edge", "delete"):
        raise HTTPException(status_code=403, detail="Permission denied")

    try:
        await EdgeService.revoke_device(
            user.tenant_id, user, device_id, session=session,
        )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(status_code=204)


@router.get("/analytics")
async def enterprise_fleet_analytics(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get aggregated fleet metrics (enterprise, authenticated)."""
    if not check_permission(user, "edge", "read"):
        raise HTTPException(status_code=403, detail="Permission denied")

    analytics = await EdgeService.get_fleet_analytics(
        user.tenant_id, session=session,
    )
    return {"data": analytics.model_dump(mode="json"), "meta": _meta()}
