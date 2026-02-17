"""Tests for agent CRUD and execution routes using mocked service layer."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.models import Agent, Execution
from tests.conftest import AGENT_ID, EXECUTION_ID, NOW, OWNER_ID


# ── Agent routes ────────────────────────────────────────────────────


def test_list_agents_envelope(
    client: TestClient,
    sample_agent: Agent,
) -> None:
    """GET /api/v1/agents/ returns envelope with data + meta + pagination."""
    with patch(
        "app.routes.agents.agent_service.list_agents",
        new_callable=AsyncMock,
        return_value=([sample_agent], 1),
    ):
        resp = client.get("/api/v1/agents/")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert "pagination" in body["meta"]
    assert body["meta"]["pagination"]["total"] == 1
    assert len(body["data"]) == 1


def test_create_agent(
    client: TestClient,
    sample_agent: Agent,
    sample_agent_data: dict[str, Any],
) -> None:
    """POST /api/v1/agents/ returns 201 with created agent in envelope."""
    with patch(
        "app.routes.agents.agent_service.create_agent",
        new_callable=AsyncMock,
        return_value=sample_agent,
    ):
        resp = client.post("/api/v1/agents/", json=sample_agent_data)
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["name"] == "test-agent"
    assert "meta" in body


def test_get_agent(
    client: TestClient,
    sample_agent: Agent,
) -> None:
    """GET /api/v1/agents/{id} returns envelope with agent data."""
    with patch(
        "app.routes.agents.agent_service.get_agent",
        new_callable=AsyncMock,
        return_value=sample_agent,
    ):
        resp = client.get(f"/api/v1/agents/{AGENT_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["id"] == str(AGENT_ID)
    assert "meta" in body


def test_get_agent_not_found(client: TestClient) -> None:
    """GET /api/v1/agents/{id} returns 404 when agent doesn't exist."""
    with patch(
        "app.routes.agents.agent_service.get_agent",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get(f"/api/v1/agents/{AGENT_ID}")
    assert resp.status_code == 404


def test_update_agent(
    client: TestClient,
    sample_agent: Agent,
) -> None:
    """PUT /api/v1/agents/{id} returns envelope with updated agent."""
    updated = Agent(**sample_agent.model_dump())
    updated.name = "renamed"
    with patch(
        "app.routes.agents.agent_service.update_agent",
        new_callable=AsyncMock,
        return_value=updated,
    ):
        resp = client.put(
            f"/api/v1/agents/{AGENT_ID}",
            json={"name": "renamed"},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "renamed"


def test_delete_agent(client: TestClient) -> None:
    """DELETE /api/v1/agents/{id} returns 204 on success."""
    with patch(
        "app.routes.agents.agent_service.delete_agent",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = client.delete(f"/api/v1/agents/{AGENT_ID}")
    assert resp.status_code == 204


def test_delete_agent_not_found(client: TestClient) -> None:
    """DELETE /api/v1/agents/{id} returns 404 when agent doesn't exist."""
    with patch(
        "app.routes.agents.agent_service.delete_agent",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = client.delete(f"/api/v1/agents/{AGENT_ID}")
    assert resp.status_code == 404


# ── Execution routes ────────────────────────────────────────────────


def test_create_execution(
    client: TestClient,
    sample_execution: Execution,
    sample_execution_data: dict[str, Any],
) -> None:
    """POST /api/v1/execute returns 201 with execution envelope."""
    with patch(
        "app.routes.executions.execution_service.create_execution",
        new_callable=AsyncMock,
        return_value=sample_execution,
    ):
        resp = client.post("/api/v1/execute", json=sample_execution_data)
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["status"] == "queued"
    assert "meta" in body


def test_list_executions_envelope(
    client: TestClient,
    sample_execution: Execution,
) -> None:
    """GET /api/v1/executions returns envelope with pagination."""
    with patch(
        "app.routes.executions.execution_service.list_executions",
        new_callable=AsyncMock,
        return_value=([sample_execution], 1),
    ):
        resp = client.get("/api/v1/executions")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert "pagination" in body["meta"]


def test_get_execution(
    client: TestClient,
    sample_execution: Execution,
) -> None:
    """GET /api/v1/executions/{id} returns envelope with execution data."""
    with patch(
        "app.routes.executions.execution_service.get_execution",
        new_callable=AsyncMock,
        return_value=sample_execution,
    ):
        resp = client.get(f"/api/v1/executions/{EXECUTION_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["id"] == str(EXECUTION_ID)
    assert "meta" in body


def test_get_execution_not_found(client: TestClient) -> None:
    """GET /api/v1/executions/{id} returns 404 when not found."""
    with patch(
        "app.routes.executions.execution_service.get_execution",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get(f"/api/v1/executions/{EXECUTION_ID}")
    assert resp.status_code == 404
