"""Abstract interface for authentication and authorisation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.interfaces.models import User, UserClaims


@runtime_checkable
class AuthProvider(Protocol):
    """Contract for authentication backends."""

    async def verify_token(self, token: str) -> UserClaims:
        """Validate a JWT and return decoded claims."""
        ...

    async def get_current_user(self, token: str) -> User:
        """Resolve a token to a full User object."""
        ...

    async def check_permission(
        self, user: User, resource: str, action: str
    ) -> bool:
        """Return True if the user may perform *action* on *resource*."""
        ...


__all__ = ["AuthProvider"]
