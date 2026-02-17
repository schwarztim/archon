"""SCIM 2.0 provisioning routes for enterprise user/group lifecycle (RFC 7644)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.models.audit import EnterpriseAuditEvent
from app.models.scim import (
    SCIMError,
    SCIMGroup,
    SCIMListResponse,
    SCIMPatchRequest,
    SCIMUser,
)
from app.secrets.manager import VaultSecretsManager, get_secrets_manager
from app.services.scim_service import SCIMService

logger = logging.getLogger(__name__)

# Custom response class for application/scim+json (RFC 7644)
_SCIM_CONTENT_TYPE = "application/scim+json"

router = APIRouter(prefix="/api/v1/scim/v2", tags=["SCIM 2.0"])


# ── Helpers ──────────────────────────────────────────────────────────


def _scim_response(
    content: dict[str, Any],
    status_code: int = 200,
) -> JSONResponse:
    """Return a JSONResponse with SCIM content type."""
    return JSONResponse(
        content=content,
        status_code=status_code,
        media_type=_SCIM_CONTENT_TYPE,
    )


def _scim_error_response(
    status_code: int,
    detail: str,
    scim_type: str = "",
) -> JSONResponse:
    """Build a SCIM-compliant error response."""
    error = SCIMError(
        status=str(status_code),
        scimType=scim_type,
        detail=detail,
    )
    return JSONResponse(
        content=error.model_dump(by_alias=True),
        status_code=status_code,
        media_type=_SCIM_CONTENT_TYPE,
    )


def _audit_event(
    tenant_id: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> EnterpriseAuditEvent:
    """Create an audit event for SCIM operations."""
    return EnterpriseAuditEvent(
        tenant_id=UUID(tenant_id) if tenant_id else UUID(int=0),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )


async def _get_scim_service(
    secrets: VaultSecretsManager = Depends(get_secrets_manager),
) -> SCIMService:
    """FastAPI dependency to construct a SCIMService instance."""
    return SCIMService(secrets=secrets)


async def _validate_scim_auth(
    request: Request,
    scim_service: SCIMService = Depends(_get_scim_service),
) -> str:
    """Validate SCIM Bearer token and return the resolved tenant_id.

    SCIM endpoints use a dedicated bearer token stored in Vault,
    separate from the JWT-based user authentication.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token = auth_header[len("Bearer "):]

    # Extract tenant_id from the X-Tenant-ID header
    tenant_id = request.headers.get("X-Tenant-ID", "")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Tenant-ID header",
        )

    is_valid = await scim_service.validate_bearer_token(tenant_id, token)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid SCIM bearer token",
        )

    return tenant_id


# ── User routes ──────────────────────────────────────────────────────


@router.get("/Users")
async def list_users(
    tenant_id: str = Depends(_validate_scim_auth),
    scim_service: SCIMService = Depends(_get_scim_service),
    filter: str = Query(default="", alias="filter"),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=100),
) -> JSONResponse:
    """List SCIM users for the tenant with optional filtering.

    Supports basic SCIM filter expressions (e.g. ``userName eq "x"``).
    """
    result = await scim_service.list_users(
        tenant_id=tenant_id,
        scim_filter=filter,
        start_index=startIndex,
        count=count,
    )

    audit = _audit_event(
        tenant_id, "scim.users.listed", "scim_user",
        details={"filter": filter, "total": result.totalResults},
    )
    logger.info(
        "SCIM users listed",
        extra={"tenant_id": tenant_id, "audit_id": str(audit.id)},
    )

    return _scim_response(result.model_dump(by_alias=True))


@router.get("/Users/{scim_id}")
async def get_user(
    scim_id: str,
    tenant_id: str = Depends(_validate_scim_auth),
    scim_service: SCIMService = Depends(_get_scim_service),
) -> JSONResponse:
    """Get a single SCIM user by ID."""
    try:
        user = await scim_service.get_user(tenant_id=tenant_id, scim_id=scim_id)
    except KeyError:
        return _scim_error_response(404, f"User {scim_id} not found")

    audit = _audit_event(
        tenant_id, "scim.user.retrieved", "scim_user", scim_id,
    )
    logger.info(
        "SCIM user retrieved",
        extra={"tenant_id": tenant_id, "scim_id": scim_id, "audit_id": str(audit.id)},
    )

    return _scim_response(user.model_dump(by_alias=True))


@router.post("/Users", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: SCIMUser,
    tenant_id: str = Depends(_validate_scim_auth),
    scim_service: SCIMService = Depends(_get_scim_service),
) -> JSONResponse:
    """Create a new SCIM user from IdP provisioning."""
    created = await scim_service.create_user(tenant_id=tenant_id, scim_user=body)

    audit = _audit_event(
        tenant_id, "scim.user.created", "scim_user", created.id,
        {"userName": created.userName},
    )
    logger.info(
        "SCIM user created",
        extra={"tenant_id": tenant_id, "scim_id": created.id, "audit_id": str(audit.id)},
    )

    return _scim_response(created.model_dump(by_alias=True), status_code=201)


