"""Production-mode stub-block enforcement tests (Phase 3 / WS9).

Covers two layers:

1. ``assert_node_runnable`` — the unit helper that decides whether a
   given node_type may execute in the current ``ARCHON_ENV``.
2. The dispatcher gate — when a run snapshot contains a stub-classified
   node and ``ARCHON_ENV=production``, the dispatcher MUST refuse to
   invoke the engine, finalise the run as ``failed`` with
   ``error_code='stub_blocked'``, and emit a ``step.failed`` event with
   ``error_code='stub_blocked_in_production'``.

ADR-005 is the spec: durable environments (production / staging) treat
silent-success node executors as a correctness violation.
"""

from __future__ import annotations

import os
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.node_executors import (
    StubBlockError,
    assert_node_runnable,
)
from app.services.node_executors.status_registry import NodeStatus

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")


SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Unit tests — assert_node_runnable
# ---------------------------------------------------------------------------


def test_assert_node_runnable_passes_for_production_node_in_production_env() -> None:
    """A production-classified node runs in production."""
    # Should not raise.
    assert_node_runnable("llmNode", env="production")
    assert_node_runnable("inputNode", env="production")
    assert_node_runnable("outputNode", env="production")


def test_assert_node_runnable_passes_for_beta_node_in_production_env() -> None:
    """Beta-classified nodes are durable-eligible (gaps tracked separately)."""
    assert_node_runnable("conditionNode", env="production")
    assert_node_runnable("dlpScanNode", env="production")
    assert_node_runnable("costGateNode", env="production")


def test_assert_node_runnable_blocks_stub_in_production() -> None:
    """A stub node raises StubBlockError in production."""
    with pytest.raises(StubBlockError) as exc_info:
        assert_node_runnable("loopNode", env="production")
    err = exc_info.value
    assert err.node_type == "loopNode"
    assert err.status is NodeStatus.STUB
    assert err.env == "production"
    assert "loopNode" in str(err)
    assert "stub" in str(err).lower()


def test_assert_node_runnable_blocks_stub_in_staging() -> None:
    """Staging is durable per ADR-005 — same enforcement as production."""
    with pytest.raises(StubBlockError) as exc_info:
        assert_node_runnable("mcpToolNode", env="staging")
    assert exc_info.value.env == "staging"
    assert exc_info.value.status is NodeStatus.STUB


def test_assert_node_runnable_allows_stub_in_dev() -> None:
    """Dev environments permit stubs — useful during integration testing."""
    # All of these are stubs; none should raise in dev.
    for node in (
        "loopNode",
        "mcpToolNode",
        "toolNode",
        "humanInputNode",
        "databaseQueryNode",
        "embeddingNode",
        "vectorSearchNode",
    ):
        assert_node_runnable(node, env="dev")


def test_assert_node_runnable_allows_stub_in_test() -> None:
    """Test environments permit stubs (CI uses stub LLMs / DLP / etc.)."""
    assert_node_runnable("loopNode", env="test")
    assert_node_runnable("functionCallNode", env="test")


def test_assert_node_runnable_unset_env_treated_as_dev(monkeypatch) -> None:
    """ARCHON_ENV unset → permissive (matches ADR-005 default)."""
    monkeypatch.delenv("ARCHON_ENV", raising=False)
    assert_node_runnable("loopNode")  # uses os.environ; should not raise


def test_assert_node_runnable_reads_archon_env_when_arg_missing(monkeypatch) -> None:
    """When env arg is None, the helper reads ARCHON_ENV from the environment."""
    monkeypatch.setenv("ARCHON_ENV", "production")
    with pytest.raises(StubBlockError):
        assert_node_runnable("loopNode")  # arg defaults to None → reads env

    monkeypatch.setenv("ARCHON_ENV", "dev")
    assert_node_runnable("loopNode")  # dev → permitted


def test_assert_node_runnable_blocks_unknown_node_in_production() -> None:
    """Unknown node types classify as DESIGNED → blocked in production."""
    with pytest.raises(StubBlockError) as exc_info:
        assert_node_runnable("totallyMadeUpNode", env="production")
    assert exc_info.value.status is NodeStatus.DESIGNED


def test_assert_node_runnable_env_normalised(monkeypatch) -> None:
    """Env is lower-cased / trimmed to match ADR-005 semantics."""
    with pytest.raises(StubBlockError):
        assert_node_runnable("loopNode", env="PRODUCTION")
    with pytest.raises(StubBlockError):
        assert_node_runnable("loopNode", env=" Production ")
    # case insensitive 'dev'
    assert_node_runnable("loopNode", env="DEV")


