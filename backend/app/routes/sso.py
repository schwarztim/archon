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
    correctly by fetching the OIDC discovery document or SAML metadata.
    """
    request_id = str(uuid4())

    logger.info("SSO connection test requested", extra={"request_id": request_id})

    protocol = _sso_config.protocol
    if not protocol:
        return {
            "data": {
                "status": "error",
                "message": "No SSO protocol configured. Set protocol to 'oidc' or 'saml' first.",
            },
            "meta": _meta(request_id=request_id),
        }

    import httpx

    target_url: str = ""
    if protocol == "oidc":
        discovery_url = _sso_config.oidc.discovery_url
        if not discovery_url:
            return {
                "data": {"status": "error", "message": "OIDC discovery URL is not configured."},
                "meta": _meta(request_id=request_id),
            }
        # Append well-known path if not already present
        target_url = (
            discovery_url
            if "/.well-known/" in discovery_url
            else discovery_url.rstrip("/") + "/.well-known/openid-configuration"
        )
    elif protocol == "saml":
        target_url = _sso_config.saml.metadata_url
        if not target_url:
            return {
                "data": {"status": "error", "message": "SAML metadata URL is not configured."},
                "meta": _meta(request_id=request_id),
            }
    else:
        return {
            "data": {"status": "error", "message": f"Unsupported protocol: {protocol}"},
            "meta": _meta(request_id=request_id),
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(target_url)
            resp.raise_for_status()

        logger.info(
            "SSO connection test succeeded",
            extra={"request_id": request_id, "protocol": protocol, "url": target_url},
        )
        return {
            "data": {
                "status": "success",
                "message": f"{protocol.upper()} provider is reachable and returned HTTP {resp.status_code}.",
                "protocol": protocol,
                "url_tested": target_url,
            },
            "meta": _meta(request_id=request_id),
        }
    except httpx.TimeoutException:
        msg = f"Connection to {protocol.upper()} provider timed out ({target_url})."
        logger.warning("SSO connection test timeout", extra={"request_id": request_id, "url": target_url})
        return {
            "data": {"status": "error", "message": msg, "protocol": protocol, "url_tested": target_url},
            "meta": _meta(request_id=request_id),
        }
    except httpx.HTTPStatusError as exc:
        msg = f"{protocol.upper()} provider returned HTTP {exc.response.status_code}."
        logger.warning("SSO connection test HTTP error", extra={"request_id": request_id, "status": exc.response.status_code})
        return {
            "data": {"status": "error", "message": msg, "protocol": protocol, "url_tested": target_url},
            "meta": _meta(request_id=request_id),
        }
    except Exception as exc:
        msg = f"Failed to reach {protocol.upper()} provider: {exc}"
        logger.warning("SSO connection test failed", extra={"request_id": request_id, "error": str(exc)})
        return {
            "data": {"status": "error", "message": msg, "protocol": protocol, "url_tested": target_url},
            "meta": _meta(request_id=request_id),
        }
