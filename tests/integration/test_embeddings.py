"""Integration tests for the embeddings endpoint via the model router.

Runs against a live Archon backend at http://localhost:8000.
AUTH_DEV_MODE=true — no auth headers required.

Skipped automatically when AZURE_OPENAI_API_KEY is not set in the environment,
because the embeddings model ('qrg-embedding-experimental') is hosted on Azure.
"""

import os

import httpx
import pytest

BASE_URL = "http://localhost:8000"

_AZURE_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
_skip_reason = "AZURE_OPENAI_API_KEY environment variable is not set"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as c:
        yield c


@pytest.fixture(scope="module")
def api_prefix():
    return "/api/v1"


@pytest.mark.skipif(not _AZURE_KEY, reason=_skip_reason)
class TestEmbeddings:
    """Tests for the embeddings endpoint through the model router.

    All tests in this class are automatically skipped when
    AZURE_OPENAI_API_KEY is not present in the environment.
    """

    def test_embeddings_endpoint(self, client, api_prefix):
        """POST /api/v1/router/embeddings should return a vector for the input text.

        Uses model 'qrg-embedding-experimental' (Azure OpenAI deployment).
        """
        payload = {
            "input": "test embedding input string",
            "model": "qrg-embedding-experimental",
        }
        resp = client.post(f"{api_prefix}/router/embeddings", json=payload)
        assert resp.status_code in (200, 422), (
            f"Unexpected status from router/embeddings: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict), f"Expected dict response, got {type(body)}"
            # Standard OpenAI-compatible embeddings response shape
            assert any(
                k in body for k in ("data", "embeddings", "embedding", "object")
            ), f"Unexpected embeddings response shape: {list(body.keys())}"
            if "data" in body:
                assert isinstance(body["data"], list), (
                    f"Expected 'data' to be a list, got {type(body['data'])}"
                )
                assert len(body["data"]) > 0, "Embeddings 'data' list is empty"
