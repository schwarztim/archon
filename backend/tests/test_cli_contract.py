"""Tests for the Archon CLI contract (W14).

Verifies that each CLI command:
  1. Constructs the correct HTTP method and path.
  2. Sends the correct JSON body or query parameters.
  3. Handles API errors gracefully (non-2xx status).
  4. Prints JSON output on success.

All HTTP calls are intercepted with httpx's MockTransport — no real server
or backend imports are used (public-API-only contract).
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import httpx
import pytest
from click.testing import CliRunner

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_API_URL", "http://test.local/api/v1")

# Import after env is set
from cli.archon_cli import cli  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_transport(status: int = 200, body: dict | None = None) -> httpx.MockTransport:
    """Return a MockTransport that always responds with the given status + body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status,
            json=body or {},
        )

    return httpx.MockTransport(handler)


def _invoke(*args: str, transport: httpx.MockTransport | None = None, **kwargs) -> "Result":  # noqa: F821
    """Run the CLI with the CliRunner, optionally patching httpx.Client."""
    runner = CliRunner(mix_stderr=False)
    if transport is not None:
        import cli.archon_cli as mod

        original = mod._get_client

        def patched_client():
            base_url = os.environ.get("ARCHON_API_URL", "http://test.local/api/v1")
            return httpx.Client(base_url=base_url, transport=transport)

        mod._get_client = patched_client
        try:
            return runner.invoke(cli, list(args), catch_exceptions=False, **kwargs)
        finally:
            mod._get_client = original
    return runner.invoke(cli, list(args), catch_exceptions=False, **kwargs)


# ---------------------------------------------------------------------------
# test_cli_start_command
# ---------------------------------------------------------------------------


