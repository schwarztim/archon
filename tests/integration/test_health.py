"""Integration tests for the /health endpoint.

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


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_endpoint(self, client):
        """GET /health should return HTTP 200 with a status field."""
        resp = client.get("/health")
        assert resp.status_code == 200, (
            f"Expected 200 from /health, got {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        # The response must contain *some* status indicator
        assert isinstance(body, dict), "Health response should be a JSON object"
        assert any(k in body for k in ("status", "health", "ok", "healthy")), (
            f"Health response missing status key: {body}"
        )

    def test_health_contains_db_status(self, client):
        """GET /health response should include database connectivity info."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        # Accept various common shapes: {"status":"ok","db":"healthy"},
        # {"status":"ok","components":{"database":...}}, {"database":...}, etc.
        raw = str(body).lower()
        assert any(word in raw for word in ("db", "database", "postgres", "sql")), (
            f"Health response does not mention DB status: {body}"
        )
