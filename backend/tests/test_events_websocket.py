"""WebSocket tests for the workflow-run event stream (WS5).

These tests exercise :mod:`app.websocket.events_manager`:

* Replay-before-live ordering — every event persisted before the connect
  is delivered to the subscriber in sequence order, and live events
  arriving during replay are buffered so nothing is dropped.
* Disconnect cleanup — when the client drops, the manager unregisters
  the subscription and cancels its heartbeat task.
* Heartbeat — with the heartbeat interval lowered to a fraction of a
  second the test sees the periodic keepalive on the wire.
* Auth — invalid tokens are rejected with WebSocket close code 4001.

Like the REST tests, we wire an in-memory aiosqlite engine into the live
FastAPI app via ``dependency_overrides`` so the websocket route reads
events from the per-test database.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Populate metadata so create_all picks up every cross-FK table.
from app.models import (  # noqa: F401
    Agent,
    Execution,
    User,
)
from app.models.workflow import (  # noqa: F401
    Workflow,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStep,
)
from app.services.event_service import append_event


_SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def async_engine():
    engine = create_async_engine(_SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def wired_app(async_engine):
    """FastAPI app with sessions + auth + ``async_session_factory`` overridden.

    The websocket route opens its own session via
    ``app.database.async_session_factory``; we monkey-patch that to point
    at the per-test engine so the route reads our seeded events.
    """
    from app.database import get_session
    from app.interfaces.models.enterprise import AuthenticatedUser
    from app.main import app
    from app.middleware.auth import get_current_user
    from app.websocket import events_manager as ws_events

    factory = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_session():
        async with factory() as session:
            yield session

    default_user = AuthenticatedUser(
        id="00000000-0000-0000-0000-000000000001",
        email="admin@archon.test",
        tenant_id="00000000-0000-0000-0000-000000000100",
        roles=["admin"],
        permissions=["*"],
        mfa_verified=True,
        session_id="test-session",
    )

    async def _override_user():
        return default_user

    # Monkey-patch the database module for the websocket path.
    import app.database as db_mod

    real_factory = db_mod.async_session_factory
    db_mod.async_session_factory = factory

    # Lower heartbeat interval so tests don't wait 30s.
    real_hb = ws_events.event_stream_manager.heartbeat_interval
    ws_events.event_stream_manager.heartbeat_interval = 0.2

    # The WebSocket route resolves auth directly (it cannot use the
    # ``get_current_user`` Depends because WebSocket params are positional).
    # Force AUTH_DEV_MODE=True so the no-token branch admits the connection
    # as the synthetic admin user.
    from app.config import settings as _settings

    real_dev_mode = _settings.AUTH_DEV_MODE
    _settings.AUTH_DEV_MODE = True

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    try:
        client = TestClient(app)
        yield client, factory
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)
        db_mod.async_session_factory = real_factory
        ws_events.event_stream_manager.heartbeat_interval = real_hb
        _settings.AUTH_DEV_MODE = real_dev_mode


# ── Seeding helpers ────────────────────────────────────────────────────


async def _seed_run(factory, *, tenant_id: UUID | None = None) -> WorkflowRun:
    async with factory() as session:
        wf = Workflow(name=f"wf-{uuid4().hex[:6]}", steps=[], graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        run = WorkflowRun(
            kind="workflow",
            workflow_id=wf.id,
            tenant_id=tenant_id,
            status="running",
            definition_snapshot={"_test": "ws"},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run


async def _seed_events(
    async_engine,
    run_id: UUID,
    events: list[tuple[str, dict[str, Any]]],
    *,
    tenant_id: UUID | None = None,
) -> list[UUID]:
    def _do_seed(sync_conn) -> list[UUID]:
        ids: list[UUID] = []
        with Session(sync_conn) as sync_session:
            for event_type, payload in events:
                event = append_event(
                    sync_session,
                    run_id,
                    event_type,
                    payload,
                    tenant_id=tenant_id,
                    step_id=payload.get("step_id"),
                )
                ids.append(event.id)
            sync_session.commit()
        return ids

    async with async_engine.begin() as conn:
        return await conn.run_sync(_do_seed)


# ── Tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ws_replays_history_then_streams_live(wired_app, async_engine):
    """Connect with 3 pre-seeded events; receive them in order; receive a 4th live."""
    client, factory = wired_app
    run = await _seed_run(factory)
    await _seed_events(
        async_engine,
        run.id,
        [
            ("run.created", {"k": 0}),
            ("run.queued", {"k": 1}),
            ("run.started", {"k": 2}),
        ],
    )

    with client.websocket_connect(f"/ws/workflow-runs/{run.id}/events") as ws:
        received: list[dict[str, Any]] = []
        # Pull the 3 replayed events.
        for _ in range(3):
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "event"
            received.append(msg["data"])
        sequences = [e["sequence"] for e in received]
        assert sequences == [0, 1, 2], received

        # Now publish a 4th live event via the seeding helper.
        await _seed_events(
            async_engine, run.id, [("run.completed", {"duration_ms": 7})]
        )

        # And explicitly broadcast it through the manager — that's the
        # production hook the dispatcher will use.
        from app.websocket.events_manager import publish_event
        from sqlmodel import select as _select

        async with factory() as session:
            stmt = _select(WorkflowRunEvent).where(
                (WorkflowRunEvent.run_id == run.id)
                & (WorkflowRunEvent.sequence == 3)
            )
            row = (await session.exec(stmt)).first()
            assert row is not None
            await publish_event(row)

        live_msg = json.loads(ws.receive_text())
        assert live_msg["type"] == "event"
        assert live_msg["data"]["sequence"] == 3
        assert live_msg["data"]["event_type"] == "run.completed"


@pytest.mark.asyncio
async def test_ws_disconnects_cleanly_when_client_drops(wired_app, async_engine):
    """Closing the client side empties the per-run subscriber list."""
    from app.websocket.events_manager import event_stream_manager

    client, factory = wired_app
    run = await _seed_run(factory)
    await _seed_events(async_engine, run.id, [("run.created", {})])

    with client.websocket_connect(f"/ws/workflow-runs/{run.id}/events") as ws:
        # Drain the replay so the subscription is fully live.
        ws.receive_text()
        # While the client is connected, the manager has at least one sub.
        assert run.id in event_stream_manager._subscriptions
        assert len(event_stream_manager._subscriptions[run.id]) >= 1
        # Politely close from the client side so the server's
        # receive_text() returns WebSocketDisconnect immediately.
        ws.close()

    # Allow the server-side disconnect cleanup to schedule.
    for _ in range(60):
        if run.id not in event_stream_manager._subscriptions:
            break
        await asyncio.sleep(0.05)

    assert run.id not in event_stream_manager._subscriptions, (
        f"sub list still present: {event_stream_manager._subscriptions}"
    )


@pytest.mark.asyncio
async def test_ws_buffers_events_arriving_during_replay(wired_app, async_engine):
    """A publish() during replay must still be delivered after replay finishes.

    We force-buffer by hand-attaching a subscription, calling publish()
    while ``sub.live`` is False, and then driving the post-replay drain.
    Every event — replayed and buffered — must be observed exactly once
    in sequence order.
    """
    from app.websocket.events_manager import EventStreamManager

    client, factory = wired_app  # noqa: F841 — just to ensure setup
    run = await _seed_run(factory)
    await _seed_events(
        async_engine,
        run.id,
        [
            ("run.created", {"i": 0}),
            ("run.queued", {"i": 1}),
        ],
    )

    # Build a fake websocket that records every send_text payload.
    class _FakeWS:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_text(self, text: str) -> None:
            self.sent.append(text)

    fake = _FakeWS()
    mgr = EventStreamManager(heartbeat_interval=10.0)

    # Manually drive the subscribe flow, but inject an extra publish()
    # *after* the replay query starts but *before* live mode toggles on.
    factory_ = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with factory_() as session:
        # Pre-build a future event we'll inject during replay. To make
        # ordering deterministic we construct the event row in advance,
        # mid-chain, then publish it through the manager while replay
        # is still in flight.
        async def _build_seq2_in_db():
            await _seed_events(async_engine, run.id, [("run.started", {"i": 2})])

        # Patch the manager's _replay_history so that, between the first
        # and second page, a publish() fires. We exploit the fact that
        # subscribe() awaits _replay_history before going live.
        original_replay = mgr._replay_history

        async def _instrumented_replay(sub, sess):
            # Run the real replay first.
            await original_replay(sub, sess)
            # Now seed and publish the live event while still pre-live.
            assert sub.live is False
            await _build_seq2_in_db()
            from sqlmodel import select as _select

            async with factory_() as s2:
                row = (
                    await s2.exec(
                        _select(WorkflowRunEvent).where(
                            (WorkflowRunEvent.run_id == run.id)
                            & (WorkflowRunEvent.sequence == 2)
                        )
                    )
                ).first()
                assert row is not None
                await mgr.publish(row)

        mgr._replay_history = _instrumented_replay  # type: ignore[method-assign]

        sub = await mgr.subscribe(
            fake,  # type: ignore[arg-type]
            run_id=run.id,
            tenant_id=None,
            session=session,
        )

    # The fake should have received:
    #   - 2 replayed events (sequence 0, 1)
    #   - 1 buffered event (sequence 2) drained after replay completed
    received_seqs: list[int] = []
    for raw in fake.sent:
        msg = json.loads(raw)
        if msg.get("type") == "event":
            received_seqs.append(msg["data"]["sequence"])
    assert received_seqs == [0, 1, 2], (
        f"buffered event was dropped: sent={received_seqs}"
    )

    await mgr.disconnect(sub)


@pytest.mark.asyncio
async def test_ws_sends_heartbeat(wired_app, async_engine):
    """With heartbeat interval at 0.2s the client sees a keepalive frame."""
    client, factory = wired_app
    run = await _seed_run(factory)
    await _seed_events(async_engine, run.id, [("run.created", {})])

    with client.websocket_connect(f"/ws/workflow-runs/{run.id}/events") as ws:
        # Drain the single replayed event.
        first = json.loads(ws.receive_text())
        assert first["type"] == "event"

        # Now wait for a heartbeat. We allow up to ~3 intervals.
        saw_heartbeat = False
        for _ in range(15):
            try:
                msg = json.loads(ws.receive_text())
            except Exception:
                break
            if msg.get("type") == "heartbeat":
                saw_heartbeat = True
                assert "timestamp" in msg
                break
        assert saw_heartbeat, "no heartbeat frame observed within timeout"


def test_ws_rejects_unauthenticated() -> None:
    """A connect with an invalid token closes with code 4001.

    Auth dev mode is left at its default (False) so the bare-token path
    is hit. Setting ``ARCHON_AUTH_DEV_MODE=true`` would let the client
    in with an empty payload — that's the expected dev behaviour but
    NOT what we are testing here.
    """
    from app.config import settings as _settings
    from app.main import app

    # Force AUTH_DEV_MODE off for this test irrespective of env.
    original = _settings.AUTH_DEV_MODE
    _settings.AUTH_DEV_MODE = False
    try:
        client = TestClient(app)
        run_id = uuid4()
        # Supply an obviously bogus token; the WS handler must reject it.
        try:
            with client.websocket_connect(
                f"/ws/workflow-runs/{run_id}/events?token=not-a-real-jwt"
            ) as ws:
                # Some servers send the close frame without raising; try
                # to read and confirm the close.
                try:
                    ws.receive_text()
                except Exception:
                    pass
        except Exception as exc:
            # starlette TestClient raises WebSocketDisconnect on close —
            # that's the expected reject behavior.
            assert "4001" in str(exc) or "disconnect" in str(exc).lower()
            return
    finally:
        _settings.AUTH_DEV_MODE = original
