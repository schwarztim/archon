"""Application-wide Redis client singleton.

Provides a shared async Redis client for cache, rate-limiting, and
session storage.  The WebSocket subsystem has its own client in
``app.websocket.redis_client``; this module is the general-purpose one.

Usage::

    from app.cache import get_redis, close_redis

    redis = await get_redis()
    await redis.set("key", "value", ex=60)
    value = await redis.get("key")

"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Module-level singleton — reset to None by close_redis()
_redis_client: object | None = None


async def get_redis():  # type: ignore[return]
    """Return the shared async Redis client, initialising on first call.

    Returns the ``redis.asyncio.Redis`` instance or raises ``RuntimeError``
    if Redis is unavailable.  Unlike the WebSocket client, this version is
    *strict*: callers that genuinely need cache should handle the error rather
    than silently degrade.

    Returns:
        redis.asyncio.Redis: Connected Redis client.

    Raises:
        RuntimeError: If the redis package is not installed or Redis is
            unreachable.
    """
    global _redis_client  # noqa: PLW0603

    if _redis_client is not None:
        return _redis_client

    try:
        import redis.asyncio as aioredis  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "redis package is not installed. Add 'redis>=5.2.0' to requirements.txt."
        ) from exc

    from app.config import settings

    try:
        client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        await client.ping()
        _redis_client = client
        logger.info("cache.redis.connected", extra={"url": settings.REDIS_URL})
        return _redis_client
    except Exception as exc:
        logger.error("cache.redis.connection_failed: %s", exc)
        raise RuntimeError(f"Redis connection failed: {exc}") from exc


async def close_redis() -> None:
    """Close and reset the shared Redis client.

    Safe to call even if ``get_redis()`` was never called or already closed.
    """
    global _redis_client  # noqa: PLW0603

    if _redis_client is not None:
        try:
            await _redis_client.aclose()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("cache.redis.close_error: %s", exc)
        finally:
            _redis_client = None
            logger.info("cache.redis.disconnected")
