"""Tests for the wizard endpoint and wizard_service."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.services.wizard_service import (
    AgentGraphDefinition,
    WizardRequest,
    WizardResponse,
    _build_mock_graph,
    generate_agent_graph,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def client() -> TestClient:
    """FastAPI TestClient with the DB session dependency overridden."""
    mock_session = AsyncMock()

    async def _override_session():  # noqa: ANN202
        yield mock_session

    app.dependency_overrides[get_session] = _override_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def sample_description() -> str:
    """Sample natural language description for testing."""
    return "a customer support bot that checks order status and handles returns"


# ── Service unit tests ──────────────────────────────────────────────


class TestWizardService:
    """Tests for wizard_service functions."""

    def test_build_mock_graph_returns_valid_definition(
        self, sample_description: str
    ) -> None:
        """_build_mock_graph returns a well-formed AgentGraphDefinition."""
        graph = _build_mock_graph(sample_description)

        assert isinstance(graph, AgentGraphDefinition)
        assert graph.description == sample_description
        assert len(graph.nodes) >= 3
        assert len(graph.edges) >= 2
        assert graph.name.startswith("agent-")

    def test_build_mock_graph_has_input_and_output_nodes(
        self, sample_description: str
    ) -> None:
        """Mock graph contains at least one input and one output node."""
        graph = _build_mock_graph(sample_description)
        node_types = {n.type for n in graph.nodes}
        assert "input" in node_types
        assert "output" in node_types

    def test_build_mock_graph_edges_reference_valid_nodes(
        self, sample_description: str
    ) -> None:
        """Every edge source/target must reference an existing node id."""
        graph = _build_mock_graph(sample_description)
        node_ids = {n.id for n in graph.nodes}
        for edge in graph.edges:
            assert edge.source in node_ids, f"Edge source {edge.source} not in nodes"
            assert edge.target in node_ids, f"Edge target {edge.target} not in nodes"

    @pytest.mark.asyncio()
    async def test_generate_agent_graph_mock_mode(
        self, sample_description: str
    ) -> None:
        """generate_agent_graph returns mock mode when no LLM key is set."""
        with patch(
            "app.services.wizard_service._llm_configured", return_value=False
        ):
            result = await generate_agent_graph(sample_description)

        assert isinstance(result, WizardResponse)
        assert result.mode == "mock"
        assert len(result.agent_definition.nodes) >= 3

    @pytest.mark.asyncio()
    async def test_generate_agent_graph_llm_mode_flag(
        self, sample_description: str
    ) -> None:
        """generate_agent_graph returns llm mode when an API key is present."""
        with patch(
            "app.services.wizard_service._llm_configured", return_value=True
        ):
            result = await generate_agent_graph(sample_description)

        assert result.mode == "llm"

    def test_wizard_request_rejects_empty(self) -> None:
        """WizardRequest rejects an empty description."""
        with pytest.raises(Exception):
            WizardRequest(description="")

    def test_wizard_request_accepts_valid(self) -> None:
        """WizardRequest accepts a valid description."""
        req = WizardRequest(description="build me a chatbot")
        assert req.description == "build me a chatbot"


# ── Route integration tests ────────────────────────────────────────


class TestWizardRoute:
    """Tests for POST /api/v1/wizard/generate."""

    def test_generate_returns_201_with_envelope(
        self, client: TestClient, sample_description: str
    ) -> None:
        """POST /api/v1/wizard/generate returns 201 with data + meta."""
        resp = client.post(
            "/api/v1/wizard/generate",
            json={"description": sample_description},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "data" in body
        assert "meta" in body
        assert "request_id" in body["meta"]
        assert "timestamp" in body["meta"]

    def test_generate_returns_agent_definition(
        self, client: TestClient, sample_description: str
    ) -> None:
        """Response data contains a valid agent_definition with nodes and edges."""
        resp = client.post(
            "/api/v1/wizard/generate",
            json={"description": sample_description},
        )
        data = resp.json()["data"]
        assert "agent_definition" in data
        defn = data["agent_definition"]
        assert "nodes" in defn
        assert "edges" in defn
        assert len(defn["nodes"]) >= 3
        assert len(defn["edges"]) >= 2
        assert "mode" in data

    def test_generate_returns_react_flow_format(
        self, client: TestClient, sample_description: str
    ) -> None:
        """Each node has id, type, position, data — React Flow compatible."""
        resp = client.post(
            "/api/v1/wizard/generate",
            json={"description": sample_description},
        )
        nodes = resp.json()["data"]["agent_definition"]["nodes"]
        for node in nodes:
            assert "id" in node
            assert "type" in node
            assert "position" in node
            assert "x" in node["position"]
            assert "y" in node["position"]
            assert "data" in node
            assert "label" in node["data"]

    def test_generate_rejects_empty_description(
        self, client: TestClient
    ) -> None:
        """POST with empty description returns 422."""
        resp = client.post(
            "/api/v1/wizard/generate",
            json={"description": ""},
        )
        assert resp.status_code == 422

    def test_generate_rejects_missing_description(
        self, client: TestClient
    ) -> None:
        """POST with missing description field returns 422."""
        resp = client.post("/api/v1/wizard/generate", json={})
        assert resp.status_code == 422

    def test_generate_rejects_too_long_description(
        self, client: TestClient
    ) -> None:
        """POST with description > 5000 chars returns 422."""
        resp = client.post(
            "/api/v1/wizard/generate",
            json={"description": "x" * 5001},
        )
        assert resp.status_code == 422

    def test_generate_accepts_max_length_description(
        self, client: TestClient
    ) -> None:
        """POST with exactly 5000 char description succeeds."""
        resp = client.post(
            "/api/v1/wizard/generate",
            json={"description": "x" * 5000},
        )
        assert resp.status_code == 201
