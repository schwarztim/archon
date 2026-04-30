"""Shared fixtures for Phase 6 load tests.

These fixtures mirror the patterns used in ``test_run_dispatcher.py`` and
``test_dispatcher_persist.py`` but scaled for N parallel runs:

    * ``load_engine_factory`` — fresh in-memory SQLite engine + session
      factory per test, fully migrated.
    * ``patched_dispatcher`` — ``async_session_factory`` monkeypatched
      onto ``run_dispatcher`` so the engine work happens on the test DB.
    * ``make_workflow`` — factory for workflow step definitions.
    * ``seed_run`` — insert a Workflow + WorkflowRun pair, return run_id.
    * ``dispatch_n_workflows`` — fan out N dispatch_run calls via gather.
    * ``assert_no_double_execute`` — workflow_run_steps row count check.
    * ``wait_for_terminal`` — poll a run until it reaches a terminal
      status (or paused — useful for the approval profile).

The CI default is small (LOAD_TEST_N=10) so the suite stays under 2 min;
local runs default to 50.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Callable
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# LLM stub mode is mandatory for all load tests — no API keys, deterministic.
os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("LANGGRAPH_CHECKPOINTING", "disabled")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_n(default: int = 50) -> int:
    """Resolve ``LOAD_TEST_N`` env var; fall back to ``default``."""
    raw = os.environ.get("LOAD_TEST_N", "").strip()
    if not raw:
        return default
    try:
        n = int(raw)
    except ValueError:
        return default
    return max(1, n)


@pytest.fixture()
def n_workflows() -> int:
    """The N for this run — honour ``LOAD_TEST_N``, default 50."""
    return load_n(50)


# ---------------------------------------------------------------------------
# Engine + session factory
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables created.

    Mirrors the helper in ``test_dispatcher_persist.py``. Imports every
    model module so SQLModel.metadata is fully populated before
    ``create_all`` runs — otherwise foreign-key targets are missing and
    inserts fail at random.
    """
    # Import all model modules so SQLModel.metadata.tables is populated.
    from app.models import Agent, Execution, User  # noqa: F401
    from app.models.approval import Approval, Signal  # noqa: F401
    from app.models.timers import Timer  # noqa: F401
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
    return engine, factory


@pytest_asyncio.fixture()
async def load_engine_factory():
    """Provide an isolated engine + session factory; tear down on exit."""
    engine, factory = await _make_engine_and_factory()
    try:
        yield engine, factory
    finally:
        await engine.dispose()


@pytest.fixture()
def patched_dispatcher(monkeypatch, load_engine_factory):
    """Patch ``run_dispatcher.async_session_factory`` to the test factory.

    Returns the (engine, factory) tuple so tests can introspect the DB.
    """
    _engine, factory = load_engine_factory
    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )
    return load_engine_factory


# ---------------------------------------------------------------------------
# Workflow factory
# ---------------------------------------------------------------------------


def _step(
    step_id: str,
    *,
    node_type: str = "outputNode",
    config: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "name": name or step_id,
        "node_type": node_type,
        "config": config or {},
        "depends_on": depends_on or [],
    }


