"""Slack connector — Slack Web API via httpx."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_SLACK_BASE = "https://slack.com/api"


class SlackConnector(BaseConnector):
    """Connector for the Slack Web API.

    Credential keys (``credentials`` dict, loaded from Vault):
        access_token: Bot/user OAuth token (``xoxb-…`` or ``xoxp-…``).
        bot_token: Alternative field name accepted for the token.

    Configuration keys (``config`` dict):
        default_channel: Default channel ID/name for write operations.
    """

    connector_type = "slack"

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        super().__init__(config, credentials)
        self._client: Any = None  # httpx.AsyncClient

    # ------------------------------------------------------------------
    # HTTP client
    # ------------------------------------------------------------------

    def _token(self) -> str:
        return (
            self.credentials.get("access_token")
            or self.credentials.get("bot_token")
            or ""
        )

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "httpx is required for SlackConnector. "
                "Install it with: pip install httpx"
            ) from exc

        self._client = httpx.AsyncClient(
            base_url=_SLACK_BASE,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=30.0,
        )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _api_call(self, method: str, **kwargs: Any) -> dict[str, Any]:
        """POST to a Slack API method and raise on Slack-level errors."""
        client = await self._get_client()
        response = await client.post(f"/{method}", json=kwargs)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return data

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def test_connection(self) -> dict[str, Any]:
        """Call ``auth.test`` to verify the token is valid."""
        start = time.monotonic()
        try:
            data = await self._api_call("auth.test")
            latency = (time.monotonic() - start) * 1000
            return {
                "success": True,
                "latency_ms": round(latency, 2),
                "message": "Authentication successful",
                "details": {
                    "team": data.get("team"),
                    "user": data.get("user"),
                    "bot_id": data.get("bot_id"),
                },
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            logger.warning("Slack test_connection failed: %s", exc)
            return {
                "success": False,
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def health_check(self) -> dict[str, Any]:
        """Run ``auth.test`` and return health status."""
        start = time.monotonic()
        try:
            await self._api_call("auth.test")
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "healthy",
                "latency_ms": round(latency, 2),
                "message": "Slack API reachable",
            }
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return {
                "status": "error",
                "latency_ms": round(latency, 2),
                "message": str(exc),
            }

    async def list_resources(self) -> list[dict[str, Any]]:
        """List public channels via ``conversations.list``.

        Returns:
            List of channel descriptors with ``id``, ``name``, ``is_private``,
            ``num_members``.
        """
        try:
            data = await self._api_call(
                "conversations.list",
                exclude_archived=True,
                limit=200,
                types="public_channel,private_channel",
            )
            channels: list[dict[str, Any]] = data.get("channels", [])
            return [
                {
                    "id": ch["id"],
                    "name": ch.get("name", ""),
                    "is_private": ch.get("is_private", False),
                    "num_members": ch.get("num_members", 0),
                    "topic": ch.get("topic", {}).get("value", ""),
                }
                for ch in channels
            ]
        except Exception as exc:
            logger.error("Slack list_resources failed: %s", exc)
            raise

    async def read(
        self,
        resource_id: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch message history from a channel via ``conversations.history``.

        Args:
            resource_id: Slack channel ID, e.g. ``"C12345678"``.
            params: Optional dict with:
                - ``limit`` (int, default 100)
                - ``oldest`` (str, Unix timestamp)
                - ``latest`` (str, Unix timestamp)

        Returns:
            List of message dicts.
        """
        params = params or {}
        limit = min(int(params.get("limit", 100)), 1000)
        call_kwargs: dict[str, Any] = {"channel": resource_id, "limit": limit}
        if "oldest" in params:
            call_kwargs["oldest"] = params["oldest"]
        if "latest" in params:
            call_kwargs["latest"] = params["latest"]

        try:
            data = await self._api_call("conversations.history", **call_kwargs)
            return data.get("messages", [])
        except Exception as exc:
            logger.error("Slack read failed for channel %s: %s", resource_id, exc)
            raise

    async def write(
        self,
        resource_id: str,
        data: Any,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Post a message to a channel via ``chat.postMessage``.

        Args:
            resource_id: Slack channel ID, e.g. ``"C12345678"``.
            data: Either a string (plain text) or a dict with Slack Block Kit
                fields (``text``, ``blocks``, ``attachments``, etc.).
            params: Optional extra API parameters.

        Returns:
            Dict with ``{"success": bool, "ts": str, "channel": str}``.
        """
        if isinstance(data, str):
            message_kwargs: dict[str, Any] = {"channel": resource_id, "text": data}
        elif isinstance(data, dict):
            message_kwargs = {"channel": resource_id, **data}
        else:
            raise ValueError("data must be a str or dict")

        if params:
            message_kwargs.update(params)

        try:
            result = await self._api_call("chat.postMessage", **message_kwargs)
            return {
                "success": True,
                "ts": result.get("ts", ""),
                "channel": result.get("channel", resource_id),
            }
        except Exception as exc:
            logger.error("Slack write failed for channel %s: %s", resource_id, exc)
            raise

    async def get_schema(self, resource_id: str) -> dict[str, Any]:
        """Return schema descriptor for a Slack channel.

        Args:
            resource_id: Slack channel ID.

        Returns:
            Dict with channel metadata and message field definitions.
        """
        try:
            data = await self._api_call("conversations.info", channel=resource_id)
            channel = data.get("channel", {})
            return {
                "channel_id": resource_id,
                "name": channel.get("name", ""),
                "is_private": channel.get("is_private", False),
                "fields": [
                    {"name": "ts", "type": "str", "description": "Message timestamp"},
                    {"name": "user", "type": "str", "description": "User ID"},
                    {"name": "text", "type": "str", "description": "Message text"},
                    {"name": "type", "type": "str", "description": "Event type"},
                    {
                        "name": "blocks",
                        "type": "list",
                        "description": "Block Kit blocks",
                    },
                    {
                        "name": "attachments",
                        "type": "list",
                        "description": "Message attachments",
                    },
                ],
            }
        except Exception as exc:
            logger.error("Slack get_schema failed for %s: %s", resource_id, exc)
            raise


__all__ = ["SlackConnector"]
