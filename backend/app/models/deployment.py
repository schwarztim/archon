"""Pydantic models for the deployment infrastructure service."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class EnvironmentType(str, Enum):
    """Supported deployment environments."""

    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class ComponentStatus(str, Enum):
    """Health status for an individual component."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class DeploymentState(str, Enum):
    """Overall deployment state."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# ── Request / config models ─────────────────────────────────────────


class TLSConfig(BaseModel):
    """TLS configuration for a deployment."""

    enabled: bool = True
    cert_ttl: str = "720h"
    auto_rotate: bool = True


class ScalingConfig(BaseModel):
    """Scaling configuration per component."""

    min_replicas: int = Field(default=1, ge=1)
    max_replicas: int = Field(default=10, ge=1)
    target_cpu_percent: int = Field(default=70, ge=10, le=100)


class ComponentConfig(BaseModel):
    """Configuration for a single deployable component."""

    name: str
    image_tag: str = "latest"
    replicas: int = Field(default=1, ge=0)
    scaling: ScalingConfig = Field(default_factory=ScalingConfig)


class DeploymentConfig(BaseModel):
    """Full deployment configuration for an environment."""

    environment: EnvironmentType = EnvironmentType.STAGING
    version: str = "0.1.0"
    components: list[ComponentConfig] = Field(default_factory=list)
    scaling: ScalingConfig = Field(default_factory=ScalingConfig)
    tls_config: TLSConfig = Field(default_factory=TLSConfig)


# ── Response models ─────────────────────────────────────────────────


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    name: str
    status: ComponentStatus = ComponentStatus.UNKNOWN
    replicas: int = 0
    ready_replicas: int = 0
    message: str = ""


class EnvironmentDeployment(BaseModel):
    """Result of deploying an environment."""

    id: UUID = Field(default_factory=uuid4)
    tenant_id: str
    environment: EnvironmentType
    version: str
    status: DeploymentState = DeploymentState.PENDING
    components: list[ComponentHealth] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_utcnow)
    completed_at: datetime | None = None


class DeploymentStatus(BaseModel):
    """Current status of a deployment with component health."""

    deployment_id: UUID
    overall_status: DeploymentState
    component_statuses: list[ComponentHealth] = Field(default_factory=list)
    health_checks: dict[str, Any] = Field(default_factory=dict)


class ScaleResult(BaseModel):
    """Result of a horizontal scaling operation."""

    component: str
    previous_replicas: int
    new_replicas: int
    status: str = "scaled"


class InfraHealth(BaseModel):
    """Infrastructure health across all platform services."""

    vault_status: ComponentStatus = ComponentStatus.UNKNOWN
    keycloak_status: ComponentStatus = ComponentStatus.UNKNOWN
    db_status: ComponentStatus = ComponentStatus.UNKNOWN
    redis_status: ComponentStatus = ComponentStatus.UNKNOWN
    overall: ComponentStatus = ComponentStatus.UNKNOWN


class CertRotationResult(BaseModel):
    """Result of a TLS certificate rotation."""

    certificates_rotated: int = 0
    next_rotation: datetime | None = None
    errors: list[str] = Field(default_factory=list)


class BackupResult(BaseModel):
    """Result of a platform backup operation."""

    backup_id: UUID = Field(default_factory=uuid4)
    size_mb: float = 0.0
    components_backed_up: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0


class PlatformMetrics(BaseModel):
    """Aggregated platform metrics."""

    cpu_usage: float = Field(default=0.0, ge=0.0, le=100.0)
    memory_usage: float = Field(default=0.0, ge=0.0, le=100.0)
    request_rate: float = Field(default=0.0, ge=0.0)
    error_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    p50_latency: float = Field(default=0.0, ge=0.0)
    p99_latency: float = Field(default=0.0, ge=0.0)


__all__ = [
    "BackupResult",
    "CertRotationResult",
    "ComponentConfig",
    "ComponentHealth",
    "ComponentStatus",
    "DeploymentConfig",
    "DeploymentState",
    "DeploymentStatus",
    "EnvironmentDeployment",
    "EnvironmentType",
    "InfraHealth",
    "PlatformMetrics",
    "ScaleResult",
    "ScalingConfig",
    "TLSConfig",
]
