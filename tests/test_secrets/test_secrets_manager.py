"""Tests for VaultSecretsManager — the Vault-backed secrets manager."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.secrets.config import SecretsConfig
from app.secrets.exceptions import (
    RotationError,
    SecretNotFoundError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_hvac_client() -> MagicMock:
    """Return a fully-mocked hvac.Client instance."""
    client = MagicMock(name="hvac.Client")

    # KV-v2 defaults
    client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"username": "admin", "password": "s3cret"}}
    }
    client.secrets.kv.v2.create_or_update_secret.return_value = {
        "data": {
            "version": 2,
            "created_time": "2026-01-15T10:00:00Z",
        }
    }
    client.secrets.kv.v2.list_secrets.return_value = {
        "data": {"keys": ["db-password", "api-key"]}
    }
    client.secrets.kv.v2.delete_metadata_and_all_versions.return_value = None

    # Health
    client.sys.read_health_status.return_value = {
        "initialized": True,
        "sealed": False,
        "cluster_name": "test-cluster",
    }

    return client


@pytest.fixture()
def _hvac_module_patch() -> Any:
    """Patch the hvac module on app.secrets.manager for the entire test.

    Yields the mock so other fixtures can configure it.  The patch stays
    active for the full duration of the test function.
    """
    mock_hvac_mod = MagicMock(name="hvac")
    mock_hvac_mod.exceptions = _make_hvac_exceptions()
    with patch("app.secrets.manager.hvac", mock_hvac_mod):
        yield mock_hvac_mod


@pytest.fixture()
def mock_secrets_manager(
    mock_hvac_client: MagicMock, tmp_path: Any, _hvac_module_patch: Any
) -> Any:
    """Build a VaultSecretsManager with a mocked hvac.Client.

    Uses tmp_path for a fake token file so _read_token works normally.
    The _hvac_module_patch fixture keeps the mock active for the whole test.
    """
    _hvac_module_patch.Client.return_value = mock_hvac_client

    token_file = tmp_path / "vault-token"
    token_file.write_text("s.fake-token-for-tests")

    config = SecretsConfig(
        vault_addr="http://vault-test:8200",
        vault_token_path=str(token_file),
        vault_namespace="archon",
        vault_mount_point="secret",
        cache_ttl_seconds=300,
    )

    from app.secrets.manager import VaultSecretsManager

    mgr = VaultSecretsManager(
        vault_addr=config.vault_addr,
        vault_token_path=config.vault_token_path,
        namespace=config.vault_namespace,
        config=config,
    )

    # Patch _get_client so every call returns our mock client
    mgr._get_client = MagicMock(return_value=mock_hvac_client)  # type: ignore[assignment]

    return mgr


# ---------------------------------------------------------------------------
# Helper: fake hvac.exceptions module
# ---------------------------------------------------------------------------


def _make_hvac_exceptions() -> MagicMock:
    """Create a mock that mimics hvac.exceptions with real exception classes."""
    mod = MagicMock()
    mod.InvalidPath = type("InvalidPath", (Exception,), {})
    mod.Forbidden = type("Forbidden", (Exception,), {})
    return mod


# ---------------------------------------------------------------------------
# Tests — get_secret
# ---------------------------------------------------------------------------


class TestGetSecret:
    """Tests for VaultSecretsManager.get_secret."""

    @pytest.mark.asyncio
    async def test_get_secret_valid(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Mock hvac client; verify correct path construction with tenant namespace."""
        result = await mock_secrets_manager.get_secret("db/password", "tenant-abc")

        assert result == {"username": "admin", "password": "s3cret"}
        mock_hvac_client.secrets.kv.v2.read_secret_version.assert_called_once_with(
            path="db/password",
            mount_point="secret",
        )
        # Verify tenant namespace isolation via _get_client
        mock_secrets_manager._get_client.assert_called_with("tenant-abc")

    @pytest.mark.asyncio
    async def test_get_secret_not_found(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Mock hvac raising InvalidPath; verify SecretNotFoundError raised."""
        # Use the exception class from the mocked hvac module in the manager
        import app.secrets.manager as mgr_module

        mock_hvac_client.secrets.kv.v2.read_secret_version.side_effect = (
            mgr_module.hvac.exceptions.InvalidPath("not found")
        )

        with pytest.raises(SecretNotFoundError) as exc_info:
            await mock_secrets_manager.get_secret("missing/path", "tenant-abc")

        assert "missing/path" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_secret_empty_tenant_id(
        self, mock_secrets_manager: Any
    ) -> None:
        """Verify ValueError raised when tenant_id is empty."""
        with pytest.raises(ValueError, match="tenant_id must not be None or empty"):
            await mock_secrets_manager.get_secret("any/path", "")

    @pytest.mark.asyncio
    async def test_get_secret_none_tenant_id(
        self, mock_secrets_manager: Any
    ) -> None:
        """Verify ValueError raised when tenant_id is None."""
        with pytest.raises(ValueError, match="tenant_id must not be None or empty"):
            await mock_secrets_manager.get_secret("any/path", None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests — put_secret
# ---------------------------------------------------------------------------


class TestPutSecret:
    """Tests for VaultSecretsManager.put_secret."""

    @pytest.mark.asyncio
    async def test_put_secret(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Mock hvac write; verify SecretMetadata returned with correct fields."""
        from app.interfaces.models.enterprise import SecretMetadata

        meta = await mock_secrets_manager.put_secret(
            "db/password", {"password": "new-pw"}, "tenant-abc"
        )

        assert isinstance(meta, SecretMetadata)
        assert meta.path == "db/password"
        assert meta.version == 2
        assert isinstance(meta.created_at, datetime)
        mock_hvac_client.secrets.kv.v2.create_or_update_secret.assert_called_once_with(
            path="db/password",
            secret={"password": "new-pw"},
            mount_point="secret",
        )


# ---------------------------------------------------------------------------
# Tests — delete_secret
# ---------------------------------------------------------------------------


class TestDeleteSecret:
    """Tests for VaultSecretsManager.delete_secret."""

    @pytest.mark.asyncio
    async def test_delete_secret(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Mock hvac delete; verify no exception."""
        await mock_secrets_manager.delete_secret("db/password", "tenant-abc")

        mock_hvac_client.secrets.kv.v2.delete_metadata_and_all_versions.assert_called_once_with(
            path="db/password",
            mount_point="secret",
        )


# ---------------------------------------------------------------------------
# Tests — list_secrets
# ---------------------------------------------------------------------------


class TestListSecrets:
    """Tests for VaultSecretsManager.list_secrets."""

    @pytest.mark.asyncio
    async def test_list_secrets(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Mock hvac list; verify list of SecretMetadata returned."""
        from app.interfaces.models.enterprise import SecretMetadata

        results = await mock_secrets_manager.list_secrets("app/", "tenant-abc")

        assert len(results) == 2
        assert all(isinstance(m, SecretMetadata) for m in results)
        assert results[0].path == "app/db-password"
        assert results[1].path == "app/api-key"


# ---------------------------------------------------------------------------
# Tests — rotate_secret
# ---------------------------------------------------------------------------


class TestRotateSecret:
    """Tests for VaultSecretsManager.rotate_secret."""

    @pytest.mark.asyncio
    async def test_rotate_secret(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Mock hvac read+write; verify new version returned."""
        meta = await mock_secrets_manager.rotate_secret("db/password", "tenant-abc")

        assert meta.version == 2
        assert meta.rotation_policy == "auto"
        # read then write → both should have been called
        mock_hvac_client.secrets.kv.v2.read_secret_version.assert_called()
        mock_hvac_client.secrets.kv.v2.create_or_update_secret.assert_called()

    @pytest.mark.asyncio
    async def test_rotate_secret_not_found(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Rotating a non-existent secret should raise RotationError."""
        import app.secrets.manager as mgr_module

        mock_hvac_client.secrets.kv.v2.read_secret_version.side_effect = (
            mgr_module.hvac.exceptions.InvalidPath("not found")
        )

        with pytest.raises(RotationError, match="does not exist"):
            await mock_secrets_manager.rotate_secret("missing/path", "tenant-abc")


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


class TestHealth:
    """Tests for VaultSecretsManager.health."""

    @pytest.mark.asyncio
    async def test_health(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Mock hvac health; verify dict returned."""
        # health() uses self._client directly, so patch it
        mock_secrets_manager._client = mock_hvac_client

        result = await mock_secrets_manager.health()

        assert isinstance(result, dict)
        assert result["status"] == "healthy"
        assert result["initialized"] is True
        assert result["sealed"] is False
        assert result["cluster_name"] == "test-cluster"


# ---------------------------------------------------------------------------
# Tests — tenant namespace isolation
# ---------------------------------------------------------------------------


class TestTenantNamespaceIsolation:
    """Verify different tenant_ids produce different Vault namespaces."""

    def test_tenant_namespace_isolation(self, mock_secrets_manager: Any) -> None:
        """Two different tenant_ids must produce different vault paths."""
        ns_a = mock_secrets_manager._get_tenant_namespace("tenant-a")
        ns_b = mock_secrets_manager._get_tenant_namespace("tenant-b")

        assert ns_a != ns_b
        assert "tenant-a" in ns_a
        assert "tenant-b" in ns_b


# ---------------------------------------------------------------------------
# Tests — caching
# ---------------------------------------------------------------------------


class TestCaching:
    """Verify the in-memory TTL cache reduces Vault calls."""

    @pytest.mark.asyncio
    async def test_cache_hit(
        self, mock_secrets_manager: Any, mock_hvac_client: MagicMock
    ) -> None:
        """Call get_secret twice; verify hvac only called once (cached)."""
        result1 = await mock_secrets_manager.get_secret("db/password", "tenant-abc")
        result2 = await mock_secrets_manager.get_secret("db/password", "tenant-abc")

        assert result1 == result2
        # hvac should have been invoked exactly once
        assert mock_hvac_client.secrets.kv.v2.read_secret_version.call_count == 1
