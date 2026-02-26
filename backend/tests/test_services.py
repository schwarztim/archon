"""Unit tests for service classes using mocked AsyncSession.

Each service method is tested by mocking the session's ORM calls
(get, exec, add, commit, refresh, delete) to verify the service logic
without requiring a real database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.interfaces.models.enterprise import AuthenticatedUser
from app.models import Agent, AgentVersion, AuditLog, Connector, Execution, Model
from app.services.agent_service import AgentService
from app.services.agent_version_service import AgentVersionService
from app.services.audit_log_service import AuditLogService
from app.services.connector_service import ConnectorService
from app.services.execution_service import ExecutionService
from app.services.model_service import ModelService

# ── Fixed UUIDs ─────────────────────────────────────────────────────

OWNER_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
AGENT_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TENANT_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _mock_session() -> AsyncMock:
    """Create a mock AsyncSession with standard ORM method stubs."""
    session = AsyncMock()
    session.add = MagicMock()
    return session


def _mock_user(permissions: list[str] | None = None) -> AuthenticatedUser:
    """Create an AuthenticatedUser with all common permissions granted."""
    return AuthenticatedUser(
        id=str(OWNER_ID),
        email="test@example.com",
        tenant_id=str(TENANT_ID),
        roles=["admin"],
        permissions=permissions
        or [
            "agents:create",
            "agents:read",
            "agents:update",
            "agents:delete",
            "executions:execute",
            "executions:read",
            "connectors:create",
            "connectors:execute",
            "connectors:delete",
        ],
    )


# ═══════════════════════════════════════════════════════════════════
# AgentService
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_create(mock_check: MagicMock) -> None:
    """AgentService.create persists and returns the agent with RBAC check."""
    session = _mock_session()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    user = _mock_user()
    agent = Agent(name="a", definition={"k": "v"}, owner_id=OWNER_ID)

    result = await AgentService.create(
        session,
        agent,
        tenant_id=TENANT_ID,
        user=user,
    )

    mock_check.assert_called_once_with(user, "agents", "create")
    session.add.assert_called()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(agent)
    assert result is agent
    assert result.owner_id == OWNER_ID


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_get_found(mock_check: MagicMock) -> None:
    """AgentService.get returns an agent when found in tenant scope."""
    session = _mock_session()
    agent = Agent(id=AGENT_ID, name="a", definition={}, owner_id=OWNER_ID)
    exec_result = MagicMock()
    exec_result.first.return_value = agent
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentService.get(session, AGENT_ID, tenant_id=TENANT_ID)

    assert result is agent
    session.exec.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_get_not_found(mock_check: MagicMock) -> None:
    """AgentService.get returns None when agent not found in tenant scope."""
    session = _mock_session()
    exec_result = MagicMock()
    exec_result.first.return_value = None
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentService.get(session, AGENT_ID, tenant_id=TENANT_ID)

    assert result is None
    session.exec.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_list(mock_check: MagicMock) -> None:
    """AgentService.list returns paginated results and total count."""
    session = _mock_session()
    agent = Agent(name="a", definition={}, owner_id=OWNER_ID)

    count_result = MagicMock()
    count_result.all.return_value = [agent]
    page_result = MagicMock()
    page_result.all.return_value = [agent]
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    agents, total = await AgentService.list(
        session,
        tenant_id=TENANT_ID,
        limit=10,
        offset=0,
    )
    assert total == 1
    assert len(agents) == 1


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_list_with_filters(mock_check: MagicMock) -> None:
    """AgentService.list applies owner_id and status filters."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    agents, total = await AgentService.list(
        session,
        tenant_id=TENANT_ID,
        owner_id=OWNER_ID,
        status="active",
        limit=5,
        offset=0,
    )
    assert total == 0
    assert agents == []
    assert session.exec.await_count == 2


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_update_found(mock_check: MagicMock) -> None:
    """AgentService.update applies data and returns updated agent."""
    session = _mock_session()
    user = _mock_user()
    agent = Agent(id=AGENT_ID, name="old", definition={}, owner_id=OWNER_ID)
    # AgentService.update calls AgentService.get internally (uses exec)
    exec_result = MagicMock()
    exec_result.first.return_value = agent
    session.exec = AsyncMock(return_value=exec_result)
    session.refresh = AsyncMock()

    result = await AgentService.update(
        session,
        AGENT_ID,
        {"name": "new"},
        tenant_id=TENANT_ID,
        user=user,
    )

    assert result is not None
    assert result.name == "new"
    mock_check.assert_called_with(user, "agents", "update")
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_update_not_found(mock_check: MagicMock) -> None:
    """AgentService.update returns None when agent not found."""
    session = _mock_session()
    user = _mock_user()
    exec_result = MagicMock()
    exec_result.first.return_value = None
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentService.update(
        session,
        AGENT_ID,
        {"name": "x"},
        tenant_id=TENANT_ID,
        user=user,
    )

    assert result is None
    mock_check.assert_called_once_with(user, "agents", "update")


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_update_ignores_unknown_fields(
    mock_check: MagicMock,
) -> None:
    """AgentService.update skips keys that don't exist on the model."""
    session = _mock_session()
    user = _mock_user()
    agent = Agent(id=AGENT_ID, name="old", definition={}, owner_id=OWNER_ID)
    exec_result = MagicMock()
    exec_result.first.return_value = agent
    session.exec = AsyncMock(return_value=exec_result)
    session.refresh = AsyncMock()

    result = await AgentService.update(
        session,
        AGENT_ID,
        {"nonexistent_field": "val"},
        tenant_id=TENANT_ID,
        user=user,
    )

    assert result is not None
    assert result.name == "old"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_delete_found(mock_check: MagicMock) -> None:
    """AgentService.delete (soft-delete) returns True when agent found."""
    session = _mock_session()
    user = _mock_user()
    agent = Agent(id=AGENT_ID, name="a", definition={}, owner_id=OWNER_ID)
    exec_result = MagicMock()
    exec_result.first.return_value = agent
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentService.delete(
        session,
        AGENT_ID,
        tenant_id=TENANT_ID,
        user=user,
    )

    assert result is True
    mock_check.assert_called_with(user, "agents", "delete")
    session.commit.assert_awaited_once()
    # Soft-delete sets status to "deleted" (no hard session.delete call)
    assert agent.status == "deleted"


