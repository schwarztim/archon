"""Tests for secrets vault enhancement — routes, access logger, and models."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser, SecretMetadata
from app.services.secret_access_logger import SecretAccessLogger, SecretAccessEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_user() -> AuthenticatedUser:
    """Return a test authenticated user with admin role."""
    return AuthenticatedUser(
        id=str(uuid4()),
        email="admin@test.com",
        tenant_id=str(uuid4()),
        roles=["admin"],
        permissions=["secrets:create", "secrets:read", "secrets:update", "secrets:delete", "secrets:admin"],
        session_id="test-session",
    )


@pytest.fixture()
def access_logger() -> SecretAccessLogger:
    """Return a fresh SecretAccessLogger instance."""
    return SecretAccessLogger()


@pytest.fixture()
def stub_secrets_manager() -> Any:
    """Return an in-memory stub secrets manager."""
    from app.secrets.manager import _StubSecretsManager

    return _StubSecretsManager()


# ---------------------------------------------------------------------------
# Tests — SecretAccessLogger
# ---------------------------------------------------------------------------


class TestSecretAccessLogger:
    """Tests for the SecretAccessLogger service."""

    def test_log_access_creates_entry(self, access_logger: SecretAccessLogger) -> None:
        """Logging an access event should create an entry."""
        access_logger.log_access(
            tenant_id="tenant-1",
            secret_path="db/password",
            user_id="user-1",
            user_email="admin@test.com",
            action="read",
            component="secrets_api",
        )

        entries, total = access_logger.get_access_log("db/password", "tenant-1")
        assert total == 1
        assert entries[0].action == "read"
        assert entries[0].user_email == "admin@test.com"

    def test_log_access_tenant_isolation(self, access_logger: SecretAccessLogger) -> None:
        """Access logs should be isolated by tenant_id."""
        access_logger.log_access(
            tenant_id="tenant-a",
            secret_path="key",
            action="read",
        )
        access_logger.log_access(
            tenant_id="tenant-b",
            secret_path="key",
            action="write",
        )

        entries_a, total_a = access_logger.get_access_log("key", "tenant-a")
        entries_b, total_b = access_logger.get_access_log("key", "tenant-b")

        assert total_a == 1
        assert total_b == 1
        assert entries_a[0].action == "read"
        assert entries_b[0].action == "write"

    def test_log_access_path_filtering(self, access_logger: SecretAccessLogger) -> None:
        """Access logs should filter by secret path."""
        access_logger.log_access(tenant_id="t", secret_path="path-a", action="read")
        access_logger.log_access(tenant_id="t", secret_path="path-b", action="write")

        entries, total = access_logger.get_access_log("path-a", "t")
        assert total == 1
        assert entries[0].secret_path == "path-a"

    def test_log_access_pagination(self, access_logger: SecretAccessLogger) -> None:
        """Access log should support limit/offset pagination."""
        for i in range(5):
            access_logger.log_access(
                tenant_id="t",
                secret_path="key",
                action=f"action-{i}",
            )

        entries, total = access_logger.get_access_log("key", "t", limit=2, offset=0)
        assert total == 5
        assert len(entries) == 2

        entries2, _ = access_logger.get_access_log("key", "t", limit=2, offset=2)
        assert len(entries2) == 2

    def test_get_all_access_logs(self, access_logger: SecretAccessLogger) -> None:
        """get_all_access_logs returns all entries for a tenant."""
        access_logger.log_access(tenant_id="t", secret_path="a", action="read")
        access_logger.log_access(tenant_id="t", secret_path="b", action="write")

        entries, total = access_logger.get_all_access_logs("t")
        assert total == 2

    def test_access_entry_model(self, access_logger: SecretAccessLogger) -> None:
        """SecretAccessEntry should have all expected fields."""
        access_logger.log_access(
            tenant_id="t",
            secret_path="test/path",
            user_id="uid",
            user_email="user@test.com",
            action="rotate",
            component="rotation_engine",
            ip_address="10.0.0.1",
            details="scheduled rotation",
        )

        entries, _ = access_logger.get_access_log("test/path", "t")
        e = entries[0]
        assert isinstance(e, SecretAccessEntry)
        assert e.secret_path == "test/path"
        assert e.user_email == "user@test.com"
        assert e.action == "rotate"
        assert e.component == "rotation_engine"
        assert e.ip_address == "10.0.0.1"
        assert e.details == "scheduled rotation"
        assert e.id  # should have a UUID
        assert e.created_at  # should have a timestamp


# ---------------------------------------------------------------------------
# Tests — SecretMetadata model extensions
# ---------------------------------------------------------------------------


class TestSecretMetadataModel:
    """Tests for the extended SecretMetadata Pydantic model."""

    def test_default_fields(self) -> None:
        """SecretMetadata should have all new default fields."""
        meta = SecretMetadata(
            path="test",
            version=1,
            created_at=datetime.now(timezone.utc),
        )
        assert meta.secret_type == "custom"
        assert meta.auto_rotate is False
        assert meta.notify_before_days == 14
        assert meta.last_rotated_at is None
        assert meta.rotation_policy_days is None
        assert meta.id == ""

    def test_all_fields_set(self) -> None:
        """SecretMetadata should accept all extended fields."""
        now = datetime.now(timezone.utc)
        meta = SecretMetadata(
            id="abc-123",
            path="providers/openai/key",
            version=3,
            created_at=now,
            updated_at=now,
            expires_at=now,
            rotation_policy="auto",
            secret_type="api_key",
            last_rotated_at=now,
            rotation_policy_days=30,
            auto_rotate=True,
            notify_before_days=7,
        )
        assert meta.id == "abc-123"
        assert meta.secret_type == "api_key"
        assert meta.auto_rotate is True
        assert meta.rotation_policy_days == 30

    def test_model_dump_json(self) -> None:
        """model_dump(mode='json') should serialize all fields."""
        meta = SecretMetadata(
            path="test",
            version=1,
            created_at=datetime.now(timezone.utc),
            secret_type="password",
        )
        dumped = meta.model_dump(mode="json")
        assert "secret_type" in dumped
        assert "auto_rotate" in dumped
        assert "notify_before_days" in dumped
        assert dumped["secret_type"] == "password"


# ---------------------------------------------------------------------------
# Tests — SecretRegistration model extensions
# ---------------------------------------------------------------------------


class TestSecretRegistrationModel:
    """Tests for the extended SecretRegistration SQLModel."""

    def test_new_fields_exist(self) -> None:
        """SecretRegistration should have new fields."""
        from app.models.secrets import SecretRegistration

        reg = SecretRegistration(
            path="test/path",
            tenant_id=uuid4(),
            secret_type="api_key",
            auto_rotate=True,
            notify_before_days=7,
        )
        assert reg.secret_type == "api_key"
        assert reg.auto_rotate is True
        assert reg.notify_before_days == 7
        assert reg.expires_at is None
        assert reg.updated_at is not None

    def test_access_log_model(self) -> None:
        """SecretAccessLog model should be importable and constructable."""
        from app.models.secrets import SecretAccessLog

        log = SecretAccessLog(
            tenant_id=uuid4(),
            secret_path="test/path",
            user_id=uuid4(),
            user_email="user@test.com",
            action="read",
            component="api",
        )
        assert log.action == "read"
        assert log.user_email == "user@test.com"


# ---------------------------------------------------------------------------
# Tests — Stub secrets manager health
# ---------------------------------------------------------------------------


class TestStubSecretsManagerHealth:
    """Test the health method on the stub secrets manager."""

    @pytest.mark.asyncio
    async def test_stub_health(self, stub_secrets_manager: Any) -> None:
        """Stub health should return stub status."""
        health = await stub_secrets_manager.health()
        assert health["status"] == "stub"


# ---------------------------------------------------------------------------
# Tests — Routes (schema validation)
# ---------------------------------------------------------------------------


class TestRouteSchemas:
    """Test that route request/response schemas are valid."""

    def test_secret_create_schema(self) -> None:
        """SecretCreate should accept new fields."""
        from app.routes.secrets import SecretCreate

        body = SecretCreate(
            path="test/key",
            data={"value": "secret"},
            secret_type="api_key",
            rotation_policy_days=30,
            auto_rotate=True,
            notify_before_days=7,
        )
        assert body.secret_type == "api_key"
        assert body.auto_rotate is True

    def test_rotate_request_schema(self) -> None:
        """RotateRequest should accept new_value field."""
        from app.routes.secrets import RotateRequest

        body = RotateRequest(reason="test", new_value={"key": "new-value"})
        assert body.new_value == {"key": "new-value"}

    def test_rotation_policy_update_schema(self) -> None:
        """RotationPolicyUpdate should validate bounds."""
        from app.routes.secrets import RotationPolicyUpdate

        policy = RotationPolicyUpdate(
            rotation_policy_days=90,
            auto_rotate=True,
            notify_before_days=14,
        )
        assert policy.rotation_policy_days == 90

    def test_vault_status_response_schema(self) -> None:
        """VaultStatusResponse should serialize correctly."""
        from app.routes.secrets import VaultStatusResponse

        resp = VaultStatusResponse(
            mode="connected",
            initialized=True,
            sealed=False,
            cluster_name="prod-cluster",
            message="Vault is healthy",
        )
        assert resp.mode == "connected"
        assert resp.cluster_name == "prod-cluster"

    def test_rotation_dashboard_item_schema(self) -> None:
        """RotationDashboardItem should serialize correctly."""
        from app.routes.secrets import RotationDashboardItem

        item = RotationDashboardItem(
            path="test/key",
            secret_type="api_key",
            rotation_status="approaching",
            last_rotated_at="2025-01-01T00:00:00Z",
            next_rotation_at="2025-02-01T00:00:00Z",
            days_until_rotation=10,
        )
        assert item.rotation_status == "approaching"
        assert item.days_until_rotation == 10


# ---------------------------------------------------------------------------
# Tests — Route function integration (with stub manager)
# ---------------------------------------------------------------------------


class TestRouteIntegration:
    """Integration tests for route handlers using stub secrets manager."""

    @pytest.mark.asyncio
    async def test_create_and_list_secrets(
        self, stub_secrets_manager: Any, test_user: AuthenticatedUser
    ) -> None:
        """Creating a secret should make it appear in list."""
        await stub_secrets_manager.put_secret(
            "test/key", {"value": "s3cret"}, test_user.tenant_id,
        )

        results = await stub_secrets_manager.list_secrets("", test_user.tenant_id)
        assert len(results) >= 1
        paths = [r.path for r in results]
        assert "test/key" in paths

    @pytest.mark.asyncio
    async def test_rotate_secret_increments_version(
        self, stub_secrets_manager: Any, test_user: AuthenticatedUser
    ) -> None:
        """Rotating a secret should increment the version."""
        await stub_secrets_manager.put_secret(
            "rot/key", {"value": "v1"}, test_user.tenant_id,
        )

        meta = await stub_secrets_manager.rotate_secret("rot/key", test_user.tenant_id)
        assert meta.version == 2

    @pytest.mark.asyncio
    async def test_delete_secret_removes_it(
        self, stub_secrets_manager: Any, test_user: AuthenticatedUser
    ) -> None:
        """Deleting a secret should remove it from list."""
        await stub_secrets_manager.put_secret(
            "del/key", {"value": "v1"}, test_user.tenant_id,
        )
        await stub_secrets_manager.delete_secret("del/key", test_user.tenant_id)

        results = await stub_secrets_manager.list_secrets("", test_user.tenant_id)
        paths = [r.path for r in results]
        assert "del/key" not in paths

    @pytest.mark.asyncio
    async def test_stub_tenant_isolation(
        self, stub_secrets_manager: Any
    ) -> None:
        """Secrets should be isolated between tenants."""
        await stub_secrets_manager.put_secret("shared/key", {"v": "1"}, "tenant-a")
        await stub_secrets_manager.put_secret("shared/key", {"v": "2"}, "tenant-b")

        val_a = await stub_secrets_manager.get_secret("shared/key", "tenant-a")
        val_b = await stub_secrets_manager.get_secret("shared/key", "tenant-b")

        assert val_a["v"] == "1"
        assert val_b["v"] == "2"

    @pytest.mark.asyncio
    async def test_access_logger_with_rotation(
        self, access_logger: SecretAccessLogger, test_user: AuthenticatedUser
    ) -> None:
        """Access logger should record rotation events."""
        access_logger.log_access(
            tenant_id=test_user.tenant_id,
            secret_path="rot/key",
            user_id=test_user.id,
            user_email=test_user.email,
            action="rotate",
            component="secrets_api",
            details="Manual rotation from UI",
        )

        entries, total = access_logger.get_access_log("rot/key", test_user.tenant_id)
        assert total == 1
        assert entries[0].action == "rotate"
        assert entries[0].details == "Manual rotation from UI"


# ---------------------------------------------------------------------------
# Tests — Registration store helpers
# ---------------------------------------------------------------------------


class TestRegistrationStore:
    """Test the in-memory registration store helpers."""

    def test_set_get_delete(self) -> None:
        """Registration CRUD operations should work."""
        from app.routes.secrets import _set_registration, _get_registration, _delete_registration

        _set_registration("t1", "path/a", {"secret_type": "api_key"})

        reg = _get_registration("t1", "path/a")
        assert reg is not None
        assert reg["secret_type"] == "api_key"

        # Tenant isolation
        assert _get_registration("t2", "path/a") is None

        _delete_registration("t1", "path/a")
        assert _get_registration("t1", "path/a") is None

    def test_delete_nonexistent_no_error(self) -> None:
        """Deleting a non-existent registration should not raise."""
        from app.routes.secrets import _delete_registration

        _delete_registration("t-missing", "no-such-path")  # should not raise
