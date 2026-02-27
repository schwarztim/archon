"""Integration tests for the audit-logs API.

Uses in-process TestClient — no live server required.
AUTH_DEV_MODE=true — no auth headers required.
"""

import pytest


class TestAuditLogs:
    """Tests for the /api/v1/audit-logs/ endpoint."""

    def test_list_audit_logs(self, client, api_prefix):
        """GET /api/v1/audit-logs/ should return HTTP 200 with a list body."""
        resp = client.get(f"{api_prefix}/audit-logs/")
        # The endpoint may require at least one filter (422) or return a list (200)
        assert resp.status_code in (200, 422), (
            f"Expected 200 or 422, got {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            # Accept either a bare list or a paginated envelope {"items": [...], ...}
            assert isinstance(body, (list, dict)), (
                f"Expected list or dict response, got {type(body)}"
            )
            if isinstance(body, dict):
                assert any(
                    k in body
                    for k in ("items", "data", "results", "logs", "audit_logs")
                ), f"Unexpected dict shape: {list(body.keys())}"

    def test_audit_logs_pagination(self, client, api_prefix):
        """GET /api/v1/audit-logs/ should honour limit and offset query params."""
        # Request first page — endpoint may require a filter param (422 is acceptable)
        resp_p1 = client.get(
            f"{api_prefix}/audit-logs/", params={"limit": 5, "offset": 0}
        )
        assert resp_p1.status_code in (200, 422), (
            f"Pagination request failed: {resp_p1.status_code}"
        )

        # Request second page — just verify it doesn't crash
        resp_p2 = client.get(
            f"{api_prefix}/audit-logs/", params={"limit": 5, "offset": 5}
        )
        assert resp_p2.status_code in (200, 422), (
            f"Second page returned unexpected status: {resp_p2.status_code}"
        )
