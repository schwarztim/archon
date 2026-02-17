"""Admin user management API routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr

from app.middleware.auth import require_auth
from app.interfaces.models.enterprise import AuthenticatedUser

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Seed data ────────────────────────────────────────────────────────

_SEED_USERS: list[dict[str, Any]] = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "System",
        "email": "system@archon.local",
        "roles": ["admin"],
        "status": "active",
        "last_login": "2025-01-15T10:30:00Z",
        "mfa_enabled": True,
        "created_at": "2024-06-01T00:00:00Z",
    },
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "name": "Dev User",
        "email": "dev@archon.local",
        "roles": ["developer"],
        "status": "active",
        "last_login": "2025-01-14T08:00:00Z",
        "mfa_enabled": False,
        "created_at": "2024-07-15T00:00:00Z",
    },
    {
        "id": "00000000-0000-0000-0000-000000000003",
        "name": "Viewer",
        "email": "viewer@archon.local",
        "roles": ["viewer"],
        "status": "active",
        "last_login": None,
        "mfa_enabled": False,
        "created_at": "2024-09-01T00:00:00Z",
    },
]

_users: list[dict[str, Any]] = [u.copy() for u in _SEED_USERS]


# ── Request models ───────────────────────────────────────────────────

class InvitePayload(BaseModel):
    email: str
    name: str
    roles: list[str]


class UpdateUserPayload(BaseModel):
    name: str | None = None
    roles: list[str] | None = None
    status: str | None = None


class BulkActionPayload(BaseModel):
    action: str
    user_ids: list[str]


# ── Helpers ──────────────────────────────────────────────────────────

def _meta(*, request_id: str | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "request_id": request_id or str(uuid4()),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        **extra,
    }


def _require_admin(user: AuthenticatedUser) -> None:
    if "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


# ── Routes ───────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    search: str = Query(default="", description="Search by name or email"),
    user_status: str = Query(default="all", alias="status", description="Filter by status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    _require_admin(user)
    filtered = _users
    if search:
        q = search.lower()
        filtered = [u for u in filtered if q in u["name"].lower() or q in u["email"].lower()]
    if user_status != "all":
        filtered = [u for u in filtered if u["status"] == user_status]
    total = len(filtered)
    page = filtered[offset : offset + limit]
    return {
        "data": page,
        "meta": {
            **_meta(),
            "pagination": {"total": total, "limit": limit, "offset": offset},
        },
    }


@router.post("/users/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(
    payload: InvitePayload,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    _require_admin(user)
    new_user = {
        "id": str(uuid4()),
        "name": payload.name,
        "email": payload.email,
        "roles": payload.roles,
        "status": "pending",
        "last_login": None,
        "mfa_enabled": False,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _users.append(new_user)
    return {"data": new_user, "meta": _meta()}


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    payload: UpdateUserPayload,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    _require_admin(user)
    for u in _users:
        if u["id"] == user_id:
            if payload.name is not None:
                u["name"] = payload.name
            if payload.roles is not None:
                u["roles"] = payload.roles
            if payload.status is not None:
                u["status"] = payload.status
            return {"data": u, "meta": _meta()}
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    _require_admin(user)
    for i, u in enumerate(_users):
        if u["id"] == user_id:
            _users.pop(i)
            return {"data": None, "meta": _meta()}
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.post("/users/bulk")
async def bulk_action(
    payload: BulkActionPayload,
    user: AuthenticatedUser = Depends(require_auth),
) -> dict[str, Any]:
    _require_admin(user)
    affected = 0
    if payload.action == "delete":
        before = len(_users)
        _users[:] = [u for u in _users if u["id"] not in payload.user_ids]
        affected = before - len(_users)
    elif payload.action in ("suspend", "activate"):
        new_status = "suspended" if payload.action == "suspend" else "active"
        for u in _users:
            if u["id"] in payload.user_ids:
                u["status"] = new_status
                affected += 1
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown action: {payload.action}")
    return {"data": {"affected": affected}, "meta": _meta()}
