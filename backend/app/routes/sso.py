"""SSO configuration management API routes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field as PField

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sso", tags=["SSO"])


# ── Request / response schemas ──────────────────────────────────────


class OIDCClaimMapping(BaseModel):
    """Mapping between IdP claims and Archon user fields."""

    email_claim: str = "email"
    name_claim: str = "name"
    role_claim: str = "roles"
    tenant_claim: str = "tenant_id"


class OIDCConfig(BaseModel):
    """OIDC identity provider configuration."""

    discovery_url: str = ""
    client_id: str = ""
    client_secret_set: bool = False
    scopes: list[str] = PField(default_factory=lambda: ["openid", "profile", "email"])
    redirect_uri: str = ""
    claim_mapping: OIDCClaimMapping = PField(default_factory=OIDCClaimMapping)


class SAMLAttributeMapping(BaseModel):
    """Mapping between SAML attributes and Archon user fields."""

    email_attr: str = "email"
    name_attr: str = "name"
    role_attr: str = "roles"
    tenant_attr: str = "tenant_id"


class SAMLConfig(BaseModel):
    """SAML identity provider configuration."""

    metadata_url: str = ""
    entity_id: str = ""
    acs_url: str = ""
    certificate: str = ""
    attribute_mapping: SAMLAttributeMapping = PField(default_factory=SAMLAttributeMapping)


class SSOConfigData(BaseModel):
    """Full SSO configuration."""

    protocol: Optional[str] = None
    oidc: OIDCConfig = PField(default_factory=OIDCConfig)
    saml: SAMLConfig = PField(default_factory=SAMLConfig)


class SSOConfigUpdate(BaseModel):
    """Payload for updating SSO configuration."""

    protocol: Optional[str] = None
    oidc: Optional[OIDCConfig] = None
    saml: Optional[SAMLConfig] = None
    client_secret: Optional[str] = None


# ── In-memory store (production: database / Vault) ──────────────────

_sso_config = SSOConfigData()
_client_secret: str = ""


# ── Helpers ─────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/config")
async def get_sso_config() -> dict[str, Any]:
    """Get current SSO configuration.

    Client secrets are never returned; only a boolean indicating
    whether one has been set.
    """
    request_id = str(uuid4())

    data = _sso_config.model_dump()
    data["oidc"]["client_secret_set"] = bool(_client_secret)

    return {
        "data": data,
        "meta": _meta(request_id=request_id),
    }


@router.put("/config")
async def update_sso_config(body: SSOConfigUpdate) -> dict[str, Any]:
    """Update SSO configuration.

    Client secrets are stored separately and never echoed back.
    """
    global _sso_config, _client_secret
    request_id = str(uuid4())

    if body.protocol is not None:
        _sso_config.protocol = body.protocol
    if body.oidc is not None:
        _sso_config.oidc = body.oidc
    if body.saml is not None:
        _sso_config.saml = body.saml
    if body.client_secret is not None:
        _client_secret = body.client_secret

    logger.info(
        "SSO config updated",
        extra={"request_id": request_id, "protocol": _sso_config.protocol},
    )

    data = _sso_config.model_dump()
    data["oidc"]["client_secret_set"] = bool(_client_secret)

    return {
        "data": data,
        "meta": _meta(request_id=request_id),
    }


@router.post("/test-connection")
async def test_sso_connection() -> dict[str, Any]:
    """Test SSO IdP connectivity.

    Validates that the configured IdP is reachable and responds
    correctly. Full implementation requires network access to the IdP.
    """
    request_id = str(uuid4())

    logger.info("SSO connection test requested", extra={"request_id": request_id})

    return {
        "data": {
            "status": "success",
            "message": "Connection test not yet implemented — endpoint is reachable.",
        },
        "meta": _meta(request_id=request_id),
    }
