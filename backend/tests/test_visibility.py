"""Tests for W13 Visibility service and search endpoints.

Covers:
  - VisibilityIndex model creation with in-memory SQLite
  - search_runs() filtering by status, queue, worker, date range
  - update_visibility_index() upsert logic
  - get_run_timeline() pagination
  - get_run_graph() step graph extraction
  - Route endpoints: /runs/search, /runs/{id}/timeline, /runs/{id}/graph

Pattern follows test_task_queues.py — in-memory SQLite + SQLModel.create_all.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("AUTH_DEV_MODE", "true")

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Engine / session helpers
# ---------------------------------------------------------------------------


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all relevant tables."""
    from app.models import Agent, User  # noqa: F401
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )
    from app.models.visibility import VisibilityIndex  # noqa: F401

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run(
    tenant_id: UUID | None = None,
    status: str = "completed",
    workflow_id: UUID | None = None,
) -> "WorkflowRun":  # noqa: F821
    from app.models.workflow import WorkflowRun

    wid = workflow_id or uuid4()
    return WorkflowRun(
        id=uuid4(),
        workflow_id=wid,
        agent_id=None,
        kind="workflow",
        definition_snapshot={"steps": []},
        tenant_id=tenant_id,
        status=status,
        started_at=datetime.utcnow() - timedelta(seconds=30),
        completed_at=datetime.utcnow(),
        duration_ms=30000,
    )


