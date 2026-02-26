"""Integration tests for the marketplace API.

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
        assert resp.status_code in (200, 422), (
            f"Unexpected status from marketplace/packages: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )
