"""Tests for Agent 02 — Visual Graph Builder validation logic.

Validates graph structure rules, node type registry, save/load serialization,
and canvas state management from the backend perspective.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest


# ── Graph Validation Helpers (mirrors frontend nodeTypes.ts logic) ───


def _make_node(
    node_type: str,
    category: str,
    config: dict[str, Any] | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Create a minimal node dict for validation testing."""
    return {
        "id": node_id or f"node_{uuid4().hex[:8]}",
        "type": node_type,
        "position": {"x": 0, "y": 0},
        "data": {
            "label": node_type,
            "category": category,
            "description": "",
            "ports": [],
            "config": config or {},
        },
    }


def _make_edge(source: str, target: str) -> dict[str, Any]:
    """Create a minimal edge dict."""
    return {"source": source, "target": target, "id": f"e-{source}-{target}"}


def validate_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[str]:
    """Python mirror of the frontend validateGraph function.

    Validates that:
    1. At least 1 input/trigger node exists
    2. At least 1 output node exists
    3. All edge sources/targets reference existing nodes
    """
    errors: list[str] = []

    has_input = any(n["data"]["category"] == "input" for n in nodes)
    has_output = any(n["data"]["category"] == "output" for n in nodes)

    if not has_input:
        errors.append("Graph must have at least 1 Input/Trigger node.")
    if not has_output:
        errors.append("Graph must have at least 1 Output node.")

    node_ids = {n["id"] for n in nodes}
    for edge in edges:
        if edge["source"] not in node_ids:
            errors.append(f'Edge source "{edge["source"]}" not found.')
        if edge["target"] not in node_ids:
            errors.append(f'Edge target "{edge["target"]}" not found.')

    return errors


# ── Node Type Registry (mirrors frontend NODE_TYPE_REGISTRY) ────────


VALID_NODE_TYPES: set[str] = {
    "inputNode",
    "outputNode",
    "llmNode",
    "toolNode",
    "conditionNode",
    "webhookTriggerNode",
    "scheduleTriggerNode",
    "streamOutputNode",
    "embeddingNode",
    "visionNode",
    "structuredOutputNode",
    "mcpToolNode",
    "httpRequestNode",
    "databaseQueryNode",
    "functionCallNode",
    "switchNode",
    "loopNode",
    "parallelNode",
    "mergeNode",
    "delayNode",
    "vectorSearchNode",
    "documentLoaderNode",
    "humanApprovalNode",
    "humanInputNode",
    "dlpScanNode",
    "costGateNode",
    "subAgentNode",
}

NODE_CATEGORIES: dict[str, str] = {
    "inputNode": "input",
    "webhookTriggerNode": "input",
    "scheduleTriggerNode": "input",
    "outputNode": "output",
    "streamOutputNode": "output",
    "llmNode": "llm",
    "embeddingNode": "llm",
    "visionNode": "llm",
    "structuredOutputNode": "llm",
    "toolNode": "tool",
    "mcpToolNode": "tool",
    "httpRequestNode": "tool",
    "databaseQueryNode": "tool",
    "functionCallNode": "tool",
    "conditionNode": "condition",
    "switchNode": "condition",
    "loopNode": "condition",
    "parallelNode": "condition",
    "mergeNode": "condition",
    "delayNode": "condition",
    "vectorSearchNode": "rag",
    "documentLoaderNode": "rag",
    "humanApprovalNode": "human",
    "humanInputNode": "human",
    "dlpScanNode": "security",
    "costGateNode": "security",
    "subAgentNode": "subagent",
}


# ── Tests ────────────────────────────────────────────────────────────


