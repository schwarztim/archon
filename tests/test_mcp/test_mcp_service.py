"""Unit tests for MCPService — sessions, components, interactions, and rendering.

Every DB interaction is mocked via AsyncSession so no real database is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.models.mcp import (
    COMPONENT_TYPES,
    MCPComponent,
    MCPInteraction,
    MCPSession,
)
from app.services.mcp import MCPService


# ── Constants (valid hex UUIDs only) ────────────────────────────────

SESSION_ID = UUID("aabbccdd-1122-3344-5566-778899aabbcc")
SESSION_ID_2 = UUID("11223344-aabb-ccdd-eeff-001122334455")
COMPONENT_ID = UUID("aabb0011-2233-4455-6677-8899aabbccdd")
COMPONENT_ID_2 = UUID("00112233-4455-6677-8899-aabbccddeeff")
INTERACTION_ID = UUID("ddeeff00-1122-3344-5566-778899001122")
AGENT_ID = UUID("aabb1122-3344-5566-7788-99aabbccddee")
USER_ID = UUID("ccddaabb-1122-3344-5566-778899001122")
MISSING_ID = UUID("00000000-aaaa-bbbb-cccc-ddddeeeeffff")


# ── Factories ───────────────────────────────────────────────────────


def _make_session(
    *,
    session_id: UUID = SESSION_ID,
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
    status: str = "active",
    extra_metadata: dict[str, Any] | None = None,
) -> MCPSession:
    """Factory for MCPSession instances."""
    return MCPSession(
        id=session_id,
        agent_id=agent_id,
        user_id=user_id,
        status=status,
        extra_metadata=extra_metadata or {},
    )


def _make_component(
    *,
    component_id: UUID = COMPONENT_ID,
    session_id: UUID = SESSION_ID,
    component_type: str = "form",
    props: dict[str, Any] | None = None,
    state: str = "mounted",
    extra_metadata: dict[str, Any] | None = None,
) -> MCPComponent:
    """Factory for MCPComponent instances."""
    return MCPComponent(
        id=component_id,
        session_id=session_id,
        component_type=component_type,
        props=props or {},
        state=state,
        extra_metadata=extra_metadata or {},
    )


def _make_interaction(
    *,
    interaction_id: UUID = INTERACTION_ID,
    session_id: UUID = SESSION_ID,
    component_id: UUID = COMPONENT_ID,
    event_type: str = "onClick",
    payload: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> MCPInteraction:
    """Factory for MCPInteraction instances."""
    return MCPInteraction(
        id=interaction_id,
        session_id=session_id,
        component_id=component_id,
        event_type=event_type,
        payload=payload or {},
        extra_metadata=extra_metadata or {},
    )


# ── Mock helpers ────────────────────────────────────────────────────


def _mock_db() -> AsyncMock:
    """Return a fully-mocked AsyncSession with common methods."""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.get = AsyncMock()
    db.exec = AsyncMock()
    return db


def _mock_exec_result(rows: list[Any]) -> MagicMock:
    """Create a mock result object returned by session.exec()."""
    result = MagicMock()
    result.all.return_value = rows
    result.first.return_value = rows[0] if rows else None
    return result


# ═══════════════════════════════════════════════════════════════════
#  Session Management Tests
# ═══════════════════════════════════════════════════════════════════


class TestCreateSession:
    """Tests for MCPService.create_session."""

    @pytest.mark.asyncio
    async def test_create_session_minimal(self) -> None:
        """Create session with no optional fields."""
        db = _mock_db()

        async def _refresh(obj: Any) -> None:
            obj.id = SESSION_ID

        db.refresh.side_effect = _refresh

        result = await MCPService.create_session(session=db)

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()
        assert isinstance(result, MCPSession)
        assert result.status == "active"
        assert result.extra_metadata == {}

    @pytest.mark.asyncio
    async def test_create_session_with_all_fields(self) -> None:
        """Create session with agent_id, user_id, and metadata."""
        db = _mock_db()
        meta = {"source": "test"}

        result = await MCPService.create_session(
            session=db,
            agent_id=AGENT_ID,
            user_id=USER_ID,
            extra_metadata=meta,
        )

        assert result.agent_id == AGENT_ID
        assert result.user_id == USER_ID
        assert result.extra_metadata == meta
        db.commit.assert_awaited_once()


class TestGetSession:
    """Tests for MCPService.get_session."""

    @pytest.mark.asyncio
    async def test_get_session_found(self) -> None:
        """Return session when it exists."""
        db = _mock_db()
        expected = _make_session()
        db.get.return_value = expected

        result = await MCPService.get_session(db, SESSION_ID)

        db.get.assert_awaited_once_with(MCPSession, SESSION_ID)
        assert result is expected

    @pytest.mark.asyncio
    async def test_get_session_not_found(self) -> None:
        """Return None when session does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await MCPService.get_session(db, MISSING_ID)

        assert result is None


