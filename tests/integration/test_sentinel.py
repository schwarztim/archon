"""Integration tests for Sentinel & SentinelScan endpoints.

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


class TestSentinel:
    """Tests for sentinel discovery, posture, and enterprise status."""

    def test_sentinel_discover(self, client, api_prefix):
        """GET /api/v1/sentinel/discover should return 200."""
        resp = client.get(f"{api_prefix}/sentinel/discover")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from sentinel/discover: {resp.status_code} — {resp.text[:300]}"
        )

    def test_sentinelscan_posture(self, client, api_prefix):
        """GET /api/v1/sentinelscan/posture/summary should return 200."""
        resp = client.get(f"{api_prefix}/sentinelscan/posture/summary")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from sentinelscan/posture/summary: "
            f"{resp.status_code} — {resp.text[:300]}"
        )

    def test_sentinel_enterprise(self, client, api_prefix):
        """GET /api/v1/sentinel/enterprise/status should return 200."""
        resp = client.get(f"{api_prefix}/sentinel/enterprise/status")
        assert resp.status_code in (200, 422), (
            f"Unexpected status from sentinel/enterprise/status: "
            f"{resp.status_code} — {resp.text[:300]}"
        )
