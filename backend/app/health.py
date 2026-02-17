"""Health and readiness probe endpoints for Archon."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])

_VERSION = "0.1.0"


async def _check_db() -> dict[str, Any]:
    """Verify database connectivity by executing a lightweight query."""
    try:
        from app.database import engine
        from sqlalchemy import text

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        logger.warning("db_health_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


async def _check_redis() -> dict[str, Any]:
    """Ping Redis and return status."""
    try:
        import redis.asyncio as aioredis

        from app.config import settings

        client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            pong = await client.ping()
            return {"status": "ok"} if pong else {"status": "error", "error": "no pong"}
        finally:
            await client.aclose()
    except Exception as exc:
        logger.warning("redis_health_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


async def _check_vault() -> dict[str, Any]:
    """Check Vault seal status via SecretsManager."""
    try:
        from app.secrets.manager import get_secrets_manager

        mgr = await get_secrets_manager()
        info = await mgr.health()
        if info.get("status") == "healthy" and not info.get("sealed", True):
            return {"status": "ok", "sealed": False}
        return {"status": "error", "details": info}
    except Exception as exc:
        logger.warning("vault_health_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


# ------------------------------------------------------------------
# Endpoint handlers (also importable for tests)
# ------------------------------------------------------------------


async def health_check() -> dict[str, Any]:
    """Liveness probe — always returns healthy if the process is alive."""
    return {"status": "healthy", "version": _VERSION}


async def readiness_check() -> dict[str, Any]:
    """Readiness probe — checks DB, Redis, and Vault connectivity."""
    db = await _check_db()
    redis = await _check_redis()
    vault = await _check_vault()

    checks = {"database": db, "redis": redis, "vault": vault}
    all_ok = all(c.get("status") == "ok" for c in checks.values())

    return {
        "status": "ready" if all_ok else "not_ready",
        "version": _VERSION,
        "checks": checks,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------
# Router endpoints
# ------------------------------------------------------------------


@router.get("/health")
async def health_endpoint() -> dict[str, Any]:
    """Liveness probe."""
    return await health_check()


@router.get("/api/v1/health")
async def health_v1_endpoint() -> dict[str, Any]:
    """Liveness probe via API prefix (Settings page compatibility)."""
    return await health_check()


@router.get("/ready")
async def ready_endpoint() -> dict[str, Any]:
    """Readiness probe."""
    return await readiness_check()


__all__ = ["health_check", "readiness_check", "router"]
