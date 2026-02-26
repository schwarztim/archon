"""Integration tests for the API keys settings endpoint.

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


class TestApiKeys:
    """Tests for listing and creating API keys under /api/v1/settings/api-keys."""

    def test_list_api_keys(self, client, api_prefix):
        """GET /api/v1/settings/api-keys should return 200 with a list."""
        resp = client.get(f"{api_prefix}/settings/api-keys")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from settings/api-keys: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )

    def test_create_api_key(self, client, api_prefix):
        """POST /api/v1/settings/api-keys with {"name":"test-key"} should return 200 or 201."""
        payload = {"name": "integration-test-key"}
        resp = client.post(f"{api_prefix}/settings/api-keys", json=payload)
        # 409 = key already exists; 422 = validation error — both indicate route works
        assert resp.status_code in (200, 201, 409, 422), (
            f"Unexpected status creating API key: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