class TestCloseSession:
    """Tests for MCPService.close_session."""

    @pytest.mark.asyncio
    async def test_close_session_success(self) -> None:
        """Close an existing active session."""
        db = _mock_db()
        mcp_session = _make_session(status="active")
        db.get.return_value = mcp_session

        result = await MCPService.close_session(db, SESSION_ID)

        assert result is not None
        assert result.status == "closed"
        assert result.closed_at is not None
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_session_not_found(self) -> None:
        """Return None when session not found."""
        db = _mock_db()
        db.get.return_value = None

        result = await MCPService.close_session(db, MISSING_ID)

        assert result is None
        db.commit.assert_not_awaited()


class TestListSessions:
    """Tests for MCPService.list_sessions."""

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self) -> None:
        """Return empty list and zero total when no sessions."""
        db = _mock_db()
        empty_result = _mock_exec_result([])
        db.exec.return_value = empty_result

        sessions, total = await MCPService.list_sessions(session=db)

        assert sessions == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_sessions_with_results(self) -> None:
        """Return sessions and correct total."""
        db = _mock_db()
        s1 = _make_session(session_id=SESSION_ID)
        s2 = _make_session(session_id=SESSION_ID_2)
        # First exec call for count, second for paginated results
        count_result = _mock_exec_result([s1, s2])
        page_result = _mock_exec_result([s1, s2])
        db.exec.side_effect = [count_result, page_result]

        sessions, total = await MCPService.list_sessions(session=db)

        assert total == 2
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_with_status_filter(self) -> None:
        """Filter by status works without errors."""
        db = _mock_db()
        s1 = _make_session(status="active")
        count_result = _mock_exec_result([s1])
        page_result = _mock_exec_result([s1])
        db.exec.side_effect = [count_result, page_result]

        sessions, total = await MCPService.list_sessions(session=db, status="active")

        assert total == 1
        assert len(sessions) == 1

    @pytest.mark.asyncio
    async def test_list_sessions_with_agent_filter(self) -> None:
        """Filter by agent_id works without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        sessions, total = await MCPService.list_sessions(
            session=db, agent_id=AGENT_ID
        )

        assert total == 0
        assert sessions == []

    @pytest.mark.asyncio
    async def test_list_sessions_pagination(self) -> None:
        """Limit and offset are accepted without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        sessions, total = await MCPService.list_sessions(
            session=db, limit=5, offset=10
        )

        assert total == 0


# ═══════════════════════════════════════════════════════════════════
#  Component Management Tests
# ═══════════════════════════════════════════════════════════════════


