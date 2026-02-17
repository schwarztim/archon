"""SQLModel database models for Archon lifecycle management."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field as PydanticField
from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class DeploymentRecord(SQLModel, table=True):
    """Tracks a deployment of an agent version to an environment."""

    __tablename__ = "deployment_records"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    agent_id: UUID = Field(foreign_key="agents.id", index=True)
    version_id: UUID = Field(foreign_key="agent_versions.id", index=True)

    # Deployment configuration
    environment: str = Field(default="staging", index=True)  # staging | production
    strategy: str = Field(default="rolling")  # canary | blue_green | rolling
    status: str = Field(default="pending", index=True)
    # pending | deploying | active | rolling_back | rolled_back | retired

    # Canary / traffic split
    traffic_percentage: int = Field(default=0)  # 0–100
    error_rate_threshold: float = Field(default=0.05)  # auto-rollback trigger

    # Replica / scaling
    replicas: int = Field(default=1)
    min_replicas: int = Field(default=1)
    max_replicas: int = Field(default=10)

    # Rollback reference
    previous_deployment_id: UUID | None = Field(default=None, index=True)

    # Arbitrary metadata (resource limits, env vars, etc.)
    config: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    deployed_by: UUID | None = Field(default=None, foreign_key="users.id")
    deployed_at: datetime | None = Field(default=None)
    retired_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class HealthCheck(SQLModel, table=True):
    """Point-in-time health snapshot for a deployment."""

    __tablename__ = "health_checks"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    deployment_id: UUID = Field(foreign_key="deployment_records.id", index=True)

    status: str = Field(default="healthy")  # healthy | degraded | unhealthy
    health_score: float = Field(default=1.0)  # 0.0–1.0 composite score
    error_rate: float = Field(default=0.0)  # 0.0–1.0
    avg_latency_ms: float = Field(default=0.0)
    p95_latency_ms: float = Field(default=0.0)
    request_count: int = Field(default=0)

    # Optional details (per-check breakdown, user satisfaction, etc.)
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    checked_at: datetime = Field(default_factory=_utcnow)


class LifecycleEvent(SQLModel, table=True):
    """Immutable audit log for lifecycle state transitions."""

    __tablename__ = "lifecycle_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    deployment_id: UUID = Field(foreign_key="deployment_records.id", index=True)
    agent_id: UUID = Field(foreign_key="agents.id", index=True)

    event_type: str = Field(index=True)
    # created | deployed | scaled | health_changed | rolled_back | retired | error
    from_state: str | None = Field(default=None)
    to_state: str | None = Field(default=None)

    message: str | None = Field(default=None, sa_column=Column(SAText, nullable=True))
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    actor_id: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)


# ── Pydantic API models (not DB tables) ─────────────────────────────


class LifecycleTransition(BaseModel):
    """Result of a lifecycle state transition."""

    agent_id: UUID
    from_state: str
    to_state: str
    transitioned_by: str
    reason: str | None = None
    transitioned_at: datetime = PydanticField(default_factory=_utcnow)


class DeploymentStrategyType(str, Enum):
    """Supported deployment strategies."""

    CANARY = "canary"
    BLUE_GREEN = "blue_green"
    ROLLING = "rolling"
    SHADOW = "shadow"


class DeploymentStrategy(BaseModel):
    """Configuration for a deployment strategy."""

    type: DeploymentStrategyType = DeploymentStrategyType.ROLLING
    canary_percentage: int = PydanticField(default=5, ge=0, le=100)
    rollback_threshold: float = PydanticField(default=0.05, ge=0.0, le=1.0)


class Deployment(BaseModel):
    """API representation of a deployment."""

    id: UUID
    agent_id: UUID
    version_id: UUID
    environment: str
    strategy: DeploymentStrategy
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CredentialRotationResult(BaseModel):
    """Result of credential rotation on environment promotion."""

    agent_id: UUID
    secrets_rotated: int
    old_leases_revoked: int
    new_lease_ids: list[str] = PydanticField(default_factory=list)


class HealthScore(BaseModel):
    """Composite health score for an agent."""

    agent_id: UUID
    overall: float = PydanticField(ge=0.0, le=1.0)
    success_rate: float = PydanticField(ge=0.0, le=1.0)
    avg_latency: float = PydanticField(ge=0.0)
    error_rate: float = PydanticField(ge=0.0, le=1.0)
    cost_score: float = PydanticField(ge=0.0, le=1.0)


class Anomaly(BaseModel):
    """An anomaly detected on agent metrics."""

    metric: str
    value: float
    expected_range: tuple[float, float]
    z_score: float
    severity: str  # low | medium | high | critical
    detected_at: datetime = PydanticField(default_factory=_utcnow)


class CronSchedule(BaseModel):
    """Cron-based schedule definition."""

    expression: str
    timezone: str = "UTC"
    enabled: bool = True
    next_run_at: datetime | None = None


class ScheduledJob(BaseModel):
    """A scheduled execution job for an agent."""

    id: UUID
    agent_id: UUID
    schedule: CronSchedule
    last_run: datetime | None = None
    next_run: datetime | None = None
    status: str = "active"  # active | paused | completed


class ApprovalGate(BaseModel):
    """Configuration for approval gates between pipeline stages."""

    from_stage: str
    to_stage: str
    required_approvers: int = PydanticField(default=1, ge=1)
    auto_approve_after_hours: float | None = None
    require_health_check: bool = True
    require_tests_pass: bool = True
    enabled: bool = True


class PipelineStageInfo(BaseModel):
    """A stage in the deployment pipeline with its deployed versions."""

    stage: str
    label: str
    deployments: list[dict[str, Any]] = PydanticField(default_factory=list)
    approval_gate: ApprovalGate | None = None


class EnvironmentInfo(BaseModel):
    """Summary of an environment's state."""

    name: str
    display_name: str
    status: str = "active"
    deployed_version: str | None = None
    agent_id: UUID | None = None
    agent_name: str | None = None
    health_status: str = "unknown"
    instance_count: int = 0
    last_deploy_at: datetime | None = None
    created_at: datetime = PydanticField(default_factory=_utcnow)


