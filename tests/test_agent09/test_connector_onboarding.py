"""Tests for Agent-09 Connector Onboarding — schemas, OAuth, testers, health, routes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models.connector import (
    AuthMethod,
    ConnectorCategory,
    ConnectorConfig,
    ConnectorInstance,
    ConnectorStatus,
    ConnectorType,
    ConnectionTestResult as ModelTestResult,
    OAuthCredential,
    OAuthFlowStart,
)
from app.services.connector_service import ConnectorService, _connectors
from app.services.connectors.schemas import (
    CONNECTOR_TYPE_REGISTRY,
    ConnectorTypeSchema,
    CredentialField,
    FieldType,
    get_connector_schema,
    get_secret_field_names,
)
from app.services.connectors.oauth import OAuthProviderRegistry, _pending_states
from app.services.connectors.testers import ConnectionTester, ConnectionTestResult
from app.services.connectors.health import HealthChecker, HealthCheckResult, HealthStatus

# ── Constants ───────────────────────────────────────────────────────

TENANT_ID = "tenant-connector-test"
CONNECTOR_ID = str(uuid4())


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_stores() -> None:
    """Reset in-memory stores between tests."""
    _connectors.clear()
    _pending_states.clear()


def _mock_secrets_mgr() -> AsyncMock:
    """Create a mock SecretsManager."""
    mgr = AsyncMock()
    mgr.put_secret = AsyncMock(return_value=MagicMock(path="test", version=1))
    mgr.get_secret = AsyncMock(return_value={"access_token": "tok_123", "token_type": "Bearer"})
    mgr.delete_secret = AsyncMock()
    return mgr


def _admin_user(**overrides: Any) -> MagicMock:
    """Mock AuthenticatedUser with admin role."""
    user = MagicMock()
    user.id = overrides.get("id", str(uuid4()))
    user.email = overrides.get("email", "admin@test.com")
    user.tenant_id = overrides.get("tenant_id", TENANT_ID)
    user.roles = overrides.get("roles", ["admin"])
    user.permissions = overrides.get("permissions", [])
    return user


# ── Connector Type Schema Tests ─────────────────────────────────────


class TestConnectorTypeRegistry:
    """Tests for the connector type catalog and schemas."""

    def test_registry_has_at_least_10_types(self) -> None:
        """Catalog must have >= 10 connector types."""
        assert len(CONNECTOR_TYPE_REGISTRY) >= 10

    def test_registry_has_35_plus_types(self) -> None:
        """Catalog should have 35+ types as specified."""
        assert len(CONNECTOR_TYPE_REGISTRY) >= 35

    def test_all_six_categories_present(self) -> None:
        """All 6 categories should be represented."""
        categories = {s.category for s in CONNECTOR_TYPE_REGISTRY}
        assert "Database" in categories
        assert "SaaS" in categories
        assert "Communication" in categories
        assert "Cloud" in categories
        assert "AI" in categories
        assert "Custom" in categories

    def test_postgresql_schema_has_correct_fields(self) -> None:
        """PostgreSQL schema must have host, port, database, username, password, ssl fields."""
        schema = get_connector_schema("postgresql")
        assert schema is not None
        field_names = [f.name for f in schema.credential_fields]
        assert "host" in field_names
        assert "port" in field_names
        assert "database" in field_names
        assert "username" in field_names
        assert "secret_credential" in field_names
        assert "ssl" in field_names

    def test_salesforce_schema_has_oauth(self) -> None:
        """Salesforce schema must support OAuth."""
        schema = get_connector_schema("salesforce")
        assert schema is not None
        assert schema.supports_oauth is True
        oauth_fields = [f for f in schema.credential_fields if f.field_type == FieldType.OAUTH]
        assert len(oauth_fields) >= 1

    def test_slack_schema_has_oauth(self) -> None:
        """Slack schema must support OAuth."""
        schema = get_connector_schema("slack")
        assert schema is not None
        assert schema.supports_oauth is True

    def test_s3_schema_has_region_bucket_keys(self) -> None:
        """S3 schema must have region, bucket, access_key, secret_key."""
        schema = get_connector_schema("s3")
        assert schema is not None
        field_names = [f.name for f in schema.credential_fields]
        assert "region" in field_names
        assert "bucket" in field_names
        assert "access_key" in field_names
        assert "secret_key" in field_names

    def test_rest_api_schema_has_auth_type(self) -> None:
        """REST API schema must have base_url and auth_type fields."""
        schema = get_connector_schema("rest_api")
        assert schema is not None
        field_names = [f.name for f in schema.credential_fields]
        assert "base_url" in field_names
        assert "auth_type" in field_names

    def test_get_connector_schema_returns_none_for_unknown(self) -> None:
        """Unknown type returns None."""
        assert get_connector_schema("nonexistent") is None

    def test_get_secret_field_names(self) -> None:
        """Secret fields should be marked for PostgreSQL."""
        secrets = get_secret_field_names("postgresql")
        assert "secret_credential" in secrets

    def test_get_secret_field_names_unknown_type(self) -> None:
        """Unknown type returns empty list for secret fields."""
        assert get_secret_field_names("nonexistent") == []

    def test_schema_field_types_are_valid(self) -> None:
        """All field types in schemas should be valid FieldType enum values."""
        for schema in CONNECTOR_TYPE_REGISTRY:
            for field in schema.credential_fields:
                assert field.field_type in FieldType.__members__.values()

    def test_schema_serialization(self) -> None:
        """Schemas must serialize to dict/JSON cleanly."""
        schema = CONNECTOR_TYPE_REGISTRY[0]
        data = schema.model_dump(mode="json")
        assert "name" in data
        assert "credential_fields" in data
        assert isinstance(data["credential_fields"], list)

    def test_database_types_present(self) -> None:
        """Database category must include PostgreSQL, MySQL, MongoDB, Redis, Elasticsearch, Snowflake, BigQuery."""
        db_types = {s.name for s in CONNECTOR_TYPE_REGISTRY if s.category == "Database"}
        for expected in ["postgresql", "mysql", "mongodb", "redis", "elasticsearch", "snowflake", "bigquery"]:
            assert expected in db_types, f"Missing database type: {expected}"

    def test_saas_types_present(self) -> None:
        """SaaS category must include Salesforce, HubSpot, Zendesk, Jira, Confluence, Notion."""
        saas_types = {s.name for s in CONNECTOR_TYPE_REGISTRY if s.category == "SaaS"}
        for expected in ["salesforce", "hubspot", "zendesk", "jira", "confluence", "notion"]:
            assert expected in saas_types, f"Missing SaaS type: {expected}"

    def test_communication_types_present(self) -> None:
        """Communication category must include Slack, Teams, Discord, Email."""
        comm_types = {s.name for s in CONNECTOR_TYPE_REGISTRY if s.category == "Communication"}
        for expected in ["slack", "teams", "discord", "email_smtp"]:
            assert expected in comm_types, f"Missing communication type: {expected}"

    def test_ai_types_present(self) -> None:
        """AI category must include OpenAI, Anthropic, Ollama, HuggingFace."""
        ai_types = {s.name for s in CONNECTOR_TYPE_REGISTRY if s.category == "AI"}
        for expected in ["openai", "anthropic", "ollama", "huggingface"]:
            assert expected in ai_types, f"Missing AI type: {expected}"


# ── OAuth Provider Registry Tests ────────────────────────────────────


class TestOAuthProviderRegistry:
    """Tests for OAuth flow logic."""

    def test_supported_providers(self) -> None:
        """Registry should list supported OAuth providers."""
        providers = OAuthProviderRegistry.supported_providers()
        assert "salesforce" in providers
        assert "slack" in providers
        assert "github" in providers
        assert "google" in providers
        assert "microsoft365" in providers

    def test_is_supported(self) -> None:
        """is_supported returns True for known OAuth providers."""
        assert OAuthProviderRegistry.is_supported("salesforce") is True
        assert OAuthProviderRegistry.is_supported("slack") is True
        assert OAuthProviderRegistry.is_supported("nonexistent") is False

    def test_build_authorize_url_salesforce(self) -> None:
        """Build authorize URL returns valid Salesforce URL."""
        url, state, verifier = OAuthProviderRegistry.build_authorize_url(
            "salesforce",
            client_id="test-client",
            redirect_uri="https://app.example.com/callback",
        )
        assert "login.salesforce.com" in url
        assert "response_type=code" in url
        assert "client_id=test-client" in url
        assert state is not None and len(state) > 10
        assert verifier is not None

    def test_build_authorize_url_slack(self) -> None:
        """Build authorize URL returns valid Slack URL."""
        url, state, _ = OAuthProviderRegistry.build_authorize_url(
            "slack",
            client_id="slack-client",
            redirect_uri="https://app.example.com/callback",
        )
        assert "slack.com" in url
        assert state is not None

    def test_build_authorize_url_unsupported_raises(self) -> None:
        """Unsupported provider raises ValueError."""
        with pytest.raises(ValueError, match="OAuth not supported"):
            OAuthProviderRegistry.build_authorize_url(
                "nonexistent",
                client_id="x",
                redirect_uri="https://example.com",
            )

    def test_store_and_pop_pending_state(self) -> None:
        """store_pending_state + pop_pending_state round-trips correctly."""
        OAuthProviderRegistry.store_pending_state(
            "test-state-123",
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            provider_type="salesforce",
            redirect_uri="https://app.example.com/callback",
            code_verifier="verifier-abc",
        )
        result = OAuthProviderRegistry.pop_pending_state("test-state-123")
        assert result is not None
        assert result["tenant_id"] == TENANT_ID
        assert result["connector_id"] == CONNECTOR_ID
        assert result["provider_type"] == "salesforce"

    def test_pop_pending_state_removes_entry(self) -> None:
        """After pop, the state should not be found again."""
        OAuthProviderRegistry.store_pending_state(
            "once-state",
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            provider_type="slack",
            redirect_uri="https://example.com",
        )
        OAuthProviderRegistry.pop_pending_state("once-state")
        assert OAuthProviderRegistry.pop_pending_state("once-state") is None

    def test_pop_nonexistent_state_returns_none(self) -> None:
        """Popping a nonexistent state returns None."""
        assert OAuthProviderRegistry.pop_pending_state("nonexistent") is None

    @pytest.mark.asyncio
    async def test_exchange_code_for_tokens(self) -> None:
        """Exchange code stores tokens in Vault and returns metadata."""
        mgr = _mock_secrets_mgr()
        result = await OAuthProviderRegistry.exchange_code_for_tokens(
            "salesforce",
            "auth-code-xyz",
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
            vault_path=f"archon/connectors/{CONNECTOR_ID}/oauth_tokens",
        )
        assert result["token_type"] == "Bearer"
        assert "vault_path" in result
        mgr.put_secret.assert_awaited_once()

    def test_build_authorize_url_with_custom_scopes(self) -> None:
        """Custom scopes override default scopes."""
        url, _, _ = OAuthProviderRegistry.build_authorize_url(
            "github",
            client_id="gh-client",
            redirect_uri="https://example.com/cb",
            scopes=["repo", "admin:org"],
        )
        assert "repo+admin%3Aorg" in url or "repo" in url


# ── Connection Tester Tests ──────────────────────────────────────────


class TestConnectionTester:
    """Tests for connection testing logic."""

    @pytest.mark.asyncio
    async def test_postgresql_valid_config(self) -> None:
        """PostgreSQL test passes with valid host + database."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "postgresql",
            {"host": "localhost", "database": "mydb", "port": "5432"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is True
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_postgresql_missing_host(self) -> None:
        """PostgreSQL test fails with missing host."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "postgresql",
            {"database": "mydb"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is False
        assert "host" in result.message.lower()

    @pytest.mark.asyncio
    async def test_s3_valid_config(self) -> None:
        """S3 test passes with bucket and credentials."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "s3",
            {"bucket": "my-bucket", "region": "us-east-1", "access_key": "AKIATEST"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_s3_missing_bucket(self) -> None:
        """S3 test fails without bucket."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "s3",
            {"region": "us-east-1"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is False
        assert "bucket" in result.message.lower()

    @pytest.mark.asyncio
    async def test_rest_api_valid(self) -> None:
        """REST API test passes with base_url."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "rest_api",
            {"base_url": "https://api.example.com"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_rest_api_missing_url(self) -> None:
        """REST API test fails without base_url."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "rest_api",
            {},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_oauth_connector_with_tokens(self) -> None:
        """OAuth connector test passes when tokens in Vault."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "salesforce",
            {},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is True
        assert "oauth" in result.message.lower() or "verified" in result.message.lower()

    @pytest.mark.asyncio
    async def test_oauth_connector_without_tokens(self) -> None:
        """OAuth connector test fails without tokens."""
        mgr = _mock_secrets_mgr()
        from app.secrets.exceptions import SecretNotFoundError
        mgr.get_secret = AsyncMock(side_effect=SecretNotFoundError("not found"))
        result = await ConnectionTester.test(
            "salesforce",
            {},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_generic_type_passes(self) -> None:
        """Unknown connector types fall back to generic validation."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "custom_unknown",
            {"some_config": "value"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_webhook_valid(self) -> None:
        """Webhook test passes with URL."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "webhook",
            {"url": "https://hooks.example.com/test"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_webhook_missing_url(self) -> None:
        """Webhook test fails without URL."""
        mgr = _mock_secrets_mgr()
        result = await ConnectionTester.test(
            "webhook",
            {},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
            connector_id=CONNECTOR_ID,
        )
        assert result.success is False

    def test_result_to_dict(self) -> None:
        """ConnectionTestResult.to_dict produces correct format."""
        result = ConnectionTestResult(
            success=True,
            latency_ms=42.5,
            message="OK",
            details={"key": "val"},
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["latency_ms"] == 42.5
        assert d["message"] == "OK"
        assert "tested_at" in d


# ── Health Checker Tests ─────────────────────────────────────────────


class TestHealthChecker:
    """Tests for health check implementations."""

    @pytest.mark.asyncio
    async def test_healthy_postgresql(self) -> None:
        """PostgreSQL returns healthy when config has host."""
        mgr = _mock_secrets_mgr()
        result = await HealthChecker.check(
            CONNECTOR_ID, "postgresql",
            {"host": "localhost", "database": "mydb"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
        )
        assert result.status == HealthStatus.HEALTHY
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_degraded_postgresql_no_host(self) -> None:
        """PostgreSQL returns degraded without host."""
        mgr = _mock_secrets_mgr()
        result = await HealthChecker.check(
            CONNECTOR_ID, "postgresql",
            {},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
        )
        assert result.status == HealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_healthy_oauth_with_tokens(self) -> None:
        """OAuth connector healthy when tokens exist."""
        mgr = _mock_secrets_mgr()
        result = await HealthChecker.check(
            CONNECTOR_ID, "salesforce",
            {},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
        )
        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_error_oauth_no_tokens(self) -> None:
        """OAuth connector errors when no tokens."""
        mgr = _mock_secrets_mgr()
        from app.secrets.exceptions import SecretNotFoundError
        mgr.get_secret = AsyncMock(side_effect=SecretNotFoundError("missing"))
        result = await HealthChecker.check(
            CONNECTOR_ID, "salesforce",
            {},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
        )
        assert result.status == HealthStatus.ERROR

    @pytest.mark.asyncio
    async def test_healthy_s3(self) -> None:
        """S3 returns healthy with bucket configured."""
        mgr = _mock_secrets_mgr()
        result = await HealthChecker.check(
            CONNECTOR_ID, "s3",
            {"bucket": "my-bucket"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
        )
        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_healthy_rest_api(self) -> None:
        """REST API returns healthy with base_url."""
        mgr = _mock_secrets_mgr()
        result = await HealthChecker.check(
            CONNECTOR_ID, "rest_api",
            {"base_url": "https://api.example.com"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
        )
        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_health_result_has_last_check(self) -> None:
        """Health result includes last_check timestamp."""
        mgr = _mock_secrets_mgr()
        result = await HealthChecker.check(
            CONNECTOR_ID, "openai",
            {"api_key": "sk-test"},
            secrets_mgr=mgr,
            tenant_id=TENANT_ID,
        )
        assert result.last_check is not None
        assert result.connector_id == CONNECTOR_ID

    def test_health_result_serialization(self) -> None:
        """HealthCheckResult serializes to dict correctly."""
        result = HealthCheckResult(
            connector_id="test-id",
            status=HealthStatus.HEALTHY,
            latency_ms=10.5,
            message="All good",
        )
        data = result.model_dump(mode="json")
        assert data["status"] == "healthy"
        assert data["connector_id"] == "test-id"
        assert "last_check" in data


# ── Connector Service Enterprise API Tests ───────────────────────────


class TestConnectorServiceEnterprise:
    """Tests for the enterprise connector service layer."""

    @pytest.mark.asyncio
    async def test_list_available_types(self) -> None:
        """list_available_connector_types returns catalog entries."""
        types = await ConnectorService.list_available_connector_types()
        assert len(types) >= 6
        names = [t.name for t in types]
        assert "salesforce" in names

    @pytest.mark.asyncio
    async def test_register_connector(self) -> None:
        """Register a new connector instance."""
        user = _admin_user()
        config = ConnectorConfig(
            type="postgresql",
            name="My PG",
            auth_method=AuthMethod.BASIC,
        )
        instance = await ConnectorService.register_connector(
            tenant_id=TENANT_ID,
            user=user,
            config=config,
        )
        assert instance.name == "My PG"
        assert instance.type == "postgresql"
        assert instance.tenant_id == TENANT_ID
        assert instance.status == ConnectorStatus.PENDING_AUTH

    @pytest.mark.asyncio
    async def test_list_connectors_tenant_scoped(self) -> None:
        """list_connectors only returns connectors for the given tenant."""
        user = _admin_user()
        config1 = ConnectorConfig(type="s3", name="S3 Prod")
        config2 = ConnectorConfig(type="slack", name="Slack Bot")
        await ConnectorService.register_connector(TENANT_ID, user, config1)
        await ConnectorService.register_connector(TENANT_ID, user, config2)
        await ConnectorService.register_connector("other-tenant", user, ConnectorConfig(type="redis", name="Other"))

        results = await ConnectorService.list_connectors(TENANT_ID)
        assert len(results) == 2
        assert all(r.tenant_id == TENANT_ID for r in results)

    @pytest.mark.asyncio
    async def test_get_connector_not_found(self) -> None:
        """get_connector raises ValueError for nonexistent ID."""
        with pytest.raises(ValueError, match="not found"):
            await ConnectorService.get_connector(TENANT_ID, uuid4())

    @pytest.mark.asyncio
    async def test_get_connector_tenant_mismatch(self) -> None:
        """get_connector raises ValueError for wrong tenant."""
        user = _admin_user()
        config = ConnectorConfig(type="openai", name="AI Key")
        instance = await ConnectorService.register_connector(TENANT_ID, user, config)
        with pytest.raises(ValueError, match="not found"):
            await ConnectorService.get_connector("wrong-tenant", instance.id)

    @pytest.mark.asyncio
    async def test_test_connection(self) -> None:
        """test_connection verifies Vault credentials."""
        user = _admin_user()
        config = ConnectorConfig(type="s3", name="Test S3")
        instance = await ConnectorService.register_connector(TENANT_ID, user, config)
        mgr = _mock_secrets_mgr()
        result = await ConnectorService.test_connection(TENANT_ID, instance.id, mgr)
        assert result.connector_id == instance.id
        assert result.status in ("ok", "error")

    @pytest.mark.asyncio
    async def test_start_oauth_flow(self) -> None:
        """start_oauth_flow returns authorization URL."""
        user = _admin_user()
        config = ConnectorConfig(type="salesforce", name="SF", auth_method=AuthMethod.OAUTH2)
        instance = await ConnectorService.register_connector(TENANT_ID, user, config)
        flow = await ConnectorService.start_oauth_flow(
            TENANT_ID, user, instance.id, "https://app.example.com/callback",
        )
        assert "salesforce.com" in flow.authorization_url
        assert flow.state is not None

    @pytest.mark.asyncio
    async def test_start_oauth_flow_unsupported_type(self) -> None:
        """start_oauth_flow raises ValueError for non-OAuth type."""
        user = _admin_user()
        config = ConnectorConfig(type="postgresql", name="PG", auth_method=AuthMethod.BASIC)
        instance = await ConnectorService.register_connector(TENANT_ID, user, config)
        with pytest.raises(ValueError, match="OAuth not configured"):
            await ConnectorService.start_oauth_flow(
                TENANT_ID, user, instance.id, "https://example.com/cb",
            )

    @pytest.mark.asyncio
    async def test_complete_oauth_flow(self) -> None:
        """complete_oauth_flow stores tokens in Vault."""
        user = _admin_user()
        config = ConnectorConfig(type="salesforce", name="SF OAuth", auth_method=AuthMethod.OAUTH2)
        instance = await ConnectorService.register_connector(TENANT_ID, user, config)
        flow = await ConnectorService.start_oauth_flow(
            TENANT_ID, user, instance.id, "https://example.com/cb",
        )
        mgr = _mock_secrets_mgr()
        cred = await ConnectorService.complete_oauth_flow(
            TENANT_ID, "auth-code-123", flow.state, mgr,
        )
        assert cred.connector_id == instance.id
        assert cred.token_type == "Bearer"
        mgr.put_secret.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_complete_oauth_invalid_state(self) -> None:
        """complete_oauth_flow raises ValueError for invalid state."""
        mgr = _mock_secrets_mgr()
        with pytest.raises(ValueError, match="Invalid"):
            await ConnectorService.complete_oauth_flow(
                TENANT_ID, "code", "bad-state", mgr,
            )

    @pytest.mark.asyncio
    async def test_revoke_connector(self) -> None:
        """revoke_connector removes from store and Vault."""
        user = _admin_user()
        config = ConnectorConfig(type="slack", name="To Delete")
        instance = await ConnectorService.register_connector(TENANT_ID, user, config)
        mgr = _mock_secrets_mgr()
        await ConnectorService.revoke_connector(TENANT_ID, user, instance.id, mgr)
        with pytest.raises(ValueError):
            await ConnectorService.get_connector(TENANT_ID, instance.id)

    @pytest.mark.asyncio
    async def test_refresh_credentials(self) -> None:
        """refresh_credentials updates tokens in Vault."""
        user = _admin_user()
        config = ConnectorConfig(type="github", name="GH Refresh")
        instance = await ConnectorService.register_connector(TENANT_ID, user, config)
        mgr = _mock_secrets_mgr()
        success = await ConnectorService.refresh_credentials(TENANT_ID, instance.id, mgr)
        assert success is True


# ── API Response Envelope Tests ──────────────────────────────────────


class TestAPIEnvelope:
    """Tests to verify API response envelope format."""

    def test_meta_block_has_required_fields(self) -> None:
        """Meta block must have request_id and timestamp."""
        from app.routes.connectors import _meta
        meta = _meta()
        assert "request_id" in meta
        assert "timestamp" in meta
        assert len(meta["request_id"]) > 0

    def test_meta_block_with_pagination(self) -> None:
        """Meta block supports optional pagination."""
        from app.routes.connectors import _meta
        meta = _meta(pagination={"total": 10, "limit": 20, "offset": 0})
        assert meta["pagination"]["total"] == 10

    def test_meta_block_custom_request_id(self) -> None:
        """Meta block accepts custom request_id."""
        from app.routes.connectors import _meta
        meta = _meta(request_id="custom-123")
        assert meta["request_id"] == "custom-123"
