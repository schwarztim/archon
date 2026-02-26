"""SQLModel database models for Archon edge runtime management."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class EdgeDevice(SQLModel, table=True):
    """Registered edge device in the Archon fleet."""

    __tablename__ = "edge_devices"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    device_type: str = Field(default="generic", index=True)
    # generic | tablet | laptop | server | gateway
    status: str = Field(default="pending", index=True)
    # pending | online | offline | degraded | decommissioned

    # Hardware / capability profile
    architecture: str = Field(default="x86_64")  # x86_64 | aarch64
    cpu_cores: int = Field(default=4)
    memory_mb: int = Field(default=8192)
    disk_mb: int = Field(default=51200)
    has_gpu: bool = Field(default=False)
    gpu_model: str | None = Field(default=None)

    # Network / location
    ip_address: str | None = Field(default=None)
    location: str | None = Field(default=None)
    region: str | None = Field(default=None, index=True)

    # Authentication
    device_fingerprint: str | None = Field(default=None, unique=True, index=True)
    certificate_thumbprint: str | None = Field(default=None)

    # Fleet assignment
    fleet_id: UUID | None = Field(default=None, index=True)

    # Arbitrary device metadata
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    last_heartbeat_at: datetime | None = Field(default=None)
    registered_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class EdgeModelDeployment(SQLModel, table=True):
    """Tracks a model deployed to an edge device for local inference."""

    __tablename__ = "edge_model_deployments"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    device_id: UUID = Field(foreign_key="edge_devices.id", index=True)

    model_name: str = Field(index=True)
    model_version: str = Field(default="latest")
    inference_backend: str = Field(default="ollama")
    # ollama | vllm | onnx

    quantization: str | None = Field(default=None)
    # 4bit | 8bit | fp16 | None (full precision)

    status: str = Field(default="pending", index=True)
    # pending | downloading | ready | failed | removed

    size_mb: int = Field(default=0)
    download_progress: float = Field(default=0.0)  # 0.0–1.0

    config: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    deployed_by: UUID | None = Field(default=None, foreign_key="users.id")
    deployed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class EdgeSyncRecord(SQLModel, table=True):
    """Tracks bi-directional sync operations between edge and central."""

    __tablename__ = "edge_sync_records"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    device_id: UUID = Field(foreign_key="edge_devices.id", index=True)

    direction: str = Field(default="up", index=True)  # up | down | bidirectional
    status: str = Field(default="pending", index=True)
    # pending | in_progress | completed | failed | conflict

    sync_type: str = Field(default="delta")  # full | delta
    conflict_strategy: str = Field(default="last_write_wins")
    # last_write_wins | merge | manual_review

    # Payload stats
    records_sent: int = Field(default=0)
    records_received: int = Field(default=0)
    bytes_transferred: int = Field(default=0)
    conflicts_detected: int = Field(default=0)
    conflicts_resolved: int = Field(default=0)

    # Delta tracking
    last_sync_cursor: str | None = Field(default=None)

    error_message: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )
    details: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)


class FleetConfig(SQLModel, table=True):
    """Configuration profile for a fleet of edge devices."""

    __tablename__ = "fleet_configs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: str | None = Field(
        default=None, sa_column=Column(SAText, nullable=True)
    )

    # Deployment profile
    target_device_type: str = Field(default="generic")
    sync_schedule: str = Field(default="periodic")
    # immediate | periodic | manual
    sync_interval_seconds: int = Field(default=300)
    conflict_strategy: str = Field(default="last_write_wins")

    # Model defaults for the fleet
    default_inference_backend: str = Field(default="ollama")
    default_quantization: str | None = Field(default=None)

    # Policy
    max_offline_hours: int = Field(default=72)
    auto_decommission: bool = Field(default=False)

    # Arbitrary fleet configuration
    config: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )

    created_by: UUID | None = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ── Pydantic API schemas (non-table) ────────────────────────────────

from pydantic import BaseModel as PydanticBase  # noqa: E402
from pydantic import Field as PField  # noqa: E402


class DeviceRegistration(PydanticBase):
    """Request schema for registering an edge device."""

    device_name: str
    platform: str = "linux"
    hardware_id: str
    capabilities: dict[str, Any] = PField(default_factory=dict)
    location: str | None = None
    architecture: str = "x86_64"
    cpu_cores: int = PField(default=4, ge=1)
    memory_mb: int = PField(default=8192, ge=512)
    disk_mb: int = PField(default=51200, ge=1024)
    has_gpu: bool = False
    gpu_model: str | None = None


class EdgeDeviceResponse(PydanticBase):
    """Response schema for an edge device."""

    id: UUID
    tenant_id: str
    device_name: str
    platform: str
    status: str
    last_sync: datetime | None = None
    firmware_version: str = "1.0.0"
    hardware_id: str | None = None
    location: str | None = None
    region: str | None = None
    created_at: datetime
    updated_at: datetime


class OfflineTokenConfig(PydanticBase):
    """Configuration for offline token provisioning."""

    ttl_days: int = PField(default=30, ge=7, le=90)
    permissions_snapshot: list[str] = PField(default_factory=list)
    allowed_agents: list[str] = PField(default_factory=list)


class OfflineToken(PydanticBase):
    """Response schema for a provisioned offline token."""

    token: str
    device_id: UUID
    expires_at: datetime
    permissions_snapshot: list[str] = PField(default_factory=list)
    allowed_agents: list[str] = PField(default_factory=list)
    encryption_key_id: str = ""


class SecretsManifest(PydanticBase):
    """Request schema for provisioning local secrets."""

    secret_paths: list[str]
    ttl_hours: int = PField(default=24, ge=1, le=720)


class LocalSecretsBundle(PydanticBase):
    """Response schema for encrypted local secrets bundle."""

    device_id: UUID
    encrypted_secrets: str
    encryption_key_id: str
    expires_at: datetime
    secret_count: int = 0


class SyncPayload(PydanticBase):
    """Request schema for bi-directional sync."""

    device_id: UUID
    local_changes: list[dict[str, Any]] = PField(default_factory=list)
    last_sync_checkpoint: str | None = None
    storage_stats: dict[str, Any] = PField(default_factory=dict)


class SyncConflict(PydanticBase):
    """A single sync conflict record."""

    resource_type: str
    resource_id: str
    local_version: str
    central_version: str
    resolution: str = "pending"


class SyncResult(PydanticBase):
    """Response schema for a sync operation."""

    processed: int = 0
    conflicts: list[SyncConflict] = PField(default_factory=list)
    new_data_from_central: list[dict[str, Any]] = PField(default_factory=list)
    next_checkpoint: str = ""
    crl_entries: list[str] = PField(default_factory=list)


class DeviceStatus(PydanticBase):
    """Response schema for device status."""

    device_id: UUID
    online: bool = False
    last_heartbeat: datetime | None = None
    storage_used_mb: int = 0
    storage_total_mb: int = 0
    battery_pct: float | None = None
    active_agents: list[str] = PField(default_factory=list)
    firmware_version: str = "1.0.0"
    last_sync: datetime | None = None


class OTAUpdate(PydanticBase):
    """Request schema for OTA update push."""

    version: str
    binary_url: str
    checksum: str
    release_notes: str = ""
    rollout_strategy: str = "canary"


class UpdateRollout(PydanticBase):
    """Response schema for an OTA update rollout."""

    update_id: UUID
    devices: list[UUID]
    status: str = "pending"
    progress_pct: float = 0.0
    version: str = ""


class RemoteCommand(PydanticBase):
    """Request schema for remote device command."""

    command: str
    args: dict[str, Any] = PField(default_factory=dict)


class CommandResult(PydanticBase):
    """Response schema for a remote command execution."""

    device_id: UUID
    command: str
    status: str = "queued"
    output: str = ""


class FleetAnalytics(PydanticBase):
    """Response schema for fleet analytics."""

    total_devices: int = 0
    online: int = 0
    offline: int = 0
    degraded: int = 0
    avg_sync_interval_seconds: float = 0.0
    total_executions: int = 0
    total_model_deployments: int = 0
    devices_by_platform: dict[str, int] = PField(default_factory=dict)


__all__ = [
    "EdgeDevice",
    "EdgeModelDeployment",
    "EdgeSyncRecord",
    "FleetConfig",
    "DeviceRegistration",
    "EdgeDeviceResponse",
    "OfflineToken",
    "OfflineTokenConfig",
    "SecretsManifest",
    "LocalSecretsBundle",
    "SyncPayload",
    "SyncResult",
    "SyncConflict",
    "DeviceStatus",
    "OTAUpdate",
    "UpdateRollout",
    "RemoteCommand",
    "CommandResult",
    "FleetAnalytics",
]