@pytest.fixture()
def make_workflow() -> Callable[..., list[dict[str, Any]]]:
    """Factory returning a list of step dicts.

    Usage::

        steps = make_workflow(num_steps=3, node_types=["inputNode",
                                                       "llmNode",
                                                       "outputNode"])

    If ``node_types`` is omitted, a chain of ``outputNode`` steps is
    produced. Each step depends on the previous one (linear chain). For
    branching topologies, callers should build dicts directly.
    """

    def _factory(
        *,
        num_steps: int = 1,
        node_types: list[str] | None = None,
        configs: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        types = list(node_types or ["outputNode"] * num_steps)
        cfgs = list(configs or [{"value": f"v{i}"} for i in range(num_steps)])
        if len(types) < num_steps:
            types += ["outputNode"] * (num_steps - len(types))
        if len(cfgs) < num_steps:
            cfgs += [{"value": f"v{i}"} for i in range(len(cfgs), num_steps)]

        steps: list[dict[str, Any]] = []
        for i in range(num_steps):
            depends = [f"s{i - 1}"] if i > 0 else []
            steps.append(
                _step(
                    step_id=f"s{i}",
                    name=f"step-{i}",
                    node_type=types[i],
                    config=cfgs[i],
                    depends_on=depends,
                )
            )
        return steps

    return _factory


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def seed_run(
    factory,
    *,
    steps: list[dict[str, Any]],
    status: str = "queued",
    tenant_id: UUID | None = None,
) -> UUID:
    """Insert a Workflow + WorkflowRun pair, return the run_id."""
    from app.models.workflow import Workflow, WorkflowRun

    async with factory() as session:
        wf = Workflow(name=f"load-wf-{uuid4().hex[:8]}",
                      steps=steps,
                      graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            kind="workflow",
            status=status,
            tenant_id=tenant_id,
            definition_snapshot={
                "kind": "workflow",
                "id": str(wf.id),
                "name": wf.name,
                "steps": steps,
                "graph_definition": {},
            },
            input_data={},
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


@pytest.fixture()
def seed_run_factory(load_engine_factory):
    """Curry the engine factory into ``seed_run`` for ergonomic use."""
    _engine, factory = load_engine_factory

    async def _seed(steps: list[dict[str, Any]], **kwargs) -> UUID:
        return await seed_run(factory, steps=steps, **kwargs)

    return _seed


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


async def dispatch_n_workflows(
    run_ids: list[UUID],
    *,
    worker_id_prefix: str = "load",
):
    """Dispatch every run_id concurrently via ``asyncio.gather``.

    Returns the list of (run_id, dispatch_result) tuples. dispatch_run
    returns the refreshed WorkflowRun on success or None on missing/lost.
    """
    from app.services.run_dispatcher import dispatch_run

    async def _one(idx: int, rid: UUID):
        worker_id = f"{worker_id_prefix}-{idx}"
        return rid, await dispatch_run(rid, worker_id=worker_id)

    results = await asyncio.gather(
        *[_one(i, rid) for i, rid in enumerate(run_ids)],
        return_exceptions=True,
    )
    return results


@pytest.fixture()
def dispatch_helper():
    """Expose ``dispatch_n_workflows`` as a fixture for ergonomic test use."""
    return dispatch_n_workflows


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


async def assert_no_double_execute(
    factory,
    run_id: UUID,
    *,
    expected_step_count: int,
) -> None:
    """Fail if the run executed any step more than once.

    Detects double-execution by counting workflow_run_steps rows. If the
    dispatcher's claim primitive is broken or two coroutines win the
    race, we'd see >expected_step_count rows for the run (each step
    re-inserted on every claim).
    """
    from app.models.workflow import WorkflowRunStep

    async with factory() as session:
        rows = (
            await session.execute(
                select(WorkflowRunStep).where(
                    WorkflowRunStep.run_id == run_id
                )
            )
        ).scalars().all()

    # Per-step uniqueness — there must be exactly one row per
    # (run_id, step_id) pair.
    by_step: dict[str, int] = {}
    for r in rows:
        by_step[r.step_id] = by_step.get(r.step_id, 0) + 1

    duplicates = {k: v for k, v in by_step.items() if v > 1}
    assert not duplicates, (
        f"double-execute on run {run_id}: step counts {duplicates}"
    )

    assert len(rows) <= expected_step_count, (
        f"run {run_id} produced {len(rows)} step rows; "
        f"expected ≤ {expected_step_count}"
    )


async def wait_for_terminal(
    factory,
    run_id: UUID,
    *,
    timeout: float = 60.0,
    accept: tuple[str, ...] = ("completed", "failed", "cancelled", "paused"),
    poll_interval: float = 0.05,
) -> str:
    """Poll a run until it reaches one of the ``accept`` statuses.

    Returns the final status string. Raises AssertionError on timeout
    so the test fails loudly with the offending run_id.
    """
    from app.models.workflow import WorkflowRun

    deadline = time.monotonic() + timeout
    last_status: str | None = None
    while time.monotonic() < deadline:
        async with factory() as session:
            run = await session.get(WorkflowRun, run_id)
            last_status = run.status if run else None
        if last_status in accept:
            return last_status
        await asyncio.sleep(poll_interval)

    raise AssertionError(
        f"run {run_id} did not reach terminal status within {timeout}s "
        f"(last seen: {last_status!r})"
    )


@pytest.fixture()
def wait_terminal_helper():
    return wait_for_terminal


@pytest.fixture()
def double_execute_helper():
    return assert_no_double_execute


# ---------------------------------------------------------------------------
# Event chain assertions
# ---------------------------------------------------------------------------


async def event_types_for_run(factory, run_id: UUID) -> list[str]:
    """Return the ordered list of event_type strings for a run."""
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        events = (
            await session.execute(
                select(WorkflowRunEvent)
                .where(WorkflowRunEvent.run_id == run_id)
                .order_by(WorkflowRunEvent.sequence)
            )
        ).scalars().all()
    return [e.event_type for e in events]


async def assert_canonical_event_chain(
    factory,
    run_id: UUID,
    *,
    require_completed: bool = True,
    require_paused: bool = False,
    require_resumed: bool = False,
) -> list[str]:
    """Assert ``run.created`` (or queued)→ claimed → started → completed.

    ``run.created`` is not emitted by the dispatcher — runs are seeded
    via direct INSERT. The dispatcher emits ``run.claimed`` first, so
    the contract verified here is:

        run.claimed → run.started → ... → run.completed

    For paused/resumed flows the caller can require those event types
    too. Returns the ordered event-type list for further inspection.
    """
    types = await event_types_for_run(factory, run_id)
    assert "run.claimed" in types, f"{run_id}: missing run.claimed in {types}"
    assert "run.started" in types, f"{run_id}: missing run.started in {types}"
    if require_completed:
        assert "run.completed" in types, (
            f"{run_id}: missing run.completed in {types}"
        )
    if require_paused:
        assert "run.paused" in types, (
            f"{run_id}: missing run.paused in {types}"
        )
    if require_resumed:
        assert "run.resumed" in types, (
            f"{run_id}: missing run.resumed in {types}"
        )
    return types


@pytest.fixture()
def event_chain_helper():
    return assert_canonical_event_chain


# ---------------------------------------------------------------------------
# Performance budget helper
# ---------------------------------------------------------------------------


def assert_within_budget(elapsed: float, *, budget_s: float, label: str) -> None:
    """Fail if ``elapsed`` exceeds ``budget_s``. Surfaces actual on success."""
    assert elapsed <= budget_s, (
        f"{label}: completed in {elapsed:.2f}s but budget was {budget_s:.2f}s"
    )


@pytest.fixture()
def budget_helper():
    return assert_within_budget
