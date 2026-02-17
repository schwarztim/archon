"""Unit tests for EdgeRuntime — device registration, model deployment, sync, fleet ops.

Every DB interaction is mocked via AsyncSession so no real database is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.models.edge import (
    EdgeDevice,
    EdgeModelDeployment,
    EdgeSyncRecord,
    FleetConfig,
)
from app.services.edge import EdgeRuntime


# ── Constants (valid hex UUIDs only) ────────────────────────────────

DEVICE_ID = UUID("aabb0011-2233-4455-6677-8899aabbccdd")
DEVICE_ID_2 = UUID("11223344-aabb-ccdd-eeff-001122334455")
DEPLOYMENT_ID = UUID("ddeeff00-1122-3344-5566-778899001122")
SYNC_ID = UUID("aabbccdd-1122-3344-5566-778899aabbcc")
FLEET_ID = UUID("00112233-4455-6677-8899-aabbccddeeff")
USER_ID = UUID("ccddaabb-1122-3344-5566-778899001122")
MISSING_ID = UUID("00000000-aaaa-bbbb-cccc-ddddeeeeffff")


# ── Factories ───────────────────────────────────────────────────────


def _make_device(
    *,
    device_id: UUID = DEVICE_ID,
    name: str = "edge-node-01",
    device_type: str = "generic",
    status: str = "online",
    architecture: str = "x86_64",
    cpu_cores: int = 4,
    memory_mb: int = 8192,
    disk_mb: int = 51200,
    has_gpu: bool = False,
    gpu_model: str | None = None,
    ip_address: str | None = None,
    location: str | None = None,
    region: str | None = None,
    fleet_id: UUID | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> EdgeDevice:
    """Factory for EdgeDevice instances."""
    return EdgeDevice(
        id=device_id,
        name=name,
        device_type=device_type,
        status=status,
        architecture=architecture,
        cpu_cores=cpu_cores,
        memory_mb=memory_mb,
        disk_mb=disk_mb,
        has_gpu=has_gpu,
        gpu_model=gpu_model,
        ip_address=ip_address,
        location=location,
        region=region,
        fleet_id=fleet_id,
        extra_metadata=extra_metadata or {},
    )


def _make_deployment(
    *,
    deployment_id: UUID = DEPLOYMENT_ID,
    device_id: UUID = DEVICE_ID,
    model_name: str = "llama3",
    model_version: str = "latest",
    inference_backend: str = "ollama",
    quantization: str | None = None,
    status: str = "downloading",
    size_mb: int = 4096,
    config: dict[str, Any] | None = None,
) -> EdgeModelDeployment:
    """Factory for EdgeModelDeployment instances."""
    return EdgeModelDeployment(
        id=deployment_id,
        device_id=device_id,
        model_name=model_name,
        model_version=model_version,
        inference_backend=inference_backend,
        quantization=quantization,
        status=status,
        size_mb=size_mb,
        config=config or {},
    )


def _make_sync_record(
    *,
    sync_id: UUID = SYNC_ID,
    device_id: UUID = DEVICE_ID,
    direction: str = "bidirectional",
    status: str = "in_progress",
    sync_type: str = "delta",
    conflict_strategy: str = "last_write_wins",
) -> EdgeSyncRecord:
    """Factory for EdgeSyncRecord instances."""
    return EdgeSyncRecord(
        id=sync_id,
        device_id=device_id,
        direction=direction,
        status=status,
        sync_type=sync_type,
        conflict_strategy=conflict_strategy,
        details={},
    )


# ── Mock helpers ────────────────────────────────────────────────────


def _mock_db() -> AsyncMock:
    """Return a fully-mocked AsyncSession with common methods."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.get = AsyncMock()
    db.exec = AsyncMock()
    return db


def _mock_exec_result(rows: list[Any]) -> MagicMock:
    """Create a mock result object returned by session.exec()."""
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


# ═══════════════════════════════════════════════════════════════════
#  Register Device Tests
# ═══════════════════════════════════════════════════════════════════


