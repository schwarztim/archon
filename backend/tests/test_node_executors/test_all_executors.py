"""Unit tests for all 28 node executors.

Each test verifies the happy-path behaviour of a single executor in isolation.
All downstream calls (LLM, DLP, CostService, httpx) are mocked so these tests
run without API keys, a database, or network access.

Run:
    LLM_STUB_MODE=true PYTHONPATH=backend python3 -m pytest \
        backend/tests/test_node_executors/ -v
"""

from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("LLM_STUB_MODE", "true")

from app.services.node_executors import NODE_EXECUTORS, NodeResult  # noqa: E402
from tests.test_node_executors import make_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


def test_registry_contains_all_expected_types():
    expected = {
        "llmNode",
        "conditionNode",
        "switchNode",
        "parallelNode",
        "loopNode",
        "humanApprovalNode",
        "dlpScanNode",
        "costGateNode",
        "subWorkflowNode",
        "subAgentNode",
        "httpRequestNode",
        "databaseQueryNode",
        "functionCallNode",
        "mergeNode",
        "delayNode",
        "webhookTriggerNode",
        "scheduleTriggerNode",
        "inputNode",
        "outputNode",
        "streamOutputNode",
        "embeddingNode",
        "visionNode",
        "structuredOutputNode",
        "vectorSearchNode",
        "documentLoaderNode",
        "humanInputNode",
        "toolNode",
        "mcpToolNode",
    }
    missing = expected - set(NODE_EXECUTORS.keys())
    assert not missing, f"Missing executors: {missing}"


