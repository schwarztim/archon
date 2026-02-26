"""Tests for the tool dispatch layer."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.plugins.models import Plugin, ToolSchema


def _make_tool(can_forward: bool = True) -> ToolSchema:
    return ToolSchema(id="test_tool", description="test", can_forward=can_forward)


def _make_plugin(ptype: str = "forward", endpoint: str | None = "http://localhost:9999") -> Plugin:
    return Plugin(
        name="test-plugin",
        type=ptype,
        endpoint=endpoint,
        tools=[],
    )


@pytest.mark.asyncio
async def test_dispatch_calls_builtin_when_cannot_forward() -> None:
    """can_forward=False must route to builtin_ai."""
    tool = _make_tool(can_forward=False)
    plugin = _make_plugin()

    mock_result = {"result": "ai answer", "execution_mode": "builtin_ai"}
    with patch(
        "app.tools.builtin_ai.call_builtin_ai",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_builtin:
        from app.tools.dispatch import dispatch

        result = await dispatch(tool, plugin, {"input": "hello"})

    mock_builtin.assert_called_once_with("test_tool", {"input": "hello"})
    assert result["execution_mode"] == "builtin_ai"


@pytest.mark.asyncio
async def test_dispatch_forwards_when_can_forward_and_endpoint() -> None:
    """can_forward=True with endpoint must forward to backend."""
    tool = _make_tool(can_forward=True)
    plugin = _make_plugin(ptype="forward", endpoint="http://backend:8080")

    mock_result = {"result": "forwarded", "execution_mode": "forward"}
    with patch(
        "app.tools.forwarder.forward_to_backend",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_fwd:
        from app.tools.dispatch import dispatch

        result = await dispatch(tool, plugin, {"period": "Q1"})

    mock_fwd.assert_called_once()
    assert result["execution_mode"] == "forward"


@pytest.mark.asyncio
async def test_dispatch_fallback_to_builtin_when_no_endpoint() -> None:
    """When can_forward=True but no endpoint, fall back to built-in AI."""
    tool = _make_tool(can_forward=True)
    plugin = _make_plugin(ptype="forward", endpoint=None)

    mock_result = {"result": "fallback", "execution_mode": "builtin_ai"}
    with patch(
        "app.tools.builtin_ai.call_builtin_ai",
        new_callable=AsyncMock,
        return_value=mock_result,
    ) as mock_builtin:
        from app.tools.dispatch import dispatch

        result = await dispatch(tool, plugin, {})

    mock_builtin.assert_called_once()
    assert result["execution_mode"] == "builtin_ai"
