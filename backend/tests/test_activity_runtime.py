"""Behavioural tests for the W3 ActivityRuntime.

Covers the runtime contract described in the W3 worker plan:

    - persists ActivityExecution row (status='running' on insert,
      terminal status on finalise, error_code/message on failure,
      retry_after_seconds on retry_scheduled, non_retryable on
      explicit non-retryable failure)
    - heartbeat callback buffers calls (≤1 row update under tight loop)
    - final heartbeat flush on success and on failure paths
    - cancellation propagates as ActivityCancelled and yields
      status='cancelled'
    - executor exception is caught and persisted as failed
    - artifact writer URI follows ``artifact://{tenant_id}/{kind}/{uuid}``
    - resolve_secret delegates to the injected resolver
    - concurrent activities don't collide on row IDs

All tests run against an in-memory SQLite database with
``activity_executions`` (and the upstream tables it FKs to) created via
``SQLModel.metadata.create_all``. The runtime accepts a custom
``db_session_factory`` so we don't need to monkey-patch the global one.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Quietens import-time side effects in some app modules.
os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services.activity_runtime import (  # noqa: E402
    ActivityCancelled,
    ActivityContext,
    ActivityResult,
    ActivityRuntime,
    adapt_legacy_executor,
)
from app.services.activity_runtime_test_doubles import (  # noqa: E402
    build_test_context,
    stub_check_cancelled,
    stub_heartbeat,
    stub_resolve_secret,
    stub_write_artifact,
)


SQLITE_URL = "sqlite+aiosqlite:///:memory:"
TENANT_UUID = UUID("11111111-1111-1111-1111-111111111111")


# ── In-memory SQLite + factory ────────────────────────────────────────


async def _make_engine_and_factory():
    """Build an in-memory SQLite engine with all tables created."""
    # Touch every model module so SQLModel.metadata is fully populated.
    from app.models import (  # noqa: F401
        Agent,
        ActivityExecution,
        Execution,
        User,
    )
    from app.models.workflow import (  # noqa: F401
        Workflow,
        WorkflowRun,
        WorkflowRunEvent,
        WorkflowRunStep,
    )
    from app.models.task_queue import Task, TaskQueue  # noqa: F401

    engine = create_async_engine(SQLITE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _seed_workflow_run(factory) -> UUID:
    """Insert a minimal Workflow + WorkflowRun and return run.id."""
    from app.models.workflow import Workflow, WorkflowRun

    async with factory() as session:
        wf = Workflow(name="rt-test", steps=[], graph_definition={})
        session.add(wf)
        await session.commit()
        await session.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            kind="workflow",
            status="queued",
            definition_snapshot={"kind": "workflow", "name": "rt-test"},
            tenant_id=TENANT_UUID,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


def _build_runtime_context(
    *,
    run_id: UUID,
    activity_type: str = "test.activity",
    attempt: int = 1,
    heartbeat=None,
    check_cancelled=None,
    write_artifact=None,
    resolve_secret=None,
    input_data: dict[str, Any] | None = None,
) -> ActivityContext:
    return ActivityContext(
        tenant_id=str(TENANT_UUID),
        run_id=str(run_id),
        step_id="s-1",
        task_id=None,
        queue_name="default",
        activity_type=activity_type,
        attempt=attempt,
        idempotency_key=str(uuid4()),
        input_data=input_data or {},
        node_config={},
        definition_snapshot={},
        db_session=None,
        worker_id="worker-test",
        trace_id=None,
        correlation_id=None,
        heartbeat=heartbeat or stub_heartbeat,
        check_cancelled=check_cancelled or stub_check_cancelled,
        write_artifact=write_artifact or stub_write_artifact,
        resolve_secret=resolve_secret or stub_resolve_secret,
    )


class _CountingArtifactService:
    """Sync artifact_service double — returns a UUID id and counts calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def store_artifact(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)

        class _Stub:
            id = uuid4()

        return _Stub()


class _NoopArtifactService:
    def store_artifact(self, **_kwargs: Any) -> Any:
        class _Stub:
            id = uuid4()

        return _Stub()


