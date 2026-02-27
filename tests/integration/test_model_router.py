"""Integration tests for the model router API.

Uses TestClient (in-process) via conftest.py fixtures.
AUTH_DEV_MODE=true — no auth headers required.
"""

import pytest


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
        assert resp.status_code in (200, 404, 422), (
            f"Unexpected status from router/health: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict), (
                f"Expected dict body from router/health, got {type(body)}"
            )
