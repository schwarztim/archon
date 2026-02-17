"""Tests for the WebSocket streaming module."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.websocket import manager
from app.websocket.manager import ConnectionManager


def test_manager_is_singleton() -> None:
    """The package-level manager is a ConnectionManager instance."""
    assert isinstance(manager, ConnectionManager)


def test_websocket_connect_and_receive() -> None:
    """Client can connect and receive a broadcast event."""
    client = TestClient(app)
    with client.websocket_connect("/ws/executions/exec-1") as ws:
        # Manager should have the connection registered
        assert "exec-1" in manager._connections
        assert len(manager._connections["exec-1"]) == 1

        # Broadcast an event from the server side (sync helper)
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            manager.send_event("exec-1", "step_started", {"step": 1})
        )
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "step_started"
        assert msg["data"]["step"] == 1
        assert "timestamp" in msg


def test_websocket_disconnect_cleanup() -> None:
    """After client disconnects, connection list is cleaned up."""
    client = TestClient(app)
    with client.websocket_connect("/ws/executions/exec-2"):
        assert "exec-2" in manager._connections
    # After context manager exits, connection should be removed
    assert "exec-2" not in manager._connections


def test_manager_disconnect_idempotent() -> None:
    """Disconnecting an unknown websocket does not raise."""
    mgr = ConnectionManager()
    # Should not raise for missing execution_id
    mgr.disconnect(object(), "nonexistent")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_send_event_no_connections() -> None:
    """Sending to an execution with no connections is a no-op."""
    mgr = ConnectionManager()
    # Should not raise
    await mgr.send_event("missing", "error", {"msg": "boom"})
