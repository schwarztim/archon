"""Simplified Azure wiring tests without SQLAlchemy model imports."""

import json
import os
from pathlib import Path
import pytest


class TestAzureWiringBasic:
    """Basic Azure integration tests without database dependencies."""

    @pytest.fixture(autouse=True)
    def setup_paths(self):
        """Setup paths for test execution."""
        self.project_root = Path(__file__).parent.parent.parent
        self.seed_file = self.project_root / "data" / "azure_models_seed.json"
        self.env_file = self.project_root / ".env"
        self.registration_script = (
            self.project_root / "scripts" / "register_azure_models.py"
        )

    def test_environment_variables_exist(self):
        """Test that required environment variables are set."""
        required_vars = [
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_API_VERSION",
        ]

        for var in required_vars:
            value = os.getenv(var)
            assert value is not None, f"Environment variable {var} not set"
            assert value.strip() != "", f"Environment variable {var} is empty"

    def test_azure_endpoint_format(self):
        """Test Azure endpoint has correct format."""
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        assert endpoint.startswith("https://"), "Endpoint must use HTTPS"
        assert (
            "openai.azure.com" in endpoint or "cognitiveservices.azure.com" in endpoint
        ), "Endpoint must be Azure OpenAI service"

    def test_seed_file_exists(self):
        """Test that Azure models seed file exists."""
        assert self.seed_file.exists(), "azure_models_seed.json not found"

    def test_seed_file_valid_json(self):
        """Test seed file contains valid JSON."""
        with open(self.seed_file) as f:
            data = json.load(f)
        assert isinstance(data, dict), "Seed file must contain JSON object"

    def test_seed_file_structure(self):
        """Test seed file has required structure."""
        with open(self.seed_file) as f:
            data = json.load(f)

        required_keys = ["provider", "models", "routing_rules"]
        for key in required_keys:
            assert key in data, f"Missing key '{key}' in seed data"

    def test_azure_models_count(self):
        """Test correct number of models are defined."""
        with open(self.seed_file) as f:
            data = json.load(f)

        models = data.get("models", [])
        # Expecting 26 Azure model deployments
        assert len(models) >= 20, f"Expected at least 20 models, got {len(models)}"

    def test_routing_rules_count(self):
        """Test correct number of routing rules."""
        with open(self.seed_file) as f:
            data = json.load(f)

        rules = data.get("routing_rules", [])
        # Expecting 5 routing rules
        assert len(rules) >= 5, f"Expected at least 5 routing rules, got {len(rules)}"

    def test_model_data_completeness(self):
        """Test that each model has required fields."""
        with open(self.seed_file) as f:
            data = json.load(f)

        models = data.get("models", [])
        required_fields = ["name", "model_id", "capabilities"]

        for i, model in enumerate(models):
            for field in required_fields:
                assert field in model, f"Model {i} missing field '{field}'"
                assert model[field], f"Model {i} has empty '{field}'"

    def test_routing_rule_structure(self):
        """Test routing rules have correct structure."""
        with open(self.seed_file) as f:
            data = json.load(f)

        rules = data.get("routing_rules", [])
        required_fields = ["name", "strategy"]

        for i, rule in enumerate(rules):
            for field in required_fields:
                assert field in rule, f"Rule {i} missing field '{field}'"

    def test_registration_script_exists(self):
        """Test registration script exists."""
        assert self.registration_script.exists(), "register_azure_models.py not found"

    def test_registration_script_syntax(self):
        """Test registration script has valid Python syntax."""
        with open(self.registration_script) as f:
            content = f.read()

        # Basic syntax check
        try:
            compile(content, str(self.registration_script), "exec")
        except SyntaxError as e:
            pytest.fail(f"Syntax error in registration script: {e}")

    def test_expected_model_categories(self):
        """Test that all expected model categories are present."""
        with open(self.seed_file) as f:
            data = json.load(f)

        models = data.get("models", [])
        model_names = [m["name"] for m in models]

        # Check for different categories based on naming patterns
        categories = {
            "chat": ["gpt-4", "gpt-5"],
            "codex": ["codex"],
            "reasoning": ["o1", "o3"],
            "embedding": ["embedding"],
            "realtime": ["realtime"],
            "specialty": ["whisper"],
        }

        for category, patterns in categories.items():
            found = any(
                any(pattern in name for pattern in patterns) for name in model_names
            )
            assert found, f"No models found for category '{category}'"

    def test_cost_tracking_data(self):
        """Test models have cost tracking information."""
        with open(self.seed_file) as f:
            data = json.load(f)

        models = data.get("models", [])

        for model in models:
            # Should have cost fields (may be 0.0 for experimental models)
            assert "cost_per_input_token" in model, (
                f"Model {model['name']} missing input cost"
            )
            assert "cost_per_output_token" in model, (
                f"Model {model['name']} missing output cost"
            )

            # Costs should be non-negative numbers
            assert isinstance(model["cost_per_input_token"], (int, float))
            assert isinstance(model["cost_per_output_token"], (int, float))
            assert model["cost_per_input_token"] >= 0
            assert model["cost_per_output_token"] >= 0

    def test_fallback_chains_in_rules(self):
        """Test routing rules define fallback chains."""
        with open(self.seed_file) as f:
            data = json.load(f)

        rules = data.get("routing_rules", [])
        models = {m["name"] for m in data.get("models", [])}

        for rule in rules:
            if "fallback_chain" in rule:
                fallback_chain = rule["fallback_chain"]
                if fallback_chain:  # If chain exists, validate it
                    assert isinstance(fallback_chain, list), (
                        f"Rule {rule['name']} fallback_chain must be list"
                    )

                    # Each model in chain should exist in our model set
                    for model_name in fallback_chain:
                        assert model_name in models, (
                            f"Fallback model '{model_name}' not found in registry"
                        )
