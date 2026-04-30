"""W4a + W4b ActivityContext executor contract tests.

Covers:
  W4a — httpRequestNode  (execute_http_request)
  W4a — webhookTriggerNode (execute_webhook_trigger)
  W4b — toolNode         (execute_tool)
  W4b — databaseQueryNode (execute_database_query)

All external I/O is mocked; no network, database, or vault calls are made.
Tests run with --noconftest (no shared conftest.py loaded).
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the backend package root is on sys.path so ``app.*`` imports resolve
# when running with --noconftest.
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..")
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_BACKEND_DIR))

# Stub LLM mode so importing node_executors doesn't trigger real LLM calls.
os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services.activity_runtime import ActivityResult  # noqa: E402
from app.services.activity_runtime_test_doubles import build_test_context  # noqa: E402
from app.services.node_executors.http_request import execute_http_request  # noqa: E402
from app.services.node_executors.webhook_trigger import execute_webhook_trigger  # noqa: E402
from app.services.node_executors.tool import execute_tool, register_tool, TOOL_REGISTRY  # noqa: E402
from app.services.node_executors.database_query import execute_database_query  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_httpx_mock(
    status_code: int = 200,
    json_body: Any = None,
    text_body: str = "",
    content: bytes = b"",
    raise_exc: Exception | None = None,
) -> MagicMock:
    """Build a mock httpx.AsyncClient context manager."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": "application/json"}
    if json_body is not None:
        response.json.return_value = json_body
        response.text = str(json_body)
        response.content = content or str(json_body).encode()
    else:
        response.json.side_effect = ValueError("not json")
        response.text = text_body
        response.content = content or text_body.encode()

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    if raise_exc is not None:
        client.request = AsyncMock(side_effect=raise_exc)
    else:
        client.request = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# W4a — httpRequestNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_success():
    """Successful 200 response yields status=completed with body + status_code."""
    ctx = build_test_context(
        activity_type="httpRequestNode",
        node_config={
            "url": "https://api.example.com/data",
            "method": "GET",
        },
    )
    mock_client = _make_httpx_mock(status_code=200, json_body={"ok": True})
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await execute_http_request(ctx)

    assert isinstance(result, ActivityResult)
    assert result.status == "completed"
    assert result.output_data["status_code"] == 200
    assert result.output_data["body"] == {"ok": True}
    assert "headers" in result.output_data


@pytest.mark.asyncio
async def test_http_request_timeout_returns_failed():
    """TimeoutException maps to status=failed with error_code=TimeoutError."""
    import httpx  # noqa: PLC0415

    ctx = build_test_context(
        activity_type="httpRequestNode",
        node_config={
            "url": "https://slow.example.com/",
            "method": "GET",
            "timeout_seconds": 0.001,
        },
    )
    mock_client = _make_httpx_mock(raise_exc=httpx.TimeoutException("timed out"))
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await execute_http_request(ctx)

    assert result.status == "failed"
    assert result.error_code == "TimeoutError"
    assert "timed out" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_http_request_blocked_domain_returns_failed():
    """A URL whose hostname is not in allowed_domains is rejected pre-flight."""
    ctx = build_test_context(
        activity_type="httpRequestNode",
        node_config={
            "url": "https://evil.example.com/steal",
            "method": "GET",
            "allowed_domains": ["api.example.com", "safe.example.com"],
        },
    )
    result = await execute_http_request(ctx)

    assert result.status == "failed"
    assert result.error_code == "domain_not_allowed"
    assert result.non_retryable is True


@pytest.mark.asyncio
async def test_http_request_missing_url_returns_failed():
    ctx = build_test_context(
        activity_type="httpRequestNode",
        node_config={"method": "POST"},
    )
    result = await execute_http_request(ctx)
    assert result.status == "failed"
    assert result.error_code == "ValueError"


@pytest.mark.asyncio
async def test_http_request_4xx_returns_failed():
    ctx = build_test_context(
        activity_type="httpRequestNode",
        node_config={"url": "https://api.example.com/missing", "method": "GET"},
    )
    mock_client = _make_httpx_mock(status_code=404, json_body={"error": "not found"})
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await execute_http_request(ctx)

    assert result.status == "failed"
    assert "404" in (result.error_code or "")


