"""Lazy Redis client for WebSocket event streaming.

Provides a single shared async Redis client backed by redis.asyncio.
The client is lazily initialized on first use so that the app boots
successfully even when Redis is unavailable at import time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis_client: "aioredis.Redis | None" = None


async def get_redis() -> "aioredis.Redis | None":
    """Return the shared Redis client, initialising it on first call.

    Returns ``None`` if the redis package is not installed or Redis is
    unreachable, allowing graceful degradation to the in-memory buffer.
    """
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    try:
        import redis.asyncio as aioredis  # type: ignore[import]
        from app.config import settings

        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        # Verify connectivity
        await _redis_client.ping()
        logger.info("redis.connected", extra={"url": settings.REDIS_URL})
        return _redis_client
    except Exception as exc:
        logger.warning("redis.unavailable — falling back to in-memory buffer: %s", exc)
        _redis_client = None
        return None


async def close_redis() -> None:
    """Close and reset the shared Redis client."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None