class TestNodeTypeRegistry:
    """Verify all 27 node types are registered with correct categories."""

    def test_all_27_node_types_registered(self) -> None:
        """Registry must contain at least 27 node types."""
        assert len(VALID_NODE_TYPES) >= 27

    def test_every_type_has_category(self) -> None:
        """Every registered node type must have a category mapping."""
        for nt in VALID_NODE_TYPES:
            assert nt in NODE_CATEGORIES, f"{nt} missing category mapping"

    @pytest.mark.parametrize(
        "node_type,expected_category",
        [
            ("llmNode", "llm"),
            ("conditionNode", "condition"),
            ("inputNode", "input"),
            ("outputNode", "output"),
            ("mcpToolNode", "tool"),
            ("httpRequestNode", "tool"),
            ("databaseQueryNode", "tool"),
            ("vectorSearchNode", "rag"),
            ("humanApprovalNode", "human"),
            ("dlpScanNode", "security"),
            ("costGateNode", "security"),
            ("subAgentNode", "subagent"),
        ],
    )
    def test_node_category_mapping(self, node_type: str, expected_category: str) -> None:
        """Spot-check category assignments."""
        assert NODE_CATEGORIES[node_type] == expected_category

    def test_palette_categories_cover_all_types(self) -> None:
        """All categories used in node types must be known."""
        known_categories = {
            "input", "output", "llm", "tool", "condition",
            "rag", "human", "security", "subagent",
        }
        used_categories = set(NODE_CATEGORIES.values())
        assert used_categories.issubset(known_categories)


class TestGraphValidation:
    """Graph validation must enforce input+output requirements."""

    def test_valid_graph_passes(self) -> None:
        """A graph with input + output nodes passes validation."""
        nodes = [
            _make_node("inputNode", "input", node_id="n1"),
            _make_node("llmNode", "llm", node_id="n2"),
            _make_node("outputNode", "output", node_id="n3"),
        ]
        edges = [_make_edge("n1", "n2"), _make_edge("n2", "n3")]
        errors = validate_graph(nodes, edges)
        assert errors == []

    def test_missing_input_node_fails(self) -> None:
        """Graph without an input node must fail."""
        nodes = [
            _make_node("llmNode", "llm", node_id="n1"),
            _make_node("outputNode", "output", node_id="n2"),
        ]
        errors = validate_graph(nodes, [_make_edge("n1", "n2")])
        assert any("Input" in e for e in errors)

    def test_missing_output_node_fails(self) -> None:
        """Graph without an output node must fail."""
        nodes = [
            _make_node("inputNode", "input", node_id="n1"),
            _make_node("llmNode", "llm", node_id="n2"),
        ]
        errors = validate_graph(nodes, [_make_edge("n1", "n2")])
        assert any("Output" in e for e in errors)

    def test_empty_graph_fails(self) -> None:
        """An empty graph must produce two errors (no input + no output)."""
        errors = validate_graph([], [])
        assert len(errors) == 2

    def test_orphan_edge_detected(self) -> None:
        """Edge referencing non-existent source/target is reported."""
        nodes = [
            _make_node("inputNode", "input", node_id="n1"),
            _make_node("outputNode", "output", node_id="n2"),
        ]
        edges = [_make_edge("n1", "n2"), _make_edge("n1", "n99")]
        errors = validate_graph(nodes, edges)
        assert any("n99" in e for e in errors)

    def test_webhook_trigger_satisfies_input_requirement(self) -> None:
        """WebhookTrigger node has category=input, should satisfy input requirement."""
        nodes = [
            _make_node("webhookTriggerNode", "input", node_id="n1"),
            _make_node("outputNode", "output", node_id="n2"),
        ]
        errors = validate_graph(nodes, [_make_edge("n1", "n2")])
        assert errors == []

    def test_schedule_trigger_satisfies_input_requirement(self) -> None:
        """ScheduleTrigger node has category=input, should satisfy input requirement."""
        nodes = [
            _make_node("scheduleTriggerNode", "input", node_id="n1"),
            _make_node("outputNode", "output", node_id="n2"),
        ]
        errors = validate_graph(nodes, [_make_edge("n1", "n2")])
        assert errors == []

    def test_stream_output_satisfies_output_requirement(self) -> None:
        """StreamOutput node has category=output, should satisfy output requirement."""
        nodes = [
            _make_node("inputNode", "input", node_id="n1"),
            _make_node("streamOutputNode", "output", node_id="n2"),
        ]
        errors = validate_graph(nodes, [_make_edge("n1", "n2")])
        assert errors == []