async def _resolve_stub(secret_ref: str) -> str:
    return f"resolved:{secret_ref}"


async def _read_execution_row(factory, exec_id: UUID):
    """Convenience read of the ActivityExecution row."""
    from app.models.activity import ActivityExecution

    async with factory() as session:
        return await session.get(ActivityExecution, exec_id)


async def _list_execution_rows(factory, run_id: UUID):
    from app.models.activity import ActivityExecution

    async with factory() as session:
        stmt = select(ActivityExecution).where(ActivityExecution.run_id == run_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())


# ── 1: Completed activity persists row ────────────────────────────────


def test_completed_activity_persists_execution_row() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            artifact_svc = _CountingArtifactService()
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=artifact_svc,
                secrets_resolver=_resolve_stub,
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                return ActivityResult(
                    status="completed",
                    output_data={"answer": 42},
                )

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)
            assert result.status == "completed"

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.status == "completed"
            assert row.completed_at is not None
            assert row.error_code is None
            assert row.error_message is None
            assert row.attempt_number == 1
            assert row.activity_type == "test.activity"
            # output_data was populated -> output_ref must point at an
            # artifact and follow the spec format.
            assert row.output_ref is not None
            assert row.output_ref.startswith(
                f"artifact://{TENANT_UUID}/activity_output/"
            )
            assert len(artifact_svc.calls) == 1
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 2: Failed activity sets error_code + error_message ────────────────


def test_failed_activity_sets_error_code_and_status() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(_ctx: ActivityContext) -> ActivityResult:
                return ActivityResult(
                    status="failed",
                    error_code="UpstreamTimeout",
                    error_message="downstream API timed out",
                )

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)
            assert result.status == "failed"

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.status == "failed"
            assert row.error_code == "UpstreamTimeout"
            assert row.error_message == "downstream API timed out"
            assert row.completed_at is not None
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 3: Cancelled activity ─────────────────────────────────────────────


def test_cancelled_activity_sets_cancelled_status() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)

            async def _check_cancelled() -> None:
                raise ActivityCancelled("operator cancel")

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                # The runtime supplies its own check_cancelled wrapper that
                # delegates to ours; calling it from the executor must raise.
                await ctx.check_cancelled()
                return ActivityResult(status="completed")  # unreachable

            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )
            ctx = _build_runtime_context(
                run_id=run_id,
                check_cancelled=_check_cancelled,
            )
            result = await runtime.execute(ctx, _executor)
            assert result.status == "cancelled"

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            assert rows[0].status == "cancelled"
            assert rows[0].completed_at is not None
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 4: Heartbeat buffer throttles writes ──────────────────────────────


def test_heartbeat_buffer_throttles_writes() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            # Use a long-ish buffer window so a tight 100x heartbeat loop
            # collapses to ≤1 mid-execution flush. The terminal flush adds
            # at most one more update — we assert ≤2 to bound that.
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
                heartbeat_buffer_ms=500,
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                t0 = time.monotonic()
                count = 0
                while (time.monotonic() - t0) < 0.1:  # ~100ms
                    await ctx.heartbeat({"i": count})
                    count += 1
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id)
            await runtime.execute(ctx, _executor)

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            # Terminal flush guarantees heartbeat_at is set.
            assert row.heartbeat_at is not None
            # Bound on row updates is observable via the persisted blob:
            # the latest "i" must be the last one (or close to it). We
            # don't assert an exact number of UPDATEs because SQLite
            # doesn't expose write count cheaply; the throttle is
            # asserted by the implementation invariant (only one flush
            # per buffer window) — the contract test below covers that.
            assert "i" in row.heartbeat_details
        finally:
            await engine.dispose()

    asyncio.run(runner())


