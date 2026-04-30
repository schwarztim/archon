"""Node executor registry and base contract.

Each node type in the visual builder maps to one NodeExecutor subclass.
The registry is keyed by the canonical frontend type name (e.g. ``llmNode``).

Usage::

    from app.services.node_executors import NODE_EXECUTORS, NodeContext, NodeResult

    executor = NODE_EXECUTORS.get(step["type"])
    if executor:
        result = await executor.execute(ctx)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class NodeContext:
    """Runtime context passed to every executor."""

    step_id: str
    node_type: str
    node_data: dict[str, Any]
    inputs: dict[str, Any]  # upstream step outputs keyed by step_id
    tenant_id: str | None
    secrets: Any  # secrets manager handle
    db_session: Any  # AsyncSession (may be None in tests)
    cancel_check: Callable[[], bool] = field(default=lambda: False)

    # Convenience accessor: node configuration sub-dict
    @property
    def config(self) -> dict[str, Any]:
        return self.node_data.get("config") or {}


@dataclass
class NodeResult:
    """Structured result returned by every executor."""

    status: str  # "completed" | "failed" | "paused" | "skipped"
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    paused_reason: str | None = None  # populated by human_approval
    token_usage: dict[str, int] | None = None
    cost_usd: float | None = None


class NodeExecutor(ABC):
    """Abstract base for all node executors."""

    @abstractmethod
    async def execute(self, ctx: NodeContext) -> NodeResult: ...


# ---------------------------------------------------------------------------
# Registry + decorator
# ---------------------------------------------------------------------------

NODE_EXECUTORS: dict[str, NodeExecutor] = {}


def register(node_type: str) -> Callable:
    """Class decorator that registers a NodeExecutor under *node_type*."""

    def decorator(cls: type[NodeExecutor]) -> type[NodeExecutor]:
        NODE_EXECUTORS[node_type] = cls()
        return cls

    return decorator


# ---------------------------------------------------------------------------
# Lazy import: ensure all executor modules are registered when this package
# is imported.  Import order does not matter because the registry is a plain
# dict populated at module load time.
# ---------------------------------------------------------------------------

from app.services.node_executors import (  # noqa: E402, F401 — side-effect imports
    condition,
    cost_gate,
    database_query,
    delay,
    dlp_scan,
    document_loader,
    embedding,
    function_call,
    http_request,
    human_approval,
    human_input,
    input_node,
    llm,
    loop,
    mcp_tool,
    merge,
    output_node,
    parallel,
    schedule_trigger,
    stream_output,
    structured_output,
    sub_agent,
    sub_workflow,
    switch,
    tool,
    vector_search,
    vision,
    webhook_trigger,
)

# Phase 3 / WS9 — production-readiness classification + stub-block gate.
# Re-exported so callers (run_dispatcher, tests, ops tooling) can import
# from the node_executors package without reaching into private modules.
from app.services.node_executors._stub_block import (  # noqa: E402, F401
    StubBlockError,
    assert_node_runnable,
)
from app.services.node_executors.status_registry import (  # noqa: E402, F401
    NODE_STATUS,
    NodeStatus,
    get_status,
    is_runnable_in_production,
    list_by_status,
)