# ---------------------------------------------------------------------------
# Integration test — dispatcher gates on stub-blocked nodes
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all run + signal + timer tables."""
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


async def _seed_run_with_steps(factory, *, steps: list[dict]) -> UUID:
    """Seed a workflow + run whose definition_snapshot contains *steps*."""
    from app.models.workflow import Workflow, WorkflowRun

    async with factory() as session:
        wf = Workflow(name="stub-block-wf", steps=steps, graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            kind="workflow",
            status="queued",
            tenant_id=None,
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


@pytest.mark.asyncio
async def test_dispatcher_emits_stub_blocked_event_on_step_attempt(monkeypatch):
    """A stub node in the snapshot fails the run before the engine runs.

    Verifies:
      - run.status == 'failed' with error_code='stub_blocked'
      - a step.failed event exists with error_code='stub_blocked_in_production'
      - the workflow engine was NOT invoked (silent-success was prevented)
    """
    engine, factory = await _make_engine_and_factory()

    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )
    monkeypatch.setenv("ARCHON_ENV", "production")

    # Sentinel: the engine must NOT be invoked when the gate fires.
    engine_called = {"value": False}

    async def _fake_engine(workflow, **kwargs):
        engine_called["value"] = True
        return {"status": "completed", "duration_ms": 0, "steps": []}

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    # Snapshot contains a stub-classified node (loopNode).
    steps = [
        {
            "step_id": "s1",
            "name": "loop-step",
            "node_type": "loopNode",
            "config": {"maxIterations": 3},
            "depends_on": [],
        },
    ]
    run_id = await _seed_run_with_steps(factory, steps=steps)

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="stub-block-worker")

    # Run finalised as failed with error_code=stub_blocked.
    assert result is not None
    assert result.status == "failed", f"expected failed, got {result.status}"
    assert result.error_code == "stub_blocked", (
        f"expected error_code='stub_blocked', got {result.error_code!r}"
    )
    assert result.error and "loopNode" in result.error
    assert result.completed_at is not None

    # The workflow engine MUST NOT have been invoked. This is the
    # invariant the gate exists to enforce — silent stub completion is
    # the failure mode being prevented.
    assert engine_called["value"] is False, (
        "execute_workflow_dag was invoked despite stub-block gate"
    )

    # step.failed event with the structured error_code is in the chain.
    from app.models.workflow import WorkflowRunEvent

    async with factory() as session:
        events_result = await session.execute(
            select(WorkflowRunEvent)
            .where(WorkflowRunEvent.run_id == run_id)
            .order_by(WorkflowRunEvent.sequence)
        )
        events = events_result.scalars().all()

    event_types = [e.event_type for e in events]
    assert "step.failed" in event_types, (
        f"step.failed missing from chain: {event_types}"
    )
    assert "run.failed" in event_types
    assert event_types[-1] == "run.failed"

    step_failed_event = next(e for e in events if e.event_type == "step.failed")
    assert step_failed_event.payload.get("error_code") == (
        "stub_blocked_in_production"
    )
    assert step_failed_event.payload.get("node_type") == "loopNode"
    assert step_failed_event.payload.get("node_status") == "stub"
    assert step_failed_event.payload.get("archon_env") == "production"
    assert step_failed_event.step_id == "s1"

    run_failed_event = next(e for e in events if e.event_type == "run.failed")
    assert run_failed_event.payload.get("error_code") == "stub_blocked"
    blocked_steps = run_failed_event.payload.get("blocked_steps") or []
    assert len(blocked_steps) == 1
    assert blocked_steps[0]["step_id"] == "s1"
    assert blocked_steps[0]["node_type"] == "loopNode"

    # A WorkflowRunStep row was persisted with the structured error_code
    # so REST consumers see the failure detail without reading events.
    from app.models.workflow import WorkflowRunStep

    async with factory() as session:
        step_result = await session.execute(
            select(WorkflowRunStep).where(WorkflowRunStep.run_id == run_id)
        )
        step_rows = step_result.scalars().all()

    assert len(step_rows) == 1
    assert step_rows[0].status == "failed"
    assert step_rows[0].error_code == "stub_blocked_in_production"
    assert step_rows[0].step_id == "s1"

    await engine.dispose()


@pytest.mark.asyncio
async def test_dispatcher_allows_production_node_in_production(monkeypatch):
    """Counter-test: a production-classified node passes the gate.

    Confirms the gate is selective — it only blocks stubs, not durable
    executors. The engine MUST be invoked for production / beta nodes.
    """
    engine, factory = await _make_engine_and_factory()

    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )
    monkeypatch.setenv("ARCHON_ENV", "production")

    engine_called = {"value": False}

    async def _fake_engine(workflow, **kwargs):
        engine_called["value"] = True
        return {
            "status": "completed",
            "duration_ms": 1,
            "steps": [
                {
                    "step_id": "s1",
                    "name": "out",
                    "status": "completed",
                    "duration_ms": 1,
                    "output_data": {"ok": True},
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    steps = [
        {
            "step_id": "s1",
            "name": "out",
            "node_type": "outputNode",  # production
            "config": {},
            "depends_on": [],
        },
    ]
    run_id = await _seed_run_with_steps(factory, steps=steps)

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="prod-ok-worker")

    assert engine_called["value"] is True, (
        "production-classified node was incorrectly gated"
    )
    assert result is not None
    assert result.status == "completed"
    assert result.error_code is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_dispatcher_allows_stub_node_in_dev(monkeypatch):
    """Counter-test: dev permits stubs — engine runs even with a stub node."""
    engine, factory = await _make_engine_and_factory()

    monkeypatch.setattr(
        "app.services.run_dispatcher.async_session_factory",
        factory,
    )
    monkeypatch.setenv("ARCHON_ENV", "dev")

    engine_called = {"value": False}

    async def _fake_engine(workflow, **kwargs):
        engine_called["value"] = True
        return {
            "status": "completed",
            "duration_ms": 1,
            "steps": [
                {
                    "step_id": "s1",
                    "name": "loop-stub",
                    "status": "completed",
                    "duration_ms": 1,
                    "output_data": {"_stub": True},
                }
            ],
        }

    monkeypatch.setattr(
        "app.services.run_dispatcher.execute_workflow_dag",
        _fake_engine,
    )

    steps = [
        {
            "step_id": "s1",
            "name": "loop-stub",
            "node_type": "loopNode",  # stub — but dev permits
            "config": {},
            "depends_on": [],
        },
    ]
    run_id = await _seed_run_with_steps(factory, steps=steps)

    from app.services.run_dispatcher import dispatch_run

    result = await dispatch_run(run_id, worker_id="dev-stub-worker")

    assert engine_called["value"] is True, (
        "dev environment incorrectly blocked a stub node"
    )
    assert result is not None
    assert result.status == "completed"

    await engine.dispose()
