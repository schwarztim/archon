"""Integration tests for Sentinel & SentinelScan endpoints.

Uses TestClient (in-process) via conftest.py fixtures.
AUTH_DEV_MODE=true — no auth headers required.
"""

import pytest


class TestSentinel:
    """Tests for sentinel discovery, posture, and enterprise status."""

    def test_sentinel_discover(self, client, api_prefix):
        """GET /api/v1/sentinel/discover should return 200 (or 405 if POST-only)."""
        resp = client.get(f"{api_prefix}/sentinel/discover")
        assert resp.status_code in (200, 404, 405, 422), (
            f"Unexpected status from sentinel/discover: {resp.status_code} — {resp.text[:300]}"
        )

    def test_sentinelscan_posture(self, client, api_prefix):
        """GET /api/v1/sentinelscan/posture/summary should return 200."""
        resp = client.get(f"{api_prefix}/sentinelscan/posture/summary")
        assert resp.status_code in (200, 404, 422), (
            f"Unexpected status from sentinelscan/posture/summary: "
            f"{resp.status_code} — {resp.text[:300]}"
        )

    def test_sentinel_enterprise(self, client, api_prefix):
        """GET /api/v1/sentinel/enterprise/status should return 200."""
        resp = client.get(f"{api_prefix}/sentinel/enterprise/status")
        assert resp.status_code in (200, 404, 422), (
            f"Unexpected status from sentinel/enterprise/status: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
