"""Auth middleware helper functions for service-layer authorization."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.interfaces.models import UserClaims


def require_role(claims: UserClaims, role: str) -> None:
    """Raise ValueError if the user does not hold the required role."""
    if role not in claims.roles:
        raise ValueError(f"Missing required role: {role}")


def require_any_role(claims: UserClaims, roles: list[str]) -> None:
    """Raise ValueError if the user holds none of the specified roles."""
    if not any(r in claims.roles for r in roles):
        raise ValueError(f"Requires one of roles: {', '.join(roles)}")


def require_owner_or_role(
    claims: UserClaims,
    resource_owner_id: UUID,
    role: str,
) -> None:
    """Allow access if the user owns the resource or holds the given role."""
    if claims.user_id != str(resource_owner_id) and role not in claims.roles:
        raise ValueError(
            f"Access denied: must be resource owner or hold role '{role}'"
        )


def extract_actor_id(claims: UserClaims) -> UUID:
    """Extract the actor UUID from decoded JWT claims."""
    return UUID(claims.user_id)


def build_audit_context(claims: UserClaims) -> dict[str, Any]:
    """Build a dict suitable for AuditLog.details from user claims."""
    return {
        "actor_email": claims.email,
        "actor_roles": claims.roles,
    }
