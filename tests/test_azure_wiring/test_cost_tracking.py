"""Tests for cost tracking fields across all 26 models."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.models.router import ModelRegistryEntry

# Load at module level for parametrize
_SEED = Path(__file__).resolve().parent.parent.parent / "data" / "azure_models_seed.json"
with open(_SEED) as _f:
    _DATA = json.load(_f)
_MODEL_NAMES = [m["name"] for m in _DATA["models"]]


def _build_entry(model_data: dict) -> ModelRegistryEntry:
    filtered = {k: v for k, v in model_data.items() if k != "category"}
    return ModelRegistryEntry(**filtered)


# ── Per-model cost validation ───────────────────────────────────────


class TestCostNonNegative:
    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_input_cost_non_negative(self, azure_models_data, model_name):
        m = next(x for x in azure_models_data if x["name"] == model_name)
        assert m["cost_per_input_token"] >= 0

    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_output_cost_non_negative(self, azure_models_data, model_name):
        m = next(x for x in azure_models_data if x["name"] == model_name)
        assert m["cost_per_output_token"] >= 0


# ── Special model cost rules ───────────────────────────────────────


class TestEmbeddingCosts:
    def test_embedding_models_zero_output_cost(self, models_by_capability):
        for m in models_by_capability.get("embedding", []):
            assert m["cost_per_output_token"] == 0.0, (
                f"Embedding model {m['name']} should have zero output cost"
            )


class TestWhisperCost:
    def test_whisper_zero_output_cost(self, azure_models_data):
        whisper_models = [m for m in azure_models_data if "whisper" in m["name"].lower()]
        assert len(whisper_models) > 0, "No whisper model found"
        for m in whisper_models:
            assert m["cost_per_output_token"] == 0.0, (
                f"Whisper model {m['name']} should have zero output cost"
            )


# ── Cost ordering ───────────────────────────────────────────────────


class TestCostOrdering:
    def test_gpt52_more_expensive_than_gpt5_mini(self, azure_models_data):
        gpt52 = [m for m in azure_models_data if "gpt-5.2" in m["name"] and "codex" not in m["name"] and "mini" not in m["name"]]
        gpt5_mini = [m for m in azure_models_data if "gpt-5-mini" in m["name"]]
        assert len(gpt52) > 0 and len(gpt5_mini) > 0
        max_gpt52_input = max(m["cost_per_input_token"] for m in gpt52)
        min_gpt5_mini_input = min(m["cost_per_input_token"] for m in gpt5_mini)
        assert max_gpt52_input > min_gpt5_mini_input

    def test_legacy_cheaper_than_latest_gen(self, models_by_category):
        legacy = models_by_category.get("legacy", [])
        chat = models_by_category.get("chat", [])
        assert len(legacy) > 0 and len(chat) > 0
        # Compare cheapest legacy input cost vs most expensive latest-gen
        min_legacy = min(m["cost_per_input_token"] for m in legacy)
        max_latest = max(m["cost_per_input_token"] for m in chat)
        # Legacy cheapest should be less than the most expensive chat model
        assert min_legacy < max_latest

    def test_embedding_cheapest_category(self, models_by_category):
        embedding = models_by_category.get("embedding", [])
        chat = models_by_category.get("chat", [])
        assert len(embedding) > 0 and len(chat) > 0
        max_embed_input = max(m["cost_per_input_token"] for m in embedding)
        avg_chat_input = sum(m["cost_per_input_token"] for m in chat) / len(chat)
        assert max_embed_input < avg_chat_input


# ── Cost calculation ────────────────────────────────────────────────


class TestCostCalculation:
    """Estimate cost for a standard prompt: 1K input, 500 output tokens."""

    @pytest.mark.parametrize("model_name", _MODEL_NAMES)
    def test_standard_prompt_cost_calculable(self, azure_models_data, model_name):
        m = next(x for x in azure_models_data if x["name"] == model_name)
        input_tokens = 1000
        output_tokens = 500
        cost = (m["cost_per_input_token"] * input_tokens) + (m["cost_per_output_token"] * output_tokens)
        assert cost >= 0.0, f"Negative cost for {model_name}"
        # Sanity: no single request should cost more than $100 at these token counts
        assert cost < 100.0, f"Unreasonably high cost {cost} for {model_name}"

    def test_all_models_have_calculable_cost(self, azure_models_data):
        """Every model can produce a numeric cost estimate."""
        for m in azure_models_data:
            cost = (m["cost_per_input_token"] * 1000) + (m["cost_per_output_token"] * 500)
            assert isinstance(cost, (int, float)), f"Cost not numeric for {m['name']}"