@pytest.mark.asyncio
@patch("app.services.agent_service.check_permission")
async def test_agent_service_delete_not_found(mock_check: MagicMock) -> None:
    """AgentService.delete returns False when agent not found."""
    session = _mock_session()
    user = _mock_user()
    exec_result = MagicMock()
    exec_result.first.return_value = None
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentService.delete(
        session,
        AGENT_ID,
        tenant_id=TENANT_ID,
        user=user,
    )

    assert result is False
    mock_check.assert_called_once_with(user, "agents", "delete")


# ═══════════════════════════════════════════════════════════════════
# ExecutionService
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_execution_service_create() -> None:
    """create_execution sets status to queued and persists."""
    from app.services.execution_service import create_execution

    session = _mock_session()
    execution = Execution(agent_id=AGENT_ID, input_data={"msg": "hi"})
    session.refresh = AsyncMock()
    result = await create_execution(session, execution)
    assert result.status == "queued"
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_execution_service_get_found() -> None:
    """get_execution returns an execution when found."""
    from app.services.execution_service import get_execution

    session = _mock_session()
    ex_id = uuid4()
    execution = Execution(id=ex_id, agent_id=AGENT_ID, input_data={})
    session.get = AsyncMock(return_value=execution)
    result = await get_execution(session, ex_id)
    assert result is execution
    session.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_execution_service_get_not_found() -> None:
    """get_execution returns None when not found."""
    from app.services.execution_service import get_execution

    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await get_execution(session, uuid4())
    assert result is None
    session.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_execution_service_list() -> None:
    """list_executions returns paginated results."""
    from app.services.execution_service import list_executions

    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    executions, total = await list_executions(session, limit=10, offset=0)
    assert total == 0
    assert executions == []
    assert session.exec.await_count == 2


@pytest.mark.asyncio
async def test_execution_service_list_with_filters() -> None:
    """list_executions applies agent_id and status filters."""
    from app.services.execution_service import list_executions

    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    executions, total = await list_executions(
        session,
        agent_id=AGENT_ID,
        status="running",
        limit=5,
        offset=0,
    )
    assert total == 0
    assert executions == []
    assert session.exec.await_count == 2


