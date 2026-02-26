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


async def _check_keycloak() -> dict[str, Any]:
    """Check Keycloak connectivity."""
    try:
        from app.config import settings as app_settings

        import httpx

        url = f"{app_settings.KEYCLOAK_URL}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return {"status": "ok"}
            return {"status": "error", "error": f"HTTP {resp.status_code}"}
    except ImportError:
        return {"status": "error", "error": "httpx not installed"}
    except Exception as exc:
        logger.warning("keycloak_health_failed", error=str(exc))
        return {"status": "error", "error": str(exc)}


async def health_check() -> dict[str, Any]:
    """Liveness probe — always returns healthy if the process is alive."""
    return {
        "status": "healthy",
        "version": _VERSION,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


async def health_check_full() -> dict[str, Any]:
    """Full health check with all service statuses for the Settings page."""
    db = await _check_db()
    redis = await _check_redis()
    vault = await _check_vault()
    keycloak = await _check_keycloak()

    vault_status = "connected"
    if vault.get("status") != "ok":
        vault_status = (
            "stub"
            if "stub" in str(vault.get("details", vault.get("error", "")))
            else "sealed"
        )

    services = {
        "api": "up",
        "database": "up" if db.get("status") == "ok" else "down",
        "redis": "up" if redis.get("status") == "ok" else "down",
        "vault": vault_status,
        "keycloak": "up" if keycloak.get("status") == "ok" else "down",
    }

    return {
        "status": "healthy",
        "version": "1.0.0",
        "services": services,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


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
    check = await health_check()
    return {
        "data": {
            "status": "ok",
            "version": check.get("version", _VERSION),
        },
        "meta": {
            "timestamp": check.get(
                "timestamp", datetime.now(tz=timezone.utc).isoformat()
            ),
        },
    }


@router.get("/api/v1/health")
async def health_v1_endpoint() -> dict[str, Any]:
    """Full health check via API prefix (Settings page compatibility)."""
    return await health_check_full()


@router.get("/ready")
async def ready_endpoint() -> dict[str, Any]:
    """Readiness probe."""
    return await readiness_check()


__all__ = ["health_check", "health_check_full", "readiness_check", "router"]
