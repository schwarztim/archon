"""Abstract interface for multi-tenant lifecycle management."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.interfaces.models.enterprise import (
    IdPConfig,
    TenantConfig,
    TenantContext,
)


@runtime_checkable
class TenantManager(Protocol):
    """Contract for tenant provisioning and configuration backends."""

    async def create_tenant(self, config: TenantConfig) -> TenantContext:
        """Provision a new tenant with the given configuration."""
        ...

    async def get_tenant(self, tenant_id: str) -> TenantContext:
        """Retrieve the context for an existing tenant."""
        ...

    async def configure_idp(
        self, tenant_id: str, idp_config: IdPConfig
    ) -> None:
        """Configure the identity provider for a tenant."""
        ...

    async def get_tenant_vault_namespace(self, tenant_id: str) -> str:
        """Return the Vault namespace path for a tenant."""
        ...


__all__ = ["TenantManager"]
