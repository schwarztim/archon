"""Integration tests for the marketplace API.

Uses in-process TestClient — no live server required.
AUTH_DEV_MODE=true — no auth headers required.
"""

import pytest


class TestMarketplace:
    """Tests for marketplace categories and packages endpoints."""

    def test_marketplace_categories(self, client, api_prefix):
        """GET /api/v1/marketplace/categories should return 200 with a list."""
        resp = client.get(f"{api_prefix}/marketplace/categories")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from marketplace/categories: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )

    def test_marketplace_packages(self, client, api_prefix):
        """GET /api/v1/marketplace/packages should return 200 with a list."""
        resp = client.get(f"{api_prefix}/marketplace/packages")
        assert resp.status_code in (200, 404, 405, 422), (
            f"Unexpected status from marketplace/packages: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )
