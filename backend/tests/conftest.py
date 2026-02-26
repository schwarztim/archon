"""Shared pytest fixtures for Archon backend tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import get_session
from app.main import app
from app.middleware.auth import get_current_user
from app.models import Agent, Execution

# ── Fixed UUIDs for deterministic tests ─────────────────────────────

OWNER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
AGENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
EXECUTION_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def sample_agent_data() -> dict[str, Any]:
    """Raw dict matching AgentCreate schema."""
    return {
        "name": "test-agent",
        "description": "A test agent",
        "definition": {"model": "gpt-4", "temperature": 0.7},
        "status": "draft",
        "owner_id": str(OWNER_ID),
        "tags": ["test"],
    }


@pytest.fixture()
def sample_agent() -> Agent:
    """Pre-built Agent model instance."""
    return Agent(
        id=AGENT_ID,
        name="test-agent",
        description="A test agent",
        definition={"model": "gpt-4", "temperature": 0.7},
        status="draft",
        owner_id=OWNER_ID,
        tags=["test"],
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture()
def sample_execution_data() -> dict[str, Any]:
    """Raw dict matching ExecutionCreate schema."""
    return {
        "agent_id": str(AGENT_ID),
        "input_data": {"message": "hello"},
    }


@pytest.fixture()
def sample_execution() -> Execution:
    """Pre-built Execution model instance."""
    return Execution(
        id=EXECUTION_ID,
        agent_id=AGENT_ID,
        status="queued",
        input_data={"message": "hello"},
        output_data=None,
        error=None,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture()
def mock_session() -> AsyncMock:
    """AsyncMock standing in for an AsyncSession."""
    session = AsyncMock()
    # Ensure session.exec() returns a result with a usable .first() method
    exec_result = MagicMock()
    exec_result.first.return_value = None
    session.exec = AsyncMock(return_value=exec_result)
    return session


@pytest.fixture()
def client(mock_session: AsyncMock) -> TestClient:
    """FastAPI TestClient with the DB session dependency overridden."""

    async def _override_session():  # noqa: ANN202
        yield mock_session

    async def _override_auth():  # noqa: ANN202
        return None

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_auth
    yield TestClient(app)
    app.dependency_overrides.clear()