class TestRegisterDevice:
    """Tests for EdgeRuntime.register_device."""

    @pytest.mark.asyncio
    async def test_register_device_minimal(self) -> None:
        """Register device with only the required name field."""
        db = _mock_db()

        async def _refresh(obj: Any) -> None:
            obj.id = DEVICE_ID

        db.refresh.side_effect = _refresh

        result = await EdgeRuntime.register_device(session=db, name="edge-01")

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()
        assert isinstance(result, EdgeDevice)
        assert result.name == "edge-01"
        assert result.status == "online"
        assert result.device_type == "generic"
        assert result.architecture == "x86_64"
        assert result.cpu_cores == 4
        assert result.memory_mb == 8192
        assert result.extra_metadata == {}

    @pytest.mark.asyncio
    async def test_register_device_all_fields(self) -> None:
        """Register device with all optional fields populated."""
        db = _mock_db()
        meta = {"firmware": "v2.1"}

        result = await EdgeRuntime.register_device(
            session=db,
            name="gpu-node-01",
            device_type="server",
            architecture="aarch64",
            cpu_cores=16,
            memory_mb=65536,
            disk_mb=1048576,
            has_gpu=True,
            gpu_model="A100",
            ip_address="10.0.0.5",
            location="datacenter-east",
            region="us-east-1",
            device_fingerprint="fp-abc123",
            certificate_thumbprint="thumb-xyz",
            fleet_id=FLEET_ID,
            extra_metadata=meta,
            registered_by=USER_ID,
        )

        assert result.name == "gpu-node-01"
        assert result.device_type == "server"
        assert result.has_gpu is True
        assert result.gpu_model == "A100"
        assert result.fleet_id == FLEET_ID
        assert result.extra_metadata == meta
        assert result.registered_by == USER_ID
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_device_sets_last_heartbeat(self) -> None:
        """Registered device should have last_heartbeat_at set."""
        db = _mock_db()

        result = await EdgeRuntime.register_device(session=db, name="hb-node")

        assert result.last_heartbeat_at is not None
        assert isinstance(result.last_heartbeat_at, datetime)


# ═══════════════════════════════════════════════════════════════════
#  Deploy Model Tests
# ═══════════════════════════════════════════════════════════════════


class TestDeployModel:
    """Tests for EdgeRuntime.deploy_model."""

    @pytest.mark.asyncio
    async def test_deploy_model_success(self) -> None:
        """Deploy model to an existing device."""
        db = _mock_db()
        device = _make_device()
        db.get.return_value = device

        async def _refresh(obj: Any) -> None:
            obj.id = DEPLOYMENT_ID

        db.refresh.side_effect = _refresh

        result = await EdgeRuntime.deploy_model(
            session=db,
            device_id=DEVICE_ID,
            model_name="llama3",
            model_version="8b",
            inference_backend="ollama",
            quantization="4bit",
            size_mb=4096,
            config={"ctx_length": 2048},
            deployed_by=USER_ID,
        )

        assert result is not None
        assert isinstance(result, EdgeModelDeployment)
        assert result.model_name == "llama3"
        assert result.model_version == "8b"
        assert result.status == "downloading"
        assert result.quantization == "4bit"
        assert result.size_mb == 4096
        assert result.deployed_by == USER_ID
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deploy_model_device_not_found(self) -> None:
        """Return None when target device does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await EdgeRuntime.deploy_model(
            session=db,
            device_id=MISSING_ID,
            model_name="llama3",
        )

        assert result is None
        db.add.assert_not_called()
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deploy_model_defaults(self) -> None:
        """Deploy model with minimal params uses correct defaults."""
        db = _mock_db()
        db.get.return_value = _make_device()

        result = await EdgeRuntime.deploy_model(
            session=db,
            device_id=DEVICE_ID,
            model_name="mistral",
        )

        assert result is not None
        assert result.model_version == "latest"
        assert result.inference_backend == "ollama"
        assert result.quantization is None
        assert result.size_mb == 0
        assert result.config == {}
        assert result.deployed_by is None


# ═══════════════════════════════════════════════════════════════════
#  Sync Tests
# ═══════════════════════════════════════════════════════════════════


class TestSync:
    """Tests for EdgeRuntime.sync."""

    @pytest.mark.asyncio
    async def test_sync_success(self) -> None:
        """Initiate sync for an existing device."""
        db = _mock_db()
        db.get.return_value = _make_device()

        async def _refresh(obj: Any) -> None:
            obj.id = SYNC_ID

        db.refresh.side_effect = _refresh

        result = await EdgeRuntime.sync(
            session=db,
            device_id=DEVICE_ID,
            direction="up",
            sync_type="full",
            conflict_strategy="merge",
            last_sync_cursor="cursor-abc",
            details={"tables": ["agents"]},
        )

        assert result is not None
        assert isinstance(result, EdgeSyncRecord)
        assert result.status == "in_progress"
        assert result.direction == "up"
        assert result.sync_type == "full"
        assert result.conflict_strategy == "merge"
        assert result.last_sync_cursor == "cursor-abc"
        assert result.details == {"tables": ["agents"]}
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sync_device_not_found(self) -> None:
        """Return None when device does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await EdgeRuntime.sync(
            session=db,
            device_id=MISSING_ID,
        )

        assert result is None
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_sync_defaults(self) -> None:
        """Sync with minimal params uses correct defaults."""
        db = _mock_db()
        db.get.return_value = _make_device()

        result = await EdgeRuntime.sync(
            session=db,
            device_id=DEVICE_ID,
        )

        assert result is not None
        assert result.direction == "bidirectional"
        assert result.sync_type == "delta"
        assert result.conflict_strategy == "last_write_wins"
        assert result.last_sync_cursor is None
        assert result.details == {}


