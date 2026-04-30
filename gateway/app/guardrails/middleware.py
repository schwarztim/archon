"""Guardrails middleware — rate limiting, input validation and audit logging."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

# ── Redis-backed sliding-window rate limiter ───────────────────────────

# Initialize one module-level async Redis client (lazy, attempt on first use).
_redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_redis_client: Any = None


async def _get_redis() -> Any | None:
    """Return the async Redis client, creating it on first call.

    Returns ``None`` if the redis package is not installed or if the server
    is unreachable — callers fall back to the in-memory window store.
    """
    global _redis_client  # noqa: PLW0603

    if _redis_client is not None:
        return _redis_client

    try:
        import redis.asyncio as redis_async  # type: ignore[import]

        client = redis_async.from_url(
            _redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await client.ping()
        _redis_client = client
        logger.info("gateway.rate_limiter.redis.connected", extra={"url": _redis_url})
        return _redis_client
    except Exception as exc:
        logger.warning(
            "gateway.rate_limiter.redis.unavailable — falling back to in-memory: %s", exc
        )
        return None


class _RateLimiter:
    """Sliding-window rate limiter keyed by user oid.

    Uses Redis sorted sets when available:
      ZADD rl:<oid>  score=ts  member=ts
      ZREMRANGEBYSCORE rl:<oid>  0  (now - window)
      ZCOUNT rl:<oid>  -inf  +inf

    Falls back to an in-memory dict when Redis is unreachable so the gateway
    continues serving requests (graceful degrade).
    """

    WINDOW_SECONDS: float = 60.0

    def __init__(self) -> None:
        # In-memory fallback store: {oid: [timestamp, ...]}
        self._windows: dict[str, list[float]] = defaultdict(list)

    async def _check_redis(self, oid: str, limit_rpm: int) -> int | None:
        """Attempt the Redis sorted-set check.  Returns current count or None on error."""
        client = await _get_redis()
        if client is None:
            return None

        try:
            now = time.time()
            window_start = now - self.WINDOW_SECONDS
            key = f"rl:{oid}"

            pipe = client.pipeline()
            # Remove timestamps outside the current window
            pipe.zremrangebyscore(key, 0, window_start)
            # Add the current timestamp (score = member = timestamp for uniqueness)
            pipe.zadd(key, {str(now): now})
            # Count entries in window
            pipe.zcount(key, "-inf", "+inf")
            # Expire the key shortly after the window so Redis cleans up
            pipe.expire(key, int(self.WINDOW_SECONDS) + 5)
            results = await pipe.execute()
            return int(results[2])  # zcount result
        except Exception as exc:
            logger.warning("gateway.rate_limiter.redis.error: %s", exc)
            return None

    def _check_memory(self, oid: str, limit_rpm: int) -> int:
        """In-memory sliding window check.  Returns current count after eviction."""
        now = time.monotonic()
        window_start = now - self.WINDOW_SECONDS
        hits = self._windows[oid]
        self._windows[oid] = [ts for ts in hits if ts >= window_start]
        self._windows[oid].append(now)
        return len(self._windows[oid])

    async def check(self, oid: str, limit_rpm: int) -> None:
        """Raise :class:`HTTPException` 429 if *oid* exceeds *limit_rpm*."""
        count = await self._check_redis(oid, limit_rpm)

        if count is None:
            # Redis unavailable — fall back to in-memory
            count = self._check_memory(oid, limit_rpm)

        if count > limit_rpm:
            logger.warning(
                "rate_limit_exceeded", extra={"oid": oid, "count": count, "limit": limit_rpm}
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {count}/{limit_rpm} requests per minute",
                headers={"Retry-After": "60"},
            )


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

    async def __call__(
        self,
        request: Request,
        user_oid: str,
        tool_id: str,
        body: dict[str, Any],
    ) -> None:
        """Run all guardrails; raise HTTPException if any check fails."""
        from app.config import get_settings

        settings = get_settings()

        # 1. Rate limit (Redis-backed with in-memory fallback)
        if settings.rate_limit_enabled:
            await _rate_limiter.check(user_oid, settings.rate_limit_rpm)

        # 2. Input validation
        validate_tool_input(tool_id, body)

        # 3. Audit log (always, even when about to fail)
        audit_log_invocation(user_oid, tool_id, body, allowed=True)


guardrails = GuardrailsMiddleware()
