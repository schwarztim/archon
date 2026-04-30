"""Test doubles for activity runtime contracts. Used by W3-W4d worker tests.

Stub implementations of the four runtime callbacks plus a context factory
that fills every required field with a deterministic placeholder. Downstream
tests should override only the doubles they care about.

Import path matches the project convention (``app.services...`` rather than
``backend.app.services...``); tests run with ``backend/`` on ``PYTHONPATH``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.services.activity_runtime import ActivityContext


async def stub_heartbeat(details: dict[str, Any]) -> None:
    """Heartbeat double — accepts and discards details."""
    return None


async def stub_check_cancelled() -> None:
    """Cancellation double — never raises."""
    return None


async def stub_write_artifact(
    name: str,
    payload: bytes | str | dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    """Artifact writer double — returns a deterministic stub URI."""
    return f"artifact://stub/{name}/{uuid4()}"


async def stub_resolve_secret(secret_ref: str) -> str:
    """Secret resolver double — echoes the reference for verification."""
    return f"stub-secret-value-for:{secret_ref}"


def build_test_context(
    *,
    tenant_id: str | None = None,
    run_id: str | None = None,
    step_id: str | None = None,
    activity_type: str = "test.activity",
    queue_name: str = "default",
    attempt: int = 1,
    input_data: dict[str, Any] | None = None,
    node_config: dict[str, Any] | None = None,
) -> ActivityContext:
    """Construct an ``ActivityContext`` populated with safe defaults.

    Callers may override any of the parameters; everything not named is
    filled with a fresh UUID or a sensible placeholder so the resulting
    context passes ``ActivityContext`` validation without further setup.
    """
    return ActivityContext(
        tenant_id=tenant_id or "00000000-0000-0000-0000-000000000001",
        run_id=run_id or str(uuid4()),
        step_id=step_id or str(uuid4()),
        task_id=str(uuid4()),
        queue_name=queue_name,
        activity_type=activity_type,
        attempt=attempt,
        idempotency_key=str(uuid4()),
        input_data=input_data or {},
        node_config=node_config or {},
        definition_snapshot={},
        db_session=None,
        worker_id="test-worker",
        trace_id=None,
        correlation_id=None,
        heartbeat=stub_heartbeat,
        check_cancelled=stub_check_cancelled,
        write_artifact=stub_write_artifact,
        resolve_secret=stub_resolve_secret,
    )


__all__ = [
    "build_test_context",
    "stub_check_cancelled",
    "stub_heartbeat",
    "stub_resolve_secret",
    "stub_write_artifact",
]
