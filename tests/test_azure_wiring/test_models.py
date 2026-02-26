"""End-to-end Azure model routing selection tests."""
from __future__ import annotations

import pytest


EXPECTED_MODEL_NAMES = {
    "model-router",
    "modelrouter",
    "gpt-5.2",
    "gpt-5.2-chat",
    "gpt-5-mini",
    "gpt-5-chat",
    "qrg-gpt-4.1",
    "qrg-gpt-4.1-mini",
    "gpt-4",
    "gpt-4o-mini",
    "gpt-5.2-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
    "o1-experiment",
    "qrg-o3-mini",
    "o1-mini",
    "text-embedding-3-small-sandbox",
    "text-embeddings-3-large-sandbox",
    "qrg-embedding-experimental",
    "gpt-realtime",
    "gpt-4o-mini-realtime-preview",
    "whisper-sandbox",
    "qrg-gpt35turbo16k-experimental",
    "qrg-gpt35turbo4k-experimental",
    "qrq-gpt4turbo-experimental",
    "qrg-gpt4o-experimental",
}


def _rule(azure_routing_rules: list[dict], name: str) -> dict:
    return next(rule for rule in azure_routing_rules if rule["name"] == name)


class TestAzureModelRegistry:
    """Validate the 26 Azure model registrations."""

    def test_all_26_models_present(self, azure_models_data):
        assert len(azure_models_data) == 26

    def test_model_names_match_expected(self, azure_models_data):
        names = {model["name"] for model in azure_models_data}
        assert names == EXPECTED_MODEL_NAMES

    @pytest.mark.parametrize("field", ["name", "model_id", "capabilities", "provider"])
    def test_models_have_required_fields(self, azure_models_data, field):
        for model in azure_models_data:
            assert field in model, f"Missing {field} for {model.get('name', 'unknown')}"
            assert model[field], f"Empty {field} for {model.get('name', 'unknown')}"


class TestRoutingSelections:
    """Ensure routing rules select the correct primary model."""

    def test_cost_optimized_default_selects_budget_model(self, azure_routing_rules):
        rule = _rule(azure_routing_rules, "cost-optimized-default")
        assert rule["fallback_chain"][0] in {"gpt-4o-mini", "gpt-5-mini"}

    def test_code_generation_selects_codex(self, azure_routing_rules):
        rule = _rule(azure_routing_rules, "code-generation")
        assert rule["fallback_chain"][0] == "gpt-5.2-codex"

    def test_reasoning_tasks_selects_o1_experiment(self, azure_routing_rules):
        rule = _rule(azure_routing_rules, "reasoning-tasks")
        assert rule["fallback_chain"][0] == "o1-experiment"

    def test_embedding_pipeline_selects_small_embedding(self, azure_routing_rules):
        rule = _rule(azure_routing_rules, "embedding-pipeline")
        assert rule["fallback_chain"][0] == "text-embedding-3-small-sandbox"

    def test_high_volume_selects_gpt5_mini(self, azure_routing_rules):
        rule = _rule(azure_routing_rules, "high-volume")
        assert rule["fallback_chain"][0] == "gpt-5-mini"
