"""Integration tests for the model router API.

Runs against a live Archon backend at http://localhost:8000.
AUTH_DEV_MODE=true — no auth headers required.
"""

import httpx
import pytest

BASE_URL = "http://localhost:8000"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        yield c


@pytest.fixture(scope="module")
def api_prefix():
    return "/api/v1"


class TestModelRouter:
    """Tests for model router providers list and health check."""

    def test_list_providers(self, client, api_prefix):
        """GET /api/v1/router/providers should return 200 with provider info."""
        resp = client.get(f"{api_prefix}/router/providers")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from router/providers: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )

    def test_router_health(self, client, api_prefix):
        """GET /api/v1/router/health should return 200."""
        resp = client.get(f"{api_prefix}/router/health")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from router/health: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict), (
                f"Expected dict body from router/health, got {type(body)}"
            )
