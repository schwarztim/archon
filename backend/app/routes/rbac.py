"""RBAC CRUD endpoints for managing custom roles and group-role mappings.

All endpoints require the ``admin`` role and are tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime

from app.utils.time import utcnow as _utcnow
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field as PField
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.rbac import require_permission
from app.models.custom_role import CustomRole, GroupRoleMapping

router = APIRouter(prefix="/rbac", tags=["RBAC"])


# ── Helpers ───────────────────────────────────────────────────────────


def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    """Build standard envelope meta block."""
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": _utcnow().isoformat(),
        **extra,
    }


def _parse_tenant_uuid(tenant_id: str, request_id: str) -> UUID:
    """Parse tenant UUID, raising HTTP 400 on invalid format."""
    try:
        return UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid tenant_id format: {tenant_id}",
        ) from exc


# ── Request / response schemas ───────────────────────────────────────


class CustomRoleCreate(BaseModel):
    """Payload for creating a custom role."""

    name: str = PField(..., min_length=1, max_length=64)
    description: str = ""
    permissions: dict[str, list[str]] = PField(default_factory=dict)


class CustomRoleUpdate(BaseModel):
    """Payload for updating a custom role's permissions."""

    description: str | None = None
    permissions: dict[str, list[str]] | None = None


class GroupMappingCreate(BaseModel):
    """Payload for creating a group-role mapping."""

    group_oid: str = PField(..., min_length=1)
    role_name: str = PField(..., min_length=1)


# ── Custom Roles ─────────────────────────────────────────────────────


