"""REST event API tests — Phase 1 / Phase 5 visibility surface (WS5).

These tests exercise the routes registered in ``app/routes/events.py``:

* ``GET /api/v1/workflow-runs/{run_id}/events``
* ``GET /api/v1/executions/{run_id}/events`` (alias)
* ``GET /api/v1/workflow-runs/{run_id}/events/verify``
* ``GET /api/v1/workflow-runs``

Test infrastructure
-------------------
* In-memory aiosqlite engine spun up per-test (matching the
  ``test_db_durability.py`` pattern). The engine is wired into the live
  FastAPI app via ``app.dependency_overrides[get_session]`` so the routes
  use the per-test database.
* Auth is monkey-patched via ``app.dependency_overrides[get_current_user]``
  so tests can present admin / tenant-scoped users without minting JWTs.
* Events are seeded by calling :func:`event_service.append_event` directly
  against the per-test sync session — keeping the hash chain deterministic
  and matching the production write path.

The orchestrator's command sets ``ARCHON_DATABASE_URL=sqlite+aiosqlite:///``
on the env, but the existing ``app/database.py`` raises ``TypeError`` on
sqlite (W1.1 work item). These tests therefore manage their own engine
end-to-end and do not depend on ``app.database.engine``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Importing all models so SQLModel.metadata is fully populated before
# create_all (cross-model FKs would otherwise fail at table creation).
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
    """Per-test async aiosqlite engine with all tables created."""
    engine = create_async_engine(_SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture()
def sync_engine():
    """Per-test sync sqlite engine for seeding via ``append_event``.

    The sync engine reuses an in-memory database via the special
    ``file::memory:?cache=shared`` URI so the async engine can see
    fixtures inserted through it. We avoid that complexity by using
    *separate* engines and seeding via the same async engine when
    needed; this fixture is provided for tests that want sync access.
    """
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest_asyncio.fixture()
async def seeded_app(async_engine):
    """FastAPI app with ``get_session`` and ``get_current_user`` overridden.

    Yields ``(client, factory, user_overrider)`` where:

    * ``client`` is a ``TestClient(app)`` ready to issue HTTP calls
    * ``factory`` returns an ``AsyncSession`` against the per-test engine
      so the test can persist runs/events directly
    * ``user_overrider(user)`` swaps the authenticated user; default is
      an admin so the route is accessible without further setup.
    """
    from app.database import get_session
    from app.interfaces.models.enterprise import AuthenticatedUser
    from app.main import app
    from app.middleware.auth import get_current_user

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

    current_user = {"value": default_user}

    async def _override_user():
        return current_user["value"]

    def overrider(user: AuthenticatedUser) -> None:
        current_user["value"] = user

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    try:
        client = TestClient(app)
        yield client, factory, overrider
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_user, None)


# ── Seeding helpers ────────────────────────────────────────────────────


async def _seed_run(
    factory: Any,
    *,
    tenant_id: UUID | None = None,
    workflow_id: UUID | None = None,
    agent_id: UUID | None = None,
    status: str = "running",
    kind: str | None = None,
    created_at: datetime | None = None,
) -> WorkflowRun:
    """Insert a WorkflowRun with the supplied (workflow_id|agent_id) XOR.

    Either workflow_id or agent_id is set; if neither is provided, a
    fresh workflow is created so the FK is satisfied. The model has a
    DB-level XOR check so we cannot leave both null.
    """
    async with factory() as session:
        if workflow_id is None and agent_id is None:
            wf = Workflow(name=f"wf-{uuid4().hex[:6]}", steps=[], graph_definition={})
            session.add(wf)
            await session.commit()
            await session.refresh(wf)
            workflow_id = wf.id
            kind = kind or "workflow"
        elif workflow_id is not None:
            kind = kind or "workflow"
        else:
            kind = kind or "agent"

        run = WorkflowRun(
            kind=kind,
            workflow_id=workflow_id,
            agent_id=agent_id,
            tenant_id=tenant_id,
            status=status,
            definition_snapshot={"_test": "seeded"},
            triggered_by="test",
        )
        if created_at is not None:
            run.created_at = (
                created_at.replace(tzinfo=None)
                if created_at.tzinfo is not None
                else created_at
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
    """Append a sequence of events using the production helper.

    ``append_event`` is a sync API; to drive it against the test's async
    engine we ``run_sync`` a callable that opens a sync session, appends
    each event, and commits. This matches the production transactional
    pattern (one append per transaction).
    """

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


# ── Tests: GET /workflow-runs/{run_id}/events ──────────────────────────


@pytest.mark.asyncio
async def test_get_run_events_returns_chronological_order(seeded_app, async_engine):
    """Events come back ordered by sequence (ascending)."""
    client, factory, _ = seeded_app
    run = await _seed_run(factory)
    await _seed_events(
        async_engine,
        run.id,
        [
            ("run.created", {"workflow_id": str(uuid4())}),
            ("run.queued", {}),
            ("run.started", {}),
            ("step.started", {"step_id": "s1", "name": "first"}),
            ("step.completed", {"step_id": "s1", "duration_ms": 12}),
            ("run.completed", {"duration_ms": 42}),
        ],
    )

    resp = client.get(f"/api/v1/workflow-runs/{run.id}/events")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == str(run.id)
    sequences = [e["sequence"] for e in body["events"]]
    assert sequences == [0, 1, 2, 3, 4, 5]
    types = [e["event_type"] for e in body["events"]]
    assert types == [
        "run.created",
        "run.queued",
        "run.started",
        "step.started",
        "step.completed",
        "run.completed",
    ]
    assert body["chain_verified"] is True
    assert body["next_after_sequence"] is None  # all events fit in one page


@pytest.mark.asyncio
async def test_get_run_events_filters_by_event_types(seeded_app, async_engine):
    """``event_types`` CSV restricts the visible payload."""
    client, factory, _ = seeded_app
    run = await _seed_run(factory)
    await _seed_events(
        async_engine,
        run.id,
        [
            ("run.created", {}),
            ("step.started", {"step_id": "s1"}),
            ("step.failed", {"step_id": "s1", "error": "boom"}),
            ("run.failed", {"error": "boom"}),
        ],
    )

    resp = client.get(
        f"/api/v1/workflow-runs/{run.id}/events",
        params={"event_types": "step.failed,run.failed"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = [e["event_type"] for e in body["events"]]
    assert types == ["step.failed", "run.failed"]
    # Chain verification still ran across the unfiltered window.
    assert body["chain_verified"] is True


@pytest.mark.asyncio
async def test_get_run_events_paginates_via_after_sequence(seeded_app, async_engine):
    """``after_sequence`` + ``limit`` paginate forward without skipping rows."""
    client, factory, _ = seeded_app
    run = await _seed_run(factory)
    pairs = [("run.created", {})]
    pairs += [("step.started", {"step_id": f"s{i}"}) for i in range(9)]
    await _seed_events(async_engine, run.id, pairs)

    page1 = client.get(
        f"/api/v1/workflow-runs/{run.id}/events",
        params={"limit": 4},
    ).json()
    seqs1 = [e["sequence"] for e in page1["events"]]
    assert seqs1 == [0, 1, 2, 3]
    assert page1["next_after_sequence"] == 3

    page2 = client.get(
        f"/api/v1/workflow-runs/{run.id}/events",
        params={"limit": 4, "after_sequence": 3},
    ).json()
    seqs2 = [e["sequence"] for e in page2["events"]]
    assert seqs2 == [4, 5, 6, 7]

    page3 = client.get(
        f"/api/v1/workflow-runs/{run.id}/events",
        params={"limit": 4, "after_sequence": 7},
    ).json()
    seqs3 = [e["sequence"] for e in page3["events"]]
    assert seqs3 == [8, 9]
    assert page3["next_after_sequence"] is None


@pytest.mark.asyncio
async def test_get_run_events_chain_verified_true_for_clean_chain(seeded_app, async_engine):
    """A pristine, contiguous chain returns ``chain_verified=true``."""
    client, factory, _ = seeded_app
    run = await _seed_run(factory)
    await _seed_events(
        async_engine,
        run.id,
        [
            ("run.created", {"k": "v"}),
            ("run.started", {}),
            ("run.completed", {"duration_ms": 1}),
        ],
    )
    resp = client.get(f"/api/v1/workflow-runs/{run.id}/events")
    assert resp.status_code == 200
    assert resp.json()["chain_verified"] is True


@pytest.mark.asyncio
async def test_get_run_events_chain_verified_false_after_payload_tamper(
    seeded_app, async_engine
):
    """Mutating a row's payload after insert flips ``chain_verified=false``.

    This is the canonical tamper test: write a clean chain, mutate one
    event's payload directly via SQL, and then assert that the integrity
    check now reports the corruption.
    """
    client, factory, _ = seeded_app
    run = await _seed_run(factory)
    await _seed_events(
        async_engine,
        run.id,
        [
            ("run.created", {"original": True}),
            ("run.started", {}),
            ("run.completed", {"duration_ms": 1}),
        ],
    )

    # Tamper: rewrite the payload of sequence=1 directly.
    factory_ = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory_() as session:
        from sqlmodel import select

        stmt = select(WorkflowRunEvent).where(
            (WorkflowRunEvent.run_id == run.id)
            & (WorkflowRunEvent.sequence == 1)
        )
        result = await session.exec(stmt)
        target = result.first()
        assert target is not None
        # Mutate a hashed field — payload — without recomputing the hash.
        target.payload = {"tampered": "yes"}
        session.add(target)
        await session.commit()

    resp = client.get(f"/api/v1/workflow-runs/{run.id}/events")
    assert resp.status_code == 200
    body = resp.json()
    assert body["chain_verified"] is False, body

    # The dedicated verify endpoint should pinpoint the corrupted row.
    verify = client.get(
        f"/api/v1/workflow-runs/{run.id}/events/verify"
    ).json()
    assert verify["chain_verified"] is False
    assert verify["first_corruption_at_sequence"] == 1
    print(
        "TAMPER VERIFY OUTPUT:",
        {
            "chain_verified": verify["chain_verified"],
            "first_corruption_at_sequence": verify["first_corruption_at_sequence"],
        },
    )


@pytest.mark.asyncio
async def test_get_run_events_404_when_run_not_in_workflow_runs(seeded_app):
    """Unknown ``run_id`` returns 404 with no row leakage."""
    client, _factory, _ = seeded_app
    resp = client.get(f"/api/v1/workflow-runs/{uuid4()}/events")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_events_tenant_scoped(seeded_app, async_engine):
    """Tenant B sees a 404 (not 403) for tenant A's run.

    Returning 404 prevents existence leakage of cross-tenant rows.
    """
    from app.interfaces.models.enterprise import AuthenticatedUser

    client, factory, set_user = seeded_app
    tenant_a = uuid4()
    tenant_b = uuid4()
    run_a = await _seed_run(factory, tenant_id=tenant_a)
    await _seed_events(async_engine, run_a.id, [("run.created", {})])

    set_user(
        AuthenticatedUser(
            id=str(uuid4()),
            email="b@archon.test",
            tenant_id=str(tenant_b),
            roles=["operator"],
        )
    )
    resp = client.get(f"/api/v1/workflow-runs/{run_a.id}/events")
    assert resp.status_code == 404, resp.text


# ── Tests: alias /executions/{run_id}/events ──────────────────────────


@pytest.mark.asyncio
async def test_executions_alias_endpoint_returns_same_payload(
    seeded_app, async_engine
):
    """The legacy alias yields the same body shape (sans request_id) as the canonical route."""
    client, factory, _ = seeded_app
    run = await _seed_run(factory)
    await _seed_events(
        async_engine,
        run.id,
        [("run.created", {}), ("run.completed", {"duration_ms": 1})],
    )

    canonical = client.get(f"/api/v1/workflow-runs/{run.id}/events").json()
    alias = client.get(f"/api/v1/executions/{run.id}/events").json()

    # ``meta.request_id`` differs between calls; strip before comparing.
    canonical.pop("meta", None)
    alias.pop("meta", None)
    assert canonical == alias


# ── Tests: GET /workflow-runs (list) ──────────────────────────────────


@pytest.mark.asyncio
async def test_workflow_runs_list_paginates_with_cursor(seeded_app, async_engine):
    """Cursor pagination walks the run history newest-first without dups."""
    client, factory, _ = seeded_app
    times = [
        datetime(2026, 4, 1, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 2, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 3, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 4, 10, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 5, 10, 0, 0, tzinfo=timezone.utc),
    ]
    runs: list[WorkflowRun] = []
    for created_at in times:
        runs.append(await _seed_run(factory, created_at=created_at))

    page1 = client.get("/api/v1/workflow-runs", params={"limit": 2}).json()
    ids1 = [r["id"] for r in page1["items"]]
    assert len(ids1) == 2
    assert page1["next_cursor"] is not None

    page2 = client.get(
        "/api/v1/workflow-runs",
        params={"limit": 2, "cursor": page1["next_cursor"]},
    ).json()
    ids2 = [r["id"] for r in page2["items"]]
    assert len(ids2) == 2
    assert not set(ids1) & set(ids2), "page2 leaked rows from page1"

    page3 = client.get(
        "/api/v1/workflow-runs",
        params={"limit": 2, "cursor": page2["next_cursor"]},
    ).json()
    ids3 = [r["id"] for r in page3["items"]]
    assert len(ids3) == 1, page3
    assert page3["next_cursor"] is None


@pytest.mark.asyncio
async def test_workflow_runs_list_filters_by_status_and_kind(
    seeded_app, async_engine
):
    """``status`` and ``kind`` filters narrow the response correctly."""
    client, factory, _ = seeded_app
    await _seed_run(factory, status="running", kind="workflow")
    await _seed_run(factory, status="completed", kind="workflow")
    await _seed_run(factory, status="failed", kind="workflow")
    # An agent-kind run.
    from app.models import Agent, User

    async with factory() as session:
        owner = User(
            email=f"o-{uuid4().hex[:6]}@archon.test", name="o"
        )
        session.add(owner)
        await session.commit()
        await session.refresh(owner)
        ag = Agent(name="t-ag", definition={}, owner_id=owner.id)
        session.add(ag)
        await session.commit()
        await session.refresh(ag)
    await _seed_run(factory, agent_id=ag.id, status="running", kind="agent")

    resp = client.get(
        "/api/v1/workflow-runs",
        params={"status": "running", "kind": "workflow"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "running"
    assert body["items"][0]["kind"] == "workflow"

    # Filtering by kind="agent" surfaces the agent-kind run only.
    resp_agent = client.get(
        "/api/v1/workflow-runs", params={"kind": "agent"}
    ).json()
    assert len(resp_agent["items"]) == 1
    assert resp_agent["items"][0]["kind"] == "agent"


# ── Sanity: route registration ─────────────────────────────────────────


def test_events_routes_registered_in_app() -> None:
    """All four REST endpoints + the WS route are wired into the app."""
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/workflow-runs/{run_id}/events" in paths
    assert "/api/v1/executions/{run_id}/events" in paths
    assert "/api/v1/workflow-runs/{run_id}/events/verify" in paths
    assert "/api/v1/workflow-runs" in paths
    assert "/ws/workflow-runs/{run_id}/events" in paths
