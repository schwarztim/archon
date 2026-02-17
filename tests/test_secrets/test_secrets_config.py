"""Tests for SecretsConfig pydantic-settings model."""

from __future__ import annotations

import pytest

from app.secrets.config import SecretsConfig


class TestDefaultValues:
    """Verify SecretsConfig ships sensible defaults."""

    def test_default_vault_addr(self) -> None:
        cfg = SecretsConfig()
        assert cfg.vault_addr == "http://localhost:8200"

    def test_default_vault_mount_point(self) -> None:
        cfg = SecretsConfig()
        assert cfg.vault_mount_point == "secret"

    def test_default_cache_ttl(self) -> None:
        cfg = SecretsConfig()
        assert cfg.cache_ttl_seconds == 300

    def test_default_vault_namespace(self) -> None:
        cfg = SecretsConfig()
        assert cfg.vault_namespace == "archon"

    def test_default_rotation_check_interval(self) -> None:
        cfg = SecretsConfig()
        assert cfg.rotation_check_interval_seconds == 3600


class TestCustomValues:
    """Verify env-var overrides via the ARCHON_ prefix."""

    def test_env_override_vault_addr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARCHON_VAULT_ADDR", "https://vault.prod:8200")
        cfg = SecretsConfig()
        assert cfg.vault_addr == "https://vault.prod:8200"

    def test_env_override_cache_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARCHON_CACHE_TTL_SECONDS", "60")
        cfg = SecretsConfig()
        assert cfg.cache_ttl_seconds == 60

    def test_env_override_mount_point(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARCHON_VAULT_MOUNT_POINT", "kv")
        cfg = SecretsConfig()
        assert cfg.vault_mount_point == "kv"