@pytest.mark.asyncio
async def test_http_request_large_body_written_as_artifact():
    """Bodies > 1 MB are offloaded to write_artifact instead of output_data."""
    big_content = b"x" * (1024 * 1024 + 1)
    artifact_calls: list[tuple] = []

    async def fake_write_artifact(name, payload, metadata):
        artifact_calls.append((name, payload, metadata))
        return "artifact://stub/http_response_body/1234"

    ctx = build_test_context(
        activity_type="httpRequestNode",
        node_config={"url": "https://api.example.com/large", "method": "GET"},
    )
    # Override the write_artifact callback.
    from dataclasses import replace  # noqa: PLC0415

    ctx = replace(ctx, write_artifact=fake_write_artifact)

    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.side_effect = ValueError
    response.text = ""
    response.content = big_content

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.request = AsyncMock(return_value=response)

    with patch("httpx.AsyncClient", return_value=client):
        result = await execute_http_request(ctx)

    assert result.status == "completed"
    assert len(artifact_calls) == 1
    assert artifact_calls[0][0] == "http_response_body"
    assert "artifact_ref" in result.output_data["body"]


# ---------------------------------------------------------------------------
# W4a — webhookTriggerNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_trigger_returns_paused():
    """First execution parks the run with status=paused."""
    ctx = build_test_context(
        activity_type="webhookTriggerNode",
        node_config={"webhook_token": "tok-abc-123"},
    )
    result = await execute_webhook_trigger(ctx)

    assert isinstance(result, ActivityResult)
    assert result.status == "paused"
    assert result.heartbeat_details is not None
    assert result.heartbeat_details["waiting_for"] == "webhook"
    assert result.heartbeat_details["webhook_token"] == "tok-abc-123"


@pytest.mark.asyncio
async def test_webhook_trigger_resume_path_returns_completed():
    """When the signal service injects webhook_payload, executor returns completed."""
    ctx = build_test_context(
        activity_type="webhookTriggerNode",
        node_config={"webhook_token": "tok-abc-123"},
        input_data={"webhook_payload": {"event": "order.created", "id": 42}},
    )
    result = await execute_webhook_trigger(ctx)

    assert result.status == "completed"
    assert result.output_data["trigger"] == "webhook"
    assert result.output_data["payload"]["event"] == "order.created"


# ---------------------------------------------------------------------------
# W4b — toolNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_node_calls_registered_tool():
    """execute_tool invokes a registered callable and returns its output."""
    async def multiply(input_data: dict) -> dict:
        return {"product": input_data["a"] * input_data["b"]}

    register_tool("_test_multiply", multiply)
    try:
        ctx = build_test_context(
            activity_type="toolNode",
            node_config={
                "tool_name": "_test_multiply",
                "tool_input": {"a": 6, "b": 7},
            },
        )
        result = await execute_tool(ctx)

        assert result.status == "completed"
        assert result.output_data["tool_output"]["product"] == 42
        assert result.output_data["tool_name"] == "_test_multiply"
    finally:
        TOOL_REGISTRY.pop("_test_multiply", None)


@pytest.mark.asyncio
async def test_tool_node_unknown_tool_returns_failed():
    """Unknown tool_name yields status=failed with error_code=ToolNotFound."""
    ctx = build_test_context(
        activity_type="toolNode",
        node_config={"tool_name": "nonexistent_tool_xyz"},
    )
    result = await execute_tool(ctx)

    assert result.status == "failed"
    assert result.error_code == "ToolNotFound"
    assert result.non_retryable is True


@pytest.mark.asyncio
async def test_tool_node_missing_tool_name_returns_failed():
    ctx = build_test_context(
        activity_type="toolNode",
        node_config={},
    )
    result = await execute_tool(ctx)

    assert result.status == "failed"
    assert result.error_code == "ValueError"


@pytest.mark.asyncio
async def test_tool_node_tool_exception_returns_failed():
    """Exception raised by a tool callable maps to status=failed."""
    async def exploding_tool(input_data: dict) -> dict:
        raise RuntimeError("tool exploded")

    register_tool("_test_exploding", exploding_tool)
    try:
        ctx = build_test_context(
            activity_type="toolNode",
            node_config={"tool_name": "_test_exploding"},
        )
        result = await execute_tool(ctx)
        assert result.status == "failed"
        assert result.error_code == "RuntimeError"
    finally:
        TOOL_REGISTRY.pop("_test_exploding", None)


