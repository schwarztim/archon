"""Tests for Agent 08 — Model Router + Vault Secrets.

Covers: router models, router service (test_connection, health, visual routing,
credential management, fallback chain), and route endpoints.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models.router import (
    CredentialField,
    FallbackChainConfig,
    ModelRegistryEntry,
    PROVIDER_CREDENTIAL_SCHEMAS,
    ProviderCredentialSchema,
    ProviderHealthDetail,
    RoutingCondition,
    RoutingDecision,
    RoutingPolicy,
    RoutingRequest,
    RoutingRule,
    RoutingStats,
    TestConnectionResult,
    VisualRouteDecision,
    VisualRouteRequest,
    VisualRoutingRule,
)

# ── Fixtures ────────────────────────────────────────────────────────

TENANT_ID = "tenant-router-test"


def _make_user(**overrides: Any) -> AuthenticatedUser:
    """Create a test user with admin permissions."""
    defaults = {
        "id": str(uuid4()),
        "email": "admin@test.com",
        "tenant_id": TENANT_ID,
        "roles": ["admin"],
        "permissions": [],
        "mfa_verified": True,
        "session_id": "test-session",
    }
    defaults.update(overrides)
    return AuthenticatedUser(**defaults)


def _make_model_entry(
    *,
    name: str = "gpt-4o",
    provider: str = "openai",
    model_id: str = "gpt-4o",
    tenant_id: str = TENANT_ID,
    entry_id: UUID | None = None,
    vault_path: str | None = None,
) -> ModelRegistryEntry:
    """Create a test model registry entry."""
    return ModelRegistryEntry(
        id=entry_id or uuid4(),
        name=name,
        provider=provider,
        model_id=model_id,
        capabilities=["chat", "code"],
        context_window=128000,
        cost_per_input_token=0.0025,
        cost_per_output_token=0.01,
        speed_tier="fast",
        avg_latency_ms=400.0,
        data_classification="general",
        is_active=True,
        health_status="healthy",
        error_rate=0.01,
        config={"tenant_id": tenant_id, "geo_residency": "us"},
        vault_secret_path=vault_path,
    )


def _make_routing_rule(
    *,
    name: str = "test-rule",
    tenant_id: str = TENANT_ID,
    target_model_id: str = "",
    visual_conditions: list[dict[str, Any]] | None = None,
    priority: int = 10,
    fallback_chain: list[str] | None = None,
) -> RoutingRule:
    """Create a test routing rule."""
    conditions: dict[str, Any] = {"tenant_id": tenant_id}
    if visual_conditions is not None:
        conditions["visual_conditions"] = visual_conditions
        conditions["target_model_id"] = target_model_id
    return RoutingRule(
        id=uuid4(),
        name=name,
        priority=priority,
        is_active=True,
        conditions=conditions,
        fallback_chain=fallback_chain or [],
    )


# ── Model Schema Tests ─────────────────────────────────────────────


class TestRouterModels:
    """Tests for the router Pydantic / SQLModel schemas."""

    def test_routing_condition_creation(self) -> None:
        """RoutingCondition instantiates with field/operator/value."""
        cond = RoutingCondition(field="capability", operator="equals", value="chat")
        assert cond.field == "capability"
        assert cond.operator == "equals"
        assert cond.value == "chat"

    def test_visual_routing_rule_creation(self) -> None:
        """VisualRoutingRule stores structured conditions."""
        rule = VisualRoutingRule(
            id=None,
            name="Test Rule",
            conditions=[
                RoutingCondition(field="capability", operator="equals", value="chat"),
                RoutingCondition(field="sensitivity_level", operator="equals", value="high"),
            ],
            target_model_id="model-123",
            priority=1,
            enabled=True,
        )
        assert len(rule.conditions) == 2
        assert rule.target_model_id == "model-123"
        assert rule.enabled is True

    def test_visual_route_request(self) -> None:
        """VisualRouteRequest stores request context."""
        req = VisualRouteRequest(
            capability="chat",
            sensitivity_level="high",
            max_cost=0.01,
            tenant_tier="premium",
        )
        assert req.capability == "chat"
        assert req.sensitivity_level == "high"
        assert req.max_cost == 0.01

    def test_visual_route_decision(self) -> None:
        """VisualRouteDecision contains model and explanation."""
        decision = VisualRouteDecision(
            model_id="uuid-1",
            model_name="gpt-4o",
            provider_id="uuid-2",
            provider_name="OpenAI",
            reason="Matched rule 'test': capability=chat",
            alternatives=[{"model_name": "claude-3", "reason": "Fallback #1"}],
        )
        assert decision.model_name == "gpt-4o"
        assert len(decision.alternatives) == 1

    def test_fallback_chain_config(self) -> None:
        """FallbackChainConfig stores ordered model IDs."""
        chain = FallbackChainConfig(model_ids=["m1", "m2", "m3"])
        assert len(chain.model_ids) == 3
        assert chain.model_ids[0] == "m1"

    def test_test_connection_result_success(self) -> None:
        """TestConnectionResult success case."""
        result = TestConnectionResult(
            success=True,
            latency_ms=234.5,
            models_found=15,
            message="Connected successfully.",
        )
        assert result.success is True
        assert result.models_found == 15
        assert result.error is None

    def test_test_connection_result_failure(self) -> None:
        """TestConnectionResult failure case."""
        result = TestConnectionResult(
            success=False,
            error="Authentication failed",
            message="Invalid API key.",
        )
        assert result.success is False
        assert result.error == "Authentication failed"

    def test_provider_health_detail(self) -> None:
        """ProviderHealthDetail includes metrics and circuit breaker."""
        health = ProviderHealthDetail(
            provider_id="p1",
            provider_name="OpenAI",
            status="healthy",
            metrics={
                "avg_latency_ms": 450,
                "p95_latency_ms": 1200,
                "p99_latency_ms": 2500,
                "error_rate_percent": 0.5,
            },
            circuit_breaker={
                "state": "closed",
                "failure_count": 2,
                "threshold": 10,
            },
        )
        assert health.status == "healthy"
        assert health.metrics["avg_latency_ms"] == 450
        assert health.circuit_breaker["state"] == "closed"

    def test_credential_field(self) -> None:
        """CredentialField schema definition."""
        field = CredentialField(
            name="api_key",
            label="API Key",
            field_type="password",
            required=True,
            placeholder="sk-...",
        )
        assert field.name == "api_key"
        assert field.field_type == "password"
        assert field.required is True

    def test_model_registry_entry_vault_path(self) -> None:
        """ModelRegistryEntry stores vault_secret_path."""
        entry = _make_model_entry(vault_path="archon/tenants/t1/providers/p1/credentials")
        assert entry.vault_secret_path == "archon/tenants/t1/providers/p1/credentials"


class TestCredentialSchemaRegistry:
    """Tests for the provider credential schema registry."""

    def test_all_expected_providers_have_schemas(self) -> None:
        """All provider types have credential schemas."""
        expected = {"openai", "anthropic", "azure_openai", "ollama", "huggingface", "google", "aws_bedrock", "custom"}
        assert expected.issubset(set(PROVIDER_CREDENTIAL_SCHEMAS.keys()))

    def test_openai_schema_has_api_key(self) -> None:
        """OpenAI schema requires just an API key."""
        schema = PROVIDER_CREDENTIAL_SCHEMAS["openai"]
        assert schema.label == "OpenAI"
        assert len(schema.fields) == 1
        assert schema.fields[0].name == "api_key"

    def test_azure_schema_has_multiple_fields(self) -> None:
        """Azure OpenAI schema has key, endpoint, deployment, version."""
        schema = PROVIDER_CREDENTIAL_SCHEMAS["azure_openai"]
        field_names = {f.name for f in schema.fields}
        assert "api_key" in field_names
        assert "endpoint_url" in field_names
        assert "deployment_name" in field_names
        assert "api_version" in field_names

    def test_ollama_schema_no_key(self) -> None:
        """Ollama schema has base_url but no API key."""
        schema = PROVIDER_CREDENTIAL_SCHEMAS["ollama"]
        field_names = {f.name for f in schema.fields}
        assert "base_url" in field_names
        assert "api_key" not in field_names

    def test_aws_bedrock_schema(self) -> None:
        """AWS Bedrock requires access key, secret key, region."""
        schema = PROVIDER_CREDENTIAL_SCHEMAS["aws_bedrock"]
        field_names = {f.name for f in schema.fields}
        assert "access_key_id" in field_names
        assert "secret_access_key" in field_names
        assert "region" in field_names

    def test_huggingface_schema(self) -> None:
        """HuggingFace has api_token and optional endpoint."""
        schema = PROVIDER_CREDENTIAL_SCHEMAS["huggingface"]
        field_names = {f.name for f in schema.fields}
        assert "api_token" in field_names
        assert "endpoint_url" in field_names

    def test_google_schema(self) -> None:
        """Google AI has api_key and optional project_id."""
        schema = PROVIDER_CREDENTIAL_SCHEMAS["google"]
        field_names = {f.name for f in schema.fields}
        assert "api_key" in field_names
        assert "project_id" in field_names

    def test_custom_schema(self) -> None:
        """Custom provider has optional api_key and base_url."""
        schema = PROVIDER_CREDENTIAL_SCHEMAS["custom"]
        field_names = {f.name for f in schema.fields}
        assert "api_key" in field_names
        assert "base_url" in field_names

    def test_all_schemas_serializable(self) -> None:
        """All credential schemas can be serialized to dict."""
        for key, schema in PROVIDER_CREDENTIAL_SCHEMAS.items():
            data = schema.model_dump(mode="json")
            assert data["provider_type"] == key
            assert isinstance(data["fields"], list)


# ── Visual Rule Matching Tests ──────────────────────────────────────


class TestVisualRuleMatching:
    """Tests for visual rule condition evaluation."""

    def test_match_equals(self) -> None:
        """equals operator matches exact string."""
        from app.services.router_service import _eval_operator
        assert _eval_operator("chat", "equals", "chat") is True
        assert _eval_operator("code", "equals", "chat") is False

    def test_match_not_equals(self) -> None:
        """not_equals operator rejects matching string."""
        from app.services.router_service import _eval_operator
        assert _eval_operator("code", "not_equals", "chat") is True
        assert _eval_operator("chat", "not_equals", "chat") is False

    def test_match_contains(self) -> None:
        """contains operator checks substring."""
        from app.services.router_service import _eval_operator
        assert _eval_operator("function_calling", "contains", "function") is True
        assert _eval_operator("chat", "contains", "function") is False

    def test_match_greater_than(self) -> None:
        """greater_than operator compares numerics."""
        from app.services.router_service import _eval_operator
        assert _eval_operator(10, "greater_than", 5) is True
        assert _eval_operator(3, "greater_than", 5) is False

    def test_match_less_than(self) -> None:
        """less_than operator compares numerics."""
        from app.services.router_service import _eval_operator
        assert _eval_operator(3, "less_than", 5) is True
        assert _eval_operator(10, "less_than", 5) is False

    def test_match_in(self) -> None:
        """in operator checks membership."""
        from app.services.router_service import _eval_operator
        assert _eval_operator("chat", "in", ["chat", "code"]) is True
        assert _eval_operator("vision", "in", ["chat", "code"]) is False

    def test_match_not_in(self) -> None:
        """not_in operator checks non-membership."""
        from app.services.router_service import _eval_operator
        assert _eval_operator("vision", "not_in", ["chat", "code"]) is True
        assert _eval_operator("chat", "not_in", ["chat", "code"]) is False

    def test_match_invalid_operator(self) -> None:
        """Unknown operator returns False."""
        from app.services.router_service import _eval_operator
        assert _eval_operator("x", "unknown_op", "y") is False

    def test_match_visual_conditions_all_and(self) -> None:
        """All conditions must match (AND logic)."""
        from app.services.router_service import _match_visual_conditions

        conditions = [
            {"field": "capability", "operator": "equals", "value": "chat"},
            {"field": "sensitivity_level", "operator": "equals", "value": "high"},
        ]
        context = {"capability": "chat", "sensitivity_level": "high", "max_cost": 0.01}
        assert _match_visual_conditions(conditions, context) is True

    def test_match_visual_conditions_partial_fail(self) -> None:
        """If one condition fails, entire match fails."""
        from app.services.router_service import _match_visual_conditions

        conditions = [
            {"field": "capability", "operator": "equals", "value": "chat"},
            {"field": "sensitivity_level", "operator": "equals", "value": "high"},
        ]
        context = {"capability": "chat", "sensitivity_level": "low"}
        assert _match_visual_conditions(conditions, context) is False

    def test_match_visual_conditions_missing_field(self) -> None:
        """Missing context field returns False."""
        from app.services.router_service import _match_visual_conditions

        conditions = [{"field": "capability", "operator": "equals", "value": "chat"}]
        context: dict[str, Any] = {}
        assert _match_visual_conditions(conditions, context) is False

    def test_match_visual_conditions_empty(self) -> None:
        """Empty conditions list returns False."""
        from app.services.router_service import _match_visual_conditions
        assert _match_visual_conditions([], {}) is False

    def test_greater_than_non_numeric(self) -> None:
        """greater_than with non-numeric returns False."""
        from app.services.router_service import _eval_operator
        assert _eval_operator("abc", "greater_than", "def") is False

    def test_in_operator_with_csv_string(self) -> None:
        """in operator parses comma-separated string values."""
        from app.services.router_service import _eval_operator
        assert _eval_operator("chat", "in", "chat,code,vision") is True
        assert _eval_operator("embedding", "in", "chat,code,vision") is False


# ── Helper Function Tests ───────────────────────────────────────────


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_find_model_by_id(self) -> None:
        """_find_model_by_id locates model by string UUID."""
        from app.services.router_service import _find_model_by_id

        m1 = _make_model_entry(name="model-1")
        m2 = _make_model_entry(name="model-2")
        result = _find_model_by_id([m1, m2], str(m1.id))
        assert result is not None
        assert result.name == "model-1"

    def test_find_model_by_id_not_found(self) -> None:
        """_find_model_by_id returns None when not found."""
        from app.services.router_service import _find_model_by_id

        m1 = _make_model_entry(name="model-1")
        result = _find_model_by_id([m1], "nonexistent-id")
        assert result is None

    def test_build_alternatives(self) -> None:
        """_build_alternatives builds list excluding selected model."""
        from app.services.router_service import _build_alternatives

        m1 = _make_model_entry(name="primary")
        m2 = _make_model_entry(name="alt-1")
        m3 = _make_model_entry(name="alt-2")
        alts = _build_alternatives([m1, m2, m3], str(m1.id))
        assert len(alts) == 2
        assert alts[0]["model_name"] == "alt-1"
        assert alts[0]["reason"] == "Fallback #1"

    def test_build_alternatives_limits_to_3(self) -> None:
        """_build_alternatives returns at most 3 alternatives."""
        from app.services.router_service import _build_alternatives

        models = [_make_model_entry(name=f"model-{i}") for i in range(6)]
        alts = _build_alternatives(models, str(models[0].id))
        assert len(alts) == 3


# ── Test Connection Provider Tests ──────────────────────────────────


class TestProviderConnectionTest:
    """Tests for the _test_provider_connection helper."""

    @pytest.mark.asyncio
    async def test_openai_with_credentials(self) -> None:
        """OpenAI test with valid credentials returns success."""
        from app.services.router_service import _test_provider_connection

        entry = _make_model_entry(provider="openai")
        result = await _test_provider_connection("openai", {"api_key": "sk-test"}, entry)
        assert result.success is True
        assert result.models_found == 15

    @pytest.mark.asyncio
    async def test_openai_without_credentials(self) -> None:
        """OpenAI test without credentials returns failure."""
        from app.services.router_service import _test_provider_connection

        entry = _make_model_entry(provider="openai")
        result = await _test_provider_connection("openai", {}, entry)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_anthropic_with_credentials(self) -> None:
        """Anthropic test with valid credentials returns success."""
        from app.services.router_service import _test_provider_connection

        entry = _make_model_entry(provider="anthropic")
        result = await _test_provider_connection("anthropic", {"api_key": "sk-ant-test"}, entry)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_unknown_provider(self) -> None:
        """Unknown provider type returns generic success."""
        from app.services.router_service import _test_provider_connection

        entry = _make_model_entry(provider="unknown_type")
        result = await _test_provider_connection("unknown_type", {}, entry)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_aws_bedrock_with_credentials(self) -> None:
        """AWS Bedrock test with access key returns success."""
        from app.services.router_service import _test_provider_connection

        entry = _make_model_entry(provider="aws_bedrock")
        result = await _test_provider_connection(
            "aws_bedrock", {"access_key_id": "AKIA...", "secret_access_key": "secret"}, entry
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_huggingface_with_token(self) -> None:
        """HuggingFace with api_token returns success."""
        from app.services.router_service import _test_provider_connection

        entry = _make_model_entry(provider="huggingface")
        result = await _test_provider_connection("huggingface", {"api_token": "hf_test"}, entry)
        assert result.success is True


# ── Circuit Breaker Tests ───────────────────────────────────────────


class TestCircuitBreaker:
    """Tests for the circuit breaker pattern."""

    def test_initial_state_closed(self) -> None:
        """Circuit breaker starts in closed state."""
        from app.services.router_service import _CircuitBreaker

        cb = _CircuitBreaker()
        assert cb.get_status("provider-1") == "closed"
        assert cb.is_open("provider-1") is False

    def test_opens_after_threshold(self) -> None:
        """Circuit opens after FAILURE_THRESHOLD consecutive failures."""
        from app.services.router_service import _CircuitBreaker

        cb = _CircuitBreaker()
        for _ in range(cb.FAILURE_THRESHOLD):
            cb.record_failure("provider-2")
        assert cb.is_open("provider-2") is True
        assert cb.get_status("provider-2") == "open"

    def test_success_resets(self) -> None:
        """Recording success resets the circuit breaker."""
        from app.services.router_service import _CircuitBreaker

        cb = _CircuitBreaker()
        cb.record_failure("provider-3")
        cb.record_failure("provider-3")
        cb.record_success("provider-3")
        assert cb.get_consecutive_failures("provider-3") == 0
        assert cb.get_status("provider-3") == "closed"

    def test_half_open_after_timeout(self) -> None:
        """Circuit moves to half_open after reset timeout."""
        from app.services.router_service import _CircuitBreaker

        cb = _CircuitBreaker()
        cb.RESET_TIMEOUT_S = 0.01  # Short timeout for testing
        for _ in range(cb.FAILURE_THRESHOLD):
            cb.record_failure("provider-4")
        assert cb.is_open("provider-4") is True
        time.sleep(0.02)
        assert cb.is_open("provider-4") is False
        assert cb.get_status("provider-4") == "half_open"


# ── Service Integration Tests (mocked DB) ──────────────────────────


class TestModelRouterServiceCredentials:
    """Tests for credential management via Vault."""

    @pytest.mark.asyncio
    async def test_save_provider_credentials(self) -> None:
        """Credentials are stored in Vault and vault_path updated in DB."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        entry = _make_model_entry()
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=entry)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        mock_secrets = AsyncMock()
        mock_secrets.put_secret = AsyncMock()

        with patch("app.services.router_service.AuditLogService") as mock_audit:
            mock_audit.create = AsyncMock()
            result = await ModelRouterService.save_provider_credentials(
                mock_session, mock_secrets, TENANT_ID, user, entry.id,
                {"api_key": "sk-test-123"},
            )

        assert result.vault_secret_path is not None
        assert "credentials" in result.vault_secret_path
        mock_secrets.put_secret.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_credentials_wrong_tenant(self) -> None:
        """Saving credentials for wrong tenant raises ValueError."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        entry = _make_model_entry(tenant_id="other-tenant")
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=entry)

        mock_secrets = AsyncMock()

        with pytest.raises(ValueError, match="not accessible"):
            await ModelRouterService.save_provider_credentials(
                mock_session, mock_secrets, TENANT_ID, user, entry.id,
                {"api_key": "sk-test"},
            )

    @pytest.mark.asyncio
    async def test_save_credentials_not_found(self) -> None:
        """Saving credentials for nonexistent provider raises ValueError."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)

        mock_secrets = AsyncMock()

        with pytest.raises(ValueError, match="not found"):
            await ModelRouterService.save_provider_credentials(
                mock_session, mock_secrets, TENANT_ID, user, uuid4(),
                {"api_key": "sk-test"},
            )


