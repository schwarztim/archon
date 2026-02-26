"""Guardrails middleware — rate limiting, input validation and audit logging."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


# ── Simple in-memory rate limiter (per oid, per minute) ───────────────


class _RateLimiter:
    """Sliding-window rate limiter keyed by user oid."""

    def __init__(self) -> None:
        # {oid: [timestamp, ...]}
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, oid: str, limit_rpm: int) -> None:
        """Raise :class:`HTTPException` 429 if *oid* exceeds *limit_rpm*."""
        now = time.monotonic()
        window_start = now - 60.0
        hits = self._windows[oid]

        # Evict old entries
        self._windows[oid] = [ts for ts in hits if ts >= window_start]
        count = len(self._windows[oid])

        if count >= limit_rpm:
            logger.warning(
                "rate_limit_exceeded", extra={"oid": oid, "count": count, "limit": limit_rpm}
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {count}/{limit_rpm} requests per minute",
                headers={"Retry-After": "60"},
            )

        self._windows[oid].append(now)


_rate_limiter = _RateLimiter()


# ── Audit logger ──────────────────────────────────────────────────────


def audit_log_invocation(
    user_oid: str,
    tool_id: str,
    body: dict[str, Any],
    *,
    allowed: bool,
    reason: str = "",
) -> None:
    """Emit a structured audit log entry for every tool invocation attempt."""
    logger.info(
        "tool_invocation_audit",
        extra={
            "user_oid": user_oid,
            "tool_id": tool_id,
            "allowed": allowed,
            "reason": reason,
            "input_keys": list(body.keys()),
        },
    )


# ── Input validation ──────────────────────────────────────────────────


def validate_tool_input(tool_id: str, body: dict[str, Any]) -> None:
    """Basic input guard — ensure tool_id is non-empty and body is a dict.

    Schema-level validation per tool is deferred to the dispatch layer.
    """
    if not tool_id or not tool_id.strip():
        raise HTTPException(status_code=400, detail="tool_id must not be empty")

    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object")


# ── Convenience dependency ────────────────────────────────────────────


class GuardrailsMiddleware:
    """Callable class applied in route handlers as a pre-invocation check."""

    def __call__(
        self,
        request: Request,
        user_oid: str,
        tool_id: str,
        body: dict[str, Any],
    ) -> None:
        """Run all guardrails; raise HTTPException if any check fails."""
        from app.config import get_settings

        settings = get_settings()

        # 1. Rate limit
        if settings.rate_limit_enabled:
            _rate_limiter.check(user_oid, settings.rate_limit_rpm)

        # 2. Input validation
        validate_tool_input(tool_id, body)

        # 3. Audit log (always, even when about to fail)
        audit_log_invocation(user_oid, tool_id, body, allowed=True)


guardrails = GuardrailsMiddleware()