class TestCreateComponent:
    """Tests for MCPService.create_component."""

    @pytest.mark.asyncio
    async def test_create_component_success(self) -> None:
        """Create a form component in an active session."""
        db = _mock_db()
        active_session = _make_session(status="active")
        db.get.return_value = active_session

        result = await MCPService.create_component(
            session=db,
            session_id=SESSION_ID,
            component_type="form",
            props={"fields": ["name", "email"]},
        )

        db.add.assert_called_once()
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()
        assert isinstance(result, MCPComponent)
        assert result.component_type == "form"
        assert result.props == {"fields": ["name", "email"]}

    @pytest.mark.asyncio
    async def test_create_component_all_valid_types(self) -> None:
        """All COMPONENT_TYPES are accepted."""
        for ctype in sorted(COMPONENT_TYPES):
            db = _mock_db()
            active_session = _make_session(status="active")
            db.get.return_value = active_session

            result = await MCPService.create_component(
                session=db,
                session_id=SESSION_ID,
                component_type=ctype,
            )

            assert result.component_type == ctype

    @pytest.mark.asyncio
    async def test_create_component_invalid_type(self) -> None:
        """Raise ValueError for invalid component_type."""
        db = _mock_db()

        with pytest.raises(ValueError, match="Invalid component_type"):
            await MCPService.create_component(
                session=db,
                session_id=SESSION_ID,
                component_type="invalid_widget",
            )

        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_component_session_not_found(self) -> None:
        """Raise ValueError when session does not exist."""
        db = _mock_db()
        db.get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await MCPService.create_component(
                session=db,
                session_id=MISSING_ID,
                component_type="form",
            )

    @pytest.mark.asyncio
    async def test_create_component_session_not_active(self) -> None:
        """Raise ValueError when session is closed."""
        db = _mock_db()
        closed_session = _make_session(status="closed")
        db.get.return_value = closed_session

        with pytest.raises(ValueError, match="not active"):
            await MCPService.create_component(
                session=db,
                session_id=SESSION_ID,
                component_type="form",
            )

    @pytest.mark.asyncio
    async def test_create_component_defaults(self) -> None:
        """Props and extra_metadata default to empty dicts."""
        db = _mock_db()
        db.get.return_value = _make_session(status="active")

        result = await MCPService.create_component(
            session=db,
            session_id=SESSION_ID,
            component_type="text",
        )

        assert result.props == {}
        assert result.extra_metadata == {}

    @pytest.mark.asyncio
    async def test_create_component_with_metadata(self) -> None:
        """Extra metadata is stored on the component."""
        db = _mock_db()
        db.get.return_value = _make_session(status="active")
        meta = {"version": "1.0", "author": "test"}

        result = await MCPService.create_component(
            session=db,
            session_id=SESSION_ID,
            component_type="chart",
            extra_metadata=meta,
        )

        assert result.extra_metadata == meta


class TestGetComponent:
    """Tests for MCPService.get_component."""

    @pytest.mark.asyncio
    async def test_get_component_found(self) -> None:
        """Return component when it exists."""
        db = _mock_db()
        expected = _make_component()
        db.get.return_value = expected

        result = await MCPService.get_component(db, COMPONENT_ID)

        db.get.assert_awaited_once_with(MCPComponent, COMPONENT_ID)
        assert result is expected

    @pytest.mark.asyncio
    async def test_get_component_not_found(self) -> None:
        """Return None when component does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await MCPService.get_component(db, MISSING_ID)

        assert result is None


class TestUpdateComponent:
    """Tests for MCPService.update_component."""

    @pytest.mark.asyncio
    async def test_update_component_success(self) -> None:
        """Update props on an existing component."""
        db = _mock_db()
        component = _make_component(props={"old": True})
        db.get.return_value = component

        result = await MCPService.update_component(
            db, COMPONENT_ID, {"props": {"new": True}}
        )

        assert result is not None
        assert result.props == {"new": True}
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_component_state_change(self) -> None:
        """Update the state of a component."""
        db = _mock_db()
        component = _make_component(state="mounted")
        db.get.return_value = component

        result = await MCPService.update_component(
            db, COMPONENT_ID, {"state": "updated"}
        )

        assert result is not None
        assert result.state == "updated"

    @pytest.mark.asyncio
    async def test_update_component_not_found(self) -> None:
        """Return None when component does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await MCPService.update_component(
            db, MISSING_ID, {"props": {"x": 1}}
        )

        assert result is None
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_update_component_ignores_unknown_keys(self) -> None:
        """Keys not present as attributes are silently ignored."""
        db = _mock_db()
        component = _make_component()
        db.get.return_value = component

        result = await MCPService.update_component(
            db, COMPONENT_ID, {"nonexistent_field": "value"}
        )

        assert result is not None
        assert not hasattr(result, "nonexistent_field") or getattr(result, "nonexistent_field", None) != "value"

    @pytest.mark.asyncio
    async def test_update_component_sets_updated_at(self) -> None:
        """updated_at is refreshed on update."""
        db = _mock_db()
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        component = _make_component()
        component.updated_at = old_time
        db.get.return_value = component

        result = await MCPService.update_component(
            db, COMPONENT_ID, {"props": {"a": 1}}
        )

        assert result is not None
        assert result.updated_at > old_time


