"""SQLModel database models for enterprise tenant configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class TenantConfiguration(SQLModel, table=True):
    """Enterprise-specific configuration for a tenant (Vault, Keycloak, SCIM, billing)."""

    __tablename__ = "tenant_configurations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(unique=True, index=True, foreign_key="tenants.id")
    vault_namespace: str | None = Field(default=None)
    keycloak_realm: str | None = Field(default=None)
    scim_endpoint: str | None = Field(default=None)
    billing_plan: str = Field(default="free")
    max_users: int = Field(default=5)
    max_agents: int = Field(default=10)
    features: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


__all__ = [
    "TenantConfiguration",
]