# ═══════════════════════════════════════════════════════════════════
#  Complete Sync Tests
# ═══════════════════════════════════════════════════════════════════


class TestCompleteSync:
    """Tests for EdgeRuntime.complete_sync."""

    @pytest.mark.asyncio
    async def test_complete_sync_success(self) -> None:
        """Mark a sync record as completed with stats."""
        db = _mock_db()
        record = _make_sync_record()
        db.get.return_value = record

        result = await EdgeRuntime.complete_sync(
            session=db,
            sync_id=SYNC_ID,
            status="completed",
            records_sent=100,
            records_received=50,
            bytes_transferred=2048,
            conflicts_detected=2,
            conflicts_resolved=2,
            last_sync_cursor="cursor-def",
        )

        assert result is not None
        assert result.status == "completed"
        assert result.records_sent == 100
        assert result.records_received == 50
        assert result.bytes_transferred == 2048
        assert result.conflicts_detected == 2
        assert result.conflicts_resolved == 2
        assert result.last_sync_cursor == "cursor-def"
        assert result.completed_at is not None
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_sync_not_found(self) -> None:
        """Return None when sync record does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await EdgeRuntime.complete_sync(
            session=db,
            sync_id=MISSING_ID,
        )

        assert result is None
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_complete_sync_failed_with_error(self) -> None:
        """Mark sync as failed with an error message."""
        db = _mock_db()
        record = _make_sync_record()
        db.get.return_value = record

        result = await EdgeRuntime.complete_sync(
            session=db,
            sync_id=SYNC_ID,
            status="failed",
            error_message="Network timeout",
        )

        assert result is not None
        assert result.status == "failed"
        assert result.error_message == "Network timeout"
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_complete_sync_defaults(self) -> None:
        """Complete sync with minimal params uses correct defaults."""
        db = _mock_db()
        record = _make_sync_record()
        db.get.return_value = record

        result = await EdgeRuntime.complete_sync(
            session=db,
            sync_id=SYNC_ID,
        )

        assert result is not None
        assert result.status == "completed"
        assert result.records_sent == 0
        assert result.records_received == 0
        assert result.bytes_transferred == 0
        assert result.conflicts_detected == 0
        assert result.conflicts_resolved == 0


# ═══════════════════════════════════════════════════════════════════
#  Get Fleet Status Tests
# ═══════════════════════════════════════════════════════════════════


class TestGetFleetStatus:
    """Tests for EdgeRuntime.get_fleet_status."""

    @pytest.mark.asyncio
    async def test_fleet_status_with_devices(self) -> None:
        """Return aggregate fleet status with devices and deployments."""
        db = _mock_db()
        d1 = _make_device(device_id=DEVICE_ID, status="online")
        d2 = _make_device(device_id=DEVICE_ID_2, status="offline")
        dep1 = _make_deployment(status="ready")
        dep2 = _make_deployment(status="downloading")

        # First exec returns devices, second returns model deployments
        device_result = _mock_exec_result([d1, d2])
        model_result = _mock_exec_result([dep1, dep2])
        db.exec.side_effect = [device_result, model_result]

        result = await EdgeRuntime.get_fleet_status(session=db)

        assert result["total_devices"] == 2
        assert result["device_status"]["online"] == 1
        assert result["device_status"]["offline"] == 1
        assert result["total_model_deployments"] == 2
        assert result["model_deployment_status"]["ready"] == 1
        assert result["model_deployment_status"]["downloading"] == 1
        assert result["fleet_id"] is None

    @pytest.mark.asyncio
    async def test_fleet_status_empty(self) -> None:
        """Return zeros when no devices exist."""
        db = _mock_db()
        device_result = _mock_exec_result([])
        model_result = _mock_exec_result([])
        db.exec.side_effect = [device_result, model_result]

        result = await EdgeRuntime.get_fleet_status(session=db)

        assert result["total_devices"] == 0
        assert result["device_status"] == {}
        assert result["total_model_deployments"] == 0
        assert result["model_deployment_status"] == {}

    @pytest.mark.asyncio
    async def test_fleet_status_with_fleet_id(self) -> None:
        """Filter fleet status by fleet_id."""
        db = _mock_db()
        d1 = _make_device(device_id=DEVICE_ID, status="online", fleet_id=FLEET_ID)
        device_result = _mock_exec_result([d1])
        model_result = _mock_exec_result([])
        db.exec.side_effect = [device_result, model_result]

        result = await EdgeRuntime.get_fleet_status(session=db, fleet_id=FLEET_ID)

        assert result["total_devices"] == 1
        assert result["fleet_id"] == str(FLEET_ID)


# ═══════════════════════════════════════════════════════════════════
#  Heartbeat Tests
# ═══════════════════════════════════════════════════════════════════


class TestHeartbeat:
    """Tests for EdgeRuntime.heartbeat."""

    @pytest.mark.asyncio
    async def test_heartbeat_success(self) -> None:
        """Record heartbeat for an existing device."""
        db = _mock_db()
        device = _make_device(status="offline")
        db.get.return_value = device

        result = await EdgeRuntime.heartbeat(session=db, device_id=DEVICE_ID)

        assert result is not None
        assert result.status == "online"
        assert result.last_heartbeat_at is not None
        assert result.updated_at is not None
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_heartbeat_device_not_found(self) -> None:
        """Return None when device does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await EdgeRuntime.heartbeat(session=db, device_id=MISSING_ID)

        assert result is None
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_heartbeat_with_metadata(self) -> None:
        """Heartbeat updates extra_metadata when provided."""
        db = _mock_db()
        device = _make_device()
        db.get.return_value = device
        meta = {"cpu_temp": 65, "load": 0.8}

        result = await EdgeRuntime.heartbeat(
            session=db,
            device_id=DEVICE_ID,
            extra_metadata=meta,
        )

        assert result is not None
        assert result.extra_metadata == meta

    @pytest.mark.asyncio
    async def test_heartbeat_without_metadata_preserves_existing(self) -> None:
        """Heartbeat without metadata does not overwrite existing metadata."""
        db = _mock_db()
        original_meta = {"firmware": "v1.0"}
        device = _make_device(extra_metadata=original_meta)
        db.get.return_value = device

        result = await EdgeRuntime.heartbeat(session=db, device_id=DEVICE_ID)

        assert result is not None
        assert result.extra_metadata == original_meta


