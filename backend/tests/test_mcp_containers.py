"""Tests for MCP Container Management API routes and service layer.

All Docker operations are mocked so tests pass without a running Docker daemon.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.models.mcp_container import MCPServerContainer

# ── Fixed IDs for deterministic tests ───────────────────────────────

CONTAINER_ID = "aaaaaaaa-1111-2222-3333-444444444444"
NOW = datetime(2025, 6, 1, 12, 0, 0)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_container(**kwargs: Any) -> MCPServerContainer:
    """Build an MCPServerContainer with sensible defaults."""
    defaults: dict[str, Any] = {
        "id": CONTAINER_ID,
        "name": "test-mcp-server",
        "image": "ghcr.io/archon/mcp-server",
        "tag": "latest",
        "status": "created",
        "container_id": None,
        "port_mappings": {"8080": "80"},
        "env_vars": {"ENV": "test"},
        "volumes": None,
        "health_check_url": "http://localhost:8080/health",
        "labels": {"app": "mcp"},
        "resource_limits": None,
        "restart_policy": "unless-stopped",
        "network": "archon-mcp",
        "tenant_id": "tenant-1",
        "created_at": NOW,
        "updated_at": NOW,
        "last_health_check": None,
        "health_status": None,
        "error_message": None,
    }
    defaults.update(kwargs)
    return MCPServerContainer(**defaults)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture()
def mock_session() -> AsyncMock:
    """AsyncMock standing in for an AsyncSession."""
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.first.return_value = None
    exec_result.all.return_value = []
    exec_result.one.return_value = 0
    session.exec = AsyncMock(return_value=exec_result)
    return session


@pytest.fixture()
def client(mock_session: AsyncMock) -> TestClient:
    """FastAPI TestClient with DB session dependency overridden.

    Uses the same pattern as conftest.py — no context manager — to avoid
    asyncpg event loop teardown errors.
    """

    async def _override_session():
        yield mock_session

    app.dependency_overrides[get_session] = _override_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def sample_container() -> MCPServerContainer:
    return _make_container()


@pytest.fixture()
def running_container() -> MCPServerContainer:
    return _make_container(status="running", container_id="docker-abc123")


# ── Test 1: Create container ─────────────────────────────────────────


def test_create_container_returns_201(
    client: TestClient, sample_container: MCPServerContainer
) -> None:
    """POST /api/v1/mcp/containers/ returns 201 with envelope."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.create_container",
        new_callable=AsyncMock,
        return_value=sample_container,
    ):
        resp = client.post(
            "/api/v1/mcp/containers/",
            json={"name": "test-mcp-server", "image": "ghcr.io/archon/mcp-server"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert body["data"]["name"] == "test-mcp-server"
    assert body["data"]["status"] == "created"


# ── Test 2: List containers ──────────────────────────────────────────


def test_list_containers_returns_envelope(
    client: TestClient, sample_container: MCPServerContainer
) -> None:
    """GET /api/v1/mcp/containers/ returns paginated envelope."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.list_containers",
        new_callable=AsyncMock,
        return_value=([sample_container], 1),
    ):
        resp = client.get("/api/v1/mcp/containers/")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert body["meta"]["pagination"]["total"] == 1
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == CONTAINER_ID


# ── Test 3: Get container by ID ──────────────────────────────────────


def test_get_container_found(
    client: TestClient, sample_container: MCPServerContainer
) -> None:
    """GET /api/v1/mcp/containers/{id} returns 200 with container data."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.get_container",
        new_callable=AsyncMock,
        return_value=sample_container,
    ):
        resp = client.get(f"/api/v1/mcp/containers/{CONTAINER_ID}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["id"] == CONTAINER_ID
    assert body["data"]["image"] == "ghcr.io/archon/mcp-server"


# ── Test 4: Get container — 404 ──────────────────────────────────────


def test_get_container_not_found(client: TestClient) -> None:
    """GET /api/v1/mcp/containers/{id} returns 404 when not found."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.get_container",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.get(f"/api/v1/mcp/containers/{CONTAINER_ID}")
    assert resp.status_code == 404


# ── Test 5: Start container ──────────────────────────────────────────


def test_start_container(
    client: TestClient, running_container: MCPServerContainer
) -> None:
    """POST /api/v1/mcp/containers/{id}/start returns running container."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.start_container",
        new_callable=AsyncMock,
        return_value=running_container,
    ):
        resp = client.post(f"/api/v1/mcp/containers/{CONTAINER_ID}/start")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "running"
    assert body["data"]["container_id"] == "docker-abc123"


# ── Test 6: Stop container ───────────────────────────────────────────


def test_stop_container(
    client: TestClient, sample_container: MCPServerContainer
) -> None:
    """POST /api/v1/mcp/containers/{id}/stop returns stopped container."""
    stopped = _make_container(status="stopped")
    with patch(
        "app.routes.mcp_containers.MCPContainerService.stop_container",
        new_callable=AsyncMock,
        return_value=stopped,
    ):
        resp = client.post(f"/api/v1/mcp/containers/{CONTAINER_ID}/stop")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "stopped"


# ── Test 7: Restart container ────────────────────────────────────────


def test_restart_container(
    client: TestClient, running_container: MCPServerContainer
) -> None:
    """POST /api/v1/mcp/containers/{id}/restart returns running container."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.restart_container",
        new_callable=AsyncMock,
        return_value=running_container,
    ):
        resp = client.post(f"/api/v1/mcp/containers/{CONTAINER_ID}/restart")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "running"


# ── Test 8: Delete container ─────────────────────────────────────────


def test_delete_container(client: TestClient) -> None:
    """DELETE /api/v1/mcp/containers/{id} returns 204."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.remove_container",
        new_callable=AsyncMock,
        return_value=None,
    ):
        resp = client.delete(f"/api/v1/mcp/containers/{CONTAINER_ID}")
    assert resp.status_code == 204