def test_cli_start_command():
    """archon run start posts to /workflows/run with workflow_id and input."""
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"run": {"id": "abc", "status": "queued"}})

    transport = httpx.MockTransport(handler)
    result = _invoke(
        "run", "start",
        "--workflow-id", "00000000-0000-0000-0000-000000000001",
        "--input", '{"key": "value"}',
        transport=transport,
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert "/workflows/run" in str(req.url)
    body = json.loads(req.content)
    assert body["workflow_id"] == "00000000-0000-0000-0000-000000000001"
    assert body["input_data"] == {"key": "value"}
    # Output should be JSON
    output = json.loads(result.output)
    assert output["run"]["id"] == "abc"


# ---------------------------------------------------------------------------
# test_cli_list_runs
# ---------------------------------------------------------------------------


def test_cli_list_runs():
    """archon run list sends GET /runs with status and limit params."""
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"runs": [], "limit": 10, "offset": 0})

    transport = httpx.MockTransport(handler)
    result = _invoke(
        "run", "list", "--status", "completed", "--limit", "10",
        transport=transport,
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "GET"
    assert "/runs" in str(req.url)
    assert "status=completed" in str(req.url)
    assert "limit=10" in str(req.url)


# ---------------------------------------------------------------------------
# test_cli_cancel_run
# ---------------------------------------------------------------------------


def test_cli_cancel_run():
    """archon run cancel sends POST /runs/{id}/cancel with reason."""
    captured: list[httpx.Request] = []
    run_id = "11111111-0000-0000-0000-000000000001"

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(
            200, json={"run": {"id": run_id, "status": "cancelling"}, "action": "cancel_requested"}
        )

    transport = httpx.MockTransport(handler)
    result = _invoke(
        "run", "cancel", run_id, "--reason", "operator cancelled",
        transport=transport,
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert f"/runs/{run_id}/cancel" in str(req.url)
    body = json.loads(req.content)
    assert body["reason"] == "operator cancelled"


# ---------------------------------------------------------------------------
# test_cli_signal
# ---------------------------------------------------------------------------


def test_cli_signal():
    """archon run signal sends POST /runs/{id}/signal with name and payload."""
    captured: list[httpx.Request] = []
    run_id = "22222222-0000-0000-0000-000000000001"

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    result = _invoke(
        "run", "signal", run_id,
        "--name", "approval_received",
        "--payload", '{"approved": true}',
        transport=transport,
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    req = captured[0]
    assert req.method == "POST"
    assert f"/runs/{run_id}/signal" in str(req.url)
    body = json.loads(req.content)
    assert body["signal_name"] == "approval_received"
    assert body["payload"] == {"approved": True}


# ---------------------------------------------------------------------------
# test_cli_terminate
# ---------------------------------------------------------------------------


def test_cli_terminate():
    """archon run terminate sends POST /runs/{id}/terminate with reason."""
    captured: list[httpx.Request] = []
    run_id = "33333333-0000-0000-0000-000000000001"

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"run": {"id": run_id, "status": "cancelled"}})

    transport = httpx.MockTransport(handler)
    result = _invoke(
        "run", "terminate", run_id, "--reason", "hard stop",
        transport=transport,
    )

    assert result.exit_code == 0, result.output
    req = captured[0]
    assert req.method == "POST"
    assert f"/runs/{run_id}/terminate" in str(req.url)
    body = json.loads(req.content)
    assert body["reason"] == "hard stop"


# ---------------------------------------------------------------------------
# test_cli_error_handling
# ---------------------------------------------------------------------------


def test_cli_error_handling_non_2xx():
    """CLI raises ClickException on non-2xx API response."""
    transport = _mock_transport(status=404, body={"detail": "not found"})
    # Use mix_stderr=True so ClickException error output merges into result.output
    runner = CliRunner(mix_stderr=True)

    import cli.archon_cli as mod

    original = mod._get_client

    def patched_client():
        return httpx.Client(
            base_url=os.environ.get("ARCHON_API_URL", "http://test.local/api/v1"),
            transport=transport,
        )

    mod._get_client = patched_client
    try:
        result = runner.invoke(cli, ["run", "get", "nonexistent-id"])
    finally:
        mod._get_client = original

    assert result.exit_code != 0
    combined = (result.output or "") + (str(result.exception) if result.exception else "")
    assert "404" in combined or "API error" in combined or "not found" in combined


# ---------------------------------------------------------------------------
# test_cli_schedule_list
# ---------------------------------------------------------------------------


def test_cli_schedule_list():
    """archon schedule list sends GET /schedules."""
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"schedules": [], "total": 0})

    transport = httpx.MockTransport(handler)
    result = _invoke("schedule", "list", transport=transport)

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert captured[0].method == "GET"
    assert "/schedules" in str(captured[0].url)


# ---------------------------------------------------------------------------
# test_cli_worker_list
# ---------------------------------------------------------------------------


def test_cli_worker_list():
    """archon worker list sends GET /workers."""
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"workers": []})

    transport = httpx.MockTransport(handler)
    result = _invoke("worker", "list", transport=transport)

    assert result.exit_code == 0, result.output
    assert captured[0].method == "GET"
    assert "/workers" in str(captured[0].url)


# ---------------------------------------------------------------------------
# test_cli_queue_list
# ---------------------------------------------------------------------------


def test_cli_queue_list():
    """archon queue list sends GET /task-queues."""
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, json={"queues": []})

    transport = httpx.MockTransport(handler)
    result = _invoke("queue", "list", transport=transport)

    assert result.exit_code == 0, result.output
    assert captured[0].method == "GET"
    assert "/task-queues" in str(captured[0].url)


# ---------------------------------------------------------------------------
# test_cli_run_events (timeline)
# ---------------------------------------------------------------------------


def test_cli_run_events():
    """archon run events calls the timeline endpoint with cursor param."""
    captured: list[httpx.Request] = []
    run_id = "44444444-0000-0000-0000-000000000001"

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(
            200, json={"events": [], "next_cursor": None, "run_id": run_id}
        )

    transport = httpx.MockTransport(handler)
    result = _invoke("run", "events", run_id, "--cursor", "0", transport=transport)

    assert result.exit_code == 0, result.output
    req = captured[0]
    assert req.method == "GET"
    assert f"/runs/{run_id}/timeline" in str(req.url)
    assert "cursor=0" in str(req.url)
