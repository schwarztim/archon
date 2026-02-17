"""Abstract interface for enterprise secrets management."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.interfaces.models.enterprise import (
    CertificateBundle,
    DynamicCredential,
    SecretMetadata,
)


@runtime_checkable
class SecretsManager(Protocol):
    """Contract for secrets management backends (e.g. HashiCorp Vault)."""

    async def get_secret(self, path: str, tenant_id: str) -> dict:
        """Retrieve a secret value by path, scoped to tenant."""
        ...

    async def put_secret(
        self, path: str, data: dict, tenant_id: str
    ) -> SecretMetadata:
        """Store or update a secret, returning its metadata."""
        ...

    async def delete_secret(self, path: str, tenant_id: str) -> None:
        """Delete a secret by path, scoped to tenant."""
        ...

    async def list_secrets(
        self, prefix: str, tenant_id: str
    ) -> list[SecretMetadata]:
        """List secret metadata under a given prefix."""
        ...

    async def rotate_secret(
        self, path: str, tenant_id: str
    ) -> SecretMetadata:
        """Trigger rotation for a secret and return updated metadata."""
        ...

    async def issue_certificate(
        self, common_name: str, tenant_id: str, ttl: str
    ) -> CertificateBundle:
        """Issue a TLS certificate via the PKI backend."""
        ...

    async def get_dynamic_credential(
        self, engine: str, role: str, tenant_id: str
    ) -> DynamicCredential:
        """Generate a short-lived credential from a secrets engine."""
        ...


__all__ = ["SecretsManager"]
