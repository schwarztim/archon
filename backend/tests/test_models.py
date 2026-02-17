"""Tests for SQLModel model instantiation (no database required)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.models import Agent, Execution, User


_OWNER_ID = uuid4()


def test_user_defaults() -> None:
    """User gets a UUID id, default role, and timestamps on creation."""
    user = User(email="a@b.com", name="Alice", tenant_id=uuid4())
    assert isinstance(user.id, UUID)
    assert user.role == "developer"
    assert isinstance(user.created_at, datetime)


def test_agent_defaults() -> None:
    """Agent gets UUID id, default status, empty tags, and timestamps."""
    agent = Agent(
        name="my-agent",
        definition={"model": "gpt-4"},
        owner_id=_OWNER_ID,
    )
    assert isinstance(agent.id, UUID)
    assert agent.status == "draft"
    assert agent.tags == []
    assert isinstance(agent.created_at, datetime)
    assert isinstance(agent.updated_at, datetime)


def test_execution_defaults() -> None:
    """Execution gets UUID id, default 'queued' status, and timestamps."""
    exe = Execution(
        agent_id=uuid4(),
        input_data={"message": "run"},
    )
    assert isinstance(exe.id, UUID)
    assert exe.status == "queued"
    assert exe.output_data is None
    assert exe.error is None
    assert isinstance(exe.created_at, datetime)


def test_agent_field_types() -> None:
    """Agent fields have the correct Python types."""
    agent = Agent(
        name="typed",
        description="desc",
        definition={"k": "v"},
        owner_id=_OWNER_ID,
        tags=["a", "b"],
    )
    assert isinstance(agent.name, str)
    assert isinstance(agent.definition, dict)
    assert isinstance(agent.tags, list)
    assert isinstance(agent.owner_id, UUID)