@pytest.mark.asyncio
async def test_execution_service_update_found() -> None:
    """get_execution followed by field mutation persists status change."""
    from app.services.execution_service import get_execution

    session = _mock_session()
    ex_id = uuid4()
    execution = Execution(id=ex_id, agent_id=AGENT_ID, input_data={}, status="queued")
    session.get = AsyncMock(return_value=execution)
    session.refresh = AsyncMock()

    result = await get_execution(session, ex_id)
    assert result is not None
    result.status = "running"
    session.add(result)
    await session.commit()
    await session.refresh(result)

    assert result.status == "running"
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_execution_service_update_not_found() -> None:
    """get_execution returns None when execution does not exist."""
    from app.services.execution_service import get_execution

    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await get_execution(session, uuid4())
    assert result is None
    session.get.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════
# ModelService
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_model_service_create() -> None:
    """ModelService.create persists and returns the model."""
    session = _mock_session()
    model = Model(name="gpt-4", provider="openai", model_id="gpt-4", config={})
    session.refresh = AsyncMock()
    result = await ModelService.create(session, model)
    session.add.assert_called_once_with(model)
    session.commit.assert_awaited_once()
    assert result is model


@pytest.mark.asyncio
async def test_model_service_get_found() -> None:
    """ModelService.get returns a model when found."""
    session = _mock_session()
    mid = uuid4()
    model = Model(id=mid, name="m", provider="p", model_id="x", config={})
    session.get = AsyncMock(return_value=model)
    result = await ModelService.get(session, mid)
    assert result is model


@pytest.mark.asyncio
async def test_model_service_get_not_found() -> None:
    """ModelService.get returns None when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await ModelService.get(session, uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_model_service_list() -> None:
    """ModelService.list returns paginated results."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    models, total = await ModelService.list(session, limit=10, offset=0)
    assert total == 0


@pytest.mark.asyncio
async def test_model_service_list_with_filters() -> None:
    """ModelService.list applies provider and is_active filters."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    models, total = await ModelService.list(
        session,
        provider="openai",
        is_active=True,
        limit=5,
        offset=0,
    )
    assert total == 0


@pytest.mark.asyncio
async def test_model_service_update_found() -> None:
    """ModelService.update applies data and returns updated model."""
    session = _mock_session()
    mid = uuid4()
    model = Model(id=mid, name="old", provider="p", model_id="x", config={})
    session.get = AsyncMock(return_value=model)
    session.refresh = AsyncMock()

    result = await ModelService.update(session, mid, {"name": "new"})
    assert result is not None
    assert result.name == "new"


@pytest.mark.asyncio
async def test_model_service_update_not_found() -> None:
    """ModelService.update returns None when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await ModelService.update(session, uuid4(), {"name": "x"})
    assert result is None


@pytest.mark.asyncio
async def test_model_service_delete_found() -> None:
    """ModelService.delete returns True when model is deleted."""
    session = _mock_session()
    mid = uuid4()
    model = Model(id=mid, name="m", provider="p", model_id="x", config={})
    session.get = AsyncMock(return_value=model)
    result = await ModelService.delete(session, mid)
    assert result is True
    session.delete.assert_awaited_once_with(model)


@pytest.mark.asyncio
async def test_model_service_delete_not_found() -> None:
    """ModelService.delete returns False when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await ModelService.delete(session, uuid4())
    assert result is False


# ═══════════════════════════════════════════════════════════════════
# ConnectorService
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_connector_service_create() -> None:
    """ConnectorService.create persists and returns the connector."""
    session = _mock_session()
    conn = Connector(name="c", type="slack", config={}, owner_id=OWNER_ID)
    session.refresh = AsyncMock()
    result = await ConnectorService.create(session, conn)
    session.add.assert_called_once_with(conn)
    assert result is conn


@pytest.mark.asyncio
async def test_connector_service_get_found() -> None:
    """ConnectorService.get returns a connector when found."""
    session = _mock_session()
    cid = uuid4()
    conn = Connector(id=cid, name="c", type="t", config={}, owner_id=OWNER_ID)
    session.get = AsyncMock(return_value=conn)
    result = await ConnectorService.get(session, cid)
    assert result is conn


@pytest.mark.asyncio
async def test_connector_service_get_not_found() -> None:
    """ConnectorService.get returns None when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await ConnectorService.get(session, uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_connector_service_list() -> None:
    """ConnectorService.list returns paginated results."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    connectors, total = await ConnectorService.list(session, limit=10, offset=0)
    assert total == 0


@pytest.mark.asyncio
async def test_connector_service_list_with_filters() -> None:
    """ConnectorService.list applies owner_id, type, and status filters."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    connectors, total = await ConnectorService.list(
        session,
        owner_id=OWNER_ID,
        connector_type="slack",
        status="active",
        limit=5,
        offset=0,
    )
    assert total == 0


