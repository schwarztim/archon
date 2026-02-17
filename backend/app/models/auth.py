"""SQLModel database models for enterprise authentication and identity."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column
from sqlalchemy import Text as SAText
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    """Return naive UTC timestamp (no tzinfo) for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.utcnow()


class UserIdentity(SQLModel, table=True):
    """Enterprise user identity linked to external IdP (Keycloak/SAML/SCIM)."""

    __tablename__ = "user_identities"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(index=True)
    display_name: str
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")
    keycloak_id: str = Field(unique=True, index=True)
    scim_external_id: str | None = Field(default=None, index=True)
    mfa_enabled: bool = Field(default=False)
    mfa_method: str | None = Field(default=None)
    last_login: datetime | None = Field(default=None)
    status: str = Field(default="active")  # active | suspended | deprovisioned
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class UserRole(SQLModel, table=True):
    """Role assignment linking a user identity to an RBAC role within a tenant."""

    __tablename__ = "user_roles"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="user_identities.id")
    role_name: str = Field(index=True)
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")
    assigned_by: UUID | None = Field(default=None, foreign_key="user_identities.id")
    assigned_at: datetime = Field(default_factory=_utcnow)


class APIKey(SQLModel, table=True):
    """Hashed API key for programmatic access with scoped permissions."""

    __tablename__ = "api_keys"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="user_identities.id")
    key_hash: str
    name: str
    tenant_id: UUID = Field(index=True, foreign_key="tenants.id")
    scopes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    expires_at: datetime | None = Field(default=None)
    last_used_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    revoked: bool = Field(default=False)


class SAMLProvider(SQLModel, table=True):
    """SAML 2.0 identity provider configuration per tenant."""

    __tablename__ = "saml_providers"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: UUID = Field(unique=True, index=True, foreign_key="tenants.id")
    entity_id: str
    metadata_url: str
    signing_cert: str = Field(sa_column=Column(SAText, nullable=False))
    name_id_format: str = Field(default="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress")
    attribute_mapping: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False),
    )
    enabled: bool = Field(default=True)


__all__ = [
    "APIKey",
    "SAMLProvider",
    "UserIdentity",
    "UserRole",
]
