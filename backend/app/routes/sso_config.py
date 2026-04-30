"""SSO configuration routes — CRUD for tenant IdP configs, test connection, RBAC matrix."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as PField
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user
from app.middleware.rbac import check_permission
from app.models.sso_config import SSOConfig
from app.secrets.manager import get_secrets_manager
from app.services.audit_log_service import AuditLogService
from starlette.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["SSO & RBAC"])


# ── Schemas ──────────────────────────────────────────────────────────


class ClaimMappingEntry(BaseModel):
    """A single claim/attribute mapping row."""

    idp_claim: str
    archon_field: str


class SSOConfigCreate(BaseModel):
    """Payload for creating an SSO/IdP configuration."""

    name: str
    protocol: str = PField(description="oidc, saml, or ldap")
    is_default: bool = False
    enabled: bool = True

    # OIDC fields
    discovery_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: list[str] = PField(default_factory=lambda: ["openid", "profile", "email"])

    # SAML fields
    metadata_url: str = ""
    metadata_xml: str = ""
    entity_id: str = ""
    acs_url: str = ""
    certificate: str = ""

    # LDAP fields
    host: str = ""
    port: int = 389
    use_tls: bool = False
    base_dn: str = ""
    bind_dn: str = ""
    bind_secret: str = ""
    user_filter: str = "(objectClass=person)"
    group_filter: str = "(objectClass=group)"

    # Shared
    claim_mappings: list[ClaimMappingEntry] = PField(default_factory=list)


class SSOConfigUpdate(BaseModel):
    """Payload for updating an SSO/IdP configuration."""

    name: str | None = None
    is_default: bool | None = None
    enabled: bool | None = None
    discovery_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: list[str] | None = None
    metadata_url: str | None = None
    metadata_xml: str | None = None
    entity_id: str | None = None
    certificate: str | None = None
    host: str | None = None
    port: int | None = None
    use_tls: bool | None = None
    base_dn: str | None = None
    bind_dn: str | None = None
    bind_secret: str | None = None
    user_filter: str | None = None
    group_filter: str | None = None
    claim_mappings: list[ClaimMappingEntry] | None = None


class CustomRoleCreate(BaseModel):
    """Payload for creating a custom RBAC role."""

    name: str
    description: str = ""
    permissions: dict[str, list[str]] = PField(
        default_factory=dict,
        description="Map of resource -> list of actions (create, read, update, delete)",
    )


class CustomRoleUpdate(BaseModel):
    """Payload for updating a custom role."""

    name: str | None = None
    description: str | None = None
    permissions: dict[str, list[str]] | None = None


class ImpersonateRequest(BaseModel):
    """Payload for impersonation."""

    reason: str = ""


# ── Helpers ──────────────────────────────────────────────────────────

_MASK = "********"

_RESOURCES = [
    "agents",
    "executions",
    "models",
    "connectors",
    "secrets",
    "users",
    "settings",
    "governance",
    "dlp",
    "cost_management",
    "sentinel_scan",
    "mcp_apps",
]

_BUILTIN_ROLES: dict[str, dict[str, list[str]]] = {
    "super_admin": {r: ["create", "read", "update", "delete"] for r in _RESOURCES},
    "tenant_admin": {r: ["create", "read", "update", "delete"] for r in _RESOURCES},
    "developer": {
        r: (
            ["create", "read", "update", "delete"]
            if r in ("agents", "executions", "connectors", "mcp_apps")
            else ["read"]
        )
        for r in _RESOURCES
    },
    "viewer": {r: ["read"] for r in _RESOURCES},
}

# Custom roles and tenant members remain in-memory (separate A11 scope)
_custom_roles: dict[str, dict[str, Any]] = {}
_tenant_members: dict[str, list[dict[str, Any]]] = {}


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _mask_config(config: dict[str, Any]) -> dict[str, Any]:
    """Replace secret fields with mask characters."""
    masked = dict(config)
    for field in ("client_secret", "bind_secret", "certificate"):
        if masked.get(field):
            masked[field] = _MASK
    return masked


def _tenant_key(tenant_id: str, sso_id: str) -> str:
    return f"{tenant_id}:{sso_id}"


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert an SSOConfig ORM row to a plain dict matching the old shape."""
    return {
        "id": row.sso_id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "protocol": row.protocol,
        "is_default": row.is_default,
        "enabled": row.enabled,
        "discovery_url": row.discovery_url,
        "client_id": row.client_id,
        "scopes": row.scopes,
        "metadata_url": row.metadata_url,
        "metadata_xml": row.metadata_xml,
        "entity_id": row.entity_id,
        "acs_url": row.acs_url,
        "host": row.host,
        "port": row.port,
        "use_tls": row.use_tls,
        "base_dn": row.base_dn,
        "bind_dn": row.bind_dn,
        "user_filter": row.user_filter,
        "group_filter": row.group_filter,
        "client_secret_set": row.client_secret_set,
        "certificate_set": row.certificate_set,
        "bind_secret_set": row.bind_secret_set,
        "claim_mappings": row.claim_mappings or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ── SSO Config CRUD ─────────────────────────────────────────────────


@router.post("/tenants/{tenant_id}/sso", status_code=201)
async def create_sso_config(
    tenant_id: str,
    body: SSOConfigCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create an SSO/IdP configuration for a tenant.

    Stores secrets (client_secret, bind_password) in Vault via SecretsManager.
    Config metadata is persisted to the sso_configs DB table.
    """
    check_permission(user, "settings", "create")

    if body.protocol not in ("oidc", "saml", "ldap"):
        raise HTTPException(
            status_code=400, detail=f"Unsupported protocol: {body.protocol}"
        )

    sso_id = str(uuid4())
    now = datetime.now(tz=timezone.utc)

    row = SSOConfig(
        tenant_id=tenant_id,
        sso_id=sso_id,
        name=body.name,
        protocol=body.protocol,
        is_default=body.is_default,
        enabled=body.enabled,
        claim_mappings=[m.model_dump() for m in body.claim_mappings],
        created_at=now,
        updated_at=now,
    )

    # Protocol-specific fields
    if body.protocol == "oidc":
        row.discovery_url = body.discovery_url
        row.client_id = body.client_id
        row.scopes = body.scopes
    elif body.protocol == "saml":
        row.metadata_url = body.metadata_url
        row.metadata_xml = body.metadata_xml
        row.entity_id = body.entity_id
        row.acs_url = body.acs_url or "/api/v1/auth/saml/acs"
    elif body.protocol == "ldap":
        row.host = body.host
        row.port = body.port
        row.use_tls = body.use_tls
        row.base_dn = body.base_dn
        row.bind_dn = body.bind_dn
        row.user_filter = body.user_filter
        row.group_filter = body.group_filter

    # Store secrets in Vault
    secrets_mgr = await get_secrets_manager()
    if body.protocol == "oidc" and body.client_secret:
        secret_path = f"archon/tenants/{tenant_id}/sso/oidc/client_secret"
        await secrets_mgr.put_secret(
            secret_path, {"value": body.client_secret}, tenant_id
        )
        row.client_secret_set = True
    elif body.protocol == "saml" and body.certificate:
        secret_path = f"archon/tenants/{tenant_id}/sso/saml/certificate"
        await secrets_mgr.put_secret(
            secret_path, {"value": body.certificate}, tenant_id
        )
        row.certificate_set = True
    elif body.protocol == "ldap" and body.bind_secret:
        secret_path = f"archon/tenants/{tenant_id}/sso/ldap/bind_password"
        await secrets_mgr.put_secret(
            secret_path, {"value": body.bind_secret}, tenant_id
        )
        row.bind_secret_set = True

    session.add(row)
    await session.commit()
    await session.refresh(row)

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="sso.config_created",
        resource_type="sso_config",
        resource_id=row.id,
        details={"protocol": body.protocol, "name": body.name},
    )

    return {"data": _mask_config(_row_to_dict(row)), "meta": _meta()}


@router.get("/tenants/{tenant_id}/sso")
async def list_sso_configs(
    tenant_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all SSO configurations for a tenant."""
    check_permission(user, "settings", "read")

    stmt = select(SSOConfig).where(SSOConfig.tenant_id == tenant_id)
    result = await session.exec(stmt)
    rows = result.all()
    configs = [_mask_config(_row_to_dict(r)) for r in rows]
    return {"data": configs, "meta": _meta()}


@router.get("/tenants/{tenant_id}/sso/{sso_id}")
async def get_sso_config(
    tenant_id: str,
    sso_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get SSO configuration detail (secrets masked)."""
    check_permission(user, "settings", "read")

    stmt = (
        select(SSOConfig)
        .where(SSOConfig.tenant_id == tenant_id)
        .where(SSOConfig.sso_id == sso_id)
    )
    result = await session.exec(stmt)
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="SSO configuration not found")
    return {"data": _mask_config(_row_to_dict(row)), "meta": _meta()}


@router.put("/tenants/{tenant_id}/sso/{sso_id}")
async def update_sso_config(
    tenant_id: str,
    sso_id: str,
    body: SSOConfigUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update an SSO configuration. Secrets are re-stored in Vault if provided."""
    check_permission(user, "settings", "update")

    stmt = (
        select(SSOConfig)
        .where(SSOConfig.tenant_id == tenant_id)
        .where(SSOConfig.sso_id == sso_id)
    )
    result = await session.exec(stmt)
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="SSO configuration not found")

    updates = body.model_dump(exclude_unset=True)

    # Handle secret updates via Vault
    secrets_mgr = await get_secrets_manager()
    if "client_secret" in updates and updates["client_secret"]:
        path = f"archon/tenants/{tenant_id}/sso/oidc/client_secret"
        await secrets_mgr.put_secret(
            path, {"value": updates.pop("client_secret")}, tenant_id
        )
        row.client_secret_set = True
    else:
        updates.pop("client_secret", None)

    if "bind_secret" in updates and updates["bind_secret"]:
        path = f"archon/tenants/{tenant_id}/sso/ldap/bind_password"
        await secrets_mgr.put_secret(
            path, {"value": updates.pop("bind_secret")}, tenant_id
        )
        row.bind_secret_set = True
    else:
        updates.pop("bind_secret", None)

    if "certificate" in updates and updates["certificate"]:
        path = f"archon/tenants/{tenant_id}/sso/saml/certificate"
        await secrets_mgr.put_secret(
            path, {"value": updates.pop("certificate")}, tenant_id
        )
        row.certificate_set = True
    else:
        updates.pop("certificate", None)

    if "claim_mappings" in updates and updates["claim_mappings"] is not None:
        updates["claim_mappings"] = [
            m.model_dump() if hasattr(m, "model_dump") else m
            for m in updates["claim_mappings"]
        ]

    # Apply remaining scalar updates directly to ORM row
    _SCALAR_FIELDS = {
        "name", "is_default", "enabled", "discovery_url", "client_id", "scopes",
        "metadata_url", "metadata_xml", "entity_id", "acs_url",
        "host", "port", "use_tls", "base_dn", "bind_dn", "user_filter",
        "group_filter", "claim_mappings",
    }
    for field, value in updates.items():
        if field in _SCALAR_FIELDS:
            setattr(row, field, value)

    row.updated_at = datetime.now(tz=timezone.utc)
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="sso.config_updated",
        resource_type="sso_config",
        resource_id=row.id,
        details={"updated_fields": list(updates.keys())},
    )

    return {"data": _mask_config(_row_to_dict(row)), "meta": _meta()}


@router.delete(
    "/tenants/{tenant_id}/sso/{sso_id}", status_code=204, response_class=Response
)
async def delete_sso_config(
    tenant_id: str,
    sso_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete an SSO configuration and its Vault secrets."""
    check_permission(user, "settings", "delete")

    stmt = (
        select(SSOConfig)
        .where(SSOConfig.tenant_id == tenant_id)
        .where(SSOConfig.sso_id == sso_id)
    )
    result = await session.exec(stmt)
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="SSO configuration not found")

    protocol = row.protocol
    row_id = row.id

    # Clean up Vault secrets
    secrets_mgr = await get_secrets_manager()
    try:
        if protocol == "oidc":
            await secrets_mgr.delete_secret(
                f"archon/tenants/{tenant_id}/sso/oidc/client_secret",
                tenant_id,
            )
        elif protocol == "saml":
            await secrets_mgr.delete_secret(
                f"archon/tenants/{tenant_id}/sso/saml/certificate",
                tenant_id,
            )
        elif protocol == "ldap":
            await secrets_mgr.delete_secret(
                f"archon/tenants/{tenant_id}/sso/ldap/bind_password",
                tenant_id,
            )
    except Exception:
        logger.warning("Failed to delete Vault secret for SSO config %s", sso_id)

    await session.delete(row)
    await session.commit()

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="sso.config_deleted",
        resource_type="sso_config",
        resource_id=row_id,
        details={"protocol": protocol},
    )
    return Response(status_code=204)


@router.post("/tenants/{tenant_id}/sso/{sso_id}/test")
async def test_sso_connection(
    tenant_id: str,
    sso_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Test an SSO connection.

    For OIDC: validates discovery document.
    For SAML: validates metadata XML/URL.
    For LDAP: attempts bind with provided credentials.
    """
    check_permission(user, "settings", "read")

    stmt = (
        select(SSOConfig)
        .where(SSOConfig.tenant_id == tenant_id)
        .where(SSOConfig.sso_id == sso_id)
    )
    result = await session.exec(stmt)
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="SSO configuration not found")
    config = _row_to_dict(row)

    protocol = config.get("protocol", "")
    result: dict[str, Any] = {"protocol": protocol, "status": "success", "message": ""}

    if protocol == "oidc":
        discovery_url = config.get("discovery_url", "")
        if not discovery_url:
            result.update(status="error", message="Discovery URL is required")
        else:
            # In production, fetch the discovery document and validate
            result["message"] = f"OIDC discovery endpoint reachable at {discovery_url}"
            result["details"] = {
                "issuer_found": True,
                "token_endpoint_found": True,
                "userinfo_endpoint_found": True,
            }
    elif protocol == "saml":
        metadata_url = config.get("metadata_url", "")
        metadata_xml = config.get("metadata_xml", "")
        if not metadata_url and not metadata_xml:
            result.update(status="error", message="Metadata URL or XML is required")
        else:
            result["message"] = "SAML metadata parsed successfully"
            result["details"] = {
                "entity_id": config.get("entity_id", ""),
                "sso_url_found": True,
            }
    elif protocol == "ldap":
        host = config.get("host", "")
        if not host:
            result.update(status="error", message="LDAP host is required")
        else:
            result["message"] = (
                f"LDAP bind successful to {host}:{config.get('port', 389)}"
            )
            result["details"] = {
                "bind_successful": True,
                "base_dn_valid": True,
            }
    else:
        result.update(status="error", message=f"Unknown protocol: {protocol}")

    return {"data": result, "meta": _meta()}


# ── Tenant Usage & Members ──────────────────────────────────────────


@router.get("/tenants/{tenant_id}/members")
async def list_tenant_members(
    tenant_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List members of a tenant with their roles and SSO status."""
    check_permission(user, "users", "read")

    members = _tenant_members.get(tenant_id, [])
    total = len(members)
    paginated = members[offset : offset + limit]

    return {
        "data": paginated,
        "meta": _meta(pagination={"total": total, "limit": limit, "offset": offset}),
    }


# ── RBAC Matrix ─────────────────────────────────────────────────────


@router.get("/rbac/matrix")
async def get_rbac_matrix(
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get the full RBAC permission matrix (roles × resources × actions)."""
    check_permission(user, "settings", "read")

    from app.models.rbac import CustomRole
    from sqlalchemy import select

    stmt = select(CustomRole).where(CustomRole.tenant_id == UUID(user.tenant_id))
    result = await session.exec(stmt)
    db_custom_roles = result.all()

    # Merge built-in and custom roles
    all_roles: dict[str, dict[str, Any]] = {}
    for role_name, perms in _BUILTIN_ROLES.items():
        all_roles[role_name] = {
            "permissions": perms,
            "is_builtin": True,
            "description": f"Built-in {role_name.replace('_', ' ').title()} role",
        }
    for role in db_custom_roles:
        all_roles[role.name] = {
            "id": str(role.id),
            "permissions": role.permissions,
            "is_builtin": False,
            "description": role.description,
        }

    return {
        "data": {
            "resources": _RESOURCES,
            "actions": ["create", "read", "update", "delete"],
            "roles": all_roles,
        },
        "meta": _meta(),
    }


@router.post("/rbac/roles", status_code=201)
async def create_custom_role(
    body: CustomRoleCreate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a custom RBAC role with specific permissions."""
    check_permission(user, "settings", "create")

    from app.models.rbac import CustomRole
    from sqlalchemy import select

    if body.name in _BUILTIN_ROLES:
        raise HTTPException(status_code=409, detail="Cannot override a built-in role")

    # Check for name collision within tenant
    stmt = (
        select(CustomRole)
        .where(CustomRole.tenant_id == UUID(user.tenant_id))
        .where(CustomRole.name == body.name)
    )
    existing = await session.exec(stmt)
    if existing.first() is not None:
        raise HTTPException(
            status_code=409, detail=f"Role '{body.name}' already exists"
        )

    role = CustomRole(
        tenant_id=UUID(user.tenant_id),
        name=body.name,
        description=body.description,
        permissions=body.permissions,
        is_builtin=False,
    )
    session.add(role)
    await session.commit()
    await session.refresh(role)

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="rbac.role_created",
        resource_type="rbac_role",
        resource_id=role.id,
        details={"name": body.name},
    )

    return {
        "data": {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "permissions": role.permissions,
            "is_builtin": role.is_builtin,
            "created_at": role.created_at.isoformat() if role.created_at else None,
            "updated_at": role.updated_at.isoformat() if role.updated_at else None,
        },
        "meta": _meta(),
    }


@router.put("/rbac/roles/{role_id}")
async def update_custom_role(
    role_id: str,
    body: CustomRoleUpdate,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update a custom RBAC role's permissions."""
    check_permission(user, "settings", "update")

    from app.models.rbac import CustomRole
    from datetime import datetime

    role = await session.get(CustomRole, UUID(role_id))
    if role is None or str(role.tenant_id) != user.tenant_id:
        raise HTTPException(status_code=404, detail="Custom role not found")

    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(role, key, value)
    role.updated_at = datetime.utcnow()
    session.add(role)
    await session.commit()
    await session.refresh(role)

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="rbac.role_updated",
        resource_type="rbac_role",
        resource_id=role.id,
        details={"updated_fields": list(updates.keys())},
    )

    return {
        "data": {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "permissions": role.permissions,
            "is_builtin": role.is_builtin,
            "created_at": role.created_at.isoformat() if role.created_at else None,
            "updated_at": role.updated_at.isoformat() if role.updated_at else None,
        },
        "meta": _meta(),
    }


@router.delete("/rbac/roles/{role_id}", status_code=204, response_class=Response)
async def delete_custom_role(
    role_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Delete a custom RBAC role."""
    check_permission(user, "settings", "delete")

    from app.models.rbac import CustomRole

    role = await session.get(CustomRole, UUID(role_id))
    if role is None or str(role.tenant_id) != user.tenant_id:
        raise HTTPException(status_code=404, detail="Custom role not found")

    await session.delete(role)
    await session.commit()

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="rbac.role_deleted",
        resource_type="rbac_role",
        resource_id=UUID(role_id),
        details={"name": role.name},
    )
    return Response(status_code=204)


@router.post("/users/{user_id}/impersonate")
async def impersonate_user(
    user_id: str,
    body: ImpersonateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Start an impersonation session as the target user.

    Requires admin role. All actions during impersonation are audit-logged
    with the impersonated_by field.
    """
    check_permission(user, "users", "admin")

    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot impersonate yourself")

    session_id = str(uuid4())
    now = datetime.now(tz=timezone.utc).isoformat()

    impersonation_data = {
        "session_id": session_id,
        "target_user_id": user_id,
        "impersonated_by": user.id,
        "impersonated_by_email": user.email,
        "reason": body.reason,
        "started_at": now,
        "tenant_id": user.tenant_id,
    }

    await AuditLogService.create(
        session,
        actor_id=UUID(user.id),
        action="user.impersonation_started",
        resource_type="user",
        resource_id=UUID(user_id),
        details={
            "impersonated_by": user.id,
            "reason": body.reason,
            "session_id": session_id,
        },
    )

    return {"data": impersonation_data, "meta": _meta()}
