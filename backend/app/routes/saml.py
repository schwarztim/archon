"""SAML 2.0 SSO routes for enterprise single sign-on."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import require_auth
from app.middleware.rbac import check_permission
from app.models.audit import EnterpriseAuditEvent
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.saml_service import SAMLService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/saml", tags=["SAML SSO"])


# ── Request / response schemas ──────────────────────────────────────


class SAMLLoginRequest(BaseModel):
    """SP-initiated SSO request payload."""

    idp_entity_id: str = ""
    relay_state: str = ""


class SAMLACSRequest(BaseModel):
    """SAML Assertion Consumer Service callback payload."""

    SAMLResponse: str
    RelayState: str = ""


class SAMLConfigureRequest(BaseModel):
    """Configure a new IdP for a tenant."""

    metadata_url_or_xml: str


class SAMLLogoutRequest(BaseModel):
    """Single Logout request payload."""

    session_index: str = ""


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _audit_event(
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    *,
    user: AuthenticatedUser | None = None,
    tenant_id: str | None = None,
) -> EnterpriseAuditEvent:
    """Create an audit event for SAML operations."""
    resolved_tenant = tenant_id or (user.tenant_id if user else "")
    return EnterpriseAuditEvent(
        tenant_id=UUID(resolved_tenant) if resolved_tenant else UUID(int=0),
        user_id=UUID(user.id) if user else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        session_id=user.session_id if user else None,
    )


async def _get_saml_service(
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> SAMLService:
    """FastAPI dependency to construct a SAMLService instance."""
    return SAMLService(secrets=secrets)


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/login")
async def saml_login(
    body: SAMLLoginRequest,
    user: AuthenticatedUser = Depends(require_auth),
    saml_service: SAMLService = Depends(_get_saml_service),
) -> dict[str, Any]:
    """SP-initiated SSO — redirect the user to the configured IdP.

    Generates a SAML AuthnRequest and returns the redirect URL.
    """
    request_id = str(uuid4())

    saml_request = await saml_service.generate_authn_request(
        tenant_id=user.tenant_id,
        idp_entity_id=body.idp_entity_id,
    )

    audit = _audit_event(
        "saml.login.initiated", "saml_session", saml_request.request_id,
        {"idp_entity_id": body.idp_entity_id, "relay_state": body.relay_state},
        user=user,
    )
    logger.info(
        "SAML SP-initiated login",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": saml_request.model_dump(),
        "meta": _meta(request_id=request_id),
    }


@router.post("/acs")
async def saml_acs(
    body: SAMLACSRequest,
    saml_service: SAMLService = Depends(_get_saml_service),
) -> dict[str, Any]:
    """Assertion Consumer Service — process IdP SAML response (unauthenticated).

    Validates the SAML assertion and returns a session token for the
    authenticated user.
    """
    request_id = str(uuid4())

    # Extract tenant_id from RelayState (format: "tenant=<id>")
    tenant_id = ""
    if body.RelayState:
        for part in body.RelayState.split("&"):
            if part.startswith("tenant="):
                tenant_id = part.split("=", 1)[1]
                break

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing tenant_id in RelayState",
        )

    try:
        authed_user = await saml_service.process_saml_response(
            saml_response_b64=body.SAMLResponse,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        audit = _audit_event(
            "saml.acs.failed", "saml_session",
            details={"error": str(exc)},
            tenant_id=tenant_id,
        )
        logger.warning(
            "SAML ACS validation failed",
            extra={"request_id": request_id, "audit_id": str(audit.id)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SAML assertion validation failed",
        ) from exc

    session_data = {
        "user_id": authed_user.id,
        "email": authed_user.email,
        "tenant_id": authed_user.tenant_id,
        "access_token": "",
        "token_type": "bearer",
        "relay_state": body.RelayState,
    }

    audit = _audit_event(
        "saml.acs.success", "saml_session",
        details={"email": authed_user.email},
        tenant_id=tenant_id,
    )
    logger.info(
        "SAML ACS callback processed",
        extra={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": session_data,
        "meta": _meta(request_id=request_id),
    }


@router.get("/metadata/{tenant_id}")
async def saml_metadata(
    tenant_id: str,
    saml_service: SAMLService = Depends(_get_saml_service),
) -> Response:
    """Return SAML SP metadata XML for a tenant (unauthenticated, /.well-known).

    Provides the SP entity ID, ACS URL, and signing certificate
    so the IdP can be configured.
    """
    request_id = str(uuid4())

    metadata_xml = await saml_service.generate_metadata(tenant_id=tenant_id)

    audit = _audit_event(
        "saml.metadata.served", "saml_metadata",
        details={"tenant_id": tenant_id},
        tenant_id=tenant_id,
    )
    logger.info(
        "SAML SP metadata served",
        extra={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return Response(
        content=metadata_xml,
        media_type="application/xml",
        headers={"X-Request-ID": request_id},
    )


@router.post("/configure", status_code=status.HTTP_201_CREATED)
async def saml_configure(
    body: SAMLConfigureRequest,
    user: AuthenticatedUser = Depends(require_auth),
    saml_service: SAMLService = Depends(_get_saml_service),
) -> dict[str, Any]:
    """Configure a new SAML IdP for the authenticated user's tenant.

    Requires ``saml:admin`` permission (admin only). Parses IdP metadata
    and stores configuration in Vault.
    """
    request_id = str(uuid4())

    if not check_permission(user, "saml", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: saml:admin required",
        )

    idp_config = await saml_service.configure_idp(
        tenant_id=user.tenant_id,
        metadata_url_or_xml=body.metadata_url_or_xml,
    )

    audit = _audit_event(
        "saml.idp.configured", "saml_idp", idp_config.entity_id,
        {"entity_id": idp_config.entity_id, "sso_url": idp_config.sso_url},
        user=user,
    )
    logger.info(
        "SAML IdP configured",
        extra={
            "request_id": request_id,
            "tenant_id": user.tenant_id,
            "entity_id": idp_config.entity_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": {
            "tenant_id": idp_config.tenant_id,
            "entity_id": idp_config.entity_id,
            "sso_url": idp_config.sso_url,
            "slo_url": idp_config.slo_url,
            "enabled": idp_config.enabled,
        },
        "meta": _meta(request_id=request_id),
    }


@router.post("/logout")
async def saml_logout(
    body: SAMLLogoutRequest,
    user: AuthenticatedUser = Depends(require_auth),
    saml_service: SAMLService = Depends(_get_saml_service),
) -> dict[str, Any]:
    """SAML Single Logout (SLO) — terminate the SAML session.

    Logs the user out and records an audit event.
    """
    request_id = str(uuid4())

    audit = _audit_event(
        "saml.logout", "saml_session", user.session_id,
        {"session_index": body.session_index},
        user=user,
    )
    logger.info(
        "SAML SLO processed",
        extra={
            "request_id": request_id,
            "user_id": user.id,
            "tenant_id": user.tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": {"message": "SAML session terminated"},
        "meta": _meta(request_id=request_id),
    }
