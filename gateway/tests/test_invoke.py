"""Tests for POST /api/v1/mcp/tools/{tool_id}/invoke."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_invoke_unknown_tool_returns_404(client: TestClient, dev_headers: dict) -> None:
    resp = client.post(
        "/api/v1/mcp/tools/nonexistent_tool/invoke",
        json={"key": "value"},
        headers=dev_headers,
    )
    assert resp.status_code == 404


def test_invoke_builtin_tool_calls_builtin_ai(client: TestClient, dev_headers: dict) -> None:
    """Public tool with can_forward=False should call built-in AI."""
    mock_result = {
        "tool_id": "public_tool",
        "result": "Built-in AI response",
        "model": "gpt-5.2-codex",
        "usage": {},
        "execution_mode": "builtin_ai",
    }
    with patch(
        "app.tools.builtin_ai.call_builtin_ai",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = client.post(
            "/api/v1/mcp/tools/public_tool/invoke",
            json={"input": "test"},
            headers=dev_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool_id"] == "public_tool"
    assert "result" in data


def test_invoke_finance_tool_allowed_for_finance_user(
    client: TestClient, dev_headers: dict
) -> None:
    """Finance user can invoke finance tools."""
    mock_result = {
        "tool_id": "get_revenue",
        "result": {"revenue": 1000000},
        "execution_mode": "forward",
    }
    with patch(
        "app.tools.forwarder.forward_to_backend",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = client.post(
            "/api/v1/mcp/tools/get_revenue/invoke",
            json={"period": "2025-Q1"},
            headers=dev_headers,
        )
    assert resp.status_code == 200
    assert resp.json()["tool_id"] == "get_revenue"


def test_invoke_returns_user_oid(client: TestClient, dev_headers: dict) -> None:
    """Response must include the caller's oid for audit trail."""
    mock_result = {"tool_id": "public_tool", "result": "ok", "execution_mode": "builtin_ai"}
    with patch(
        "app.tools.builtin_ai.call_builtin_ai",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        resp = client.post(
            "/api/v1/mcp/tools/public_tool/invoke",
            json={},
            headers=dev_headers,
        )
    assert resp.status_code == 200
    assert "user_oid" in resp.json()


def test_invoke_propagates_backend_error_as_502(client: TestClient, dev_headers: dict) -> None:
    """When dispatch raises, the route must return 502."""
    with patch(
        "app.tools.dispatch.dispatch",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Backend unavailable"),
    ):
        resp = client.post(
            "/api/v1/mcp/tools/get_revenue/invoke",
            json={"period": "2025-Q1"},
            headers=dev_headers,
        )
    assert resp.status_code == 502
