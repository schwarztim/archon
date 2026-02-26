"""Tests for all 26 Azure model registrations from seed data."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.models.router import ModelRegistryEntry

# Load model names for parametrize at module level
_SEED = Path(__file__).resolve().parent.parent.parent / "data" / "azure_models_seed.json"
with open(_SEED) as _f:
    _DATA = json.load(_f)
_MODEL_NAMES = [m["name"] for m in _DATA["models"]]


def _build_entry(model_data: dict) -> ModelRegistryEntry:
    """Build a ModelRegistryEntry from seed dict, dropping non-schema keys."""
    filtered = {k: v for k, v in model_data.items() if k != "category"}
    return ModelRegistryEntry(**filtered)


# ── Total count ─────────────────────────────────────────────────────


class TestModelCount:
    def test_total_model_count_is_26(self, azure_models_data):
        assert len(azure_models_data) == 26


# ── Per-model parametrized tests ────────────────────────────────────


class TestModelInstantiation:
    """Each model can be instantiated as a valid ModelRegistryEntry."""

    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_model_instantiates(self, azure_models_data, model_name):
        model_data = next(m for m in azure_models_data if m["name"] == model_name)
        entry = _build_entry(model_data)
        assert isinstance(entry, ModelRegistryEntry)

    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_model_provider_is_azure(self, azure_models_data, model_name):
        model_data = next(m for m in azure_models_data if m["name"] == model_name)
        entry = _build_entry(model_data)
        assert entry.provider == "azure-qrg-sandbox"

    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_model_has_azure_config(self, azure_models_data, model_name):
        model_data = next(m for m in azure_models_data if m["name"] == model_name)
        entry = _build_entry(model_data)
        assert "azure_deployment" in entry.config
        assert "azure_api_version" in entry.config

    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_model_context_window_positive(self, azure_models_data, model_name):
        model_data = next(m for m in azure_models_data if m["name"] == model_name)
        entry = _build_entry(model_data)
        assert entry.context_window >= 0

    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_model_speed_tier_valid(self, azure_models_data, model_name):
        model_data = next(m for m in azure_models_data if m["name"] == model_name)
        entry = _build_entry(model_data)
        assert entry.speed_tier in ("fast", "medium", "slow")

    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_model_cost_non_negative(self, azure_models_data, model_name):
        model_data = next(m for m in azure_models_data if m["name"] == model_name)
        entry = _build_entry(model_data)
        assert entry.cost_per_input_token >= 0
        assert entry.cost_per_output_token >= 0


class TestModelUniqueness:
    def test_all_model_names_unique(self, azure_models_data):
        names = [m["name"] for m in azure_models_data]
        assert len(names) == len(set(names))

    def test_all_model_ids_present(self, azure_models_data):
        for m in azure_models_data:
            assert m["model_id"], f"model_id missing for {m['name']}"


# ── Category-specific tests ─────────────────────────────────────────


class TestChatModels:
    def test_chat_model_count(self, models_by_category):
        assert len(models_by_category.get("chat", [])) == 10

    def test_chat_models_have_chat_capability(self, models_by_category):
        for m in models_by_category.get("chat", []):
            assert "chat" in m["capabilities"], f"{m['name']} missing chat capability"

    def test_chat_models_support_streaming(self, models_by_category):
        for m in models_by_category.get("chat", []):
            assert m["supports_streaming"] is True, f"{m['name']} should stream"


class TestCodexModels:
    def test_codex_model_count(self, models_by_category):
        assert len(models_by_category.get("codex", [])) == 3

    def test_codex_models_have_code_capability(self, models_by_category):
        for m in models_by_category.get("codex", []):
            assert "code" in m["capabilities"], f"{m['name']} missing code capability"

    def test_codex_models_support_streaming(self, models_by_category):
        for m in models_by_category.get("codex", []):
            assert m["supports_streaming"] is True


class TestReasoningModels:
    def test_reasoning_model_count(self, models_by_category):
        assert len(models_by_category.get("reasoning", [])) == 3

    def test_reasoning_models_have_reasoning_capability(self, models_by_category):
        for m in models_by_category.get("reasoning", []):
            assert "reasoning" in m["capabilities"], f"{m['name']} missing reasoning"


class TestEmbeddingModels:
    def test_embedding_model_count(self, models_by_category):
        assert len(models_by_category.get("embedding", [])) == 3

    def test_embedding_models_have_embedding_capability(self, models_by_category):
        for m in models_by_category.get("embedding", []):
            assert "embedding" in m["capabilities"], f"{m['name']} missing embedding"

    def test_embedding_models_no_streaming(self, models_by_category):
        for m in models_by_category.get("embedding", []):
            assert m["supports_streaming"] is False, f"{m['name']} should not stream"


class TestSpecialtyModels:
    def test_specialty_model_count(self, models_by_category):
        assert len(models_by_category.get("specialty", [])) == 3

    def test_specialty_models_have_appropriate_capabilities(self, models_by_category):
        specialty_caps = {"realtime", "audio", "transcription"}
        for m in models_by_category.get("specialty", []):
            caps = set(m["capabilities"])
            assert caps & specialty_caps, f"{m['name']} missing specialty cap"


class TestLegacyModels:
    def test_legacy_model_count(self, models_by_category):
        assert len(models_by_category.get("legacy", [])) == 4

    def test_legacy_models_have_chat_capability(self, models_by_category):
        for m in models_by_category.get("legacy", []):
            assert "chat" in m["capabilities"], f"{m['name']} missing chat"
