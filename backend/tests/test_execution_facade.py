"""Tests for ExecutionFacade — Phase 1 / WS2.

Covers ADR-001 (XOR target, definition snapshot), ADR-002 (hash-chained
run.created + run.queued events), ADR-004 (input_hash computation),
ADR-006 (legacy fallback + projection shape).

All tests run against an in-memory SQLite engine via the AsyncSession
created in conftest_facade — zero external dependencies.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

# Import all models so SQLModel.metadata is populated.
from app.models import Agent, Execution, User  # noqa: F401
from app.models.workflow import (
    Workflow,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowRunStep,  # noqa: F401
)
from app.services.execution_facade import ExecutionFacade
from app.services.idempotency_service import IdempotencyConflict


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture()
async def engine():
    """Fresh in-memory SQLite engine with all tables created."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    # Enable foreign keys + CHECK constraints for SQLite
    from sqlalchemy import event

    async with eng.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture()
async def session(engine) -> AsyncSession:
    """An AsyncSession bound to the fresh engine.

    ``expire_on_commit=False`` matches application/factory configuration —
    detached attribute access after commit/refresh would otherwise issue
    lazy SQL and crash on greenlet boundaries.
    """
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


@pytest_asyncio.fixture()
async def seeded_user(session: AsyncSession) -> User:
    """A persisted User row referenced by Agent.owner_id."""
    user = User(
        id=uuid4(),
        email="facade-tester@example.com",
        name="Facade Tester",
        role="admin",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest_asyncio.fixture()
async def seeded_agent(session: AsyncSession, seeded_user: User) -> Agent:
    """A persisted Agent referenced by agent-driven runs."""
    agent = Agent(
        id=uuid4(),
        name="facade-test-agent",
        description="agent for facade tests",
        definition={"model": "gpt-3.5-turbo"},
        status="ready",
        owner_id=seeded_user.id,
        tags=["test"],
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@pytest_asyncio.fixture()
async def seeded_workflow(session: AsyncSession) -> Workflow:
    """A persisted Workflow referenced by workflow-driven runs."""
    wf = Workflow(
        id=uuid4(),
        name="facade-test-workflow",
        description="workflow for facade tests",
        steps=[
            {"name": "step-a", "config": {"type": "inputNode"}, "depends_on": []},
            {"name": "step-b", "config": {"type": "outputNode"}, "depends_on": ["step-a"]},
        ],
        graph_definition={"nodes": [], "edges": []},
        is_active=True,
    )
    session.add(wf)
    await session.commit()
    await session.refresh(wf)
    return wf


# ── Helpers ───────────────────────────────────────────────────────────


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_workflow_run_emits_run_created_and_queued_events(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """ADR-002: every new run receives sequence-0 'run.created' and sequence-1 'run.queued'."""
    tenant_id = uuid4()
    run, is_new = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data={"message": "hello"},
    )

    assert is_new is True
    assert run.kind == "workflow"
    assert run.workflow_id == seeded_workflow.id
    assert run.agent_id is None
    assert run.status == "queued"
    assert run.queued_at is not None

    stmt = (
        select(WorkflowRunEvent)
        .where(WorkflowRunEvent.run_id == run.id)
        .order_by(WorkflowRunEvent.sequence.asc())
    )
    events = list((await session.exec(stmt)).all())
    assert [e.event_type for e in events] == ["run.created", "run.queued"]
    assert [e.sequence for e in events] == [0, 1]
    # Hash chain shape: sequence 0 has prev_hash=None.
    assert events[0].prev_hash is None
    assert events[1].prev_hash == events[0].current_hash


@pytest.mark.asyncio
async def test_create_agent_run_uses_kind_agent_and_agent_id(
    session: AsyncSession, seeded_agent: Agent
) -> None:
    """Agent-driven runs carry kind='agent' and the agent_id; workflow_id remains NULL."""
    run, is_new = await ExecutionFacade.create_run(
        session,
        kind="agent",
        agent_id=seeded_agent.id,
        tenant_id=uuid4(),
        input_data={"prompt": "do something"},
    )

    assert is_new is True
    assert run.kind == "agent"
    assert run.agent_id == seeded_agent.id
    assert run.workflow_id is None
    assert run.status == "queued"


@pytest.mark.asyncio
async def test_create_run_requires_exactly_one_of_workflow_id_agent_id(
    session: AsyncSession, seeded_agent: Agent, seeded_workflow: Workflow
) -> None:
    """XOR enforcement at the facade layer: both raises, neither raises."""
    # Both set → ValueError
    with pytest.raises(ValueError, match="exactly one of"):
        await ExecutionFacade.create_run(
            session,
            kind="workflow",
            workflow_id=seeded_workflow.id,
            agent_id=seeded_agent.id,
            tenant_id=uuid4(),
            input_data={},
        )

    # Neither set → ValueError
    with pytest.raises(ValueError, match="exactly one of"):
        await ExecutionFacade.create_run(
            session,
            kind="workflow",
            workflow_id=None,
            agent_id=None,
            tenant_id=uuid4(),
            input_data={},
        )


@pytest.mark.asyncio
async def test_create_run_captures_definition_snapshot(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """ADR-001: definition_snapshot is captured at creation, immutable thereafter."""
    run, _ = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=uuid4(),
        input_data={},
    )
    snap = run.definition_snapshot
    assert snap is not None
    assert snap.get("kind") == "workflow"
    assert snap.get("id") == str(seeded_workflow.id)
    assert snap.get("name") == seeded_workflow.name
    assert snap.get("steps") == seeded_workflow.steps
    assert snap.get("graph_definition") == seeded_workflow.graph_definition
    assert "captured_at" in snap


@pytest.mark.asyncio
async def test_create_run_input_hash_is_sha256_of_canonical_input_data(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """ADR-004: input_hash = sha256(canonical_json(envelope))."""
    tenant_id = uuid4()
    input_data = {"b": 2, "a": 1, "nested": {"y": 2, "x": 1}}

    run, _ = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=tenant_id,
        input_data=input_data,
    )

    expected = hashlib.sha256(
        _canonical(
            {
                "kind": "workflow",
                "workflow_id": str(seeded_workflow.id),
                "agent_id": None,
                "input_data": input_data,
            }
        ).encode("utf-8")
    ).hexdigest()
    assert run.input_hash == expected


@pytest.mark.asyncio
async def test_get_falls_back_to_legacy_execution_when_run_not_found(
    session: AsyncSession, seeded_agent: Agent
) -> None:
    """ADR-006: ExecutionFacade.get checks workflow_runs first, then executions."""
    # Insert a legacy Execution row (no WorkflowRun for the same id).
    legacy = Execution(
        id=uuid4(),
        agent_id=seeded_agent.id,
        status="completed",
        input_data={"k": "v"},
        output_data={"resp": "done"},
    )
    session.add(legacy)
    await session.commit()
    await session.refresh(legacy)

    # WorkflowRun lookup miss → Execution fallback.
    resolved = await ExecutionFacade.get(session, legacy.id)
    assert resolved is not None
    assert isinstance(resolved, Execution)
    assert resolved.id == legacy.id
    assert resolved.status == "completed"

    # Unknown id → None.
    missing = await ExecutionFacade.get(session, uuid4())
    assert missing is None


@pytest.mark.asyncio
async def test_project_to_legacy_execution_shape_round_trip(
    session: AsyncSession, seeded_workflow: Workflow
) -> None:
    """ADR-006 projection: WorkflowRun → legacy Execution JSON shape contract."""
    run, _ = await ExecutionFacade.create_run(
        session,
        kind="workflow",
        workflow_id=seeded_workflow.id,
        tenant_id=uuid4(),
        input_data={"x": 1},
    )

    shape = ExecutionFacade.project_to_legacy_execution_shape(run)

    # Required legacy keys present.
    for key in (
        "id",
        "agent_id",
        "status",
        "input_data",
        "output_data",
        "error",
        "steps",
        "metrics",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    ):
        assert key in shape, f"projection missing legacy key {key!r}"

    # ID round-trips as a string.
    assert UUID(shape["id"]) == run.id
    assert shape["status"] == "queued"
    assert shape["input_data"] == {"x": 1}
    assert shape["agent_id"] is None  # workflow-driven row
    # Canonical fields exposed for opt-in clients.
    assert shape["run_id"] == str(run.id)
    assert shape["kind"] == "workflow"
    assert shape["workflow_id"] == str(seeded_workflow.id)


@pytest.mark.asyncio
async def test_create_run_missing_workflow_raises_value_error(
    session: AsyncSession,
) -> None:
    """ValueError when workflow_id references a row that doesn't exist."""
    with pytest.raises(ValueError, match="not found"):
        await ExecutionFacade.create_run(
            session,
            kind="workflow",
            workflow_id=uuid4(),
            tenant_id=uuid4(),
            input_data={},
        )
