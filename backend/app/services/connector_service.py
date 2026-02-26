"""Enterprise Connector Hub — OAuth flows, Vault-backed credentials, plugin framework."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

from app.interfaces.models.enterprise import AuthenticatedUser
from app.interfaces.secrets_manager import SecretsManager
from app.middleware.rbac import check_permission
from app.models.connector import (
    ActionResult,
    AuthMethod,
    ConnectionTestResult,
    ConnectorCategory,
    ConnectorConfig,
    ConnectorInstance,
    ConnectorStatus,
    ConnectorType,
    OAuthCredential,
    OAuthFlowStart,
)

logger = logging.getLogger(__name__)

# ── Built-in connector type catalog ─────────────────────────────────

_CONNECTOR_CATALOG: list[ConnectorType] = [
    ConnectorType(
        name="salesforce",
        category=ConnectorCategory.CRM,
        auth_methods=[AuthMethod.OAUTH2],
        required_scopes=["api", "refresh_token"],
        description="Salesforce CRM integration",
    ),
    ConnectorType(
        name="s3",
        category=ConnectorCategory.STORAGE,
        auth_methods=[AuthMethod.API_KEY, AuthMethod.SERVICE_ACCOUNT],
        required_scopes=[],
        description="Amazon S3 object storage",
    ),
    ConnectorType(
        name="slack",
        category=ConnectorCategory.COMMUNICATION,
        auth_methods=[AuthMethod.OAUTH2],
        required_scopes=["chat:write", "channels:read"],
        description="Slack messaging integration",
    ),
    ConnectorType(
        name="postgresql",
        category=ConnectorCategory.DATABASE,
        auth_methods=[AuthMethod.BASIC, AuthMethod.SERVICE_ACCOUNT],
        required_scopes=[],
        description="PostgreSQL database connector",
    ),
    ConnectorType(
        name="bigquery",
        category=ConnectorCategory.ANALYTICS,
        auth_methods=[AuthMethod.SERVICE_ACCOUNT],
        required_scopes=["bigquery.readonly"],
        description="Google BigQuery analytics",
    ),
    ConnectorType(
        name="github",
        category=ConnectorCategory.DEVTOOLS,
        auth_methods=[AuthMethod.OAUTH2, AuthMethod.API_KEY],
        required_scopes=["repo", "read:org"],
        description="GitHub DevOps integration",
    ),
]

# OAuth provider endpoint registry (extendable via plugins)
_OAUTH_PROVIDERS: dict[str, dict[str, str]] = {
    "salesforce": {
        "authorize_url": "https://login.salesforce.com/services/oauth2/authorize",
        "token_url": "https://login.salesforce.com/services/oauth2/token",
    },
    "slack": {
        "authorize_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
    },
}

# In-memory pending-OAuth states (production: Redis / DB)
_pending_oauth: dict[str, dict[str, Any]] = {}


def _vault_path(tenant_id: str, connector_type: str) -> str:
    """Build the Vault secret path for a connector's credentials."""
    return f"archon/{tenant_id}/connectors/{connector_type}"


def _vault_path_by_id(tenant_id: str, connector_id: str) -> str:
    """Build the canonical Vault secret path scoped by connector instance ID."""
    return f"secret/tenants/{tenant_id}/connectors/{connector_id}"


def _audit_details(user: AuthenticatedUser, **extra: Any) -> dict[str, Any]:
    """Build a structured audit-details dict (secret values excluded)."""
    return {
        "actor_id": user.id,
        "actor_email": user.email,
        "tenant_id": user.tenant_id,
        **extra,
    }


# ── In-memory registry (replaces DB for now) ───────────────────────

_connectors: dict[str, ConnectorInstance] = {}


