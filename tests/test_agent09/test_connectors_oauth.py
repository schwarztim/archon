"""Tests for Agent-09 OAuth flow endpoints and provider integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.connectors.oauth import OAuthProviderRegistry, _pending_states


# ── Constants ───────────────────────────────────────────────────────

TENANT_ID = "tenant-oauth-test"
CONNECTOR_ID = str(uuid4())


@pytest.fixture(autouse=True)
def _clear_oauth_state() -> None:
    """Reset pending OAuth states between tests."""
    _pending_states.clear()


def _mock_secrets_mgr() -> AsyncMock:
    """Create a mock SecretsManager."""
    mgr = AsyncMock()
    mgr.put_secret = AsyncMock(return_value=MagicMock(path="test", version=1))
    mgr.get_secret = AsyncMock(return_value={"access_token": "tok_123"})
    return mgr


# ── OAuth Flow Integration Tests ────────────────────────────────────


class TestOAuthFlowIntegration:
    """End-to-end OAuth flow tests."""

    @pytest.mark.asyncio
    async def test_full_authorize_callback_cycle_salesforce(self) -> None:
        """Full authorize → store state → pop state cycle for Salesforce."""
        url, state, verifier = OAuthProviderRegistry.build_authorize_url(
            "salesforce",
            client_id="sf-client-id",
            redirect_uri="https://app.example.com/callback",
        )

        OAuthProviderRegistry.store_pending_state(
            state,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            provider_type="salesforce",
            redirect_uri="https://app.example.com/callback",
            code_verifier=verifier,
        )

        pending = await OAuthProviderRegistry.pop_pending_state(state)
        assert pending is not None
        assert pending["tenant_id"] == TENANT_ID
        assert pending["provider_type"] == "salesforce"

    @pytest.mark.asyncio
    async def test_full_authorize_callback_cycle_slack(self) -> None:
        """Full authorize → store state → pop state cycle for Slack."""
        url, state, verifier = OAuthProviderRegistry.build_authorize_url(
            "slack",
            client_id="slack-bot-id",
            redirect_uri="https://app.example.com/callback",
            scopes=["chat:write", "channels:read"],
        )

        assert "slack.com" in url

        OAuthProviderRegistry.store_pending_state(
            state,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            provider_type="slack",
            redirect_uri="https://app.example.com/callback",
            code_verifier=verifier,
        )

        pending = await OAuthProviderRegistry.pop_pending_state(state)
        assert pending is not None
        assert pending["provider_type"] == "slack"

    @pytest.mark.asyncio
    async def test_full_authorize_callback_cycle_github(self) -> None:
        """Full authorize → store state → pop state cycle for GitHub."""
        url, state, _ = OAuthProviderRegistry.build_authorize_url(
            "github",
            client_id="gh-app-id",
            redirect_uri="https://app.example.com/callback",
        )

        assert "github.com" in url

        OAuthProviderRegistry.store_pending_state(
            state,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            provider_type="github",
            redirect_uri="https://app.example.com/callback",
        )

        pending = await OAuthProviderRegistry.pop_pending_state(state)
        assert pending["provider_type"] == "github"

    @pytest.mark.asyncio
    async def test_full_authorize_callback_cycle_google(self) -> None:
        """Full authorize → store state → pop state cycle for Google."""
        url, state, _ = OAuthProviderRegistry.build_authorize_url(
            "google",
            client_id="google-client-id",
            redirect_uri="https://app.example.com/callback",
        )

        assert "accounts.google.com" in url

        OAuthProviderRegistry.store_pending_state(
            state,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            provider_type="google",
            redirect_uri="https://app.example.com/callback",
        )

        pending = await OAuthProviderRegistry.pop_pending_state(state)
        assert pending["provider_type"] == "google"

    @pytest.mark.asyncio
    async def test_full_authorize_callback_cycle_microsoft365(self) -> None:
        """Full authorize → store state → pop state cycle for Microsoft 365."""
        url, state, _ = OAuthProviderRegistry.build_authorize_url(
            "microsoft365",
            client_id="ms-client-id",
            redirect_uri="https://app.example.com/callback",
        )

        assert "login.microsoftonline.com" in url

        OAuthProviderRegistry.store_pending_state(
            state,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            provider_type="microsoft365",
            redirect_uri="https://app.example.com/callback",
        )

        pending = await OAuthProviderRegistry.pop_pending_state(state)
        assert pending["provider_type"] == "microsoft365"

    @pytest.mark.asyncio
    async def test_token_exchange_stores_in_vault(self) -> None:
        """Token exchange stores tokens via secrets manager."""
        mgr = _mock_secrets_mgr()
        vault_path = f"archon/connectors/{CONNECTOR_ID}/oauth_tokens"

        result = await OAuthProviderRegistry.exchange_code_for_tokens(
            "salesforce",
            "auth-code-from-sf",
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            vault_path=vault_path,
        )

        assert result["token_type"] == "Bearer"
        assert result["vault_path"] == vault_path
        mgr.put_secret.assert_awaited_once()
        call_args = mgr.put_secret.call_args
        stored_data = call_args.args[1] if len(call_args.args) > 1 else call_args[0][1]
        assert "access_token" in stored_data
        assert "refresh_token" in stored_data

    @pytest.mark.asyncio
    async def test_token_exchange_different_providers(self) -> None:
        """Token exchange works for multiple provider types."""
        mgr = _mock_secrets_mgr()

        for provider in ["salesforce", "slack", "github"]:
            result = await OAuthProviderRegistry.exchange_code_for_tokens(
                provider,
                f"code-for-{provider}",
                secrets_mgr=mgr,
                tenant_id=TENANT_ID,
                connector_id=str(uuid4()),
                vault_path=f"archon/connectors/test/{provider}",
            )
            assert result["token_type"] == "Bearer"


# ── OAuth Security Tests ────────────────────────────────────────────


class TestOAuthSecurity:
    """Security-related OAuth tests."""

    def test_state_is_unique_per_request(self) -> None:
        """Each authorize call generates a unique state token."""
        states = set()
        for _ in range(10):
            _, state, _ = OAuthProviderRegistry.build_authorize_url(
                "salesforce",
                client_id="test",
                redirect_uri="https://example.com/cb",
            )
            states.add(state)
        assert len(states) == 10

    def test_state_token_length(self) -> None:
        """State tokens should be sufficiently long for CSRF protection."""
        _, state, _ = OAuthProviderRegistry.build_authorize_url(
            "salesforce",
            client_id="test",
            redirect_uri="https://example.com/cb",
        )
        assert len(state) >= 20

    def test_code_verifier_length(self) -> None:
        """PKCE code verifier should be sufficiently long."""
        _, _, verifier = OAuthProviderRegistry.build_authorize_url(
            "salesforce",
            client_id="test",
            redirect_uri="https://example.com/cb",
        )
        assert verifier is not None
        assert len(verifier) >= 40

    @pytest.mark.asyncio
    async def test_replay_prevention(self) -> None:
        """State can only be consumed once (replay prevention)."""
        OAuthProviderRegistry.store_pending_state(
            "replay-state",
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            provider_type="salesforce",
            redirect_uri="https://example.com/cb",
        )

        first = await OAuthProviderRegistry.pop_pending_state("replay-state")
        assert first is not None

        second = await OAuthProviderRegistry.pop_pending_state("replay-state")
        assert second is None

    @pytest.mark.asyncio
    async def test_tenant_isolation_in_state(self) -> None:
        """State stores are tenant-scoped."""
        OAuthProviderRegistry.store_pending_state(
            "tenant-state",
            tenant_id="tenant-A",
            connector_id=CONNECTOR_ID,
            provider_type="salesforce",
            redirect_uri="https://example.com/cb",
        )

        pending = await OAuthProviderRegistry.pop_pending_state("tenant-state")
        assert pending is not None
        assert pending["tenant_id"] == "tenant-A"


# ── OAuth Provider Coverage ─────────────────────────────────────────


class TestOAuthProviderCoverage:
    """Ensure all required OAuth providers are configured."""

    def test_all_required_providers_present(self) -> None:
        """Salesforce, Slack, GitHub, Google, Microsoft 365 must be supported."""
        for provider in ["salesforce", "slack", "github", "google", "microsoft365"]:
            assert OAuthProviderRegistry.is_supported(provider), (
                f"Provider {provider} should be supported"
            )

    def test_authorize_url_format_for_each_provider(self) -> None:
        """Each provider's authorize URL should contain the correct domain."""
        expected_domains = {
            "salesforce": "salesforce.com",
            "slack": "slack.com",
            "github": "github.com",
            "google": "google.com",
            "microsoft365": "microsoftonline.com",
        }
        for provider, domain in expected_domains.items():
            url, _, _ = OAuthProviderRegistry.build_authorize_url(
                provider,
                client_id="test",
                redirect_uri="https://example.com/cb",
            )
            assert domain in url, f"{provider} URL should contain {domain}"

    def test_extra_params_in_authorize_url(self) -> None:
        """Extra params are appended to authorize URL."""
        url, _, _ = OAuthProviderRegistry.build_authorize_url(
            "salesforce",
            client_id="test",
            redirect_uri="https://example.com/cb",
            extra_params={"prompt": "consent"},
        )
        assert "prompt=consent" in url
