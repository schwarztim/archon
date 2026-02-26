"""Direct Azure OpenAI smoke tests.

These tests call Azure OpenAI APIs directly (not through the backend)
to verify credentials, connectivity, and model availability.
All tests are skipped if AZURE_OPENAI_API_KEY is not set.
"""

import os
import pytest
import httpx

AZURE_ENDPOINT = "https://YOUR_AZURE_ENDPOINT.cognitiveservices.azure.com"
API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")

pytestmark = pytest.mark.skipif(not API_KEY, reason="AZURE_OPENAI_API_KEY not set")


class TestAzureOpenAISmoke:
    """Direct Azure OpenAI API connectivity tests."""

    def test_chat_completion(self):
        """Call the responses API with gpt-5.2-codex model."""
        url = f"{AZURE_ENDPOINT}/openai/responses?api-version=2025-04-01-preview"
        headers = {
            "api-key": API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "model": "gpt-5.2-codex",
            "input": "Say OK",
            "max_output_tokens": 16,
        }

        resp = httpx.post(url, headers=headers, json=payload, timeout=30.0)
        assert resp.status_code == 200, (
            f"Chat API failed: {resp.status_code} {resp.text}"
        )

        data = resp.json()
        # Responses API always returns an "output" array (not "choices")
        assert "output" in data, (
            f"Responses API must return 'output' key: {list(data.keys())}"
        )
        assert isinstance(data["output"], list), (
            f"'output' must be a list, got {type(data['output'])}"
        )
        assert len(data["output"]) > 0, "Responses API returned empty 'output'"

    def test_embeddings(self):
        """Call the embeddings API with qrg-embedding-experimental model."""
        url = f"{AZURE_ENDPOINT}/openai/deployments/qrg-embedding-experimental/embeddings?api-version=2023-05-15"
        headers = {
            "api-key": API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "input": "test embedding text",
            "model": "qrg-embedding-experimental",
        }

        resp = httpx.post(url, headers=headers, json=payload, timeout=30.0)
        assert resp.status_code == 200, (
            f"Embeddings API failed: {resp.status_code} {resp.text}"
        )

        data = resp.json()
        assert "data" in data, f"Missing 'data' key: {list(data.keys())}"
        assert len(data["data"]) > 0, "Empty embeddings response"
        assert "embedding" in data["data"][0], "Missing embedding vector"
        assert len(data["data"][0]["embedding"]) > 0, "Empty embedding vector"

    def test_endpoint_reachable(self):
        """Verify the Azure OpenAI endpoint is reachable."""
        resp = httpx.get(AZURE_ENDPOINT, timeout=10.0, follow_redirects=True)
        # Should get some response (even if 404 for root path)
        assert resp.status_code < 500, f"Endpoint unreachable: {resp.status_code}"

    def test_invalid_model_returns_error(self):
        """Verify that a nonexistent model deployment returns a clear error."""
        url = f"{AZURE_ENDPOINT}/openai/responses?api-version=2025-04-01-preview"
        headers = {
            "api-key": API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "model": "nonexistent-model-xyz",
            "input": "test",
            "max_output_tokens": 5,
        }

        resp = httpx.post(url, headers=headers, json=payload, timeout=10.0)
        # Azure returns 404 for unknown models; 400 if model param is invalid
        assert resp.status_code in (400, 404), (
            f"Expected 400 or 404 for nonexistent model, got {resp.status_code}"
        )
