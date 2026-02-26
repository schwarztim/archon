"""Health and readiness check endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness probe")
async def health(request: Request) -> dict[str, str]:
    """Return service liveness status."""
    from app.config import get_settings

    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready", summary="Readiness probe")
async def ready(request: Request) -> dict[str, object]:
    """Return service readiness — includes plugin count."""
    from app.plugins.loader import plugin_loader

    plugins = plugin_loader.get_plugins()
    return {
        "status": "ready",
        "plugins_loaded": len(plugins),
        "plugin_names": [p.name for p in plugins],
    }
