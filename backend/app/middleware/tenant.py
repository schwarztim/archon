"""Tenant context middleware and query-level tenant isolation."""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from fastapi import Depends, HTTPException, Request, status

from app.interfaces.models.enterprise import AuthenticatedUser, TenantContext
from app.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

# In-memory tenant config cache (keyed by tenant_id).
# Production deployments should replace this with a database or config-service
# lookup; this provides a working default.
_tenant_cache: dict[str, TenantContext] = {}

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Simple tenant_id extractor (no full context resolution required)
# ---------------------------------------------------------------------------


async def get_tenant_id(request: Request) -> str:
    """Extract ``tenant_id`` from request state set by ``TenantMiddleware``.

    Falls back to ``'default-tenant'`` when no tenant has been resolved
    (e.g. unauthenticated health-check routes).

    Usage::

        @router.get("/items")
        async def list_items(tenant_id: str = Depends(get_tenant_id)):
            ...
    """
    return getattr(request.state, "tenant_id", "default-tenant")


# ---------------------------------------------------------------------------
# Core dependency
# ---------------------------------------------------------------------------


async def get_tenant_context(
    user: AuthenticatedUser = Depends(get_current_user),
) -> TenantContext:
    """Resolve the full ``TenantContext`` for the authenticated user's tenant.

    Raises HTTP 403 if the tenant_id is missing or cannot be resolved.
    """
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tenant associated with this user",
        )

    cached = _tenant_cache.get(user.tenant_id)
    if cached is not None:
        return cached

    # Build a default context from the user's JWT claims.
    # A real implementation would query a tenant-config service or database.
    context = TenantContext(
        tenant_id=user.tenant_id,
        name=user.tenant_id,
        vault_namespace=f"tenants/{user.tenant_id}",
        keycloak_realm=user.tenant_id,
    )
    _tenant_cache[user.tenant_id] = context
    return context


async def require_tenant(
    ctx: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    """FastAPI dependency that ensures a valid tenant context exists.

    Returns the ``TenantContext`` or raises HTTP 403.
    """
    return ctx


# ---------------------------------------------------------------------------
# Query-level tenant isolation
# ---------------------------------------------------------------------------


class TenantFilter:
    """SQLModel/SQLAlchemy query filter that enforces tenant isolation.

    Usage::

        tf = TenantFilter(user.tenant_id)
        stmt = select(Agent).where(tf.apply(Agent))
        # → SELECT ... WHERE agent.tenant_id = :tenant_id

        # Or compose manually:
        stmt = select(Agent).where(Agent.tenant_id == tf.tenant_id)
    """

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id

    def apply(self, model: Any) -> Any:
        """Return a SQLAlchemy clause ``model.tenant_id == self.tenant_id``.

        Raises ``AttributeError`` if the model lacks a ``tenant_id`` column.
        """
        if not hasattr(model, "tenant_id"):
            raise AttributeError(f"{model.__name__} does not have a tenant_id column")
        return model.tenant_id == self.tenant_id  # type: ignore[return-value]

    def __repr__(self) -> str:
        return f"TenantFilter(tenant_id={self.tenant_id!r})"