@router.get("/custom-roles")
async def list_custom_roles(
    user: AuthenticatedUser = Depends(require_permission("rbac", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all custom roles for the current tenant."""
    request_id = str(uuid4())
    tenant_uuid = _parse_tenant_uuid(user.tenant_id, request_id)

    result = await session.exec(
        select(CustomRole).where(CustomRole.tenant_id == tenant_uuid)
    )
    roles = result.all()

    return {
        "data": [
            {
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "permissions": r.permissions,
                "is_builtin": r.is_builtin,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in roles
        ],
        "meta": _meta(request_id=request_id, count=len(roles)),
    }


@router.post("/custom-roles", status_code=status.HTTP_201_CREATED)
async def create_custom_role(
    body: CustomRoleCreate,
    user: AuthenticatedUser = Depends(require_permission("rbac", "admin")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new custom role for the current tenant."""
    request_id = str(uuid4())
    tenant_uuid = _parse_tenant_uuid(user.tenant_id, request_id)

    # Prevent duplicate names within the tenant
    existing = await session.exec(
        select(CustomRole).where(
            CustomRole.tenant_id == tenant_uuid,
            CustomRole.name == body.name,  # type: ignore[arg-type]
        )
    )
    if existing.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Custom role '{body.name}' already exists for this tenant.",
        )

    role = CustomRole(
        tenant_id=tenant_uuid,
        name=body.name,
        description=body.description,
        permissions=body.permissions,
        is_builtin=False,
    )
    session.add(role)
    await session.commit()
    await session.refresh(role)

    return {
        "data": {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "permissions": role.permissions,
            "is_builtin": role.is_builtin,
            "created_at": role.created_at.isoformat(),
            "updated_at": role.updated_at.isoformat(),
        },
        "meta": _meta(request_id=request_id),
    }


@router.put("/custom-roles/{role_id}")
async def update_custom_role(
    role_id: UUID,
    body: CustomRoleUpdate,
    user: AuthenticatedUser = Depends(require_permission("rbac", "admin")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Update the permissions (and optionally description) of a custom role."""
    request_id = str(uuid4())
    tenant_uuid = _parse_tenant_uuid(user.tenant_id, request_id)

    result = await session.exec(
        select(CustomRole).where(
            CustomRole.id == role_id,
            CustomRole.tenant_id == tenant_uuid,
        )
    )
    role = result.first()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Custom role {role_id} not found.",
        )

    if role.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Built-in roles cannot be modified.",
        )

    if body.description is not None:
        role.description = body.description
    if body.permissions is not None:
        role.permissions = body.permissions
    role.updated_at = datetime.utcnow()  # noqa: DTZ003 — naive for TIMESTAMP WITHOUT TIME ZONE

    session.add(role)
    await session.commit()
    await session.refresh(role)

    return {
        "data": {
            "id": str(role.id),
            "name": role.name,
            "description": role.description,
            "permissions": role.permissions,
            "updated_at": role.updated_at.isoformat(),
        },
        "meta": _meta(request_id=request_id),
    }


@router.delete("/custom-roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom_role(
    role_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("rbac", "admin")),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a custom role (built-in roles cannot be deleted)."""
    request_id = str(uuid4())
    tenant_uuid = _parse_tenant_uuid(user.tenant_id, request_id)

    result = await session.exec(
        select(CustomRole).where(
            CustomRole.id == role_id,
            CustomRole.tenant_id == tenant_uuid,
        )
    )
    role = result.first()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Custom role {role_id} not found.",
        )

    if role.is_builtin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Built-in roles cannot be deleted.",
        )

    await session.delete(role)
    await session.commit()


# ── Group-Role Mappings ──────────────────────────────────────────────


@router.get("/group-mappings")
async def list_group_mappings(
    user: AuthenticatedUser = Depends(require_permission("rbac", "read")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List all group → role mappings for the current tenant."""
    request_id = str(uuid4())
    tenant_uuid = _parse_tenant_uuid(user.tenant_id, request_id)

    result = await session.exec(
        select(GroupRoleMapping).where(GroupRoleMapping.tenant_id == tenant_uuid)
    )
    mappings = result.all()

    return {
        "data": [
            {
                "id": str(m.id),
                "tenant_id": str(m.tenant_id),
                "group_oid": m.group_oid,
                "role_name": m.role_name,
                "created_at": m.created_at.isoformat(),
            }
            for m in mappings
        ],
        "meta": _meta(request_id=request_id, count=len(mappings)),
    }


@router.post("/group-mappings", status_code=status.HTTP_201_CREATED)
async def create_group_mapping(
    body: GroupMappingCreate,
    user: AuthenticatedUser = Depends(require_permission("rbac", "admin")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Create a new group → role mapping for the current tenant."""
    request_id = str(uuid4())
    tenant_uuid = _parse_tenant_uuid(user.tenant_id, request_id)

    # Prevent duplicate mappings
    existing = await session.exec(
        select(GroupRoleMapping).where(
            GroupRoleMapping.tenant_id == tenant_uuid,
            GroupRoleMapping.group_oid == body.group_oid,  # type: ignore[arg-type]
            GroupRoleMapping.role_name == body.role_name,  # type: ignore[arg-type]
        )
    )
    if existing.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Mapping for group '{body.group_oid}' → '{body.role_name}' already exists.",
        )

    mapping = GroupRoleMapping(
        tenant_id=tenant_uuid,
        group_oid=body.group_oid,
        role_name=body.role_name,
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)

    return {
        "data": {
            "id": str(mapping.id),
            "tenant_id": str(mapping.tenant_id),
            "group_oid": mapping.group_oid,
            "role_name": mapping.role_name,
            "created_at": mapping.created_at.isoformat(),
        },
        "meta": _meta(request_id=request_id),
    }


@router.delete("/group-mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_mapping(
    mapping_id: UUID,
    user: AuthenticatedUser = Depends(require_permission("rbac", "admin")),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Delete a group → role mapping."""
    request_id = str(uuid4())
    tenant_uuid = _parse_tenant_uuid(user.tenant_id, request_id)

    result = await session.exec(
        select(GroupRoleMapping).where(
            GroupRoleMapping.id == mapping_id,
            GroupRoleMapping.tenant_id == tenant_uuid,
        )
    )
    mapping = result.first()
    if mapping is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group mapping {mapping_id} not found.",
        )

    await session.delete(mapping)
    await session.commit()
