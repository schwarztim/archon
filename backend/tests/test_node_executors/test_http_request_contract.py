"""httpRequestNode contract tests — Phase 3 / WS9.

Output envelope (success):
``{"status_code": 200, "body": dict|str, "headers": dict}``
Output (failure): ``status="failed"``, error names HTTP status or exception.
Cancellation: ``cancel_check`` honoured pre-flight (returns ``status="skipped"``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.node_executors import NODE_EXECUTORS  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


def _mock_httpx(status_code: int = 200, body=None, raise_exc=None):
    """Return a patched httpx.AsyncClient context manager."""
    if body is None:
        body = {"ok": True}

    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body
    response.headers = {"content-type": "application/json"}
    response.text = str(body)

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    if raise_exc:
        client.request = AsyncMock(side_effect=raise_exc)
    else:
        client.request = AsyncMock(return_value=response)

    return client


# ---------------------------------------------------------------------------
# 1. input schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_missing_url_is_failed():
    ctx = make_ctx("httpRequestNode", config={"method": "GET"})
    r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "failed"
    assert "url" in (r.error or "").lower()


@pytest.mark.asyncio
async def test_http_request_default_method_is_get():
    ctx = make_ctx("httpRequestNode", config={"url": "https://example.com/"})
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200)):
        r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "completed"


@pytest.mark.asyncio
async def test_http_request_supports_camel_and_snake_timeout():
    ctx_c = make_ctx(
        "httpRequestNode",
        config={"url": "https://x", "timeoutSeconds": 5},
    )
    ctx_s = make_ctx(
        "httpRequestNode",
        config={"url": "https://x", "timeout": 5},
    )
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200)):
        rc = await NODE_EXECUTORS["httpRequestNode"].execute(ctx_c)
        rs = await NODE_EXECUTORS["httpRequestNode"].execute(ctx_s)
    assert rc.status == "completed" and rs.status == "completed"


# ---------------------------------------------------------------------------
# 2. output schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_output_envelope_shape():
    ctx = make_ctx(
        "httpRequestNode",
        config={"method": "GET", "url": "https://example.com/"},
    )
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, {"answer": 42})):
        r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    for key in ("status_code", "body", "headers"):
        assert key in r.output
    assert r.output["status_code"] == 200
    assert r.output["body"] == {"answer": 42}


# ---------------------------------------------------------------------------
# 3. success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_2xx_completes():
    ctx = make_ctx(
        "httpRequestNode",
        config={"method": "POST", "url": "https://x", "body": {"k": "v"}},
    )
    with patch("httpx.AsyncClient", return_value=_mock_httpx(201, {"id": 1})):
        r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "completed"


@pytest.mark.asyncio
async def test_http_request_bearer_auth_header_assembled():
    captured: dict = {}

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {}
    response.headers = {}

    async def _request(method, url, **kw):
        captured.update(kw)
        return response

    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.request = _request

    ctx = make_ctx(
        "httpRequestNode",
        config={
            "method": "GET",
            "url": "https://x",
            "authType": "bearer",
            "authToken": "secret-token",
        },
    )
    with patch("httpx.AsyncClient", return_value=client):
        r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "completed"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"


# ---------------------------------------------------------------------------
# 4. failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_4xx_fails():
    ctx = make_ctx(
        "httpRequestNode", config={"method": "GET", "url": "https://x"}
    )
    with patch("httpx.AsyncClient", return_value=_mock_httpx(404)):
        r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "failed"
    assert "404" in (r.error or "")


@pytest.mark.asyncio
async def test_http_request_5xx_fails():
    ctx = make_ctx(
        "httpRequestNode", config={"method": "GET", "url": "https://x"}
    )
    with patch("httpx.AsyncClient", return_value=_mock_httpx(503)):
        r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "failed"


@pytest.mark.asyncio
async def test_http_request_timeout_fails():
    import httpx  # noqa: PLC0415

    ctx = make_ctx(
        "httpRequestNode",
        config={"method": "GET", "url": "https://x", "timeoutSeconds": 0.1},
    )
    with patch(
        "httpx.AsyncClient",
        return_value=_mock_httpx(raise_exc=httpx.TimeoutException("timed out")),
    ):
        r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "failed"
    assert "timed out" in (r.error or "").lower() or "timeoutexception" in (
        r.error or ""
    ).lower()


# ---------------------------------------------------------------------------
# 5. cancellation — honoured pre-flight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_cancellation_pre_flight():
    ctx = make_ctx(
        "httpRequestNode",
        config={"method": "GET", "url": "https://x"},
        cancel_check=lambda: True,
    )
    r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "skipped"
    assert r.output["reason"] == "cancelled"


# ---------------------------------------------------------------------------
# 6. retry classification — exception bubble surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_arbitrary_exception_caught():
    ctx = make_ctx(
        "httpRequestNode",
        config={"method": "GET", "url": "https://x"},
    )
    with patch(
        "httpx.AsyncClient",
        return_value=_mock_httpx(raise_exc=ConnectionError("ECONNREFUSED")),
    ):
        r = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)
    assert r.status == "failed"
    assert "ConnectionError" in (r.error or "") or "ECONNREFUSED" in (r.error or "")


# ---------------------------------------------------------------------------
# 7. tenant isolation — node has no tenant-scoped behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_tenant_id_does_not_affect_output():
    cfg = {"method": "GET", "url": "https://x"}
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, {"a": 1})):
        ra = await NODE_EXECUTORS["httpRequestNode"].execute(
            make_ctx("httpRequestNode", config=cfg, tenant_id="t-a")
        )
    with patch("httpx.AsyncClient", return_value=_mock_httpx(200, {"a": 1})):
        rb = await NODE_EXECUTORS["httpRequestNode"].execute(
            make_ctx("httpRequestNode", config=cfg, tenant_id="t-b")
        )
    assert ra.output == rb.output


# ---------------------------------------------------------------------------
# 8. event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_event_emission_not_applicable():
    pytest.skip("event emission N/A — HTTP node emits no events directly")
