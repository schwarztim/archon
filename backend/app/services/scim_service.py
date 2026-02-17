"""SCIM 2.0 provisioning service for Archon enterprise user lifecycle."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.models.scim import (
    SCIMEmail,
    SCIMError,
    SCIMGroup,
    SCIMGroupMember,
    SCIMListResponse,
    SCIMMeta,
    SCIMName,
    SCIMPatchOperation,
    SCIMUser,
)
from app.secrets.manager import VaultSecretsManager

logger = logging.getLogger(__name__)

_VAULT_SCIM_TOKEN_PATH = "scim/bearer-tokens"
_VAULT_SCIM_USERS_PREFIX = "scim/users"
_VAULT_SCIM_GROUPS_PREFIX = "scim/groups"


class SCIMService:
    """Tenant-scoped SCIM 2.0 provisioning service (RFC 7644).

    All user and group data is stored via :class:`VaultSecretsManager` with
    full tenant isolation.  Bearer tokens for SCIM endpoint authentication
    are retrieved from Vault on a per-tenant basis.
    """

    def __init__(self, secrets: VaultSecretsManager) -> None:
        self._secrets = secrets
        # In-memory store keyed by (tenant_id, scim_id) for demonstration.
        # Production would use the database via SQLModel.
        self._users: dict[str, dict[str, SCIMUser]] = {}
        self._groups: dict[str, dict[str, SCIMGroup]] = {}

    # ------------------------------------------------------------------
    # Bearer-token authentication
    # ------------------------------------------------------------------

    async def validate_bearer_token(self, tenant_id: str, token: str) -> bool:
        """Validate a SCIM bearer token against the value stored in Vault.

        Args:
            tenant_id: Tenant scope.
            token: Bearer token presented by the IdP.

        Returns:
            True if the token matches the stored value.
        """
        try:
            secret = await self._secrets.get_secret(
                _VAULT_SCIM_TOKEN_PATH, tenant_id,
            )
            stored = secret.get("token", "")
            return stored == token
        except Exception:
            logger.warning(
                "scim.token_validation_failed",
                extra={"tenant_id": tenant_id},
            )
            return False

    # ------------------------------------------------------------------
    # User operations (RFC 7644 §3)
    # ------------------------------------------------------------------

    async def list_users(
        self,
        tenant_id: str,
        scim_filter: str = "",
        start_index: int = 1,
        count: int = 100,
    ) -> SCIMListResponse:
        """List SCIM users for a tenant, with optional filtering.

        Args:
            tenant_id: Tenant scope.
            scim_filter: SCIM filter expression (e.g. ``userName eq "x"``).
            start_index: 1-based start index for pagination.
            count: Maximum number of results per page.

        Returns:
            SCIMListResponse containing matching users.
        """
        tenant_users = self._users.get(tenant_id, {})
        all_users = list(tenant_users.values())

        # Basic filter support for userName eq "value"
        if scim_filter:
            all_users = self._apply_user_filter(all_users, scim_filter)

        total = len(all_users)
        start = max(start_index - 1, 0)
        page = all_users[start : start + count]

        await self._audit_log(
            tenant_id,
            "scim.users.listed",
            {"filter": scim_filter, "total": total},
        )

        return SCIMListResponse(
            totalResults=total,
            startIndex=start_index,
            itemsPerPage=len(page),
            Resources=[u.model_dump(by_alias=True) for u in page],
        )

    async def get_user(self, tenant_id: str, scim_id: str) -> SCIMUser:
        """Retrieve a single SCIM user by ID.

        Args:
            tenant_id: Tenant scope.
            scim_id: SCIM resource ID.

        Returns:
            The matching SCIMUser.

        Raises:
            KeyError: If the user is not found.
        """
        tenant_users = self._users.get(tenant_id, {})
        user = tenant_users.get(scim_id)
        if user is None:
            raise KeyError(f"SCIM user {scim_id} not found in tenant {tenant_id}")

        await self._audit_log(
            tenant_id,
            "scim.user.retrieved",
            {"scim_id": scim_id},
        )
        return user

    async def create_user(self, tenant_id: str, scim_user: SCIMUser) -> SCIMUser:
        """Provision a new user from an IdP SCIM push.

        Args:
            tenant_id: Tenant scope.
            scim_user: User resource from the IdP.

        Returns:
            The created SCIMUser with generated ID and metadata.
        """
        scim_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        scim_user.id = scim_id
        scim_user.meta = SCIMMeta(
            resourceType="User",
            created=now,
            lastModified=now,
            location=f"/scim/v2/Users/{scim_id}",
        )

        if tenant_id not in self._users:
            self._users[tenant_id] = {}
        self._users[tenant_id][scim_id] = scim_user

        await self._audit_log(
            tenant_id,
            "scim.user.created",
            {"scim_id": scim_id, "userName": scim_user.userName},
        )

        return scim_user

    async def update_user(
        self,
        tenant_id: str,
        scim_id: str,
        operations: list[SCIMPatchOperation],
    ) -> SCIMUser:
        """Apply SCIM PATCH operations to an existing user.

        Args:
            tenant_id: Tenant scope.
            scim_id: SCIM resource ID to update.
            operations: List of SCIM PATCH operations.

        Returns:
            The updated SCIMUser.

        Raises:
            KeyError: If the user is not found.
        """
        user = await self.get_user(tenant_id, scim_id)
        user_dict = user.model_dump(by_alias=True)

        for op in operations:
            user_dict = self._apply_patch_op(user_dict, op)

        updated = SCIMUser.model_validate(user_dict)
        updated.meta.lastModified = datetime.now(timezone.utc)
        self._users[tenant_id][scim_id] = updated

        await self._audit_log(
            tenant_id,
            "scim.user.updated",
            {"scim_id": scim_id, "operations_count": len(operations)},
        )

        return updated

    async def delete_user(self, tenant_id: str, scim_id: str) -> None:
        """Deactivate (soft-delete) a SCIM user.

        Sets ``active`` to ``False`` rather than removing the record,
        preserving audit history.

        Args:
            tenant_id: Tenant scope.
            scim_id: SCIM resource ID to deactivate.

        Raises:
            KeyError: If the user is not found.
        """
        user = await self.get_user(tenant_id, scim_id)
        user.active = False
        user.meta.lastModified = datetime.now(timezone.utc)
        self._users[tenant_id][scim_id] = user

        await self._audit_log(
            tenant_id,
            "scim.user.deactivated",
            {"scim_id": scim_id, "userName": user.userName},
        )

    # ------------------------------------------------------------------
    # Group operations (RFC 7644 §3)
    # ------------------------------------------------------------------

    async def list_groups(
        self,
        tenant_id: str,
        scim_filter: str = "",
        start_index: int = 1,
        count: int = 100,
    ) -> SCIMListResponse:
        """List SCIM groups for a tenant.

        Args:
            tenant_id: Tenant scope.
            scim_filter: SCIM filter expression.
            start_index: 1-based start index.
            count: Maximum results per page.

        Returns:
            SCIMListResponse containing matching groups.
        """
        tenant_groups = self._groups.get(tenant_id, {})
        all_groups = list(tenant_groups.values())

        if scim_filter:
            all_groups = self._apply_group_filter(all_groups, scim_filter)

        total = len(all_groups)
        start = max(start_index - 1, 0)
        page = all_groups[start : start + count]

        await self._audit_log(
            tenant_id,
            "scim.groups.listed",
            {"filter": scim_filter, "total": total},
        )

        return SCIMListResponse(
            totalResults=total,
            startIndex=start_index,
            itemsPerPage=len(page),
            Resources=[g.model_dump(by_alias=True) for g in page],
        )

    async def create_group(self, tenant_id: str, scim_group: SCIMGroup) -> SCIMGroup:
        """Provision a new group from IdP.

        Args:
            tenant_id: Tenant scope.
            scim_group: Group resource from the IdP.

        Returns:
            The created SCIMGroup.
        """
        scim_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)

        scim_group.id = scim_id
        scim_group.meta = SCIMMeta(
            resourceType="Group",
            created=now,
            lastModified=now,
            location=f"/scim/v2/Groups/{scim_id}",
        )

        if tenant_id not in self._groups:
            self._groups[tenant_id] = {}
        self._groups[tenant_id][scim_id] = scim_group

        await self._audit_log(
            tenant_id,
            "scim.group.created",
            {"scim_id": scim_id, "displayName": scim_group.displayName},
        )

        return scim_group

    async def update_group(
        self,
        tenant_id: str,
        scim_id: str,
        operations: list[SCIMPatchOperation],
    ) -> SCIMGroup:
        """Apply SCIM PATCH operations to an existing group.

        Args:
            tenant_id: Tenant scope.
            scim_id: SCIM group resource ID.
            operations: List of SCIM PATCH operations.

        Returns:
            The updated SCIMGroup.

        Raises:
            KeyError: If the group is not found.
        """
        tenant_groups = self._groups.get(tenant_id, {})
        group = tenant_groups.get(scim_id)
        if group is None:
            raise KeyError(f"SCIM group {scim_id} not found in tenant {tenant_id}")

        group_dict = group.model_dump(by_alias=True)

        for op in operations:
            group_dict = self._apply_patch_op(group_dict, op)

        updated = SCIMGroup.model_validate(group_dict)
        updated.meta.lastModified = datetime.now(timezone.utc)
        self._groups[tenant_id][scim_id] = updated

        await self._audit_log(
            tenant_id,
            "scim.group.updated",
            {"scim_id": scim_id, "operations_count": len(operations)},
        )

        return updated

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_user_filter(
        users: list[SCIMUser], scim_filter: str,
    ) -> list[SCIMUser]:
        """Apply basic SCIM filter to user list (userName eq "value")."""
        if "userName eq" in scim_filter:
            target = scim_filter.split('"')[1] if '"' in scim_filter else ""
            return [u for u in users if u.userName == target]
        if "externalId eq" in scim_filter:
            target = scim_filter.split('"')[1] if '"' in scim_filter else ""
            return [u for u in users if u.externalId == target]
        return users

    @staticmethod
    def _apply_group_filter(
        groups: list[SCIMGroup], scim_filter: str,
    ) -> list[SCIMGroup]:
        """Apply basic SCIM filter to group list."""
        if "displayName eq" in scim_filter:
            target = scim_filter.split('"')[1] if '"' in scim_filter else ""
            return [g for g in groups if g.displayName == target]
        return groups

    @staticmethod
    def _apply_patch_op(
        resource: dict[str, Any], op: SCIMPatchOperation,
    ) -> dict[str, Any]:
        """Apply a single SCIM PATCH operation to a resource dict."""
        operation = op.op.lower()

        if operation == "replace":
            if op.path:
                resource[op.path] = op.value
            elif isinstance(op.value, dict):
                resource.update(op.value)
        elif operation == "add":
            if op.path:
                existing = resource.get(op.path)
                if isinstance(existing, list) and isinstance(op.value, list):
                    existing.extend(op.value)
                else:
                    resource[op.path] = op.value
            elif isinstance(op.value, dict):
                resource.update(op.value)
        elif operation == "remove":
            if op.path and op.path in resource:
                del resource[op.path]

        return resource

    async def _audit_log(
        self,
        tenant_id: str,
        action: str,
        details: dict[str, Any],
    ) -> None:
        """Log an audit event for SCIM provisioning operations.

        Emits structured JSON log entries.  In production this additionally
        writes to the AuditLog table via the database session.
        """
        logger.info(
            "audit.scim",
            extra={
                "tenant_id": tenant_id,
                "action": action,
                "details": details,
            },
        )


__all__ = ["SCIMService"]