@router.patch("/Users/{scim_id}")
async def update_user(
    scim_id: str,
    body: SCIMPatchRequest,
    tenant_id: str = Depends(_validate_scim_auth),
    scim_service: SCIMService = Depends(_get_scim_service),
) -> JSONResponse:
    """Update a SCIM user via PATCH operations (RFC 7644 §3.5.2)."""
    try:
        updated = await scim_service.update_user(
            tenant_id=tenant_id,
            scim_id=scim_id,
            operations=body.Operations,
        )
    except KeyError:
        return _scim_error_response(404, f"User {scim_id} not found")

    audit = _audit_event(
        tenant_id, "scim.user.updated", "scim_user", scim_id,
        {"operations_count": len(body.Operations)},
    )
    logger.info(
        "SCIM user updated",
        extra={"tenant_id": tenant_id, "scim_id": scim_id, "audit_id": str(audit.id)},
    )

    return _scim_response(updated.model_dump(by_alias=True))


@router.delete("/Users/{scim_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    scim_id: str,
    tenant_id: str = Depends(_validate_scim_auth),
    scim_service: SCIMService = Depends(_get_scim_service),
) -> None:
    """Deactivate a SCIM user (soft-delete)."""
    try:
        await scim_service.delete_user(tenant_id=tenant_id, scim_id=scim_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {scim_id} not found",
        )

    audit = _audit_event(
        tenant_id, "scim.user.deactivated", "scim_user", scim_id,
    )
    logger.info(
        "SCIM user deactivated",
        extra={"tenant_id": tenant_id, "scim_id": scim_id, "audit_id": str(audit.id)},
    )


# ── Group routes ─────────────────────────────────────────────────────


@router.get("/Groups")
async def list_groups(
    tenant_id: str = Depends(_validate_scim_auth),
    scim_service: SCIMService = Depends(_get_scim_service),
    filter: str = Query(default="", alias="filter"),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=100),
) -> JSONResponse:
    """List SCIM groups for the tenant."""
    result = await scim_service.list_groups(
        tenant_id=tenant_id,
        scim_filter=filter,
        start_index=startIndex,
        count=count,
    )

    audit = _audit_event(
        tenant_id, "scim.groups.listed", "scim_group",
        details={"filter": filter, "total": result.totalResults},
    )
    logger.info(
        "SCIM groups listed",
        extra={"tenant_id": tenant_id, "audit_id": str(audit.id)},
    )

    return _scim_response(result.model_dump(by_alias=True))


@router.post("/Groups", status_code=status.HTTP_201_CREATED)
async def create_group(
    body: SCIMGroup,
    tenant_id: str = Depends(_validate_scim_auth),
    scim_service: SCIMService = Depends(_get_scim_service),
) -> JSONResponse:
    """Create a new SCIM group from IdP provisioning."""
    created = await scim_service.create_group(tenant_id=tenant_id, scim_group=body)

    audit = _audit_event(
        tenant_id, "scim.group.created", "scim_group", created.id,
        {"displayName": created.displayName},
    )
    logger.info(
        "SCIM group created",
        extra={"tenant_id": tenant_id, "scim_id": created.id, "audit_id": str(audit.id)},
    )

    return _scim_response(created.model_dump(by_alias=True), status_code=201)


@router.patch("/Groups/{scim_id}")
async def update_group(
    scim_id: str,
    body: SCIMPatchRequest,
    tenant_id: str = Depends(_validate_scim_auth),
    scim_service: SCIMService = Depends(_get_scim_service),
) -> JSONResponse:
    """Update a SCIM group via PATCH operations."""
    try:
        updated = await scim_service.update_group(
            tenant_id=tenant_id,
            scim_id=scim_id,
            operations=body.Operations,
        )
    except KeyError:
        return _scim_error_response(404, f"Group {scim_id} not found")

    audit = _audit_event(
        tenant_id, "scim.group.updated", "scim_group", scim_id,
        {"operations_count": len(body.Operations)},
    )
    logger.info(
        "SCIM group updated",
        extra={"tenant_id": tenant_id, "scim_id": scim_id, "audit_id": str(audit.id)},
    )

    return _scim_response(updated.model_dump(by_alias=True))


# ── Discovery routes ─────────────────────────────────────────────────


@router.get("/ServiceProviderConfig")
async def service_provider_config() -> JSONResponse:
    """SCIM ServiceProviderConfig endpoint (unauthenticated per AGENT_RULES)."""
    config = {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": "https://archon.dev/docs/scim",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 100},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Authentication via Vault-managed bearer tokens",
                "specUri": "https://tools.ietf.org/html/rfc6750",
                "primary": True,
            },
        ],
    }
    return _scim_response(config)


@router.get("/Schemas")
async def scim_schemas() -> JSONResponse:
    """SCIM Schemas endpoint — returns supported resource schemas."""
    schemas = {
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 2,
        "itemsPerPage": 2,
        "startIndex": 1,
        "Resources": [
            {
                "id": "urn:ietf:params:scim:schemas:core:2.0:User",
                "name": "User",
                "description": "SCIM 2.0 User resource",
                "attributes": [],
            },
            {
                "id": "urn:ietf:params:scim:schemas:core:2.0:Group",
                "name": "Group",
                "description": "SCIM 2.0 Group resource",
                "attributes": [],
            },
        ],
    }
    return _scim_response(schemas)
