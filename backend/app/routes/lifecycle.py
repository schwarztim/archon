"""API routes for Archon lifecycle management."""

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
from app.models.lifecycle import (
    CronSchedule,
    DeploymentStrategy,
    DeploymentStrategyType,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.lifecycle import LifecycleManager
from app.services.lifecycle_service import LifecycleService

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


# ── Request / response schemas ──────────────────────────────────────


class DeployRequest(BaseModel):
    """Payload for deploying an agent version."""

    agent_id: UUID
    version_id: UUID
    environment: str = "staging"
    strategy: str = "rolling"
    replicas: int = PField(default=1, ge=1, le=100)
    min_replicas: int = PField(default=1, ge=1)
    max_replicas: int = PField(default=10, ge=1)
    error_rate_threshold: float = PField(default=0.05, ge=0.0, le=1.0)
    config: dict[str, Any] = PField(default_factory=dict)
    deployed_by: UUID | None = None


class PromoteCanaryRequest(BaseModel):
    """Payload for promoting canary traffic."""

    traffic_percentage: int = PField(ge=0, le=100)


class ScaleRequest(BaseModel):
    """Payload for scaling a deployment."""

    replicas: int = PField(ge=0)


class RollbackRequest(BaseModel):
    """Payload for rolling back a deployment."""

    reason: str = "manual rollback"
    actor_id: UUID | None = None


class RetireRequest(BaseModel):
    """Payload for retiring a deployment."""

    reason: str = "retirement"
    actor_id: UUID | None = None


class HealthCheckRequest(BaseModel):
    """Payload for recording a health check."""

    status: str = "healthy"
    health_score: float = PField(default=1.0, ge=0.0, le=1.0)
    error_rate: float = PField(default=0.0, ge=0.0, le=1.0)
    avg_latency_ms: float = PField(default=0.0, ge=0.0)
    p95_latency_ms: float = PField(default=0.0, ge=0.0)
    request_count: int = PField(default=0, ge=0)
    details: dict[str, Any] = PField(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Deployments ─────────────────────────────────────────────────────


@router.post("/deployments", status_code=201)
async def create_deployment(
    body: DeployRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Deploy an agent version to an environment."""
    record = await LifecycleManager.deploy(
        session,
        agent_id=body.agent_id,
        version_id=body.version_id,
        environment=body.environment,
        strategy=body.strategy,
        replicas=body.replicas,
        min_replicas=body.min_replicas,
        max_replicas=body.max_replicas,
        error_rate_threshold=body.error_rate_threshold,
        config=body.config,
        deployed_by=body.deployed_by,
    )
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


@router.get("/deployments")
async def list_deployments(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    agent_id: UUID | None = Query(default=None),
    environment: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List deployments with optional filters and pagination."""
    records, total = await LifecycleManager.list_deployments(
        session,
        agent_id=agent_id,
        environment=environment,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [r.model_dump(mode="json") for r in records],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


@router.get("/deployments/{deployment_id}")
async def get_deployment(
    deployment_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get a single deployment by ID."""
    record = await LifecycleManager.get_deployment(session, deployment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


# ── Deployment actions ──────────────────────────────────────────────


@router.post("/deployments/{deployment_id}/promote")
async def promote_canary(
    deployment_id: UUID,
    body: PromoteCanaryRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Promote canary deployment to a higher traffic percentage."""
    record = await LifecycleManager.promote_canary(
        session, deployment_id, traffic_percentage=body.traffic_percentage,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


@router.post("/deployments/{deployment_id}/scale")
async def scale_deployment(
    deployment_id: UUID,
    body: ScaleRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Scale a deployment to the requested replica count."""
    record = await LifecycleManager.scale(
        session, deployment_id, replicas=body.replicas,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


@router.post("/deployments/{deployment_id}/rollback")
async def rollback_deployment(
    deployment_id: UUID,
    body: RollbackRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Roll back a deployment to its predecessor."""
    record = await LifecycleManager.rollback(
        session,
        deployment_id,
        reason=body.reason,
        actor_id=body.actor_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


@router.post("/deployments/{deployment_id}/retire")
async def retire_deployment(
    deployment_id: UUID,
    body: RetireRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Retire a deployment permanently."""
    record = await LifecycleManager.retire(
        session,
        deployment_id,
        reason=body.reason,
        actor_id=body.actor_id,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"data": record.model_dump(mode="json"), "meta": _meta()}


# ── Health checks ───────────────────────────────────────────────────


@router.post("/deployments/{deployment_id}/health", status_code=201)
async def record_health_check(
    deployment_id: UUID,
    body: HealthCheckRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Record a health check for a deployment."""
    check = await LifecycleManager.record_health_check(
        session,
        deployment_id=deployment_id,
        status=body.status,
        health_score=body.health_score,
        error_rate=body.error_rate,
        avg_latency_ms=body.avg_latency_ms,
        p95_latency_ms=body.p95_latency_ms,
        request_count=body.request_count,
        details=body.details,
    )
    if check is None:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return {"data": check.model_dump(mode="json"), "meta": _meta()}


@router.get("/deployments/{deployment_id}/health")
async def list_health_checks(
    deployment_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List health checks for a deployment."""
    checks, total = await LifecycleManager.list_health_checks(
        session, deployment_id, limit=limit, offset=offset,
    )
    return {
        "data": [c.model_dump(mode="json") for c in checks],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


# ── Lifecycle events ────────────────────────────────────────────────


@router.get("/events")
async def list_events(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    deployment_id: UUID | None = Query(default=None),
    agent_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List lifecycle events with optional filters."""
    events, total = await LifecycleManager.list_events(
        session,
        deployment_id=deployment_id,
        agent_id=agent_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return {
        "data": [e.model_dump(mode="json") for e in events],
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


# ═══════════════════════════════════════════════════════════════════════
# Enterprise lifecycle endpoints — auth, RBAC, tenant-scoped, audited
# ═══════════════════════════════════════════════════════════════════════

enterprise_router = APIRouter(
    prefix="/api/v1/agents",
    tags=["lifecycle-enterprise"],
)


# ── Enterprise request schemas ──────────────────────────────────────


class TransitionRequest(BaseModel):
    """Payload for a lifecycle state transition."""

    target_state: str
    reason: str | None = None


class EnterpriseDeployRequest(BaseModel):
    """Payload for enterprise deployment."""

    strategy_type: DeploymentStrategyType = DeploymentStrategyType.ROLLING
    canary_percentage: int = PField(default=5, ge=0, le=100)
    rollback_threshold: float = PField(default=0.05, ge=0.0, le=1.0)
    target_env: str = "staging"
    version_id: UUID | None = None


class EnterpriseRollbackRequest(BaseModel):
    """Payload for enterprise rollback."""

    reason: str = "manual rollback"


class ScheduleRequest(BaseModel):
    """Payload for scheduling an agent execution."""

    expression: str
    timezone: str = "UTC"
    enabled: bool = True


# ── Helpers ─────────────────────────────────────────────────────────


def _user_dict(user: AuthenticatedUser) -> dict[str, Any]:
    """Convert AuthenticatedUser to dict for service layer."""
    return {
        "id": user.id,
        "email": user.email,
        "tenant_id": user.tenant_id,
        "roles": user.roles,
    }


# ── Enterprise routes ───────────────────────────────────────────────


@enterprise_router.post("/{agent_id}/lifecycle/transition", status_code=200)
async def enterprise_transition(
    agent_id: UUID,
    body: TransitionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Transition an agent through the lifecycle state machine."""
    if not check_permission(user, "agents", "update"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:update")

    try:
        result = await LifecycleService.transition(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            agent_id=agent_id,
            target_state=body.target_state,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@enterprise_router.post("/{agent_id}/deploy", status_code=201)
async def enterprise_deploy(
    agent_id: UUID,
    body: EnterpriseDeployRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Deploy an agent with a specified strategy."""
    if not check_permission(user, "agents", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:execute")

    strategy = DeploymentStrategy(
        type=body.strategy_type,
        canary_percentage=body.canary_percentage,
        rollback_threshold=body.rollback_threshold,
    )

    try:
        result = await LifecycleService.deploy(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            agent_id=agent_id,
            strategy=strategy,
            target_env=body.target_env,
            version_id=body.version_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


rollback_router = APIRouter(
    prefix="/api/v1/deployments",
    tags=["lifecycle-enterprise"],
)


@rollback_router.post("/{deployment_id}/rollback", status_code=200)
async def enterprise_rollback(
    deployment_id: UUID,
    body: EnterpriseRollbackRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Roll back a deployment."""
    if not check_permission(user, "agents", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:execute")

    try:
        result = await LifecycleService.rollback_deployment(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            deployment_id=deployment_id,
            reason=body.reason,
        )
    except (ValueError, PermissionError) as exc:
        status_code = 403 if isinstance(exc, PermissionError) else 404
        raise HTTPException(status_code=status_code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@enterprise_router.get("/{agent_id}/health", status_code=200)
async def enterprise_health(
    agent_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Compute the health score for an agent."""
    if not check_permission(user, "agents", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:read")

    result = await LifecycleService.compute_health_score(
        tenant_id=user.tenant_id,
        agent_id=agent_id,
    )
    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@enterprise_router.get("/{agent_id}/anomalies", status_code=200)
async def enterprise_anomalies(
    agent_id: UUID,
    window_hours: int = Query(default=24, ge=1, le=720),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Detect anomalies in agent metrics."""
    if not check_permission(user, "agents", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:read")

    results = await LifecycleService.detect_anomalies(
        tenant_id=user.tenant_id,
        agent_id=agent_id,
        window_hours=window_hours,
    )
    return {
        "data": [a.model_dump(mode="json") for a in results],
        "meta": _meta(),
    }


@enterprise_router.post("/{agent_id}/schedule", status_code=201)
async def enterprise_schedule(
    agent_id: UUID,
    body: ScheduleRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Schedule recurring agent executions."""
    if not check_permission(user, "agents", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:execute")

    schedule = CronSchedule(
        expression=body.expression,
        timezone=body.timezone,
        enabled=body.enabled,
    )

    try:
        result = await LifecycleService.schedule_execution(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            agent_id=agent_id,
            schedule=schedule,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


schedules_router = APIRouter(
    prefix="/api/v1",
    tags=["lifecycle-enterprise"],
)


@schedules_router.get("/schedules", status_code=200)
async def enterprise_list_schedules(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List all scheduled jobs for the authenticated tenant."""
    if not check_permission(user, "agents", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:read")

    results = await LifecycleService.list_scheduled_jobs(
        tenant_id=user.tenant_id,
    )
    return {
        "data": [j.model_dump(mode="json") for j in results],
        "meta": _meta(),
    }


# ═══════════════════════════════════════════════════════════════════════
# Lifecycle v1 endpoints — pipeline, environments, health, gates
# ═══════════════════════════════════════════════════════════════════════

lifecycle_v1_router = APIRouter(
    prefix="/lifecycle",
    tags=["lifecycle-v1"],
)


# ── Request schemas ─────────────────────────────────────────────────


class EnhancedDeployRequest(BaseModel):
    """Enhanced deployment request with strategy details."""

    agent_id: UUID
    version_id: UUID
    environment: str = "staging"
    strategy_type: str = "rolling"
    replicas: int = PField(default=2, ge=1, le=100)
    canary_percentage: int = PField(default=10, ge=0, le=100)
    blue_green_preview: bool = False
    rollback_threshold: float = PField(default=0.05, ge=0.0, le=1.0)
    pre_deploy_checks: bool = True
    config: dict[str, Any] = PField(default_factory=dict)


class GatesConfigRequest(BaseModel):
    """Request to configure approval gates."""

    gates: list[dict[str, Any]]


# ── Enhanced deploy ─────────────────────────────────────────────────


@lifecycle_v1_router.post("/deploy", status_code=201)
async def enhanced_deploy(
    body: EnhancedDeployRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Deploy an agent with enhanced strategy configuration."""
    if not check_permission(user, "agents", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:execute")

    strategy_map: dict[str, DeploymentStrategyType] = {
        "rolling": DeploymentStrategyType.ROLLING,
        "blue_green": DeploymentStrategyType.BLUE_GREEN,
        "blue-green": DeploymentStrategyType.BLUE_GREEN,
        "canary": DeploymentStrategyType.CANARY,
        "shadow": DeploymentStrategyType.SHADOW,
    }
    strategy_type = strategy_map.get(body.strategy_type, DeploymentStrategyType.ROLLING)

    strategy = DeploymentStrategy(
        type=strategy_type,
        canary_percentage=body.canary_percentage,
        rollback_threshold=body.rollback_threshold,
    )

    try:
        result = await LifecycleService.deploy(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            agent_id=body.agent_id,
            strategy=strategy,
            target_env=body.environment,
            version_id=body.version_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ── Promote / Demote ────────────────────────────────────────────────


@lifecycle_v1_router.post("/promote/{deployment_id}", status_code=200)
async def promote_deployment(
    deployment_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Promote a deployment to the next pipeline stage."""
    if not check_permission(user, "agents", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:execute")

    try:
        result = await LifecycleService.promote_to_next_stage(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            deployment_id=deployment_id,
        )
    except (ValueError, PermissionError) as exc:
        status_code = 403 if isinstance(exc, PermissionError) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@lifecycle_v1_router.post("/demote/{deployment_id}", status_code=200)
async def demote_deployment(
    deployment_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Demote a deployment to the previous pipeline stage."""
    if not check_permission(user, "agents", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:execute")

    try:
        result = await LifecycleService.demote_to_previous_stage(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            deployment_id=deployment_id,
        )
    except (ValueError, PermissionError) as exc:
        status_code = 403 if isinstance(exc, PermissionError) else 400
        raise HTTPException(status_code=status_code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ── Rollback ────────────────────────────────────────────────────────


@lifecycle_v1_router.post("/rollback/{deployment_id}", status_code=200)
async def rollback_v1(
    deployment_id: UUID,
    body: EnterpriseRollbackRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Roll back a deployment."""
    if not check_permission(user, "agents", "execute"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:execute")

    try:
        result = await LifecycleService.rollback_deployment(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            deployment_id=deployment_id,
            reason=body.reason,
        )
    except (ValueError, PermissionError) as exc:
        status_code = 403 if isinstance(exc, PermissionError) else 404
        raise HTTPException(status_code=status_code, detail=str(exc))

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


# ── Pipeline view ───────────────────────────────────────────────────


@lifecycle_v1_router.get("/pipeline", status_code=200)
async def get_pipeline(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get all pipeline stages with deployed versions."""
    if not check_permission(user, "agents", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:read")

    stages = await LifecycleService.get_pipeline(
        tenant_id=user.tenant_id,
    )
    return {
        "data": [s.model_dump(mode="json") for s in stages],
        "meta": _meta(),
    }


# ── Environments ────────────────────────────────────────────────────


@lifecycle_v1_router.get("/environments", status_code=200)
async def list_environments(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List all environments with health and deployment info."""
    if not check_permission(user, "agents", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:read")

    envs = await LifecycleService.list_environments(
        tenant_id=user.tenant_id,
    )
    return {
        "data": [e.model_dump(mode="json") for e in envs],
        "meta": _meta(),
    }


# ── Config diff ─────────────────────────────────────────────────────


@lifecycle_v1_router.get("/diff", status_code=200)
async def config_diff(
    source: str = Query(description="Source environment"),
    target: str = Query(description="Target environment"),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Compare configuration between two environments."""
    if not check_permission(user, "agents", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:read")

    diff = await LifecycleService.get_config_diff(
        tenant_id=user.tenant_id,
        source_env=source,
        target_env=target,
    )
    return {"data": diff.model_dump(mode="json"), "meta": _meta()}


# ── Deployment history ──────────────────────────────────────────────


@lifecycle_v1_router.get("/history/{environment}", status_code=200)
async def deployment_history(
    environment: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get deployment history timeline for an environment."""
    if not check_permission(user, "agents", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:read")

    entries = await LifecycleService.get_deployment_history(
        tenant_id=user.tenant_id,
        environment=environment,
    )
    return {
        "data": [e.model_dump(mode="json") for e in entries],
        "meta": _meta(),
    }


# ── Approval gates ─────────────────────────────────────────────────


@lifecycle_v1_router.put("/gates", status_code=200)
async def configure_gates(
    body: GatesConfigRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Configure approval gates between pipeline stages."""
    if not check_permission(user, "agents", "update"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:update")

    try:
        gates = await LifecycleService.configure_gates(
            tenant_id=user.tenant_id,
            user=_user_dict(user),
            gates=body.gates,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    return {
        "data": [g.model_dump(mode="json") for g in gates],
        "meta": _meta(),
    }


# ── Post-deployment health ──────────────────────────────────────────


@lifecycle_v1_router.get("/health/{deployment_id}", status_code=200)
async def deployment_health(
    deployment_id: UUID,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get post-deployment health metrics."""
    if not check_permission(user, "agents", "read"):
        raise HTTPException(status_code=403, detail="Permission denied: agents:read")

    try:
        health = await LifecycleService.get_deployment_health(
            tenant_id=user.tenant_id,
            deployment_id=deployment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {"data": health.model_dump(mode="json"), "meta": _meta()}
