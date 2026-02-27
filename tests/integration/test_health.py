"""Integration tests for the /health endpoint.

Uses in-process TestClient — no live server required.
AUTH_DEV_MODE=true — no auth headers required.
"""

import pytest


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_endpoint(self, client):
        """GET /health should return HTTP 200 with a status field."""
        resp = client.get("/health")
        assert resp.status_code == 200, (
            f"Expected 200 from /health, got {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        assert isinstance(body, dict), "Health response should be a JSON object"
        # The endpoint wraps the status under a "data" key:
        # {"data": {"status": "ok", ...}, "meta": {...}}
        # Accept that shape as well as a bare top-level status key.
        effective = body.get("data", body)
        assert any(k in effective for k in ("status", "health", "ok", "healthy")), (
            f"Health response missing status key: {body}"
        )

    def test_health_contains_version(self, client):
        """GET /health response should include the application version."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        # Check the version is present either at top level or under "data"
        raw = str(body).lower()
        assert "version" in raw, f"Health response does not include version: {body}"

    def test_health_full_endpoint(self, client, api_prefix):
        """GET /api/v1/health returns full service status including database key."""
        resp = client.get(f"{api_prefix}/health")
        assert resp.status_code == 200
        body = resp.json()
        raw = str(body).lower()
        # The full health endpoint includes service checks with a "database" key
        assert any(word in raw for word in ("db", "database", "postgres", "sql")), (
            f"Full health response does not mention DB status: {body}"
        )
