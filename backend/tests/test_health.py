"""Tests for the /health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_200() -> None:
    """GET /health returns 200 with envelope format."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_envelope_format() -> None:
    """Response body has 'data' and 'meta' top-level keys."""
    client = TestClient(app)
    body = client.get("/health").json()
    assert "data" in body
    assert "meta" in body


def test_health_data_contains_status() -> None:
    """data.status is 'ok'."""
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["data"]["status"] == "ok"


def test_health_meta_has_timestamp() -> None:
    """meta.timestamp is an ISO-8601 string."""
    client = TestClient(app)
    body = client.get("/health").json()
    assert "timestamp" in body["meta"]
    # Basic sanity: contains a 'T' separator
    assert "T" in body["meta"]["timestamp"]
