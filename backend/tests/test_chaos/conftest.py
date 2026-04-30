"""Shared fixtures and helpers for the chaos test suite.

Provides:
  - `engine_and_factory`     in-memory SQLite engine + AsyncSession factory
  - `seed_workflow`           helper that returns a seeded workflow_id
  - `seed_run`                helper that inserts a WorkflowRun row
  - `simulated_worker`        factory that builds independent worker IDs
  - `corrupt_lease`           helper that backdates a run's lease_expires_at
  - `consecutive_failures`    AsyncMock-style patcher for transient DB failure
  - `chaos_session`           session whose .execute() can be configured to
                              raise on the first N invocations and then
                              succeed (transient failure simulation)

The fixtures intentionally avoid touching the real Postgres / Redis stack —
chaos tests run hermetically against in-memory SQLite and patched module
boundaries so they exercise the *recovery* code paths without needing
real outages.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Callable
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Stub mode keeps the LLM path from making real network calls.
os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")
os.environ.setdefault(
    "ARCHON_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t"
)
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Engine + session factory
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def engine_and_factory():
    """Per-test in-memory SQLite engine with all tables materialised.

    Yields ``(engine, factory)``. The engine is disposed at teardown.
    """
    # Importing the model modules populates SQLModel.metadata with every
    # table needed by the chaos suite (workflow + run + step + event +
    # timer + signal + approval + worker_registry).
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.approval import Approval, Signal  # noqa: F401
    from app.models.timers import Timer  # noqa: F401
    from app.models.worker_registry import WorkerHeartbeat  # noqa: F401
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def factory(engine_and_factory):
    """Shortcut returning just the AsyncSession factory."""
    _engine, fac = engine_and_factory
    return fac


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def seed_workflow(factory) -> UUID:
    """Seed a single Workflow row and return its id."""
    from app.models.workflow import Workflow

    workflow_steps = [
        {
            "step_id": "s1",
            "name": "step-one",
            "node_type": "outputNode",
            "config": {"value": "ok"},
            "depends_on": [],
        }
    ]
    async with factory() as session:
        wf = Workflow(
            name="chaos-wf",
            steps=workflow_steps,
            graph_definition={},
        )
        session.add(wf)
        await session.commit()
        await session.refresh(wf)
        return wf.id


async def insert_run(
    factory,
    *,
    workflow_id: UUID,
    status: str = "queued",
    lease_owner: str | None = None,
    lease_expires_at: datetime | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> UUID:
    """Insert a WorkflowRun row and return its id.

    Helper used by tests that need fine-grained control over the row
    state (lease fields, status, custom snapshot steps).
    """
    from app.models.workflow import WorkflowRun

    snapshot_steps = steps or [
        {
            "step_id": "s1",
            "name": "step-one",
            "node_type": "outputNode",
            "config": {"value": "ok"},
            "depends_on": [],
        }
    ]
    async with factory() as session:
        run = WorkflowRun(
            workflow_id=workflow_id,
            kind="workflow",
            status=status,
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            definition_snapshot={
                "kind": "workflow",
                "id": str(workflow_id),
                "name": "chaos-wf",
                "steps": snapshot_steps,
                "graph_definition": {},
            },
            input_data={},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


# ---------------------------------------------------------------------------
# Worker simulation
# ---------------------------------------------------------------------------


@pytest.fixture()
def simulated_worker() -> Callable[[str], str]:
    """Factory that produces stable-ish worker IDs.

    Usage::

        wid = simulated_worker("alpha")  # → "alpha-<short-uuid>"

    Each call mints a fresh suffix so concurrent claim races have
    distinct contestants.
    """

    def _make(label: str = "worker") -> str:
        return f"{label}-{uuid4().hex[:8]}"

    return _make


# ---------------------------------------------------------------------------
# Lease corruption helper (simulates worker crash mid-step)
# ---------------------------------------------------------------------------


@pytest.fixture()
def corrupt_lease(factory):
    """Async helper that backdates a run's lease_expires_at.

    Returns a coroutine factory. Usage::

        await corrupt_lease(run_id, seconds_in_past=120)

    Effect: the run's ``lease_expires_at`` is set to ``now - delta`` and
    ``status`` stays ``running``. ``reclaim_expired_runs`` will then
    return it to ``queued`` on the next sweep — which simulates the
    crash-recovery codepath the worker uses when a lease holder dies.
    """
    from app.models.workflow import WorkflowRun

    async def _do(
        run_id: UUID,
        *,
        seconds_in_past: int = 120,
        keep_status: str = "running",
    ) -> None:
        async with factory() as session:
            row = await session.get(WorkflowRun, run_id)
            assert row is not None, f"run {run_id} not found"
            row.lease_expires_at = datetime.utcnow() - timedelta(
                seconds=seconds_in_past
            )
            row.status = keep_status
            session.add(row)
            await session.commit()

    return _do


# ---------------------------------------------------------------------------
# Transient-failure session wrapper
# ---------------------------------------------------------------------------


class FlakySession:
    """Wrap an AsyncSession; raise ``exc`` on the first ``fail_count`` execs.

    After the failure budget is exhausted, calls are forwarded to the
    underlying session. Used to assert that the dispatcher / engine retry
    cleanly when the database has a hiccup.

    The wrapper preserves async context-manager semantics so callers can
    still do ``async with FlakySession(...) as s:``.
    """

    def __init__(
        self,
        inner: AsyncSession,
        *,
        fail_count: int = 1,
        exc: BaseException | None = None,
        target_method: str = "execute",
    ) -> None:
        self._inner = inner
        self._remaining = fail_count
        self._exc = exc or TimeoutError("simulated db timeout")
        self._target = target_method
        self.attempts = 0  # number of times target_method was invoked

    def __getattr__(self, item: str):
        # Default proxy: forward everything to inner.
        return getattr(self._inner, item)

    async def __aenter__(self) -> "FlakySession":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._inner.__aexit__(exc_type, exc, tb)

    async def execute(self, *args, **kwargs):
        if self._target == "execute":
            self.attempts += 1
            if self._remaining > 0:
                self._remaining -= 1
                raise self._exc
        return await self._inner.execute(*args, **kwargs)

    async def commit(self) -> None:
        if self._target == "commit":
            self.attempts += 1
            if self._remaining > 0:
                self._remaining -= 1
                raise self._exc
        await self._inner.commit()

    async def flush(self) -> None:
        if self._target == "flush":
            self.attempts += 1
            if self._remaining > 0:
                self._remaining -= 1
                raise self._exc
        await self._inner.flush()


@pytest.fixture()
def consecutive_failures():
    """Patch helper: produce an async function that fails N times then succeeds.

    Usage::

        flake = consecutive_failures(n=2, exc=TimeoutError("db"))
        async def _wrapped(*a, **kw):
            await flake()
            return await real_func(*a, **kw)

    The returned callable has an `.attempts` attribute the test can
    inspect after the SUT exercises the flaky path.
    """

    class _Counter:
        def __init__(self, n: int, exc: BaseException) -> None:
            self.n = n
            self.exc = exc
            self.attempts = 0

        async def __call__(self) -> None:
            self.attempts += 1
            if self.n > 0:
                self.n -= 1
                raise self.exc

    def _make(*, n: int = 1, exc: BaseException | None = None) -> _Counter:
        return _Counter(n, exc or TimeoutError("simulated"))

    return _make


# ---------------------------------------------------------------------------
# Chaos session — the unified injectable-failure session fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def chaos_session(factory):
    """Yield (factory, builder) where builder returns a fresh FlakySession.

    The builder accepts kwargs forwarded to ``FlakySession`` — fail_count,
    exc, target_method — so each test can craft a session whose
    ``execute``/``commit``/``flush`` raises a configurable exception for
    the first N calls.
    """

    def _build(
        inner: AsyncSession,
        *,
        fail_count: int = 1,
        exc: BaseException | None = None,
        target_method: str = "execute",
    ) -> FlakySession:
        return FlakySession(
            inner,
            fail_count=fail_count,
            exc=exc,
            target_method=target_method,
        )

    yield factory, _build


__all__ = [
    "FlakySession",
    "engine_and_factory",
    "factory",
    "seed_workflow",
    "insert_run",
    "simulated_worker",
    "corrupt_lease",
    "consecutive_failures",
    "chaos_session",
]
