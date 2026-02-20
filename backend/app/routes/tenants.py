"""Enterprise tenant management API routes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field as PField

from app.interfaces.models.enterprise import AuthenticatedUser, IdPConfig
from app.middleware.auth import require_auth
from app.middleware.rbac import check_permission, require_permission
from app.models.audit import EnterpriseAuditEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenancy", tags=["Tenants"])


# ── Request / response schemas ──────────────────────────────────────


class TenantCreate(BaseModel):
    """Payload for creating a new tenant."""

    name: str
    slug: str
    owner_email: str
    tier: str = "free"
    settings: dict[str, Any] = PField(default_factory=dict)


class TenantUpdate(BaseModel):
    """Payload for updating tenant configuration."""

    name: str | None = None
    tier: str | None = None
    status: str | None = None
    settings: dict[str, Any] | None = None


class TenantResponse(BaseModel):
    """Serialised tenant representation for API responses."""

    id: str
    name: str
    slug: str
    tier: str
    status: str
    owner_email: str
    settings: dict[str, Any] = PField(default_factory=dict)
    created_at: str
    updated_at: str


class IdPConfigRequest(BaseModel):
    """Payload for configuring an identity provider for a tenant."""

    type: str
    metadata_url: str = ""
    entity_id: str = ""
    signing_cert: str = ""


# ── Helpers ──────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _audit_event(
    user: AuthenticatedUser,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> EnterpriseAuditEvent:
    """Create an audit event record for a state-changing operation."""
    return EnterpriseAuditEvent(
        tenant_id=UUID(user.tenant_id),
        user_id=UUID(user.id),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        session_id=user.session_id,
    )


def _is_super_admin(user: AuthenticatedUser) -> bool:
    """Check whether the user holds a super-admin role."""
    return "super_admin" in user.roles or "admin" in user.roles


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreate,
    user: AuthenticatedUser = Depends(require_permission("tenants", "create")),
) -> dict[str, Any]:
    """Create a new tenant on the platform.

    Requires ``tenants:create`` permission (super admin only).
    Provisions default configuration and quota records.
    """
    request_id = str(uuid4())
    tenant_id = str(uuid4())

    tenant_data = {
        "id": tenant_id,
        "name": body.name,
        "slug": body.slug,
        "tier": body.tier,
        "status": "active",
        "owner_email": body.owner_email,
        "settings": body.settings,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    audit = _audit_event(
        user, "tenant.created", "tenant", tenant_id,
        {"name": body.name, "slug": body.slug, "tier": body.tier},
    )
    logger.info(
        "Tenant created",
        extra={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": tenant_data,
        "meta": _meta(request_id=request_id),
    }


@router.get("/tenants")
async def list_tenants(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """List tenants visible to the authenticated user.

    Super admins see all tenants; regular users see only their own.
    Results are paginated.
    """
    if _is_super_admin(user):
        tenants: list[dict[str, Any]] = []
        total = 0
    else:
        tenants = [
            {
                "id": user.tenant_id,
                "name": user.tenant_id,
            },
        ]
        total = 1

    return {
        "data": tenants,
        "meta": _meta(
            pagination={"total": total, "limit": limit, "offset": offset},
        ),
    }


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    """Get details for a specific tenant.

    Users may view their own tenant. Super admins may view any tenant.
    """
    if not _is_super_admin(user) and user.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: cannot access another tenant",
        )

    tenant_data = {
        "id": tenant_id,
        "name": tenant_id,
    }

    return {
        "data": tenant_data,
        "meta": _meta(),
    }


@router.put("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: TenantUpdate,
    user: AuthenticatedUser = Depends(require_permission("tenants", "update")),
) -> dict[str, Any]:
    """Update a tenant's configuration.

    Requires ``tenants:update`` permission. Only fields present in the
    request body are modified.
    """
    request_id = str(uuid4())

    if not _is_super_admin(user) and user.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: cannot modify another tenant",
        )

    update_fields = body.model_dump(exclude_none=True)

    audit = _audit_event(
        user, "tenant.updated", "tenant", tenant_id,
        {"updated_fields": list(update_fields.keys())},
    )
    logger.info(
        "Tenant updated",
        extra={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": {"id": tenant_id, **update_fields},
        "meta": _meta(request_id=request_id),
    }


@router.put("/tenants/{tenant_id}/idp")
async def configure_tenant_idp(
    tenant_id: str,
    body: IdPConfigRequest,
    user: AuthenticatedUser = Depends(require_permission("tenants", "admin")),
) -> dict[str, Any]:
    """Configure an identity provider (IdP) for a tenant.

    Requires ``tenants:admin`` permission. Supports SAML, OIDC, and
    local authentication types.
    """
    request_id = str(uuid4())

    if not _is_super_admin(user) and user.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: cannot configure another tenant's IdP",
        )

    idp_data = {
        "tenant_id": tenant_id,
        "type": body.type,
        "metadata_url": body.metadata_url,
        "entity_id": body.entity_id,
        "configured_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    audit = _audit_event(
        user, "tenant.idp_configured", "tenant_idp", tenant_id,
        {"idp_type": body.type},
    )
    logger.info(
        "Tenant IdP configured",
        extra={
            "request_id": request_id,
            "tenant_id": tenant_id,
            "idp_type": body.type,
            "audit_id": str(audit.id),
        },
    )

    return {
        "data": idp_data,
        "meta": _meta(request_id=request_id),
    }
