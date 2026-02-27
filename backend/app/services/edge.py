"""Edge runtime service for Archon — device registration, model deployment, sync, and fleet management."""

from __future__ import annotations

from datetime import datetime

from app.utils.time import utcnow as _utcnow
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.edge import EdgeDevice, EdgeModelDeployment, EdgeSyncRecord, FleetConfig


class EdgeRuntime:
    """Manages edge devices, local model deployments, sync, and fleet operations."""

    # ── Device Registration ─────────────────────────────────────────

    @staticmethod
    async def register_device(
        session: AsyncSession,
        *,
        name: str,
        device_type: str = "generic",
        architecture: str = "x86_64",
        cpu_cores: int = 4,
        memory_mb: int = 8192,
        disk_mb: int = 51200,
        has_gpu: bool = False,
        gpu_model: str | None = None,
        ip_address: str | None = None,
        location: str | None = None,
        region: str | None = None,
        device_fingerprint: str | None = None,
        certificate_thumbprint: str | None = None,
        fleet_id: UUID | None = None,
        extra_metadata: dict[str, Any] | None = None,
        registered_by: UUID | None = None,
    ) -> EdgeDevice:
        """Register a new edge device in the fleet.

        Creates the device record and sets its initial status to ``online``.
        """
        device = EdgeDevice(
            name=name,
            device_type=device_type,
            status="online",
            architecture=architecture,
            cpu_cores=cpu_cores,
            memory_mb=memory_mb,
            disk_mb=disk_mb,
            has_gpu=has_gpu,
            gpu_model=gpu_model,
            ip_address=ip_address,
            location=location,
            region=region,
            device_fingerprint=device_fingerprint,
            certificate_thumbprint=certificate_thumbprint,
            fleet_id=fleet_id,
            extra_metadata=extra_metadata or {},
            last_heartbeat_at=_utcnow(),
            registered_by=registered_by,
        )
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device

    # ── Update Device ───────────────────────────────────────────────

    @staticmethod
    async def update_device(
        session: AsyncSession,
        device_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        ip_address: str | None = None,
        location: str | None = None,
        region: str | None = None,
        fleet_id: UUID | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> EdgeDevice | None:
        """Update mutable fields on an edge device.

        Returns ``None`` if the device does not exist.
        """
        device = await session.get(EdgeDevice, device_id)
        if device is None:
            return None

        if name is not None:
            device.name = name
        if status is not None:
            device.status = status
        if ip_address is not None:
            device.ip_address = ip_address
        if location is not None:
            device.location = location
        if region is not None:
            device.region = region
        if fleet_id is not None:
            device.fleet_id = fleet_id
        if extra_metadata is not None:
            device.extra_metadata = extra_metadata

        device.updated_at = _utcnow()
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device

    # ── Get Device ──────────────────────────────────────────────────

    @staticmethod
    async def get_device(
        session: AsyncSession,
        device_id: UUID,
    ) -> EdgeDevice | None:
        """Return a single edge device by ID."""
        return await session.get(EdgeDevice, device_id)

    # ── List Devices ────────────────────────────────────────────────

    @staticmethod
    async def list_devices(
        session: AsyncSession,
        *,
        status: str | None = None,
        device_type: str | None = None,
        region: str | None = None,
        fleet_id: UUID | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[EdgeDevice], int]:
        """Return paginated edge devices with optional filters."""
        base = select(EdgeDevice)
        if status is not None:
            base = base.where(EdgeDevice.status == status)
        if device_type is not None:
            base = base.where(EdgeDevice.device_type == device_type)
        if region is not None:
            base = base.where(EdgeDevice.region == region)
        if fleet_id is not None:
            base = base.where(EdgeDevice.fleet_id == fleet_id)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                EdgeDevice.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    # ── Heartbeat ───────────────────────────────────────────────────

    @staticmethod
    async def heartbeat(
        session: AsyncSession,
        device_id: UUID,
        *,
        extra_metadata: dict[str, Any] | None = None,
    ) -> EdgeDevice | None:
        """Record a heartbeat from an edge device."""
        device = await session.get(EdgeDevice, device_id)
        if device is None:
            return None

        device.last_heartbeat_at = _utcnow()
        device.status = "online"
        if extra_metadata is not None:
            device.extra_metadata = extra_metadata
        device.updated_at = _utcnow()
        session.add(device)
        await session.commit()
        await session.refresh(device)
        return device

    # ── Model Deployment ────────────────────────────────────────────

    @staticmethod
    async def deploy_model(
        session: AsyncSession,
        *,
        device_id: UUID,
        model_name: str,
        model_version: str = "latest",
        inference_backend: str = "ollama",
        quantization: str | None = None,
        size_mb: int = 0,
        config: dict[str, Any] | None = None,
        deployed_by: UUID | None = None,
    ) -> EdgeModelDeployment | None:
        """Deploy a model to an edge device for local inference.

        Returns ``None`` if the target device does not exist.
        """
        device = await session.get(EdgeDevice, device_id)
        if device is None:
            return None

        deployment = EdgeModelDeployment(
            device_id=device_id,
            model_name=model_name,
            model_version=model_version,
            inference_backend=inference_backend,
            quantization=quantization,
            status="downloading",
            size_mb=size_mb,
            config=config or {},
            deployed_by=deployed_by,
            deployed_at=_utcnow(),
        )
        session.add(deployment)
        await session.commit()
        await session.refresh(deployment)
        return deployment

    # ── Model Deployment Queries ────────────────────────────────────

    @staticmethod
    async def get_model_deployment(
        session: AsyncSession,
        deployment_id: UUID,
    ) -> EdgeModelDeployment | None:
        """Return a single model deployment by ID."""
        return await session.get(EdgeModelDeployment, deployment_id)

    @staticmethod
    async def list_model_deployments(
        session: AsyncSession,
        *,
        device_id: UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[EdgeModelDeployment], int]:
        """Return paginated model deployments with optional filters."""
        base = select(EdgeModelDeployment)
        if device_id is not None:
            base = base.where(EdgeModelDeployment.device_id == device_id)
        if status is not None:
            base = base.where(EdgeModelDeployment.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                EdgeModelDeployment.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def update_model_deployment_status(
        session: AsyncSession,
        deployment_id: UUID,
        *,
        status: str,
        download_progress: float | None = None,
    ) -> EdgeModelDeployment | None:
        """Update the status of a model deployment."""
        deployment = await session.get(EdgeModelDeployment, deployment_id)
        if deployment is None:
            return None

        deployment.status = status
        if download_progress is not None:
            deployment.download_progress = download_progress
        deployment.updated_at = _utcnow()
        session.add(deployment)
        await session.commit()
        await session.refresh(deployment)
        return deployment

    # ── Sync Management ─────────────────────────────────────────────

    @staticmethod
    async def sync(
        session: AsyncSession,
        *,
        device_id: UUID,
        direction: str = "bidirectional",
        sync_type: str = "delta",
        conflict_strategy: str = "last_write_wins",
        last_sync_cursor: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> EdgeSyncRecord | None:
        """Initiate a sync operation for an edge device.

        Returns ``None`` if the target device does not exist.
        """
        device = await session.get(EdgeDevice, device_id)
        if device is None:
            return None

        record = EdgeSyncRecord(
            device_id=device_id,
            direction=direction,
            status="in_progress",
            sync_type=sync_type,
            conflict_strategy=conflict_strategy,
            last_sync_cursor=last_sync_cursor,
            details=details or {},
            started_at=_utcnow(),
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    @staticmethod
    async def complete_sync(
        session: AsyncSession,
        sync_id: UUID,
        *,
        status: str = "completed",
        records_sent: int = 0,
        records_received: int = 0,
        bytes_transferred: int = 0,
        conflicts_detected: int = 0,
        conflicts_resolved: int = 0,
        last_sync_cursor: str | None = None,
        error_message: str | None = None,
    ) -> EdgeSyncRecord | None:
        """Mark a sync operation as completed (or failed)."""
        record = await session.get(EdgeSyncRecord, sync_id)
        if record is None:
            return None

        record.status = status
        record.records_sent = records_sent
        record.records_received = records_received
        record.bytes_transferred = bytes_transferred
        record.conflicts_detected = conflicts_detected
        record.conflicts_resolved = conflicts_resolved
        if last_sync_cursor is not None:
            record.last_sync_cursor = last_sync_cursor
        if error_message is not None:
            record.error_message = error_message
        record.completed_at = _utcnow()

        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record

    @staticmethod
    async def list_sync_records(
        session: AsyncSession,
        *,
        device_id: UUID | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[EdgeSyncRecord], int]:
        """Return paginated sync records with optional filters."""
        base = select(EdgeSyncRecord)
        if device_id is not None:
            base = base.where(EdgeSyncRecord.device_id == device_id)
        if status is not None:
            base = base.where(EdgeSyncRecord.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                EdgeSyncRecord.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total

    # ── Fleet Operations ────────────────────────────────────────────

    @staticmethod
    async def get_fleet_status(
        session: AsyncSession,
        fleet_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Return an aggregate status summary for the fleet (or a specific fleet).

        Counts devices by status, plus totals for model deployments and
        recent sync records.
        """
        device_base = select(EdgeDevice)
        if fleet_id is not None:
            device_base = device_base.where(EdgeDevice.fleet_id == fleet_id)

        result = await session.exec(device_base)
        devices = list(result.all())

        status_counts: dict[str, int] = {}
        for d in devices:
            status_counts[d.status] = status_counts.get(d.status, 0) + 1

        device_ids = [d.id for d in devices]

        # Model deployment counts
        model_base = select(EdgeModelDeployment)
        if device_ids:
            model_base = model_base.where(
                EdgeModelDeployment.device_id.in_(device_ids)  # type: ignore[union-attr]
            )
        model_result = await session.exec(model_base)
        model_deployments = list(model_result.all()) if device_ids else []

        model_status_counts: dict[str, int] = {}
        for m in model_deployments:
            model_status_counts[m.status] = model_status_counts.get(m.status, 0) + 1

        return {
            "total_devices": len(devices),
            "device_status": status_counts,
            "total_model_deployments": len(model_deployments),
            "model_deployment_status": model_status_counts,
            "fleet_id": str(fleet_id) if fleet_id else None,
        }

    # ── Fleet Config CRUD ───────────────────────────────────────────

    @staticmethod
    async def create_fleet_config(
        session: AsyncSession,
        *,
        name: str,
        description: str | None = None,
        target_device_type: str = "generic",
        sync_schedule: str = "periodic",
        sync_interval_seconds: int = 300,
        conflict_strategy: str = "last_write_wins",
        default_inference_backend: str = "ollama",
        default_quantization: str | None = None,
        max_offline_hours: int = 72,
        auto_decommission: bool = False,
        config: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> FleetConfig:
        """Create a new fleet configuration profile."""
        fleet = FleetConfig(
            name=name,
            description=description,
            target_device_type=target_device_type,
            sync_schedule=sync_schedule,
            sync_interval_seconds=sync_interval_seconds,
            conflict_strategy=conflict_strategy,
            default_inference_backend=default_inference_backend,
            default_quantization=default_quantization,
            max_offline_hours=max_offline_hours,
            auto_decommission=auto_decommission,
            config=config or {},
            created_by=created_by,
        )
        session.add(fleet)
        await session.commit()
        await session.refresh(fleet)
        return fleet

    @staticmethod
    async def get_fleet_config(
        session: AsyncSession,
        fleet_id: UUID,
    ) -> FleetConfig | None:
        """Return a single fleet config by ID."""
        return await session.get(FleetConfig, fleet_id)

    @staticmethod
    async def list_fleet_configs(
        session: AsyncSession,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[FleetConfig], int]:
        """Return paginated fleet configurations."""
        base = select(FleetConfig)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = (
            base.offset(offset)
            .limit(limit)
            .order_by(
                FleetConfig.created_at.desc()  # type: ignore[union-attr]
            )
        )
        result = await session.exec(stmt)
        return list(result.all()), total


__all__ = [
    "EdgeRuntime",
]
