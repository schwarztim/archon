"""Tests for MobileService — device registration, biometric auth, push, offline sync."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.mobile import (
    BiometricProof,
    DeviceRegistration,
    DeviceSession,
    MobileAuthResult,
    MobilePlatform,
    OfflineAction,
    PushNotification,
    SyncResult,
)
from app.services.mobile_service import MobileService

# ── Fixtures ────────────────────────────────────────────────────────

TENANT = "tenant-mobile-test"


def _user(tenant_id: str = TENANT, **overrides: Any) -> AuthenticatedUser:
    defaults: dict[str, Any] = dict(
        id=str(uuid4()),
        email="mobile@example.com",
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=[],
        session_id="sess-mob",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _mock_secrets(**overrides: Any) -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_secret = AsyncMock(return_value=overrides.get("get_return", {}))
    mgr.put_secret = AsyncMock()
    mgr.delete_secret = AsyncMock()
    return mgr


def _device_reg(**overrides: Any) -> DeviceRegistration:
    defaults: dict[str, Any] = dict(
        platform=MobilePlatform.IOS,
        device_name="iPhone 15 Pro",
        push_token="apns-token-abc",
        biometric_capable=True,
    )
    defaults.update(overrides)
    return DeviceRegistration(**defaults)


# ── register_device ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_device_returns_session() -> None:
    secrets = _mock_secrets()
    svc = MobileService(secrets)
    user = _user()
    reg = _device_reg()

    session = await svc.register_device(TENANT, user, reg)

    assert isinstance(session, DeviceSession)
    assert session.tenant_id == TENANT
    assert session.user_id == user.id
    assert session.platform == MobilePlatform.IOS
    assert session.push_enabled is True
    assert session.biometric_enrolled is True


@pytest.mark.asyncio
async def test_register_device_stores_in_vault() -> None:
    secrets = _mock_secrets()
    svc = MobileService(secrets)
    user = _user()

    await svc.register_device(TENANT, user, _device_reg())

    secrets.put_secret.assert_awaited_once()
    call_args = secrets.put_secret.call_args
    assert TENANT in call_args[0][0]
    assert "push_token" in call_args[0][1]


@pytest.mark.asyncio
async def test_register_device_no_push_token() -> None:
    secrets = _mock_secrets()
    svc = MobileService(secrets)
    user = _user()
    reg = _device_reg(push_token="")

    session = await svc.register_device(TENANT, user, reg)

    assert session.push_enabled is False


# ── authenticate_biometric ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_biometric_auth_success() -> None:
    signing_key = "test-signing-key-123"
    challenge = "random-challenge-xyz"
    expected_sig = hmac.new(
        signing_key.encode("utf-8"),
        challenge.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    device_id = "device-bio-01"
    device_data = {"user_id": "u1", "device_id": device_id}

    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(side_effect=[
        device_data,                  # _load_device
        {"key": signing_key},         # _get_signing_key
        device_data,                  # _touch_device (inside put_secret is separate)
    ])
    secrets.put_secret = AsyncMock()

    svc = MobileService(secrets)
    proof = BiometricProof(
        challenge=challenge,
        signature=expected_sig,
        device_id=device_id,
        timestamp=datetime.now(timezone.utc),
    )

    result = await svc.authenticate_biometric(TENANT, device_id, proof)

    assert isinstance(result, MobileAuthResult)
    assert result.access_token != ""
    assert result.expires_in == 900


@pytest.mark.asyncio
async def test_biometric_auth_device_not_found() -> None:
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(side_effect=Exception("not found"))
    svc = MobileService(secrets)

    proof = BiometricProof(
        challenge="c", signature="s", device_id="d",
        timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="not registered"):
        await svc.authenticate_biometric(TENANT, "d", proof)


@pytest.mark.asyncio
async def test_biometric_auth_device_id_mismatch() -> None:
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(return_value={"user_id": "u1"})
    svc = MobileService(secrets)

    proof = BiometricProof(
        challenge="c", signature="s", device_id="wrong-device",
        timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="mismatch"):
        await svc.authenticate_biometric(TENANT, "real-device", proof)


# ── authenticate_saml_mobile ────────────────────────────────────────


@pytest.mark.asyncio
async def test_saml_mobile_auth_returns_tokens() -> None:
    secrets = _mock_secrets()
    svc = MobileService(secrets)

    result = await svc.authenticate_saml_mobile(TENANT, "base64-saml-response")

    assert isinstance(result, MobileAuthResult)
    assert result.access_token != ""
    assert result.mfa_required is False


# ── refresh_mobile_session ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_session_success() -> None:
    device_id = "device-refresh-01"
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(return_value={"user_id": "u1", "device_id": device_id})
    secrets.put_secret = AsyncMock()
    svc = MobileService(secrets)

    result = await svc.refresh_mobile_session(TENANT, device_id, "old-refresh-token")

    assert isinstance(result, MobileAuthResult)
    assert result.device_id == device_id


@pytest.mark.asyncio
async def test_refresh_session_device_not_registered() -> None:
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(side_effect=Exception("not found"))
    svc = MobileService(secrets)

    with pytest.raises(ValueError, match="not registered"):
        await svc.refresh_mobile_session(TENANT, "ghost", "tok")


# ── send_push_notification ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_push_notification_dispatched() -> None:
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(return_value={"apns_key": "k"})
    svc = MobileService(secrets)

    notification = PushNotification(title="Alert", body="Something happened")
    await svc.send_push_notification(TENANT, "user-1", notification)

    secrets.get_secret.assert_awaited_once()


# ── sync_offline_actions ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_offline_all_processed() -> None:
    secrets = _mock_secrets()
    svc = MobileService(secrets)
    user = _user()

    actions = [
        OfflineAction(action_type="create", idempotency_key="k1", payload={}),
        OfflineAction(action_type="update", idempotency_key="k2", payload={}),
    ]
    result = await svc.sync_offline_actions(TENANT, user, actions)

    assert isinstance(result, SyncResult)
    assert result.processed == 2
    assert result.failed == 0
    assert result.conflicts == []


@pytest.mark.asyncio
async def test_sync_offline_detects_duplicate_idempotency_keys() -> None:
    secrets = _mock_secrets()
    svc = MobileService(secrets)
    user = _user()

    actions = [
        OfflineAction(action_type="create", idempotency_key="dup", payload={}),
        OfflineAction(action_type="create", idempotency_key="dup", payload={}),
    ]
    result = await svc.sync_offline_actions(TENANT, user, actions)

    assert result.processed == 1
    assert result.conflicts == ["dup"]


# ── revoke_device ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_device_success() -> None:
    user = _user()
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(return_value={"user_id": user.id, "device_id": "d1"})
    secrets.put_secret = AsyncMock()
    svc = MobileService(secrets)

    await svc.revoke_device(TENANT, user, "d1")

    secrets.put_secret.assert_awaited_once()
    written = secrets.put_secret.call_args[0][1]
    assert written["revoked"] is True


@pytest.mark.asyncio
async def test_revoke_device_not_found() -> None:
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(side_effect=Exception("missing"))
    svc = MobileService(secrets)
    user = _user()

    with pytest.raises(ValueError, match="not found"):
        await svc.revoke_device(TENANT, user, "ghost")


@pytest.mark.asyncio
async def test_revoke_device_wrong_user() -> None:
    user = _user()
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(return_value={"user_id": "someone-else"})
    svc = MobileService(secrets)

    with pytest.raises(ValueError, match="does not belong"):
        await svc.revoke_device(TENANT, user, "d1")
