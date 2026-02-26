"""WebSocket connection manager for real-time execution updates.

Provides two classes:

- :class:`ConnectionManager` — lightweight manager kept for backward
  compatibility.  New code should prefer :class:`ExecutionStreamManager`.

- :class:`ExecutionStreamManager` — full-featured Redis-backed streaming
  manager implementing connect/broadcast/disconnect with event replay, tenant
  isolation, and server-side heartbeat.

Event format
------------
Every event broadcast through :class:`ExecutionStreamManager` has the shape::

    {
        "event_id": "<uuid4>",
        "type": "llm_stream_token" | "tool_call" | "tool_result"
               | "agent_start" | "agent_complete" | "error" | "cost_update",
        "timestamp": "2025-02-25T10:00:00.000000+00:00",
        "data": { ... }   # type-specific payload
    }

Redis stream keys
-----------------
Events are stored under ``ws:execution:{execution_id}``.
Streams are capped at 500 entries and expire after 24 h with no activity.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_EVENT_BUFFER_SIZE = 200  # In-memory ring buffer size per execution
_STREAM_MAXLEN = 500  # Redis stream cap (approximate)
_STREAM_TTL_SECONDS = 86_400  # 24 h stream TTL
_HEARTBEAT_INTERVAL = 30  # Seconds between server pings
_PONG_TIMEOUT = 90  # Seconds to wait for pong before disconnect
_STREAM_KEY_TPL = "ws:execution:{execution_id}"


def _stream_key(execution_id: str) -> str:
    return _STREAM_KEY_TPL.format(execution_id=execution_id)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ── Auth helper ───────────────────────────────────────────────────────────────


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


# ── Buffered event ───────────────────────────────────────────────────────────


class _BufferedEvent:
    __slots__ = ("event_id", "serialised")

    def __init__(self, event_id: str, serialised: str) -> None:
        self.event_id = event_id
        self.serialised = serialised


# ── Connection metadata ──────────────────────────────────────────────────────


class _ConnMeta:
    __slots__ = (
        "websocket",
        "execution_id",
        "tenant_id",
        "last_ping_sent",
        "last_pong_received",
        "_heartbeat_task",
    )

    def __init__(
        self,
        websocket: WebSocket,
        execution_id: str,
        tenant_id: str | None,
    ) -> None:
        self.websocket = websocket
        self.execution_id = execution_id
        self.tenant_id = tenant_id
        self.last_ping_sent: str | None = None
        self.last_pong_received: str | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None


# ── ExecutionStreamManager ───────────────────────────────────────────────────


class ExecutionStreamManager:
    """Manages WebSocket connections for execution event streaming.

    This class owns the full lifecycle:
    1. ``connect()``  — accept socket, start heartbeat, replay missed events
    2. ``broadcast()``— persist to Redis stream (XADD execution:{id}), then fan-out
    3. ``disconnect()``— clean up metadata and cancel heartbeat task
    4. ``handle_client_message()``— process ping/pong/reconnect messages
    """

    def __init__(self) -> None:
        # execution_id → list of active WebSockets
        self._connections: dict[str, list[WebSocket]] = {}
        # tenant_id → set of execution_ids (for scoped broadcast)
        self._tenant_rooms: dict[str, set[str]] = {}
        # id(websocket) → tenant_id
        self._connection_tenants: dict[int, str] = {}
        # id(websocket) → connection metadata
        self._connection_meta: dict[int, _ConnMeta] = {}
        # execution_id → ring buffer of recent events (for fast replay)
        self._event_buffer: dict[str, deque[_BufferedEvent]] = {}

    # ── Public connect / disconnect ──────────────────────────────────────────

    async def connect(
        self,
        websocket: WebSocket,
        execution_id: str,
        *,
        tenant_id: str | None = None,
        last_event_id: str | None = None,
    ) -> None:
        """Accept *websocket* and subscribe it to *execution_id* events.

        If *last_event_id* is supplied, missed events are replayed:
        - First from the in-memory buffer (fast, survives only server lifetime)
        - Then from the Redis stream (durable, survives restarts)

        A background heartbeat task is started for every connection.
        """
        await websocket.accept()

        self._connections.setdefault(execution_id, []).append(websocket)

        if tenant_id:
            self._tenant_rooms.setdefault(tenant_id, set()).add(execution_id)
            self._connection_tenants[id(websocket)] = tenant_id

        meta = _ConnMeta(websocket, execution_id, tenant_id)
        self._connection_meta[id(websocket)] = meta

        logger.info(
            "websocket.connect",
            extra={"execution_id": execution_id, "tenant_id": tenant_id or ""},
        )

        # Replay missed events before resuming live stream
        if last_event_id is not None:
            await self._replay(websocket, execution_id, last_event_id)

        # Start server-side heartbeat
        meta._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(websocket, execution_id),
            name=f"ws-hb-{execution_id}-{id(websocket)}",
        )

    async def disconnect(
        self,
        websocket: WebSocket,
        execution_id: str,
    ) -> None:
        """Unregister *websocket* and cancel its heartbeat task."""
        meta = self._connection_meta.pop(id(websocket), None)
        if meta and meta._heartbeat_task:
            meta._heartbeat_task.cancel()

        tenant_id = self._connection_tenants.pop(id(websocket), None)

        conns = self._connections.get(execution_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(execution_id, None)
            if tenant_id:
                room = self._tenant_rooms.get(tenant_id)
                if room:
                    room.discard(execution_id)
                    if not room:
                        self._tenant_rooms.pop(tenant_id, None)

        logger.info(
            "websocket.disconnect",
            extra={"execution_id": execution_id, "tenant_id": tenant_id or ""},
        )

    # ── Broadcast ────────────────────────────────────────────────────────────

    async def broadcast(
        self,
        execution_id: str,
        event_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Build, persist, and broadcast an event.

        1. Assign a UUID event_id and ISO timestamp.
        2. Store in Redis stream (XADD execution:{execution_id}) — best-effort.
        3. Store in in-memory ring buffer for fast replay.
        4. Fan-out to all connected WebSockets for the execution.
        """
        event: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "type": event_type,
            "timestamp": _now_iso(),
            "data": data,
        }
        serialised = json.dumps(event)

        # Persist to Redis stream and in-memory buffer
        await self._xadd(execution_id, event, serialised)
        self._buffer(execution_id, event["event_id"], serialised)

        # Fan-out
        conns = list(self._connections.get(execution_id, []))
        if tenant_id:
            conns = [
                ws for ws in conns if self._connection_tenants.get(id(ws)) == tenant_id
            ]

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(serialised)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws, execution_id)

    async def send_event(
        self,
        execution_id: str,
        event_type: str,
        data: dict[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Alias for :meth:`broadcast` — backward compatible with ConnectionManager."""
        await self.broadcast(execution_id, event_type, data, tenant_id=tenant_id)

    # ── Client message handling ───────────────────────────────────────────────

    async def handle_client_message(
        self,
        websocket: WebSocket,
        execution_id: str,
        raw_message: str,
    ) -> None:
        """Process an inbound client message.

        Handles:
        - ``{"type": "pong"}``                        — updates pong timestamp
        - ``{"type": "ping"}``                        — replies with pong
        - ``{"type": "reconnect", "last_event_id": "..."}`` — triggers replay
        """
        try:
            msg: dict[str, Any] = json.loads(raw_message)
        except (json.JSONDecodeError, ValueError):
            return

        msg_type = msg.get("type", "")

        if msg_type == "pong":
            meta = self._connection_meta.get(id(websocket))
            if meta:
                meta.last_pong_received = _now_iso()

        elif msg_type == "ping":
            # Client-initiated ping — reply immediately
            try:
                await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception:
                pass

        elif msg_type == "reconnect":
            last_event_id = msg.get("last_event_id")
            if last_event_id:
                await self._replay(websocket, execution_id, last_event_id)

    # ── Tenant helpers ────────────────────────────────────────────────────────

    def get_tenant_executions(self, tenant_id: str) -> set[str]:
        """Return execution IDs active for a tenant."""
        return set(self._tenant_rooms.get(tenant_id, set()))

    def get_buffered_event_count(self, execution_id: str) -> int:
        """Return number of events in the in-memory buffer for *execution_id*."""
        buf = self._event_buffer.get(execution_id)
        return len(buf) if buf else 0

    def clear_event_buffer(self, execution_id: str) -> None:
        """Drop the in-memory buffer for a completed execution."""
        self._event_buffer.pop(execution_id, None)

    # ── Heartbeat ────────────────────────────────────────────────────────────

    async def _heartbeat_loop(
        self,
        websocket: WebSocket,
        execution_id: str,
    ) -> None:
        """Send a ping every ``_HEARTBEAT_INTERVAL`` seconds.

        If no pong arrives within ``_PONG_TIMEOUT`` seconds the connection
        is forcibly disconnected with WebSocket close code 1008.
        """
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)

                meta = self._connection_meta.get(id(websocket))
                if meta is None:
                    break

                now = _now_iso()
                meta.last_ping_sent = now
                ping_msg = json.dumps({"type": "ping", "timestamp": now})

                try:
                    await websocket.send_text(ping_msg)
                except Exception:
                    await self.disconnect(websocket, execution_id)
                    break

                # Wait for pong
                try:
                    await asyncio.wait_for(
                        self._wait_for_pong(websocket, now),
                        timeout=_PONG_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "websocket.pong_timeout",
                        extra={"execution_id": execution_id},
                    )
                    await self.disconnect(websocket, execution_id)
                    try:
                        await websocket.close(code=1008)
                    except Exception:
                        pass
                    break

        except asyncio.CancelledError:
            pass  # Normal teardown

    async def _wait_for_pong(self, websocket: WebSocket, ping_time: str) -> None:
        """Block until a pong is received after ``ping_time``."""
        while True:
            await asyncio.sleep(1)
            meta = self._connection_meta.get(id(websocket))
            if meta is None:
                return
            if meta.last_pong_received and meta.last_pong_received >= ping_time:
                return

    # ── In-memory ring buffer ─────────────────────────────────────────────────

    def _buffer(
        self,
        execution_id: str,
        event_id: str,
        serialised: str,
    ) -> None:
        if execution_id not in self._event_buffer:
            self._event_buffer[execution_id] = deque(maxlen=_EVENT_BUFFER_SIZE)
        self._event_buffer[execution_id].append(_BufferedEvent(event_id, serialised))

    async def _replay(
        self,
        websocket: WebSocket,
        execution_id: str,
        last_event_id: str,
    ) -> None:
        """Replay events after *last_event_id* — in-memory first, then Redis."""
        replayed = await self._replay_from_buffer(
            websocket, execution_id, last_event_id
        )
        if not replayed:
            # Buffer was empty or last_event_id predates it — try Redis
            await self._replay_from_redis(websocket, execution_id, last_event_id)

    async def _replay_from_buffer(
        self,
        websocket: WebSocket,
        execution_id: str,
        last_event_id: str,
    ) -> int:
        """Send buffered events after *last_event_id*. Returns count replayed."""
        buffer = self._event_buffer.get(execution_id)
        if not buffer:
            return 0

        found = False
        count = 0
        for evt in buffer:
            if evt.event_id == last_event_id:
                found = True
                continue
            if found:
                try:
                    await websocket.send_text(evt.serialised)
                    count += 1
                except Exception:
                    break

        # If event not found in buffer, replay all (client is behind the buffer)
        if not found and buffer:
            for evt in buffer:
                try:
                    await websocket.send_text(evt.serialised)
                    count += 1
                except Exception:
                    break

        if count:
            logger.info(
                "websocket.replay_buffer",
                extra={"execution_id": execution_id, "replayed": count},
            )
        return count

    # ── Redis Streams ─────────────────────────────────────────────────────────

    async def _xadd(
        self,
        execution_id: str,
        event: dict[str, Any],
        serialised: str,
    ) -> None:
        """Append *event* to the Redis stream. Errors are silently absorbed."""
        from app.websocket.redis_client import get_redis

        redis = await get_redis()
        if redis is None:
            return
        key = _stream_key(execution_id)
        try:
            await redis.xadd(
                key,
                {"event_json": serialised},
                maxlen=_STREAM_MAXLEN,
                approximate=True,
            )
            await redis.expire(key, _STREAM_TTL_SECONDS)
        except Exception as exc:
            logger.warning("redis.xadd failed for %s: %s", execution_id, exc)

    async def _replay_from_redis(
        self,
        websocket: WebSocket,
        execution_id: str,
        last_event_id: str,
    ) -> int:
        """Read the Redis stream and send events after *last_event_id*."""
        from app.websocket.redis_client import get_redis

        redis = await get_redis()
        if redis is None:
            return 0

        key = _stream_key(execution_id)
        try:
            entries: list[tuple[str, dict[str, str]]] = await redis.xrange(
                key, count=_STREAM_MAXLEN
            )
        except Exception as exc:
            logger.warning("redis.xrange failed for %s: %s", execution_id, exc)
            return 0

        found = False
        count = 0
        for _sid, fields in entries:
            raw = fields.get("event_json", "")
            if not raw:
                continue
            try:
                evt: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if found:
                try:
                    await websocket.send_json(evt)
                    count += 1
                except Exception:
                    break
            elif evt.get("event_id") == last_event_id:
                found = True

        if count:
            logger.info(
                "websocket.replay_redis",
                extra={"execution_id": execution_id, "replayed": count},
            )
        return count


# ── Legacy ConnectionManager ──────────────────────────────────────────────────


class ConnectionManager:
    """Lightweight WebSocket connection manager (legacy).

    Kept for backward compatibility.  Prefer :class:`ExecutionStreamManager`
    for new code — it adds Redis persistence, replay, and heartbeat.
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
        """Accept and register a WebSocket for the given execution."""
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
        data: dict[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> None:
        """Broadcast a JSON event to all connections for an execution."""
        from datetime import datetime, timezone

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
                ws for ws in conns if self._connection_tenants.get(id(ws)) == tenant_id
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
