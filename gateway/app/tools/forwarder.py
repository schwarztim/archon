"""Tool forwarder — proxies MCP tool invocations to backend plugin endpoints."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def forward_to_backend(
    endpoint: str,
    tool_id: str,
    body: dict[str, Any],
    *,
    auth_header: str = "Authorization",
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Forward a tool invocation to the plugin's backend endpoint.

    Args:
        endpoint: Base URL of the plugin backend, e.g. ``http://finance-mcp:8080``.
        tool_id: The tool identifier to invoke.
        body: The tool input payload.
        auth_header: HTTP header name for forwarding credentials.
        auth_token: Bearer token to forward (e.g. the caller's access token).

    Returns:
        The parsed JSON response from the backend.

    Raises:
        ``httpx.HTTPStatusError`` on non-2xx responses.
        ``RuntimeError`` if httpx is not available.
    """
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx is required for tool forwarding") from exc

    url = f"{endpoint.rstrip('/')}/mcp/tools/{tool_id}/invoke"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if auth_token:
        headers[auth_header] = f"Bearer {auth_token}"

    logger.info(
        "tool_forward",
        extra={"tool_id": tool_id, "endpoint": endpoint},
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()
