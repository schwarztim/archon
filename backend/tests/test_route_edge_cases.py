"""Tests for route edge cases: update-not-found, invalid UUIDs, pagination bounds."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.models import Agent, Connector, Model
from tests.conftest import AGENT_ID, NOW, OWNER_ID

MODEL_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
CONNECTOR_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


# ── Agent route edge cases ──────────────────────────────────────────


def test_update_agent_not_found(client: TestClient) -> None:
    """PUT /api/v1/agents/{id} returns 404 when agent doesn't exist."""
    with patch(
        "app.routes.agents.agent_service.update_agent",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.put(
            f"/api/v1/agents/{AGENT_ID}",
            json={"name": "nonexistent"},
        )
    assert resp.status_code == 404


def test_get_agent_invalid_uuid(client: TestClient) -> None:
    """GET /api/v1/agents/not-a-uuid returns 422 validation error."""
    resp = client.get("/api/v1/agents/not-a-uuid")
    assert resp.status_code == 422


def test_create_agent_missing_required_field(client: TestClient) -> None:
    """POST /api/v1/agents/ without required field returns 422."""
    resp = client.post("/api/v1/agents/", json={"description": "no name"})
    assert resp.status_code == 422


def test_list_agents_custom_pagination(
    client: TestClient,
    sample_agent: Agent,
) -> None:
    """GET /api/v1/agents/?limit=5&offset=10 passes pagination through."""
    with patch(
        "app.routes.agents.agent_service.list_agents",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        resp = client.get("/api/v1/agents/?limit=5&offset=10")
    assert resp.status_code == 200
    pagination = resp.json()["meta"]["pagination"]
    assert pagination["limit"] == 5
    assert pagination["offset"] == 10
    assert pagination["total"] == 0


def test_list_agents_invalid_limit(client: TestClient) -> None:
    """GET /api/v1/agents/?limit=0 returns 422 (limit must be >=1)."""
    resp = client.get("/api/v1/agents/?limit=0")
    assert resp.status_code == 422


def test_list_agents_limit_exceeds_max(client: TestClient) -> None:
    """GET /api/v1/agents/?limit=200 returns 422 (limit max is 100)."""
    resp = client.get("/api/v1/agents/?limit=200")
    assert resp.status_code == 422


# ── Model route edge cases ──────────────────────────────────────────


def test_update_model_not_found(client: TestClient) -> None:
    """PUT /api/v1/models/{id} returns 404 when model doesn't exist."""
    with patch(
        "app.routes.models.ModelService.update",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.put(
            f"/api/v1/models/{MODEL_ID}",
            json={"name": "nonexistent"},
        )
    assert resp.status_code == 404


def test_create_model_missing_required_field(client: TestClient) -> None:
    """POST /api/v1/models/ without required field returns 422."""
    resp = client.post("/api/v1/models/", json={"name": "only-name"})
    assert resp.status_code == 422


def test_get_model_invalid_uuid(client: TestClient) -> None:
    """GET /api/v1/models/not-a-uuid returns 422."""
    resp = client.get("/api/v1/models/not-a-uuid")
    assert resp.status_code == 422


# ── Connector route edge cases ──────────────────────────────────────


def test_update_connector_not_found(client: TestClient) -> None:
    """PUT /api/v1/connectors/{id} returns 404 when connector doesn't exist."""
    with patch(
        "app.routes.connectors.ConnectorService.update",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.put(
            f"/api/v1/connectors/{CONNECTOR_ID}",
            json={"name": "nonexistent"},
        )
    assert resp.status_code == 404


def test_create_connector_missing_required_field(client: TestClient) -> None:
    """POST /api/v1/connectors/ without required field returns 422."""
    resp = client.post("/api/v1/connectors/", json={"name": "only-name"})
    assert resp.status_code == 422


def test_get_connector_invalid_uuid(client: TestClient) -> None:
    """GET /api/v1/connectors/not-a-uuid returns 422."""
    resp = client.get("/api/v1/connectors/not-a-uuid")
    assert resp.status_code == 422


# ── Execution route edge cases ──────────────────────────────────────


def test_create_execution_missing_required_field(client: TestClient) -> None:
    """POST /api/v1/execute without required field returns 422."""
    resp = client.post("/api/v1/execute", json={"input_data": {}})
    assert resp.status_code == 422


def test_get_execution_invalid_uuid(client: TestClient) -> None:
    """GET /api/v1/executions/not-a-uuid returns 422."""
    resp = client.get("/api/v1/executions/not-a-uuid")
    assert resp.status_code == 422


def test_list_executions_custom_pagination(client: TestClient) -> None:
    """GET /api/v1/executions?limit=3&offset=5 passes pagination through."""
    with patch(
        "app.routes.executions.execution_service.list_executions",
        new_callable=AsyncMock,
        return_value=([], 0),
    ):
        resp = client.get("/api/v1/executions?limit=3&offset=5")
    assert resp.status_code == 200
    pagination = resp.json()["meta"]["pagination"]
    assert pagination["limit"] == 3
    assert pagination["offset"] == 5


# ── AuditLog route edge cases ──────────────────────────────────────


def test_audit_logs_partial_resource_filter(client: TestClient) -> None:
    """GET /api/v1/audit-logs/ with only resource_type (no resource_id) returns 422."""
    resp = client.get("/api/v1/audit-logs/", params={"resource_type": "agent"})
    assert resp.status_code == 422


# ── AgentVersion route edge cases ──────────────────────────────────


def test_list_agent_versions_missing_agent_id(client: TestClient) -> None:
    """GET /api/v1/agent-versions/ without agent_id returns 422."""
    resp = client.get("/api/v1/agent-versions/")
    assert resp.status_code == 422


def test_create_agent_version_missing_required(client: TestClient) -> None:
    """POST /api/v1/agent-versions/ without required fields returns 422."""
    resp = client.post("/api/v1/agent-versions/", json={"version": "1.0.0"})
    assert resp.status_code == 422


def test_get_agent_version_invalid_uuid(client: TestClient) -> None:
    """GET /api/v1/agent-versions/not-a-uuid returns 422."""
    resp = client.get("/api/v1/agent-versions/not-a-uuid")
    assert resp.status_code == 422
