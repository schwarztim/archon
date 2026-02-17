"""Extended model tests for AgentVersion, Model, Connector, AuditLog, and edge cases."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.models import AgentVersion, AuditLog, Connector, Execution, Model, User


_OWNER_ID = uuid4()
_AGENT_ID = uuid4()


# ── AgentVersion model ──────────────────────────────────────────────


def test_agent_version_defaults() -> None:
    """AgentVersion gets UUID id and timestamp on creation."""
    version = AgentVersion(
        agent_id=_AGENT_ID,
        version="1.0.0",
        definition={"model": "gpt-4"},
        created_by=_OWNER_ID,
    )
    assert isinstance(version.id, UUID)
    assert version.version == "1.0.0"
    assert version.change_log is None
    assert isinstance(version.created_at, datetime)


def test_agent_version_with_changelog() -> None:
    """AgentVersion accepts optional change_log field."""
    version = AgentVersion(
        agent_id=_AGENT_ID,
        version="2.0.0",
        definition={"model": "gpt-4"},
        change_log="Breaking changes",
        created_by=_OWNER_ID,
    )
    assert version.change_log == "Breaking changes"


# ── Model (LLM provider) ───────────────────────────────────────────


def test_model_defaults() -> None:
    """Model gets UUID id, is_active=True, and timestamps on creation."""
    model = Model(
        name="gpt-4o",
        provider="openai",
        model_id="gpt-4o-2024-05-13",
        config={"temperature": 0.7},
    )
    assert isinstance(model.id, UUID)
    assert model.is_active is True
    assert isinstance(model.created_at, datetime)
    assert isinstance(model.updated_at, datetime)


def test_model_inactive() -> None:
    """Model can be created with is_active=False."""
    model = Model(
        name="old-model",
        provider="anthropic",
        model_id="claude-2",
        config={},
        is_active=False,
    )
    assert model.is_active is False


# ── Connector model ─────────────────────────────────────────────────


def test_connector_defaults() -> None:
    """Connector gets UUID id, default status 'inactive', and timestamps."""
    connector = Connector(
        name="slack-bot",
        type="slack",
        config={"webhook_url": "https://example.com"},
        owner_id=_OWNER_ID,
    )
    assert isinstance(connector.id, UUID)
    assert connector.status == "inactive"
    assert isinstance(connector.created_at, datetime)


def test_connector_active_status() -> None:
    """Connector can be created with status='active'."""
    connector = Connector(
        name="active-bot",
        type="slack",
        config={},
        owner_id=_OWNER_ID,
        status="active",
    )
    assert connector.status == "active"


# ── AuditLog model ──────────────────────────────────────────────────


def test_audit_log_defaults() -> None:
    """AuditLog gets UUID id and timestamp on creation."""
    log = AuditLog(
        actor_id=_OWNER_ID,
        action="create",
        resource_type="agent",
        resource_id=_AGENT_ID,
    )
    assert isinstance(log.id, UUID)
    assert log.details is None
    assert isinstance(log.created_at, datetime)


def test_audit_log_with_details() -> None:
    """AuditLog accepts optional details dict."""
    log = AuditLog(
        actor_id=_OWNER_ID,
        action="update",
        resource_type="agent",
        resource_id=_AGENT_ID,
        details={"field": "name", "old": "a", "new": "b"},
    )
    assert log.details is not None
    assert log.details["field"] == "name"


# ── Execution model edge cases ──────────────────────────────────────


def test_execution_with_output_and_error() -> None:
    """Execution can hold both output_data and error."""
    exe = Execution(
        agent_id=_AGENT_ID,
        input_data={"message": "test"},
        output_data={"result": "partial"},
        error="Timeout after 30s",
        status="failed",
    )
    assert exe.output_data == {"result": "partial"}
    assert exe.error == "Timeout after 30s"
    assert exe.status == "failed"


def test_execution_timestamps() -> None:
    """Execution has started_at and completed_at as None by default."""
    exe = Execution(agent_id=_AGENT_ID, input_data={})
    assert exe.started_at is None
    assert exe.completed_at is None


# ── User model edge cases ──────────────────────────────────────────


def test_user_custom_role() -> None:
    """User can be created with a non-default role."""
    user = User(email="admin@example.com", name="Admin", role="admin", tenant_id=uuid4())
    assert user.role == "admin"


def test_user_updated_at_default() -> None:
    """User gets updated_at timestamp on creation."""
    user = User(email="x@y.com", name="X", tenant_id=uuid4())
    assert isinstance(user.updated_at, datetime)