# ── Test 9: Get container logs ────────────────────────────────────────


def test_get_container_logs(client: TestClient) -> None:
    """GET /api/v1/mcp/containers/{id}/logs returns log lines."""
    log_lines = ["[INFO] server started", "[INFO] listening on :8080"]
    with patch(
        "app.routes.mcp_containers.MCPContainerService.get_logs",
        new_callable=AsyncMock,
        return_value=log_lines,
    ):
        resp = client.get(f"/api/v1/mcp/containers/{CONTAINER_ID}/logs?tail=50")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["lines"] == log_lines
    assert body["data"]["tail"] == 50


# ── Test 10: Health check ─────────────────────────────────────────────


def test_health_check_healthy(client: TestClient) -> None:
    """GET /api/v1/mcp/containers/{id}/health returns health status."""
    healthy = _make_container(health_status="healthy", last_health_check=NOW)
    with patch(
        "app.routes.mcp_containers.MCPContainerService.check_health",
        new_callable=AsyncMock,
        return_value=healthy,
    ):
        resp = client.get(f"/api/v1/mcp/containers/{CONTAINER_ID}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["health_status"] == "healthy"


# ── Test 11: Start — 404 if not found ────────────────────────────────


def test_start_container_not_found(client: TestClient) -> None:
    """POST /api/v1/mcp/containers/{id}/start returns 404 when missing."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.start_container",
        new_callable=AsyncMock,
        side_effect=ValueError(f"Container {CONTAINER_ID} not found"),
    ):
        resp = client.post(f"/api/v1/mcp/containers/{CONTAINER_ID}/start")
    assert resp.status_code == 404


# ── Test 12: Delete — 404 if not found ───────────────────────────────


def test_delete_container_not_found(client: TestClient) -> None:
    """DELETE /api/v1/mcp/containers/{id} returns 404 when missing."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.remove_container",
        new_callable=AsyncMock,
        side_effect=ValueError(f"Container {CONTAINER_ID} not found"),
    ):
        resp = client.delete(f"/api/v1/mcp/containers/{CONTAINER_ID}")
    assert resp.status_code == 404


# ── Test 13: List containers with filters ────────────────────────────


def test_list_containers_with_filters(
    client: TestClient, running_container: MCPServerContainer
) -> None:
    """GET /api/v1/mcp/containers/?status=running filters correctly."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.list_containers",
        new_callable=AsyncMock,
        return_value=([running_container], 1),
    ) as mock_list:
        resp = client.get("/api/v1/mcp/containers/?status=running&tenant_id=tenant-1")
    assert resp.status_code == 200
    # Verify filters were forwarded
    mock_list.assert_called_once()
    call_kwargs = mock_list.call_args.kwargs
    assert call_kwargs.get("status") == "running"
    assert call_kwargs.get("tenant_id") == "tenant-1"


# ── Test 14: MCPServerContainer model defaults ────────────────────────


def test_mcp_container_model_defaults() -> None:
    """MCPServerContainer has correct defaults."""
    c = MCPServerContainer(name="test", image="redis")
    assert c.tag == "latest"
    assert c.status == "created"
    assert c.restart_policy == "unless-stopped"
    assert c.network == "archon-mcp"
    assert c.id is not None  # uuid4 generated


# ── Test 15: Create with auto_start ──────────────────────────────────


def test_create_container_with_auto_start(
    client: TestClient, running_container: MCPServerContainer
) -> None:
    """POST /api/v1/mcp/containers/ with auto_start=true returns running container."""
    with patch(
        "app.routes.mcp_containers.MCPContainerService.create_container",
        new_callable=AsyncMock,
        return_value=running_container,
    ) as mock_create:
        resp = client.post(
            "/api/v1/mcp/containers/",
            json={
                "name": "test-mcp-server",
                "image": "ghcr.io/archon/mcp-server",
                "auto_start": True,
            },
        )
    assert resp.status_code == 201
    assert resp.json()["data"]["status"] == "running"
    # Verify auto_start was forwarded
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs.get("auto_start") is True