class TestModelRouterServiceDelete:
    """Tests for provider deletion with Vault cleanup."""

    @pytest.mark.asyncio
    async def test_delete_provider_cleans_vault(self) -> None:
        """Deleting provider removes Vault credentials."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        entry = _make_model_entry(vault_path="archon/tenants/t1/providers/p1/credentials")
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=entry)
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        mock_secrets = AsyncMock()
        mock_secrets.delete_secret = AsyncMock()

        with patch("app.services.router_service.AuditLogService") as mock_audit:
            mock_audit.create = AsyncMock()
            result = await ModelRouterService.delete_provider(
                mock_session, mock_secrets, TENANT_ID, user, entry.id,
            )

        assert result is True
        mock_secrets.delete_secret.assert_called_once()
        mock_session.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_provider_not_found(self) -> None:
        """Deleting nonexistent provider returns False."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)
        mock_secrets = AsyncMock()

        result = await ModelRouterService.delete_provider(
            mock_session, mock_secrets, TENANT_ID, user, uuid4(),
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_provider_wrong_tenant(self) -> None:
        """Deleting provider from wrong tenant returns False."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        entry = _make_model_entry(tenant_id="other-tenant")
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=entry)
        mock_secrets = AsyncMock()

        result = await ModelRouterService.delete_provider(
            mock_session, mock_secrets, TENANT_ID, user, entry.id,
        )
        assert result is False


class TestModelRouterServiceTestConnection:
    """Tests for the test_connection service method."""

    @pytest.mark.asyncio
    async def test_connection_success(self) -> None:
        """Test connection with valid credentials returns success."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        entry = _make_model_entry(
            provider="openai",
            vault_path="archon/tenants/t1/providers/p1/credentials",
        )
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=entry)
        mock_session.commit = AsyncMock()

        mock_secrets = AsyncMock()
        mock_secrets.get_secret = AsyncMock(return_value={"api_key": "sk-test"})

        with patch("app.services.router_service.AuditLogService") as mock_audit:
            mock_audit.create = AsyncMock()
            result = await ModelRouterService.test_connection(
                mock_session, mock_secrets, TENANT_ID, user, entry.id,
            )

        assert result.success is True
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_connection_not_found(self) -> None:
        """Test connection for nonexistent provider returns failure."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)
        mock_secrets = AsyncMock()

        result = await ModelRouterService.test_connection(
            mock_session, mock_secrets, TENANT_ID, user, uuid4(),
        )
        assert result.success is False

    @pytest.mark.asyncio
    async def test_connection_vault_error(self) -> None:
        """Test connection with Vault error returns failure."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        entry = _make_model_entry(
            vault_path="archon/tenants/t1/providers/p1/credentials",
        )
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=entry)

        mock_secrets = AsyncMock()
        mock_secrets.get_secret = AsyncMock(side_effect=Exception("Vault unavailable"))

        result = await ModelRouterService.test_connection(
            mock_session, mock_secrets, TENANT_ID, user, entry.id,
        )
        assert result.success is False
        assert "Vault" in result.message


