"""Tests for sandbox service and routes.

Covers SandboxService lifecycle (create, get, list, destroy, execute)
and the sandbox API endpoints via FastAPI TestClient.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.sandbox_service import (
    SandboxExecuteResult,
    SandboxResourceLimits,
    SandboxService,
    SandboxSession,
    SandboxStatus,
    sandbox_service,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def svc() -> SandboxService:
    """Fresh SandboxService instance per test."""
    return SandboxService()


@pytest.fixture()
def client() -> TestClient:
    """FastAPI TestClient with sandbox routes registered."""
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════
# SandboxResourceLimits schema tests
# ═══════════════════════════════════════════════════════════════════


def test_resource_limits_defaults() -> None:
    """Default resource limits are 30s timeout and 256MB memory."""
    limits = SandboxResourceLimits()
    assert limits.max_execution_time == 30
    assert limits.max_memory_mb == 256


def test_resource_limits_custom() -> None:
    """Custom resource limits are accepted."""
    limits = SandboxResourceLimits(max_execution_time=60, max_memory_mb=512)
    assert limits.max_execution_time == 60
    assert limits.max_memory_mb == 512


def test_resource_limits_validation_min() -> None:
    """Resource limits reject values below minimum."""
    with pytest.raises(Exception):
        SandboxResourceLimits(max_execution_time=0)
    with pytest.raises(Exception):
        SandboxResourceLimits(max_memory_mb=8)


def test_resource_limits_validation_max() -> None:
    """Resource limits reject values above maximum."""
    with pytest.raises(Exception):
        SandboxResourceLimits(max_execution_time=999)
    with pytest.raises(Exception):
        SandboxResourceLimits(max_memory_mb=9999)


# ═══════════════════════════════════════════════════════════════════
# SandboxService unit tests
# ═══════════════════════════════════════════════════════════════════


def test_create_session(svc: SandboxService) -> None:
    """create_session returns a READY session with a valid UUID."""
    session = svc.create_session()
    assert isinstance(session.id, UUID)
    assert session.status == SandboxStatus.READY
    assert session.resource_limits.max_execution_time == 30


def test_create_session_custom_limits(svc: SandboxService) -> None:
    """create_session respects custom resource limits."""
    limits = SandboxResourceLimits(max_execution_time=10, max_memory_mb=128)
    session = svc.create_session(resource_limits=limits)
    assert session.resource_limits.max_execution_time == 10
    assert session.resource_limits.max_memory_mb == 128


def test_get_session_found(svc: SandboxService) -> None:
    """get_session returns the session when it exists."""
    session = svc.create_session()
    found = svc.get_session(session.id)
    assert found is not None
    assert found.id == session.id


def test_get_session_not_found(svc: SandboxService) -> None:
    """get_session returns None for unknown ID."""
    result = svc.get_session(uuid4())
    assert result is None


def test_list_sessions_empty(svc: SandboxService) -> None:
    """list_sessions returns empty list when no sessions exist."""
    sessions, total = svc.list_sessions()
    assert sessions == []
    assert total == 0


def test_list_sessions_pagination(svc: SandboxService) -> None:
    """list_sessions paginates correctly."""
    for _ in range(5):
        svc.create_session()
    sessions, total = svc.list_sessions(limit=2, offset=0)
    assert len(sessions) == 2
    assert total == 5

    sessions2, _ = svc.list_sessions(limit=2, offset=3)
    assert len(sessions2) == 2


def test_destroy_session_found(svc: SandboxService) -> None:
    """destroy_session removes the session and returns True."""
    session = svc.create_session()
    assert svc.destroy_session(session.id) is True
    assert svc.get_session(session.id) is None


def test_destroy_session_not_found(svc: SandboxService) -> None:
    """destroy_session returns False for unknown ID."""
    assert svc.destroy_session(uuid4()) is False


# ═══════════════════════════════════════════════════════════════════
# SandboxService.execute tests
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execute_simple_code(svc: SandboxService) -> None:
    """Execute simple print statement and capture stdout."""
    result = await svc.execute("print('hello sandbox')")
    assert result.status == SandboxStatus.COMPLETED
    assert result.exit_code == 0
    assert "hello sandbox" in result.stdout
    assert result.execution_time_ms > 0
    assert isinstance(result.session_id, UUID)


@pytest.mark.asyncio
async def test_execute_syntax_error(svc: SandboxService) -> None:
    """Execute code with syntax error returns FAILED."""
    result = await svc.execute("def bad(")
    assert result.status == SandboxStatus.FAILED
    assert result.exit_code != 0
    assert "SyntaxError" in result.stderr


@pytest.mark.asyncio
async def test_execute_runtime_error(svc: SandboxService) -> None:
    """Execute code with runtime error returns FAILED."""
    result = await svc.execute("raise ValueError('boom')")
    assert result.status == SandboxStatus.FAILED
    assert result.exit_code == 1
    assert "ValueError" in result.stderr


@pytest.mark.asyncio
async def test_execute_with_timeout() -> None:
    """Execute code that exceeds timeout returns TIMEOUT."""
    svc = SandboxService()
    limits = SandboxResourceLimits(max_execution_time=1, max_memory_mb=256)
    result = await svc.execute(
        "import time; time.sleep(60)",
        resource_limits=limits,
    )
    assert result.status == SandboxStatus.TIMEOUT
    assert result.exit_code == 124
    assert "TimeoutError" in result.stderr or "timeout" in result.stderr.lower()


@pytest.mark.asyncio
async def test_execute_with_existing_session(svc: SandboxService) -> None:
    """Execute reuses an existing session when session_id is provided."""
    session = svc.create_session()
    result = await svc.execute("print('reuse')", session_id=session.id)
    assert result.session_id == session.id
    assert result.status == SandboxStatus.COMPLETED


@pytest.mark.asyncio
async def test_execute_nonexistent_session_creates_new(svc: SandboxService) -> None:
    """Execute with unknown session_id creates a new session."""
    fake_id = uuid4()
    result = await svc.execute("print('new')", session_id=fake_id)
    assert result.session_id != fake_id
    assert result.status == SandboxStatus.COMPLETED


@pytest.mark.asyncio
async def test_execute_empty_output(svc: SandboxService) -> None:
    """Execute code that produces no output."""
    result = await svc.execute("x = 42")
    assert result.status == SandboxStatus.COMPLETED
    assert result.stdout == ""
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_execute_multiline_code(svc: SandboxService) -> None:
    """Execute multiline code."""
    code = "for i in range(3):\n    print(i)"
    result = await svc.execute(code)
    assert result.status == SandboxStatus.COMPLETED
    assert "0" in result.stdout
    assert "2" in result.stdout


# ═══════════════════════════════════════════════════════════════════
# Route tests — POST /api/v1/sandbox/execute
# ═══════════════════════════════════════════════════════════════════


def test_route_execute_success(client: TestClient) -> None:
    """POST /api/v1/sandbox/execute returns 200 with result envelope."""
    resp = client.post(
        "/api/v1/sandbox/execute",
        json={"code": "print('route test')"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert body["data"]["status"] == "completed"
    assert "route test" in body["data"]["stdout"]
    assert body["meta"]["request_id"]
    assert body["meta"]["timestamp"]


def test_route_execute_with_limits(client: TestClient) -> None:
    """POST /api/v1/sandbox/execute respects custom resource limits."""
    resp = client.post(
        "/api/v1/sandbox/execute",
        json={
            "code": "print('ok')",
            "resource_limits": {"max_execution_time": 10, "max_memory_mb": 128},
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["resource_limits"]["max_execution_time"] == 10
    assert data["resource_limits"]["max_memory_mb"] == 128


def test_route_execute_empty_code(client: TestClient) -> None:
    """POST /api/v1/sandbox/execute rejects empty code."""
    resp = client.post("/api/v1/sandbox/execute", json={"code": ""})
    assert resp.status_code == 422


def test_route_execute_invalid_body(client: TestClient) -> None:
    """POST /api/v1/sandbox/execute rejects missing code field."""
    resp = client.post("/api/v1/sandbox/execute", json={})
    assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
# Route tests — sandbox session management
# ═══════════════════════════════════════════════════════════════════


def test_route_create_session(client: TestClient) -> None:
    """POST /api/v1/sandbox/sessions returns 201 with session data."""
    resp = client.post(
        "/api/v1/sandbox/sessions",
        json={"resource_limits": {"max_execution_time": 15, "max_memory_mb": 64}},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["data"]["status"] == "ready"
    assert body["data"]["resource_limits"]["max_execution_time"] == 15


def test_route_create_session_defaults(client: TestClient) -> None:
    """POST /api/v1/sandbox/sessions with defaults."""
    resp = client.post("/api/v1/sandbox/sessions", json={})
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["resource_limits"]["max_execution_time"] == 30
    assert data["resource_limits"]["max_memory_mb"] == 256


def test_route_list_sessions(client: TestClient) -> None:
    """GET /api/v1/sandbox/sessions returns paginated list."""
    resp = client.get("/api/v1/sandbox/sessions")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["data"], list)
    assert "pagination" in body["meta"]


def test_route_get_session(client: TestClient) -> None:
    """GET /api/v1/sandbox/sessions/{id} returns session."""
    # Create first
    create_resp = client.post("/api/v1/sandbox/sessions", json={})
    session_id = create_resp.json()["data"]["id"]

    resp = client.get(f"/api/v1/sandbox/sessions/{session_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == session_id


def test_route_get_session_not_found(client: TestClient) -> None:
    """GET /api/v1/sandbox/sessions/{id} returns 404 for unknown ID."""
    resp = client.get(f"/api/v1/sandbox/sessions/{uuid4()}")
    assert resp.status_code == 404


def test_route_destroy_session(client: TestClient) -> None:
    """DELETE /api/v1/sandbox/sessions/{id} returns 204."""
    create_resp = client.post("/api/v1/sandbox/sessions", json={})
    session_id = create_resp.json()["data"]["id"]

    resp = client.delete(f"/api/v1/sandbox/sessions/{session_id}")
    assert resp.status_code == 204

    # Verify it's gone
    get_resp = client.get(f"/api/v1/sandbox/sessions/{session_id}")
    assert get_resp.status_code == 404


def test_route_destroy_session_not_found(client: TestClient) -> None:
    """DELETE /api/v1/sandbox/sessions/{id} returns 404 for unknown ID."""
    resp = client.delete(f"/api/v1/sandbox/sessions/{uuid4()}")
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════════════


def test_module_singleton() -> None:
    """Module-level sandbox_service is a SandboxService instance."""
    assert isinstance(sandbox_service, SandboxService)
