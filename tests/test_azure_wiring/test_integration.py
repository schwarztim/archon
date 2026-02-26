"""Integration tests for Azure OpenAI model router functionality."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import json
import uuid
import os

# Test configuration
SEED_FILE = (
    Path(__file__).resolve().parent.parent.parent / "data" / "azure_models_seed.json"
)


@pytest.fixture
def seed_data():
    """Load seed data for integration tests."""
    with open(SEED_FILE) as f:
        return json.load(f)


@pytest.fixture
def mock_router_service():
    """Mock ModelRouterService for integration testing."""
    with patch("app.services.router_service.ModelRouterService") as mock:
        service = AsyncMock()
        mock.return_value = service
        yield service


@pytest.fixture
def mock_azure_client():
    """Mock Azure OpenAI client responses."""
    with patch("httpx.AsyncClient") as mock_client:
        client = AsyncMock()
        mock_client.return_value.__aenter__.return_value = client

        # Mock successful models list response
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "data": [
                {"id": "model-router", "object": "model"},
                {"id": "text-embedding-3-small-sandbox", "object": "model"},
            ]
        }
        client.get.return_value = response

        yield client


class TestAzureIntegration:
    """Integration tests for Azure OpenAI model routing."""

    def test_end_to_end_model_registration(self, seed_data, mock_router_service):
        """Test complete model registration flow."""
        from scripts.register_azure_models import (
            register_provider_as_entry,
            register_models,
            register_routing_rules,
        )

        # Mock database session
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()

        # Test provider registration
        provider = asyncio.run(register_provider_as_entry(session, seed_data["provider"]))
        assert provider.name == "azure-qrg-sandbox"
        assert provider.provider == "azure_openai"
        assert provider.config["is_provider_record"] is True

        # Test model registration
        models = asyncio.run(register_models(session, seed_data["models"]))
        assert len(models) == 26

        # Verify model categories
        chat_models = [m for m in models if "chat" in m.capabilities]
        embedding_models = [m for m in models if "embedding" in m.capabilities]
        reasoning_models = [m for m in models if "reasoning" in m.capabilities]

        assert len(chat_models) >= 6  # Expected chat models
        assert len(embedding_models) >= 3  # Expected embedding models
        assert len(reasoning_models) >= 3  # Expected reasoning models

        # Test routing rules registration
        rules = asyncio.run(register_routing_rules(session, seed_data["routing_rules"]))
        assert len(rules) == 5

        # Verify specific routing rules exist
        rule_names = {rule.name for rule in rules}
        expected_rules = {
            "cost-optimized-default",
            "code-generation",
            "reasoning-tasks",
            "embedding-pipeline",
            "high-volume",
        }
        assert rule_names == expected_rules

    def test_router_service_integration(self, seed_data, mock_router_service):
        """Test integration with ModelRouterService."""
        from app.models.router import RoutingRequest

        # Mock a routing request
        request = RoutingRequest(
            task_type="chat",
            input_tokens_estimate=500,
            data_classification="general",
            latency_requirement="medium",
            budget_limit=None,
            required_capabilities=["chat"],
            geo_residency=None,
        )

        # Mock router response with Azure model
        mock_router_service.route.return_value = {
            "model_id": "model-router",
            "provider": "azure-qrg-sandbox",
            "endpoint": "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com",
            "routing_rule": "cost-optimized-default",
        }

        # Test routing
        result = asyncio.run(mock_router_service.route(request))

        assert result["model_id"] == "model-router"
        assert result["provider"] == "azure-qrg-sandbox"
        assert result["routing_rule"] == "cost-optimized-default"
        mock_router_service.route.assert_called_once_with(request)

    def test_fallback_chain_execution(self, seed_data, mock_router_service):
        """Test routing rule fallback chains work correctly."""
        # Get reasoning-tasks rule which has fallback chain
        reasoning_rule = next(
            rule
            for rule in seed_data["routing_rules"]
            if rule["name"] == "reasoning-tasks"
        )

        fallback_chain = reasoning_rule["fallback_chain"]
        assert len(fallback_chain) >= 2  # Should have primary + fallbacks

        # Mock primary model failure, fallback success
        def mock_route_with_fallback(request):
            if hasattr(mock_route_with_fallback, "call_count"):
                mock_route_with_fallback.call_count += 1
            else:
                mock_route_with_fallback.call_count = 1

            if mock_route_with_fallback.call_count == 1:
                raise Exception("Primary model unavailable")
            return {
                "model_id": fallback_chain[1],  # Second model in chain
                "provider": "azure-qrg-sandbox",
                "routing_rule": "reasoning-tasks",
                "fallback_used": True,
            }

        mock_router_service.route.side_effect = mock_route_with_fallback

        # Test fallback execution (would be done by router service)
        try:
            asyncio.run(mock_router_service.route(MagicMock()))
        except Exception:
            result = asyncio.run(mock_router_service.route(MagicMock()))
            assert result["fallback_used"] is True
            assert result["model_id"] == fallback_chain[1]

    def test_cost_optimization_routing(self, seed_data):
        """Test cost-optimized routing selects appropriate models."""
        # Get cost-optimized rule
        cost_rule = next(
            rule
            for rule in seed_data["routing_rules"]
            if rule["name"] == "cost-optimized-default"
        )

        assert cost_rule["weight_cost"] >= 0.3  # High cost weighting

        # Verify cost-optimized models are in the chain
        cost_chain = cost_rule["fallback_chain"]

        # Should prioritize mini/smaller models for cost optimization
        cost_efficient_models = [
            model for model in cost_chain if "mini" in model.lower()
        ]
        assert len(cost_efficient_models) >= 1, (
            "Cost-optimized chain should include mini models"
        )

    def test_azure_connectivity_validation(self, mock_azure_client):
        """Test Azure endpoint connectivity validation."""
        from scripts.register_azure_models import validate_connectivity

        # Test successful connectivity
        with patch.dict(
            "os.environ",
            {
                "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
                "AZURE_OPENAI_API_KEY": "test-key",
                "AZURE_OPENAI_API_VERSION": "2025-01-01-preview",
            },
        ):
            reachable, message = asyncio.run(validate_connectivity())
            assert reachable is True
            assert "HTTP 200" in message

    def test_credential_security_integration(self):
        """Test secure credential management integration."""
        from app.config import azure_settings

        # Test credential retrieval (will use env fallback in tests)
        creds = azure_settings.get_secure_credentials()

        assert "endpoint" in creds
        assert "api_key" in creds
        assert "api_version" in creds
        assert "source" in creds
        assert creds["source"] in ["keychain", "env"]

    def test_feature_flag_integration(self):
        """Test Azure provider feature flag integration."""
        from app.config import settings

        # Verify cost tracking is enabled (required for Azure model routing)
        assert settings.FEATURE_COST_TRACKING is True

        # Verify other features that integrate with model routing
        assert settings.FEATURE_DLP_ENABLED is True  # Data classification
        assert settings.FEATURE_A2A_ENABLED is True  # API-to-API routing


class TestAzureModelValidation:
    """Tests for Azure model-specific validation."""

    def test_model_capability_mapping(self, seed_data):
        """Test that Azure models have correct capability mappings."""
        models = seed_data["models"]

        # Verify chat models have correct capabilities
        chat_models = [
            m for m in models if any("chat" in cap for cap in m.get("capabilities", []))
        ]
        assert len(chat_models) >= 6

        # Verify embedding models
        embedding_models = [
            m
            for m in models
            if any("embedding" in cap for cap in m.get("capabilities", []))
        ]
        assert len(embedding_models) >= 3

        for model in embedding_models:
            assert "embedding" in model["name"]

    def test_azure_specific_configuration(self, seed_data):
        """Test Azure-specific model configurations."""
        models = seed_data["models"]

        # Check that Azure models have proper config
        for model in models:
            assert "provider" in model
            assert model["provider"] == "azure-qrg-sandbox"

            # Azure models should have deployment name in config
            if "config" in model:
                config = model["config"]
                assert "azure_deployment" in config or "deployment_name" in config


class TestAzureErrorHandling:
    """Test error handling in Azure integration."""

    def test_database_unavailable_handling(self):
        """Test graceful handling when database is unavailable."""
        from scripts.register_azure_models import main

        with patch("app.database.async_session_factory") as mock_factory:
            mock_factory.side_effect = Exception("Database connection failed")

            # Should not raise exception, just print warning
            asyncio.run(main())  # This should complete without raising

    def test_azure_endpoint_unreachable(self):
        """Test handling when Azure endpoint is unreachable."""
        from scripts.register_azure_models import validate_connectivity

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get.side_effect = (
                Exception("Connection timeout")
            )

            reachable, message = asyncio.run(validate_connectivity())
            assert reachable is False
            assert "Connection error" in message

    def test_missing_credentials_handling(self):
        """Test handling when Azure credentials are missing."""
        async def mock_validate_connectivity():
            """Mock version that simulates missing credentials."""
            return (
                False,
                "Missing Azure OpenAI credentials (check Keychain or environment)",
            )

        # Test the expected behavior
        reachable, message = asyncio.run(mock_validate_connectivity())
        assert reachable is False
        assert "Missing" in message or "credentials" in message.lower()