def test_heartbeat_throttle_collapses_tight_loop() -> None:
    """Direct invariant test — the buffer drops intermediate calls."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)

            update_calls = {"count": 0}

            class _Spy(ActivityRuntime):
                async def _update_heartbeat(self, *, execution_id, details):
                    update_calls["count"] += 1
                    return await super()._update_heartbeat(
                        execution_id=execution_id, details=details
                    )

            runtime = _Spy(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
                heartbeat_buffer_ms=10_000,  # effectively never flushes mid-run
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                for i in range(100):
                    await ctx.heartbeat({"i": i})
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id)
            await runtime.execute(ctx, _executor)

            # 100 heartbeat calls collapsed to:
            #   * 1 fast-path flush at the very first call (last_flush_ms
            #     starts at 0, so the first call clears the debounce);
            #   * 0 mid-loop flushes (10s buffer never elapses inside
            #     the executor body);
            #   * 1 terminal force-flush from the runtime's finally block.
            # That's a strict upper bound of 2 — still ≪ 100.
            assert update_calls["count"] <= 2, (
                f"expected ≤2 heartbeat row updates under throttle, got "
                f"{update_calls['count']}"
            )
            # Also assert we genuinely throttled — 100 buffered calls
            # must NOT have produced 100 (or anywhere near) updates.
            assert update_calls["count"] < 10, (
                "throttle did not collapse the tight heartbeat loop"
            )
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 5 + 6: Final heartbeat flush on success and failure ───────────────


def test_final_heartbeat_flush_on_success() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
                heartbeat_buffer_ms=10_000,
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                await ctx.heartbeat({"phase": "midway"})
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id)
            await runtime.execute(ctx, _executor)

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.heartbeat_at is not None
            assert row.heartbeat_details.get("phase") == "midway"
        finally:
            await engine.dispose()

    asyncio.run(runner())


def test_final_heartbeat_flush_on_failure() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
                heartbeat_buffer_ms=10_000,
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                await ctx.heartbeat({"phase": "before-fail"})
                raise RuntimeError("boom")

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)
            assert result.status == "failed"
            assert result.error_code == "RuntimeError"

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.status == "failed"
            assert row.heartbeat_at is not None
            assert row.heartbeat_details.get("phase") == "before-fail"
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 7: non_retryable=True ─────────────────────────────────────────────


def test_non_retryable_result_sets_status_failed_no_retry() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(_ctx: ActivityContext) -> ActivityResult:
                return ActivityResult(
                    status="failed",
                    non_retryable=True,
                    error_code="ValidationError",
                    error_message="schema mismatch",
                )

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)
            assert result.status == "failed"
            assert result.non_retryable is True

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.status == "failed"
            assert row.non_retryable is True
            assert row.error_code == "ValidationError"
            assert row.retry_after_seconds is None
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 8: retry_scheduled records retry_after_seconds ────────────────────


def test_retry_scheduled_result_records_retry_after_seconds() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(_ctx: ActivityContext) -> ActivityResult:
                return ActivityResult(
                    status="retry_scheduled",
                    retry_after_seconds=42,
                    error_code="TransientNetworkError",
                    error_message="reset by peer",
                )

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)
            assert result.status == "retry_scheduled"
            assert result.retry_after_seconds == 42

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.status == "retry_scheduled"
            assert row.retry_after_seconds == 42
            assert row.error_code == "TransientNetworkError"
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 9: Executor exception is caught and persisted ─────────────────────


def test_executor_exception_is_caught_and_persisted_as_failed() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(_ctx: ActivityContext) -> ActivityResult:
                raise ValueError("bad input")

            ctx = _build_runtime_context(run_id=run_id)
            # Runtime swallows the exception per contract; returns a
            # synthetic failed ActivityResult.
            result = await runtime.execute(ctx, _executor)
            assert result.status == "failed"
            assert result.error_code == "ValueError"
            assert result.error_message and "bad input" in result.error_message

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.status == "failed"
            assert row.error_code == "ValueError"
            assert "bad input" in (row.error_message or "")
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 10: Artifact writer URI format ────────────────────────────────────


def test_artifact_writer_uri_format() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            artifact_svc = _CountingArtifactService()
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=artifact_svc,
                secrets_resolver=_resolve_stub,
            )

            captured: dict[str, str] = {}

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                # Use the runtime-supplied write_artifact callback, which
                # forwards to ActivityRuntime._persist_artifact and
                # builds the URI itself.
                uri = await ctx.write_artifact(
                    "diagnostic.json",
                    {"k": "v"},
                    {"role": "diagnostic"},
                )
                captured["uri"] = uri
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id)
            await runtime.execute(ctx, _executor)

            uri = captured["uri"]
            # Expected shape: artifact://{tenant_id}/{kind}/{uuid}
            assert uri.startswith(f"artifact://{TENANT_UUID}/activity_output/")
            tail = uri.split("/")[-1]
            # Last segment must parse as a UUID.
            UUID(tail)
            # The artifact service was invoked at least once for the
            # write_artifact call (and possibly again for output_data;
            # in this test output_data is empty so exactly one).
            assert len(artifact_svc.calls) >= 1
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 11: resolve_secret delegates ──────────────────────────────────────


def test_resolve_secret_delegates_to_provided_resolver() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            captured: dict[str, str] = {}

            async def _resolver(ref: str) -> str:
                captured["ref"] = ref
                return "the-secret-value"

            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolver,
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                value = await ctx.resolve_secret("vault://api/key")
                assert value == "the-secret-value"
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)
            assert result.status == "completed"
            assert captured["ref"] == "vault://api/key"
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── 12: Concurrent executions don't collide ───────────────────────────


def test_concurrent_activity_executions_dont_collide() -> None:
    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(_ctx: ActivityContext) -> ActivityResult:
                # Yield twice to force interleaving with the sibling.
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                return ActivityResult(status="completed")

            ctx_a = _build_runtime_context(
                run_id=run_id, activity_type="conc.a", attempt=1
            )
            ctx_b = _build_runtime_context(
                run_id=run_id, activity_type="conc.b", attempt=1
            )

            results = await asyncio.gather(
                runtime.execute(ctx_a, _executor),
                runtime.execute(ctx_b, _executor),
            )
            assert all(r.status == "completed" for r in results)

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 2
            ids = {r.id for r in rows}
            assert len(ids) == 2  # distinct primary keys
            types = sorted(r.activity_type for r in rows)
            assert types == ["conc.a", "conc.b"]
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── Bonus: invariant — running row inserted before executor body runs ──


def test_running_row_visible_to_executor_via_db_lookup() -> None:
    """Strengthens the persistence ordering contract for downstream tests."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            observed_states: list[str] = []

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                from app.models.activity import ActivityExecution

                async with factory() as session:
                    stmt = select(ActivityExecution).where(
                        ActivityExecution.run_id == UUID(ctx.run_id)
                    )
                    result = await session.execute(stmt)
                    rows = list(result.scalars().all())
                    if rows:
                        observed_states.append(rows[0].status)
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id)
            await runtime.execute(ctx, _executor)
            assert observed_states == ["running"]
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── adapt_legacy_executor: success path ──────────────────────────────


