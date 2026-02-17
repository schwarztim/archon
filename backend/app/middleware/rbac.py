"""Role-based access control middleware with tenant-scoped permissions."""

from __future__ import annotations

from enum import Enum
from typing import Callable

from fastapi import Depends, HTTPException, status

from app.interfaces.models.enterprise import AuthenticatedUser
from app.middleware.auth import get_current_user


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
    """
    required = f"{resource}:{action}"

    # 1. Check explicit permission strings
    if required in user.permissions:
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


def require_permission(
    resource: str,
    action: str,
) -> Callable[..., AuthenticatedUser]:
    """Return a FastAPI ``Depends`` callable that enforces an RBAC check.

    Usage::

        @router.post("/agents")
        async def create_agent(
            user: AuthenticatedUser = Depends(require_permission("agents", "create")),
        ): ...
    """

    async def _dependency(
        user: AuthenticatedUser = Depends(get_current_user),
    ) -> AuthenticatedUser:
        if not check_permission(user, resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {resource}:{action}",
            )
        return user

    return _dependency
