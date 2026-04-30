"""Contract-type tests for the W3 activity runtime + W1/W2 model surfaces.

These are interface tests — they verify the type contracts that downstream
workers (W4a-d, W1.5 dispatcher polling) build against. No business logic
is exercised; the runtime stubs intentionally raise ``NotImplementedError``.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from app.models.task_queue import Task, TaskQueue
from app.models.worker_registry import WorkerRegistration
from app.services.activity_runtime import (
    ActivityContext,
    ActivityResult,
    execute_activity,
)
from app.services.activity_runtime_test_doubles import build_test_context


# ── ActivityContext ───────────────────────────────────────────────────


def test_activity_context_has_required_fields() -> None:
    """Every plan-spec field is present and accessible on ActivityContext."""
    ctx = build_test_context()

    # Identity / routing.
    assert isinstance(ctx.tenant_id, str)
    assert isinstance(ctx.run_id, str)
    assert isinstance(ctx.step_id, str)
    assert ctx.task_id is None or isinstance(ctx.task_id, str)
    assert isinstance(ctx.queue_name, str)
    assert isinstance(ctx.activity_type, str)
    assert isinstance(ctx.attempt, int)
    assert isinstance(ctx.idempotency_key, str)

    # Payload.
    assert isinstance(ctx.input_data, dict)
    assert isinstance(ctx.node_config, dict)
    assert isinstance(ctx.definition_snapshot, dict)

    # Execution context.
    assert hasattr(ctx, "db_session")
    assert isinstance(ctx.worker_id, str)
    assert ctx.trace_id is None or isinstance(ctx.trace_id, str)
    assert ctx.correlation_id is None or isinstance(ctx.correlation_id, str)

    # Callbacks must be callable (Protocol satisfaction is structural).
    assert callable(ctx.heartbeat)
    assert callable(ctx.check_cancelled)
    assert callable(ctx.write_artifact)
    assert callable(ctx.resolve_secret)


def test_activity_context_is_frozen() -> None:
    """ActivityContext is frozen — mutation raises FrozenInstanceError."""
    ctx = build_test_context()
    field_names = {f.name for f in dataclasses.fields(ActivityContext)}
    expected = {
        "tenant_id",
        "run_id",
        "step_id",
        "task_id",
        "queue_name",
        "activity_type",
        "attempt",
        "idempotency_key",
        "input_data",
        "node_config",
        "definition_snapshot",
        "db_session",
        "worker_id",
        "trace_id",
        "correlation_id",
        "heartbeat",
        "check_cancelled",
        "write_artifact",
        "resolve_secret",
    }
    assert field_names == expected, (
        f"unexpected ActivityContext field set; missing={expected - field_names}, "
        f"extra={field_names - expected}"
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.attempt = 99  # type: ignore[misc]


# ── ActivityResult ────────────────────────────────────────────────────


def test_activity_result_defaults() -> None:
    """ActivityResult fills all defaults correctly when only ``status`` is set."""
    result = ActivityResult(status="completed")
    assert result.status == "completed"
    assert result.output_data == {}
    assert result.artifacts == []
    assert result.metrics == {}
    assert result.heartbeat_details is None
    assert result.retry_after_seconds is None
    assert result.non_retryable is False
    assert result.error_code is None
    assert result.error_message is None


# ── TaskQueue + Task model surfaces ───────────────────────────────────


def test_taskqueue_columns() -> None:
    """TaskQueue + Task expose the W1-spec columns and indexes."""
    queue_columns = set(TaskQueue.__table__.columns.keys())
    expected_queue = {
        "id",
        "tenant_id",
        "name",
        "queue_type",
        "description",
        "max_dispatch_rate",
        "concurrency_limit",
        "retention_days",
        "paused",
        "created_at",
        "updated_at",
    }
    assert expected_queue.issubset(queue_columns), (
        f"missing TaskQueue columns: {expected_queue - queue_columns}"
    )

    task_columns = set(Task.__table__.columns.keys())
    expected_task = {
        "id",
        "tenant_id",
        "run_id",
        "step_id",
        "queue_name",
        "task_type",
        "payload_ref",
        "status",
        "visible_at",
        "attempts",
        "lease_owner",
        "lease_expiration",
        "priority",
        "idempotency_key",
        "created_at",
        "updated_at",
    }
    assert expected_task.issubset(task_columns), (
        f"missing Task columns: {expected_task - task_columns}"
    )

    # Polling and idempotency-unique indexes must exist on Task.
    task_index_names = {idx.name for idx in Task.__table__.indexes}
    assert "ix_task_polling" in task_index_names
    assert "ix_task_idempotency_unique" in task_index_names


# ── WorkerRegistration model surface ──────────────────────────────────


def test_workerregistration_columns() -> None:
    """WorkerRegistration exposes W2 columns and the stale-lookup index."""
    columns = set(WorkerRegistration.__table__.columns.keys())
    expected = {
        "id",
        "tenant_id",
        "worker_name",
        "worker_version",
        "environment",
        "queue_names",
        "capabilities",
        "max_concurrency",
        "started_at",
        "last_heartbeat_at",
        "status",
        "deployment_id",
        "current_load",
        "in_flight_task_count",
    }
    assert expected.issubset(columns), (
        f"missing WorkerRegistration columns: {expected - columns}"
    )

    index_names = {idx.name for idx in WorkerRegistration.__table__.indexes}
    assert "ix_workerregistration_stale_lookup" in index_names


# ── Runtime stub raises ───────────────────────────────────────────────


def test_runtime_callable_lands_in_w3() -> None:
    """``execute_activity`` is the W3-implemented entry — must be callable.

    Pre-W3 this test asserted the stub raised ``NotImplementedError``. W3
    landed the runtime body in ``app.services.activity_runtime`` so the
    contract obligation flips: the entry must be a coroutine function and
    must accept ``(ActivityContext, Awaitable[ActivityResult])``. The
    behavioural runtime tests live in ``test_activity_runtime.py``.
    """
    import inspect as _inspect

    assert _inspect.iscoroutinefunction(execute_activity), (
        "execute_activity must be an async callable for W3+"
    )
    sig = _inspect.signature(execute_activity)
    assert list(sig.parameters) == ["context", "executor"], (
        f"unexpected signature: {sig}"
    )
