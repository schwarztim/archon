"""OAuth 2.0 flow logic for connector providers."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from app.interfaces.secrets_manager import SecretsManager

logger = logging.getLogger(__name__)


# ── OAuth provider endpoint registry ────────────────────────────────

_OAUTH_ENDPOINTS: dict[str, dict[str, str]] = {
    "salesforce": {
        "authorize_url": "https://login.salesforce.com/services/oauth2/authorize",
        "token_url": "https://login.salesforce.com/services/oauth2/token",
        "default_scopes": "api refresh_token",
    },
    "slack": {
        "authorize_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "default_scopes": "chat:write channels:read",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "default_scopes": "repo read:org",
    },
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "default_scopes": "openid email profile",
    },
    "microsoft365": {
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "default_scopes": "openid email User.Read",
    },
    "hubspot": {
        "authorize_url": "https://app.hubspot.com/oauth/authorize",
        "token_url": "https://api.hubapi.com/oauth/v1/token",
        "default_scopes": "contacts",
    },
    "teams": {
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "default_scopes": "ChannelMessage.Send",
    },
}

# In-memory pending-OAuth states (production: Redis / DB)
_pending_states: dict[str, dict[str, Any]] = {}


class OAuthProviderRegistry:
    """Manages OAuth provider configurations and flow state."""

    @staticmethod
    def supported_providers() -> list[str]:
        """Return list of provider names that support OAuth."""
        return list(_OAUTH_ENDPOINTS.keys())

    @staticmethod
    def is_supported(provider_type: str) -> bool:
        """Check if a provider type supports OAuth."""
        return provider_type in _OAUTH_ENDPOINTS

    @staticmethod
    def build_authorize_url(
        provider_type: str,
        *,
        client_id: str,
        redirect_uri: str,
        scopes: list[str] | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> tuple[str, str, str | None]:
        """Build the OAuth authorization URL for a provider.

        Returns:
            Tuple of (authorization_url, state, code_verifier).
        """
        provider = _OAUTH_ENDPOINTS.get(provider_type)
        if provider is None:
            raise ValueError(f"OAuth not supported for provider: {provider_type}")

        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)

        scope_str = " ".join(scopes) if scopes else provider.get("default_scopes", "")

        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope_str,
            "state": state,
        }
        if extra_params:
            params.update(extra_params)

        authorization_url = f"{provider['authorize_url']}?{urlencode(params)}"

        return authorization_url, state, code_verifier

    @staticmethod
    def store_pending_state(
        state: str,
        *,
        tenant_id: str,
        connector_id: str,
        provider_type: str,
        redirect_uri: str,
        code_verifier: str | None = None,
    ) -> None:
        """Store state for a pending OAuth flow."""
        _pending_states[state] = {
            "tenant_id": tenant_id,
            "connector_id": connector_id,
            "provider_type": provider_type,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }

    @staticmethod
    def pop_pending_state(state: str) -> dict[str, Any] | None:
        """Pop and return the pending state, or None if not found."""
        return _pending_states.pop(state, None)

    @staticmethod
    async def exchange_code_for_tokens(
        provider_type: str,
        code: str,
        *,
        secrets_mgr: SecretsManager,
        tenant_id: str,
        connector_id: str,
        vault_path: str,
    ) -> dict[str, Any]:
        """Exchange auth code for tokens and store in Vault.

        In production this would POST to the token_url.
        Here we simulate token exchange and store via SecretsManager.
        """
        token_data = {
            "access_token": hashlib.sha256(code.encode()).hexdigest(),
            "refresh_token": secrets.token_urlsafe(48),
            "token_type": "Bearer",
            "expires_in": 3600,
            "obtained_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        await secrets_mgr.put_secret(vault_path, token_data, tenant_id)

        logger.info(
            "oauth.tokens_stored",
            extra={
                "tenant_id": tenant_id,
                "connector_id": connector_id,
                "provider_type": provider_type,
                "vault_path": vault_path,
            },
        )

        return {
            "token_type": token_data["token_type"],
            "expires_in": token_data["expires_in"],
            "vault_path": vault_path,
        }
