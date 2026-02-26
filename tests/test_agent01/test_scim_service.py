"""Comprehensive tests for SCIMService — SCIM 2.0 provisioning."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.models.scim import (
    SCIMEmail,
    SCIMGroup,
    SCIMGroupMember,
    SCIMListResponse,
    SCIMName,
    SCIMPatchOperation,
    SCIMUser,
)
from app.services.scim_service import SCIMService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TENANT_A = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
_TENANT_B = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb"


def _make_scim_user(
    user_name: str = "alice@example.com",
    display_name: str = "Alice",
    external_id: str = "ext-001",
) -> SCIMUser:
    return SCIMUser(
        userName=user_name,
        displayName=display_name,
        externalId=external_id,
        name=SCIMName(givenName="Alice", familyName="Smith"),
        emails=[SCIMEmail(value=user_name)],
    )


def _make_scim_group(
    display_name: str = "Engineering",
    external_id: str = "grp-001",
) -> SCIMGroup:
    return SCIMGroup(
        displayName=display_name,
        externalId=external_id,
    )


@pytest.fixture()
def mock_secrets() -> AsyncMock:
    secrets = AsyncMock()
    secrets.get_secret = AsyncMock(return_value={"token": "valid-token"})
    return secrets


@pytest.fixture()
def svc(mock_secrets: AsyncMock) -> SCIMService:
    return SCIMService(secrets=mock_secrets)


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------


class TestListUsers:
    """Tests for SCIMService.list_users."""

    @pytest.mark.asyncio
    async def test_empty_tenant_returns_zero(self, svc: SCIMService) -> None:
        result = await svc.list_users(_TENANT_A)
        assert isinstance(result, SCIMListResponse)
        assert result.totalResults == 0
        assert result.Resources == []

    @pytest.mark.asyncio
    async def test_returns_created_users(self, svc: SCIMService) -> None:
        await svc.create_user(_TENANT_A, _make_scim_user())
        await svc.create_user(_TENANT_A, _make_scim_user("bob@example.com"))
        result = await svc.list_users(_TENANT_A)
        assert result.totalResults == 2
        assert result.itemsPerPage == 2

    @pytest.mark.asyncio
    async def test_pagination_start_index(self, svc: SCIMService) -> None:
        for i in range(5):
            await svc.create_user(
                _TENANT_A,
                _make_scim_user(f"user{i}@example.com"),
            )
        result = await svc.list_users(_TENANT_A, start_index=3, count=2)
        assert result.startIndex == 3
        assert result.itemsPerPage == 2
        assert result.totalResults == 5

    @pytest.mark.asyncio
    async def test_filter_by_username(self, svc: SCIMService) -> None:
        await svc.create_user(_TENANT_A, _make_scim_user("alice@example.com"))
        await svc.create_user(_TENANT_A, _make_scim_user("bob@example.com"))
        result = await svc.list_users(
            _TENANT_A,
            scim_filter='userName eq "alice@example.com"',
        )
        assert result.totalResults == 1


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------


class TestCreateUser:
    """Tests for SCIMService.create_user."""

    @pytest.mark.asyncio
    async def test_provisions_user_with_id(self, svc: SCIMService) -> None:
        user = await svc.create_user(_TENANT_A, _make_scim_user())
        assert user.id != ""
        assert user.userName == "alice@example.com"

    @pytest.mark.asyncio
    async def test_meta_set_on_creation(self, svc: SCIMService) -> None:
        user = await svc.create_user(_TENANT_A, _make_scim_user())
        assert user.meta.resourceType == "User"
        assert user.meta.created is not None
        assert user.meta.lastModified is not None
        assert user.meta.location.startswith("/scim/v2/Users/")

    @pytest.mark.asyncio
    async def test_created_user_retrievable(self, svc: SCIMService) -> None:
        created = await svc.create_user(_TENANT_A, _make_scim_user())
        retrieved = await svc.get_user(_TENANT_A, created.id)
        assert retrieved.userName == created.userName


# ---------------------------------------------------------------------------
# update_user (SCIM PATCH)
# ---------------------------------------------------------------------------


class TestUpdateUser:
    """Tests for SCIMService.update_user with SCIM PATCH operations."""

    @pytest.mark.asyncio
    async def test_replace_display_name(self, svc: SCIMService) -> None:
        user = await svc.create_user(_TENANT_A, _make_scim_user())
        ops = [SCIMPatchOperation(op="replace", path="displayName", value="Alice S.")]
        updated = await svc.update_user(_TENANT_A, user.id, ops)
        assert updated.displayName == "Alice S."

    @pytest.mark.asyncio
    async def test_replace_active_flag(self, svc: SCIMService) -> None:
        user = await svc.create_user(_TENANT_A, _make_scim_user())
        ops = [SCIMPatchOperation(op="replace", path="active", value=False)]
        updated = await svc.update_user(_TENANT_A, user.id, ops)
        assert updated.active is False

    @pytest.mark.asyncio
    async def test_update_modifies_last_modified(self, svc: SCIMService) -> None:
        user = await svc.create_user(_TENANT_A, _make_scim_user())
        original_modified = user.meta.lastModified
        ops = [SCIMPatchOperation(op="replace", path="displayName", value="New")]
        updated = await svc.update_user(_TENANT_A, user.id, ops)
        assert updated.meta.lastModified >= original_modified

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self, svc: SCIMService) -> None:
        ops = [SCIMPatchOperation(op="replace", path="displayName", value="X")]
        with pytest.raises(KeyError):
            await svc.update_user(_TENANT_A, "nonexistent-id", ops)


# ---------------------------------------------------------------------------
# delete_user (soft-delete / deactivate)
# ---------------------------------------------------------------------------


class TestDeleteUser:
    """Tests for SCIMService.delete_user (soft-delete)."""

    @pytest.mark.asyncio
    async def test_deactivates_user(self, svc: SCIMService) -> None:
        user = await svc.create_user(_TENANT_A, _make_scim_user())
        await svc.delete_user(_TENANT_A, user.id)
        deactivated = await svc.get_user(_TENANT_A, user.id)
        assert deactivated.active is False

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises(self, svc: SCIMService) -> None:
        with pytest.raises(KeyError):
            await svc.delete_user(_TENANT_A, "no-such-id")

    @pytest.mark.asyncio
    async def test_delete_updates_last_modified(self, svc: SCIMService) -> None:
        user = await svc.create_user(_TENANT_A, _make_scim_user())
        original = user.meta.lastModified
        await svc.delete_user(_TENANT_A, user.id)
        deactivated = await svc.get_user(_TENANT_A, user.id)
        assert deactivated.meta.lastModified >= original


# ---------------------------------------------------------------------------
# list_groups & create_group
# ---------------------------------------------------------------------------


class TestGroups:
    """Tests for SCIMService group operations."""

    @pytest.mark.asyncio
    async def test_list_groups_empty(self, svc: SCIMService) -> None:
        result = await svc.list_groups(_TENANT_A)
        assert isinstance(result, SCIMListResponse)
        assert result.totalResults == 0

    @pytest.mark.asyncio
    async def test_create_group_assigns_id(self, svc: SCIMService) -> None:
        group = await svc.create_group(_TENANT_A, _make_scim_group())
        assert group.id != ""
        assert group.displayName == "Engineering"

    @pytest.mark.asyncio
    async def test_create_group_meta(self, svc: SCIMService) -> None:
        group = await svc.create_group(_TENANT_A, _make_scim_group())
        assert group.meta.resourceType == "Group"
        assert group.meta.location.startswith("/scim/v2/Groups/")

    @pytest.mark.asyncio
    async def test_list_groups_returns_created(self, svc: SCIMService) -> None:
        await svc.create_group(_TENANT_A, _make_scim_group("Eng"))
        await svc.create_group(_TENANT_A, _make_scim_group("Sales"))
        result = await svc.list_groups(_TENANT_A)
        assert result.totalResults == 2

    @pytest.mark.asyncio
    async def test_filter_groups_by_display_name(self, svc: SCIMService) -> None:
        await svc.create_group(_TENANT_A, _make_scim_group("Eng"))
        await svc.create_group(_TENANT_A, _make_scim_group("Sales"))
        result = await svc.list_groups(
            _TENANT_A,
            scim_filter='displayName eq "Eng"',
        )
        assert result.totalResults == 1


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """Verify SCIM operations are tenant-scoped."""

    @pytest.mark.asyncio
    async def test_users_isolated_between_tenants(self, svc: SCIMService) -> None:
        await svc.create_user(_TENANT_A, _make_scim_user("a@example.com"))
        await svc.create_user(_TENANT_B, _make_scim_user("b@example.com"))
        a_result = await svc.list_users(_TENANT_A)
        b_result = await svc.list_users(_TENANT_B)
        assert a_result.totalResults == 1
        assert b_result.totalResults == 1

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_get_tenant_b_user(
        self,
        svc: SCIMService,
    ) -> None:
        user_b = await svc.create_user(_TENANT_B, _make_scim_user())
        with pytest.raises(KeyError):
            await svc.get_user(_TENANT_A, user_b.id)

    @pytest.mark.asyncio
    async def test_groups_isolated_between_tenants(self, svc: SCIMService) -> None:
        await svc.create_group(_TENANT_A, _make_scim_group("GroupA"))
        await svc.create_group(_TENANT_B, _make_scim_group("GroupB"))
        a_result = await svc.list_groups(_TENANT_A)
        b_result = await svc.list_groups(_TENANT_B)
        assert a_result.totalResults == 1
        assert b_result.totalResults == 1


# ---------------------------------------------------------------------------
# SCIM error handling
# ---------------------------------------------------------------------------


class TestSCIMErrorHandling:
    """Tests for SCIM error scenarios."""

    @pytest.mark.asyncio
    async def test_get_user_404(self, svc: SCIMService) -> None:
        with pytest.raises(KeyError, match="not found"):
            await svc.get_user(_TENANT_A, "does-not-exist")

    @pytest.mark.asyncio
    async def test_delete_user_404(self, svc: SCIMService) -> None:
        with pytest.raises(KeyError, match="not found"):
            await svc.delete_user(_TENANT_A, "does-not-exist")

    @pytest.mark.asyncio
    async def test_update_group_404(self, svc: SCIMService) -> None:
        ops = [SCIMPatchOperation(op="replace", path="displayName", value="X")]
        with pytest.raises(KeyError, match="not found"):
            await svc.update_group(_TENANT_A, "no-group", ops)

    @pytest.mark.asyncio
    async def test_validate_bearer_token_valid(
        self,
        svc: SCIMService,
        mock_secrets: AsyncMock,
    ) -> None:
        result = await svc.validate_bearer_token(_TENANT_A, "valid-token")
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_bearer_token_invalid(
        self,
        svc: SCIMService,
        mock_secrets: AsyncMock,
    ) -> None:
        result = await svc.validate_bearer_token(_TENANT_A, "wrong-token")
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_bearer_token_vault_error(
        self,
        svc: SCIMService,
        mock_secrets: AsyncMock,
    ) -> None:
        mock_secrets.get_secret.side_effect = Exception("vault unavailable")
        result = await svc.validate_bearer_token(_TENANT_A, "any")
        assert result is False