@pytest.mark.asyncio
async def test_connector_service_update_found() -> None:
    """ConnectorService.update applies data and returns updated connector."""
    session = _mock_session()
    cid = uuid4()
    conn = Connector(id=cid, name="old", type="t", config={}, owner_id=OWNER_ID)
    session.get = AsyncMock(return_value=conn)
    session.refresh = AsyncMock()

    result = await ConnectorService.update(session, cid, {"name": "new"})
    assert result is not None
    assert result.name == "new"


@pytest.mark.asyncio
async def test_connector_service_update_not_found() -> None:
    """ConnectorService.update returns None when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await ConnectorService.update(session, uuid4(), {"name": "x"})
    assert result is None


@pytest.mark.asyncio
async def test_connector_service_delete_found() -> None:
    """ConnectorService.delete returns True when connector is deleted."""
    session = _mock_session()
    cid = uuid4()
    conn = Connector(id=cid, name="c", type="t", config={}, owner_id=OWNER_ID)
    session.get = AsyncMock(return_value=conn)
    result = await ConnectorService.delete(session, cid)
    assert result is True
    session.delete.assert_awaited_once_with(conn)


@pytest.mark.asyncio
async def test_connector_service_delete_not_found() -> None:
    """ConnectorService.delete returns False when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await ConnectorService.delete(session, uuid4())
    assert result is False