# ═══════════════════════════════════════════════════════════════════
#  Update Device Tests
# ═══════════════════════════════════════════════════════════════════


class TestUpdateDevice:
    """Tests for EdgeRuntime.update_device."""

    @pytest.mark.asyncio
    async def test_update_device_name(self) -> None:
        """Update only the device name."""
        db = _mock_db()
        device = _make_device()
        db.get.return_value = device

        result = await EdgeRuntime.update_device(
            session=db,
            device_id=DEVICE_ID,
            name="renamed-node",
        )

        assert result is not None
        assert result.name == "renamed-node"
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_device_not_found(self) -> None:
        """Return None when device does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await EdgeRuntime.update_device(
            session=db,
            device_id=MISSING_ID,
            name="new-name",
        )

        assert result is None
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_device_multiple_fields(self) -> None:
        """Update multiple fields at once."""
        db = _mock_db()
        device = _make_device()
        db.get.return_value = device

        result = await EdgeRuntime.update_device(
            session=db,
            device_id=DEVICE_ID,
            name="updated-node",
            status="degraded",
            ip_address="192.168.1.100",
            location="rack-42",
            region="eu-west-1",
            fleet_id=FLEET_ID,
            extra_metadata={"tag": "production"},
        )

        assert result is not None
        assert result.name == "updated-node"
        assert result.status == "degraded"
        assert result.ip_address == "192.168.1.100"
        assert result.location == "rack-42"
        assert result.region == "eu-west-1"
        assert result.fleet_id == FLEET_ID
        assert result.extra_metadata == {"tag": "production"}
        assert result.updated_at is not None

    @pytest.mark.asyncio
    async def test_update_device_no_changes(self) -> None:
        """Calling update with no optional fields still commits and sets updated_at."""
        db = _mock_db()
        device = _make_device()
        db.get.return_value = device

        result = await EdgeRuntime.update_device(
            session=db,
            device_id=DEVICE_ID,
        )

        assert result is not None
        assert result.updated_at is not None
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_device_preserves_unchanged_fields(self) -> None:
        """Fields not passed to update remain at their original values."""
        db = _mock_db()
        device = _make_device(
            name="original",
            status="online",
            ip_address="10.0.0.1",
        )
        db.get.return_value = device

        result = await EdgeRuntime.update_device(
            session=db,
            device_id=DEVICE_ID,
            name="changed",
        )

        assert result is not None
        assert result.name == "changed"
        assert result.status == "online"
        assert result.ip_address == "10.0.0.1"
