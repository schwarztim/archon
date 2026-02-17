"""Pydantic settings for the SecretsManager SDK."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class SecretsConfig(BaseSettings):
    """Configuration for the Vault-backed secrets manager.

    All fields can be overridden via environment variables prefixed with
    ``ARCHON_`` (e.g. ``ARCHON_VAULT_ADDR``).
    """

    vault_addr: str = "http://localhost:8200"
    vault_token_path: str = "/var/run/secrets/vault-token"
    vault_namespace: str = "archon"
    vault_mount_point: str = "secret"
    cache_ttl_seconds: int = 300
    rotation_check_interval_seconds: int = 3600

    model_config = {"env_prefix": "ARCHON_"}


__all__ = ["SecretsConfig"]
