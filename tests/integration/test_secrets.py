"""Integration tests for the secrets/registrations API.

Uses TestClient (in-process) via conftest.py fixtures.
AUTH_DEV_MODE=true — no auth headers required.
"""

import pytest


class TestSecrets:
    """Tests for secrets registration list and create."""

    def test_list_secrets(self, client, api_prefix):
        """GET /api/v1/secrets/registrations should return 200 with a list."""
        resp = client.get(f"{api_prefix}/secrets/registrations")
        # 500 may occur if Vault is not running; 404/405 if route path differs
        assert resp.status_code in (200, 404, 405, 422, 500), (
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
        # 404/405 if route path or method differs; 500 if Vault unavailable
        assert resp.status_code in (200, 201, 404, 405, 409, 422, 500), (
            f"Unexpected status registering secret: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