class TestDeleteComponent:
    """Tests for MCPService.delete_component."""

    @pytest.mark.asyncio
    async def test_delete_component_success(self) -> None:
        """Return True when component is deleted."""
        db = _mock_db()
        component = _make_component()
        db.get.return_value = component

        result = await MCPService.delete_component(db, COMPONENT_ID)

        assert result is True
        db.delete.assert_awaited_once_with(component)
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_component_not_found(self) -> None:
        """Return False when component does not exist."""
        db = _mock_db()
        db.get.return_value = None

        result = await MCPService.delete_component(db, MISSING_ID)

        assert result is False
        db.delete.assert_not_awaited()
        db.commit.assert_not_awaited()


class TestListComponents:
    """Tests for MCPService.list_components."""

    @pytest.mark.asyncio
    async def test_list_components_empty(self) -> None:
        """Return empty list and zero total."""
        db = _mock_db()
        empty = _mock_exec_result([])
        db.exec.return_value = empty

        components, total = await MCPService.list_components(session=db)

        assert components == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_components_with_results(self) -> None:
        """Return components and correct total."""
        db = _mock_db()
        c1 = _make_component(component_id=COMPONENT_ID)
        c2 = _make_component(component_id=COMPONENT_ID_2)
        count_result = _mock_exec_result([c1, c2])
        page_result = _mock_exec_result([c1, c2])
        db.exec.side_effect = [count_result, page_result]

        components, total = await MCPService.list_components(session=db)

        assert total == 2
        assert len(components) == 2

    @pytest.mark.asyncio
    async def test_list_components_filter_by_session(self) -> None:
        """Filter by session_id accepted without errors."""
        db = _mock_db()
        c1 = _make_component()
        count_result = _mock_exec_result([c1])
        page_result = _mock_exec_result([c1])
        db.exec.side_effect = [count_result, page_result]

        components, total = await MCPService.list_components(
            session=db, session_id=SESSION_ID
        )

        assert total == 1

    @pytest.mark.asyncio
    async def test_list_components_filter_by_type(self) -> None:
        """Filter by component_type accepted without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        components, total = await MCPService.list_components(
            session=db, component_type="chart"
        )

        assert total == 0

    @pytest.mark.asyncio
    async def test_list_components_filter_by_state(self) -> None:
        """Filter by state accepted without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        components, total = await MCPService.list_components(
            session=db, state="mounted"
        )

        assert total == 0

    @pytest.mark.asyncio
    async def test_list_components_pagination(self) -> None:
        """Limit and offset are forwarded without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        components, total = await MCPService.list_components(
            session=db, limit=10, offset=5
        )

        assert total == 0


# ═══════════════════════════════════════════════════════════════════
#  Rendering Tests
# ═══════════════════════════════════════════════════════════════════


class TestRenderComponent:
    """Tests for MCPService.render_component."""

    @pytest.mark.asyncio
    async def test_render_component_success(self) -> None:
        """Render a mounted component into a WebSocket-ready payload."""
        db = _mock_db()
        component = _make_component(
            component_id=COMPONENT_ID,
            component_type="form",
            props={"fields": ["name"]},
            state="mounted",
            extra_metadata={"version": "1"},
        )
        db.get.return_value = component

        result = await MCPService.render_component(db, COMPONENT_ID)

        assert result["type"] == "component"
        assert result["component"] == "form"
        assert result["props"] == {"fields": ["name"]}
        assert result["id"] == str(COMPONENT_ID)
        assert result["state"] == "mounted"
        assert result["extra_metadata"] == {"version": "1"}

    @pytest.mark.asyncio
    async def test_render_component_updated_state(self) -> None:
        """Render works for components in 'updated' state."""
        db = _mock_db()
        component = _make_component(state="updated")
        db.get.return_value = component

        result = await MCPService.render_component(db, COMPONENT_ID)

        assert result["state"] == "updated"

    @pytest.mark.asyncio
    async def test_render_component_not_found(self) -> None:
        """Raise ValueError when component does not exist."""
        db = _mock_db()
        db.get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await MCPService.render_component(db, MISSING_ID)

    @pytest.mark.asyncio
    async def test_render_component_unmounted(self) -> None:
        """Raise ValueError when component is unmounted."""
        db = _mock_db()
        component = _make_component(state="unmounted")
        db.get.return_value = component

        with pytest.raises(ValueError, match="unmounted"):
            await MCPService.render_component(db, COMPONENT_ID)


# ═══════════════════════════════════════════════════════════════════
#  Interaction Handling Tests
# ═══════════════════════════════════════════════════════════════════


class TestHandleInteraction:
    """Tests for MCPService.handle_interaction."""

    @pytest.mark.asyncio
    async def test_handle_interaction_success(self) -> None:
        """Record a valid interaction on a mounted component."""
        db = _mock_db()
        active_session = _make_session(status="active")
        component = _make_component(state="mounted")

        def _get_side_effect(model: type, id_: UUID) -> Any:
            if model is MCPSession:
                return active_session
            if model is MCPComponent:
                return component
            return None

        db.get.side_effect = _get_side_effect

        result = await MCPService.handle_interaction(
            session=db,
            session_id=SESSION_ID,
            component_id=COMPONENT_ID,
            event_type="onClick",
            payload={"x": 100, "y": 200},
        )

        assert isinstance(result, MCPInteraction)
        assert result.event_type == "onClick"
        assert result.payload == {"x": 100, "y": 200}
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_interaction_with_metadata(self) -> None:
        """Extra metadata is stored on the interaction."""
        db = _mock_db()
        active_session = _make_session(status="active")
        component = _make_component(state="mounted")

        def _get_side_effect(model: type, id_: UUID) -> Any:
            if model is MCPSession:
                return active_session
            if model is MCPComponent:
                return component
            return None

        db.get.side_effect = _get_side_effect
        meta = {"browser": "Chrome"}

        result = await MCPService.handle_interaction(
            session=db,
            session_id=SESSION_ID,
            component_id=COMPONENT_ID,
            event_type="onSubmit",
            extra_metadata=meta,
        )

        assert result.extra_metadata == meta

    @pytest.mark.asyncio
    async def test_handle_interaction_session_not_found(self) -> None:
        """Raise ValueError when session does not exist."""
        db = _mock_db()
        db.get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await MCPService.handle_interaction(
                session=db,
                session_id=MISSING_ID,
                component_id=COMPONENT_ID,
                event_type="onClick",
            )

    @pytest.mark.asyncio
    async def test_handle_interaction_session_not_active(self) -> None:
        """Raise ValueError when session is closed."""
        db = _mock_db()
        closed_session = _make_session(status="closed")
        db.get.return_value = closed_session

        with pytest.raises(ValueError, match="not active"):
            await MCPService.handle_interaction(
                session=db,
                session_id=SESSION_ID,
                component_id=COMPONENT_ID,
                event_type="onClick",
            )

    @pytest.mark.asyncio
    async def test_handle_interaction_component_not_found(self) -> None:
        """Raise ValueError when component does not exist."""
        db = _mock_db()
        active_session = _make_session(status="active")

        def _get_side_effect(model: type, id_: UUID) -> Any:
            if model is MCPSession:
                return active_session
            return None

        db.get.side_effect = _get_side_effect

        with pytest.raises(ValueError, match="not found"):
            await MCPService.handle_interaction(
                session=db,
                session_id=SESSION_ID,
                component_id=MISSING_ID,
                event_type="onClick",
            )

    @pytest.mark.asyncio
    async def test_handle_interaction_component_unmounted(self) -> None:
        """Raise ValueError when component is unmounted."""
        db = _mock_db()
        active_session = _make_session(status="active")
        unmounted = _make_component(state="unmounted")

        def _get_side_effect(model: type, id_: UUID) -> Any:
            if model is MCPSession:
                return active_session
            if model is MCPComponent:
                return unmounted
            return None

        db.get.side_effect = _get_side_effect

        with pytest.raises(ValueError, match="unmounted"):
            await MCPService.handle_interaction(
                session=db,
                session_id=SESSION_ID,
                component_id=COMPONENT_ID,
                event_type="onClick",
            )

    @pytest.mark.asyncio
    async def test_handle_interaction_defaults(self) -> None:
        """Payload and extra_metadata default to empty dicts."""
        db = _mock_db()
        active_session = _make_session(status="active")
        component = _make_component(state="mounted")

        def _get_side_effect(model: type, id_: UUID) -> Any:
            if model is MCPSession:
                return active_session
            if model is MCPComponent:
                return component
            return None

        db.get.side_effect = _get_side_effect

        result = await MCPService.handle_interaction(
            session=db,
            session_id=SESSION_ID,
            component_id=COMPONENT_ID,
            event_type="onChange",
        )

        assert result.payload == {}
        assert result.extra_metadata == {}


class TestListInteractions:
    """Tests for MCPService.list_interactions."""

    @pytest.mark.asyncio
    async def test_list_interactions_empty(self) -> None:
        """Return empty list and zero total."""
        db = _mock_db()
        empty = _mock_exec_result([])
        db.exec.return_value = empty

        interactions, total = await MCPService.list_interactions(session=db)

        assert interactions == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_interactions_with_results(self) -> None:
        """Return interactions and correct total."""
        db = _mock_db()
        i1 = _make_interaction()
        count_result = _mock_exec_result([i1])
        page_result = _mock_exec_result([i1])
        db.exec.side_effect = [count_result, page_result]

        interactions, total = await MCPService.list_interactions(session=db)

        assert total == 1
        assert len(interactions) == 1

    @pytest.mark.asyncio
    async def test_list_interactions_filter_by_session(self) -> None:
        """Filter by session_id accepted without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        interactions, total = await MCPService.list_interactions(
            session=db, session_id=SESSION_ID
        )

        assert total == 0

    @pytest.mark.asyncio
    async def test_list_interactions_filter_by_component(self) -> None:
        """Filter by component_id accepted without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        interactions, total = await MCPService.list_interactions(
            session=db, component_id=COMPONENT_ID
        )

        assert total == 0

    @pytest.mark.asyncio
    async def test_list_interactions_filter_by_event_type(self) -> None:
        """Filter by event_type accepted without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        interactions, total = await MCPService.list_interactions(
            session=db, event_type="onClick"
        )

        assert total == 0

    @pytest.mark.asyncio
    async def test_list_interactions_pagination(self) -> None:
        """Limit and offset are forwarded without errors."""
        db = _mock_db()
        count_result = _mock_exec_result([])
        page_result = _mock_exec_result([])
        db.exec.side_effect = [count_result, page_result]

        interactions, total = await MCPService.list_interactions(
            session=db, limit=5, offset=10
        )

        assert total == 0


