"""API routes for the Cross-Platform Security Proxy Gateway."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import require_auth
from app.middleware.rbac import check_permission
from app.models.security_proxy import (
    ClassifyBody,
    ProxyRequestBody,
    SAMLTerminateBody,
    UpstreamConfig,
    UpstreamCreateBody,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.security_proxy_service import SecurityProxyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/proxy", tags=["Security Proxy"])


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


async def _get_proxy_service(
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> SecurityProxyService:
    """FastAPI dependency to construct a SecurityProxyService."""
    return SecurityProxyService(secrets=secrets)


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/request")
async def proxy_request(
    body: ProxyRequestBody,
    user: AuthenticatedUser = Depends(require_auth),
    proxy_service: SecurityProxyService = Depends(_get_proxy_service),
) -> dict[str, Any]:
    """Proxy a request through the full security pipeline.

    Authenticates, DLP scans, injects credentials, routes, DLP scans
    the response, and produces an audit trail.
    """
    if not check_permission(user, "proxy", "execute"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: proxy:execute",
        )

    from app.models.security_proxy import ProxyRequest

    proxy_req = ProxyRequest(
        method=body.method,
        url=body.url,
        headers=body.headers,
        body=body.body,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )

    result = await proxy_service.process_request(
        tenant_id=user.tenant_id,
        user=user,
        proxy_request=proxy_req,
    )

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.post("/saml/terminate")
async def saml_terminate(
    body: SAMLTerminateBody,
    user: AuthenticatedUser = Depends(require_auth),
    proxy_service: SecurityProxyService = Depends(_get_proxy_service),
) -> dict[str, Any]:
    """Terminate a SAML assertion at the proxy level.

    Validates the SAML response, extracts identity, and creates an
    internal proxy session translated to JWT downstream.
    """
    if not check_permission(user, "proxy", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: proxy:admin",
        )

    try:
        session = await proxy_service.terminate_saml(
            saml_response=body.saml_response,
            issuer=body.issuer,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {"data": session.model_dump(mode="json"), "meta": _meta()}


@router.post("/upstreams", status_code=201)
async def configure_upstream(
    body: UpstreamCreateBody,
    user: AuthenticatedUser = Depends(require_auth),
    proxy_service: SecurityProxyService = Depends(_get_proxy_service),
) -> dict[str, Any]:
    """Configure an upstream AI endpoint for the tenant."""
    if not check_permission(user, "proxy", "create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: proxy:create",
        )

    upstream = UpstreamConfig(
        name=body.name,
        base_url=body.base_url,
        provider_type=body.provider_type,
        auth_method=body.auth_method,
        vault_credential_path=body.vault_credential_path,
        rate_limit=body.rate_limit,
    )

    result = await proxy_service.configure_upstream(
        tenant_id=user.tenant_id,
        user=user,
        upstream=upstream,
    )

    return {"data": result.model_dump(mode="json"), "meta": _meta()}


@router.get("/upstreams")
async def list_upstreams(
    user: AuthenticatedUser = Depends(require_auth),
    proxy_service: SecurityProxyService = Depends(_get_proxy_service),
) -> dict[str, Any]:
    """List configured upstreams for the tenant."""
    if not check_permission(user, "proxy", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: proxy:read",
        )

    upstreams = await proxy_service.list_upstreams(tenant_id=user.tenant_id)

    return {
        "data": [u.model_dump(mode="json") for u in upstreams],
        "meta": _meta(),
    }


@router.get("/metrics")
async def proxy_metrics(
    user: AuthenticatedUser = Depends(require_auth),
    proxy_service: SecurityProxyService = Depends(_get_proxy_service),
) -> dict[str, Any]:
    """Return aggregated proxy metrics for the tenant."""
    if not check_permission(user, "proxy", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: proxy:read",
        )

    metrics = await proxy_service.get_proxy_metrics(tenant_id=user.tenant_id)

    return {"data": metrics.model_dump(mode="json"), "meta": _meta()}


@router.post("/classify")
async def classify_content(
    body: ClassifyBody,
    user: AuthenticatedUser = Depends(require_auth),
    proxy_service: SecurityProxyService = Depends(_get_proxy_service),
) -> dict[str, Any]:
    """Classify content by topic, sensitivity, and intent."""
    if not check_permission(user, "proxy", "read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: proxy:read",
        )

    classification = await proxy_service.classify_content(body.content)

    return {"data": classification.model_dump(mode="json"), "meta": _meta()}