class ConfigDiff(BaseModel):
    """Comparison between two environment configurations."""

    source_env: str
    target_env: str
    differences: list[dict[str, Any]] = PydanticField(default_factory=list)
    source_version: str | None = None
    target_version: str | None = None


class DeploymentHistoryEntry(BaseModel):
    """A single entry in the deployment history timeline."""

    id: UUID
    agent_id: UUID
    agent_name: str | None = None
    version_id: str
    environment: str
    strategy: str
    status: str
    deployed_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    rollback_reason: str | None = None


class HealthMetrics(BaseModel):
    """Detailed post-deployment health metrics."""

    deployment_id: UUID
    status: str = "healthy"
    response_time_p50: float = 0.0
    response_time_p95: float = 0.0
    response_time_p99: float = 0.0
    error_rate: float = 0.0
    throughput_rps: float = 0.0
    uptime_pct: float = 100.0
    auto_rollback_triggered: bool = False
    auto_rollback_threshold: float = 0.05
    checked_at: datetime = PydanticField(default_factory=_utcnow)


__all__ = [
    "Anomaly",
    "ApprovalGate",
    "ConfigDiff",
    "CredentialRotationResult",
    "CronSchedule",
    "Deployment",
    "DeploymentHistoryEntry",
    "DeploymentRecord",
    "DeploymentStrategy",
    "DeploymentStrategyType",
    "EnvironmentInfo",
    "HealthCheck",
    "HealthMetrics",
    "HealthScore",
    "LifecycleEvent",
    "LifecycleTransition",
    "PipelineStageInfo",
    "ScheduledJob",
]