# ═══════════════════════════════════════════════════════════════════
#  Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge-case and boundary tests."""

    @pytest.mark.asyncio
    async def test_create_component_expired_session(self) -> None:
        """Raise ValueError when session is expired (not just closed)."""
        db = _mock_db()
        expired = _make_session(status="expired")
        db.get.return_value = expired

        with pytest.raises(ValueError, match="not active"):
            await MCPService.create_component(
                session=db,
                session_id=SESSION_ID,
                component_type="table",
            )

    @pytest.mark.asyncio
    async def test_handle_interaction_expired_session(self) -> None:
        """Raise ValueError when session is expired."""
        db = _mock_db()
        expired = _make_session(status="expired")
        db.get.return_value = expired

        with pytest.raises(ValueError, match="not active"):
            await MCPService.handle_interaction(
                session=db,
                session_id=SESSION_ID,
                component_id=COMPONENT_ID,
                event_type="onClick",
            )

    @pytest.mark.asyncio
    async def test_render_component_returns_string_id(self) -> None:
        """The rendered id field is always a string, not UUID."""
        db = _mock_db()
        component = _make_component(component_id=COMPONENT_ID)
        db.get.return_value = component

        result = await MCPService.render_component(db, COMPONENT_ID)

        assert isinstance(result["id"], str)

    @pytest.mark.asyncio
    async def test_create_session_none_metadata_becomes_empty(self) -> None:
        """Passing None for extra_metadata stores empty dict."""
        db = _mock_db()

        result = await MCPService.create_session(
            session=db, extra_metadata=None
        )

        assert result.extra_metadata == {}

    @pytest.mark.asyncio
    async def test_component_types_constant(self) -> None:
        """COMPONENT_TYPES has the expected members."""
        assert COMPONENT_TYPES == frozenset(
            {"form", "chart", "table", "text", "code", "image"}
        )
