"""Tests for Azure provider registration via seed data."""
from __future__ import annotations

import pytest
from app.models.router import ModelProvider


class TestProviderRegistration:
    """Validate the Azure provider definition from seed data."""

    def test_provider_creates_valid_model_provider(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert isinstance(provider, ModelProvider)

    def test_provider_api_type_is_azure_openai(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert provider.api_type == "azure_openai"

    def test_provider_name(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert provider.name == "azure-qrg-sandbox"

    def test_provider_has_26_model_ids(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert len(provider.model_ids) == 26

    def test_provider_data_classification_level(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert provider.data_classification_level == "internal"

    def test_provider_geo_residency(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert provider.geo_residency == "us"

    def test_provider_is_active_default(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert provider.is_active is True

    def test_provider_has_capabilities(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert len(provider.capabilities) > 0
        assert "chat" in provider.capabilities
        assert "embedding" in provider.capabilities

    def test_provider_cost_non_negative(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert provider.cost_per_1k_tokens >= 0.0

    def test_provider_latency_non_negative(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert provider.avg_latency_ms >= 0.0

    def test_duplicate_provider_data_creates_separate_instance(self, azure_provider_data):
        """Creating two providers from same data yields independent objects."""
        p1 = ModelProvider(**azure_provider_data)
        p2 = ModelProvider(**azure_provider_data)
        assert p1.name == p2.name
        assert p1 is not p2

    def test_provider_model_ids_are_unique(self, azure_provider_data):
        provider = ModelProvider(**azure_provider_data)
        assert len(provider.model_ids) == len(set(provider.model_ids))
