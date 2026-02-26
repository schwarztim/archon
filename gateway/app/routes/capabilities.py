"""GET /mcp/capabilities — lists tools visible to the authenticated user."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.auth.middleware import get_current_user
from app.auth.models import GatewayUser
from app.plugins.models import Plugin

router = APIRouter(tags=["mcp"])


def user_has_access(user: GatewayUser, plugin: Plugin) -> bool:
    """Return True if *user* is allowed to see/use *plugin*.

    Access is granted when:
    - The plugin has no ``required_groups`` restriction, OR
    - The user belongs to at least one of the required groups.
    """
    if not plugin.required_groups:
        return True
    user_groups = set(user.groups)
    return bool(user_groups.intersection(plugin.required_groups))


@router.get("/mcp/capabilities")
async def get_capabilities(
    request: Request,
    user: GatewayUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the MCP capabilities (tools) visible to the authenticated user."""
    from app.plugins.loader import plugin_loader

    plugins = plugin_loader.get_plugins()
    visible_tools: list[dict[str, Any]] = []

    for plugin in plugins:
        if not user_has_access(user, plugin):
            continue
        for tool in plugin.tools:
            visible_tools.append(
                {
                    "id": tool.id,
                    "plugin": plugin.name,
                    "plugin_display_name": plugin.display_name or plugin.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
            )

    return {
        "tools": visible_tools,
        "total": len(visible_tools),
        "user": {"oid": user.oid, "email": user.email},
    }
