"""Tests for the /executions and /agents/{id}/execute REST surface.

Phase 1 / WS2 (ADR-001/004/006) reshaped these endpoints to route through
``ExecutionFacade.create_run`` so a durable ``WorkflowRun`` row is the
canonical artifact. Tests assert:

  - dispatch_run is called with a WorkflowRun.id (NOT an Execution.id)
  - response payload exposes both ``id`` and the legacy ``execution_id``
    alias for backward compatibility
  - the route writes a ``workflow_runs`` row + run.created/run.queued
    events
  - regression: ``_simulate_execution`` and ``dispatch_run`` import remain
    intact

These tests bootstrap a SQLite engine + AsyncSession factory at module
import time (BEFORE conftest's pool_size+max_overflow trips), then
override ``app.database.async_session_factory`` and the ``get_session``
dependency so the route layer transparently uses the in-memory engine.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

# ── Required env BEFORE any app import. ──────────────────────────────
# ``backend/tests/conftest.py`` imports ``app.database`` at module level
# which builds an engine with pool_size+max_overflow — sqlite-aiosqlite
# rejects those. Use a postgres-shape URL so the import succeeds; the
# test client below overrides the session factory before any route fires.
os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault(
    "ARCHON_DATABASE_URL",
    "postgresql+asyncpg://t:t@localhost/t",
)
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")


# ─────────────────────────────────────────────────────────────────────
# In-process test client + sqlite engine override.
# Cached at module level so multiple tests share the boot cost.
# ─────────────────────────────────────────────────────────────────────


_CLIENT = None  # type: ignore[var-annotated]
_AGENT_ID: UUID | None = None
_TEST_ENGINE = None  # type: ignore[var-annotated]
_TEST_SESSION_FACTORY = None  # type: ignore[var-annotated]


def _bootstrap_client():
    """Build a TestClient with sqlite-backed sessions and a seeded Agent."""
    global _CLIENT, _AGENT_ID, _TEST_ENGINE, _TEST_SESSION_FACTORY
    if _CLIENT is not None and _AGENT_ID is not None:
        return _CLIENT, _AGENT_ID

    import tempfile

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    # Import all models so SQLModel.metadata is fully populated.
    import app.models  # noqa: F401
    import app.models.workflow  # noqa: F401

    # File-backed SQLite avoids the connection-drop fragility of
    # ``:memory:`` engines across multiple TestClient requests. StaticPool
    # keeps a single shared connection so the schema persists between
    # tests in the cached client.
    db_path = os.path.join(
        tempfile.gettempdir(), f"archon_exec_real_{uuid.uuid4().hex[:8]}.db"
    )
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
            await conn.run_sync(SQLModel.metadata.create_all)

    asyncio.run(_setup())

    factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    # Override app.database singletons so route handlers transparently use
    # the in-memory engine. Every consumer that does
    # ``from app.database import async_session_factory`` (e.g. dispatch_run)
    # will see this replacement once the assignment is made.
    import app.database as _dbmod

    _dbmod.engine = engine
    _dbmod.async_session_factory = factory

    async def _override_get_session():
        async with factory() as session:
            yield session

    # Build the FastAPI app under mocked Redis + sqlite-friendly engine.
    from fastapi.testclient import TestClient
    from sqlalchemy.ext.asyncio import (
        create_async_engine as _real_create_async_engine,
    )

    def _sqlite_friendly(url, **kwargs):
        if "sqlite" in str(url):
            kwargs.pop("pool_size", None)
            kwargs.pop("max_overflow", None)
            kwargs.pop("pool_pre_ping", None)
        return _real_create_async_engine(url, **kwargs)

    mock_redis = MagicMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ttl = AsyncMock(return_value=60)
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.ping = AsyncMock(return_value=True)
    mock_redis.aclose = AsyncMock()
    mock_redis.close = AsyncMock()

    with (
        patch(
            "sqlalchemy.ext.asyncio.create_async_engine",
            side_effect=_sqlite_friendly,
        ),
        patch("redis.asyncio.from_url", return_value=mock_redis),
        patch("app.logging_config.setup_logging"),
    ):
        from app.main import create_app
        from app.database import get_session
        from app.middleware.auth import get_current_user
        from app.interfaces.models.enterprise import AuthenticatedUser

        app = create_app()

        # Dependency override so every route gets a session bound to our engine.
        app.dependency_overrides[get_session] = _override_get_session

        # Override auth so tests do not depend on AUTH_DEV_MODE env var
        # being set before conftest's settings is initialised. Yields a
        # synthetic admin user for every request.
        async def _override_user() -> AuthenticatedUser:
            return AuthenticatedUser(
                id="00000000-0000-0000-0000-000000000001",
                email="test@example.com",
                tenant_id="00000000-0000-0000-0000-000000000099",
                roles=["admin"],
            )

        app.dependency_overrides[get_current_user] = _override_user

        from app.middleware.rate_limit import _get_redis as _rl_get_redis
        if hasattr(_rl_get_redis, "_client"):
            del _rl_get_redis._client  # type: ignore[attr-defined]

        # Avoid running the real on_startup which would try Postgres again.
        # Patch init_db to a no-op for the duration of TestClient context.
        with patch("app.database.init_db", new=AsyncMock()):
            client = TestClient(app, raise_server_exceptions=False)
            client.__enter__()  # trigger startup hooks (now no-op DB init)

    # Seed the default User so Agent.owner_id FK passes (the on_startup
    # handler usually does this — it's been patched out, so do it here).
    from app.models import User
    from sqlmodel import select

    async def _seed_default_user():
        async with factory() as session:
            existing = (
                await session.exec(select(User).limit(1))
            ).first()
            if existing is None:
                session.add(
                    User(
                        id=UUID("00000000-0000-0000-0000-000000000001"),
                        email="system@archon.local",
                        name="System",
                        role="admin",
                    )
                )
                await session.commit()

    asyncio.run(_seed_default_user())

    # Provision an Agent up-front (REST call so FK + tenant scoping is real).
    agent_payload = {
        "name": f"facade-route-agent-{uuid.uuid4().hex[:8]}",
        "description": "agent for executions_real tests",
        "definition": {"model": "gpt-3.5-turbo"},
        "tags": ["test"],
    }
    resp = client.post("/api/v1/agents/", json=agent_payload)
    assert resp.status_code in (200, 201), resp.text
    agent_id = UUID((resp.json().get("data") or {}).get("id"))

    _CLIENT = client
    _AGENT_ID = agent_id
    _TEST_ENGINE = engine
    _TEST_SESSION_FACTORY = factory
    return client, agent_id


# ─────────────────────────────────────────────────────────────────────
# Tests for POST /api/v1/execute (legacy convenience alias)
# ─────────────────────────────────────────────────────────────────────


def test_post_execute_calls_dispatch_run():
    """POST /api/v1/execute schedules dispatch_run with the WorkflowRun.id."""
    client, agent_id = _bootstrap_client()

    with (
        patch("app.routes.executions.dispatch_run", new=AsyncMock()),
        patch("app.routes.executions.asyncio.create_task") as mock_create_task,
    ):
        resp = client.post(
            "/api/v1/execute",
            json={"agent_id": str(agent_id), "input_data": {}},
        )
    assert resp.status_code == 201, resp.text
    assert mock_create_task.called, "asyncio.create_task was not called"


def test_post_execute_returns_201_with_execution_id():
    """POST /api/v1/execute returns 201 + execution_id alias on a fresh run."""
    client, agent_id = _bootstrap_client()

    with (
        patch("app.routes.executions.dispatch_run", new=AsyncMock()),
        patch("app.routes.executions.asyncio.create_task"),
    ):
        resp = client.post(
            "/api/v1/execute",
            json={"agent_id": str(agent_id), "input_data": {"prompt": "hello"}},
        )

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "data" in body
    # ADR-006 contract: legacy ``execution_id`` alias surfaced alongside ``id``.
    assert "id" in body["data"] and "execution_id" in body["data"]
    assert body["data"]["id"] == body["data"]["execution_id"]


# ─────────────────────────────────────────────────────────────────────
# Tests for POST /api/v1/executions (canonical entry point)
# ─────────────────────────────────────────────────────────────────────


def test_post_executions_creates_workflow_run_row():
    """Phase 1: POST /executions persists a WorkflowRun (NOT an Execution)."""
    client, agent_id = _bootstrap_client()

    with (
        patch("app.routes.executions.dispatch_run", new=AsyncMock()),
        patch("app.routes.executions.asyncio.create_task"),
    ):
        resp = client.post(
            "/api/v1/executions",
            json={"agent_id": str(agent_id), "input_data": {"k": "v"}},
        )
    assert resp.status_code == 201, resp.text
    run_id = (resp.json().get("data") or {}).get("id")
    assert run_id is not None

    from app.models.workflow import WorkflowRun

    async def _check() -> WorkflowRun | None:
        async with _TEST_SESSION_FACTORY() as session:
            return await session.get(WorkflowRun, UUID(run_id))

    run = asyncio.run(_check())
    assert run is not None, "POST /executions did not persist a WorkflowRun"
    assert run.kind == "agent"
    assert run.agent_id == agent_id
    assert run.workflow_id is None
    assert run.definition_snapshot is not None
    assert run.status == "queued"


def test_post_executions_emits_run_created_and_run_queued_events():
    """Phase 1 + ADR-002: every new run emits sequence-0 + sequence-1 events."""
    client, agent_id = _bootstrap_client()

    with (
        patch("app.routes.executions.dispatch_run", new=AsyncMock()),
        patch("app.routes.executions.asyncio.create_task"),
    ):
        resp = client.post(
            "/api/v1/executions",
            json={"agent_id": str(agent_id), "input_data": {}},
        )
    assert resp.status_code == 201, resp.text
    run_id = UUID((resp.json().get("data") or {}).get("id"))

    from app.models.workflow import WorkflowRunEvent
    from sqlmodel import select

    async def _events() -> list[WorkflowRunEvent]:
        async with _TEST_SESSION_FACTORY() as session:
            stmt = (
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence.asc())
            )
            result = await session.exec(stmt)
            return list(result.all())

    events = asyncio.run(_events())
    types = [e.event_type for e in events]
    assert types == ["run.created", "run.queued"], (
        f"Expected ['run.created','run.queued'], got {types}"
    )


def test_post_executions_response_includes_run_id_and_execution_id_alias():
    """Phase 1 contract: response carries id, execution_id (alias), run_id, kind."""
    client, agent_id = _bootstrap_client()

    with (
        patch("app.routes.executions.dispatch_run", new=AsyncMock()),
        patch("app.routes.executions.asyncio.create_task"),
    ):
        resp = client.post(
            "/api/v1/executions",
            json={"agent_id": str(agent_id), "input_data": {}},
        )
    assert resp.status_code == 201, resp.text
    data = (resp.json() or {}).get("data") or {}

    assert "id" in data and "execution_id" in data
    assert data["id"] == data["execution_id"]
    assert data.get("run_id") == data["id"]
    assert data.get("kind") == "agent"


def test_post_agents_id_execute_passes_workflow_run_id_not_execution_id_to_dispatcher():
    """Conflict 9 fix: agents/{id}/execute hands dispatch_run a WorkflowRun.id."""
    client, agent_id = _bootstrap_client()

    with (
        patch("app.routes.agents.dispatch_run", new=AsyncMock()),
        patch("app.routes.agents.asyncio.create_task") as mock_create_task,
    ):
        resp = client.post(
            f"/api/v1/agents/{agent_id}/execute",
            json={"input": {"msg": "hi"}, "config_overrides": {}},
        )
    assert resp.status_code in (200, 201), resp.text
    body = (resp.json() or {}).get("data") or {}
    rid = body.get("execution_id")
    assert rid is not None

    from app.models import Execution
    from app.models.workflow import WorkflowRun

    async def _check() -> dict[str, Any]:
        async with _TEST_SESSION_FACTORY() as session:
            wr = await session.get(WorkflowRun, UUID(rid))
            ex = await session.get(Execution, UUID(rid))
            return {"workflow_run": wr, "execution": ex}

    out = asyncio.run(_check())
    assert out["workflow_run"] is not None, (
        "Conflict 9: agents/{id}/execute did not persist a WorkflowRun"
    )
    assert out["execution"] is None, (
        "Conflict 9: legacy Execution row should NOT be created"
    )
    assert mock_create_task.called


# ─────────────────────────────────────────────────────────────────────
# Static guards retained from the original test file.
# ─────────────────────────────────────────────────────────────────────


def test_simulate_execution_removed():
    """_simulate_execution must not exist in the executions route module."""
    import app.routes.executions as executions_mod

    assert not hasattr(executions_mod, "_simulate_execution"), (
        "_simulate_execution still present — mock simulation was not removed"
    )
    assert not hasattr(executions_mod, "_generate_mock_steps"), (
        "_generate_mock_steps still present — mock simulation was not removed"
    )


def test_dispatch_run_imported():
    """dispatch_run must be importable from the executions route module."""
    import app.routes.executions as executions_mod

    assert hasattr(executions_mod, "dispatch_run"), (
        "dispatch_run not found in app.routes.executions — import missing"
    )
