"""WebSocket connection manager for real-time execution updates."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


async def authenticate_websocket(
    websocket: WebSocket,
    token: str,
) -> dict[str, Any] | None:
    """Validate a JWT token for a WebSocket connection.

    Uses the same JWKS-based validation as the HTTP auth middleware.

    Args:
        websocket: The WebSocket connection (unused directly, kept for
            context/logging).
        token: The raw JWT string to validate.

    Returns:
        The decoded JWT payload dict on success, or ``None`` if the token
        is invalid or expired.
    """
    from app.middleware.auth import _extract_roles, _fetch_jwks, _get_signing_key

    try:
        from jose import JWTError, jwt as jose_jwt
        from jose.exceptions import ExpiredSignatureError
    except ImportError:
        logger.error("python-jose not installed; cannot validate WebSocket token")
        return None

    from app.config import settings

    try:
        jwks = await _fetch_jwks()
        signing_key = _get_signing_key(jwks, token)
        payload: dict[str, Any] = jose_jwt.decode(
            token,
            signing_key,
            algorithms=[settings.JWT_ALGORITHM],
            audience="account",
            issuer=settings.KEYCLOAK_URL,
            options={
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
        return payload
    except (JWTError, ExpiredSignatureError, Exception):
        logger.warning("WebSocket token validation failed")
        return None


class ConnectionManager:
    """Manages WebSocket connections grouped by execution_id.

    Supports optional tenant isolation: connections can be scoped to a
    ``tenant_id`` so that broadcast messages only reach connections
    belonging to the same tenant.
    """

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self._tenant_rooms: dict[str, set[str]] = {}
        self._connection_tenants: dict[int, str] = {}

    async def connect(
        self,
        websocket: WebSocket,
        execution_id: str,
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Accept and register a WebSocket for the given execution.

        Args:
            websocket: The WebSocket to accept and register.
            execution_id: Execution identifier to group connections.
            tenant_id: Optional tenant identifier for tenant-scoped rooms.
        """
        await websocket.accept()
        self._connections.setdefault(execution_id, []).append(websocket)

        if tenant_id:
            self._tenant_rooms.setdefault(tenant_id, set()).add(execution_id)
            self._connection_tenants[id(websocket)] = tenant_id

        logger.info(
            "websocket.connect",
            extra={
                "execution_id": execution_id,
                "tenant_id": tenant_id or "",
            },
        )

    def disconnect(
        self,
        websocket: WebSocket,
        execution_id: str,
    ) -> None:
        """Remove a WebSocket from the given execution's connection list."""
        tenant_id = self._connection_tenants.pop(id(websocket), None)

        conns = self._connections.get(execution_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(execution_id, None)
            # Clean up tenant room entry
            if tenant_id:
                room = self._tenant_rooms.get(tenant_id)
                if room:
                    room.discard(execution_id)
                    if not room:
                        self._tenant_rooms.pop(tenant_id, None)

        logger.info(
            "websocket.disconnect",
            extra={
                "execution_id": execution_id,
                "tenant_id": tenant_id or "",
            },
        )

    async def send_event(
        self,
        execution_id: str,
        event_type: str,
        data: dict,
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Broadcast a JSON event to all connections for an execution.

        When *tenant_id* is provided, the event is only sent to connections
        that belong to the same tenant.
        """
        message = json.dumps(
            {
                "type": event_type,
                "data": data,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }
        )

        conns = list(self._connections.get(execution_id, []))

        if tenant_id:
            conns = [
                ws
                for ws in conns
                if self._connection_tenants.get(id(ws)) == tenant_id
            ]

        tasks = [self._safe_send(ws, message, execution_id) for ws in conns]
        if tasks:
            await asyncio.gather(*tasks)

    def get_tenant_executions(self, tenant_id: str) -> set[str]:
        """Return execution IDs associated with a tenant."""
        return set(self._tenant_rooms.get(tenant_id, set()))

    async def _safe_send(
        self, websocket: WebSocket, message: str, execution_id: str
    ) -> None:
        """Send a message, disconnecting on failure."""
        try:
            await websocket.send_text(message)
        except Exception:
            self.disconnect(websocket, execution_id)
