"""Tests for models, connectors, audit_logs, and agent_versions routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from app.models import AgentVersion, AuditLog, Connector, Model
from tests.conftest import AGENT_ID, NOW, OWNER_ID

# ── Fixed UUIDs ─────────────────────────────────────────────────────

MODEL_ID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
CONNECTOR_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
AUDIT_LOG_ID = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
VERSION_ID = UUID("11111111-1111-1111-1111-111111111111")


# ── Fixtures (inline) ──────────────────────────────────────────────


def _sample_model() -> Model:
    return Model(
        id=MODEL_ID,
        name="gpt-4o",
        provider="openai",
        model_id="gpt-4o-2024-05-13",
        config={"temperature": 0.7},
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _sample_connector() -> Connector:
    return Connector(
        id=CONNECTOR_ID,
        name="slack-bot",
        type="slack",
        config={"webhook_url": "https://hooks.slack.com/test"},
        status="active",
        owner_id=OWNER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _sample_audit_log() -> AuditLog:
    return AuditLog(
        id=AUDIT_LOG_ID,
        actor_id=OWNER_ID,
        action="create",
        resource_type="agent",
        resource_id=AGENT_ID,
        details={"name": "test-agent"},
        created_at=NOW,
    )


def _sample_agent_version() -> AgentVersion:
    return AgentVersion(
        id=VERSION_ID,
        agent_id=AGENT_ID,
        version="1.0.0",
        definition={"model": "gpt-4", "temperature": 0.7},
        change_log="Initial version",
        created_by=OWNER_ID,
        created_at=NOW,
    )


# ── Model routes ────────────────────────────────────────────────────


def test_list_models_envelope(client: TestClient) -> None:
    """GET /api/v1/models/ returns envelope with data + meta + pagination."""
    with patch(
        "app.routes.models.ModelService.list",
        new_callable=AsyncMock,
        return_value=([_sample_model()], 1),
    ):
        resp = client.get("/api/v1/models/")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert "pagination" in body["meta"]
    assert body["meta"]["pagination"]["total"] == 1
    assert len(body["data"]) == 1


def test_create_model(client: TestClient) -> None:
    """POST /api/v1/models/ returns 201 with created model in envelope."""
    with patch(
        "app.routes.models.ModelService.create",
        new_callable=AsyncMock,
        return_value=_sample_model(),
    ):
        resp = client.post(
            "/api/v1/models/",
            json={
                "name": "gpt-4o",
                "provider": "openai",
                "model_id": "gpt-4o-2024-05-13",
                "config": {"temperature": 0.7},
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["name"] == "gpt-4o"
    assert "meta" in body


def test_get_model(client: TestClient) -> None:
    """GET /api/v1/models/{id} returns envelope with model data."""
    with patch(
        "app.routes.models.ModelService.get",
        new_callable=AsyncMock,
        return_value=_sample_model(),
    ):
        resp = client.get(f"/api/v1/models/{MODEL_ID}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == str(MODEL_ID)


def test_get_model_not_found(client: TestClient) -> None:
    """GET /api/v1/models/{id} returns 404 when not found."""
    with patch(
        "app.routes.models.ModelService.get",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get(f"/api/v1/models/{MODEL_ID}")
    assert resp.status_code == 404


def test_update_model(client: TestClient) -> None:
    """PUT /api/v1/models/{id} returns envelope with updated model."""
    updated = _sample_model()
    updated.name = "gpt-4o-mini"
    with patch(
        "app.routes.models.ModelService.update",
        new_callable=AsyncMock,
        return_value=updated,
    ):
        resp = client.put(
            f"/api/v1/models/{MODEL_ID}",
            json={"name": "gpt-4o-mini"},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "gpt-4o-mini"


def test_delete_model(client: TestClient) -> None:
    """DELETE /api/v1/models/{id} returns 204 on success."""
    with patch(
        "app.routes.models.ModelService.delete",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = client.delete(f"/api/v1/models/{MODEL_ID}")
    assert resp.status_code == 204


def test_delete_model_not_found(client: TestClient) -> None:
    """DELETE /api/v1/models/{id} returns 404 when not found."""
    with patch(
        "app.routes.models.ModelService.delete",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = client.delete(f"/api/v1/models/{MODEL_ID}")
    assert resp.status_code == 404


# ── Connector routes ────────────────────────────────────────────────


def test_list_connectors_envelope(client: TestClient) -> None:
    """GET /api/v1/connectors/ returns envelope with pagination."""
    with patch(
        "app.routes.connectors.ConnectorService.list",
        new_callable=AsyncMock,
        return_value=([_sample_connector()], 1),
    ):
        resp = client.get("/api/v1/connectors/")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "pagination" in body["meta"]
    assert body["meta"]["pagination"]["total"] == 1


def test_create_connector(client: TestClient) -> None:
    """POST /api/v1/connectors/ returns 201 with created connector."""
    with patch(
        "app.routes.connectors.ConnectorService.create",
        new_callable=AsyncMock,
        return_value=_sample_connector(),
    ):
        resp = client.post(
            "/api/v1/connectors/",
            json={
                "name": "slack-bot",
                "type": "slack",
                "config": {"webhook_url": "https://hooks.slack.com/test"},
                "owner_id": str(OWNER_ID),
            },
        )
    assert resp.status_code == 201
    assert resp.json()["data"]["name"] == "slack-bot"


def test_get_connector(client: TestClient) -> None:
    """GET /api/v1/connectors/{id} returns envelope."""
    with patch(
        "app.routes.connectors.ConnectorService.get",
        new_callable=AsyncMock,
        return_value=_sample_connector(),
    ):
        resp = client.get(f"/api/v1/connectors/{CONNECTOR_ID}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == str(CONNECTOR_ID)


def test_get_connector_not_found(client: TestClient) -> None:
    """GET /api/v1/connectors/{id} returns 404 when not found."""
    with patch(
        "app.routes.connectors.ConnectorService.get",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get(f"/api/v1/connectors/{CONNECTOR_ID}")
    assert resp.status_code == 404


def test_update_connector(client: TestClient) -> None:
    """PUT /api/v1/connectors/{id} returns envelope with updated connector."""
    updated = _sample_connector()
    updated.name = "slack-bot-v2"
    with patch(
        "app.routes.connectors.ConnectorService.update",
        new_callable=AsyncMock,
        return_value=updated,
    ):
        resp = client.put(
            f"/api/v1/connectors/{CONNECTOR_ID}",
            json={"name": "slack-bot-v2"},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "slack-bot-v2"


def test_delete_connector(client: TestClient) -> None:
    """DELETE /api/v1/connectors/{id} returns 204 on success."""
    with patch(
        "app.routes.connectors.ConnectorService.delete",
        new_callable=AsyncMock,
        return_value=True,
    ):
        resp = client.delete(f"/api/v1/connectors/{CONNECTOR_ID}")
    assert resp.status_code == 204


def test_delete_connector_not_found(client: TestClient) -> None:
    """DELETE /api/v1/connectors/{id} returns 404 when not found."""
    with patch(
        "app.routes.connectors.ConnectorService.delete",
        new_callable=AsyncMock,
        return_value=False,
    ):
        resp = client.delete(f"/api/v1/connectors/{CONNECTOR_ID}")
    assert resp.status_code == 404


# ── AuditLog routes ─────────────────────────────────────────────────


def test_list_audit_logs_by_resource(client: TestClient) -> None:
    """GET /api/v1/audit-logs/ with resource filter returns envelope."""
    with patch(
        "app.routes.audit_logs.AuditLogService.list_by_resource",
        new_callable=AsyncMock,
        return_value=([_sample_audit_log()], 1),
    ):
        resp = client.get(
            "/api/v1/audit-logs/",
            params={"resource_type": "agent", "resource_id": str(AGENT_ID)},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert "pagination" in body["meta"]


def test_list_audit_logs_by_actor(client: TestClient) -> None:
    """GET /api/v1/audit-logs/ with actor_id filter returns envelope."""
    with patch(
        "app.routes.audit_logs.AuditLogService.list_by_actor",
        new_callable=AsyncMock,
        return_value=([_sample_audit_log()], 1),
    ):
        resp = client.get(
            "/api/v1/audit-logs/",
            params={"actor_id": str(OWNER_ID)},
        )
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


def test_list_audit_logs_no_filter_returns_422(client: TestClient) -> None:
    """GET /api/v1/audit-logs/ without filters returns 422."""
    resp = client.get("/api/v1/audit-logs/")
    assert resp.status_code == 422


# ── AgentVersion routes ─────────────────────────────────────────────


def test_list_agent_versions(client: TestClient) -> None:
    """GET /api/v1/agent-versions/ returns envelope with pagination."""
    with patch(
        "app.routes.agent_versions.AgentVersionService.list_by_agent",
        new_callable=AsyncMock,
        return_value=([_sample_agent_version()], 1),
    ):
        resp = client.get(
            "/api/v1/agent-versions/",
            params={"agent_id": str(AGENT_ID)},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 1
    assert "pagination" in body["meta"]


def test_create_agent_version(client: TestClient) -> None:
    """POST /api/v1/agent-versions/ returns 201 with version envelope."""
    with patch(
        "app.routes.agent_versions.AgentVersionService.create",
        new_callable=AsyncMock,
        return_value=_sample_agent_version(),
    ):
        resp = client.post(
            "/api/v1/agent-versions/",
            json={
                "agent_id": str(AGENT_ID),
                "version": "1.0.0",
                "definition": {"model": "gpt-4", "temperature": 0.7},
                "change_log": "Initial version",
                "created_by": str(OWNER_ID),
            },
        )
    assert resp.status_code == 201
    assert resp.json()["data"]["version"] == "1.0.0"


def test_get_agent_version(client: TestClient) -> None:
    """GET /api/v1/agent-versions/{id} returns envelope."""
    with patch(
        "app.routes.agent_versions.AgentVersionService.get",
        new_callable=AsyncMock,
        return_value=_sample_agent_version(),
    ):
        resp = client.get(f"/api/v1/agent-versions/{VERSION_ID}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == str(VERSION_ID)


def test_get_agent_version_not_found(client: TestClient) -> None:
    """GET /api/v1/agent-versions/{id} returns 404 when not found."""
    with patch(
        "app.routes.agent_versions.AgentVersionService.get",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get(f"/api/v1/agent-versions/{VERSION_ID}")
    assert resp.status_code == 404


def test_get_latest_agent_version(client: TestClient) -> None:
    """GET /api/v1/agent-versions/latest returns the latest version."""
    with patch(
        "app.routes.agent_versions.AgentVersionService.get_latest",
        new_callable=AsyncMock,
        return_value=_sample_agent_version(),
    ):
        resp = client.get(
            "/api/v1/agent-versions/latest",
            params={"agent_id": str(AGENT_ID)},
        )
    assert resp.status_code == 200
    assert resp.json()["data"]["version"] == "1.0.0"


def test_get_latest_agent_version_not_found(client: TestClient) -> None:
    """GET /api/v1/agent-versions/latest returns 404 when none exist."""
    with patch(
        "app.routes.agent_versions.AgentVersionService.get_latest",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get(
            "/api/v1/agent-versions/latest",
            params={"agent_id": str(AGENT_ID)},
        )
    assert resp.status_code == 404
