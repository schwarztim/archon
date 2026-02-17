"""Tests for EdgeService — device registration, offline tokens, sync, fleet, OTA, revocation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.edge import (
    CommandResult,
    DeviceRegistration,
    DeviceStatus,
    EdgeDevice,
    EdgeDeviceResponse,
    EdgeSyncRecord,
    FleetAnalytics,
    LocalSecretsBundle,
    OTAUpdate,
    OfflineToken,
    OfflineTokenConfig,
    SecretsManifest,
    SyncPayload,
    SyncResult,
    UpdateRollout,
)
from app.services.edge_service import EdgeService

# ── Fixtures ────────────────────────────────────────────────────────

TENANT = "tenant-edge-test"


def _user(**overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="edge@example.com",
        tenant_id=TENANT,
        roles=["admin"],
        permissions=["edge:create", "edge:read", "edge:execute"],
        session_id="sess-edge",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _mock_secrets() -> AsyncMock:
    mgr = AsyncMock()
    mgr.read_secret = AsyncMock(return_value="device-enc-key-hex")
    return mgr


def _mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _device_registration(**overrides: Any) -> DeviceRegistration:
    defaults: dict[str, Any] = dict(
        device_name="edge-node-01",
        platform="linux",
        hardware_id="hw-abc-123",
        capabilities={"inference": True},
        location="us-east-1",
        architecture="x86_64",
        cpu_cores=8,
        memory_mb=16384,
        disk_mb=102400,
        has_gpu=True,
        gpu_model="NVIDIA T4",
    )
    defaults.update(overrides)
    return DeviceRegistration(**defaults)


def _edge_device(tenant_id: str = TENANT, status: str = "online", **overrides: Any) -> EdgeDevice:
    now = datetime.now(timezone.utc)
    defaults: dict[str, Any] = dict(
        id=uuid4(),
        name="edge-node-01",
        device_type="linux",
        status=status,
        architecture="x86_64",
        cpu_cores=8,
        memory_mb=16384,
        disk_mb=102400,
        has_gpu=True,
        gpu_model="NVIDIA T4",
        location="us-east-1",
        device_fingerprint="fp-abc",
        extra_metadata={"tenant_id": tenant_id, "hardware_id": "hw-abc-123", "firmware_version": "1.0.0"},
        last_heartbeat_at=now,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return EdgeDevice(**defaults)


# ── register_device ─────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.edge_service.AuditLogService.create", new_callable=AsyncMock)
async def test_register_device_success(mock_audit: AsyncMock) -> None:
    session = _mock_session()
    user = _user()
    reg = _device_registration()

    result = await EdgeService.register_device(
        TENANT, user, reg, session=session, secrets_manager=_mock_secrets(),
    )

    assert isinstance(result, EdgeDeviceResponse)
    assert result.device_name == "edge-node-01"
    assert result.platform == "linux"
    assert result.status == "online"
    assert result.tenant_id == TENANT
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.edge_service.AuditLogService.create", new_callable=AsyncMock)
async def test_register_device_generates_fingerprint(mock_audit: AsyncMock) -> None:
    session = _mock_session()
    result = await EdgeService.register_device(
        TENANT, _user(), _device_registration(), session=session, secrets_manager=_mock_secrets(),
    )

    assert result.id is not None
    assert result.hardware_id == "hw-abc-123"


# ── provision_offline_token ─────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.edge_service.AuditLogService.create", new_callable=AsyncMock)
async def test_provision_offline_token_success(mock_audit: AsyncMock) -> None:
    device = _edge_device()
    session = _mock_session()
    session.get = AsyncMock(return_value=device)
    config = OfflineTokenConfig(ttl_days=30, permissions_snapshot=["read"], allowed_agents=["agent-a"])

    result = await EdgeService.provision_offline_token(
        TENANT, _user(), device.id, config, session=session, secrets_manager=_mock_secrets(),
    )

    assert isinstance(result, OfflineToken)
    assert result.device_id == device.id
    assert result.token.startswith("eyJ.")
    assert result.expires_at is not None
    assert result.allowed_agents == ["agent-a"]


@pytest.mark.asyncio
async def test_provision_offline_token_device_not_found() -> None:
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await EdgeService.provision_offline_token(
            TENANT, _user(), uuid4(), OfflineTokenConfig(), session=session, secrets_manager=_mock_secrets(),
        )


@pytest.mark.asyncio
async def test_provision_offline_token_wrong_tenant() -> None:
    device = _edge_device(tenant_id="other-tenant")
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    with pytest.raises(PermissionError, match="not in tenant scope"):
        await EdgeService.provision_offline_token(
            TENANT, _user(), device.id, OfflineTokenConfig(), session=session, secrets_manager=_mock_secrets(),
        )


# ── provision_local_secrets ─────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.edge_service.AuditLogService.create", new_callable=AsyncMock)
async def test_provision_local_secrets_success(mock_audit: AsyncMock) -> None:
    device = _edge_device()
    session = _mock_session()
    session.get = AsyncMock(return_value=device)
    manifest = SecretsManifest(secret_paths=["api/key1", "api/key2"], ttl_hours=48)

    result = await EdgeService.provision_local_secrets(
        TENANT, device.id, manifest, session=session, secrets_manager=_mock_secrets(), user=_user(),
    )

    assert isinstance(result, LocalSecretsBundle)
    assert result.device_id == device.id
    assert result.secret_count == 2
    assert result.encrypted_secrets  # non-empty hash


@pytest.mark.asyncio
async def test_provision_local_secrets_wrong_tenant() -> None:
    device = _edge_device(tenant_id="wrong-tenant")
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    with pytest.raises(PermissionError, match="not in tenant scope"):
        await EdgeService.provision_local_secrets(
            TENANT, device.id, SecretsManifest(secret_paths=["k"]), session=session, secrets_manager=_mock_secrets(), user=_user(),
        )


# ── sync_device ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_device_bidirectional() -> None:
    device = _edge_device()
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    payload = SyncPayload(
        device_id=device.id,
        local_changes=[{"type": "config", "data": "val"}],
        last_sync_checkpoint="cp-1",
        storage_stats={"used_mb": 500},
    )
    result = await EdgeService.sync_device(TENANT, device.id, payload, session=session)

    assert isinstance(result, SyncResult)
    assert result.processed == 1
    assert result.next_checkpoint != ""
    assert isinstance(result.conflicts, list)


@pytest.mark.asyncio
async def test_sync_device_not_found() -> None:
    session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="not found"):
        await EdgeService.sync_device(TENANT, uuid4(), SyncPayload(device_id=uuid4()), session=session)


# ── device_status ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_device_status_online() -> None:
    device = _edge_device(status="online")
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    status = await EdgeService.get_device_status(TENANT, device.id, session=session)

    assert isinstance(status, DeviceStatus)
    assert status.online is True
    assert status.device_id == device.id
    assert status.firmware_version == "1.0.0"


@pytest.mark.asyncio
async def test_device_status_wrong_tenant() -> None:
    device = _edge_device(tenant_id="other")
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    with pytest.raises(PermissionError, match="not in tenant scope"):
        await EdgeService.get_device_status(TENANT, device.id, session=session)


# ── list_fleet ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_fleet_filters_by_tenant() -> None:
    own_device = _edge_device(tenant_id=TENANT)
    other_device = _edge_device(tenant_id="other-tenant")
    session = _mock_session()

    mock_result = MagicMock()
    mock_result.all.return_value = [own_device, other_device]
    session.exec = AsyncMock(return_value=mock_result)

    fleet = await EdgeService.list_fleet(TENANT, session=session)

    assert len(fleet) == 1
    assert fleet[0].tenant_id == TENANT


# ── remote_command ──────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.edge_service.AuditLogService.create", new_callable=AsyncMock)
async def test_remote_command_restart(mock_audit: AsyncMock) -> None:
    device = _edge_device()
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    result = await EdgeService.send_remote_command(
        TENANT, _user(), device.id, "restart", session=session,
    )

    assert isinstance(result, CommandResult)
    assert result.command == "restart"
    assert result.status == "queued"
    assert result.device_id == device.id


@pytest.mark.asyncio
async def test_remote_command_invalid() -> None:
    device = _edge_device()
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    with pytest.raises(ValueError, match="Invalid command"):
        await EdgeService.send_remote_command(
            TENANT, _user(), device.id, "format-disk", session=session,
        )


# ── push_ota_update ─────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.edge_service.AuditLogService.create", new_callable=AsyncMock)
async def test_push_ota_update_success(mock_audit: AsyncMock) -> None:
    device = _edge_device()
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    update = OTAUpdate(version="2.0.0", binary_url="https://cdn.example.com/fw.bin", checksum="sha256:abc")
    result = await EdgeService.push_ota_update(
        TENANT, _user(), [device.id], update, session=session,
    )

    assert isinstance(result, UpdateRollout)
    assert result.version == "2.0.0"
    assert result.status == "pending"
    assert device.id in result.devices


@pytest.mark.asyncio
async def test_push_ota_update_device_not_found() -> None:
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    update = OTAUpdate(version="2.0.0", binary_url="https://cdn.example.com/fw.bin", checksum="sha256:abc")

    with pytest.raises(ValueError, match="not found"):
        await EdgeService.push_ota_update(TENANT, _user(), [uuid4()], update, session=session)


# ── revoke_device ───────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("app.services.edge_service.AuditLogService.create", new_callable=AsyncMock)
async def test_revoke_device_success(mock_audit: AsyncMock) -> None:
    device = _edge_device()
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    await EdgeService.revoke_device(TENANT, _user(), device.id, session=session)

    assert device.status == "decommissioned"
    assert device.extra_metadata.get("revoked") is True
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_revoke_device_wrong_tenant() -> None:
    device = _edge_device(tenant_id="other")
    session = _mock_session()
    session.get = AsyncMock(return_value=device)

    with pytest.raises(PermissionError, match="not in tenant scope"):
        await EdgeService.revoke_device(TENANT, _user(), device.id, session=session)


# ── fleet_analytics ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fleet_analytics_counts() -> None:
    d1 = _edge_device(status="online")
    d2 = _edge_device(status="offline")
    d3 = _edge_device(status="degraded")
    other = _edge_device(tenant_id="other", status="online")
    session = _mock_session()

    mock_devices = MagicMock()
    mock_devices.all.return_value = [d1, d2, d3, other]
    mock_syncs = MagicMock()
    mock_syncs.all.return_value = []
    session.exec = AsyncMock(side_effect=[mock_devices, mock_syncs])

    analytics = await EdgeService.get_fleet_analytics(TENANT, session=session)

    assert isinstance(analytics, FleetAnalytics)
    assert analytics.total_devices == 3
    assert analytics.online == 1
    assert analytics.offline == 1
    assert analytics.degraded == 1


@pytest.mark.asyncio
async def test_fleet_analytics_empty_tenant() -> None:
    session = _mock_session()
    mock_devices = MagicMock()
    mock_devices.all.return_value = []
    session.exec = AsyncMock(return_value=mock_devices)

    analytics = await EdgeService.get_fleet_analytics(TENANT, session=session)

    assert analytics.total_devices == 0
    assert analytics.online == 0
