"""Role-based access control middleware with tenant-scoped permissions."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Callable

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user

logger = logging.getLogger(__name__)


class Action(str, Enum):
    """Permitted actions on a resource."""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    ADMIN = "admin"


# ---------------------------------------------------------------------------
# Default role → permission mappings
# ---------------------------------------------------------------------------
# Mapping: role -> set of allowed actions (applied to *any* resource unless
# the role is resource-scoped, e.g. ``agent_creator``).

_ROLE_ACTIONS: dict[str, set[str]] = {
    "admin": {a.value for a in Action},
    "operator": {Action.READ.value, Action.EXECUTE.value},
    "viewer": {Action.READ.value},
    "agent_creator": {Action.CREATE.value, Action.READ.value},
}

# Resource-specific role constraints.  If a role appears here, its
# permissions are limited to the listed resources only.
_ROLE_RESOURCES: dict[str, set[str] | None] = {
    "admin": None,  # all resources
    "operator": None,
    "viewer": None,
    "agent_creator": {"agents"},
}


# ---------------------------------------------------------------------------
# Permission checking
# ---------------------------------------------------------------------------


def check_permission(
    user: AuthenticatedUser,
    resource: str,
    action: str,
) -> bool:
    """Return ``True`` if *user* may perform *action* on *resource*.

    Permission is granted when **any** of the user's roles includes the
    requested action for the given resource.  Explicit ``permissions`` strings
    on the user (format ``resource:action``) are also honoured.

    This is the synchronous fast-path that only checks built-in roles and
    explicit permission strings.  For custom DB-backed roles use
    ``check_permission_db()`` instead.
    """
    required = f"{resource}:{action}"

    # 1. Check explicit permission strings (includes wildcard "*")
    if required in user.permissions or "*" in user.permissions:
        return True

    # 2. Check role-based mappings
    for role in user.roles:
        allowed_actions = _ROLE_ACTIONS.get(role)
        if allowed_actions is None:
            continue
        if action not in allowed_actions:
            continue
        # Verify resource scope (None means all resources allowed)
        allowed_resources = _ROLE_RESOURCES.get(role)
        if allowed_resources is None or resource in allowed_resources:
            return True

    return False


async def check_permission_db(
    user: AuthenticatedUser,
    resource: str,
    action: str,
    *,
    session: AsyncSession | None = None,
) -> bool:
    """Return ``True`` if *user* may perform *action* on *resource*.

    Extends ``check_permission`` with a DB lookup for custom roles when
    *session* is provided.
    """
    # Fast path: built-in roles + explicit permissions
    if check_permission(user, resource, action):
        return True

    # Check custom roles from DB (when session is available)
    if session is not None:
        try:
            from uuid import UUID

            from sqlmodel import select

            from app.models.rbac import CustomRole

            try:
                tenant_uuid = UUID(user.tenant_id)
            except ValueError:
                return False

            stmt = select(CustomRole).where(
                CustomRole.tenant_id == tenant_uuid,
                CustomRole.name.in_(user.roles),  # type: ignore[attr-defined]
            )
            result = await session.exec(stmt)
            custom_roles = result.all()

            for custom_role in custom_roles:
                perms: dict[str, list[str]] = custom_role.permissions or {}
                # Format: {"agents": ["create", "read"], "*": ["read"], ...}
                for res_key, actions in perms.items():
                    if res_key in (resource, "*") and action in actions:
                        return True
        except Exception:
            logger.debug("rbac: DB custom-role lookup failed", exc_info=True)

    return False


def require_permission(
    resource: str,
    action: str,
) -> Callable[..., AuthenticatedUser]:
    """Return a FastAPI ``Depends`` callable that enforces an RBAC check.

    Checks both built-in roles (fast path) and DB-backed custom roles.

    Usage::

        @router.post("/agents")
        async def create_agent(
            user: AuthenticatedUser = Depends(require_permission("agents", "create")),
        ): ...
    """

    async def _dependency(
        user: AuthenticatedUser = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> AuthenticatedUser:
        if not await check_permission_db(user, resource, action, session=session):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {resource}:{action}",
            )
        return user

    return _dependency