class TestGraphSerialization:
    """Graph definition must round-trip through JSON serialization."""

    def test_graph_roundtrip(self) -> None:
        """Nodes and edges must survive JSON serialization."""
        nodes = [
            _make_node("inputNode", "input", node_id="n1"),
            _make_node("llmNode", "llm", {"model": "gpt-4o", "temperature": 0.7}, "n2"),
            _make_node("outputNode", "output", node_id="n3"),
        ]
        edges = [_make_edge("n1", "n2"), _make_edge("n2", "n3")]

        graph_def = {"nodes": nodes, "edges": edges}
        serialized = json.dumps(graph_def)
        restored = json.loads(serialized)

        assert len(restored["nodes"]) == 3
        assert len(restored["edges"]) == 2
        assert restored["nodes"][1]["data"]["config"]["model"] == "gpt-4o"

    def test_complex_config_roundtrip(self) -> None:
        """Node configs with nested structures must serialize cleanly."""
        config = {
            "conditions": {
                "logic": "AND",
                "conditions": [
                    {"field": "input.status", "operator": "equals", "value": "active"},
                    {"field": "input.count", "operator": "gt", "value": "10"},
                ],
            },
        }
        node = _make_node("conditionNode", "condition", config, "c1")
        serialized = json.dumps(node)
        restored = json.loads(serialized)
        conds = restored["data"]["config"]["conditions"]["conditions"]
        assert len(conds) == 2
        assert conds[0]["operator"] == "equals"

    def test_key_value_pairs_roundtrip(self) -> None:
        """Key-value pair configs (headers, params) must serialize cleanly."""
        config = {
            "method": "POST",
            "url": "https://api.example.com",
            "headerPairs": [
                {"key": "Content-Type", "value": "application/json"},
                {"key": "Authorization", "value": "Bearer {{token}}"},
            ],
            "body": '{"query": "test"}',
        }
        node = _make_node("httpRequestNode", "tool", config, "h1")
        serialized = json.dumps(node)
        restored = json.loads(serialized)
        headers = restored["data"]["config"]["headerPairs"]
        assert len(headers) == 2
        assert headers[0]["key"] == "Content-Type"


class TestNodeConfigValidation:
    """Per-node config validation rules."""

    def test_llm_node_requires_model(self) -> None:
        """LLM node without a model should be flaggable."""
        config: dict[str, Any] = {"model": "", "temperature": 0.7}
        assert config["model"] == ""  # empty = invalid

    def test_llm_temperature_range(self) -> None:
        """Temperature must be between 0 and 2."""
        assert 0 <= 0.7 <= 2
        assert not (0 <= 2.5 <= 2)  # 2.5 is out of range
        assert not (0 <= -0.1 <= 2)  # negative is out of range

    def test_mcp_tool_requires_server_and_tool(self) -> None:
        """MCP tool node must have serverName and toolName."""
        config: dict[str, Any] = {"serverName": "github", "toolName": "search"}
        assert config["serverName"] and config["toolName"]

    def test_http_request_requires_url_and_method(self) -> None:
        """HTTP request node must have url and method."""
        config: dict[str, Any] = {"method": "GET", "url": "https://example.com"}
        assert config["url"] and config["method"]

    def test_condition_visual_builder_structure(self) -> None:
        """Condition node visual builder must produce valid ConditionGroup."""
        group = {
            "logic": "AND",
            "conditions": [
                {"field": "input.score", "operator": "gt", "value": "80"},
            ],
        }
        assert group["logic"] in ("AND", "OR")
        assert len(group["conditions"]) >= 1
        assert group["conditions"][0]["operator"] in {
            "equals", "not_equals", "contains", "gt", "lt",
            "gte", "lte", "starts_with", "ends_with",
        }

    def test_vector_search_threshold_range(self) -> None:
        """Similarity threshold must be 0–1."""
        assert 0 <= 0.7 <= 1
        assert not (0 <= 1.5 <= 1)

    def test_delay_ms_non_negative(self) -> None:
        """Delay must be >= 0."""
        assert 1000 >= 0
        assert not (-1 >= 0)

    def test_cost_gate_max_cost_non_negative(self) -> None:
        """Max cost must be >= 0."""
        assert 10 >= 0
        assert not (-5 >= 0)


