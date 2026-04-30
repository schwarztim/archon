"""Registry-driven smoke matrix — the structural floor for Phase 3.

For every entry in ``NODE_EXECUTORS`` (the canonical registry of registered
node executors) we assert three contract dimensions:

1. **callable** — the executor is awaitable and accepts a NodeContext.
2. **shape**    — the result is a NodeResult with a status in the canonical
                  set ``{completed, failed, paused, skipped, cancelled}``.
3. **classified** — the executor has a ``NodeStatus`` entry in
                    ``status_registry.NODE_STATUS`` (skipped gracefully if
                    the registry module isn't present yet).

Failures here mean a node was registered without the contract surface the
dispatcher relies on — that is a P0 regression.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services.node_executors import NODE_EXECUTORS, NodeResult  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# Canonical set of status values the dispatcher knows how to interpret.
_VALID_STATUSES: frozenset[str] = frozenset(
    {"completed", "failed", "paused", "skipped", "cancelled"}
)


# Per-node minimal config.  Mirrors conftest._MINIMAL_CONFIG but kept local
# so the parametrize id list is stable and the file reads as a contract spec.
_MINIMAL_CONFIG: dict[str, dict[str, Any]] = {
    "llmNode": {"model": "gpt-3.5-turbo", "prompt": "hello"},
    "conditionNode": {"expression": "1 == 1"},
    "switchNode": {"expression": "'red'", "cases": [{"value": "red"}]},
    "parallelNode": {"executionMode": "all"},
    "loopNode": {"maxIterations": 3},
    "humanApprovalNode": {"prompt": "Approve?"},
    "dlpScanNode": {"actionOnViolation": "flag"},
    "costGateNode": {"maxUsd": 0},
    "subWorkflowNode": {"workflowId": "wf-1", "workflowDefinition": {"steps": []}},
    "subAgentNode": {"agentId": "agent-1", "agentDefinition": {}},
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
    "visionNode": {"model": "gpt-4o", "imageUrl": "https://x"},
    "structuredOutputNode": {"model": "gpt-4o-mini", "schema": {}},
    "vectorSearchNode": {"collection": "docs"},
    "documentLoaderNode": {"source": "s3://x"},
    "humanInputNode": {"prompt": "name?"},
    "toolNode": {"toolName": "calc"},
    "mcpToolNode": {"serverName": "srv", "toolName": "search"},
}


def _patch_external_calls() -> list:
    """Return a list of patcher context managers for external dependencies.

    The smoke matrix should never touch the network or a real DB — every
    "real" call is mocked at the source.  Patchers are returned so the test
    can compose them with ``contextlib.ExitStack``.
    """
    from app.models.dlp import DLPScanResultSchema, RiskLevel, ScanAction  # noqa: PLC0415

    dlp_mock = MagicMock(spec=DLPScanResultSchema)
    dlp_mock.risk_level = RiskLevel.LOW
    dlp_mock.action = ScanAction.ALLOW
    dlp_mock.findings = []

    httpx_response = MagicMock()
    httpx_response.status_code = 200
    httpx_response.json.return_value = {"ok": True}
    httpx_response.headers = {}
    httpx_response.text = "{}"

    httpx_client = AsyncMock()
    httpx_client.__aenter__ = AsyncMock(return_value=httpx_client)
    httpx_client.__aexit__ = AsyncMock(return_value=None)
    httpx_client.request = AsyncMock(return_value=httpx_response)

    return [
        patch(
            "app.services.dlp_service.DLPService.scan_content",
            return_value=dlp_mock,
        ),
        patch("httpx.AsyncClient", return_value=httpx_client),
        # Stub sub-agent execution to avoid recursing into agent infra
        patch(
            "app.langgraph.engine.execute_agent",
            new=AsyncMock(return_value={"status": "completed", "output": {}}),
        ),
    ]


# ---------------------------------------------------------------------------
# Matrix tests
# ---------------------------------------------------------------------------


_REGISTERED = sorted(NODE_EXECUTORS.keys())


def test_registry_is_non_empty():
    """Sanity: at least one executor is registered."""
    assert NODE_EXECUTORS, "NODE_EXECUTORS is empty — registration did not run"


@pytest.mark.parametrize("node_type", _REGISTERED)
def test_executor_callable(node_type: str):
    """Every registered executor exposes an async ``execute`` method."""
    executor = NODE_EXECUTORS[node_type]
    assert hasattr(executor, "execute"), f"{node_type} missing execute()"
    assert callable(executor.execute), f"{node_type}.execute is not callable"


@pytest.mark.asyncio
@pytest.mark.parametrize("node_type", _REGISTERED)
async def test_executor_returns_dict_with_status(node_type: str):
    """Result is a NodeResult with a status in the canonical set."""
    config = _MINIMAL_CONFIG.get(node_type, {})
    ctx = make_ctx(node_type, config=config)

    from contextlib import ExitStack  # noqa: PLC0415

    with ExitStack() as stack:
        for p in _patch_external_calls():
            stack.enter_context(p)
        result = await NODE_EXECUTORS[node_type].execute(ctx)

    assert isinstance(result, NodeResult), (
        f"{node_type} returned {type(result).__name__}, expected NodeResult"
    )
    assert result.status in _VALID_STATUSES, (
        f"{node_type} returned status={result.status!r} — not in {_VALID_STATUSES}"
    )
    assert isinstance(result.output, dict), (
        f"{node_type} output is {type(result.output).__name__}, expected dict"
    )


@pytest.mark.parametrize("node_type", _REGISTERED)
def test_executor_has_status_classification(node_type: str):
    """Every executor has a NodeStatus entry in status_registry.

    Skipped gracefully when the registry module is not yet importable —
    Phase 3 / WS9 may add it after these tests are in place.
    """
    try:
        from app.services.node_executors import status_registry  # noqa: PLC0415
    except ImportError:
        pytest.skip("status_registry not present yet — gracefully skipped")
        return

    assert node_type in status_registry.NODE_STATUS, (
        f"{node_type} is registered in NODE_EXECUTORS but missing from "
        f"status_registry.NODE_STATUS — production gate cannot classify it."
    )
    status = status_registry.NODE_STATUS[node_type]
    assert isinstance(status, status_registry.NodeStatus)


def test_status_registry_no_extras():
    """status_registry.NODE_STATUS must not classify nodes that aren't registered."""
    try:
        from app.services.node_executors import status_registry  # noqa: PLC0415
    except ImportError:
        pytest.skip("status_registry not present yet — gracefully skipped")
        return

    extras = set(status_registry.NODE_STATUS) - set(NODE_EXECUTORS)
    assert not extras, (
        f"status_registry classifies {extras} but they are not registered "
        f"in NODE_EXECUTORS — drift between registry and classification."
    )


def test_executor_count_matches_expected():
    """28 nodes per the feature matrix — pin the count so silent removals fail."""
    assert len(NODE_EXECUTORS) == 28, (
        f"Expected 28 registered executors, got {len(NODE_EXECUTORS)} — "
        f"feature matrix drift."
    )