class TestModelRouterServiceHealth:
    """Tests for provider health methods."""

    @pytest.mark.asyncio
    async def test_get_provider_health_detail(self) -> None:
        """Health detail returns metrics and circuit breaker info."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        entry = _make_model_entry()
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=entry)

        result = await ModelRouterService.get_provider_health_detail(
            mock_session, TENANT_ID, user, entry.id,
        )

        assert result.provider_id == str(entry.id)
        assert result.status == "healthy"
        assert "avg_latency_ms" in result.metrics
        assert "state" in result.circuit_breaker

    @pytest.mark.asyncio
    async def test_get_provider_health_not_found(self) -> None:
        """Health detail for nonexistent provider raises ValueError."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await ModelRouterService.get_provider_health_detail(
                mock_session, TENANT_ID, user, uuid4(),
            )


class TestModelRouterServiceVisualRouting:
    """Tests for visual rule-based routing."""

    @pytest.mark.asyncio
    async def test_route_visual_no_models(self) -> None:
        """Visual route with no models returns 'none'."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        request = VisualRouteRequest(capability="chat")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.exec = AsyncMock(return_value=mock_result)

        result = await ModelRouterService.route_visual(
            mock_session, TENANT_ID, user, request,
        )

        assert result.model_name == "none"
        assert "No eligible models" in result.reason

    @pytest.mark.asyncio
    async def test_route_visual_default_fallback(self) -> None:
        """Visual route with candidates but no rules uses first candidate."""
        from app.services.router_service import ModelRouterService

        user = _make_user()
        request = VisualRouteRequest(capability="chat")

        model = _make_model_entry(name="fallback-model")

        mock_session = AsyncMock()
        # First call returns models, second returns rules
        mock_result1 = MagicMock()
        mock_result1.all.return_value = [model]
        mock_result2 = MagicMock()
        mock_result2.all.return_value = []

        call_count = 0
        async def mock_exec(stmt: Any) -> Any:
            nonlocal call_count
            call_count += 1
            return mock_result1 if call_count == 1 else mock_result2

        mock_session.exec = mock_exec
        mock_session.commit = AsyncMock()

        result = await ModelRouterService.route_visual(
            mock_session, TENANT_ID, user, request,
        )

        assert result.model_name == "fallback-model"
        assert "default" in result.reason.lower() or "fallback" in result.reason.lower()


# ── Scoring Tests ───────────────────────────────────────────────────


class TestModelScoring:
    """Tests for the multi-factor model scoring."""

    def test_score_model_returns_factors(self) -> None:
        """_score_model returns composite score and factor breakdown."""
        from app.services.router_service import _score_model

        model = _make_model_entry()
        request = RoutingRequest(task_type="chat")
        policy = RoutingPolicy()

        score, factors = _score_model(model, request, policy)

        assert isinstance(score, float)
        assert score > 0
        assert len(factors) == 4
        factor_names = {f.factor for f in factors}
        assert "cost" in factor_names
        assert "latency" in factor_names
        assert "quality" in factor_names
        assert "data_residency" in factor_names

    def test_score_model_degraded_penalty(self) -> None:
        """Degraded health status applies 0.7 multiplier."""
        from app.services.router_service import _score_model

        model = _make_model_entry()
        model.health_status = "degraded"
        request = RoutingRequest(task_type="chat")
        policy = RoutingPolicy()

        score_degraded, _ = _score_model(model, request, policy)

        model.health_status = "healthy"
        score_healthy, _ = _score_model(model, request, policy)

        assert score_degraded < score_healthy

    def test_score_model_with_geo_match(self) -> None:
        """Geo-residency match gives higher data_residency score."""
        from app.services.router_service import _score_model

        model = _make_model_entry()
        policy = RoutingPolicy()

        req_match = RoutingRequest(task_type="chat", geo_residency="us")
        score_match, _ = _score_model(model, req_match, policy)

        req_nomatch = RoutingRequest(task_type="chat", geo_residency="eu")
        score_nomatch, _ = _score_model(model, req_nomatch, policy)

        assert score_match >= score_nomatch
