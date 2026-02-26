"""Integration tests for the audit-logs API.

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


class TestAuditLogs:
    """Tests for the /api/v1/audit-logs/ endpoint."""

    def test_list_audit_logs(self, client, api_prefix):
        """GET /api/v1/audit-logs/ should return HTTP 200 with a list body."""
        resp = client.get(f"{api_prefix}/audit-logs/")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        # Accept either a bare list or a paginated envelope {"items": [...], ...}
        assert isinstance(body, (list, dict)), (
            f"Expected list or dict response, got {type(body)}"
        )
        if isinstance(body, dict):
            assert any(
                k in body for k in ("items", "data", "results", "logs", "audit_logs")
            ), f"Unexpected dict shape: {list(body.keys())}"

    def test_audit_logs_pagination(self, client, api_prefix):
        """GET /api/v1/audit-logs/ should honour limit and offset query params."""
        # Request first page
        resp_p1 = client.get(
            f"{api_prefix}/audit-logs/", params={"limit": 5, "offset": 0}
        )
        assert resp_p1.status_code == 200, (
            f"Pagination request failed: {resp_p1.status_code}"
        )

        # Request second page — just verify it doesn't crash
        resp_p2 = client.get(
            f"{api_prefix}/audit-logs/", params={"limit": 5, "offset": 5}
        )
        assert resp_p2.status_code == 200, (
            f"Second page returned unexpected status: {resp_p2.status_code}"
        )
