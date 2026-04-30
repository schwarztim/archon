"""Shared fixtures for Phase 3 node-executor contract tests.

These fixtures are local to ``backend/tests/test_node_executors/`` and are
deliberately **light-weight**: every dependency that would touch the
network, the DB, or a real LLM provider is mocked.  Tests that need a
specific behaviour from a dependency override the fixture or patch the
target module directly.

Exposed fixtures
----------------

``stub_step_input``       — minimal valid step config for a node_type.
``mock_session``          — async DB session (AsyncMock).
``mock_run``              — minimal queued WorkflowRun-shaped object.
``record_events_helper``  — captures emitted events for assertion.
``make_ctx``               — builds a NodeContext (re-export of the
                             helper from ``tests/test_node_executors/__init__.py``
                             with extra hooks for cancel_check).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

# Tests in this package run in stub mode by default so the LLM node is
# deterministic regardless of the host environment.
os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services.node_executors import NodeContext  # noqa: E402


# ---------------------------------------------------------------------------
# Step-config presets
# ---------------------------------------------------------------------------

# Minimum-viable config per node_type.  These are the smallest dicts a node
# accepts without raising a validation error / returning ``status=failed``.
_MINIMAL_CONFIG: dict[str, dict[str, Any]] = {
    "llmNode": {"model": "gpt-3.5-turbo", "prompt": "Say hello"},
    "conditionNode": {"expression": "1 == 1"},
    "switchNode": {"expression": "'red'", "cases": [{"value": "red"}]},
    "parallelNode": {"executionMode": "all"},
    "loopNode": {"maxIterations": 3},
    "humanApprovalNode": {"prompt": "Approve?"},
    "dlpScanNode": {"actionOnViolation": "flag"},
    "costGateNode": {"maxUsd": 0},
    "subWorkflowNode": {"workflowId": "wf-123", "workflowDefinition": {"steps": []}},
    "subAgentNode": {"agentId": "agent-1"},
    "httpRequestNode": {"method": "GET", "url": "https://example.com/"},
    "databaseQueryNode": {"query": "SELECT 1", "connectorId": "pg1"},
    "functionCallNode": {"functionName": "noop"},
    "mergeNode": {"strategy": "all"},
    "delayNode": {"seconds": 0},
    "webhookTriggerNode": {},
    "scheduleTriggerNode": {"cron": "0 * * * *"},
    "inputNode": {},
    "outputNode": {},
    "streamOutputNode": {},
    "embeddingNode": {"model": "text-embedding-ada-002"},
    "visionNode": {"model": "gpt-4o", "imageUrl": "https://example.com/x.png"},
    "structuredOutputNode": {"model": "gpt-4o-mini", "schema": {}},
    "vectorSearchNode": {"collection": "docs"},
    "documentLoaderNode": {"source": "s3://bucket/file.pdf"},
    "humanInputNode": {"prompt": "Your name?"},
    "toolNode": {"toolName": "calc"},
    "mcpToolNode": {"serverName": "srv", "toolName": "search"},
}


@pytest.fixture()
def stub_step_input() -> Callable[..., dict[str, Any]]:
    """Return a builder that produces a minimal valid step config dict.

    Usage::

        cfg = stub_step_input("llmNode")           # → {"model": ..., "prompt": ...}
        cfg = stub_step_input("llmNode", model="gpt-4")
    """

    def _builder(node_type: str, **overrides: Any) -> dict[str, Any]:
        base = dict(_MINIMAL_CONFIG.get(node_type, {}))
        base.update(overrides)
        return base

    return _builder


# ---------------------------------------------------------------------------
# DB / run scaffolding
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_session() -> AsyncMock:
    """Async-flavoured DB session stand-in.

    ``execute`` returns a sync MagicMock so callers can chain ``.fetchone()``
    / ``.scalars()`` without async-await mismatches.
    """
    session = AsyncMock()

    exec_result = MagicMock()
    exec_result.fetchone.return_value = (0.0,)
    exec_result.fetchall.return_value = []
    exec_result.first.return_value = None
    exec_result.all.return_value = []
    exec_result.scalar.return_value = None
    scalars = MagicMock()
    scalars.first.return_value = None
    scalars.all.return_value = []
    exec_result.scalars.return_value = scalars

    session.execute = AsyncMock(return_value=exec_result)
    session.exec = AsyncMock(return_value=exec_result)
    session.flush = AsyncMock(return_value=None)
    session.commit = AsyncMock(return_value=None)
    session.rollback = AsyncMock(return_value=None)
    session.add = MagicMock()
    return session


@dataclass
class MockRun:
    """Minimal WorkflowRun shape used by tests that don't hit a real DB."""

    id: UUID = field(default_factory=uuid4)
    tenant_id: str | None = "test-tenant"
    workflow_id: str = "wf-123"
    status: str = "queued"
    paused_at: Any = None
    payload: dict[str, Any] = field(default_factory=dict)


@pytest.fixture()
def mock_run() -> MockRun:
    return MockRun()


# ---------------------------------------------------------------------------
# Event recorder
# ---------------------------------------------------------------------------


class _EventRecorder:
    """Captures (event_type, payload) tuples for later assertion."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        self.events.append((event_type, dict(payload or {})))

    # awaitable variant — many event services are async
    async def aemit(
        self, event_type: str, payload: dict[str, Any] | None = None
    ) -> None:
        self.emit(event_type, payload)

    def types(self) -> list[str]:
        return [t for t, _ in self.events]

    def payload_for(self, event_type: str) -> dict[str, Any] | None:
        for t, p in self.events:
            if t == event_type:
                return p
        return None


@pytest.fixture()
def record_events_helper() -> _EventRecorder:
    return _EventRecorder()


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


@pytest.fixture()
def make_ctx() -> Callable[..., NodeContext]:
    """Return a builder that produces a NodeContext per test."""

    def _build(
        node_type: str = "llmNode",
        config: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        tenant_id: str | None = "test-tenant",
        db_session: Any | None = None,
        cancel_check: Callable[[], bool] | None = None,
        node_data_extra: dict[str, Any] | None = None,
    ) -> NodeContext:
        node_data: dict[str, Any] = {"config": dict(config or {})}
        if node_data_extra:
            node_data.update(node_data_extra)
        return NodeContext(
            step_id="test-step-1",
            node_type=node_type,
            node_data=node_data,
            inputs=dict(inputs or {}),
            tenant_id=tenant_id,
            secrets=MagicMock(),
            db_session=db_session,
            cancel_check=cancel_check or (lambda: False),
        )

    return _build
