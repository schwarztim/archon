"""SSO configuration management API routes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as PField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models.sso_config import SSOConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sso", tags=["SSO"])

# Sentinel tenant_id used for the single-tenant global SSO config stored here.
# The full per-tenant CRUD lives in routes/sso_config.py (POST /api/v1/tenants/{id}/sso).
_GLOBAL_TENANT_ID = "__global__"
_GLOBAL_SSO_ID = "global"


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


# ── Helpers ─────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


async def _get_or_create_row(session: AsyncSession) -> SSOConfig:
    """Fetch the single global SSO config row, creating it if absent."""
    stmt = (
        select(SSOConfig)
        .where(SSOConfig.tenant_id == _GLOBAL_TENANT_ID)
        .where(SSOConfig.sso_id == _GLOBAL_SSO_ID)
    )
    result = await session.exec(stmt)
    row = result.first()
    if row is None:
        now = datetime.now(tz=timezone.utc)
        row = SSOConfig(
            tenant_id=_GLOBAL_TENANT_ID,
            sso_id=_GLOBAL_SSO_ID,
            name="global",
            protocol="",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def _row_to_config_data(row: SSOConfig) -> dict[str, Any]:
    """Convert DB row back to the SSOConfigData-shaped dict."""
    return {
        "protocol": row.protocol or None,
        "oidc": {
            "discovery_url": row.discovery_url,
            "client_id": row.client_id,
            "client_secret_set": row.client_secret_set,
            "scopes": row.scopes or ["openid", "profile", "email"],
            "redirect_uri": "",
            "claim_mapping": {
                "email_claim": "email",
                "name_claim": "name",
                "role_claim": "roles",
                "tenant_claim": "tenant_id",
            },
        },
        "saml": {
            "metadata_url": row.metadata_url,
            "entity_id": row.entity_id,
            "acs_url": row.acs_url,
            "certificate": "",
            "attribute_mapping": {
                "email_attr": "email",
                "name_attr": "name",
                "role_attr": "roles",
                "tenant_attr": "tenant_id",
            },
        },
    }


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/config")
async def get_sso_config(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get current SSO configuration (DB-backed).

    Client secrets are never returned; only a boolean indicating
    whether one has been set.
    """
    request_id = str(uuid4())
    row = await _get_or_create_row(session)
    data = _row_to_config_data(row)
    return {
        "data": data,
        "meta": _meta(request_id=request_id),
    }


@router.put("/config")
async def update_sso_config(
    body: SSOConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update SSO configuration (DB-backed).

    Client secrets are stored separately and never echoed back.
    """
    request_id = str(uuid4())
    row = await _get_or_create_row(session)

    if body.protocol is not None:
        row.protocol = body.protocol
    if body.oidc is not None:
        row.discovery_url = body.oidc.discovery_url
        row.client_id = body.oidc.client_id
        row.scopes = body.oidc.scopes
    if body.saml is not None:
        row.metadata_url = body.saml.metadata_url
        row.entity_id = body.saml.entity_id
        row.acs_url = body.saml.acs_url
        if body.saml.certificate:
            row.certificate_set = True
    if body.client_secret is not None:
        # In production this would go to Vault; here we mark it as set
        row.client_secret_set = bool(body.client_secret)

    row.updated_at = datetime.now(tz=timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)

    logger.info(
        "SSO config updated",
        extra={"request_id": request_id, "protocol": row.protocol},
    )

    data = _row_to_config_data(row)
    return {
        "data": data,
        "meta": _meta(request_id=request_id),
    }


@router.post("/test-connection")
async def test_sso_connection(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Test SSO IdP connectivity.

    Validates that the configured IdP is reachable and responds
    correctly by fetching the OIDC discovery document or SAML metadata.
    """
    request_id = str(uuid4())
    logger.info("SSO connection test requested", extra={"request_id": request_id})

    row = await _get_or_create_row(session)
    protocol = row.protocol or ""

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
        discovery_url = row.discovery_url
        if not discovery_url:
            return {
                "data": {"status": "error", "message": "OIDC discovery URL is not configured."},
                "meta": _meta(request_id=request_id),
            }
        target_url = (
            discovery_url
            if "/.well-known/" in discovery_url
            else discovery_url.rstrip("/") + "/.well-known/openid-configuration"
        )
    elif protocol == "saml":
        target_url = row.metadata_url
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
