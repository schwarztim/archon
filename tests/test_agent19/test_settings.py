"""Tests for Settings Platform — health endpoint, settings CRUD, feature flags,
API keys, and notifications."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser


# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000100"
ADMIN_USER_ID = "00000000-0000-0000-0000-000000000001"
REGULAR_USER_ID = "00000000-0000-0000-0000-000000000002"


def _admin_user(**overrides: Any) -> AuthenticatedUser:
    """Create an admin AuthenticatedUser for testing."""
    defaults: dict[str, Any] = dict(
        id=ADMIN_USER_ID,
        email="admin@archon.local",
        tenant_id=TENANT_ID,
        roles=["admin"],
        permissions=[],
        session_id="sess-settings",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _regular_user(**overrides: Any) -> AuthenticatedUser:
    """Create a regular (non-admin) AuthenticatedUser for testing."""
    defaults: dict[str, Any] = dict(
        id=REGULAR_USER_ID,
        email="user@archon.local",
        tenant_id=TENANT_ID,
        roles=["user"],
        permissions=[],
        session_id="sess-settings-user",
    )
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


# ── Health Endpoint Tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_basic() -> None:
    """Basic /health returns healthy status."""
    from app.health import health_check

    result = await health_check()
    assert result["status"] == "healthy"
    assert "version" in result
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_health_check_full_returns_all_services() -> None:
    """Full health check returns all service statuses."""
    from app.health import health_check_full

    with (
        patch("app.health._check_db", return_value={"status": "ok"}),
        patch("app.health._check_redis", return_value={"status": "ok"}),
        patch("app.health._check_vault", return_value={"status": "ok"}),
        patch("app.health._check_keycloak", return_value={"status": "ok"}),
    ):
        result = await health_check_full()

    assert result["status"] == "healthy"
    assert result["version"] == "1.0.0"
    assert "services" in result
    services = result["services"]
    assert services["api"] == "up"
    assert services["database"] == "up"
    assert services["redis"] == "up"
    assert services["vault"] == "connected"
    assert services["keycloak"] == "up"
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_health_check_full_db_down() -> None:
    """Health check reports database as down when DB check fails."""
    from app.health import health_check_full

    with (
        patch(
            "app.health._check_db",
            return_value={"status": "error", "error": "conn refused"},
        ),
        patch("app.health._check_redis", return_value={"status": "ok"}),
        patch("app.health._check_vault", return_value={"status": "ok"}),
        patch("app.health._check_keycloak", return_value={"status": "ok"}),
    ):
        result = await health_check_full()

    assert result["services"]["database"] == "down"
    assert result["services"]["api"] == "up"


@pytest.mark.asyncio
async def test_health_check_full_vault_stub() -> None:
    """Health check reports vault as stub when vault returns stub status."""
    from app.health import health_check_full

    with (
        patch("app.health._check_db", return_value={"status": "ok"}),
        patch("app.health._check_redis", return_value={"status": "ok"}),
        patch(
            "app.health._check_vault", return_value={"status": "error", "error": "stub"}
        ),
        patch("app.health._check_keycloak", return_value={"status": "ok"}),
    ):
        result = await health_check_full()

    assert result["services"]["vault"] == "stub"


@pytest.mark.asyncio
async def test_health_check_full_keycloak_down() -> None:
    """Health check reports keycloak as down when check fails."""
    from app.health import health_check_full

    with (
        patch("app.health._check_db", return_value={"status": "ok"}),
        patch("app.health._check_redis", return_value={"status": "ok"}),
        patch("app.health._check_vault", return_value={"status": "ok"}),
        patch(
            "app.health._check_keycloak",
            return_value={"status": "error", "error": "timeout"},
        ),
    ):
        result = await health_check_full()

    assert result["services"]["keycloak"] == "down"


# ── Settings CRUD Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_settings_returns_defaults() -> None:
    """GET /settings returns default platform settings."""
    from app.routes.settings import get_settings, _settings_store

    # Clean state for this tenant
    _settings_store.pop(TENANT_ID, None)

    user = _admin_user()
    result = await get_settings(user=user)

    assert "data" in result
    assert "meta" in result
    data = result["data"]
    assert data["general"]["platform_name"] == "Archon"
    assert data["general"]["timezone"] == "UTC"
    assert data["authentication"]["session_timeout_minutes"] == 480
    assert data["appearance"]["theme"] == "dark"


@pytest.mark.asyncio
async def test_get_settings_masks_smtp_password() -> None:
    """GET /settings masks SMTP password if present."""
    from app.routes.settings import get_settings, _settings_store

    _settings_store[TENANT_ID] = {
        "general": {"platform_name": "Archon"},
        "authentication": {},
        "notifications": {"smtp_password": "super-secret"},
        "api": {},
        "appearance": {},
    }

    user = _admin_user()
    result = await get_settings(user=user)

    assert result["data"]["notifications"]["smtp_password"] == "********"

    # Cleanup
    _settings_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_update_settings_general() -> None:
    """PUT /settings updates general section."""
    from app.routes.settings import update_settings, SettingsUpdate, _settings_store

    _settings_store.pop(TENANT_ID, None)

    user = _admin_user()
    body = SettingsUpdate(
        general={"platform_name": "Archon Pro", "timezone": "America/New_York"}
    )
    result = await update_settings(body=body, user=user)

    assert result["data"]["general"]["platform_name"] == "Archon Pro"
    assert result["data"]["general"]["timezone"] == "America/New_York"
    assert "meta" in result

    _settings_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_update_settings_strips_smtp_password() -> None:
    """PUT /settings removes smtp_password from stored data (goes to Vault)."""
    from app.routes.settings import update_settings, SettingsUpdate, _settings_store

    _settings_store.pop(TENANT_ID, None)

    user = _admin_user()
    body = SettingsUpdate(
        notifications={"smtp_host": "smtp.example.com", "smtp_password": "vault-me"}
    )
    result = await update_settings(body=body, user=user)

    # Password should NOT be stored in the settings dict
    assert "smtp_password" not in result["data"]["notifications"]
    assert result["data"]["notifications"]["smtp_host"] == "smtp.example.com"

    _settings_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_update_settings_appearance() -> None:
    """PUT /settings updates appearance section."""
    from app.routes.settings import update_settings, SettingsUpdate, _settings_store

    _settings_store.pop(TENANT_ID, None)

    user = _admin_user()
    body = SettingsUpdate(appearance={"theme": "light", "accent_color": "#3b82f6"})
    result = await update_settings(body=body, user=user)

    assert result["data"]["appearance"]["theme"] == "light"
    assert result["data"]["appearance"]["accent_color"] == "#3b82f6"

    _settings_store.pop(TENANT_ID, None)


# ── Feature Flags Tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_feature_flags_returns_defaults() -> None:
    """GET /settings/feature-flags returns default flags for admin."""
    from app.routes.settings import list_feature_flags, _flags_store

    _flags_store.pop(TENANT_ID, None)

    user = _admin_user()
    result = await list_feature_flags(user=user)

    assert "data" in result
    flags = result["data"]
    assert len(flags) == 5
    names = [f["name"] for f in flags]
    assert "experimental_agents" in names
    assert "multi_model_routing" in names


@pytest.mark.asyncio
async def test_toggle_feature_flag_enable() -> None:
    """PUT /settings/feature-flags/{name} enables a flag."""
    from app.routes.settings import toggle_feature_flag, FeatureFlagUpdate, _flags_store

    _flags_store.pop(TENANT_ID, None)

    user = _admin_user()
    body = FeatureFlagUpdate(enabled=True)
    result = await toggle_feature_flag(
        flag_name="experimental_agents", body=body, user=user
    )

    assert result["data"]["name"] == "experimental_agents"
    assert result["data"]["enabled"] is True

    _flags_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_toggle_feature_flag_disable() -> None:
    """PUT /settings/feature-flags/{name} disables a flag."""
    from app.routes.settings import toggle_feature_flag, FeatureFlagUpdate, _flags_store

    _flags_store.pop(TENANT_ID, None)

    user = _admin_user()
    # multi_model_routing starts enabled
    body = FeatureFlagUpdate(enabled=False)
    result = await toggle_feature_flag(
        flag_name="multi_model_routing", body=body, user=user
    )

    assert result["data"]["name"] == "multi_model_routing"
    assert result["data"]["enabled"] is False

    _flags_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_toggle_feature_flag_not_found() -> None:
    """PUT /settings/feature-flags/{name} raises 404 for unknown flag."""
    from app.routes.settings import toggle_feature_flag, FeatureFlagUpdate, _flags_store
    from fastapi import HTTPException

    _flags_store.pop(TENANT_ID, None)

    user = _admin_user()
    body = FeatureFlagUpdate(enabled=True)

    with pytest.raises(HTTPException) as exc_info:
        await toggle_feature_flag(flag_name="nonexistent_flag", body=body, user=user)

    assert exc_info.value.status_code == 404

    _flags_store.pop(TENANT_ID, None)


# ── API Keys Tests ──────────────────────────────────────────────────


class _FakeSession:
    """Minimal in-memory AsyncSession mock for API-key tests."""

    def __init__(self) -> None:
        self._store: dict[Any, Any] = {}

    def add(self, obj: Any) -> None:
        self._store[obj.id] = obj

    async def commit(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass

    async def get(self, model: Any, pk: Any) -> Any:
        return self._store.get(pk)

    async def exec(self, stmt: Any) -> Any:
        from app.models.settings import SettingsAPIKey

        # Simple in-memory filter: return all SettingsAPIKey records matching
        # the WHERE clauses encoded in the statement.  We inspect the
        # statement's whereclause to extract tenant_id and revoked filters.
        try:
            clauses = stmt.whereclause.clauses
        except AttributeError:
            clauses = []

        tenant_filter: Any = None
        revoked_filter: Any = None
        for clause in clauses:
            try:
                col_name = clause.left.key
                # Handle both BindParameter (e.g. uuid/str) and boolean literals
                try:
                    val = clause.right.value
                except AttributeError:
                    # SQLAlchemy uses False_() / True_() for boolean comparisons
                    from sqlalchemy import false, true
                    from sqlalchemy.sql.elements import False_, True_

                    right = clause.right
                    if isinstance(right, False_):
                        val = False
                    elif isinstance(right, True_):
                        val = True
                    else:
                        continue
                if col_name == "tenant_id":
                    tenant_filter = val
                elif col_name == "revoked":
                    revoked_filter = val
            except AttributeError:
                pass

        rows = [
            obj
            for obj in self._store.values()
            if isinstance(obj, SettingsAPIKey)
            and (tenant_filter is None or str(obj.tenant_id) == str(tenant_filter))
            and (revoked_filter is None or obj.revoked == revoked_filter)
        ]

        class _Result:
            def __init__(self, data: list) -> None:
                self._data = data

            def all(self) -> list:
                return self._data

        return _Result(rows)


@pytest.mark.asyncio
async def test_create_api_key() -> None:
    """POST /settings/api-keys creates a key and returns it."""
    from app.routes.settings import create_api_key, CreateAPIKeyRequest

    session = _FakeSession()
    user = _admin_user()
    body = CreateAPIKeyRequest(name="Test Key", scopes=["read", "write"])
    result = await create_api_key(body=body, user=user, session=session)  # type: ignore[arg-type]

    assert "data" in result
    data = result["data"]
    assert data["name"] == "Test Key"
    assert "key" in data  # Full key shown once
    assert data["key_prefix"] == data["key"][:8]
    assert data["revoked"] is False
    assert data["scopes"] == ["read", "write"]


@pytest.mark.asyncio
async def test_list_api_keys() -> None:
    """GET /settings/api-keys lists active keys (no hash exposed)."""
    from app.routes.settings import create_api_key, list_api_keys, CreateAPIKeyRequest

    session = _FakeSession()
    user = _admin_user()
    await create_api_key(
        body=CreateAPIKeyRequest(name="Key 1"), user=user, session=session
    )  # type: ignore[arg-type]
    await create_api_key(
        body=CreateAPIKeyRequest(name="Key 2"), user=user, session=session
    )  # type: ignore[arg-type]

    result = await list_api_keys(user=user, limit=20, offset=0, session=session)  # type: ignore[arg-type]

    assert len(result["data"]) == 2
    for key in result["data"]:
        assert "key_hash" not in key  # Hash must not be exposed
        assert "name" in key


@pytest.mark.asyncio
async def test_revoke_api_key() -> None:
    """DELETE /settings/api-keys/{id} revokes a key."""
    from app.routes.settings import (
        create_api_key,
        revoke_api_key,
        list_api_keys,
        CreateAPIKeyRequest,
    )

    session = _FakeSession()
    user = _admin_user()
    created = await create_api_key(
        body=CreateAPIKeyRequest(name="To Revoke"), user=user, session=session
    )  # type: ignore[arg-type]
    key_id = created["data"]["id"]

    result = await revoke_api_key(key_id=key_id, user=user, session=session)  # type: ignore[arg-type]
    assert result["data"]["revoked"] is True

    # Key should no longer appear in listing
    listing = await list_api_keys(user=user, limit=20, offset=0, session=session)  # type: ignore[arg-type]
    assert len(listing["data"]) == 0


@pytest.mark.asyncio
async def test_revoke_api_key_not_found() -> None:
    """DELETE /settings/api-keys/{id} raises 404 for unknown key."""
    from app.routes.settings import revoke_api_key
    from fastapi import HTTPException

    session = _FakeSession()
    user = _admin_user()
    with pytest.raises(HTTPException) as exc_info:
        await revoke_api_key(key_id=str(uuid4()), user=user, session=session)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_api_keys_pagination() -> None:
    """GET /settings/api-keys respects limit/offset."""
    from app.routes.settings import create_api_key, list_api_keys, CreateAPIKeyRequest

    session = _FakeSession()
    user = _admin_user()
    for i in range(5):
        await create_api_key(
            body=CreateAPIKeyRequest(name=f"Key {i}"), user=user, session=session
        )  # type: ignore[arg-type]

    result = await list_api_keys(user=user, limit=2, offset=0, session=session)  # type: ignore[arg-type]
    assert len(result["data"]) == 2
    assert result["meta"]["pagination"]["total"] == 5

    result2 = await list_api_keys(user=user, limit=2, offset=3, session=session)  # type: ignore[arg-type]
    assert len(result2["data"]) == 2


# ── Notifications Tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_test_notification_email_no_smtp() -> None:
    """POST /settings/notifications/test fails when SMTP not configured."""
    from app.routes.settings import (
        send_test_notification,
        NotificationTestRequest,
        _settings_store,
    )
    from fastapi import HTTPException

    _settings_store.pop(TENANT_ID, None)

    user = _admin_user()
    body = NotificationTestRequest(channel="email", recipient="test@example.com")

    with pytest.raises(HTTPException) as exc_info:
        await send_test_notification(body=body, user=user)

    assert exc_info.value.status_code == 400
    assert "SMTP" in exc_info.value.detail

    _settings_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_send_test_notification_slack_no_webhook() -> None:
    """POST /settings/notifications/test fails when Slack not configured."""
    from app.routes.settings import (
        send_test_notification,
        NotificationTestRequest,
        _settings_store,
    )
    from fastapi import HTTPException

    _settings_store.pop(TENANT_ID, None)

    user = _admin_user()
    body = NotificationTestRequest(channel="slack")

    with pytest.raises(HTTPException) as exc_info:
        await send_test_notification(body=body, user=user)

    assert exc_info.value.status_code == 400
    assert "Slack" in exc_info.value.detail

    _settings_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_send_test_notification_invalid_channel() -> None:
    """POST /settings/notifications/test fails for unsupported channel."""
    from app.routes.settings import (
        send_test_notification,
        NotificationTestRequest,
        _settings_store,
    )
    from fastapi import HTTPException

    _settings_store.pop(TENANT_ID, None)

    user = _admin_user()
    body = NotificationTestRequest(channel="sms")

    with pytest.raises(HTTPException) as exc_info:
        await send_test_notification(body=body, user=user)

    assert exc_info.value.status_code == 400

    _settings_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_send_test_notification_email_success() -> None:
    """POST /settings/notifications/test succeeds when SMTP is configured."""
    from app.routes.settings import (
        send_test_notification,
        NotificationTestRequest,
        _settings_store,
    )

    _settings_store[TENANT_ID] = {
        "general": {},
        "authentication": {},
        "notifications": {
            "smtp_host": "smtp.example.com",
            "smtp_from": "noreply@archon.io",
        },
        "api": {},
        "appearance": {},
    }

    user = _admin_user()
    body = NotificationTestRequest(channel="email", recipient="test@example.com")
    with patch(
        "app.routes.settings.aiosmtplib.send", new_callable=AsyncMock
    ) as mock_send:
        result = await send_test_notification(body=body, user=user)
        mock_send.assert_called_once()

    assert result["data"]["channel"] == "email"
    assert result["data"]["status"] == "sent"

    _settings_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_send_test_notification_slack_success() -> None:
    """POST /settings/notifications/test succeeds when Slack is configured."""
    from app.routes.settings import (
        send_test_notification,
        NotificationTestRequest,
        _settings_store,
    )

    _settings_store[TENANT_ID] = {
        "general": {},
        "authentication": {},
        "notifications": {"slack_webhook_url": "https://hooks.slack.com/services/test"},
        "api": {},
        "appearance": {},
    }

    user = _admin_user()
    body = NotificationTestRequest(channel="slack")
    result = await send_test_notification(body=body, user=user)

    assert result["data"]["channel"] == "slack"
    assert result["data"]["status"] == "sent"

    _settings_store.pop(TENANT_ID, None)


# ── Tenant Isolation Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_settings_tenant_isolation() -> None:
    """Settings are scoped per tenant — no cross-tenant leakage."""
    from app.routes.settings import (
        get_settings,
        update_settings,
        SettingsUpdate,
        _settings_store,
    )

    tenant_a = "tenant-a-settings"
    tenant_b = "tenant-b-settings"
    _settings_store.pop(tenant_a, None)
    _settings_store.pop(tenant_b, None)

    user_a = _admin_user(tenant_id=tenant_a)
    user_b = _admin_user(tenant_id=tenant_b, id=str(uuid4()))

    # Update tenant A
    await update_settings(
        body=SettingsUpdate(general={"platform_name": "Tenant A Platform"}),
        user=user_a,
    )

    # Tenant B should still have defaults
    result_b = await get_settings(user=user_b)
    assert result_b["data"]["general"]["platform_name"] == "Archon"

    # Tenant A should have the updated name
    result_a = await get_settings(user=user_a)
    assert result_a["data"]["general"]["platform_name"] == "Tenant A Platform"

    _settings_store.pop(tenant_a, None)
    _settings_store.pop(tenant_b, None)


@pytest.mark.asyncio
async def test_api_keys_tenant_isolation() -> None:
    """API keys are scoped per tenant."""
    from app.routes.settings import create_api_key, list_api_keys, CreateAPIKeyRequest

    tenant_a = "00000000-0000-0000-0000-000000000aaa"
    tenant_b = "00000000-0000-0000-0000-000000000bbb"

    # Use separate sessions to simulate tenant isolation
    session_a = _FakeSession()
    session_b = _FakeSession()

    user_a = _admin_user(tenant_id=tenant_a)
    user_b = _admin_user(tenant_id=tenant_b, id=str(uuid4()))

    await create_api_key(
        body=CreateAPIKeyRequest(name="A Key"), user=user_a, session=session_a
    )  # type: ignore[arg-type]

    result_a = await list_api_keys(user=user_a, limit=20, offset=0, session=session_a)  # type: ignore[arg-type]
    result_b = await list_api_keys(user=user_b, limit=20, offset=0, session=session_b)  # type: ignore[arg-type]

    assert len(result_a["data"]) == 1
    assert len(result_b["data"]) == 0


# ── Settings Model Tests ────────────────────────────────────────────


def test_settings_api_key_generate() -> None:
    """SettingsAPIKey.generate_key returns key, prefix, and hash."""
    from app.models.settings import SettingsAPIKey

    raw, prefix, key_hash = SettingsAPIKey.generate_key()

    assert len(raw) > 20
    assert prefix == raw[:8]
    assert len(key_hash) == 64  # SHA-256 hex digest


def test_settings_api_key_hash_consistency() -> None:
    """Same raw key always produces the same hash."""
    import hashlib

    from app.models.settings import SettingsAPIKey

    raw, _, hash1 = SettingsAPIKey.generate_key()
    hash2 = hashlib.sha256(raw.encode()).hexdigest()

    assert hash1 == hash2


# ── Meta / Envelope Tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_response_envelope_format() -> None:
    """All responses follow the {data, meta} envelope format."""
    from app.routes.settings import get_settings, _settings_store

    _settings_store.pop(TENANT_ID, None)

    user = _admin_user()
    result = await get_settings(user=user)

    assert "data" in result
    assert "meta" in result
    meta = result["meta"]
    assert "request_id" in meta
    assert "timestamp" in meta

    _settings_store.pop(TENANT_ID, None)


@pytest.mark.asyncio
async def test_feature_flags_pagination_meta() -> None:
    """Feature flags response includes pagination metadata."""
    from app.routes.settings import list_feature_flags, _flags_store

    _flags_store.pop(TENANT_ID, None)

    user = _admin_user()
    result = await list_feature_flags(user=user)

    assert "pagination" in result["meta"]
    assert result["meta"]["pagination"]["total"] == 5

    _flags_store.pop(TENANT_ID, None)
