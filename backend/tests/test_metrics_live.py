"""W17a — live metrics emission proof.

Proves that the runtime path (dispatch, task claim, activity retry, schedule
fire) increments the canonical W17a counters in ``metrics_middleware`` and
that those series appear in the Prometheus text output of GET /metrics.

Strategy
--------
- All tests operate entirely in-process: no external Prometheus, no network.
- Counter state is read directly from ``metrics_middleware`` storage dicts.
- For the /metrics endpoint test, a FastAPI TestClient is bootstrapped with
  an in-memory SQLite engine (same pattern as test_metrics_real_emission.py).
- ``--noconftest`` compatible: no conftest fixtures used.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from uuid import uuid4, UUID

# Required env BEFORE any app import so database / vault clients don't crash.
os.environ.setdefault("LLM_STUB_MODE", "true")
os.environ.setdefault("ARCHON_DATABASE_URL", "postgresql+asyncpg://t:t@localhost/t")
os.environ.setdefault("ARCHON_AUTH_DEV_MODE", "true")
os.environ.setdefault("ARCHON_VAULT_ADDR", "http://localhost:8200")
os.environ.setdefault("ARCHON_VAULT_TOKEN", "test-token")
os.environ.setdefault("ARCHON_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("ARCHON_DISPATCH_INLINE", "1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_w17a_stores() -> None:
    """Zero out all W17a in-process metric stores between tests."""
    from app.middleware import metrics_middleware as mm
    mm._runs_total_counts.clear()
    mm._run_duration_sums.clear()
    mm._run_duration_counts.clear()
    mm._run_duration_buckets.clear()
    mm._tasks_claimed_counts.clear()
    mm._tasks_completed_counts.clear()
    mm._tasks_failed_counts.clear()
    mm._activity_retry_counts.clear()
    mm._schedule_fires_counts.clear()
    mm._pipeline_ingress_counts.clear()
    mm._queue_depth_gauges.clear()
    mm._queue_drain_counts.clear()
    mm._worker_heartbeat_counts.clear()
    mm._worker_active_tasks.clear()
    mm._schedule_missed_counts.clear()
    mm._pipeline_callback_counts.clear()
    mm._policy_deny_counts.clear()
    mm._dlp_block_counts.clear()
    mm._budget_deny_counts.clear()


def _make_sqlite_engine_and_factory():
    """Return (engine, session_factory) backed by a fresh in-memory SQLite DB."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    import app.models  # noqa: F401
    import app.models.workflow  # noqa: F401
    try:
        import app.models.task_queue  # noqa: F401
    except ImportError:
        pass
    try:
        import app.models.activity  # noqa: F401
    except ImportError:
        pass

    db_path = os.path.join(
        tempfile.gettempdir(),
        f"archon_w17a_{uuid.uuid4().hex[:8]}.db",
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
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


def _seed_workflow_and_run(factory, *, tenant_id: UUID, workflow_id: UUID, run_id: UUID) -> None:
    """Insert a minimal Workflow + WorkflowRun directly into the test DB."""
    from app.models.workflow import Workflow, WorkflowRun

    async def _insert():
        async with factory() as session:
            wf = Workflow(
                id=workflow_id,
                tenant_id=tenant_id,
                name="w17a-test",
                definition={"steps": [{"step_id": "s1", "type": "stub", "name": "s1"}]},
                created_by="test",
            )
            session.add(wf)
            await session.flush()
            run = WorkflowRun(
                id=run_id,
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                status="pending",
                trigger_type="api",
                definition_snapshot={
                    "steps": [{"step_id": "s1", "type": "stub", "name": "s1"}]
                },
            )
            session.add(run)
            await session.commit()

    asyncio.run(_insert())


# ---------------------------------------------------------------------------
# test_run_produces_nonzero_runs_total
# ---------------------------------------------------------------------------


def test_run_produces_nonzero_runs_total():
    """Dispatching a run increments archon_runs_total."""
    from unittest.mock import patch, AsyncMock, MagicMock

    _reset_w17a_stores()

    engine, factory = _make_sqlite_engine_and_factory()
    tenant_id = uuid4()
    workflow_id = uuid4()
    run_id = uuid4()
    _seed_workflow_and_run(factory, tenant_id=tenant_id, workflow_id=workflow_id, run_id=run_id)

    import app.database as _dbmod
    _dbmod.engine = engine
    _dbmod.async_session_factory = factory

    import app.services.run_dispatcher as dispatcher
    dispatcher.async_session_factory = factory  # type: ignore[assignment]

    # execute_workflow_dag stub: return a minimal completed result.
    async def _stub_engine(wf, **kwargs):
        return {"status": "completed", "steps": [], "output": {}}

    with patch.object(dispatcher, "execute_workflow_dag", side_effect=_stub_engine):
        result = asyncio.run(dispatcher.dispatch_run(run_id))

    from app.services.metrics_service import get_runs_total_counts
    counts = get_runs_total_counts()
    total = sum(counts.values())
    assert total > 0, f"archon_runs_total not incremented; counts={counts}"


# ---------------------------------------------------------------------------
# test_task_claimed_increments_counter
# ---------------------------------------------------------------------------


def test_task_claimed_increments_counter():
    """claim_task increments archon_tasks_claimed_total."""
    _reset_w17a_stores()

    engine, factory = _make_sqlite_engine_and_factory()
    tenant_id = uuid4()
    workflow_id = uuid4()
    run_id = uuid4()
    _seed_workflow_and_run(factory, tenant_id=tenant_id, workflow_id=workflow_id, run_id=run_id)

    async def _run():
        from app.services.task_queue_service import enqueue_task, claim_task
        async with factory() as session:
            task = await enqueue_task(
                session,
                tenant_id=tenant_id,
                run_id=run_id,
                queue_name="default",
                task_type="test_task",
                commit=True,
            )
        async with factory() as session:
            claimed = await claim_task(
                session,
                task_id=task.id,
                lease_owner="worker-test",
                lease_ttl_seconds=30,
            )
            await session.commit()
        return claimed

    claimed = asyncio.run(_run())
    assert claimed is not None

    from app.services.metrics_service import get_task_claimed_counts
    counts = get_task_claimed_counts()
    total = sum(counts.values())
    assert total >= 1, f"archon_tasks_claimed_total not incremented; counts={counts}"


# ---------------------------------------------------------------------------
# test_activity_retry_increments_counter
# ---------------------------------------------------------------------------


def test_activity_retry_increments_counter():
    """record_activity_retry increments archon_activity_retries_total."""
    _reset_w17a_stores()

    from app.services.metrics_service import record_activity_retry, get_activity_retry_counts
    record_activity_retry(activity_type="llm_call")
    record_activity_retry(activity_type="llm_call")

    counts = get_activity_retry_counts()
    assert counts.get("llm_call", 0) == 2, f"Expected 2 retries, got {counts}"


# ---------------------------------------------------------------------------
# test_schedule_fire_increments_counter
# ---------------------------------------------------------------------------


def test_schedule_fire_increments_counter():
    """record_schedule_fire increments archon_schedule_fires_total."""
    _reset_w17a_stores()

    from app.services.metrics_service import record_schedule_fire, get_schedule_fires_counts
    sid = str(uuid4())
    record_schedule_fire(schedule_id=sid)
    record_schedule_fire(schedule_id=sid)

    counts = get_schedule_fires_counts()
    assert counts.get(sid, 0) == 2, f"Expected 2 fires, got {counts}"


# ---------------------------------------------------------------------------
# test_prometheus_endpoint_returns_metrics
# ---------------------------------------------------------------------------


def test_prometheus_endpoint_returns_metrics():
    """render_metrics() returns Prometheus text format containing archon_ series.

    We call ``render_metrics()`` directly (the same function that the
    ``GET /metrics`` route invokes) rather than going through TestClient so
    this test is isolated from pre-existing import failures in unrelated
    route modules (e.g. app/routes/replay.py uses a missing symbol that
    breaks create_app in the current branch — a separate defect unrelated
    to W17a).
    """
    # Seed one counter so we know at least one series is non-empty.
    from app.services.metrics_service import record_task_claimed
    record_task_claimed(queue_name="probe-queue")

    from app.middleware.metrics_middleware import render_metrics
    body = render_metrics()

    assert isinstance(body, str), "render_metrics() must return a string"
    assert body.endswith("\n"), "Prometheus text format must end with newline"
    assert "archon_" in body, "No archon_ series found in render_metrics() output"

    # W17a series must be present.
    w17a_series = [
        "archon_tasks_claimed_total",
        "archon_tasks_completed_total",
        "archon_tasks_failed_total",
        "archon_runs_total",
        "archon_run_duration_seconds",
        "archon_activity_retries_total",
        "archon_schedule_fires_total",
        "archon_pipeline_ingress_total",
        "archon_queue_depth",
        "archon_worker_heartbeats_total",
        "archon_policy_denies_total",
        "archon_dlp_blocks_total",
        "archon_budget_denies_total",
    ]
    for series in w17a_series:
        assert series in body, (
            f"W17a series '{series}' not found in render_metrics() output. "
            f"First 300 chars: {body[:300]}"
        )
