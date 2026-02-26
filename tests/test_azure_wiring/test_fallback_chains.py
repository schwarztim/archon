"""Tests for fallback chains in routing rules."""
from __future__ import annotations

import pytest


class TestFallbackChainStructure:
    """Every routing rule has a valid, non-empty fallback chain."""

    @pytest.mark.parametrize("idx", range(5))
    def test_fallback_chain_non_empty(self, azure_routing_rules, idx):
        chain = azure_routing_rules[idx]["fallback_chain"]
        assert len(chain) > 0, f"Rule {azure_routing_rules[idx]['name']} has empty fallback"

    @pytest.mark.parametrize("idx", range(5))
    def test_fallback_chain_has_at_least_3_entries(self, azure_routing_rules, idx):
        chain = azure_routing_rules[idx]["fallback_chain"]
        assert len(chain) >= 3, (
            f"Rule {azure_routing_rules[idx]['name']} has only {len(chain)} fallback entries"
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_fallback_entries_reference_valid_models(self, azure_routing_rules, all_model_names, idx):
        chain = azure_routing_rules[idx]["fallback_chain"]
        for entry in chain:
            assert entry in all_model_names, (
                f"Fallback '{entry}' in rule '{azure_routing_rules[idx]['name']}' "
                f"not found in registered models"
            )

    @pytest.mark.parametrize("idx", range(5))
    def test_no_duplicate_fallback_entries(self, azure_routing_rules, idx):
        chain = azure_routing_rules[idx]["fallback_chain"]
        assert len(chain) == len(set(chain)), (
            f"Rule {azure_routing_rules[idx]['name']} has duplicate fallback entries"
        )


class TestCostOptimizedDefaultFallback:
    def test_falls_back_through_cheap_models(self, azure_routing_rules, azure_models_data):
        rule = next(r for r in azure_routing_rules if r["name"] == "cost-optimized-default")
        chain = rule["fallback_chain"]
        # First entry should be a mini / cheap model
        assert "mini" in chain[0].lower() or "nano" in chain[0].lower(), (
            f"First fallback should be a cheap model, got {chain[0]}"
        )
        # Verify all entries exist
        model_names = {m["name"] for m in azure_models_data}
        for entry in chain:
            assert entry in model_names


class TestCodeGenerationFallback:
    def test_falls_back_through_codex_models(self, azure_routing_rules, models_by_capability):
        rule = next(r for r in azure_routing_rules if r["name"] == "code-generation")
        chain = rule["fallback_chain"]
        code_model_names = {m["name"] for m in models_by_capability.get("code", [])}
        # At least some entries should be code-capable models
        code_entries = [e for e in chain if e in code_model_names]
        assert len(code_entries) >= 2, "code-generation should fallback through codex models"


class TestReasoningTasksFallback:
    def test_falls_back_through_reasoning_models(self, azure_routing_rules, models_by_capability):
        rule = next(r for r in azure_routing_rules if r["name"] == "reasoning-tasks")
        chain = rule["fallback_chain"]
        reasoning_names = {m["name"] for m in models_by_capability.get("reasoning", [])}
        reasoning_entries = [e for e in chain if e in reasoning_names]
        assert len(reasoning_entries) >= 2, "reasoning-tasks should fallback through reasoning models"


class TestEmbeddingPipelineFallback:
    def test_falls_back_through_embedding_models(self, azure_routing_rules, models_by_capability):
        rule = next(r for r in azure_routing_rules if r["name"] == "embedding-pipeline")
        chain = rule["fallback_chain"]
        embedding_names = {m["name"] for m in models_by_capability.get("embedding", [])}
        embedding_entries = [e for e in chain if e in embedding_names]
        assert len(embedding_entries) >= 2, "embedding-pipeline should fallback through embedding models"


class TestHighVolumeFallback:
    def test_falls_back_through_high_throughput_models(self, azure_routing_rules, azure_models_data):
        rule = next(r for r in azure_routing_rules if r["name"] == "high-volume")
        chain = rule["fallback_chain"]
        # High-volume should prefer fast/cheap models
        model_lookup = {m["name"]: m for m in azure_models_data}
        for entry in chain:
            m = model_lookup[entry]
            assert m["speed_tier"] in ("fast", "medium"), (
                f"high-volume fallback {entry} has unexpected speed_tier {m['speed_tier']}"
            )
