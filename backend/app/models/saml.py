"""Pydantic models for SAML 2.0 SSO configuration and assertions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SAMLAttributeMapping(BaseModel):
    """Maps SAML assertion attributes to internal user profile fields."""

    email: str = Field(
        default="urn:oid:0.9.2342.19200300.100.1.3",
        description="SAML attribute name for email",
    )
    display_name: str = Field(
        default="urn:oid:2.16.840.1.113730.3.1.241",
        description="SAML attribute name for display name",
    )
    first_name: str = Field(
        default="urn:oid:2.5.4.42",
        description="SAML attribute name for first name",
    )
    last_name: str = Field(
        default="urn:oid:2.5.4.4",
        description="SAML attribute name for last name",
    )
    groups: str = Field(
        default="memberOf",
        description="SAML attribute name for group membership",
    )


class SAMLIdPConfig(BaseModel):
    """Configuration for a SAML 2.0 Identity Provider bound to a tenant."""

    tenant_id: str
    entity_id: str
    sso_url: str
    slo_url: str = ""
    signing_cert_fingerprint: str = ""
    name_id_format: str = Field(
        default="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
    )
    attribute_mapping: SAMLAttributeMapping = Field(
        default_factory=SAMLAttributeMapping,
    )
    metadata_url: str = ""
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SAMLRequest(BaseModel):
    """SAML AuthnRequest redirect payload."""

    redirect_url: str
    request_id: str
    relay_state: str = ""


class SAMLAssertion(BaseModel):
    """Parsed and validated SAML assertion data."""

    subject_name_id: str
    session_index: str = ""
    issuer: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    not_before: datetime | None = None
    not_on_or_after: datetime | None = None
    authn_instant: datetime | None = None


__all__ = [
    "SAMLAttributeMapping",
    "SAMLAssertion",
    "SAMLIdPConfig",
    "SAMLRequest",
]
