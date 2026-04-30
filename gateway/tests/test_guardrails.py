"""Tests for guardrails middleware."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


def test_empty_tool_id_raises_400() -> None:
    from app.guardrails.middleware import validate_tool_input

    with pytest.raises(HTTPException) as exc:
        validate_tool_input("", {})
    assert exc.value.status_code == 400


def test_non_dict_body_raises_422() -> None:
    from app.guardrails.middleware import validate_tool_input

    with pytest.raises(HTTPException) as exc:
        validate_tool_input("some_tool", [1, 2, 3])  # type: ignore[arg-type]
    assert exc.value.status_code == 422


def test_valid_input_passes() -> None:
    from app.guardrails.middleware import validate_tool_input

    # Should not raise
    validate_tool_input("get_revenue", {"period": "2025-Q1"})


@pytest.mark.asyncio
async def test_rate_limiter_allows_within_limit() -> None:
    from app.guardrails.middleware import _RateLimiter

    limiter = _RateLimiter()
    for _ in range(5):
        await limiter.check("user-oid", 10)  # 5 requests, limit 10 — should pass


@pytest.mark.asyncio
async def test_rate_limiter_blocks_over_limit() -> None:
    from app.guardrails.middleware import _RateLimiter

    limiter = _RateLimiter()
    for _ in range(3):
        await limiter.check("user-oid-ratelimited", 3)

    with pytest.raises(HTTPException) as exc:
        await limiter.check("user-oid-ratelimited", 3)
    assert exc.value.status_code == 429


def test_audit_log_invocation_does_not_raise() -> None:
    """Audit logging must never raise even with unusual inputs."""
    from app.guardrails.middleware import audit_log_invocation

    audit_log_invocation("oid", "tool_id", {}, allowed=True)
    audit_log_invocation("oid", "tool_id", {"nested": {"a": 1}}, allowed=False, reason="blocked")
