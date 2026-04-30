# Test fixtures and shared helpers for node executor tests.
from __future__ import annotations

from typing import Any, Callable
from unittest.mock import MagicMock

from app.services.node_executors import NodeContext


def make_ctx(
    node_type: str = "llmNode",
    config: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    tenant_id: str | None = "test-tenant",
    db_session: Any | None = None,
    *,
    cancel_check: Callable[[], bool] | None = None,
    node_data_extra: dict[str, Any] | None = None,
) -> NodeContext:
    """Build a minimal NodeContext for testing.

    Optional kwargs (Phase 3 / WS9):
      cancel_check     — callable returning True to signal cancellation; defaults to no-op
      node_data_extra  — extra keys merged into ``node_data`` alongside ``config``
                         (used by approval / delay nodes which probe ``node_data``
                         for ``run_id`` etc.).
    """
    step_data: dict[str, Any] = {"config": config or {}}
    if node_data_extra:
        step_data.update(node_data_extra)
    return NodeContext(
        step_id="test-step-1",
        node_type=node_type,
        node_data=step_data,
        inputs=inputs or {},
        tenant_id=tenant_id,
        secrets=MagicMock(),
        db_session=db_session,
        cancel_check=cancel_check or (lambda: False),
    )
