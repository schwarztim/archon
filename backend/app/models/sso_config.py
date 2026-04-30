"""SQLModel table definition for persisted SSO configurations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class SSOConfig(SQLModel, table=True):
    """Persistent SSO/IdP configuration per tenant.

    Replaces the ``_sso_configs`` in-memory dict in
    ``backend/app/routes/sso_config.py``.
    """

    __tablename__ = "sso_configs"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tenant_id: str = Field(index=True)
    sso_id: str = Field(index=True, unique=True)  # caller-assigned ID

    name: str
    protocol: str  # "oidc" | "saml" | "ldap"
    is_default: bool = False
    enabled: bool = True

    # OIDC fields
    discovery_url: str = ""
    client_id: str = ""
    scopes: Optional[Any] = Field(default_factory=list, sa_column=Column(JSON))

    # SAML fields
    metadata_url: str = ""
    metadata_xml: str = ""
    entity_id: str = ""
    acs_url: str = ""

    # LDAP fields
    host: str = ""
    port: int = 389
    use_tls: bool = False
    base_dn: str = ""
    bind_dn: str = ""
    user_filter: str = "(objectClass=person)"
    group_filter: str = "(objectClass=group)"

    # Whether the protocol-specific secret has been stored in Vault
    client_secret_set: bool = False
    certificate_set: bool = False
    bind_secret_set: bool = False

    # Claim/attribute mappings stored as JSON array
    claim_mappings: Optional[Any] = Field(default_factory=list, sa_column=Column(JSON))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