# ---------------------------------------------------------------------------
# llmNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_node_stub_mode():
    """LLM node returns stub content when LLM_STUB_MODE=true."""
    ctx = make_ctx("llmNode", config={"model": "gpt-3.5-turbo", "prompt": "Say hello"})
    result = await NODE_EXECUTORS["llmNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["content"].startswith("[STUB]")
    assert result.token_usage is not None
    assert result.token_usage["total_tokens"] == 30


# ---------------------------------------------------------------------------
# conditionNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_node_true_branch():
    ctx = make_ctx("conditionNode", config={"expression": "1 == 1"})
    result = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["branch"] == "true"


@pytest.mark.asyncio
async def test_condition_node_false_branch():
    ctx = make_ctx("conditionNode", config={"expression": "1 == 2"})
    result = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["branch"] == "false"


@pytest.mark.asyncio
async def test_condition_node_missing_expression():
    ctx = make_ctx("conditionNode", config={})
    result = await NODE_EXECUTORS["conditionNode"].execute(ctx)
    assert result.status == "failed"
    assert "expression" in result.error.lower()


# ---------------------------------------------------------------------------
# switchNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_node_matches_case():
    ctx = make_ctx(
        "switchNode",
        config={
            "expression": "'red'",
            "cases": [{"value": "red"}, {"value": "blue"}],
        },
    )
    result = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["branch"] == "red"
    assert result.output["matched"] is True


@pytest.mark.asyncio
async def test_switch_node_default_when_no_match():
    ctx = make_ctx(
        "switchNode",
        config={
            "expression": "'green'",
            "cases": [{"value": "red"}, {"value": "blue"}],
        },
    )
    result = await NODE_EXECUTORS["switchNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["branch"] == "default"
    assert result.output["matched"] is False


# ---------------------------------------------------------------------------
# parallelNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parallel_node_records_mode():
    ctx = make_ctx("parallelNode", config={"executionMode": "all"})
    result = await NODE_EXECUTORS["parallelNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["execution_mode"] == "all"
    assert result.output["_fanout_hint"] is True


# ---------------------------------------------------------------------------
# loopNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_node_records_max_iterations():
    ctx = make_ctx("loopNode", config={"maxIterations": 5})
    result = await NODE_EXECUTORS["loopNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["max_iterations"] == 5
    assert result.output["_loop_hint"] is True


# ---------------------------------------------------------------------------
# humanApprovalNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_human_approval_node_pauses():
    ctx = make_ctx("humanApprovalNode", config={"prompt": "Approve this?"})
    result = await NODE_EXECUTORS["humanApprovalNode"].execute(ctx)
    assert result.status == "paused"
    assert result.paused_reason == "awaiting_human_approval"
    assert "approval_id" in result.output


# ---------------------------------------------------------------------------
# dlpScanNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlp_scan_node_passes_clean_content():
    clean_inputs = {"step1": {"content": "Hello world, no PII here."}}
    ctx = make_ctx("dlpScanNode", config={}, inputs=clean_inputs)

    from app.models.dlp import DLPScanResultSchema, RiskLevel, ScanAction  # noqa: PLC0415

    mock_result = MagicMock(spec=DLPScanResultSchema)
    mock_result.risk_level = RiskLevel.LOW
    mock_result.action = ScanAction.ALLOW
    mock_result.findings = []

    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=mock_result,
    ):
        result = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["passed"] is True


@pytest.mark.asyncio
async def test_dlp_scan_node_blocks_high_risk():
    ctx = make_ctx(
        "dlpScanNode",
        config={"actionOnViolation": "block"},
        inputs={"step1": "AKIA0000000000000000 secret key"},  # fake AWS key pattern
    )

    from app.models.dlp import DLPScanResultSchema, RiskLevel, ScanAction  # noqa: PLC0415

    mock_result = MagicMock(spec=DLPScanResultSchema)
    mock_result.risk_level = RiskLevel.CRITICAL
    mock_result.action = ScanAction.BLOCK
    mock_result.findings = [MagicMock()]

    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=mock_result,
    ):
        result = await NODE_EXECUTORS["dlpScanNode"].execute(ctx)

    assert result.status == "failed"
    assert "DLP violation" in result.error


# ---------------------------------------------------------------------------
# costGateNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_gate_passes_when_no_threshold():
    ctx = make_ctx("costGateNode", config={"maxUsd": 0})
    result = await NODE_EXECUTORS["costGateNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["reason"] == "no_threshold_configured"


@pytest.mark.asyncio
async def test_cost_gate_passes_when_under_budget():
    ctx = make_ctx("costGateNode", config={"maxUsd": 100.0}, tenant_id="t1", db_session=MagicMock())

    with patch(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        new=AsyncMock(return_value=5.0),
    ):
        result = await NODE_EXECUTORS["costGateNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["passed"] is True


@pytest.mark.asyncio
async def test_cost_gate_blocks_when_over_budget():
    # Pass a non-None db_session mock so the gate doesn't skip
    ctx = make_ctx("costGateNode", config={"maxUsd": 10.0}, tenant_id="t1", db_session=MagicMock())

    with patch(
        "app.services.node_executors.cost_gate._get_tenant_running_total",
        new=AsyncMock(return_value=15.0),
    ):
        result = await NODE_EXECUTORS["costGateNode"].execute(ctx)

    assert result.status == "failed"
    assert "Cost gate exceeded" in result.error


# ---------------------------------------------------------------------------
# httpRequestNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_request_node_get():
    ctx = make_ctx(
        "httpRequestNode",
        config={"method": "GET", "url": "https://httpbin.org/get"},
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"url": "https://httpbin.org/get"}
    mock_response.headers = {}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)

    assert result.status == "completed"
    assert result.output["status_code"] == 200


@pytest.mark.asyncio
async def test_http_request_node_fails_on_4xx():
    ctx = make_ctx(
        "httpRequestNode",
        config={"method": "GET", "url": "https://example.com/notfound"},
    )

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"error": "not found"}
    mock_response.headers = {}
    mock_response.text = "Not found"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.request = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await NODE_EXECUTORS["httpRequestNode"].execute(ctx)

    assert result.status == "failed"


# ---------------------------------------------------------------------------
# delayNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delay_node_zero_delay():
    ctx = make_ctx("delayNode", config={"seconds": 0})
    result = await NODE_EXECUTORS["delayNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["delayed_seconds"] == 0


@pytest.mark.asyncio
async def test_delay_node_respects_cancel():
    cancelled = False

    def cancel():
        return True

    ctx = make_ctx("delayNode", config={"seconds": 10})
    ctx.cancel_check = cancel
    result = await NODE_EXECUTORS["delayNode"].execute(ctx)
    assert result.status == "skipped"
    assert result.output["reason"] == "cancelled"


# ---------------------------------------------------------------------------
# mergeNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merge_node_all_strategy():
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "all"},
        inputs={"s1": "value1", "s2": "value2"},
    )
    result = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert result.status == "completed"
    assert "value1" in result.output["merged"]
    assert "value2" in result.output["merged"]


@pytest.mark.asyncio
async def test_merge_node_merge_strategy():
    ctx = make_ctx(
        "mergeNode",
        config={"strategy": "merge"},
        inputs={"s1": {"a": 1}, "s2": {"b": 2}},
    )
    result = await NODE_EXECUTORS["mergeNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["merged"] == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# inputNode / outputNode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_input_node_passes_through():
    ctx = make_ctx("inputNode", config={}, inputs={"data": "hello"})
    result = await NODE_EXECUTORS["inputNode"].execute(ctx)
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_output_node_collects_upstream():
    ctx = make_ctx(
        "outputNode",
        config={},
        inputs={"s1": {"content": "final answer"}},
    )
    result = await NODE_EXECUTORS["outputNode"].execute(ctx)
    assert result.status == "completed"
    assert "result" in result.output


# ---------------------------------------------------------------------------
# Trigger nodes (pass-through)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_trigger_node():
    ctx = make_ctx("webhookTriggerNode", config={})
    result = await NODE_EXECUTORS["webhookTriggerNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["trigger"] == "webhook"


@pytest.mark.asyncio
async def test_schedule_trigger_node():
    ctx = make_ctx("scheduleTriggerNode", config={"cron": "0 * * * *"})
    result = await NODE_EXECUTORS["scheduleTriggerNode"].execute(ctx)
    assert result.status == "completed"
    assert result.output["cron"] == "0 * * * *"


# ---------------------------------------------------------------------------
# Stub executors (smoke tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node_type,config",
    [
        ("streamOutputNode", {}),
        # NOTE: embeddingNode promoted from STUB to BETA — covered by
        # backend/tests/test_node_executors/test_embedding_node_contract.py
        # and backend/tests/test_embeddings_wrapper.py.
        # NOTE: structuredOutputNode promoted from STUB to BETA — covered
        # by backend/tests/test_node_executors/test_structured_output_node_contract.py.
        ("visionNode", {"model": "gpt-4o"}),
        ("toolNode", {"toolName": "calculator"}),
        ("mcpToolNode", {"serverName": "my-server", "toolName": "search"}),
        ("databaseQueryNode", {"query": "SELECT 1", "connectorId": "pg1"}),
        ("functionCallNode", {"functionName": "myFunc"}),
        ("vectorSearchNode", {"collection": "docs"}),
        ("documentLoaderNode", {"source": "s3://bucket/file.pdf"}),
        ("humanInputNode", {"prompt": "Enter your name"}),
    ],
)
async def test_stub_executors_complete(node_type: str, config: dict):
    """All stub executors should return status=completed without crashing."""
    ctx = make_ctx(node_type, config=config)
    executor = NODE_EXECUTORS.get(node_type)
    assert executor is not None, f"No executor registered for {node_type}"
    result = await executor.execute(ctx)
    assert result.status == "completed", (
        f"{node_type} returned status={result.status}, error={result.error}"
    )
    assert result.output.get("_stub") is True, f"{node_type} output missing _stub flag"


# ---------------------------------------------------------------------------
# Integration test: parallel → condition → dlp_scan → output
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integration_dag_parallel_condition_dlp_output():
    """Small DAG: parallel fan-out → condition (true branch) → dlp_scan (clean) → output."""
    from app.services.workflow_engine import execute_workflow_dag  # noqa: PLC0415
    from app.models.dlp import DLPScanResultSchema, RiskLevel, ScanAction  # noqa: PLC0415

    # Minimal stub workflow
    workflow = {
        "id": "integ-test-wf",
        "name": "Integration Test",
        "steps": [
            {
                "id": "step-parallel",
                "name": "parallel",
                "node_type": "parallelNode",
                "config": {"executionMode": "all"},
                "depends_on": [],
            },
            {
                "id": "step-condition",
                "name": "condition",
                "node_type": "conditionNode",
                "config": {"expression": "1 == 1"},
                "depends_on": ["step-parallel"],
            },
            {
                "id": "step-dlp",
                "name": "dlp",
                "node_type": "dlpScanNode",
                "config": {"actionOnViolation": "flag"},
                "depends_on": ["step-condition"],
            },
            {
                "id": "step-output",
                "name": "output",
                "node_type": "outputNode",
                "config": {},
                "depends_on": ["step-dlp"],
            },
        ],
    }

    mock_dlp = MagicMock()
    mock_dlp.risk_level = RiskLevel.LOW
    mock_dlp.action = ScanAction.ALLOW
    mock_dlp.findings = []

    with patch(
        "app.services.dlp_service.DLPService.scan_content",
        return_value=mock_dlp,
    ):
        result = await execute_workflow_dag(workflow)

    assert result["status"] == "completed", (
        f"Workflow failed: {[s for s in result['steps'] if s['status'] != 'completed']}"
    )
    step_statuses = {s["name"]: s["status"] for s in result["steps"]}
    assert step_statuses["parallel"] == "completed"
    assert step_statuses["condition"] == "completed"
    assert step_statuses["dlp"] == "completed"
    assert step_statuses["output"] == "completed"