def test_adapt_legacy_executor_bridges_dict_interface() -> None:
    """Legacy dict-in/dict-out executor produces a completed ActivityResult."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def legacy_fn(state: dict) -> dict:
                return {"result": state.get("x", 0) * 2, "processed": True}

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                return await adapt_legacy_executor(legacy_fn, ctx)

            ctx = _build_runtime_context(run_id=run_id, input_data={"x": 21})
            result = await runtime.execute(ctx, _executor)

            assert result.status == "completed"
            assert result.output_data["result"] == 42
            assert result.output_data["processed"] is True

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            assert rows[0].status == "completed"
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── adapt_legacy_executor: error key in returned dict ────────────────


def test_adapt_legacy_executor_error_key_yields_failed_result() -> None:
    """A legacy executor returning {'error': ...} maps to status='failed'."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def legacy_fn(state: dict) -> dict:
                return {"error": "upstream unavailable", "code": 503}

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                return await adapt_legacy_executor(legacy_fn, ctx)

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)

            assert result.status == "failed"
            assert result.error_code == "LegacyExecutorError"
            assert "upstream unavailable" in (result.error_message or "")
            # Non-error keys still appear in output_data.
            assert result.output_data.get("code") == 503
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── test_execute_activity_creates_execution_row (named alias) ─────────