@pytest.mark.asyncio
async def test_tool_node_builtin_echo():
    """Built-in echo tool is available without explicit registration."""
    ctx = build_test_context(
        activity_type="toolNode",
        node_config={
            "tool_name": "echo",
            "tool_input": {"message": "hello"},
        },
    )
    result = await execute_tool(ctx)
    assert result.status == "completed"
    assert result.output_data["tool_output"]["echo"]["message"] == "hello"


# ---------------------------------------------------------------------------
# W4b — databaseQueryNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_database_query_resolves_secret():
    """execute_database_query calls resolve_secret with the configured ref."""
    resolved_calls: list[str] = []

    async def capture_resolve(ref: str) -> str:
        resolved_calls.append(ref)
        # Return a real (fake) connection string so SQLAlchemy can parse it.
        return "sqlite:///:memory:"

    ctx = build_test_context(
        activity_type="databaseQueryNode",
        node_config={
            "connection_string_secret_ref": "vault://prod/db/conn",
            "query": "SELECT 1 AS n",
        },
    )
    from dataclasses import replace  # noqa: PLC0415

    ctx = replace(ctx, resolve_secret=capture_resolve)

    with patch(
        "app.services.node_executors.database_query._run_query",
        new=AsyncMock(return_value=[{"n": 1}]),
    ):
        result = await execute_database_query(ctx)

    assert resolved_calls == ["vault://prod/db/conn"]
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_database_query_readonly():
    """read_only=True is passed through to _run_query."""
    calls: list[dict] = []

    async def fake_run_query(**kwargs):
        calls.append(kwargs)
        return [{"count": 5}]

    async def stub_resolve(ref: str) -> str:
        return "sqlite:///:memory:"

    ctx = build_test_context(
        activity_type="databaseQueryNode",
        node_config={
            "connection_string_secret_ref": "vault://db",
            "query": "SELECT count(*) AS count FROM users",
            "read_only": True,
        },
    )
    from dataclasses import replace  # noqa: PLC0415

    ctx = replace(ctx, resolve_secret=stub_resolve)

    with patch(
        "app.services.node_executors.database_query._run_query",
        new=AsyncMock(side_effect=fake_run_query),
    ):
        result = await execute_database_query(ctx)

    assert result.status == "completed"
    assert calls[0]["read_only"] is True
    assert result.output_data["rows"] == [{"count": 5}]
    assert result.output_data["row_count"] == 1


@pytest.mark.asyncio
async def test_database_query_missing_secret_ref_returns_failed():
    ctx = build_test_context(
        activity_type="databaseQueryNode",
        node_config={"query": "SELECT 1"},
    )
    result = await execute_database_query(ctx)
    assert result.status == "failed"
    assert result.error_code == "ValueError"
    assert result.non_retryable is True


@pytest.mark.asyncio
async def test_database_query_secret_resolution_failure_returns_failed():
    """When resolve_secret raises, the executor returns failed (non-retryable)."""
    async def bad_resolve(ref: str) -> str:
        raise PermissionError("vault access denied")

    ctx = build_test_context(
        activity_type="databaseQueryNode",
        node_config={
            "connection_string_secret_ref": "vault://restricted",
            "query": "SELECT 1",
        },
    )
    from dataclasses import replace  # noqa: PLC0415

    ctx = replace(ctx, resolve_secret=bad_resolve)

    result = await execute_database_query(ctx)
    assert result.status == "failed"
    assert result.error_code == "SecretResolutionError"
    assert result.non_retryable is True


@pytest.mark.asyncio
async def test_database_query_engine_error_returns_failed():
    """SQL execution errors map to status=failed."""
    async def stub_resolve(ref: str) -> str:
        return "sqlite:///:memory:"

    ctx = build_test_context(
        activity_type="databaseQueryNode",
        node_config={
            "connection_string_secret_ref": "vault://db",
            "query": "SELECT * FROM nonexistent_table",
        },
    )
    from dataclasses import replace  # noqa: PLC0415

    ctx = replace(ctx, resolve_secret=stub_resolve)

    with patch(
        "app.services.node_executors.database_query._run_query",
        new=AsyncMock(side_effect=Exception("no such table: nonexistent_table")),
    ):
        result = await execute_database_query(ctx)

    assert result.status == "failed"
    assert "nonexistent_table" in (result.error_message or "")
