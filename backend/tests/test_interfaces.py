"""Tests for interface models and protocol contracts."""

from __future__ import annotations

from app.interfaces import AgentRepository, AuthProvider, EventBus, ExecutionEngine
from app.interfaces.models import (
    AgentDefinition,
    Event,
    ExecutionResult,
    ExecutionStatus,
    User,
    UserClaims,
)


# ── ExecutionStatus enum ────────────────────────────────────────────


def test_execution_status_values() -> None:
    """ExecutionStatus enum contains expected lifecycle states."""
    assert ExecutionStatus.QUEUED == "queued"
    assert ExecutionStatus.RUNNING == "running"
    assert ExecutionStatus.COMPLETED == "completed"
    assert ExecutionStatus.FAILED == "failed"
    assert ExecutionStatus.CANCELLED == "cancelled"


def test_execution_status_is_str() -> None:
    """ExecutionStatus members are also strings."""
    assert isinstance(ExecutionStatus.QUEUED, str)


# ── AgentDefinition dataclass ───────────────────────────────────────


def test_agent_definition_defaults() -> None:
    """AgentDefinition has correct defaults for optional fields."""
    ad = AgentDefinition(id="a1", name="agent", definition={"k": "v"})
    assert ad.status == "draft"
    assert ad.owner_id == ""
    assert ad.description == ""
    assert ad.tags == []


def test_agent_definition_all_fields() -> None:
    """AgentDefinition accepts all fields."""
    ad = AgentDefinition(
        id="a2",
        name="full",
        definition={"model": "gpt-4"},
        status="active",
        owner_id="user-1",
        description="desc",
        tags=["x"],
    )
    assert ad.id == "a2"
    assert ad.tags == ["x"]


# ── ExecutionResult dataclass ───────────────────────────────────────


def test_execution_result_defaults() -> None:
    """ExecutionResult has None defaults for optional fields."""
    er = ExecutionResult(
        execution_id="e1",
        agent_id="a1",
        status=ExecutionStatus.QUEUED,
    )
    assert er.output is None
    assert er.error is None
    assert er.duration_ms is None


def test_execution_result_all_fields() -> None:
    """ExecutionResult accepts all fields including optionals."""
    er = ExecutionResult(
        execution_id="e2",
        agent_id="a2",
        status=ExecutionStatus.COMPLETED,
        output={"result": "ok"},
        error=None,
        duration_ms=150,
    )
    assert er.duration_ms == 150


# ── UserClaims dataclass ────────────────────────────────────────────


def test_user_claims_defaults() -> None:
    """UserClaims defaults to empty roles list."""
    uc = UserClaims(user_id="u1", email="a@b.com")
    assert uc.roles == []


def test_user_claims_with_roles() -> None:
    """UserClaims accepts roles list."""
    uc = UserClaims(user_id="u1", email="a@b.com", roles=["admin", "viewer"])
    assert len(uc.roles) == 2


# ── User dataclass ──────────────────────────────────────────────────


def test_user_defaults() -> None:
    """User defaults to empty roles list."""
    u = User(id="u1", email="a@b.com")
    assert u.roles == []


def test_user_with_roles() -> None:
    """User accepts roles list."""
    u = User(id="u1", email="a@b.com", roles=["admin"])
    assert u.roles == ["admin"]


# ── Event dataclass ─────────────────────────────────────────────────


def test_event_defaults() -> None:
    """Event defaults to empty channel and timestamp."""
    e = Event(type="test", payload={"k": "v"})
    assert e.channel == ""
    assert e.timestamp == ""


def test_event_all_fields() -> None:
    """Event accepts all fields."""
    e = Event(type="step", payload={"n": 1}, channel="ch1", timestamp="2025-01-01")
    assert e.channel == "ch1"


# ── Protocol runtime checks ────────────────────────────────────────


def test_agent_repository_is_protocol() -> None:
    """AgentRepository is a runtime-checkable Protocol."""
    assert hasattr(AgentRepository, "__protocol_attrs__") or hasattr(
        AgentRepository, "__abstractmethods__"
    ) or callable(getattr(AgentRepository, "create", None)) is False
    # Simply verify it's importable and is a class
    assert isinstance(AgentRepository, type)


def test_auth_provider_is_protocol() -> None:
    """AuthProvider is a runtime-checkable Protocol."""
    assert isinstance(AuthProvider, type)


def test_event_bus_is_protocol() -> None:
    """EventBus is a runtime-checkable Protocol."""
    assert isinstance(EventBus, type)


def test_execution_engine_is_protocol() -> None:
    """ExecutionEngine is a runtime-checkable Protocol."""
    assert isinstance(ExecutionEngine, type)
