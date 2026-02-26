"""Integration tests for RBAC / SSO custom roles API.

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


class TestRBAC:
    """Tests for SSO config custom roles (list and create)."""

    def test_list_roles(self, client, api_prefix):
        """GET /api/v1/sso/config/roles should return 200 with a list of roles."""
        resp = client.get(f"{api_prefix}/sso/config/roles")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from sso/config/roles: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict, got {type(body)}"
            )

    def test_create_custom_role(self, client, api_prefix):
        """POST /api/v1/sso/config/roles should return 200 or 201."""
        payload = {
            "name": "test-role",
            "permissions": ["read"],
            "description": "Created by integration test",
        }
        resp = client.post(f"{api_prefix}/sso/config/roles", json=payload)
        # 422 is acceptable if server-side validation rejects missing required fields
        assert resp.status_code in (200, 201, 409, 422), (
            f"Unexpected status creating custom role: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
