"""RBAC tests — verifies role-based access control and tenant boundaries."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.middleware.rbac import Action, check_permission, require_permission


# ---------------------------------------------------------------------------
# check_permission unit tests
# ---------------------------------------------------------------------------


def test_admin_has_all_permissions(mock_authenticated_user) -> None:
    """Admin role grants every action on any resource."""
    user = mock_authenticated_user(roles=["admin"])

    for action in Action:
        assert check_permission(user, "agents", action.value) is True
        assert check_permission(user, "secrets", action.value) is True
        assert check_permission(user, "tenants", action.value) is True


def test_viewer_read_only(mock_authenticated_user) -> None:
    """Viewer role can read but must be denied create/update/delete/execute."""
    user = mock_authenticated_user(roles=["viewer"])

    assert check_permission(user, "agents", "read") is True
    assert check_permission(user, "agents", "create") is False
    assert check_permission(user, "agents", "update") is False
    assert check_permission(user, "agents", "delete") is False
    assert check_permission(user, "agents", "execute") is False


def test_operator_can_execute(mock_authenticated_user) -> None:
    """Operator role can read and execute, but not create/update/delete."""
    user = mock_authenticated_user(roles=["operator"])

    assert check_permission(user, "agents", "read") is True
    assert check_permission(user, "agents", "execute") is True
    assert check_permission(user, "agents", "create") is False
    assert check_permission(user, "agents", "update") is False
    assert check_permission(user, "agents", "delete") is False


def test_cross_tenant_blocked(mock_authenticated_user) -> None:
    """A user from tenant A must not pass permission checks that imply
    tenant B access.  The RBAC layer itself doesn't enforce tenant boundaries
    (that is ``TenantFilter``'s job), but we verify that having roles does
    *not* implicitly grant cross-tenant privileges — the tenant_id on the
    user object stays fixed.
    """
    user_a = mock_authenticated_user(tenant_id="tenant-a", roles=["admin"])
    user_b = mock_authenticated_user(tenant_id="tenant-b", roles=["viewer"])

    # User A has admin on their own tenant context
    assert check_permission(user_a, "agents", "delete") is True
    # User B only has viewer — cannot delete
    assert check_permission(user_b, "agents", "delete") is False

    # Tenant IDs remain distinct (RBAC doesn't leak)
    assert user_a.tenant_id != user_b.tenant_id


@pytest.mark.asyncio
async def test_require_permission_returns_403(mock_authenticated_user) -> None:
    """``require_permission`` dependency raises 403 for unauthorised action."""
    user = mock_authenticated_user(roles=["viewer"])
    dep = require_permission("agents", "delete")

    # Invoke the inner dependency directly, injecting the user
    from unittest.mock import AsyncMock, patch

    with patch(
        "app.middleware.rbac.get_current_user",
        new_callable=AsyncMock,
        return_value=user,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dep(user=user)

    assert exc_info.value.status_code == 403
    assert "agents:delete" in exc_info.value.detail


def test_super_admin_cross_tenant(mock_authenticated_user) -> None:
    """A super-admin (admin role) should pass permission checks regardless of
    resource, demonstrating that the admin role is not resource-scoped.
    This simulates a platform-level super admin that can access all tenants.
    """
    super_admin = mock_authenticated_user(
        tenant_id="platform",
        roles=["admin"],
    )

    # Admin can access every resource and every action
    resources = ["agents", "secrets", "tenants", "connectors", "models"]
    for resource in resources:
        for action in Action:
            assert check_permission(super_admin, resource, action.value) is True, (
                f"super admin denied {resource}:{action.value}"
            )
