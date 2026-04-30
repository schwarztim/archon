"""POST /mcp/tools/{tool_id}/invoke — dispatches a tool invocation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth.middleware import get_current_user
from app.auth.models import GatewayUser
from app.guardrails.middleware import audit_log_invocation, guardrails
from app.routes.capabilities import user_has_access

router = APIRouter(tags=["mcp"])
logger = logging.getLogger(__name__)


@router.post("/mcp/tools/{tool_id}/invoke")
async def invoke_tool(
    tool_id: str,
    request: Request,
    user: GatewayUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Invoke a specific MCP tool by ID.

    The caller must:
    - Be authenticated (valid Entra JWT or dev-token in dev mode).
    - Have access to the plugin that exposes the tool.

    The invocation is dispatched to the appropriate backend (container,
    forwarded endpoint, or built-in Azure OpenAI) based on the tool config.

    The request body is a free-form JSON object (tool input).
    """
    from app.plugins.loader import plugin_loader

    # Parse request body as dict (handle empty body gracefully)
    try:
        body: dict[str, Any] = await request.json()
        if not isinstance(body, dict):
            body = {"input": body}
    except Exception:  # noqa: BLE001
        body = {}

    # 1. Guardrails (rate limit, input validation, audit log)
    try:
        await guardrails(request, user.oid, tool_id, body)
    except HTTPException:
        audit_log_invocation(user.oid, tool_id, body, allowed=False, reason="guardrail_rejected")
        raise

    # 2. Look up the tool
    entry = plugin_loader.get_tool_plugin(tool_id)
    if entry is None:
        audit_log_invocation(user.oid, tool_id, body, allowed=False, reason="tool_not_found")
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found")

    plugin, tool = entry

    # 3. Access control
    if not user_has_access(user, plugin):
        audit_log_invocation(user.oid, tool_id, body, allowed=False, reason="access_denied")
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: you do not have access to plugin '{plugin.name}'",
        )

    # 4. Dispatch
    from app.tools.dispatch import dispatch

    # Extract the caller's bearer token for forwarding
    auth_header = request.headers.get("Authorization", "")
    caller_token: str | None = None
    if auth_header.lower().startswith("bearer "):
        caller_token = auth_header[7:].strip()

    try:
        result = await dispatch(tool, plugin, body, caller_token=caller_token)
    except Exception as exc:
        logger.error("tool_invocation_error", exc_info=True, extra={"tool_id": tool_id})
        raise HTTPException(status_code=502, detail=f"Tool invocation failed: {exc}") from exc

    return {
        "tool_id": tool_id,
        "plugin": plugin.name,
        "result": result,
        "user_oid": user.oid,
    }