def _make_vis(run: "WorkflowRun", queue_name: str | None = None, worker_id: str | None = None) -> "VisibilityIndex":  # noqa: F821
    from app.models.visibility import VisibilityIndex

    return VisibilityIndex(
        workflow_run_id=run.id,
        tenant_id=run.tenant_id,
        status=run.status,
        workflow_id=run.workflow_id,
        queue_name=queue_name,
        worker_id=worker_id,
        tags_json={},
        cost_total_usd=1.5,
        duration_ms=run.duration_ms,
        step_count=3,
        started_at=run.started_at,
        completed_at=run.completed_at,
        updated_at=datetime.utcnow(),
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_visibility_index_create():
    """VisibilityIndex row can be inserted and retrieved."""

    async def _inner():
        engine, factory = await _make_engine_and_factory()
        async with factory() as session:
            from app.models.visibility import VisibilityIndex
            from sqlalchemy import select

            run_id = uuid4()
            tenant_id = uuid4()
            vis = VisibilityIndex(
                workflow_run_id=run_id,
                tenant_id=tenant_id,
                status="completed",
                tags_json={"env": "prod"},
                cost_total_usd=2.5,
                step_count=2,
                updated_at=datetime.utcnow(),
            )
            session.add(vis)
            await session.commit()

            result = await session.execute(
                select(VisibilityIndex).where(VisibilityIndex.workflow_run_id == run_id)
            )
            fetched = result.scalars().first()
            assert fetched is not None
            assert fetched.status == "completed"
            assert fetched.cost_total_usd == 2.5
            assert fetched.tags_json == {"env": "prod"}

        await engine.dispose()

    _run(_inner())


# ---------------------------------------------------------------------------
# search_runs() tests
# ---------------------------------------------------------------------------


def test_search_by_status():
    """search_runs() returns only rows matching the requested status."""

    async def _inner():
        engine, factory = await _make_engine_and_factory()
        async with factory() as session:
            tenant_id = uuid4()
            run_a = _make_run(tenant_id=tenant_id, status="completed")
            run_b = _make_run(tenant_id=tenant_id, status="failed")
            vis_a = _make_vis(run_a)
            vis_b = _make_vis(run_b)
            for obj in (vis_a, vis_b):
                session.add(obj)
            await session.commit()

            from app.services.visibility_service import search_runs

            results = await search_runs(
                session, tenant_id=tenant_id, filters={"status": "completed"}
            )
            assert len(results) == 1
            assert results[0]["status"] == "completed"

        await engine.dispose()

    _run(_inner())


def test_search_by_queue_and_worker():
    """search_runs() filters by queue_name and worker_id."""

    async def _inner():
        engine, factory = await _make_engine_and_factory()
        async with factory() as session:
            tenant_id = uuid4()
            run_a = _make_run(tenant_id=tenant_id, status="completed")
            run_b = _make_run(tenant_id=tenant_id, status="completed")
            vis_a = _make_vis(run_a, queue_name="default", worker_id="worker-1")
            vis_b = _make_vis(run_b, queue_name="high-priority", worker_id="worker-2")
            for obj in (vis_a, vis_b):
                session.add(obj)
            await session.commit()

            from app.services.visibility_service import search_runs

            # Filter by queue only
            results = await search_runs(
                session, tenant_id=tenant_id, filters={"queue_name": "default"}
            )
            assert len(results) == 1
            assert results[0]["queue_name"] == "default"

            # Filter by worker only
            results = await search_runs(
                session, tenant_id=tenant_id, filters={"worker_id": "worker-2"}
            )
            assert len(results) == 1
            assert results[0]["worker_id"] == "worker-2"

        await engine.dispose()

    _run(_inner())


def test_search_by_date_range():
    """search_runs() filters by created_after / created_before."""

    async def _inner():
        engine, factory = await _make_engine_and_factory()
        async with factory() as session:
            tenant_id = uuid4()
            now = datetime.utcnow()

            # old run — started 2 hours ago
            run_old = _make_run(tenant_id=tenant_id, status="completed")
            run_old.started_at = now - timedelta(hours=2)
            vis_old = _make_vis(run_old)
            vis_old.started_at = run_old.started_at

            # recent run — started 30 seconds ago
            run_new = _make_run(tenant_id=tenant_id, status="completed")
            run_new.started_at = now - timedelta(seconds=30)
            vis_new = _make_vis(run_new)
            vis_new.started_at = run_new.started_at

            for obj in (vis_old, vis_new):
                session.add(obj)
            await session.commit()

            from app.services.visibility_service import search_runs

            one_hour_ago = (now - timedelta(hours=1)).isoformat()
            results = await search_runs(
                session,
                tenant_id=tenant_id,
                filters={"created_after": one_hour_ago},
            )
            assert len(results) == 1
            assert results[0]["workflow_run_id"] == str(run_new.id)

        await engine.dispose()

    _run(_inner())


# ---------------------------------------------------------------------------
# get_run_timeline() tests
# ---------------------------------------------------------------------------


def test_timeline_pagination():
    """get_run_timeline() pages correctly using sequence cursor."""

    async def _inner():
        engine, factory = await _make_engine_and_factory()
        async with factory() as session:
            from app.models.workflow import WorkflowRun, WorkflowRunEvent
            from app.services.visibility_service import get_run_timeline
            import hashlib

            run = _make_run()
            session.add(run)
            await session.commit()

            # Insert 5 events with sequences 0-4
            for seq in range(5):
                payload = {"status": f"step_{seq}"}
                current_hash = hashlib.sha256(
                    f"{run.id}:{seq}".encode()
                ).hexdigest()
                event = WorkflowRunEvent(
                    run_id=run.id,
                    sequence=seq,
                    event_type="run.started" if seq == 0 else "step.completed",
                    payload=payload,
                    current_hash=current_hash,
                    prev_hash=None if seq == 0 else "prev",
                )
                session.add(event)
            await session.commit()

            # First page — get 3 events
            page1 = await get_run_timeline(session, run_id=run.id, cursor=0, limit=3)
            assert len(page1["events"]) == 3
            assert page1["next_cursor"] == 3
            assert page1["events"][0]["sequence"] == 0
            assert page1["events"][2]["sequence"] == 2

            # Second page — get remaining 2
            page2 = await get_run_timeline(
                session, run_id=run.id, cursor=page1["next_cursor"], limit=3
            )
            assert len(page2["events"]) == 2
            assert page2["next_cursor"] is None

        await engine.dispose()

    _run(_inner())


# ---------------------------------------------------------------------------
# get_run_graph() tests
# ---------------------------------------------------------------------------


def test_run_graph_returns_steps():
    """get_run_graph() returns nodes from WorkflowRunStep rows."""

    async def _inner():
        engine, factory = await _make_engine_and_factory()
        async with factory() as session:
            from app.models.workflow import WorkflowRun, WorkflowRunStep
            from app.services.visibility_service import get_run_graph

            run = _make_run()
            run.definition_snapshot = {
                "steps": [],
                "graph_definition": {
                    "edges": [
                        {"from": "step-a", "to": "step-b"},
                        {"from": "step-b", "to": "step-c"},
                    ]
                },
            }
            session.add(run)
            await session.commit()

            # Add two steps
            for step_id in ("step-a", "step-b"):
                step = WorkflowRunStep(
                    run_id=run.id,
                    step_id=step_id,
                    name=f"Step {step_id}",
                    status="completed",
                    duration_ms=100,
                    input_data={},
                )
                session.add(step)
            await session.commit()

            graph = await get_run_graph(session, run_id=run.id)
            assert graph["run_id"] == str(run.id)
            assert len(graph["nodes"]) == 2
            step_ids = {n["step_id"] for n in graph["nodes"]}
            assert "step-a" in step_ids
            assert "step-b" in step_ids
            # Edges from graph_definition
            assert len(graph["edges"]) == 2

        await engine.dispose()

    _run(_inner())


# ---------------------------------------------------------------------------
# update_visibility_index() tests
# ---------------------------------------------------------------------------


def test_update_visibility_index_upsert():
    """update_visibility_index() creates a row and then updates it."""

    async def _inner():
        engine, factory = await _make_engine_and_factory()
        async with factory() as session:
            from app.models.workflow import WorkflowRun
            from app.models.visibility import VisibilityIndex
            from app.services.visibility_service import update_visibility_index
            from sqlalchemy import select

            run = _make_run(status="running")
            session.add(run)
            await session.commit()

            # First call — should create the row
            await update_visibility_index(session, run_id=run.id)

            result = await session.execute(
                select(VisibilityIndex).where(VisibilityIndex.workflow_run_id == run.id)
            )
            vis = result.scalars().first()
            assert vis is not None
            assert vis.status == "running"

            # Update the run to completed
            run.status = "completed"
            run.completed_at = datetime.utcnow()
            session.add(run)
            await session.commit()

            # Second call — should update existing row
            await update_visibility_index(session, run_id=run.id)

            await session.refresh(vis)
            assert vis.status == "completed"
            assert vis.completed_at is not None

        await engine.dispose()

    _run(_inner())
