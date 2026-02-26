"""Tests for the 5 routing rules from seed data."""
from __future__ import annotations

import pytest
from app.models.router import RoutingRule


def _build_rule(rule_data: dict) -> RoutingRule:
    """Build a RoutingRule from seed dict."""
    return RoutingRule(**rule_data)


class TestRoutingRuleCount:
    def test_exactly_5_rules(self, azure_routing_rules):
        assert len(azure_routing_rules) == 5


class TestRoutingRuleValidity:
    """All routing rules are valid RoutingRule instances."""

    @pytest.mark.parametrize("idx", range(5))
    def test_rule_instantiates(self, azure_routing_rules, idx):
        rule = _build_rule(azure_routing_rules[idx])
        assert isinstance(rule, RoutingRule)


class TestCostOptimizedDefault:
    def _rule(self, azure_routing_rules):
        return next(r for r in azure_routing_rules if r["name"] == "cost-optimized-default")

    def test_strategy(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["strategy"] == "cost_optimized"

    def test_priority_is_zero(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["priority"] == 0

    def test_empty_conditions(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["conditions"] == {}


class TestCodeGeneration:
    def _rule(self, azure_routing_rules):
        return next(r for r in azure_routing_rules if r["name"] == "code-generation")

    def test_strategy(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["strategy"] == "performance_optimized"

    def test_priority(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["priority"] == 10

    def test_conditions_require_code(self, azure_routing_rules):
        cond = self._rule(azure_routing_rules)["conditions"]
        code_vals = [v for v in cond.values() if v == "code"]
        assert len(code_vals) > 0, "code-generation rule should reference code capability"


class TestReasoningTasks:
    def _rule(self, azure_routing_rules):
        return next(r for r in azure_routing_rules if r["name"] == "reasoning-tasks")

    def test_strategy(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["strategy"] == "performance_optimized"

    def test_priority(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["priority"] == 10

    def test_conditions_require_reasoning(self, azure_routing_rules):
        cond = self._rule(azure_routing_rules)["conditions"]
        reasoning_vals = [v for v in cond.values() if v == "reasoning"]
        assert len(reasoning_vals) > 0, "reasoning-tasks rule should reference reasoning"


class TestEmbeddingPipeline:
    def _rule(self, azure_routing_rules):
        return next(r for r in azure_routing_rules if r["name"] == "embedding-pipeline")

    def test_strategy(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["strategy"] == "cost_optimized"

    def test_priority(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["priority"] == 5

    def test_conditions_require_embedding(self, azure_routing_rules):
        cond = self._rule(azure_routing_rules)["conditions"]
        embedding_vals = [v for v in cond.values() if v == "embedding"]
        assert len(embedding_vals) > 0, "embedding-pipeline rule should reference embedding"


class TestHighVolume:
    def _rule(self, azure_routing_rules):
        return next(r for r in azure_routing_rules if r["name"] == "high-volume")

    def test_strategy(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["strategy"] == "balanced"

    def test_priority(self, azure_routing_rules):
        assert self._rule(azure_routing_rules)["priority"] == 5

    def test_conditions_high_volume(self, azure_routing_rules):
        cond = self._rule(azure_routing_rules)["conditions"]
        assert len(cond) > 0, "high-volume should have conditions"


class TestWeightsAndDefaults:
    """Weights, active flags, and priority ordering."""

    @pytest.mark.parametrize("idx", range(5))
    def test_weights_sum_approximately_one(self, azure_routing_rules, idx):
        r = azure_routing_rules[idx]
        total = r["weight_cost"] + r["weight_latency"] + r["weight_capability"] + r["weight_sensitivity"]
        assert abs(total - 1.0) < 0.01, f"Rule {r['name']} weights sum to {total}"

    @pytest.mark.parametrize("idx", range(5))
    def test_rule_is_active(self, azure_routing_rules, idx):
        assert azure_routing_rules[idx]["is_active"] is True

    def test_priority_ordering(self, azure_routing_rules):
        """code-generation and reasoning > embedding/high-volume > default."""
        by_name = {r["name"]: r for r in azure_routing_rules}
        assert by_name["code-generation"]["priority"] > by_name["embedding-pipeline"]["priority"]
        assert by_name["reasoning-tasks"]["priority"] > by_name["high-volume"]["priority"]
        assert by_name["embedding-pipeline"]["priority"] > by_name["cost-optimized-default"]["priority"]
        assert by_name["high-volume"]["priority"] > by_name["cost-optimized-default"]["priority"]
