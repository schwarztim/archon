"""Gateway API routes — plugin management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.plugins.models import Plugin

router = APIRouter(prefix="/plugins", tags=["plugins"])


@router.get("/", response_model=list[Plugin], summary="List all loaded plugins")
async def list_plugins(request: Request) -> list[Plugin]:
    """Return every enabled plugin currently loaded by the gateway."""
    from app.plugins.loader import plugin_loader

    return plugin_loader.get_plugins()


@router.get("/{name}", response_model=Plugin, summary="Get a plugin by name")
async def get_plugin(name: str, request: Request) -> Plugin:
    """Return a single plugin definition identified by its *name* slug."""
    from app.plugins.loader import plugin_loader

    plugin = plugin_loader.get_plugin(name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")
    return plugin
