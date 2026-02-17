"""WebSocket route for streaming execution updates."""

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket import manager
from app.websocket.manager import authenticate_websocket

logger = logging.getLogger(__name__)

router = APIRouter()

_WS_CLOSE_AUTH_FAILED = 4001


async def _resolve_token(websocket: WebSocket) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve a JWT from query param or first auth message.

    Checks ``?token=...`` query parameter first.  If absent, reads the
    first WebSocket message expecting ``{"type": "auth", "token": "..."}``.

    Returns:
        A tuple of (token, payload) on success or (None, None) on failure.
    """
    # 1. Try query parameter
    token: str | None = websocket.query_params.get("token")
    if token:
        payload = await authenticate_websocket(websocket, token)
        return (token, payload) if payload else (None, None)

    # 2. Try first message
    try:
        raw = await websocket.receive_text()
        msg = json.loads(raw)
        if isinstance(msg, dict) and msg.get("type") == "auth":
            token = msg.get("token", "")
            if token:
                payload = await authenticate_websocket(websocket, token)
                return (token, payload) if payload else (None, None)
    except Exception:
        pass

    return None, None


async def _resolve_token_dev(websocket: WebSocket) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve token with dev-mode HS256 fallback for WebSocket auth."""
    # 1. Try query parameter
    token: str | None = websocket.query_params.get("token")
    if token:
        # Try standard auth first
        payload = await authenticate_websocket(websocket, token)
        if payload:
            return token, payload
        # Try HS256 dev-mode fallback
        payload = _try_hs256_decode(token)
        if payload:
            return token, payload

    # 2. Try first message
    try:
        raw = await websocket.receive_text()
        msg = json.loads(raw)
        if isinstance(msg, dict) and msg.get("type") == "auth":
            token = msg.get("token", "")
            if token:
                payload = await authenticate_websocket(websocket, token)
                if payload:
                    return token, payload
                payload = _try_hs256_decode(token)
                if payload:
                    return token, payload
    except Exception:
        pass

    return None, None


def _try_hs256_decode(token: str) -> dict[str, Any] | None:
    """Attempt HS256 dev-mode JWT decode."""
    try:
        from jose import jwt as jose_jwt, JWTError
        from app.config import settings
        payload: dict[str, Any] = jose_jwt.decode(
            token, settings.JWT_SECRET, algorithms=["HS256"],
            options={"verify_exp": True, "verify_iss": False, "verify_aud": False},
        )
        if payload.get("sub") and payload.get("email"):
            return payload
    except Exception:
        pass
    return None


@router.websocket("/ws/executions/{execution_id}")
async def execution_ws(websocket: WebSocket, execution_id: str) -> None:
    """Stream real-time events for a running execution.

    Authenticates via ``?token=`` query parameter or a first-message auth
    handshake.  Unauthenticated connections are rejected with close code
    4001.  Authenticated connections are scoped to the user's tenant.

    Events streamed:
    - execution.started — execution begins processing
    - step.started — a step begins
    - step.completed — a step finishes with metrics
    - step.failed — a step encounters an error
    - tool.called — a tool invocation occurs
    - llm.response — LLM response received
    - execution.completed — execution finishes successfully
    - execution.failed — execution finishes with error
    """
    await websocket.accept()

    # Authenticate (with dev-mode fallback)
    token, payload = await _resolve_token_dev(websocket)
    if payload is None:
        logger.warning(
            "websocket.auth_failed",
            extra={"execution_id": execution_id},
        )
        await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
        return

    # Extract tenant context
    tenant_id: str = payload.get("tenant_id", "")
    if not tenant_id:
        issuer: str = payload.get("iss", "")
        parts = issuer.rstrip("/").split("/")
        tenant_id = parts[-1] if parts else ""

    user_id: str = payload.get("sub", "")

    logger.info(
        "websocket.authenticated",
        extra={
            "execution_id": execution_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
        },
    )

    # Register with tenant-scoped room (skip accept — already accepted above)
    manager._connections.setdefault(execution_id, []).append(websocket)
    if tenant_id:
        manager._tenant_rooms.setdefault(tenant_id, set()).add(execution_id)
        manager._connection_tenants[id(websocket)] = tenant_id

    try:
        while True:
            # Keep-alive: receive and discard client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, execution_id)
