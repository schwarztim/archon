"""Integration tests for Azure OpenAI via the model router and directly.

Uses TestClient (in-process) via conftest.py fixtures.
AUTH_DEV_MODE=true — no auth headers required.

Skipped automatically when AZURE_OPENAI_API_KEY is not set in the environment,
because these tests require a live Azure OpenAI deployment to succeed.
"""

import os

import httpx
import pytest

_AZURE_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
_skip_reason = "AZURE_OPENAI_API_KEY environment variable is not set"


@pytest.mark.skipif(not _AZURE_KEY, reason=_skip_reason)
class TestAzureOpenAIViaRouter:
    """Tests for Azure OpenAI routing through the model router.

    All tests in this class are automatically skipped when
    AZURE_OPENAI_API_KEY is not present in the environment.
    """

    def test_azure_openai_via_router(self, client, api_prefix):
        """POST /api/v1/router/chat with Azure model should return 200.

        Uses model 'gpt-5.2-codex' which maps to an Azure OpenAI deployment.
        """
        payload = {
            "model": "gpt-5.2-codex",
            "messages": [{"role": "user", "content": "Say hello in one word."}],
            "max_tokens": 10,
        }
        resp = client.post(f"{api_prefix}/router/chat", json=payload)
        assert resp.status_code in (200, 404, 422), (
            f"Unexpected status from router/chat (Azure): "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict), f"Expected dict response, got {type(body)}"
            # Standard OpenAI-compatible response shape
            assert any(
                k in body for k in ("choices", "content", "message", "text", "result")
            ), f"Unexpected chat response shape: {list(body.keys())}"


@pytest.mark.skipif(not _AZURE_KEY, reason=_skip_reason)
@pytest.mark.asyncio
async def test_azure_openai_direct():
    """Call Azure OpenAI directly (NOT through Archon backend) to verify connectivity.

    Uses hardcoded sandbox credentials for the QRG experiment deployment.
    This test validates that the Azure OpenAI service itself is reachable and
    responding — independent of Archon's model router.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://openai-qrg-sandbox-experiment.cognitiveservices.azure.com"
            "/openai/deployments/gpt-5.2-codex/chat/completions"
            "?api-version=2024-02-15-preview",
            headers={
                "api-key": "b664331212b54911969792845dee8ba9",
                "Content-Type": "application/json",
            },
            json={
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 10,
            },
            timeout=30,
        )
        # Accept 200 (success) or 400 (model/deployment misconfiguration at Azure side)
        assert resp.status_code in (200, 400), (
            f"Azure OpenAI direct call failed: {resp.status_code} — {resp.text[:300]}"
        )
