"""Tool dispatcher — routes invocations to builtin AI or plugin forwarder."""

from __future__ import annotations

import logging
from typing import Any

from app.plugins.models import Plugin, ToolSchema

logger = logging.getLogger(__name__)


async def dispatch(
    tool: ToolSchema,
    plugin: Plugin,
    body: dict[str, Any],
    *,
    caller_token: str | None = None,
) -> dict[str, Any]:
    """Dispatch a tool invocation to the correct execution backend.

    Decision tree:

    - ``tool.can_forward == False`` → execute via built-in Azure OpenAI
    - ``tool.can_forward == True`` and ``plugin.type == 'container'``
      → spin up container then forward
    - ``tool.can_forward == True`` and ``plugin.endpoint`` is set
      → forward to backend URL
    - Fallback → built-in Azure OpenAI
    """
    if not tool.can_forward:
        logger.info(
            "dispatch_builtin",
            extra={"tool_id": tool.id, "plugin": plugin.name},
        )
        from app.tools.builtin_ai import call_builtin_ai

        return await call_builtin_ai(tool.id, body)

    if plugin.type == "container":
        logger.info(
            "dispatch_container",
            extra={"tool_id": tool.id, "plugin": plugin.name},
        )
        from app.tools.container import get_or_start_container

        endpoint = await get_or_start_container(plugin)
        from app.tools.forwarder import forward_to_backend

        return await forward_to_backend(
            endpoint,
            tool.id,
            body,
            auth_header=plugin.auth_header,
            auth_token=caller_token,
        )

    if plugin.endpoint:
        logger.info(
            "dispatch_forward",
            extra={"tool_id": tool.id, "plugin": plugin.name, "endpoint": plugin.endpoint},
        )
        from app.tools.forwarder import forward_to_backend

        return await forward_to_backend(
            plugin.endpoint,
            tool.id,
            body,
            auth_header=plugin.auth_header,
            auth_token=caller_token,
        )

    # Fallback — no endpoint configured
    logger.warning(
        "dispatch_fallback_builtin",
        extra={"tool_id": tool.id, "plugin": plugin.name},
    )
    from app.tools.builtin_ai import call_builtin_ai

    return await call_builtin_ai(tool.id, body)