# ═══════════════════════════════════════════════════════════════════
# AuditLogService
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_audit_log_service_create() -> None:
    """Direct AuditLog persistence works with all required fields."""
    session = _mock_session()
    session.refresh = AsyncMock()

    entry = AuditLog(
        actor_id=OWNER_ID,
        action="create",
        resource_type="agent",
        resource_id=str(AGENT_ID),
        details={"name": "test"},
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    session.add.assert_called_once_with(entry)
    session.commit.assert_awaited_once()
    session.refresh.assert_awaited_once_with(entry)
    assert isinstance(entry, AuditLog)
    assert entry.action == "create"
    assert entry.resource_type == "agent"
    assert entry.actor_id == OWNER_ID
    assert entry.details == {"name": "test"}


@pytest.mark.asyncio
async def test_audit_log_service_create_no_details() -> None:
    """AuditLog can be created with details=None."""
    session = _mock_session()
    session.refresh = AsyncMock()

    entry = AuditLog(
        actor_id=OWNER_ID,
        action="delete",
        resource_type="agent",
        resource_id=str(AGENT_ID),
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    assert entry.details is None
    assert entry.action == "delete"
    assert entry.actor_id == OWNER_ID
    assert entry.resource_type == "agent"
    assert entry.resource_id == str(AGENT_ID)


@pytest.mark.asyncio
async def test_audit_log_service_list_by_resource() -> None:
    """AuditLogService.list_by_resource returns paginated results."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    entries, total = await AuditLogService.list_by_resource(
        session,
        resource_type="agent",
        resource_id=AGENT_ID,
        limit=10,
        offset=0,
    )
    assert total == 0
    assert entries == []


@pytest.mark.asyncio
async def test_audit_log_service_list_by_actor() -> None:
    """AuditLogService.list_by_actor returns paginated results."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    entries, total = await AuditLogService.list_by_actor(
        session,
        actor_id=OWNER_ID,
        limit=10,
        offset=0,
    )
    assert total == 0


# ═══════════════════════════════════════════════════════════════════
# AgentVersionService
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_agent_version_service_create() -> None:
    """AgentVersionService.create persists and returns the version."""
    session = _mock_session()
    session.refresh = AsyncMock()
    version = AgentVersion(
        agent_id=AGENT_ID,
        version="1.0.0",
        definition={"model": "gpt-4"},
        created_by=OWNER_ID,
    )
    result = await AgentVersionService.create(session, version)
    session.add.assert_called_once_with(version)
    session.commit.assert_awaited_once()
    assert result is version


@pytest.mark.asyncio
async def test_agent_version_service_get_found() -> None:
    """AgentVersionService.get returns a version when found."""
    session = _mock_session()
    vid = uuid4()
    version = AgentVersion(
        id=vid,
        agent_id=AGENT_ID,
        version="1.0.0",
        definition={},
        created_by=OWNER_ID,
    )
    session.get = AsyncMock(return_value=version)
    result = await AgentVersionService.get(session, vid)
    assert result is version


@pytest.mark.asyncio
async def test_agent_version_service_get_not_found() -> None:
    """AgentVersionService.get returns None when not found."""
    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await AgentVersionService.get(session, uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_agent_version_service_list_by_agent() -> None:
    """AgentVersionService.list_by_agent returns paginated results."""
    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    versions, total = await AgentVersionService.list_by_agent(
        session,
        agent_id=AGENT_ID,
        limit=10,
        offset=0,
    )
    assert total == 0
    assert versions == []


@pytest.mark.asyncio
async def test_agent_version_service_get_latest_found() -> None:
    """AgentVersionService.get_latest returns the most recent version."""
    session = _mock_session()
    version = AgentVersion(
        agent_id=AGENT_ID,
        version="2.0.0",
        definition={},
        created_by=OWNER_ID,
    )
    exec_result = MagicMock()
    exec_result.first.return_value = version
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentVersionService.get_latest(session, AGENT_ID)
    assert result is version


@pytest.mark.asyncio
async def test_agent_version_service_get_latest_not_found() -> None:
    """AgentVersionService.get_latest returns None when no versions exist."""
    session = _mock_session()
    exec_result = MagicMock()
    exec_result.first.return_value = None
    session.exec = AsyncMock(return_value=exec_result)

    result = await AgentVersionService.get_latest(session, AGENT_ID)
    assert result is None


# ═══════════════════════════════════════════════════════════════════
# Backward-compatible module-level functions (agent_service)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_module_create_agent() -> None:
    """Module-level create_agent delegates to AgentService.create."""
    from app.services.agent_service import create_agent

    session = _mock_session()
    session.refresh = AsyncMock()
    agent = Agent(name="a", definition={}, owner_id=OWNER_ID)
    result = await create_agent(session, agent)
    assert result is agent


@pytest.mark.asyncio
async def test_module_get_agent() -> None:
    """Module-level get_agent delegates to AgentService.get."""
    from app.services.agent_service import get_agent

    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await get_agent(session, AGENT_ID)
    assert result is None


@pytest.mark.asyncio
async def test_module_list_agents() -> None:
    """Module-level list_agents delegates to AgentService.list."""
    from app.services.agent_service import list_agents

    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    agents, total = await list_agents(session, limit=10, offset=0)
    assert total == 0


@pytest.mark.asyncio
async def test_module_update_agent() -> None:
    """Module-level update_agent delegates to AgentService.update."""
    from app.services.agent_service import update_agent

    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await update_agent(session, AGENT_ID, {"name": "x"})
    assert result is None


@pytest.mark.asyncio
async def test_module_delete_agent() -> None:
    """Module-level delete_agent delegates to AgentService.delete."""
    from app.services.agent_service import delete_agent

    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await delete_agent(session, AGENT_ID)
    assert result is False


# ═══════════════════════════════════════════════════════════════════
# Backward-compatible module-level functions (execution_service)
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_module_create_execution() -> None:
    """Module-level create_execution delegates to ExecutionService.create."""
    from app.services.execution_service import create_execution

    session = _mock_session()
    session.refresh = AsyncMock()
    execution = Execution(agent_id=AGENT_ID, input_data={"msg": "hi"})
    result = await create_execution(session, execution)
    assert result.status == "queued"


@pytest.mark.asyncio
async def test_module_get_execution() -> None:
    """Module-level get_execution delegates to ExecutionService.get."""
    from app.services.execution_service import get_execution

    session = _mock_session()
    session.get = AsyncMock(return_value=None)
    result = await get_execution(session, uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_module_list_executions() -> None:
    """Module-level list_executions delegates to ExecutionService.list."""
    from app.services.execution_service import list_executions

    session = _mock_session()
    count_result = MagicMock()
    count_result.all.return_value = []
    page_result = MagicMock()
    page_result.all.return_value = []
    session.exec = AsyncMock(side_effect=[count_result, page_result])

    executions, total = await list_executions(session, limit=10, offset=0)
    assert total == 0
