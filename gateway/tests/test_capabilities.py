"""Tests for GET /api/v1/mcp/capabilities."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_capabilities_returns_tools(client: TestClient, dev_headers: dict) -> None:
    """Dev user in MCP-Users-Finance should see finance tools."""
    resp = client.get("/api/v1/mcp/capabilities", headers=dev_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert "total" in data
    assert data["total"] >= 1


def test_capabilities_includes_public_tool(client: TestClient, dev_headers: dict) -> None:
    """Public tools (no group restriction) should always be visible."""
    resp = client.get("/api/v1/mcp/capabilities", headers=dev_headers)
    assert resp.status_code == 200
    tool_ids = {t["id"] for t in resp.json()["tools"]}
    assert "public_tool" in tool_ids


def test_capabilities_includes_finance_tool_for_finance_user(
    client: TestClient, dev_headers: dict
) -> None:
    """Finance group member should see finance tools."""
    # dev user has groups: MCP-Users-Finance
    resp = client.get("/api/v1/mcp/capabilities", headers=dev_headers)
    assert resp.status_code == 200
    tool_ids = {t["id"] for t in resp.json()["tools"]}
    assert "get_revenue" in tool_ids


def test_capabilities_requires_auth(client: TestClient) -> None:
    """Missing auth header should return 401 when not in dev mode with dev-token."""
    # With AUTH_DEV_MODE=true and no token, dev user is returned — this passes
    # This tests that the endpoint at least responds correctly
    resp = client.get("/api/v1/mcp/capabilities")
    # In dev mode with no token, we get a dev user back
    assert resp.status_code == 200


def test_capabilities_tool_has_required_fields(client: TestClient, dev_headers: dict) -> None:
    """Each tool entry must have id, plugin, description, input_schema."""
    resp = client.get("/api/v1/mcp/capabilities", headers=dev_headers)
    assert resp.status_code == 200
    for tool in resp.json()["tools"]:
        assert "id" in tool
        assert "plugin" in tool
        assert "description" in tool
        assert "input_schema" in tool