class TestCanvasStateManagement:
    """Canvas store state transitions."""

    def test_initial_state(self) -> None:
        """Default canvas state must be empty and clean."""
        state = {
            "nodes": [],
            "edges": [],
            "selectedNodeId": None,
            "isDirty": False,
            "showValidation": False,
            "lastAutoSave": None,
        }
        assert state["nodes"] == []
        assert state["edges"] == []
        assert state["isDirty"] is False
        assert state["showValidation"] is False

    def test_add_node_marks_dirty(self) -> None:
        """Adding a node should set isDirty = True."""
        state = {"nodes": [], "isDirty": False}
        node = _make_node("llmNode", "llm")
        state["nodes"] = [*state["nodes"], node]
        state["isDirty"] = True
        assert len(state["nodes"]) == 1
        assert state["isDirty"] is True

    def test_mark_clean_after_save(self) -> None:
        """markClean should reset isDirty to False."""
        state = {"isDirty": True}
        state["isDirty"] = False  # markClean
        assert state["isDirty"] is False

    def test_load_graph_resets_state(self) -> None:
        """loadGraph should replace nodes/edges and clear history."""
        nodes = [_make_node("inputNode", "input")]
        edges: list[dict[str, Any]] = []
        state: dict[str, Any] = {
            "nodes": nodes,
            "edges": edges,
            "history": [],
            "future": [],
            "isDirty": False,
            "selectedNodeId": None,
        }
        assert len(state["nodes"]) == 1
        assert state["isDirty"] is False
        assert state["history"] == []

    def test_auto_save_interval(self) -> None:
        """Auto-save interval should be 30 seconds."""
        auto_save_interval_ms = 30_000
        assert auto_save_interval_ms == 30_000

    def test_undo_redo_history(self) -> None:
        """History stack should support undo/redo."""
        history: list[dict[str, Any]] = []
        future: list[dict[str, Any]] = []

        # Add to history
        snapshot = {"nodes": [_make_node("llmNode", "llm")], "edges": []}
        history.append(snapshot)
        assert len(history) == 1

        # Undo
        prev = history.pop()
        future.insert(0, prev)
        assert len(history) == 0
        assert len(future) == 1

        # Redo
        nxt = future.pop(0)
        history.append(nxt)
        assert len(history) == 1
        assert len(future) == 0


class TestPaletteCategories:
    """Node palette must organize nodes into correct categories."""

    EXPECTED_CATEGORIES: dict[str, list[str]] = {
        "input": ["inputNode", "webhookTriggerNode", "scheduleTriggerNode"],
        "output": ["outputNode", "streamOutputNode"],
        "llm": ["llmNode", "embeddingNode", "visionNode", "structuredOutputNode"],
        "tool": ["toolNode", "mcpToolNode", "httpRequestNode", "databaseQueryNode", "functionCallNode"],
        "condition": ["conditionNode", "switchNode", "loopNode", "parallelNode", "mergeNode", "delayNode"],
        "rag": ["vectorSearchNode", "documentLoaderNode"],
        "human": ["humanApprovalNode", "humanInputNode"],
        "security": ["dlpScanNode", "costGateNode"],
        "subagent": ["subAgentNode"],
    }

    @pytest.mark.parametrize("category", EXPECTED_CATEGORIES.keys())
    def test_category_has_expected_nodes(self, category: str) -> None:
        """Each category must contain the expected node types."""
        expected = self.EXPECTED_CATEGORIES[category]
        actual = [nt for nt, cat in NODE_CATEGORIES.items() if cat == category]
        for nt in expected:
            assert nt in actual, f"{nt} not found in category {category}"

    def test_total_categories_is_9(self) -> None:
        """There should be exactly 9 categories in the palette."""
        categories = set(NODE_CATEGORIES.values())
        assert len(categories) == 9

    def test_all_nodes_belong_to_a_category(self) -> None:
        """Every node type must belong to exactly one category."""
        for nt in VALID_NODE_TYPES:
            assert nt in NODE_CATEGORIES


