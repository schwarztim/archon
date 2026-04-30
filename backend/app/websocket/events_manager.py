"""Real-time WebSocket broker for ``workflow_run_events``.

This is the live-stream companion to the REST events API in
``app/routes/events.py``. Together they implement Phase 1 / Phase 5 of the
master plan: a completed run can be reconstructed from history without
having held a live WebSocket open during the run.

Design (per WS5 mission):

* :class:`EventStreamManager` is a publish-subscribe broker keyed by
  ``run_id``. Subscribers receive events for a single run only.
* When a websocket subscribes, the manager **first replays** every event
  that already exists for the run (by ``sequence`` ascending), then
  switches to **live** mode. Events that arrive *during* the replay are
  buffered and flushed before live streaming begins, so nothing is dropped.
* :func:`publish_event` is a module-level convenience for callers (the
  dispatcher / event-service emitters) that have already persisted a
  :class:`WorkflowRunEvent`. The publish path NEVER calls ``append_event``
  — it only fans out.
* Heartbeats: a 30-second server ping (named ``heartbeat``) keeps proxies
  alive and lets clients detect dead sockets. The interval is overridable
  for tests via :class:`EventStreamManager.heartbeat_interval`.
* Authentication mirrors ``app/websocket/routes.py`` — JWT in the
  ``?token=`` query param. No token = treated as anonymous; routes can
  enforce auth more strictly when ``ARCHON_AUTH_DEV_MODE`` is false.

The manager does NOT touch ``app.websocket.manager`` (that is the legacy
execution-stream broker for W1.2). This is a parallel surface.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.models.workflow import WorkflowRun, WorkflowRunEvent

logger = logging.getLogger(__name__)


_DEFAULT_HEARTBEAT_INTERVAL = 30.0  # seconds
_REPLAY_PAGE_SIZE = 500


def _utcnow_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _serialise_event(event: WorkflowRunEvent) -> dict[str, Any]:
    """Render a WorkflowRunEvent as the wire-format dict.

    Mirrors the REST shape so REST + WebSocket clients can use one
    deserialiser.
    """
    return {
        "id": str(event.id),
        "run_id": str(event.run_id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": event.payload,
        "tenant_id": str(event.tenant_id) if event.tenant_id else None,
        "correlation_id": event.correlation_id,
        "span_id": event.span_id,
        "step_id": event.step_id,
        "prev_hash": event.prev_hash,
        "current_hash": event.current_hash,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


# ── Subscription metadata ──────────────────────────────────────────────


class _Subscription:
    """Per-websocket subscription state.

    During replay, live events arrive into ``buffer``; once replay finishes
    the buffer is drained, ``live`` flips True and subsequent ``publish``
    calls send directly. Sequences already replayed are tracked so we
    never double-deliver an event that arrived between replay-fetch and
    live-attach.
    """

    __slots__ = (
        "websocket",
        "run_id",
        "tenant_id",
        "buffer",
        "live",
        "sent_sequences",
        "lock",
        "heartbeat_task",
        "closed",
    )

    def __init__(
        self,
        websocket: WebSocket,
        run_id: UUID,
        tenant_id: UUID | None,
    ) -> None:
        self.websocket = websocket
        self.run_id = run_id
        self.tenant_id = tenant_id
        self.buffer: deque[WorkflowRunEvent] = deque()
        self.live: bool = False
        self.sent_sequences: set[int] = set()
        self.lock = asyncio.Lock()
        self.heartbeat_task: asyncio.Task[None] | None = None
        self.closed: bool = False


# ── Manager ────────────────────────────────────────────────────────────


class EventStreamManager:
    """Publish-subscribe broker for ``workflow_run_events``.

    The dispatcher and ``event_service.append_event`` emitters call
    :meth:`publish` after persisting an event; subscribers receive only
    events whose ``run_id`` matches their subscription.

    The manager itself never persists. It is the broadcast half of the
    write path.
    """

    def __init__(self, *, heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL) -> None:
        self._subscriptions: dict[UUID, list[_Subscription]] = defaultdict(list)
        self.heartbeat_interval = heartbeat_interval

    # ── Subscribe / disconnect ─────────────────────────────────────────

    async def subscribe(
        self,
        websocket: WebSocket,
        *,
        run_id: UUID,
        tenant_id: UUID | None,
        session: AsyncSession,
    ) -> _Subscription:
        """Register *websocket* and replay history before going live.

        The websocket is assumed to already be ``accept()``ed by the route
        handler. We do replay -> live transition under a per-subscription
        lock so concurrent publishes during replay are not lost.
        """
        sub = _Subscription(websocket, run_id, tenant_id)
        self._subscriptions[run_id].append(sub)

        # Phase 1: replay everything currently persisted.
        await self._replay_history(sub, session)

        # Phase 2: drain anything buffered during replay, then mark live.
        async with sub.lock:
            for event in list(sub.buffer):
                if event.sequence in sub.sent_sequences:
                    continue
                await self._send_event(sub, event)
            sub.buffer.clear()
            sub.live = True

        # Phase 3: start heartbeat.
        sub.heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(sub),
            name=f"events-ws-hb-{run_id}",
        )

        logger.info(
            "events_ws.subscribed",
            extra={
                "run_id": str(run_id),
                "tenant_id": str(tenant_id) if tenant_id else "",
            },
        )
        return sub

    async def disconnect(self, sub: _Subscription) -> None:
        """Detach a subscription and cancel its heartbeat task."""
        sub.closed = True
        if sub.heartbeat_task and not sub.heartbeat_task.done():
            sub.heartbeat_task.cancel()
        subs = self._subscriptions.get(sub.run_id, [])
        if sub in subs:
            subs.remove(sub)
        if not subs:
            self._subscriptions.pop(sub.run_id, None)
        logger.info(
            "events_ws.disconnected", extra={"run_id": str(sub.run_id)}
        )

    # ── Publish (broadcast already-persisted event) ────────────────────

    async def publish(self, event: WorkflowRunEvent) -> None:
        """Fan out *event* to every subscriber for ``event.run_id``.

        The event is assumed to be already persisted by the caller (the
        emitter inside the run-event transaction). The manager NEVER
        writes to the database.
        """
        subs = list(self._subscriptions.get(event.run_id, []))
        for sub in subs:
            async with sub.lock:
                if sub.closed:
                    continue
                if not sub.live:
                    # Replay still in progress — buffer for the post-
                    # replay drain phase.
                    sub.buffer.append(event)
                    continue
                await self._send_event(sub, event)

    # ── Internal helpers ───────────────────────────────────────────────

    async def _replay_history(self, sub: _Subscription, session: AsyncSession) -> None:
        """Page through workflow_run_events by sequence and forward each."""
        offset = 0
        while True:
            stmt = (
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == sub.run_id)
                .order_by(WorkflowRunEvent.sequence.asc())
                .offset(offset)
                .limit(_REPLAY_PAGE_SIZE)
            )
            result = await session.exec(stmt)
            page = result.all()
            if not page:
                break
            for event in page:
                await self._send_event(sub, event)
            if len(page) < _REPLAY_PAGE_SIZE:
                break
            offset += _REPLAY_PAGE_SIZE

    async def _send_event(self, sub: _Subscription, event: WorkflowRunEvent) -> None:
        """Send a single event over the wire (or mark the sub closed)."""
        if sub.closed:
            return
        try:
            await sub.websocket.send_text(
                json.dumps({"type": "event", "data": _serialise_event(event)})
            )
            sub.sent_sequences.add(event.sequence)
        except Exception as exc:  # connection died mid-send
            logger.debug("events_ws.send_failed", extra={"err": str(exc)})
            sub.closed = True

    async def _heartbeat_loop(self, sub: _Subscription) -> None:
        """Periodic server-side keepalive."""
        try:
            while not sub.closed:
                await asyncio.sleep(self.heartbeat_interval)
                if sub.closed:
                    break
                try:
                    await sub.websocket.send_text(
                        json.dumps(
                            {"type": "heartbeat", "timestamp": _utcnow_iso()}
                        )
                    )
                except Exception:
                    sub.closed = True
                    break
        except asyncio.CancelledError:
            pass


# ── Module-level singleton + publish hook ─────────────────────────────


event_stream_manager = EventStreamManager()


async def publish_event(event: WorkflowRunEvent) -> None:
    """Module-level fan-out hook.

    Other parts of the codebase (the run dispatcher, the event service)
    may call this after persisting a ``WorkflowRunEvent`` to surface it
    on connected websockets. We expose this as a free function so callers
    don't need to import the singleton directly.
    """
    await event_stream_manager.publish(event)


# ── WebSocket route ────────────────────────────────────────────────────


router = APIRouter(tags=["events-ws"])

_WS_CLOSE_AUTH_FAILED = 4001


async def _resolve_ws_auth(
    websocket: WebSocket,
) -> tuple[bool, dict[str, Any]]:
    """Resolve the websocket's auth context.

    Returns ``(is_authenticated, payload)``. When ``ARCHON_AUTH_DEV_MODE``
    is true and no token is supplied, an empty payload is returned and
    the connection is treated as the dev-admin user (matching
    ``get_current_user``'s dev bypass). Invalid tokens always reject.
    """
    from app.config import settings as _settings
    from app.websocket.manager import authenticate_websocket

    token = websocket.query_params.get("token")
    if not token:
        if _settings.AUTH_DEV_MODE:
            return True, {
                "sub": "00000000-0000-0000-0000-000000000001",
                "tenant_id": "00000000-0000-0000-0000-000000000100",
            }
        return False, {}

    payload = await authenticate_websocket(websocket, token)
    if payload:
        return True, payload

    # HS256 dev fallback
    try:
        from jose import jwt as jose_jwt  # type: ignore[import]

        decoded: dict[str, Any] = jose_jwt.decode(
            token,
            _settings.JWT_SECRET,
            algorithms=["HS256"],
            options={
                "verify_exp": True,
                "verify_iss": False,
                "verify_aud": False,
            },
        )
        if decoded.get("sub"):
            return True, decoded
    except Exception:
        pass

    return False, {}


def _coerce_tenant(payload: dict[str, Any]) -> UUID | None:
    """Pull a tenant UUID from a JWT payload, tolerating missing/invalid."""
    raw = payload.get("tenant_id") or payload.get("tid")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (ValueError, TypeError):
        return None


@router.websocket("/ws/workflow-runs/{run_id}/events")
async def workflow_run_events_ws(
    websocket: WebSocket,
    run_id: UUID,
    token: str | None = Query(default=None),  # noqa: ARG001 — read via query_params
) -> None:
    """Per-run event stream.

    Auth via cookie or query token. Sends:

    - **replay block:** last N events from DB (newest-last)
    - **live block:** events as they're appended
    - **heartbeat:** every 30s to detect dead clients

    Events arriving during replay are buffered and flushed in order so
    nothing is dropped.
    """
    is_authed, payload = await _resolve_ws_auth(websocket)
    if not is_authed:
        await websocket.accept()
        await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
        return

    tenant_id = _coerce_tenant(payload)

    await websocket.accept()

    # Tenant scope check + run existence: load run, verify tenant match.
    # We use a fresh session so we own its lifecycle for the entire
    # subscription (not just the brief replay).
    from app.database import async_session_factory

    async with async_session_factory() as session:
        run_stmt = select(WorkflowRun).where(WorkflowRun.id == run_id)
        run_row = (await session.exec(run_stmt)).first()
        if run_row is None:
            await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
            return
        if (
            tenant_id is not None
            and run_row.tenant_id is not None
            and run_row.tenant_id != tenant_id
        ):
            await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
            return

        sub = await event_stream_manager.subscribe(
            websocket,
            run_id=run_id,
            tenant_id=tenant_id,
            session=session,
        )

    try:
        # Keep the socket open. Clients may send pongs/pings but the
        # current contract is server-push only; we ignore inbound text.
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except RuntimeError:
                break
    finally:
        await event_stream_manager.disconnect(sub)


__all__ = [
    "EventStreamManager",
    "event_stream_manager",
    "publish_event",
    "router",
    "workflow_run_events_ws",
]


# Cosmetic: the dependency-getter is imported but unused here on the
# normal code path because subscribe() is given an explicit session in
# the websocket route. Keeping it imported documents the module's
# database surface for static-analysis tools.
_ = get_session
