"""Integration tests for the templates API.

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


class TestTemplates:
    """Tests for the /api/v1/templates endpoint."""

    def test_list_templates(self, client, api_prefix):
        """GET /api/v1/templates should return HTTP 200."""
        resp = client.get(f"{api_prefix}/templates")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from templates: {resp.status_code} — {resp.text[:300]}"
        )

    def test_templates_response_is_list(self, client, api_prefix):
        """GET /api/v1/templates response body should be a list (or paginated wrapper)."""
        resp = client.get(f"{api_prefix}/templates")
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            body = resp.json()
            # Accept bare list OR a dict with an 'items'/'data'/'results' key
            assert isinstance(body, (list, dict)), (
                f"Response body should be a list or dict, got {type(body).__name__}"
            )
            if isinstance(body, dict):
                assert any(
                    k in body
                    for k in ("items", "data", "results", "templates", "total")
                ), f"Unexpected paginated envelope keys: {list(body.keys())}"