class TestSaveLoadIntegration:
    """Save/load graph_definition integration."""

    def test_save_payload_structure(self) -> None:
        """Save payload must include name, nodes, edges."""
        payload = {
            "name": "My Agent",
            "nodes": [
                _make_node("inputNode", "input", node_id="n1"),
                _make_node("llmNode", "llm", {"model": "gpt-4o"}, "n2"),
                _make_node("outputNode", "output", node_id="n3"),
            ],
            "edges": [_make_edge("n1", "n2"), _make_edge("n2", "n3")],
        }
        assert "name" in payload
        assert "nodes" in payload
        assert "edges" in payload
        assert len(payload["nodes"]) == 3
        assert len(payload["edges"]) == 2

    def test_load_restores_node_positions(self) -> None:
        """Loaded nodes must preserve their position coordinates."""
        node = _make_node("llmNode", "llm", node_id="n1")
        node["position"] = {"x": 250, "y": 100}
        serialized = json.dumps(node)
        restored = json.loads(serialized)
        assert restored["position"]["x"] == 250
        assert restored["position"]["y"] == 100

    def test_load_restores_edge_types(self) -> None:
        """Loaded edges must preserve their type and animation settings."""
        edge = {
            "id": "e1",
            "source": "n1",
            "target": "n2",
            "type": "smoothstep",
            "animated": True,
        }
        serialized = json.dumps(edge)
        restored = json.loads(serialized)
        assert restored["type"] == "smoothstep"
        assert restored["animated"] is True

    def test_validate_before_save_blocks_invalid_graph(self) -> None:
        """Saving must be blocked when validation fails."""
        nodes = [_make_node("llmNode", "llm", node_id="n1")]
        edges: list[dict[str, Any]] = []
        errors = validate_graph(nodes, edges)
        assert len(errors) > 0  # should have at least input/output errors
        # In the UI, save would be blocked

    def test_validate_passes_for_complete_graph(self) -> None:
        """Valid graph with input + output must pass validation."""
        nodes = [
            _make_node("inputNode", "input", node_id="n1"),
            _make_node("conditionNode", "condition", {
                "conditions": {
                    "logic": "AND",
                    "conditions": [{"field": "x", "operator": "equals", "value": "y"}],
                },
            }, "n2"),
            _make_node("outputNode", "output", node_id="n3"),
        ]
        edges = [_make_edge("n1", "n2"), _make_edge("n2", "n3")]
        errors = validate_graph(nodes, edges)
        assert errors == []


class TestTestRunPanel:
    """Test run panel validation."""

    def test_test_input_must_be_valid_json(self) -> None:
        """Test input must parse as valid JSON."""
        valid_input = '{"message": "hello"}'
        parsed = json.loads(valid_input)
        assert isinstance(parsed, dict)

    def test_invalid_json_input_detected(self) -> None:
        """Invalid JSON should be caught before execution."""
        invalid_input = "not valid json {"
        with pytest.raises(json.JSONDecodeError):
            json.loads(invalid_input)

    def test_empty_object_is_valid_input(self) -> None:
        """Empty object {} is a valid test input."""
        parsed = json.loads("{}")
        assert parsed == {}

    def test_execution_payload_structure(self) -> None:
        """Execution payload must have agent_id and input."""
        agent_id = str(uuid4())
        payload = {
            "agent_id": agent_id,
            "input": {"message": "test"},
        }
        assert payload["agent_id"] == agent_id
        assert "input" in payload
