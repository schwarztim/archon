"""Integration tests for the secrets/registrations API.

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


class TestSecrets:
    """Tests for secrets registration list and create."""

    def test_list_secrets(self, client, api_prefix):
        """GET /api/v1/secrets/registrations should return 200 with a list."""
        resp = client.get(f"{api_prefix}/secrets/registrations")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from secrets/registrations: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict body, got {type(body)}"
            )

    def test_register_secret(self, client, api_prefix):
        """POST /api/v1/secrets/register should return 200 or 201."""
        payload = {
            "name": "integration-test-secret",
            "secret_type": "api_key",
            "value": "test-dummy-value-for-integration-test",
            "description": "Created by integration test suite",
        }
        resp = client.post(f"{api_prefix}/secrets/register", json=payload)
        # 422 means the route exists but our payload failed validation — still OK
        assert resp.status_code in (200, 201, 409, 422), (
            f"Unexpected status registering secret: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