def test_execute_activity_creates_execution_row() -> None:
    """An execute call inserts one ActivityExecution row with status=running
    before the executor body, then finalises it to completed on exit."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id, attempt=1)
            await runtime.execute(ctx, _executor)

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            assert rows[0].status == "completed"
            assert rows[0].attempt_number == 1
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── test_execute_activity_increments_attempt_on_retry ────────────────


def test_execute_activity_increments_attempt_on_retry() -> None:
    """Each call with a higher attempt number produces a separate row."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(_ctx: ActivityContext) -> ActivityResult:
                return ActivityResult(status="failed", error_code="Transient")

            ctx1 = _build_runtime_context(run_id=run_id, attempt=1)
            ctx2 = _build_runtime_context(run_id=run_id, attempt=2)

            await runtime.execute(ctx1, _executor)
            await runtime.execute(ctx2, _executor)

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 2
            attempt_numbers = sorted(r.attempt_number for r in rows)
            assert attempt_numbers == [1, 2]
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── test_heartbeat_updates_execution_details (named alias) ───────────


def test_heartbeat_updates_execution_details() -> None:
    """Heartbeat callback writes details into the ActivityExecution row."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
                heartbeat_buffer_ms=0,  # flush immediately
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                await ctx.heartbeat({"progress": "50%", "items_done": 5})
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id)
            await runtime.execute(ctx, _executor)

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.heartbeat_at is not None
            assert row.heartbeat_details.get("progress") == "50%"
            assert row.heartbeat_details.get("items_done") == 5
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── test_cancel_check_raises_on_cancelled_run (named alias) ──────────


def test_cancel_check_raises_on_cancelled_run() -> None:
    """check_cancelled raises ActivityCancelled and the row is persisted as cancelled."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)

            async def _cancelling() -> None:
                raise ActivityCancelled("cancelled by operator")

            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(ctx: ActivityContext) -> ActivityResult:
                await ctx.check_cancelled()
                return ActivityResult(status="completed")

            ctx = _build_runtime_context(run_id=run_id, check_cancelled=_cancelling)
            result = await runtime.execute(ctx, _executor)

            assert result.status == "cancelled"
            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            assert rows[0].status == "cancelled"
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── test_result_persists_to_execution_row (named alias) ──────────────


def test_result_persists_to_execution_row() -> None:
    """ActivityResult fields (error_code, retry_after_seconds, non_retryable) are
    persisted to the ActivityExecution row accurately."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(_ctx: ActivityContext) -> ActivityResult:
                return ActivityResult(
                    status="retry_scheduled",
                    retry_after_seconds=30,
                    error_code="RateLimited",
                    error_message="quota exceeded",
                    non_retryable=False,
                )

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)

            assert result.retry_after_seconds == 30
            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            row = rows[0]
            assert row.retry_after_seconds == 30
            assert row.error_code == "RateLimited"
            assert "quota exceeded" in (row.error_message or "")
            assert row.non_retryable is False
        finally:
            await engine.dispose()

    asyncio.run(runner())


# ── test_retry_scheduled_sets_retry_after (named alias) ──────────────


def test_retry_scheduled_sets_retry_after() -> None:
    """retry_after_seconds from ActivityResult lands on the execution row."""

    async def runner() -> None:
        engine, factory = await _make_engine_and_factory()
        try:
            run_id = await _seed_workflow_run(factory)
            runtime = ActivityRuntime(
                db_session_factory=factory,
                artifact_service=_NoopArtifactService(),
                secrets_resolver=_resolve_stub,
            )

            async def _executor(_ctx: ActivityContext) -> ActivityResult:
                return ActivityResult(
                    status="retry_scheduled",
                    retry_after_seconds=120,
                )

            ctx = _build_runtime_context(run_id=run_id)
            result = await runtime.execute(ctx, _executor)

            assert result.status == "retry_scheduled"
            assert result.retry_after_seconds == 120

            rows = await _list_execution_rows(factory, run_id)
            assert len(rows) == 1
            assert rows[0].retry_after_seconds == 120
            assert rows[0].status == "retry_scheduled"
        finally:
            await engine.dispose()

    asyncio.run(runner())
