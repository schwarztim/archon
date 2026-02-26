"""WebSocket route for streaming execution updates."""

import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.websocket.execution_stream import execution_stream
from app.websocket.manager import authenticate_websocket

logger = logging.getLogger(__name__)

router = APIRouter()

_WS_CLOSE_AUTH_FAILED = 4001


# ── Auth helpers ─────────────────────────────────────────────────────────────


def _try_hs256_decode(token: str) -> dict[str, Any] | None:
    """Attempt HS256 dev-mode JWT decode."""
    try:
        from jose import jwt as jose_jwt  # type: ignore[import]
        from app.config import settings

        payload: dict[str, Any] = jose_jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_exp": True, "verify_iss": False, "verify_aud": False},
        )
        if payload.get("sub") and payload.get("email"):
            return payload
    except Exception:
        pass
    return None


async def _resolve_token(
    websocket: WebSocket,
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve a JWT from the ``?token=`` query parameter only.

    Returns:
        ``(None, None)`` when no token is supplied — connection is allowed
        in dev/test mode with an empty context.
        ``(token, payload)`` on successful validation.
        ``(token, None)`` when a token is supplied but invalid.
    """
    token: str | None = websocket.query_params.get("token")
    if not token:
        # No token — allow with empty context (dev/test mode)
        return None, None

    # Try JWKS validation first, then HS256 dev-mode fallback
    payload = await authenticate_websocket(websocket, token)
    if payload:
        return token, payload
    payload = _try_hs256_decode(token)
    if payload:
        return token, payload
    # Token provided but invalid
    return token, None


# ── WebSocket endpoint ───────────────────────────────────────────────────────


@router.websocket("/ws/executions/{execution_id}")
async def execution_ws(
    websocket: WebSocket,
    execution_id: str,
    last_event_id: str | None = Query(None, alias="last_event_id"),
) -> None:
    """Stream real-time events for a running execution.

    Authenticates via ``?token=`` query parameter.  Unauthenticated
    connections are allowed in dev/test mode.  Invalid tokens are rejected
    with close code 4001.

    Query parameters
    ----------------
    last_event_id : str, optional
        The ``event_id`` of the last event the client successfully received.
        When provided, all missed events are replayed from the Redis stream
        (durable) or in-memory buffer before live streaming resumes.

    Events streamed
    ---------------
    - ``llm_stream_token`` — incremental LLM token
    - ``tool_call``        — tool invocation started
    - ``tool_result``      — tool invocation completed
    - ``agent_start``      — agent begins a step
    - ``agent_complete``   — agent completes a step
    - ``error``            — execution-level error
    - ``cost_update``      — token/cost accounting update
    - ``ping``             — server heartbeat (every 30 s); client must reply ``pong``
    """
    token, payload = await _resolve_token(websocket)

    if payload is None and token is not None:
        # Token provided but invalid — accept then reject
        logger.warning(
            "websocket.auth_failed",
            extra={"execution_id": execution_id},
        )
        await websocket.accept()
        await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
        return

    # No token provided — allow with empty context (dev/test mode)
    if payload is None:
        payload = {}

    # Extract tenant context
    tenant_id: str = payload.get("tenant_id", "")
    if not tenant_id:
        issuer: str = payload.get("iss", "")
        parts = issuer.rstrip("/").split("/")
        tenant_id = parts[-1] if parts else ""

    user_id: str = payload.get("sub", "")

    logger.info(
        "websocket.connecting",
        extra={
            "execution_id": execution_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "last_event_id": last_event_id,
        },
    )

    # ExecutionStreamManager.connect() accepts the socket, starts heartbeat,
    # and replays missed events from in-memory buffer / Redis stream
    await execution_stream.connect(
        websocket,
        execution_id,
        tenant_id=tenant_id or None,
        last_event_id=last_event_id,
    )

    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except RuntimeError:
                # WebSocket already disconnected (state transition error)
                break
            # Delegate to manager: handles pong acknowledgement and
            # reconnect-replay requests
            await execution_stream.handle_client_message(websocket, execution_id, raw)
    except WebSocketDisconnect:
        pass
    finally:
        await execution_stream.disconnect(websocket, execution_id)
        logger.info(
            "websocket.disconnected",
            extra={
                "execution_id": execution_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
        )