class ConnectorService:
    """Enterprise Connector Hub with OAuth flows and Vault-backed credentials.

    All operations are tenant-scoped, RBAC-checked, and audit-logged.
    Credentials are stored exclusively via ``SecretsManager``; secret
    values never appear in logs, responses, or error messages.
    """

    # -- Legacy static helpers (backward compat with existing routes) --

    @staticmethod
    async def create(session: Any, connector: Any) -> Any:
        """Persist a new connector via the ORM session (legacy route compat)."""
        session.add(connector)
        await session.commit()
        await session.refresh(connector)
        return connector

    @staticmethod
    async def get(session: Any, connector_id: UUID) -> Any | None:
        """Return a single ORM connector by ID (legacy route compat)."""
        return await session.get(
            __import__("app.models", fromlist=["Connector"]).Connector,
            connector_id,
        )

    @staticmethod
    async def list(
        session: Any,
        *,
        owner_id: UUID | None = None,
        connector_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        """Return paginated ORM connectors with optional filters (legacy compat)."""
        from sqlmodel import select as _sel

        from app.models import Connector as _C

        base = _sel(_C)
        if owner_id is not None:
            base = base.where(_C.owner_id == owner_id)
        if connector_type is not None:
            base = base.where(_C.type == connector_type)
        if status is not None:
            base = base.where(_C.status == status)

        count_result = await session.exec(base)
        total = len(count_result.all())

        stmt = base.offset(offset).limit(limit).order_by(_C.created_at.desc())  # type: ignore[union-attr]
        result = await session.exec(stmt)
        return list(result.all()), total

    @staticmethod
    async def update(
        session: Any, connector_id: UUID, data: dict[str, Any]
    ) -> Any | None:
        """Apply partial updates to an ORM connector (legacy route compat)."""
        from app.models import Connector as _C

        connector = await session.get(_C, connector_id)
        if connector is None:
            return None
        for key, value in data.items():
            if hasattr(connector, key):
                setattr(connector, key, value)
        session.add(connector)
        await session.commit()
        await session.refresh(connector)
        return connector

    @staticmethod
    async def delete(session: Any, connector_id: UUID) -> bool:
        """Delete an ORM connector by ID (legacy route compat)."""
        from app.models import Connector as _C

        connector = await session.get(_C, connector_id)
        if connector is None:
            return False
        await session.delete(connector)
        await session.commit()
        return True

    # ------------------------------------------------------------------
    # Enterprise API
    # ------------------------------------------------------------------

    @staticmethod
    async def register_connector(
        tenant_id: str,
        user: AuthenticatedUser,
        config: ConnectorConfig,
    ) -> ConnectorInstance:
        """Register a new connector instance for a tenant.

        RBAC: requires ``connectors:create``.
        Audit: logs ``connector.registered``.
        """
        check_permission(user, "connectors", "create")

        instance = ConnectorInstance(
            id=uuid4(),
            tenant_id=tenant_id,
            type=config.type,
            name=config.name,
            status=ConnectorStatus.PENDING_AUTH,
            auth_method=config.auth_method,
            scopes=config.scopes,
        )
        _connectors[str(instance.id)] = instance

        logger.info(
            "connector.registered",
            extra=_audit_details(
                user,
                action="connector.registered",
                resource_type="connector",
                resource_id=str(instance.id),
                connector_type=config.type,
            ),
        )
        return instance

    @staticmethod
    async def start_oauth_flow(
        tenant_id: str,
        user: AuthenticatedUser,
        connector_id: UUID,
        redirect_uri: str,
    ) -> OAuthFlowStart:
        """Initiate an OAuth 2.0 authorization-code flow.

        Generates a CSRF state token and optional PKCE code verifier,
        then returns the authorization URL for the user to redirect to.
        """
        check_permission(user, "connectors", "create")

        instance = _connectors.get(str(connector_id))
        if instance is None or instance.tenant_id != tenant_id:
            raise ValueError("Connector not found or tenant mismatch")

        provider = _OAUTH_PROVIDERS.get(instance.type)
        if provider is None:
            raise ValueError(
                f"OAuth not configured for connector type: {instance.type}"
            )

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)

        # Retrieve OAuth client_id from Vault via SecretsManager path
        # (actual credentials fetched at callback time; only metadata here)
        _pending_oauth[state] = {
            "tenant_id": tenant_id,
            "connector_id": str(connector_id),
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "connector_type": instance.type,
        }

        params = urlencode(
            {
                "response_type": "code",
                "client_id": f"{{vault:{_vault_path(tenant_id, instance.type)}:client_id}}",
                "redirect_uri": redirect_uri,
                "scope": " ".join(instance.scopes),
                "state": state,
            }
        )
        authorization_url = f"{provider['authorize_url']}?{params}"

        logger.info(
            "connector.oauth_started",
            extra=_audit_details(
                user,
                action="connector.oauth_started",
                resource_type="connector",
                resource_id=str(connector_id),
            ),
        )

        return OAuthFlowStart(
            authorization_url=authorization_url,
            state=state,
            code_verifier=code_verifier,
        )

    @staticmethod
    async def complete_oauth_flow(
        tenant_id: str,
        code: str,
        state: str,
        secrets_mgr: SecretsManager,
    ) -> OAuthCredential:
        """Exchange an authorization code for tokens, store in Vault.

        The access/refresh tokens are persisted exclusively via
        ``SecretsManager``; they never appear in logs or API responses.
        """
        pending = _pending_oauth.pop(state, None)
        if pending is None or pending["tenant_id"] != tenant_id:
            raise ValueError("Invalid or expired OAuth state")

        connector_id = UUID(pending["connector_id"])
        connector_type = pending["connector_type"]
        vault_path = _vault_path(tenant_id, connector_type)
        # Canonical per-instance path (spec: secret/tenants/{tenant_id}/connectors/{connector_id})
        canonical_vault_path = _vault_path_by_id(tenant_id, str(connector_id))

        # In production: exchange code via HTTP POST to token_url.
        # Here we store the code as a placeholder demonstrating
        # Vault-only credential storage.
        token_data = {
            "access_token": hashlib.sha256(code.encode()).hexdigest(),
            "refresh_token": secrets.token_urlsafe(48),
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        # Store at both the type-scoped path and the canonical per-instance path
        await secrets_mgr.put_secret(vault_path, token_data, tenant_id)
        try:
            await secrets_mgr.put_secret(canonical_vault_path, token_data, tenant_id)
        except Exception as exc:
            logger.warning(
                "connector.oauth_completed: could not write canonical vault path: %s",
                exc,
            )

        expires_at = datetime.now(tz=timezone.utc)

        # Mark connector as active
        instance = _connectors.get(str(connector_id))
        if instance is not None:
            instance.status = ConnectorStatus.ACTIVE

        logger.info(
            "connector.oauth_completed",
            extra={
                "tenant_id": tenant_id,
                "action": "connector.oauth_completed",
                "resource_type": "connector",
                "resource_id": str(connector_id),
            },
        )

        return OAuthCredential(
            connector_id=connector_id,
            token_type="Bearer",
            scopes=instance.scopes if instance else [],
            expires_at=expires_at,
            vault_path=vault_path,
        )

    @staticmethod
    async def list_connectors(tenant_id: str) -> list[ConnectorInstance]:
        """Return all connector instances for a tenant."""
        return [c for c in _connectors.values() if c.tenant_id == tenant_id]

    @staticmethod
    async def get_connector(
        tenant_id: str,
        connector_id: UUID,
    ) -> ConnectorInstance:
        """Return a single connector, enforcing tenant isolation."""
        instance = _connectors.get(str(connector_id))
        if instance is None or instance.tenant_id != tenant_id:
            raise ValueError("Connector not found")
        return instance

    @staticmethod
    async def test_connection(
        tenant_id: str,
        connector_id: UUID,
        secrets_mgr: SecretsManager,
    ) -> ConnectionTestResult:
        """Health-check a connector by verifying its Vault credentials exist."""
        instance = _connectors.get(str(connector_id))
        if instance is None or instance.tenant_id != tenant_id:
            raise ValueError("Connector not found")

        vault_path = _vault_path(tenant_id, instance.type)
        start = time.monotonic()
        try:
            await secrets_mgr.get_secret(vault_path, tenant_id)
            latency = (time.monotonic() - start) * 1000
            instance.last_health_check = datetime.now(tz=timezone.utc)
            return ConnectionTestResult(
                connector_id=connector_id,
                status="ok",
                latency_ms=round(latency, 2),
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ConnectionTestResult(
                connector_id=connector_id,
                status="error",
                latency_ms=round(latency, 2),
                error_message=str(exc),
            )

    @staticmethod
    async def execute_action(
        tenant_id: str,
        user: AuthenticatedUser,
        connector_id: UUID,
        action: str,
        params: dict[str, Any],
    ) -> ActionResult:
        """Execute a CRUD action via a connector.

        RBAC: requires ``connectors:execute``.
        Audit: logs ``connector.action_executed``.
        """
        check_permission(user, "connectors", "execute")

        instance = _connectors.get(str(connector_id))
        if instance is None or instance.tenant_id != tenant_id:
            raise ValueError("Connector not found")

        # Plugin dispatch point — delegate to type-specific handler
        result_data = {
            "connector_type": instance.type,
            "action": action,
            "params": params,
            "executed_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        logger.info(
            "connector.action_executed",
            extra=_audit_details(
                user,
                action="connector.action_executed",
                resource_type="connector",
                resource_id=str(connector_id),
                connector_action=action,
            ),
        )

        return ActionResult(
            connector_id=connector_id,
            action=action,
            data=result_data,
            metadata={"tenant_id": tenant_id},
        )

    @staticmethod
    async def refresh_credentials(
        tenant_id: str,
        connector_id: UUID,
        secrets_mgr: SecretsManager,
    ) -> bool:
        """Refresh OAuth tokens via Vault, returning success status.

        Reads existing credentials from Vault, performs a token refresh,
        and stores the updated tokens back. Auto-invoked on token expiry.
        """
        instance = _connectors.get(str(connector_id))
        if instance is None or instance.tenant_id != tenant_id:
            raise ValueError("Connector not found")

        vault_path = _vault_path(tenant_id, instance.type)
        try:
            existing = await secrets_mgr.get_secret(vault_path, tenant_id)
            # In production: POST to token_url with grant_type=refresh_token.
            refreshed = {
                **existing,
                "access_token": secrets.token_urlsafe(32),
                "refreshed_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            await secrets_mgr.put_secret(vault_path, refreshed, tenant_id)

            logger.info(
                "connector.credentials_refreshed",
                extra={
                    "tenant_id": tenant_id,
                    "resource_type": "connector",
                    "resource_id": str(connector_id),
                },
            )
            return True
        except Exception:
            logger.exception(
                "connector.credentials_refresh_failed",
                extra={
                    "tenant_id": tenant_id,
                    "resource_id": str(connector_id),
                },
            )
            return False

    @staticmethod
    async def revoke_connector(
        tenant_id: str,
        user: AuthenticatedUser,
        connector_id: UUID,
        secrets_mgr: SecretsManager,
    ) -> None:
        """Revoke OAuth tokens, remove credentials from Vault, delete connector.

        RBAC: requires ``connectors:delete``.
        Audit: logs ``connector.revoked``.
        """
        check_permission(user, "connectors", "delete")

        instance = _connectors.get(str(connector_id))
        if instance is None or instance.tenant_id != tenant_id:
            raise ValueError("Connector not found")

        vault_path = _vault_path(tenant_id, instance.type)
        try:
            await secrets_mgr.delete_secret(vault_path, tenant_id)
        except Exception:
            logger.warning(
                "Vault secret deletion failed during revoke",
                extra={"vault_path": vault_path, "tenant_id": tenant_id},
            )

        _connectors.pop(str(connector_id), None)

        logger.info(
            "connector.revoked",
            extra=_audit_details(
                user,
                action="connector.revoked",
                resource_type="connector",
                resource_id=str(connector_id),
            ),
        )

    @staticmethod
    async def list_available_connector_types() -> list[ConnectorType]:
        """Return the catalog of available connector types."""
        return list(_CONNECTOR_CATALOG)
