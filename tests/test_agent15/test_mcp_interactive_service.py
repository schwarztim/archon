"""Tests for MCPInteractiveService — sessions, rendering, actions, and component types."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.mcp_interactive import (
    ActionResult,
    ComponentAction,
    ComponentCategory,
    ComponentConfig,
    ComponentSession,
    ComponentType,
    RenderedComponent,
)
from app.services.mcp_interactive_service import (
    MCPInteractiveService,
    _sessions,
    _component_types,
    _update_queues,
)

# ── Fixtures ────────────────────────────────────────────────────────

TENANT = "tenant-interactive-test"


def _user(**overrides: Any) -> MagicMock:
    u = MagicMock()
    u.id = overrides.get("id", str(uuid4()))
    u.roles = overrides.get("roles", ["admin"])
    u.permissions = overrides.get("permissions", ["read", "write"])
    return u


@pytest.fixture(autouse=True)
def _clear_stores() -> None:
    """Reset in-memory stores between tests."""
    _sessions.clear()
    _component_types.clear()
    _update_queues.clear()


# ── create_component_session ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_component_session_returns_active_session() -> None:
    user = _user()
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.CHART,
    )
    assert isinstance(session, ComponentSession)
    assert session.status == "active"
    assert session.tenant_id == TENANT
    assert session.user_id == user.id


@pytest.mark.asyncio
async def test_create_component_session_caches_permissions() -> None:
    user = _user(permissions=["agents:read", "agents:write"])
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.FORM,
    )
    assert session.permissions == ["agents:read", "agents:write"]


@pytest.mark.asyncio
async def test_create_session_stores_in_tenant_map() -> None:
    user = _user()
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.TABLE,
    )
    assert session.session_id in _sessions[TENANT]


# ── get_session ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_existing() -> None:
    user = _user()
    created = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.CHART,
    )
    fetched = await MCPInteractiveService.get_session(TENANT, created.session_id)
    assert fetched.session_id == created.session_id


@pytest.mark.asyncio
async def test_get_session_not_found_raises() -> None:
    with pytest.raises(ValueError, match="not found"):
        await MCPInteractiveService.get_session(TENANT, uuid4())


# ── render_component ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_component_returns_html_with_csp_nonce() -> None:
    user = _user()
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.CHART,
    )
    config = ComponentConfig(type=ComponentCategory.CHART, data_source="metrics")
    rendered = await MCPInteractiveService.render_component(
        TENANT, user, session.session_id, config,
    )
    assert isinstance(rendered, RenderedComponent)
    assert rendered.csp_nonce != ""
    assert "data-nonce" in rendered.html_content


@pytest.mark.asyncio
async def test_render_component_admin_gets_full_rbac() -> None:
    user = _user(roles=["admin"])
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.FORM,
    )
    config = ComponentConfig(
        type=ComponentCategory.FORM,
        display_options={"theme": "dark"},
    )
    rendered = await MCPInteractiveService.render_component(
        TENANT, user, session.session_id, config,
    )
    assert rendered.data["rbac_level"] == "full"
    assert "display_options" in rendered.data


@pytest.mark.asyncio
async def test_render_component_non_admin_restricted() -> None:
    user = _user(roles=["viewer"])
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.CHART,
    )
    config = ComponentConfig(type=ComponentCategory.CHART)
    rendered = await MCPInteractiveService.render_component(
        TENANT, user, session.session_id, config,
    )
    assert rendered.data["rbac_level"] == "restricted"
    assert "display_options" not in rendered.data


@pytest.mark.asyncio
async def test_render_component_wrong_user_raises() -> None:
    owner = _user()
    other = _user()
    session = await MCPInteractiveService.create_component_session(
        TENANT, owner, ComponentCategory.CHART,
    )
    config = ComponentConfig(type=ComponentCategory.CHART)
    with pytest.raises(ValueError, match="does not belong"):
        await MCPInteractiveService.render_component(
            TENANT, other, session.session_id, config,
        )


# ── handle_component_action ────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_action_success() -> None:
    user = _user()
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.APPROVAL,
    )
    action = ComponentAction(
        session_id=session.session_id,
        action_type="button_click",
        payload={"button": "approve"},
    )
    result = await MCPInteractiveService.handle_component_action(
        TENANT, user, session.session_id, action,
    )
    assert isinstance(result, ActionResult)
    assert result.success is True
    assert result.data["action_type"] == "button_click"


@pytest.mark.asyncio
async def test_handle_action_enqueues_update() -> None:
    user = _user()
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.TABLE,
    )
    action = ComponentAction(
        session_id=session.session_id,
        action_type="sort",
        payload={"column": "name"},
    )
    await MCPInteractiveService.handle_component_action(
        TENANT, user, session.session_id, action,
    )
    queue = _update_queues[TENANT][session.session_id]
    assert len(queue) == 1
    assert queue[0]["action_type"] == "sort"


# ── register_component_type / list_component_types ──────────────────


@pytest.mark.asyncio
async def test_register_component_type_admin() -> None:
    user = _user(roles=["admin"])
    comp_def = ComponentType(name="CustomChart", category=ComponentCategory.CHART)
    result = await MCPInteractiveService.register_component_type(TENANT, user, comp_def)
    assert result.tenant_id == TENANT
    assert result.created_by == user.id


@pytest.mark.asyncio
async def test_register_component_type_non_admin_raises() -> None:
    user = _user(roles=["viewer"])
    comp_def = ComponentType(name="Blocked", category=ComponentCategory.TABLE)
    with pytest.raises(ValueError, match="Only admins"):
        await MCPInteractiveService.register_component_type(TENANT, user, comp_def)


@pytest.mark.asyncio
async def test_list_component_types_returns_registered() -> None:
    user = _user(roles=["admin"])
    comp_def = ComponentType(name="ListTest", category=ComponentCategory.MAP)
    await MCPInteractiveService.register_component_type(TENANT, user, comp_def)
    types = await MCPInteractiveService.list_component_types(TENANT)
    assert len(types) >= 1
    assert any(t.name == "ListTest" for t in types)


# ── close_session ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_session_marks_closed() -> None:
    user = _user()
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.TIMELINE,
    )
    await MCPInteractiveService.close_session(TENANT, session.session_id)
    assert _sessions[TENANT][session.session_id].status == "closed"


@pytest.mark.asyncio
async def test_close_session_removes_queue() -> None:
    user = _user()
    session = await MCPInteractiveService.create_component_session(
        TENANT, user, ComponentCategory.CODE_EDITOR,
    )
    await MCPInteractiveService.close_session(TENANT, session.session_id)
    assert session.session_id not in _update_queues.get(TENANT, {})
