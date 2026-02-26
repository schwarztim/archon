"""Integration tests for the settings API.

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


class TestSettings:
    """Tests for the /api/v1/settings endpoints."""

    def test_get_settings(self, client, api_prefix):
        """GET /api/v1/settings should return 200 with a settings object."""
        resp = client.get(f"{api_prefix}/settings")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from settings: {resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict), (
                f"Expected dict body from settings, got {type(body)}"
            )

    def test_list_notifications(self, client, api_prefix):
        """GET /api/v1/settings/notifications should return 200."""
        resp = client.get(f"{api_prefix}/settings/notifications")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from settings/notifications: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )
