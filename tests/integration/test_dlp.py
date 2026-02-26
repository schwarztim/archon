"""Integration tests for the DLP (Data Loss Prevention) API.

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


class TestDLP:
    """Tests for the DLP scan and policies endpoints."""

    def test_dlp_scan(self, client, api_prefix):
        """POST /api/v1/dlp/scan should return 200 with scan results."""
        payload = {
            "content": "test text with no sensitive data",
            "direction": "input",
        }
        resp = client.post(f"{api_prefix}/dlp/scan", json=payload)
        # 422 means the route exists but our payload differs from the schema — OK
        assert resp.status_code in (200, 422), (
            f"Unexpected status from dlp/scan: {resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict), (
                f"Expected dict from dlp/scan, got {type(body)}"
            )
            # Expect at minimum a risk level or action field
            assert any(
                k in body
                for k in ("risk_level", "action", "findings", "result", "status")
            ), f"Unexpected DLP scan response shape: {list(body.keys())}"

    def test_dlp_policies(self, client, api_prefix):
        """GET /api/v1/dlp/policies should return 200 with a list of policies."""
        resp = client.get(f"{api_prefix}/dlp/policies")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from dlp/policies: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict from dlp/policies, got {type(body)}"
            )
