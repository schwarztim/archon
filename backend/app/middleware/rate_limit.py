"""Redis-backed rate limiting middleware for Archon.

Two tiers of enforcement:
1. Global per-tenant — ``ARCHON_RATE_LIMIT_RPM`` requests per minute (default 1000)
2. Per-API-key — uses ``APIKey.rate_limit`` field when present

Uses Redis INCR + EXPIRE for a fixed-window counter.  Returns HTTP 429
with a ``Retry-After`` header when a limit is exceeded.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import settings

logger = logging.getLogger(__name__)

# Paths that bypass rate limiting entirely
_EXEMPT_PREFIXES = (
    "/health",
    "/healthz",
    "/readyz",
    "/livez",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
)

_WINDOW_SECONDS = 60  # fixed 1-minute window


def _get_redis():  # type: ignore[return]
    """Return a lazily-imported Redis client, or None if unavailable."""
    try:
        import redis.asyncio as aioredis  # type: ignore[import]

        # Use a module-level singleton to avoid re-connecting on every request
        if not hasattr(_get_redis, "_client"):
            _get_redis._client = aioredis.from_url(  # type: ignore[attr-defined]
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        return _get_redis._client  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover
        return None


async def _incr_window(redis: Any, key: str, limit: int) -> tuple[int, int]:
    """Increment the sliding-window counter for *key*.

    Returns ``(current_count, ttl_seconds)``.  Sets EXPIRE only on the first
    increment within a window so the counter resets automatically.
    """
    try:
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, _WINDOW_SECONDS)
        ttl = await redis.ttl(key)
        return int(current), max(int(ttl), 1)
    except Exception:
        # Redis unavailable — fail open (allow request)
        logger.debug("rate_limit: Redis error, failing open", exc_info=True)
        return 0, _WINDOW_SECONDS


def _build_429(retry_after: int) -> JSONResponse:
    """Build a standardised HTTP 429 response."""
    return JSONResponse(
        status_code=429,
        content={
            "errors": [
                {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": "Too many requests. Please retry after the indicated delay.",
                }
            ]
        },
        headers={"Retry-After": str(retry_after)},
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window rate limiter enforcing global-per-tenant and per-API-key limits."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Check rate limits before forwarding the request downstream."""
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # Exempt health / docs / metrics endpoints
        path = request.url.path
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        redis = _get_redis()
        if redis is None:
            # Redis not available — fail open
            return await call_next(request)

        # ------------------------------------------------------------------
        # Determine the tenant and optional API key from request state / headers
        # ------------------------------------------------------------------
        tenant_id: str = getattr(request.state, "tenant_id", "") or ""
        api_key_id: str = getattr(request.state, "api_key_id", "") or ""
        api_key_limit: int | None = getattr(request.state, "api_key_rate_limit", None)

        # Fall back to IP address as the rate-limit subject when no tenant is known
        if not tenant_id:
            tenant_id = request.client.host if request.client else "anonymous"

        window_minute = int(time.time()) // _WINDOW_SECONDS

        # ------------------------------------------------------------------
        # Tier 1: Global per-tenant rate limit
        # ------------------------------------------------------------------
        global_key = f"rl:{tenant_id}:{window_minute}"
        global_count, global_ttl = await _incr_window(
            redis, global_key, settings.RATE_LIMIT_RPM
        )

        if global_count > settings.RATE_LIMIT_RPM:
            logger.warning(
                "rate_limit: global tenant limit exceeded",
                extra={
                    "tenant_id": tenant_id,
                    "count": global_count,
                    "limit": settings.RATE_LIMIT_RPM,
                },
            )
            return _build_429(global_ttl)

        # ------------------------------------------------------------------
        # Tier 2: Per-API-key rate limit (when key is present and has a limit)
        # ------------------------------------------------------------------
        if api_key_id and api_key_limit is not None and api_key_limit > 0:
            key_key = f"rl:apikey:{api_key_id}:{window_minute}"
            key_count, key_ttl = await _incr_window(redis, key_key, api_key_limit)

            if key_count > api_key_limit:
                logger.warning(
                    "rate_limit: per-API-key limit exceeded",
                    extra={
                        "api_key_id": api_key_id,
                        "count": key_count,
                        "limit": api_key_limit,
                    },
                )
                return _build_429(key_ttl)

        return await call_next(request)
